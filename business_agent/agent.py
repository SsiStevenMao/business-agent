from collections.abc import Callable
from pathlib import Path
import re
from typing import Any

from business_agent.database import execute_read_query, schema_description
from business_agent.llm import LanguageModel, ModelProviderError
from business_agent.roles import Role


class BusinessAgent:
    def __init__(self, database_path: Path, model: LanguageModel, role: Role) -> None:
        self.database_path = database_path
        self.model = model
        self.role = role
        self._pending_question: str | None = None
        self._clarification_history: list[str] = []

    @staticmethod
    def _recent_scope_clarification(question: str) -> str | None:
        recent_expression = r"最近|近期|\brecent(?:ly)?\b|\blately\b|\blatest\b"
        if not re.search(recent_expression, question, re.IGNORECASE):
            return None

        target_expressions = (
            r"订单|订单明细|订单行|order|purchase|item|line item",
            r"产品|商品|库存|product|inventory",
            r"客户|顾客|customer|client",
        )
        has_target = any(
            re.search(expression, question, re.IGNORECASE)
            for expression in target_expressions
        )
        time_range_expressions = (
            r"(?:最近|近|过去)\s*(?:\d+|一|两|三|四|五|六|七|半)\s*"
            r"(?:天|日|周|个?月|年|小时|分钟)",
            r"(?:今天|昨天|前天|本周|这周|上周|本月|这个月|上个月|"
            r"本季度|这个季度|上季度|今年|本年|去年)",
            r"\b(?:last|past|previous)\s+\d+\s+"
            r"(?:days?|weeks?|months?|quarters?|years?)\b",
            r"\b(?:today|yesterday|this week|last week|this month|last month|"
            r"this quarter|last quarter|this year|last year)\b",
            r"\b(?:since|from)\s+\d{4}-\d{1,2}-\d{1,2}\b",
        )
        has_time_range = any(
            re.search(expression, question, re.IGNORECASE)
            for expression in time_range_expressions
        )
        if has_target and has_time_range:
            return None

        is_chinese = any("\u4e00" <= character <= "\u9fff" for character in question)
        if is_chinese:
            if not has_target and not has_time_range:
                return (
                    "你想查询哪类业务数据（订单、客户、产品等）？"
                    "“最近”具体指什么时间范围（例如最近 7 天或 30 天）？"
                )
            if not has_target:
                return "你想查询哪类业务数据（订单、客户、产品等）？"
            return "你想查询哪个时间范围内的数据（例如最近 7 天或 30 天）？"

        if not has_target and not has_time_range:
            return (
                "Which business data should I look up (orders, customers, products, etc.), "
                "and what time range do you mean by “recent” (for example, the last 7 or 30 days)?"
            )
        if not has_target:
            return "Which business data should I look up (orders, customers, products, etc.)?"
        return "What time range do you mean (for example, the last 7 or 30 days)?"

    def answer(
        self,
        question: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        if self._pending_question is None:
            clarification = self._recent_scope_clarification(question)
            if clarification is not None:
                self._pending_question = question
                self._clarification_history = [f"助手追问：{clarification}"]
                return "", clarification

        if on_progress is not None:
            on_progress("模型正在判断问题类型...")
        prompt = (
            "你是一个业务数据助手。先理解用户意图，再按要求返回 JSON：\n"
            "- business_query：用户询问当前业务数据库中实际存在、且当前角色有权访问的"
            "订单、客户、产品或订单明细数据。生成一条有效的只读 SQLite SELECT，填入 sql，"
            "answer 留空。\n"
            "- clarification：用户想查询业务数据，但缺少决定查询对象或范围的关键信息。"
            "sql 留空，并在 answer 中用用户使用的语言提出简短、明确的澄清问题。不要猜测"
            "用户指的是哪类数据，也不要擅自选择时间范围。若用户只说“查一下最近的”，"
            "询问要查订单、产品还是其他业务数据，并询问“最近”具体指什么时间范围；"
            "若已明确对象但时间范围不明确，例如“查最近的订单”，只询问时间范围。\n"
            "如果提供了待澄清的原始请求和对话记录，判断用户最新消息是否在补充该请求："
            "若是，将原始请求与补充信息合并后继续处理；若最新消息明显是新的独立请求，"
            "只处理新请求，不要把旧请求的信息混入。\n"
            "- general：问候、闲聊、一般知识、写作、计算，或无法从当前角色可访问的业务"
            "数据库中查询的问题。sql 留空，并用用户使用的语言直接回答。若问题是在询问"
            "数据库中没有或当前角色无权访问的业务事实，明确说明无法从当前可访问的数据"
            "中确认，不要猜测或编造。\n"
            "只有完成业务对象和必要范围的辨认后才生成 SQL。诸如“最近的”“近期”等时间"
            "表达在缺少具体时间范围时必须先澄清，不要自行解释为最近 7 天、30 天或某个"
            "默认区间；若业务对象也不明确，应一并询问。不要为不完整的业务请求执行 SQL。\n"
            "不要把问候或一般问题转换成 SQL。业务查询只选择用户要求的字段；仅在需要"
            "跨表数据时 JOIN。用户明确指定条数时才添加对应的 LIMIT，且不得超过当前角色"
            "的行数上限；用户询问“所有”“全部”或完整列表时，不要添加 LIMIT，查询工具会"
            "按当前角色的行数上限截断结果。未指定条数时也不要自行使用固定的 LIMIT。"
            "当前角色单次查询最多返回 "
            f"{self.role.max_rows} 行。\n"
            "只能使用列出的表和字段。SQL 必须是只读 SELECT。\n"
            "示例：用户说“你好”时，intent=general，sql 为空，answer 为简短问候；"
            "用户说“查询前3个客户的名字和邮箱”时，intent=business_query，SQL 为 "
            "SELECT first_name, last_name, email FROM customers LIMIT 3，不要 JOIN orders；"
            "用户说“查一下最近的”时，intent=clarification，sql 为空，询问业务对象和时间"
            "范围；用户说“查最近的订单”时，intent=clarification，sql 为空，询问时间范围。\n"
            "只输出 JSON 对象，包含 intent、sql、answer 三个字段，不要输出 Markdown。\n\n"
            f"Allowed tables: {', '.join(sorted(self.role.allowed_tables))}\n"
            f"{schema_description(self.role.allowed_tables)}"
        )
        routed_question = question
        if self._pending_question is not None:
            history = "\n".join(self._clarification_history)
            routed_question = (
                f"待澄清的原始请求：{self._pending_question}\n"
                f"此前的澄清对话：\n{history or '（无）'}\n"
                f"用户最新消息：{question}"
            )
        if on_progress is not None:
            on_progress("模型正在判断意图、必要时澄清并生成 SQL...")
        plan = self.model.route_request(routed_question, prompt)
        if plan["intent"] in {"general", "clarification"}:
            if plan["sql"].strip():
                raise ModelProviderError(
                    f"The model returned SQL for a {plan['intent']} request."
                )
            answer = plan["answer"].strip()
            if not answer:
                raise ModelProviderError(
                    f"The model classified the request as {plan['intent']} "
                    "but returned no answer."
                )
            if plan["intent"] == "clarification":
                if self._pending_question is None:
                    self._pending_question = question
                    self._clarification_history = [f"助手追问：{answer}"]
                else:
                    self._clarification_history.extend(
                        (f"用户补充：{question}", f"助手追问：{answer}")
                    )
            else:
                self._pending_question = None
                self._clarification_history = []
            return "", answer

        sql = plan["sql"].strip()
        if not sql:
            raise ModelProviderError(
                "Ollama classified the request as a business query but returned no SQL."
            )
        self._pending_question = None
        self._clarification_history = []
        rows = execute_read_query(
            self.database_path,
            sql,
            self.role.allowed_tables,
            max_rows=self.role.max_rows,
        )
        return sql, self._format_rows(rows, self.role.max_rows)

    @staticmethod
    def _format_rows(rows: list[dict[str, Any]], max_rows: int = 100) -> str:
        if not rows:
            return "没有查到匹配的数据。"

        columns = list(rows[0])

        def cell(value: Any) -> str:
            return (
                str(value if value is not None else "")
                .replace("|", "\\|")
                .replace("\n", " ")
                .replace("\r", " ")
            )

        header = "| " + " | ".join(cell(column) for column in columns) + " |"
        separator = "| " + " | ".join("---" for _ in columns) + " |"
        body = [
            "| " + " | ".join(cell(row.get(column)) for column in columns) + " |"
            for row in rows
        ]
        return (
            f"查询结果（本角色最多显示 {max_rows} 行）：\n"
            + "\n".join([header, separator, *body])
        )
