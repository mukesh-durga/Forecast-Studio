"""Tests for the full POST /query execution flow.

Free, offline (local generator + SQLite demo DB). No paid API, no network.
Run with:

    cd backend && pytest app/tests/test_query_flow.py -v
"""

import pytest
from fastapi.testclient import TestClient

from app.api.routes_query import provide_sql_generator
from app.main import app
from app.services import execution_service
from app.services.sql_generator import GeneratedSql, SqlGenerator


@pytest.fixture
def client():
    return TestClient(app)


def test_query_returns_rows_for_top_products(client):
    resp = client.post(
        "/query",
        json={"question": "What are the top 5 products by revenue?", "connection_id": "demo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dialect"] == "sqlite"
    assert body["generator"] == "local"
    assert body["intent"] == "top_products_by_revenue"
    assert body["guard_passed"] is True
    assert body["columns"] == ["product_name", "revenue"]
    assert 1 <= body["row_count"] <= 5
    assert len(body["rows"]) == body["row_count"]
    # Rows carry the selected columns.
    assert "product_name" in body["rows"][0]
    assert "revenue" in body["rows"][0]
    assert body["runtime_ms"] >= 0


def test_query_open_tickets_returns_a_count(client):
    resp = client.post("/query", json={"question": "How many support tickets are still open?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "open_tickets"
    assert body["row_count"] == 1
    assert body["columns"] == ["open_tickets"]
    assert isinstance(body["rows"][0]["open_tickets"], int)


def test_query_defaults_to_demo_connection(client):
    resp = client.post("/query", json={"question": "average order value"})
    assert resp.status_code == 200
    assert resp.json()["connection_id"] == "demo"


def test_query_unknown_connection_returns_404(client):
    resp = client.post("/query", json={"question": "x", "connection_id": "nope"})
    assert resp.status_code == 404


def test_query_unsupported_question_does_not_execute(client):
    resp = client.post("/query", json={"question": "what's the weather tomorrow?"})
    assert resp.status_code == 200
    body = resp.json()
    # Honest unsupported response — nothing was executed, nothing fabricated.
    assert body["matched"] is False
    assert body["intent"] == "unsupported"
    assert body["sql"] is None
    assert body["guard_passed"] is False
    assert body["row_count"] == 0
    assert body["rows"] == []
    assert body["columns"] == []
    # Verification present, explicitly unverified with the unsupported reason.
    assert body["verification"]["verified"] is False
    assert body["verification"]["failure_reason"] == "unsupported_question"
    # Exact, naturally-spaced user-facing strings (no missing spaces).
    assert body["message"] == (
        "This local demo currently supports predefined database analytics questions. "
        "Try one of the examples below."
    )
    assert body["verification"]["explanation"] == (
        "No supported database analytics question matched, so no SQL was generated or executed."
    )
    # Guard against the reported concatenation typos.
    for glued in ("SQLwas", "currentlysupports", "databaseanalytics", "questionmatched"):
        assert glued not in body["message"] + body["verification"]["explanation"]
    assert len(body["suggestions"]) > 0


def test_supported_question_still_executes_and_verifies(client):
    """Guard against regressions: supported questions are unchanged."""
    resp = client.post("/query", json={"question": "What are the top 5 products by revenue?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["intent"] == "top_products_by_revenue"
    assert body["row_count"] > 0
    assert body["verification"]["verified"] is True
    assert body["sql"] and "LIMIT" in body["sql"]


@pytest.mark.parametrize(
    "question",
    [
        "Which products made the most revenue?",
        "Which products generated the highest sales revenue?",
    ],
)
def test_top_products_paraphrases_end_to_end(client, question):
    resp = client.post("/query", json={"question": question, "connection_id": "demo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["intent"] == "top_products_by_revenue"
    assert body["columns"] == ["product_name", "revenue"]
    assert body["sql"] and body["sql"].strip().upper().startswith("SELECT")
    assert 1 <= body["row_count"] <= 5


def test_supported_sql_and_explanation_spacing(client):
    """Endpoint-level regression (TestClient -> POST /query): the live response
    SQL and verification explanation must be naturally spaced."""
    resp = client.post("/query", json={"question": "What are the top 5 products by revenue?"})
    assert resp.status_code == 200
    body = resp.json()

    # Final /query response SQL — exact expected substring, no glued 'ONo'.
    assert "JOIN products ON order_items.product_id = products.id" in body["sql"]
    assert " ON order_items." in body["sql"]
    assert "ONorder_items" not in body["sql"]

    # Verification explanation — exact expected substring, no glued 'returns['.
    assert body["verification"]["verified"] is True
    assert "The query returns ['product_name', 'revenue']" in body["verification"]["explanation"]
    assert "returns[" not in body["verification"]["explanation"]


class _UnsafeGenerator(SqlGenerator):
    """A generator that emits a write statement — must never be executed."""

    backend_name = "unsafe-test"

    def generate(self, question, schema, plan=None):
        # matched=True so it reaches the guard (an unsupported/matched=False
        # question short-circuits before execution and is never guarded).
        return GeneratedSql(sql="DELETE FROM customers", intent="evil", matched=True)


def test_query_never_executes_unsafe_sql(client):
    """The guard must block a write statement before execution (422)."""
    app.dependency_overrides[provide_sql_generator] = lambda: _UnsafeGenerator()
    try:
        resp = client.post("/query", json={"question": "delete everything"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert "guard" in resp.json()["detail"].lower()
    # Confirm the demo table is untouched (read-only guarantee still holds).
    check = execution_service.execute("demo", "SELECT COUNT(*) AS c FROM customers")
    assert check.rows[0]["c"] > 0


def test_execution_service_runs_guarded_sql_directly():
    result = execution_service.execute("demo", "SELECT city FROM customers LIMIT 3")
    assert result.columns == ["city"]
    assert result.row_count == 3
    assert result.runtime_ms >= 0
