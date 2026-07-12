"""Tests for the generic schema-aware SQL fallback (Phase 21).

Covers the classifier, the generator on the demo SQLite schema, the end-to-end
/query generic path, dialect handling, and a Postgres-dialect run via a local-safe
fake connector. No paid API, no network.
"""

import pytest
from fastapi.testclient import TestClient

from app.db.connectors.base import BaseConnector
from app.db.connectors.sqlite_connector import SQLiteConnector
from app.config import settings
from app.main import app
from app.services import generic_generator as gg
from app.services import schema_service
from app.services.sql_guard import validate_sql


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def schema():
    return schema_service.get_schema("demo")


# --- classifier -------------------------------------------------------------

@pytest.mark.parametrize("q", [
    "What is the revenue for each product?",
    "How many customers are there?",
    "average price of products",
    "How many support tickets are there?",
])
def test_classifier_database_questions(schema, q):
    assert gg.classify(q, schema) == gg.DB_ANALYTICS


@pytest.mark.parametrize("q", [
    "What is the weather tomorrow?",
    "Tell me a joke",
    "Who won the world cup?",
])
def test_classifier_general_questions_unsupported(schema, q):
    assert gg.classify(q, schema) == gg.UNSUPPORTED_GENERAL


@pytest.mark.parametrize("q", [
    "Please delete all customers",
    "drop table orders",
    "update customers set city = 'X'",
])
def test_classifier_unsafe_questions(schema, q):
    assert gg.classify(q, schema) == gg.UNSAFE


# --- generator (SQL is grounded + guard-passing) ----------------------------

@pytest.mark.parametrize("q", [
    "What is the revenue for each product?",
    "How many customers are there?",
    "How many orders were placed each month?",
    "How many support tickets are there?",
    "What is the average price of products?",
    "Revenue by category",
])
def test_generated_sql_guard_passes_and_selects_only(schema, q):
    g = gg.generate(q, schema)
    assert g is not None
    safe = validate_sql(g.sql)          # SELECT-only, single statement
    assert safe.upper().startswith("SELECT")


def test_revenue_per_product_shape(schema):
    g = gg.generate("What is the revenue for each product?", schema)
    assert "SUM(order_items.quantity * order_items.unit_price)" in g.sql
    assert "JOIN products" in g.sql
    assert g.expected_columns == ["product_name", "revenue"]


def test_postgres_dialect_uses_to_char(schema):
    pg = schema.model_copy(update={"dialect": "postgresql"})
    g = gg.generate("How many orders were placed each month?", pg)
    assert "to_char(orders.order_date, 'YYYY-MM')" in g.sql
    assert "strftime" not in g.sql


# --- semantic routing (Phase 23 fix) ---------------------------------------

def test_customer_spend_uses_orders_not_marketing(schema):
    g = gg.generate("Which customers spent the most?", schema)
    assert g is not None
    sql = g.sql
    # Joins the customer→orders→order_items chain, never marketing_campaigns.
    assert "customers" in sql and "orders" in sql and "order_items" in sql
    assert "marketing_campaigns" not in sql
    assert "customer_name" in g.expected_columns
    assert "total_spent" in g.expected_columns   # "spent" -> total_spent alias
    assert 'ORDER BY total_spent DESC' in sql and sql.rstrip().endswith("LIMIT 5")


def test_customer_revenue_alias_is_revenue(schema):
    g = gg.generate("Which customer generated the most revenue?", schema)
    assert "marketing_campaigns" not in g.sql
    assert g.expected_columns == ["customer_name", "revenue"]


def test_products_made_the_most_money(schema):
    g = gg.generate("Which products made the most money?", schema)
    assert "products" in g.sql and "order_items" in g.sql
    assert "marketing_campaigns" not in g.sql
    assert g.expected_columns[0] == "product_name"


def test_marketing_channel_uses_marketing_campaigns(schema):
    g = gg.generate("Which marketing channel had the highest spend?", schema)
    assert "marketing_campaigns" in g.sql
    assert "channel" in g.expected_columns


def test_revenue_by_order_status_joins_orders(schema):
    g = gg.generate("Show revenue by order status", schema)
    assert "order_items" in g.sql and "orders" in g.sql
    assert "GROUP BY orders.status" in g.sql
    assert g.expected_columns == ["status", "revenue"]


def test_semantic_mismatch_flags_customer_spend_on_marketing():
    bad = "SELECT SUM(marketing_campaigns.spend) AS total_spend FROM marketing_campaigns"
    reason = gg.semantic_mismatch("Which customers spent the most?", bad)
    assert reason is not None and "marketing_campaigns" in reason


def test_semantic_mismatch_none_for_correct_customer_sql():
    good = ("SELECT customers.name AS customer_name, "
            "SUM(order_items.quantity * order_items.unit_price) AS total_spent "
            "FROM order_items JOIN orders ON order_items.order_id = orders.id "
            "JOIN customers ON orders.customer_id = customers.id GROUP BY customers.name")
    assert gg.semantic_mismatch("Which customers spent the most?", good) is None


# --- end-to-end /query generic path -----------------------------------------

def _post(client, q):
    return client.post("/query", json={"question": q}).json()


def test_customer_spend_end_to_end_verified(client):
    b = _post(client, "Which customers spent the most?")
    assert b["matched"] is True and b["generic_mode_used"] is True
    assert "customer_name" in b["columns"]
    assert "total_spent" in b["columns"] or "revenue" in b["columns"]
    assert "marketing_campaigns" not in (b["sql"] or "")
    assert b["verification"]["verified"] is True
    assert b["row_count"] > 0


def test_revenue_by_order_status_end_to_end(client):
    b = _post(client, "Show revenue by order status")
    assert b["generic_mode_used"] is True
    assert set(b["columns"]) == {"status", "revenue"}
    assert b["verification"]["verified"] is True


def test_generic_verify_rejects_semantically_wrong_sql(client, monkeypatch):
    """If the generator emits a customer-spend query over marketing_campaigns,
    the route's semantic repair re-routes it to the correct table group."""
    bad = gg.GenericSql(
        sql="SELECT SUM(marketing_campaigns.spend) AS total_spend FROM marketing_campaigns",
        expected_columns=["total_spend"],
    )
    monkeypatch.setattr(gg, "generate", lambda q, s: bad)  # repair() is unaffected
    b = _post(client, "Which customers spent the most?")
    assert b["matched"] is True and b["generic_mode_used"] is True
    # Repaired to the correct customer/order tables and verified.
    assert "marketing_campaigns" not in b["sql"]
    assert "customer_name" in b["columns"]
    assert b["repair_attempted"] is True and b["repair_successful"] is True
    assert b["verification"]["verified"] is True


def test_generic_product_revenue_not_in_examples(client):
    b = _post(client, "What is the revenue for each product?")
    assert b["matched"] is True
    assert b["generic_mode_used"] is True
    assert b["generator"] == "generic"
    assert b["columns"] == ["product_name", "revenue"]
    assert b["row_count"] > 0
    assert b["verification"]["verified"] is True
    assert b["sample_checked"] is True


def test_generic_customer_question(client):
    b = _post(client, "How many customers are there?")
    assert b["matched"] is True and b["generic_mode_used"] is True
    assert b["columns"] == ["count"]
    assert b["rows"][0]["count"] > 0


def test_generic_monthly_aggregation(client):
    b = _post(client, "How many orders were placed each month?")
    assert b["matched"] is True and b["generic_mode_used"] is True
    assert b["columns"] == ["month", "count"]
    assert b["row_count"] > 0


def test_generic_support_ticket_question(client):
    b = _post(client, "How many support tickets are there for each status?")
    assert b["matched"] is True and b["generic_mode_used"] is True
    assert set(b["columns"]) == {"status", "count"}
    assert b["row_count"] > 0


def test_known_intent_still_uses_fast_path(client):
    b = _post(client, "What are the top 5 products by revenue?")
    assert b["generic_mode_used"] is False
    assert b["generator"] == "local"
    assert b["intent"] == "top_products_by_revenue"


def test_weather_remains_unsupported(client):
    b = _post(client, "What is the weather tomorrow?")
    assert b["matched"] is False
    assert b["sql"] is None
    assert b["generic_mode_used"] is False
    assert b["verification"]["failure_reason"] == "unsupported_general_question"


def test_unsafe_question_rejected(client):
    b = _post(client, "Please delete all customers")
    assert b["matched"] is False
    assert b["sql"] is None
    assert b["generic_mode_used"] is False
    assert b["verification"]["failure_reason"] == "unsafe_question"
    # No rows executed, no fabrication.
    assert b["row_count"] == 0 and b["rows"] == []


# --- Postgres generic path via a local-safe fake connector ------------------

class _FakePostgresConnector(BaseConnector):
    """Reports postgres dialect but delegates to the seeded SQLite demo."""

    dialect = "postgresql"

    def __init__(self):
        self._sqlite = SQLiteConnector(settings.demo_db_path)

    def list_tables(self):
        return self._sqlite.list_tables()

    def get_columns(self, table):
        return self._sqlite.get_columns(table)

    def get_sample_rows(self, table, limit):
        return self._sqlite.get_sample_rows(table, limit)

    def count_rows(self, table):
        return self._sqlite.count_rows(table)

    def run_select(self, sql, timeout_seconds):
        return self._sqlite.run_select(sql, timeout_seconds)


def test_generic_query_works_on_postgres_connection(client, monkeypatch):
    monkeypatch.setattr(schema_service, "get_connector", lambda cid: _FakePostgresConnector())
    # Dialect-agnostic generic query (no date functions) over a Postgres connection.
    resp = client.post(
        "/query",
        json={"question": "What is the revenue for each product?", "connection_id": "demo_postgres"},
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["dialect"] == "postgresql"
    assert b["generic_mode_used"] is True
    assert b["columns"] == ["product_name", "revenue"]
    assert b["row_count"] > 0
    assert b["verification"]["verified"] is True
