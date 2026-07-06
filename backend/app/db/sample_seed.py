"""Seed the SQLite demo database with a realistic e-commerce dataset.

Run as a module from the backend/ directory:

    python -m app.db.sample_seed

Idempotent: drops and recreates the demo tables each run. Uses a fixed random
seed so the generated data is stable across runs (nice for screenshots/tests).
"""

from __future__ import annotations

import os
import random
import sqlite3
from datetime import date, datetime, timedelta

from app.config import settings

RANDOM_SEED = 42

SCHEMA = """
DROP TABLE IF EXISTS support_tickets;
DROP TABLE IF EXISTS marketing_campaigns;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    city        TEXT NOT NULL,
    signup_date DATE NOT NULL
);

CREATE TABLE products (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL,
    price    REAL NOT NULL
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    order_date  DATE NOT NULL,
    status      TEXT NOT NULL
);

CREATE TABLE order_items (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL,
    unit_price REAL NOT NULL
);

CREATE TABLE marketing_campaigns (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    channel    TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    spend      REAL NOT NULL
);

CREATE TABLE support_tickets (
    id                 INTEGER PRIMARY KEY,
    customer_id        INTEGER NOT NULL REFERENCES customers(id),
    created_at         TIMESTAMP NOT NULL,
    issue_type         TEXT NOT NULL,
    status             TEXT NOT NULL,
    satisfaction_score INTEGER
);
"""

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


def _daterange_random(rng: random.Random, start: date, end: date) -> date:
    delta_days = (end - start).days
    return start + timedelta(days=rng.randint(0, delta_days))


def seed(db_path: str) -> None:
    rng = random.Random(RANDOM_SEED)

    # Ensure a clean file so the schema matches exactly.
    if os.path.exists(db_path):
        os.remove(db_path)

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)

        today = date(2026, 7, 1)

        # --- customers ---
        customers = []
        for i, name in enumerate(CUSTOMER_NAMES, start=1):
            email = name.lower().replace(" ", ".") + "@example.com"
            city = rng.choice(CITIES)
            signup = _daterange_random(rng, date(2025, 1, 1), date(2026, 5, 1))
            customers.append((i, name, email, city, signup.isoformat()))
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers
        )

        # --- products ---
        products = [
            (i, name, category, price)
            for i, (name, category, price) in enumerate(PRODUCTS, start=1)
        ]
        conn.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?)", products
        )

        # --- orders + order_items ---
        orders = []
        order_items = []
        item_id = 1
        for order_id in range(1, 81):  # 80 orders
            customer_id = rng.randint(1, len(customers))
            order_date = _daterange_random(rng, date(2026, 1, 1), today)
            status = rng.choice(ORDER_STATUSES)
            orders.append(
                (order_id, customer_id, order_date.isoformat(), status)
            )

            # 1-4 line items per order
            for _ in range(rng.randint(1, 4)):
                product_id = rng.randint(1, len(products))
                quantity = rng.randint(1, 3)
                # unit price = product price, occasionally discounted
                base_price = products[product_id - 1][3]
                unit_price = round(base_price * rng.choice([1.0, 1.0, 0.9]), 2)
                order_items.append(
                    (item_id, order_id, product_id, quantity, unit_price)
                )
                item_id += 1

        conn.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?)", orders
        )
        conn.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", order_items
        )

        # --- marketing_campaigns ---
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
            campaigns.append(
                (cid, cname, channel, start.isoformat(), end.isoformat(), spend)
            )
        conn.executemany(
            "INSERT INTO marketing_campaigns VALUES (?, ?, ?, ?, ?, ?)", campaigns
        )

        # --- support_tickets ---
        tickets = []
        for tid in range(1, 31):  # 30 tickets
            customer_id = rng.randint(1, len(customers))
            created = datetime(2026, 1, 1) + timedelta(
                days=rng.randint(0, 180), hours=rng.randint(0, 23)
            )
            issue_type = rng.choice(ISSUE_TYPES)
            status = rng.choice(TICKET_STATUSES)
            # Only resolved/closed tickets have a satisfaction score.
            score = rng.randint(1, 5) if status in ("resolved", "closed") else None
            tickets.append(
                (tid, customer_id, created.isoformat(sep=" "), issue_type, status, score)
            )
        conn.executemany(
            "INSERT INTO support_tickets VALUES (?, ?, ?, ?, ?, ?)", tickets
        )

        conn.commit()

        counts = {
            "customers": len(customers),
            "products": len(products),
            "orders": len(orders),
            "order_items": len(order_items),
            "marketing_campaigns": len(campaigns),
            "support_tickets": len(tickets),
        }
        print(f"Seeded demo database at {db_path}")
        for table, n in counts.items():
            print(f"  {table:<20} {n} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    seed(settings.demo_db_path)
