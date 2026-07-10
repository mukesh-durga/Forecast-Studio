"""Seed a Postgres database (e.g. Neon) with the shared e-commerce dataset.

Run from the backend/ directory with POSTGRES_DATABASE_URL (or DATABASE_URL) set:

    export POSTGRES_DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require"
    python -m app.db.postgres_seed

Idempotent: drops and recreates the demo tables. Data is identical to the
SQLite demo (see ``demo_dataset``).
"""

from __future__ import annotations

import sys

from app.config import settings
from app.db import demo_dataset

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
    price    DOUBLE PRECISION NOT NULL
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
    unit_price DOUBLE PRECISION NOT NULL
);

CREATE TABLE marketing_campaigns (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    channel    TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    spend      DOUBLE PRECISION NOT NULL
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

_PLACEHOLDERS = {t: ", ".join(["%s"] * len(cols)) for t, cols in demo_dataset.COLUMNS.items()}


def seed(dsn: str) -> None:
    import psycopg  # lazy: only needed when seeding Postgres

    data = demo_dataset.build_dataset()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
            for table, rows in data.items():
                cur.executemany(
                    f"INSERT INTO {table} VALUES ({_PLACEHOLDERS[table]})", rows
                )
        conn.commit()

    print("Seeded Postgres demo database")
    for table, rows in data.items():
        print(f"  {table:<20} {len(rows)} rows")


if __name__ == "__main__":
    if not settings.postgres_url:
        print(
            "POSTGRES_DATABASE_URL (or DATABASE_URL) is not set. Export it and re-run.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    seed(settings.postgres_url)
