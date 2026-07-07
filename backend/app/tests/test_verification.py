"""Tests for the free local verification service.

No paid API, no network. Run with:

    cd backend && pytest app/tests/test_verification.py -v
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import verification_service


@pytest.fixture
def client():
    return TestClient(app)


# --- unit tests on verification_service.verify -----------------------------

def test_verify_top_products_success():
    v = verification_service.verify(
        intent="top_products_by_revenue",
        matched=True,
        sql="SELECT p.name AS product_name, SUM(x) AS revenue FROM t GROUP BY p.name",
        columns=["product_name", "revenue"],
        rows=[{"product_name": "Chair", "revenue": 100}],
        row_count=1,
    )
    assert v.verified is True
    assert v.confidence >= 0.7
    assert v.failure_reason is None


def test_verify_city_customers_success():
    v = verification_service.verify(
        intent="city_most_customers",
        matched=True,
        sql="SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city",
        columns=["city", "customer_count"],
        rows=[{"city": "Austin", "customer_count": 5}],
        row_count=1,
    )
    assert v.verified is True


def test_verify_monthly_revenue_success():
    v = verification_service.verify(
        intent="monthly_revenue",
        matched=True,
        sql="SELECT strftime('%Y-%m', d) AS month, SUM(x) AS revenue FROM t GROUP BY month",
        columns=["month", "revenue"],
        rows=[{"month": "2026-01", "revenue": 500}],
        row_count=3,
    )
    assert v.verified is True


def test_verify_open_tickets_success():
    v = verification_service.verify(
        intent="open_tickets",
        matched=True,
        sql="SELECT COUNT(*) AS open_tickets FROM support_tickets WHERE status = 'open'",
        columns=["open_tickets"],
        rows=[{"open_tickets": 8}],
        row_count=1,
    )
    assert v.verified is True


def test_verify_fails_on_missing_column():
    v = verification_service.verify(
        intent="top_products_by_revenue",
        matched=True,
        sql="SELECT p.name AS product_name FROM t GROUP BY p.name",
        columns=["product_name"],           # missing "revenue"
        rows=[{"product_name": "Chair"}],
        row_count=1,
    )
    assert v.verified is False
    assert v.failure_reason.startswith("missing_expected_columns")
    assert 0.0 <= v.confidence <= 1.0


def test_verify_fails_on_no_rows():
    v = verification_service.verify(
        intent="open_tickets",
        matched=True,
        sql="SELECT COUNT(*) AS open_tickets FROM support_tickets WHERE status = 'open'",
        columns=["open_tickets"],
        rows=[],
        row_count=0,
    )
    assert v.verified is False
    assert v.failure_reason == "no_rows"


def test_verify_unmatched_question_low_confidence():
    v = verification_service.verify(
        intent=None,
        matched=False,
        sql="SELECT * FROM customers",
        columns=["id", "name"],
        rows=[{"id": 1, "name": "Ava"}],
        row_count=1,
    )
    assert v.verified is False
    assert v.confidence <= 0.3
    assert v.failure_reason == "unmatched_question"


# --- end-to-end via POST /query --------------------------------------------

def test_query_includes_verification_verified(client):
    resp = client.post("/query", json={"question": "What are the top 5 products by revenue?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verification"]["verified"] is True
    assert body["verification"]["confidence"] >= 0.7
    assert body["verification"]["failure_reason"] is None


def test_query_unsupported_question_is_unverified(client):
    resp = client.post("/query", json={"question": "tell me a joke"})
    assert resp.status_code == 200
    body = resp.json()
    # Unsupported: no fabricated answer; verification is explicitly unverified.
    assert body["matched"] is False
    assert body["intent"] == "unsupported"
    assert body["sql"] is None
    assert body["verification"]["verified"] is False
    assert body["verification"]["failure_reason"] == "unsupported_question"
