"""Tests for the sample execution + self-check + repair loop (Milestone 17).

Free, offline (local generator + SQLite demo DB). No paid API, no network.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import routes_query
from app.api.routes_query import provide_sql_generator
from app.main import app
from app.services import planner_service, schema_service, self_check_service
from app.services.sql_generator import GeneratedSql, SqlGenerator


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def schema():
    return schema_service.get_schema("demo")


# --- pure self-check logic -------------------------------------------------

def test_valid_sample_passes_check(schema):
    plan = planner_service.create_plan("Which city has the most customers?", schema)
    check = self_check_service.check_sample(
        plan,
        columns=["city", "customer_count"],
        rows=[{"city": "Austin", "customer_count": 5}],
        row_count=1,
    )
    assert check.passed is True
    assert check.reason is None
    assert check.sample_row_count == 1


def test_missing_expected_column_fails_check(schema):
    plan = planner_service.create_plan("Which city has the most customers?", schema)
    check = self_check_service.check_sample(
        plan,
        columns=["city"],  # customer_count missing
        rows=[{"city": "Austin"}],
        row_count=1,
    )
    assert check.passed is False
    assert "missing_columns" in check.reason
    assert "customer_count" in check.reason


def test_empty_result_fails_check(schema):
    plan = planner_service.create_plan("Which city has the most customers?", schema)
    check = self_check_service.check_sample(
        plan, columns=["city", "customer_count"], rows=[], row_count=0
    )
    assert check.passed is False
    assert check.reason == "empty_result"


def test_single_aggregate_shape_mismatch_fails_check(schema):
    plan = planner_service.create_plan("What is the average order value?", schema)
    # A single-aggregate query must collapse to exactly one row.
    check = self_check_service.check_sample(
        plan,
        columns=["average_order_value"],
        rows=[{"average_order_value": 1}, {"average_order_value": 2}],
        row_count=2,
    )
    assert check.passed is False
    assert check.reason == "aggregate_shape_mismatch"


def test_build_sample_sql_uses_stricter_limit(schema):
    plan = planner_service.create_plan("total revenue by month", schema)
    from app.services.sql_generator import render_sql_from_plan
    from app.services.sql_guard import validate_sql

    safe = validate_sql(render_sql_from_plan(plan))  # LIMIT 100 injected
    sample = self_check_service.build_sample_sql(safe)
    assert sample.rstrip().endswith("LIMIT 5")


def test_repair_sql_rerender_from_plan(schema):
    plan = planner_service.create_plan("Which city has the most customers?", schema)
    repaired = self_check_service.repair_sql(plan)
    assert repaired is not None
    assert "customer_count" in repaired
    assert "GROUP BY customers.city" in repaired


def test_repair_sql_none_for_unmatched_plan(schema):
    plan = planner_service.create_plan("tell me a joke", schema)
    assert self_check_service.repair_sql(plan) is None


# --- end-to-end through POST /query ----------------------------------------

def test_supported_query_reports_sample_checked(client):
    resp = client.post(
        "/query",
        json={"question": "Which city has the most customers?", "connection_id": "demo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_checked"] is True
    assert body["sample_row_count"] >= 1
    assert body["repair_attempted"] is False
    assert body["repair_successful"] is False


def test_unsupported_query_is_not_sample_checked(client):
    resp = client.post("/query", json={"question": "tell me a joke"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["sample_checked"] is False
    assert body["repair_attempted"] is False


class _MissingColumnGenerator(SqlGenerator):
    """Drafts SQL that omits an expected column, so the sample check fails and a
    repair is triggered. Real, executable SQL — just the wrong projection."""

    backend_name = "local"

    def generate(self, question, schema, plan=None):
        # city_most_customers expects [city, customer_count]; drop customer_count.
        return GeneratedSql(
            sql="SELECT city FROM customers GROUP BY city",
            intent="city_most_customers",
            matched=True,
        )


def test_repair_attempted_once_and_succeeds(client):
    app.dependency_overrides[provide_sql_generator] = lambda: _MissingColumnGenerator()
    try:
        resp = client.post(
            "/query",
            json={"question": "Which city has the most customers?", "connection_id": "demo"},
        )
    finally:
        app.dependency_overrides.pop(provide_sql_generator, None)

    assert resp.status_code == 200
    body = resp.json()
    # The draft failed the sample check; one repair ran and fixed it.
    assert body["sample_checked"] is True
    assert body["repair_attempted"] is True
    assert body["repair_successful"] is True
    # Final result is the repaired, correct shape.
    assert body["columns"] == ["city", "customer_count"]
    assert body["verification"]["verified"] is True


def test_unsafe_repair_is_rejected(client, monkeypatch):
    """If the repair step proposes unsafe SQL, the guard rejects it, the repair
    is not adopted, and the unsafe SQL is never executed."""
    monkeypatch.setattr(
        self_check_service, "repair_sql", lambda plan: "DELETE FROM customers"
    )
    app.dependency_overrides[provide_sql_generator] = lambda: _MissingColumnGenerator()
    try:
        resp = client.post(
            "/query",
            json={"question": "Which city has the most customers?", "connection_id": "demo"},
        )
    finally:
        app.dependency_overrides.pop(provide_sql_generator, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["repair_attempted"] is True
    assert body["repair_successful"] is False
    # Never executed the unsafe repair; the returned SQL is a SELECT.
    assert body["sql"].strip().upper().startswith("SELECT")
    assert "DELETE" not in body["sql"].upper()


def test_repair_helper_rejects_unsafe_sql_directly(monkeypatch):
    """Unit-level: the repair path re-guards, so unsafe repair SQL is discarded
    and the original safe SQL is kept."""
    schema = schema_service.get_schema("demo")
    plan = planner_service.create_plan("Which city has the most customers?", schema)
    safe = "SELECT city FROM customers GROUP BY city LIMIT 100"  # fails check (missing col)
    monkeypatch.setattr(
        self_check_service, "repair_sql", lambda plan: "DROP TABLE customers"
    )
    final_sql, meta = routes_query._sample_check_and_repair("demo", safe, plan)
    assert meta["repair_attempted"] is True
    assert meta["repair_successful"] is False
    assert final_sql == safe  # unsafe repair rejected -> original kept
