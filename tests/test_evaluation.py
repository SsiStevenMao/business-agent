import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from business_agent.database import execute_read_query, initialize_database
from business_agent.evaluate import _evaluate_question, load_golden_questions
from business_agent.llm import OllamaModel
from business_agent.roles import ROLES
from business_agent.seed import seed_database


class GoldenQuestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "golden.db"
        initialize_database(self.database_path)
        seed_database(self.database_path, order_count=1000)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_golden_answers_match_seeded_database(self) -> None:
        for case in load_golden_questions():
            with self.subTest(case=case.id):
                if case.expected_intent == "general":
                    self.assertIsNone(case.expected_sql)
                    continue

                self.assertIsNotNone(case.expected_sql)
                role = ROLES[case.role]
                rows = execute_read_query(
                    self.database_path,
                    case.expected_sql,
                    role.allowed_tables,
                    max_rows=role.max_rows,
                )
                if case.expected_rows is not None:
                    actual_rows = tuple(tuple(row.values()) for row in rows)
                    self.assertEqual(actual_rows, case.expected_rows)
                if case.expected_row_count is not None:
                    self.assertEqual(len(rows), case.expected_row_count)

    def test_golden_questions_have_unique_ids_and_valid_roles(self) -> None:
        cases = load_golden_questions()
        ids = [case.id for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(cases)
        for case in cases:
            self.assertIn(case.role, ROLES)

    def test_evaluator_catches_model_returning_only_50_of_all_orders(self) -> None:
        case = next(
            question
            for question in load_golden_questions()
            if question.id == "all-orders"
        )
        model = OllamaModel("http://localhost:11434", "test-model")
        with patch.object(
            model,
            "route_request",
            return_value={
                "intent": "business_query",
                "sql": "SELECT * FROM orders LIMIT 50",
                "answer": "",
            },
        ):
            failure = _evaluate_question(case, self.database_path, model)

        self.assertIsNotNone(failure)
        self.assertIn("query result differs", failure)


if __name__ == "__main__":
    unittest.main()
