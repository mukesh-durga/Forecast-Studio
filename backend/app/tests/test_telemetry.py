"""Tests for per-query telemetry and cost tracking."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes_query import provide_sql_generator
from app.main import app
from app.services import history_service
from app.services.sql_generator import (
    GeneratedSql,
    GroqSqlGenerator,
    LocalSqlGenerator,
    SqlGenerator,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_telemetry_omitted_without_debug(client):
    resp = client.post("/query", json={"question": "top 5 products by revenue"})
    assert resp.status_code == 200
    assert resp.json()["telemetry"] is None


ALL_LATENCY_FIELDS = (
    "planner_latency_ms",
    "generation_latency_ms",
    "sample_execution_latency_ms",
    "final_execution_latency_ms",
    "verification_latency_ms",
    "total_latency_ms",
)


def test_local_telemetry_fields_and_zero_cost(client):
    resp = client.post(
        "/query", json={"question": "top 5 products by revenue", "show_debug": True}
    )
    assert resp.status_code == 200
    t = resp.json()["telemetry"]
    assert t is not None
    assert t["provider"] == "local"
    # Every per-phase latency is present and non-negative.
    for key in ALL_LATENCY_FIELDS:
        assert t[key] >= 0
    # Total covers the individual phases (sum <= total, allowing overhead).
    phase_sum = (
        t["planner_latency_ms"] + t["generation_latency_ms"]
        + t["sample_execution_latency_ms"] + t["final_execution_latency_ms"]
        + t["verification_latency_ms"]
    )
    assert t["total_latency_ms"] >= phase_sum - 0.01
    # Flow flags present.
    assert t["cache_hit"] is False
    assert t["repair_attempted"] is False
    # Local provider costs nothing and uses no tokens.
    assert t["estimated_prompt_tokens"] == 0
    assert t["estimated_completion_tokens"] == 0
    assert t["estimated_cost_usd"] == 0.0


def test_cache_hit_telemetry_is_cache_provider_zero_cost(client):
    client.post("/query", json={"question": "top 5 products by revenue"})
    resp = client.post(
        "/query", json={"question": "top 5 products by revenue", "show_debug": True}
    )
    body = resp.json()
    assert body["cache_hit"] is True
    t = body["telemetry"]
    assert t["provider"] == "cache"
    assert t["cache_hit"] is True
    assert t["estimated_cost_usd"] == 0.0
    assert t["estimated_total_tokens"] == 0


def test_groq_telemetry_has_tokens_and_cost(client):
    gen = GroqSqlGenerator(
        api_key="k", model="m", fallback=LocalSqlGenerator(), timeout=1.0
    )
    sql = "SELECT city, COUNT(*) AS c FROM customers GROUP BY city LIMIT 5"
    with patch.object(gen, "_complete", return_value=sql):
        app.dependency_overrides[provide_sql_generator] = lambda: gen
        try:
            resp = client.post(
                "/query", json={"question": "list cities by customers", "show_debug": True}
            )
        finally:
            app.dependency_overrides.clear()

    t = resp.json()["telemetry"]
    assert t["provider"] == "groq"
    assert t["estimated_prompt_tokens"] > 0
    assert t["estimated_completion_tokens"] > 0
    assert t["estimated_total_tokens"] == (
        t["estimated_prompt_tokens"] + t["estimated_completion_tokens"]
    )
    assert t["estimated_cost_usd"] > 0.0


class _MissingColumnGenerator(SqlGenerator):
    backend_name = "local"

    def generate(self, question, schema, plan=None):
        return GeneratedSql(
            sql="SELECT city FROM customers GROUP BY city",  # missing customer_count
            intent="city_most_customers", matched=True,
        )


def test_repair_attempted_flag_in_telemetry(client):
    app.dependency_overrides[provide_sql_generator] = lambda: _MissingColumnGenerator()
    try:
        resp = client.post(
            "/query",
            json={"question": "Which city has the most customers?", "show_debug": True},
        )
    finally:
        app.dependency_overrides.pop(provide_sql_generator, None)
    t = resp.json()["telemetry"]
    assert t["repair_attempted"] is True
    assert t["sample_execution_latency_ms"] >= 0


def test_telemetry_is_stored_in_history(client):
    client.post("/query", json={"question": "How many support tickets are still open?"})
    with history_service._connect() as conn:
        row = conn.execute(
            "SELECT provider, planner_ms, generation_ms, sample_execution_ms, "
            "final_execution_ms, total_ms, estimated_cost_usd "
            "FROM query_history ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "local"           # provider
    for i in range(1, 6):              # every latency column stored, non-negative
        assert row[i] is not None and row[i] >= 0
    assert row[6] == 0.0               # estimated_cost_usd (local)
