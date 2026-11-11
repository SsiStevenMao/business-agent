import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


FIRST_NAMES = [
    "Alex", "Avery", "Blake", "Casey", "Cameron", "Dakota", "Drew", "Elliot",
    "Emerson", "Finley", "Harper", "Jordan", "Kai", "Logan", "Morgan", "Parker",
    "Quinn", "Reese", "Riley", "Rowan", "Sam", "Taylor", "Ari", "Charlie",
    "Jamie", "Jules", "Kendall", "Robin", "Skyler", "Toby",
]
LAST_NAMES = [
    "Adams", "Bennett", "Brooks", "Carter", "Chen", "Clark", "Davis", "Evans",
    "Foster", "Garcia", "Green", "Hall", "Harris", "Hill", "Jackson", "Kim",
    "Lee", "Lewis", "Martin", "Miller", "Moore", "Nguyen", "Patel", "Perez",
    "Reed", "Rivera", "Scott", "Smith", "Turner", "Wright",
]
CITIES = [
    ("Seattle", "WA", "98101"), ("Austin", "TX", "73301"),
    ("Denver", "CO", "80201"), ("Portland", "OR", "97201"),
    ("Boston", "MA", "02108"), ("Chicago", "IL", "60601"),
    ("Atlanta", "GA", "30301"), ("Miami", "FL", "33101"),
]
PRODUCTS = [
    ("Electronics", "Wireless Mouse", "Ergonomic wireless mouse"),
    ("Electronics", "USB-C Hub", "Seven-port USB-C hub"),
    ("Electronics", "Mechanical Keyboard", "Compact mechanical keyboard"),
    ("Electronics", "Webcam", "1080p USB webcam"),
    ("Office", "Desk Lamp", "Adjustable LED desk lamp"),
    ("Office", "Notebook Set", "Set of three lined notebooks"),
    ("Office", "Monitor Stand", "Bamboo monitor stand"),
    ("Furniture", "Office Chair", "Adjustable mesh office chair"),
    ("Furniture", "Standing Desk", "Electric height-adjustable desk"),
    ("Accessories", "Laptop Sleeve", "Protective 14-inch laptop sleeve"),
]

ORDER_STATUSES = ("pending", "processing", "shipped", "delivered", "cancelled", "returned")
PAYMENT_STATUSES = ("pending", "paid", "paid", "paid", "paid", "refunded")


def seed_database(path: Path, order_count: int = 1000) -> None:
    randomizer = random.Random(2026)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = now.isoformat()

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] > 0:
            return

        customers = []
        for index in range(50):
            first = FIRST_NAMES[index % len(FIRST_NAMES)]
            last = LAST_NAMES[(index * 7) % len(LAST_NAMES)]
            customers.append(
                (
                    f"CUST-{index + 1:04d}",
                    first,
                    last,
                    f"{first.lower()}.{last.lower()}.{index + 1}@example.com",
                    f"+1-555-{index + 1:04d}",
                    f"{last} & Co." if index % 3 == 0 else None,
                    "inactive" if index % 13 == 0 else "active",
                    stamp,
                    stamp,
                )
            )
        connection.executemany(
            "INSERT INTO customers "
            "(customer_code, first_name, last_name, email, phone, company, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            customers,
        )

        product_rows = []
        for index in range(100):
            category, name, description = PRODUCTS[index % len(PRODUCTS)]
            product_rows.append(
                (
                    f"SKU-{index + 1:04d}",
                    f"{name} {index // len(PRODUCTS) + 1}" if index >= len(PRODUCTS) else name,
                    description,
                    category,
                    round(randomizer.uniform(8, 450), 2),
                    randomizer.randint(0, 250),
                    "discontinued" if index % 19 == 0 else "active",
                    stamp,
                    stamp,
                )
            )
        connection.executemany(
            "INSERT INTO products "
            "(sku, name, description, category, unit_price, stock_quantity, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            product_rows,
        )

        product_records = connection.execute(
            "SELECT id, unit_price FROM products ORDER BY id"
        ).fetchall()
        customer_ids = [
            row[0] for row in connection.execute("SELECT id FROM customers ORDER BY id")
        ]

        for order_index in range(order_count):
            order_date = now - timedelta(days=randomizer.randrange(366))
            order_stamp = order_date.isoformat()
            status_index = randomizer.randrange(len(ORDER_STATUSES))
            order_status = ORDER_STATUSES[status_index]
            payment_status = PAYMENT_STATUSES[status_index]
            city, region, postal_code = randomizer.choice(CITIES)
            selected_products = randomizer.sample(product_records, randomizer.randint(1, 4))

            items = []
            subtotal = 0.0
            for product_id, current_price in selected_products:
                quantity = randomizer.randint(1, 4)
                unit_price = round(current_price * randomizer.uniform(0.85, 1.15), 2)
                discount = round(unit_price * quantity * randomizer.choice((0, 0, 0, 0.05, 0.1)), 2)
                subtotal += unit_price * quantity - discount
                items.append((product_id, quantity, unit_price, discount))

            subtotal = round(subtotal, 2)
            tax_amount = round(subtotal * 0.08, 2)
            shipping_amount = 0.0 if subtotal >= 100 else 9.99
            order_id = connection.execute(
                "INSERT INTO orders "
                "(order_number, customer_id, order_date, status, payment_status, currency, "
                "shipping_address, shipping_city, shipping_region, shipping_postal_code, "
                "subtotal, tax_amount, shipping_amount, total_amount, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ORD-{order_index + 1:06d}",
                    randomizer.choice(customer_ids),
                    order_stamp,
                    order_status,
                    payment_status,
                    f"{randomizer.randint(100, 9999)} Market Street",
                    city,
                    region,
                    postal_code,
                    subtotal,
                    tax_amount,
                    shipping_amount,
                    round(subtotal + tax_amount + shipping_amount, 2),
                    order_stamp,
                    order_stamp,
                ),
            ).lastrowid
            connection.executemany(
                "INSERT INTO items (order_id, product_id, quantity, unit_price, discount_amount) "
                "VALUES (?, ?, ?, ?, ?)",
                [(order_id, *item) for item in items],
            )
