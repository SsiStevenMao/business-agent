import sqlite3
from pathlib import Path
import time
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    customer_code TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'discontinued')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    order_number TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled', 'returned')),
    payment_status TEXT NOT NULL
        CHECK (payment_status IN ('pending', 'paid', 'refunded', 'failed')),
    currency TEXT NOT NULL DEFAULT 'USD',
    shipping_address TEXT NOT NULL,
    shipping_city TEXT NOT NULL,
    shipping_region TEXT NOT NULL,
    shipping_postal_code TEXT NOT NULL,
    subtotal REAL NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    tax_amount REAL NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    shipping_amount REAL NOT NULL DEFAULT 0 CHECK (shipping_amount >= 0),
    total_amount REAL NOT NULL DEFAULT 0 CHECK (total_amount >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    discount_amount REAL NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    UNIQUE (order_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_items_order_id ON items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product_id ON items(product_id);
"""

COLUMN_DESCRIPTIONS = {
    "customers": (
        "id, customer_code, first_name, last_name, email, phone, company, "
        "status, created_at, updated_at"
    ),
    "products": (
        "id, sku, name, description, category, unit_price, stock_quantity, "
        "status, created_at, updated_at"
    ),
    "orders": (
        "id, order_number, customer_id, order_date, status, payment_status, currency, "
        "shipping_address, shipping_city, shipping_region, shipping_postal_code, "
        "subtotal, tax_amount, shipping_amount, total_amount, created_at, updated_at"
    ),
    "items": "id, order_id, product_id, quantity, unit_price, discount_amount",
}

MAX_QUERY_ROWS = 1000


class QueryError(ValueError):
    """Raised when a generated SQL query is invalid or not permitted."""


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_SQL)


def schema_description(allowed_tables: frozenset[str]) -> str:
    lines = ["SQLite tables:"]
    for table in ("customers", "products", "orders", "items"):
        if table in allowed_tables:
            lines.append(f"{table}({COLUMN_DESCRIPTIONS[table]})")

    relationships = (
        ("orders", "customers", "orders.customer_id=customers.id"),
        ("items", "orders", "items.order_id=orders.id"),
        ("items", "products", "items.product_id=products.id"),
    )
    visible_relationships = [
        relation
        for source, target, relation in relationships
        if source in allowed_tables and target in allowed_tables
    ]
    if visible_relationships:
        lines.append("Relationships: " + "; ".join(visible_relationships))
    return "\n".join(lines)


def execute_read_query(
    path: Path,
    sql: str,
    allowed_tables: frozenset[str],
    max_rows: int = 100,
) -> list[dict[str, Any]]:
    if not sql or len(sql) > 8000 or "\x00" in sql:
        raise QueryError("SQL is empty or exceeds the 8000-character limit.")
    if not 1 <= max_rows <= MAX_QUERY_ROWS:
        raise QueryError(f"max_rows must be between 1 and {MAX_QUERY_ROWS}.")

    connection = sqlite3.connect(path, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")

    allowed_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }

    def authorize(
        action: int,
        first_argument: str | None,
        second_argument: str | None,
        database_name: str | None,
        trigger_name: str | None,
    ) -> int:
        del database_name, trigger_name
        if action in allowed_actions:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ and first_argument in allowed_tables:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    connection.set_authorizer(authorize)
    started_at = time.monotonic()
    connection.set_progress_handler(
        lambda: int(time.monotonic() - started_at > 3),
        1000,
    )
    try:
        cursor = connection.execute(sql)
        if cursor.description is None:
            raise QueryError("Only read-only SELECT queries are allowed.")
        rows = cursor.fetchmany(max_rows + 1)
        return [dict(row) for row in rows[:max_rows]]
    except sqlite3.Error as error:
        raise QueryError(f"SQLite rejected the query: {error}") from error
    finally:
        connection.close()
