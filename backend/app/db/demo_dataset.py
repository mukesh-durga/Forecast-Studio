"""Deterministic e-commerce demo dataset.

Shared by the SQLite seeder (``sample_seed``) and the Postgres seeder
(``postgres_seed``) so both databases contain the *same* rows. Dates/timestamps
are ISO-formatted strings — SQLite stores them as-is, and Postgres implicitly
casts them into DATE/TIMESTAMP columns.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

RANDOM_SEED = 42

CUSTOMER_NAMES = [
    "Ava Johnson", "Liam Smith", "Olivia Brown", "Noah Garcia", "Emma Martinez",
    "Sophia Davis", "Mason Rodriguez", "Isabella Wilson", "James Anderson",
    "Mia Thomas", "Benjamin Taylor", "Charlotte Moore", "Elijah Jackson",
    "Amelia White", "Lucas Harris", "Harper Martin", "Henry Thompson",
    "Evelyn Lee", "Alexander Perez", "Abigail Clark", "Daniel Lewis",
    "Emily Walker", "Michael Hall", "Ella Young",
]

CITIES = [
    "New York", "San Francisco", "Chicago", "Austin", "Seattle",
    "Boston", "Denver", "Miami", "Portland", "Atlanta",
]

PRODUCTS = [
    ("Wireless Headphones", "Electronics", 129.99),
    ("Bluetooth Speaker", "Electronics", 79.50),
    ("4K Monitor", "Electronics", 349.00),
    ("Mechanical Keyboard", "Electronics", 99.95),
    ("Ergonomic Mouse", "Electronics", 45.00),
    ("Standing Desk", "Furniture", 429.00),
    ("Office Chair", "Furniture", 259.99),
    ("Desk Lamp", "Furniture", 39.99),
    ("Cotton T-Shirt", "Apparel", 24.99),
    ("Running Shoes", "Apparel", 89.99),
    ("Water Bottle", "Accessories", 19.99),
    ("Backpack", "Accessories", 64.50),
]

ORDER_STATUSES = ["completed", "completed", "completed", "shipped", "pending", "cancelled"]
CAMPAIGN_CHANNELS = ["Email", "Google Ads", "Facebook", "Instagram", "SEO"]
ISSUE_TYPES = ["shipping", "billing", "product_defect", "account", "returns"]
TICKET_STATUSES = ["open", "open", "resolved", "resolved", "resolved", "closed"]

# Insert column order for each table (INSERT ... VALUES matches this order).
COLUMNS = {
    "customers": ("id", "name", "email", "city", "signup_date"),
    "products": ("id", "name", "category", "price"),
    "orders": ("id", "customer_id", "order_date", "status"),
    "order_items": ("id", "order_id", "product_id", "quantity", "unit_price"),
    "marketing_campaigns": ("id", "name", "channel", "start_date", "end_date", "spend"),
    "support_tickets": ("id", "customer_id", "created_at", "issue_type", "status", "satisfaction_score"),
}


def _daterange_random(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def build_dataset() -> dict[str, list[tuple]]:
    """Return {table: [row tuples]} — deterministic across runs and databases."""
    rng = random.Random(RANDOM_SEED)
    today = date(2026, 7, 1)

    customers = []
    for i, name in enumerate(CUSTOMER_NAMES, start=1):
        email = name.lower().replace(" ", ".") + "@example.com"
        city = rng.choice(CITIES)
        signup = _daterange_random(rng, date(2025, 1, 1), date(2026, 5, 1))
        customers.append((i, name, email, city, signup.isoformat()))

    products = [
        (i, name, category, price)
        for i, (name, category, price) in enumerate(PRODUCTS, start=1)
    ]

    orders = []
    order_items = []
    item_id = 1
    for order_id in range(1, 81):  # 80 orders
        customer_id = rng.randint(1, len(customers))
        order_date = _daterange_random(rng, date(2026, 1, 1), today)
        status = rng.choice(ORDER_STATUSES)
        orders.append((order_id, customer_id, order_date.isoformat(), status))

        for _ in range(rng.randint(1, 4)):  # 1-4 line items per order
            product_id = rng.randint(1, len(products))
            quantity = rng.randint(1, 3)
            base_price = products[product_id - 1][3]
            unit_price = round(base_price * rng.choice([1.0, 1.0, 0.9]), 2)
            order_items.append((item_id, order_id, product_id, quantity, unit_price))
            item_id += 1

    campaigns = []
    campaign_names = [
        "New Year Sale", "Spring Launch", "Summer Promo",
        "Back to Office", "Loyalty Boost", "Flash Weekend",
    ]
    for cid, cname in enumerate(campaign_names, start=1):
        channel = rng.choice(CAMPAIGN_CHANNELS)
        start = _daterange_random(rng, date(2026, 1, 1), date(2026, 5, 1))
        end = start + timedelta(days=rng.randint(14, 45))
        spend = round(rng.uniform(2000, 25000), 2)
        campaigns.append((cid, cname, channel, start.isoformat(), end.isoformat(), spend))

    tickets = []
    for tid in range(1, 31):  # 30 tickets
        customer_id = rng.randint(1, len(customers))
        created = datetime(2026, 1, 1) + timedelta(
            days=rng.randint(0, 180), hours=rng.randint(0, 23)
        )
        issue_type = rng.choice(ISSUE_TYPES)
        status = rng.choice(TICKET_STATUSES)
        score = rng.randint(1, 5) if status in ("resolved", "closed") else None
        tickets.append((tid, customer_id, created.isoformat(sep=" "), issue_type, status, score))

    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "marketing_campaigns": campaigns,
        "support_tickets": tickets,
    }
