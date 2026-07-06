"""Tests for the POST /query/generate-sql endpoint.

Uses the free local generator — no API key, no network, no dependency overrides.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_generate_sql_endpoint_top_products(client):
    resp = client.post(
        "/query/generate-sql",
        json={"question": "What are the top 5 products by revenue?", "connection_id": "demo"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generator"] == "local"
    assert body["matched"] is True
    assert body["intent"] == "top_products_by_revenue"
    assert body["guard_passed"] is True
    assert "LIMIT" in body["sql"]
    assert body["dialect"] == "sqlite"


def test_generate_sql_endpoint_open_tickets(client):
    resp = client.post("/query/generate-sql", json={"question": "How many support tickets are still open?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "open_tickets"
    assert body["guard_passed"] is True


def test_generate_sql_endpoint_unrecognized_question(client):
    resp = client.post("/query/generate-sql", json={"question": "tell me a joke"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["guard_passed"] is True     # fallback is still a safe SELECT


def test_generate_sql_endpoint_unknown_connection(client):
    resp = client.post("/query/generate-sql", json={"question": "x", "connection_id": "nope"})
    assert resp.status_code == 404


def test_generate_sql_endpoint_defaults_to_demo(client):
    resp = client.post("/query/generate-sql", json={"question": "average order value"})
    assert resp.status_code == 200
    assert resp.json()["connection_id"] == "demo"
