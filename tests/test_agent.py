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
        self.assertIn("不要把问候或一般问题转换成 SQL", prompt)

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
        self.assertIn("用户询问“所有”“全部”或完整列表时，不要添加 LIMIT", prompt)
        self.assertIn("未指定条数时也不要自行使用固定的 LIMIT", prompt)
        self.assertNotIn("明细列表最多 50 行", prompt)
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

    def test_greeting_is_answered_by_model_without_querying_database(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["customer_support"])

        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "general",
                "sql": "",
                "answer": "你好！我可以帮你查询订单、客户和产品信息。",
            },
        ) as route_request:
            sql, answer = agent.answer("你好")

        self.assertEqual(sql, "")
        self.assertIn("你好", answer)
        route_request.assert_called_once()

    def test_out_of_scope_question_is_handled_as_general_without_sql(self) -> None:
        model = OllamaModel("http://localhost:11434", "test-model")
        agent = BusinessAgent(self.database_path, model, ROLES["customer_support"])

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
            _, answer = agent.answer("Return 1200 rows")

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
            _, answer = agent.answer("Return 1200 rows")

        result_rows = [
            line for line in answer.splitlines() if line.startswith("| ")
        ][2:]
        self.assertEqual(len(result_rows), 100)
        self.assertIn("最多显示 100 行", answer)


if __name__ == "__main__":
    unittest.main()
