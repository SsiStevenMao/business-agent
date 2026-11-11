import sqlite3
import tempfile
import unittest
from pathlib import Path

from business_agent.database import QueryError, execute_read_query, initialize_database
from business_agent.seed import seed_database


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "business.db"
        initialize_database(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_seed_creates_requested_business_data_and_relationships(self) -> None:
        seed_database(self.database_path, order_count=20)
        with sqlite3.connect(self.database_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 50)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 100)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 20)
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0], 20)
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )

    def test_query_is_read_only_and_respects_role_table_permissions(self) -> None:
        seed_database(self.database_path, order_count=1)
        rows = execute_read_query(
            self.database_path,
            "SELECT COUNT(*) AS count FROM customers",
            frozenset({"customers"}),
        )
        self.assertEqual(rows[0]["count"], 50)

        with self.assertRaises(QueryError):
            execute_read_query(
                self.database_path,
                "SELECT * FROM products",
                frozenset({"customers"}),
            )
        with self.assertRaises(QueryError):
            execute_read_query(
                self.database_path,
                "DELETE FROM customers",
                frozenset({"customers"}),
            )

    def test_query_results_are_capped(self) -> None:
        seed_database(self.database_path, order_count=1)
        rows = execute_read_query(
            self.database_path,
            "SELECT id FROM customers ORDER BY id",
            frozenset({"customers"}),
            max_rows=5,
        )
        self.assertEqual(len(rows), 5)


if __name__ == "__main__":
    unittest.main()
