from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    key: str
    name: str
    description: str
    allowed_tables: frozenset[str]
    max_rows: int = 100


ROLES = {
    role.key: role
    for role in (
        Role(
            key="customer_support",
            name="Customer Support",
            description="Look up customer profiles and their order history/status.",
            allowed_tables=frozenset({"customers", "orders", "items"}),
            max_rows=1000,
        ),
        Role(
            key="sales_analyst",
            name="Sales Analyst",
            description="Analyze customers, orders, products, and order line items.",
            allowed_tables=frozenset({"customers", "orders", "products", "items"}),
            max_rows=1000,
        ),
        Role(
            key="inventory_manager",
            name="Inventory Manager",
            description="Review product catalog, stock levels, and product sales.",
            allowed_tables=frozenset({"products", "items", "orders"}),
            max_rows=1000,
        ),
        Role(
            key="admin",
            name="Read-only Administrator",
            description="Read and report on all business data.",
            allowed_tables=frozenset({"customers", "orders", "products", "items"}),
            max_rows=1000,
        ),
    )
}
