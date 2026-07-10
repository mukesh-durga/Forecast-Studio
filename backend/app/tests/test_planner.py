"""Tests for the query planning layer."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import planner_service, schema_service


@pytest.fixture
def schema():
    return schema_service.get_schema("demo")


# (question, expected intent, expected required tables, must-contain measure fragment,
#  expected result columns)
CASES = [
    ("What are the top 5 products by revenue?", "top_products_by_revenue",
     {"order_items", "products"}, "revenue", ["product_name", "revenue"]),
    ("Which city has the most customers?", "city_most_customers",
     {"customers"}, "customer_count", ["city", "customer_count"]),
    ("What was the total revenue by month?", "monthly_revenue",
     {"orders", "order_items"}, "revenue", ["month", "revenue"]),
    ("Which product category generated the highest revenue?", "category_revenue",
     {"order_items", "products"}, "revenue", ["category", "revenue"]),
    ("What is the average order value?", "average_order_value",
     {"orders", "order_items"}, "average_order_value", ["average_order_value"]),
    ("Which customers placed the most orders?", "top_customers_by_orders",
     {"customers", "orders"}, "order_count", ["customer_name", "order_count"]),
    ("How many support tickets are still open?", "open_tickets",
     {"support_tickets"}, "open_tickets", ["open_tickets"]),
    ("Which issue type has the lowest satisfaction score?", "lowest_satisfaction_issue",
     {"support_tickets"}, "avg_satisfaction", ["issue_type", "avg_satisfaction"]),
    ("What marketing channel had the highest spend?", "top_channel_by_spend",
     {"marketing_campaigns"}, "total_spend", ["channel", "total_spend"]),
]


@pytest.mark.parametrize("question,intent,tables,measure,expected_cols", CASES)
def test_plan_fields(schema, question, intent, tables, measure, expected_cols):
    plan = planner_service.create_plan(question, schema)
    assert plan.matched is True
    assert plan.intent == intent
    assert plan.question == question
    assert plan.target_connection == "demo"
    assert 0.5 <= plan.confidence <= 1.0
    assert set(plan.required_tables) == tables
    assert any(measure in m for m in plan.measures)
    assert plan.expected_result_columns == expected_cols
    # Every required column is fully qualified and belongs to a required table.
    assert plan.required_columns
    for col in plan.required_columns:
        table, _, _ = col.partition(".")
        assert table in tables
    # One join condition per additional table.
    assert len(plan.joins) == len(plan.required_tables) - 1
    # Structured fields are lists / optional int.
    assert isinstance(plan.dimensions, list)
    assert isinstance(plan.filters, list)
    assert isinstance(plan.group_by, list)
    assert isinstance(plan.order_by, list)
    assert plan.limit is None or isinstance(plan.limit, int)


def test_plan_has_join_and_order_by_for_top_products(schema):
    plan = planner_service.create_plan("top 5 products by revenue", schema)
    assert plan.joins == ["order_items.product_id = products.id"]
    assert plan.group_by == ["products.name"]
    assert plan.order_by == ["revenue DESC"]
    assert plan.limit == 5


def test_plan_has_filter_for_open_tickets(schema):
    plan = planner_service.create_plan("how many support tickets are open?", schema)
    assert plan.filters == ["support_tickets.status = 'open'"]


def test_plan_confidence_is_deterministic_and_reflects_coverage(schema):
    canonical = planner_service.create_plan("top products by revenue", schema)
    # Same question -> identical confidence (deterministic).
    assert canonical.confidence == planner_service.create_plan(
        "top products by revenue", schema
    ).confidence
    # A question padded with unrecognized words scores no higher.
    noisy = planner_service.create_plan(
        "hey friend kindly reveal top products by revenue pretty please", schema
    )
    assert noisy.confidence <= canonical.confidence


def test_plan_month_expression_matches_dialect(schema):
    plan = planner_service.create_plan("total revenue by month", schema)
    assert any("strftime" in d for d in plan.dimensions)  # sqlite demo

    pg_schema = schema.model_copy(update={"dialect": "postgresql"})
    pg_plan = planner_service.create_plan("total revenue by month", pg_schema)
    assert any("to_char" in d for d in pg_plan.dimensions)
    assert not any("strftime" in d for d in pg_plan.dimensions)


def test_unsupported_question_plan(schema):
    plan = planner_service.create_plan("what is the weather tomorrow?", schema)
    assert plan.matched is False
    assert plan.intent == "unsupported"
    assert plan.confidence == 0.0
    assert plan.question == "what is the weather tomorrow?"
    assert plan.target_connection == "demo"
    assert plan.required_tables == []
    assert plan.measures == []


def test_plan_unsupported_when_required_tables_missing(schema):
    """A matched intent whose tables aren't in the schema is unsupported."""
    tiny = schema.model_copy(
        update={"tables": [t for t in schema.tables if t.name == "customers"]}
    )
    plan = planner_service.create_plan("top 5 products by revenue", tiny)
    assert plan.matched is False
    assert plan.intent == "unsupported"


# --- plan in the API response only when show_debug=true --------------------

def test_query_omits_plan_by_default():
    resp = TestClient(app).post("/query", json={"question": "top 5 products by revenue"})
    assert resp.status_code == 200
    assert resp.json()["plan"] is None


def test_query_includes_plan_with_show_debug():
    resp = TestClient(app).post(
        "/query", json={"question": "top 5 products by revenue", "show_debug": True}
    )
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    assert plan is not None
    assert plan["intent"] == "top_products_by_revenue"
    assert plan["required_tables"] == ["order_items", "products"]
    assert plan["group_by"] == ["products.name"]
    assert plan["order_by"] == ["revenue DESC"]
    assert plan["limit"] == 5
    assert plan["expected_result_columns"] == ["product_name", "revenue"]
    assert plan["target_connection"] == "demo"
    assert plan["confidence"] > 0.0


def test_query_includes_plan_for_unsupported_with_show_debug():
    resp = TestClient(app).post(
        "/query", json={"question": "tell me a joke", "show_debug": True}
    )
    assert resp.status_code == 200
    plan = resp.json()["plan"]
    assert plan is not None
    assert plan["matched"] is False
    assert plan["intent"] == "unsupported"
    assert plan["confidence"] == 0.0
