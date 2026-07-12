"""Tests for the optional Groq SQL-generation provider.

The Groq API is ALWAYS mocked here (via `_complete`) — no network, no real
Groq calls, and the `groq` package need not be installed to run these.

Run with:  cd backend && pytest app/tests/test_groq_provider.py -v
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes_query import provide_sql_generator
from app.config import settings
from app.main import app
from app.services import schema_service
from app.services.sql_generator import (
    GroqSqlGenerator,
    LocalSqlGenerator,
    get_sql_generator,
)


@pytest.fixture
def schema():
    return schema_service.get_schema("demo")


def make_groq() -> GroqSqlGenerator:
    return GroqSqlGenerator(
        api_key="test-key", model="test-model", fallback=LocalSqlGenerator(), timeout=1.0
    )


# --- generation behavior (Groq mocked) -------------------------------------

def test_groq_success_returns_guarded_sql(schema):
    gen = make_groq()
    with patch.object(gen, "_complete", return_value="SELECT name FROM customers"):
        res = gen.generate("list customer names", schema)
    assert res.matched is True
    assert res.intent == "groq"
    assert res.sql.upper().startswith("SELECT")
    assert "LIMIT" in res.sql  # guard injected a default LIMIT


def test_groq_strips_markdown_fences(schema):
    gen = make_groq()
    with patch.object(gen, "_complete", return_value="```sql\nSELECT COUNT(*) FROM orders\n```"):
        res = gen.generate("count orders", schema)
    assert res.matched is True
    assert "```" not in res.sql
    assert "COUNT(*)" in res.sql


def test_groq_unsafe_sql_falls_back_to_local(schema):
    """Groq returns a write statement -> guard rejects -> local fallback."""
    gen = make_groq()
    with patch.object(gen, "_complete", return_value="DELETE FROM customers"):
        res = gen.generate("What are the top 5 products by revenue?", schema)
    assert res.matched is True
    assert res.intent == "top_products_by_revenue"  # came from local template
    assert "DELETE" not in res.sql.upper()


def test_groq_error_falls_back_to_local(schema):
    gen = make_groq()
    with patch.object(gen, "_complete", side_effect=RuntimeError("network down")):
        res = gen.generate("How many support tickets are still open?", schema)
    assert res.matched is True
    assert res.intent == "open_tickets"


def test_groq_timeout_on_unsupported_returns_unsupported(schema):
    gen = make_groq()
    with patch.object(gen, "_complete", side_effect=TimeoutError("timed out")):
        res = gen.generate("tell me a joke", schema)
    assert res.matched is False
    assert res.intent == "unsupported"
    assert res.sql == ""


def test_groq_empty_output_falls_back(schema):
    gen = make_groq()
    with patch.object(gen, "_complete", return_value="   "):
        res = gen.generate("Which city has the most customers?", schema)
    assert res.intent == "city_most_customers"


def test_groq_placeholder_sql_is_rejected_and_falls_back(schema):
    """Safe-but-ungrounded placeholder SQL must NOT be accepted as a match."""
    gen = make_groq()
    placeholder = "SELECT NULL AS weather_tomorrow WHERE 1=0 LIMIT 1"
    with patch.object(gen, "_complete", return_value=placeholder):
        res = gen.generate("what is the weather tomorrow?", schema)
    # Rejected by grounding -> local fallback -> unsupported (no fake match).
    assert res.matched is False
    assert res.intent == "unsupported"
    assert res.sql == ""


def test_groq_unknown_table_is_rejected_and_falls_back(schema):
    gen = make_groq()
    with patch.object(gen, "_complete", return_value="SELECT * FROM weather LIMIT 5"):
        res = gen.generate("what is the weather tomorrow?", schema)
    assert res.matched is False
    assert res.intent == "unsupported"


def test_groq_valid_schema_sql_is_accepted(schema):
    """Grounded SQL that uses real tables is accepted as a Groq match."""
    gen = make_groq()
    sql = "SELECT city, COUNT(*) AS c FROM customers GROUP BY city ORDER BY c DESC LIMIT 5"
    with patch.object(gen, "_complete", return_value=sql):
        res = gen.generate("which cities have the most customers by count", schema)
    assert res.matched is True
    assert res.intent == "groq"
    assert "customers" in res.sql.lower()


def test_query_endpoint_weather_question_is_unsupported():
    """End-to-end: Groq placeholder for a weather question -> unsupported, no execution."""
    gen = make_groq()
    placeholder = "SELECT NULL AS weather_tomorrow WHERE 1=0 LIMIT 1"
    with patch.object(gen, "_complete", return_value=placeholder):
        app.dependency_overrides[provide_sql_generator] = lambda: gen
        try:
            resp = TestClient(app).post("/query", json={"question": "what is the weather tomorrow?"})
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["intent"] == "unsupported"
    assert body["sql"] is None
    assert body["guard_passed"] is False
    assert body["row_count"] == 0
    assert body["rows"] == []
    assert body["columns"] == []
    assert body["verification"]["verified"] is False
    assert body["verification"]["failure_reason"] == "unsupported_general_question"
    assert "predefined database analytics questions" in body["message"]
    assert len(body["suggestions"]) > 0


# --- provider selection (factory) ------------------------------------------

def test_factory_defaults_to_local(monkeypatch):
    monkeypatch.setattr(settings, "sql_generator_provider", "local")
    assert isinstance(get_sql_generator(), LocalSqlGenerator)


def test_factory_missing_provider_is_local(monkeypatch):
    monkeypatch.setattr(settings, "sql_generator_provider", "")
    assert isinstance(get_sql_generator(), LocalSqlGenerator)


def test_factory_groq_without_key_uses_local(monkeypatch):
    monkeypatch.setattr(settings, "sql_generator_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "")
    assert isinstance(get_sql_generator(), LocalSqlGenerator)


def test_factory_groq_with_key_uses_groq(monkeypatch):
    monkeypatch.setattr(settings, "sql_generator_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    gen = get_sql_generator()
    assert isinstance(gen, GroqSqlGenerator)
    assert gen.backend_name == "groq"


def test_factory_unknown_provider_uses_local(monkeypatch):
    monkeypatch.setattr(settings, "sql_generator_provider", "acme-llm")
    assert isinstance(get_sql_generator(), LocalSqlGenerator)


# --- end-to-end via POST /query (Groq mocked) ------------------------------

def test_query_endpoint_executes_groq_sql():
    gen = make_groq()
    with patch.object(gen, "_complete", return_value="SELECT name, city FROM customers LIMIT 5"):
        app.dependency_overrides[provide_sql_generator] = lambda: gen
        try:
            resp = TestClient(app).post("/query", json={"question": "show me customers"})
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["generator"] == "groq"
    assert body["matched"] is True
    assert body["columns"] == ["name", "city"]
    assert body["row_count"] > 0
    assert "LIMIT" in body["sql"]  # guard-enforced, executed read-only
