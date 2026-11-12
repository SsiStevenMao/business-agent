from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from business_agent.agent import BusinessAgent
from business_agent.config import PROJECT_ROOT, load_settings
from business_agent.database import (
    QueryError,
    execute_read_query,
    initialize_database,
)
from business_agent.llm import LanguageModel, ModelProviderError, create_model
from business_agent.roles import ROLES
from business_agent.seed import seed_database


GOLDEN_QUESTIONS_PATH = PROJECT_ROOT / "evaluation" / "golden_questions.json"


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    question: str
    role: str
    expected_intent: str
    expected_sql: str | None = None
    expected_rows: tuple[tuple[Any, ...], ...] | None = None
    expected_row_count: int | None = None


def load_golden_questions() -> list[GoldenQuestion]:
    with GOLDEN_QUESTIONS_PATH.open(encoding="utf-8") as file:
        records = json.load(file)
    return [
        GoldenQuestion(
            id=record["id"],
            question=record["question"],
            role=record["role"],
            expected_intent=record["expected_intent"],
            expected_sql=record.get("expected_sql"),
            expected_rows=(
                tuple(tuple(row) for row in record["expected_rows"])
                if "expected_rows" in record
                else None
            ),
            expected_row_count=record.get("expected_row_count"),
        )
        for record in records
    ]


def _row_multiset(rows: list[dict[str, Any]], columns: list[str]) -> Counter:
    return Counter(tuple(row[column] for column in columns) for row in rows)


def _evaluate_question(
    case: GoldenQuestion,
    database_path: Path,
    model: LanguageModel,
) -> str | None:
    role = ROLES[case.role]
    agent = BusinessAgent(database_path, model, role)
    sql, answer = agent.answer(case.question)
    if not answer.strip():
        return "agent returned an empty answer"
    if case.expected_intent == "clarification":
        if sql:
            return f"expected clarification without SQL, got SQL: {sql}"
        if not answer.rstrip().endswith(("?", "？")):
            return f"expected a clarifying question, got: {answer}"
        return None
    actual_intent = "business_query" if sql else "general"
    if actual_intent != case.expected_intent:
        return f"expected intent {case.expected_intent!r}, got {actual_intent!r}"
    if case.expected_intent == "general":
        return None
    if case.expected_sql is None:
        return "business question is missing its golden SQL"

    actual_rows = execute_read_query(
        database_path,
        sql,
        role.allowed_tables,
        max_rows=role.max_rows,
    )
    expected_rows = execute_read_query(
        database_path,
        case.expected_sql,
        role.allowed_tables,
        max_rows=role.max_rows,
    )
    actual_columns = list(actual_rows[0]) if actual_rows else []
    expected_columns = list(expected_rows[0]) if expected_rows else []
    if actual_columns != expected_columns:
        return (
            f"expected columns {expected_columns!r}, "
            f"got {actual_columns!r}; SQL: {sql}"
        )
    if _row_multiset(actual_rows, actual_columns) != _row_multiset(
        expected_rows, expected_columns
    ):
        return f"query result differs from the golden answer; SQL: {sql}"
    if case.expected_row_count is not None and len(actual_rows) != case.expected_row_count:
        return (
            f"expected {case.expected_row_count} rows, got {len(actual_rows)}; "
            f"SQL: {sql}"
        )
    if case.expected_rows is not None:
        actual_values = tuple(
            tuple(row[column] for column in actual_columns) for row in actual_rows
        )
        if actual_values != case.expected_rows:
            return f"expected rows {case.expected_rows!r}, got {actual_values!r}"
    return None


def main() -> int:
    try:
        settings = load_settings()
        model = create_model(settings)
    except ModelProviderError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    cases = load_golden_questions()
    failures = 0
    with tempfile.TemporaryDirectory(prefix="business-agent-eval-") as directory:
        database_path = Path(directory) / "evaluation.db"
        initialize_database(database_path)
        seed_database(database_path, order_count=1000)

        for case in cases:
            try:
                failure = _evaluate_question(case, database_path, model)
            except (ModelProviderError, QueryError) as error:
                failure = str(error)
            if failure is None:
                print(f"PASS {case.id}: {case.question}")
            else:
                failures += 1
                print(f"FAIL {case.id}: {failure}")

    passed = len(cases) - failures
    print(f"\nEvaluation: {passed}/{len(cases)} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
