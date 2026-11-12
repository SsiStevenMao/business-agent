import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from business_agent.agent import BusinessAgent
from business_agent.database import initialize_database
from business_agent.llm import OllamaModel
from business_agent.roles import ROLES
from business_agent.seed import seed_database


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "business.db"
        initialize_database(self.database_path)
        seed_database(self.database_path, order_count=1)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_business_query_runs_sql_generated_by_model(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        sql_query = "SELECT first_name, last_name FROM customers ORDER BY id LIMIT 2"
        agent = BusinessAgent(
            self.database_path,
            model,
            ROLES["customer_support"],
        )

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": sql_query,
                "answer": "",
            },
        ) as route_request:
            sql, answer = agent.answer("Show two customer names")

        self.assertIn("查询结果", answer)
        self.assertIn("| first_name | last_name |", answer)
        table_rows = [line for line in answer.splitlines() if line.startswith("| ")]
        self.assertEqual(len(table_rows) - 2, 2)
        self.assertEqual(sql, sql_query)
        route_request.assert_called_once()
        prompt = route_request.call_args.args[1]
        self.assertIn("general：用户在问候、闲聊、问一般知识", prompt)
        self.assertIn("业务查询", prompt)

    def test_all_orders_prompt_does_not_instruct_model_to_limit_to_50(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])
        sql_query = "SELECT * FROM orders"

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": sql_query,
                "answer": "",
            },
        ) as route_request:
            sql, _ = agent.answer("给我返回所有订单")

        prompt = route_request.call_args.args[1]
        self.assertIn("用户要求“所有订单”", prompt)
        self.assertIn("完整列表时可直接查询", prompt)
        self.assertIn("“所有/全部”及未指定条数时不添加固定 LIMIT", prompt)
        self.assertEqual(sql, sql_query)

    def test_reports_empty_query_results(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(
            self.database_path,
            model,
            ROLES["customer_support"],
        )

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": "SELECT first_name FROM customers WHERE id = -1",
                "answer": "",
            },
        ):
            _, answer = agent.answer("Find a missing customer")

        self.assertEqual(answer, "没有查到匹配的数据。")

    def test_non_admin_greeting_is_rejected_without_calling_model(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["customer_support"])

        with patch.object(model, "route_request") as route_request:
            sql, answer = agent.answer("你好")

        self.assertEqual(sql, "")
        self.assertIn("管理员", answer)
        route_request.assert_not_called()

    def test_admin_can_answer_general_questions(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "general",
                "sql": "",
                "answer": "你好！",
            },
        ) as route_request:
            sql, answer = agent.answer("你好")

        self.assertEqual(sql, "")
        self.assertEqual(answer, "你好！")
        route_request.assert_called_once()

    def test_non_admin_business_query_still_calls_model(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["customer_support"])
        sql_query = "SELECT first_name FROM customers LIMIT 1"

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": sql_query,
                "answer": "",
            },
        ) as route_request:
            sql, answer = agent.answer("Show one customer")

        self.assertEqual(sql, sql_query)
        self.assertIn("查询结果", answer)
        route_request.assert_called_once()

    def test_non_admin_cannot_return_general_answer_for_business_looking_question(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["customer_support"])

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "general",
                "sql": "",
                "answer": "There are 50 customers.",
            },
        ) as route_request:
            sql, answer = agent.answer("How many customers are in the database?")

        self.assertEqual(sql, "")
        self.assertIn("admin role", answer)
        route_request.assert_called_once()

    def test_admin_live_market_question_does_not_invent_current_data(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with patch.object(model, "route_request") as route_request:
            sql, answer = agent.answer("今天每股怎么样？")

        self.assertEqual(sql, "")
        self.assertIn("没有接入实时行情", answer)
        route_request.assert_not_called()

    def test_admin_market_performance_question_without_time_is_not_sent_to_model(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with patch.object(model, "route_request") as route_request:
            sql, answer = agent.answer("美股表现怎么样？")

        self.assertEqual(sql, "")
        self.assertIn("没有接入实时行情", answer)
        route_request.assert_not_called()

    def test_non_admin_live_market_question_is_rejected_without_model_call(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])

        with patch.object(model, "route_request") as route_request:
            sql, answer = agent.answer("今天每股怎么样？")

        self.assertEqual(sql, "")
        self.assertIn("管理员", answer)
        route_request.assert_not_called()

    def test_ambiguous_recent_query_asks_for_target_and_time_range(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with (
            patch.object(model, "route_request") as route_request,
            patch("business_agent.agent.execute_read_query") as execute_read_query,
        ):
            sql, answer = agent.answer("查一下最近的")

        self.assertEqual(sql, "")
        self.assertIn("订单", answer)
        self.assertIn("产品", answer)
        self.assertIn("时间范围", answer)
        execute_read_query.assert_not_called()
        route_request.assert_not_called()

    def test_recent_orders_query_clarifies_missing_time_range(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with (
            patch.object(model, "route_request") as route_request,
            patch("business_agent.agent.execute_read_query") as execute_read_query,
        ):
            sql, answer = agent.answer("查一下最近的订单")

        self.assertEqual(sql, "")
        self.assertIn("时间范围", answer)
        self.assertNotIn("哪类业务数据", answer)
        execute_read_query.assert_not_called()
        route_request.assert_not_called()

    def test_sales_performance_clarifies_missing_metric_and_time_range(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with (
            patch.object(model, "route_request") as route_request,
            patch("business_agent.agent.execute_read_query") as execute_read_query,
        ):
            sql, answer = agent.answer("查销售表现")

        self.assertEqual(sql, "")
        self.assertIn("销售指标", answer)
        self.assertIn("时间范围", answer)
        route_request.assert_not_called()
        execute_read_query.assert_not_called()

    def test_recent_sales_performance_clarifies_metric_and_time_together(self) -> None:
        question = "查最近销售表现"
        clarification = BusinessAgent._sales_scope_clarification(question)
        self.assertIsNotNone(clarification)
        self.assertIn("销售指标", clarification)
        self.assertIn("时间范围", clarification)

    def test_recent_sales_metric_clarifies_missing_time_range(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])

        with patch.object(model, "route_request") as route_request:
            sql, answer = agent.answer("查最近销售额")

        self.assertEqual(sql, "")
        self.assertIn("时间范围", answer)
        route_request.assert_not_called()

    def test_unresolved_order_reference_asks_for_identifier(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])

        with (
            patch.object(model, "route_request") as route_request,
            patch("business_agent.agent.execute_read_query") as execute_read_query,
        ):
            sql, answer = agent.answer("查这个订单的状态")

        self.assertEqual(sql, "")
        self.assertIn("订单号", answer)
        route_request.assert_not_called()
        execute_read_query.assert_not_called()

    def test_business_terms_in_writing_request_are_not_preemptively_queried(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with (
            patch.object(
                model,
                "route_request",
                return_value={
                    "intent": "general",
                    "sql": "",
                    "answer": "当然可以，我可以帮你写一封订单延迟通知邮件。",
                },
            ) as route_request,
            patch("business_agent.agent.execute_read_query") as execute_read_query,
        ):
            sql, answer = agent.answer("帮我写一封订单延迟通知邮件")

        self.assertEqual(sql, "")
        self.assertIn("邮件", answer)
        route_request.assert_called_once()
        execute_read_query.assert_not_called()

    def test_writing_about_an_unresolved_order_does_not_trigger_reference_clarification(
        self,
    ) -> None:
        question = "帮我写一封关于那个订单延迟的通知邮件"
        self.assertIsNone(
            BusinessAgent._unresolved_reference_clarification(question)
        )

    def test_sales_report_template_does_not_trigger_data_scope_clarification(self) -> None:
        question = "帮我生成销售表现报告模板"
        self.assertIsNone(BusinessAgent._sales_scope_clarification(question))

    def test_latest_news_is_not_mistaken_for_a_business_query(self) -> None:
        self.assertIsNone(
            BusinessAgent._recent_scope_clarification(
                "Show me the latest space news"
            )
        )

    def test_clarification_follow_up_uses_context_then_runs_query(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])
        plan = {
            "intent": "business_query",
            "sql": "SELECT order_number FROM orders",
            "answer": "",
        }

        with patch.object(model, "route_request", return_value=plan) as route_request:
            first_sql, first_answer = agent.answer("查一下最近的")
            second_sql, second_answer = agent.answer("订单，最近 7 天")

        self.assertEqual(first_sql, "")
        self.assertIn("时间范围", first_answer)
        self.assertEqual(second_sql, "SELECT order_number FROM orders")
        self.assertIn("查询结果", second_answer)
        follow_up = route_request.call_args.args[0]
        self.assertIn('"pending_request": "查一下最近的"', follow_up)
        self.assertIn('"助手追问：', follow_up)
        self.assertIn('"current_user_message": "订单，最近 7 天"', follow_up)
        self.assertIsNone(agent._pending_question)
        route_request.assert_called_once()

    def test_follow_up_receives_prior_questions_answers_and_sql(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])
        plans = [
            {
                "intent": "business_query",
                "sql": (
                    "SELECT first_name, last_name, email FROM customers "
                    "WHERE customer_code = 'CUST-0001'"
                ),
                "answer": "",
            },
            {
                "intent": "business_query",
                "sql": (
                    "SELECT email FROM customers "
                    "WHERE customer_code = 'CUST-0001'"
                ),
                "answer": "",
            },
        ]

        with patch.object(model, "route_request", side_effect=plans) as route_request:
            agent.answer("客户 CUST-0001 是谁？")
            sql, answer = agent.answer("他的邮箱呢？")

        self.assertIn("email", answer)
        self.assertTrue(sql.startswith("SELECT email"))
        second_request = route_request.call_args_list[1].args[0]
        self.assertIn("客户 CUST-0001 是谁？", second_request)
        self.assertIn("Alex", second_request)
        self.assertIn("CUST-0001", second_request)
        self.assertIn("他的邮箱呢？", second_request)

    def test_follow_up_reference_is_sent_with_history_instead_of_preemptively_blocked(
        self,
    ) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["customer_support"])
        plans = [
            {
                "intent": "business_query",
                "sql": (
                    "SELECT order_number, status FROM orders "
                    "WHERE order_number = 'ORD-000001'"
                ),
                "answer": "",
            },
            {
                "intent": "business_query",
                "sql": (
                    "SELECT status FROM orders "
                    "WHERE order_number = 'ORD-000001'"
                ),
                "answer": "",
            },
        ]

        with patch.object(model, "route_request", side_effect=plans) as route_request:
            agent.answer("订单 ORD-000001 的状态是什么？")
            sql, _ = agent.answer("这个订单的状态呢？")

        self.assertTrue(sql.startswith("SELECT status"))
        route_request.assert_called()
        second_request = route_request.call_args_list[1].args[0]
        self.assertIn("ORD-000001", second_request)
        self.assertIn("这个订单的状态呢？", second_request)

    def test_general_follow_up_receives_previous_exchange(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])
        plans = [
            {
                "intent": "general",
                "sql": "",
                "answer": "我们正在讨论订单的查询方式。",
            },
            {
                "intent": "general",
                "sql": "",
                "answer": "可以，我继续解释订单查询。",
            },
        ]

        with patch.object(model, "route_request", side_effect=plans) as route_request:
            agent.answer("我们刚才在讨论什么？")
            agent.answer("继续说")

        second_request = route_request.call_args_list[1].args[0]
        self.assertIn("我们刚才在讨论什么？", second_request)
        self.assertIn("我们正在讨论订单的查询方式。", second_request)
        self.assertIn("继续说", second_request)

    def test_decision_trace_reports_general_route_without_database_access(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])
        trace: list[str] = []
        with (
            patch.object(
                model,
                "route_request",
                return_value={
                    "intent": "general",
                    "sql": "",
                    "answer": "你好！",
                },
            ),
            patch("business_agent.agent.execute_read_query") as execute_read_query,
        ):
            agent.answer("你好", on_trace=trace.append)

        self.assertEqual(len(trace), 1)
        self.assertIn("普通对话", trace[0])
        self.assertIn("不调用数据库", trace[0])
        execute_read_query.assert_not_called()

    def test_decision_trace_reports_business_route_and_query_result(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])
        trace: list[str] = []
        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": "SELECT COUNT(*) AS order_count FROM orders",
                "answer": "",
            },
        ):
            agent.answer("一共有多少订单？", on_trace=trace.append)

        self.assertEqual(len(trace), 2)
        self.assertIn("业务数据查询", trace[0])
        self.assertIn("只读 SQL", trace[0])
        self.assertIn("返回 1 行", trace[1])

    def test_conversation_memory_is_bounded_and_can_be_cleared(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])
        for index in range(agent._MAX_HISTORY_TURNS + 3):
            agent._remember_turn(f"问题 {index}", f"回答 {index}")

        self.assertEqual(len(agent._conversation_history), agent._MAX_HISTORY_TURNS)
        self.assertNotIn("问题 0", str(agent._conversation_history))
        agent._pending_question = "待澄清的问题"
        agent._clarification_history = ["请提供更多信息"]

        agent.clear_conversation()

        self.assertEqual(agent._conversation_history, [])
        self.assertIsNone(agent._pending_question)
        self.assertEqual(agent._clarification_history, [])

    def test_explicit_recent_time_range_is_not_blocked_by_clarification_guard(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["sales_analyst"])
        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": "SELECT order_number FROM orders LIMIT 1",
                "answer": "",
            },
        ) as route_request:
            sql, _ = agent.answer("查询最近 7 天的订单")

        self.assertEqual(sql, "SELECT order_number FROM orders LIMIT 1")
        route_request.assert_called_once()

    def test_explicit_calendar_year_is_accepted_as_time_range(self) -> None:
        self.assertIsNone(
            BusinessAgent._recent_scope_clarification("查询最近的订单，2026年")
        )

    def test_out_of_scope_question_is_handled_as_general_without_sql(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["admin"])

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "general",
                "sql": "",
                "answer": "光合作用是植物将光能转化为化学能的过程。",
            },
        ):
            sql, answer = agent.answer("什么是光合作用？")

        self.assertEqual(sql, "")
        self.assertIn("光合作用", answer)

    def test_internal_role_can_return_up_to_1000_rows(self) -> None:
        role = ROLES["admin"]
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, role)
        sql_query = (
            "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL "
            "SELECT n + 1 FROM seq WHERE n < 1200) SELECT n FROM seq"
        )

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": sql_query,
                "answer": "",
            },
        ):
            _, answer = agent.answer("Return 1200 rows from orders")

        result_rows = [
            line for line in answer.splitlines() if line.startswith("| ")
        ][2:]
        self.assertEqual(role.max_rows, 1000)
        self.assertEqual(len(result_rows), 1000)
        self.assertIn("最多显示 1000 行", answer)

    def test_default_role_row_cap_is_100(self) -> None:
        role = replace(ROLES["customer_support"], max_rows=100)
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, role)
        sql_query = (
            "WITH RECURSIVE seq(n) AS (SELECT 1 UNION ALL "
            "SELECT n + 1 FROM seq WHERE n < 1200) SELECT n FROM seq"
        )

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": sql_query,
                "answer": "",
            },
        ):
            _, answer = agent.answer("Return 1200 rows from orders")

        result_rows = [
            line for line in answer.splitlines() if line.startswith("| ")
        ][2:]
        self.assertEqual(len(result_rows), 100)
        self.assertIn("最多显示 100 行", answer)


if __name__ == "__main__":
    unittest.main()
