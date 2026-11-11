from collections.abc import Callable
from pathlib import Path
from typing import Any

from business_agent.database import execute_read_query, schema_description
from business_agent.llm import OllamaAgentError, OllamaModel
from business_agent.roles import Role


class BusinessAgent:
    def __init__(self, database_path: Path, model: OllamaModel, role: Role) -> None:
        self.database_path = database_path
        self.model = model
        self.role = role

    def answer(
        self,
        question: str,
        on_progress: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        if on_progress is not None:
            on_progress("模型思考模式已开启，正在判断问题类型...")
        prompt = (
            "你是一个业务数据助手。先理解用户意图，再按要求返回 JSON：\n"
            "- business_query：用户询问当前业务数据库中实际存在、且当前角色有权访问的"
            "订单、客户、产品或订单明细数据。生成一条有效的只读 SQLite SELECT，填入 sql，"
            "answer 留空。\n"
            "- general：问候、闲聊、一般知识、写作、计算，或无法从当前角色可访问的业务"
            "数据库中查询的问题。sql 留空，并用用户使用的语言直接回答。若问题是在询问"
            "数据库中没有或当前角色无权访问的业务事实，明确说明无法从当前可访问的数据"
            "中确认，不要猜测或编造。\n"
            "不要把问候或一般问题转换成 SQL。业务查询只选择用户要求的字段；仅在需要"
            "跨表数据时 JOIN。用户指定条数时必须遵守 LIMIT；未指定时明细列表最多 50 行。"
            "只能使用列出的表和字段。SQL 必须是只读 SELECT。\n"
            "示例：用户说“你好”时，intent=general，sql 为空，answer 为简短问候；"
            "用户说“查询前3个客户的名字和邮箱”时，intent=business_query，SQL 为 "
            "SELECT first_name, last_name, email FROM customers LIMIT 3，不要 JOIN orders。\n"
            "只输出 JSON 对象，包含 intent、sql、answer 三个字段，不要输出 Markdown。\n\n"
            f"Allowed tables: {', '.join(sorted(self.role.allowed_tables))}\n"
            f"{schema_description(self.role.allowed_tables)}"
        )
        if on_progress is not None:
            on_progress("模型正在判断意图并生成回复或 SQL...")
        plan = self.model.route_request(question, prompt)
        if plan["intent"] == "general":
            answer = plan["answer"].strip()
            if not answer:
                raise OllamaAgentError(
                    "Ollama classified the request as general but returned no answer."
                )
            return "", answer

        sql = plan["sql"].strip()
        if not sql:
            raise OllamaAgentError(
                "Ollama classified the request as a business query but returned no SQL."
            )
        rows = execute_read_query(
            self.database_path,
            sql,
            self.role.allowed_tables,
        )
        return sql, self._format_rows(rows)

    @staticmethod
    def _format_rows(rows: list[dict[str, Any]]) -> str:
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
        return "查询结果（最多显示 100 行）：\n" + "\n".join([header, separator, *body])
