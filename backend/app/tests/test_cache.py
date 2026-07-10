"""Tests for query history + semantic-dedup cache.

Each test gets an isolated, empty metadata store (see conftest).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.responses import Telemetry
from app.services import history_service, schema_service


@pytest.fixture
def client():
    return TestClient(app)


def _telemetry() -> Telemetry:
    return Telemetry(
        provider="local", generation_ms=0.0, execution_ms=0.0,
        verification_ms=0.0, total_ms=0.0,
    )


def _seed(
    *, connection_id="demo", question, intent, schema_version="sig-a",
    verified=True, sql="SELECT 1 AS a LIMIT 5",
):
    """Insert one query_history row for cache unit tests."""
    history_service.record(
        connection_id=connection_id, question=question,
        normalized_question=history_service.normalize(question),
        generated_sql=sql, intent=intent, schema_version=schema_version,
        row_count=1, verified=verified, cache_hit=False, telemetry=_telemetry(),
        confidence=0.9 if verified else 0.0, runtime_ms=1.0,
    )


# --- unit: normalization + similarity --------------------------------------

def test_normalize_ignores_case_and_punctuation():
    assert history_service.normalize("What are the TOP 5 products by revenue?!") == (
        "what are the top 5 products by revenue"
    )


def test_jaccard_identity_and_disjoint():
    assert history_service.jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert history_service.jaccard({"a"}, {"b"}) == 0.0


def test_content_tokens_drop_stopwords_make_paraphrase_equal():
    a = history_service.content_tokens("What are the top 5 products by revenue")
    b = history_service.content_tokens("Show me the top 5 products by revenue")
    assert a == b  # both -> {top, 5, products, revenue}


def test_schema_version_stable():
    schema = schema_service.get_schema("demo")
    assert history_service.schema_version(schema) == history_service.schema_version(schema)


# --- endpoint: exact + near-duplicate cache hits ---------------------------

def test_first_query_is_a_cache_miss(client):
    resp = client.post("/query", json={"question": "What are the top 5 products by revenue?"})
    assert resp.status_code == 200
    assert resp.json()["cache_hit"] is False


def test_exact_cache_hit(client):
    q = "What are the top 5 products by revenue?"
    first = client.post("/query", json={"question": q}).json()
    assert first["cache_hit"] is False

    # Same question (different casing/punctuation) -> exact cache hit.
    second = client.post("/query", json={"question": "what are the TOP 5 products by revenue!!!"}).json()
    assert second["cache_hit"] is True
    assert second["sql"] == first["sql"]
    assert second["row_count"] == first["row_count"]


def test_near_duplicate_cache_hit(client):
    first = client.post("/query", json={"question": "What are the top 5 products by revenue?"}).json()
    assert first["cache_hit"] is False

    # Paraphrase (not an exact string match) -> semantic cache hit.
    second = client.post("/query", json={"question": "Show me the top 5 products by revenue"}).json()
    assert second["cache_hit"] is True
    assert second["sql"] == first["sql"]
    assert second["generator"] == "cache"


def test_different_question_is_not_a_cache_hit(client):
    client.post("/query", json={"question": "What are the top 5 products by revenue?"})
    other = client.post("/query", json={"question": "Which city has the most customers?"}).json()
    assert other["cache_hit"] is False
    assert other["intent"] == "city_most_customers"


def test_history_is_recorded(client):
    client.post("/query", json={"question": "How many support tickets are still open?"})
    with history_service._connect() as conn:
        rows = conn.execute(
            "SELECT question, intent, generated_sql, confidence, runtime_ms FROM query_history"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "open_tickets"
    assert rows[0][2] and "support_tickets" in rows[0][2]
    assert rows[0][3] is not None and rows[0][3] > 0  # confidence stored
    assert rows[0][4] is not None                     # runtime_ms stored


# --- reuse constraints: intent, schema, verified (Milestone 18) ------------

def test_exact_hit_reports_match_score(client):
    q = "What are the top 5 products by revenue?"
    client.post("/query", json={"question": q})
    second = client.post("/query", json={"question": q, "show_debug": True}).json()
    assert second["cache_hit"] is True
    assert second["cache_match_score"] == 1.0
    assert second["cached_from_question"] == q


def test_cached_from_question_hidden_without_debug(client):
    q = "What are the top 5 products by revenue?"
    client.post("/query", json={"question": q})
    second = client.post("/query", json={"question": q}).json()
    assert second["cache_hit"] is True
    assert second["cached_from_question"] is None  # not exposed without show_debug


def test_semantic_dedup_requires_same_intent():
    # A verified entry for one intent must NOT be reused for a different intent,
    # even when the questions share tokens.
    _seed(question="top revenue leaders", intent="top_products_by_revenue")
    hit = history_service.find_cached(
        "demo", history_service.normalize("top revenue leaders"),
        "sig-a", 0.5, intent="category_revenue",
    )
    assert hit is None


def test_schema_mismatch_is_not_a_cache_hit():
    _seed(question="top 5 products by revenue", intent="top_products_by_revenue",
          schema_version="sig-a")
    hit = history_service.find_cached(
        "demo", history_service.normalize("top 5 products by revenue"),
        "sig-DIFFERENT", 0.5, intent="top_products_by_revenue",
    )
    assert hit is None


def test_unverified_result_is_not_reused():
    _seed(question="top 5 products by revenue", intent="top_products_by_revenue",
          verified=False)
    hit = history_service.find_cached(
        "demo", history_service.normalize("top 5 products by revenue"),
        "sig-a", 0.5, intent="top_products_by_revenue",
    )
    assert hit is None


def test_unmatched_intent_never_hits_cache():
    _seed(question="top 5 products by revenue", intent="top_products_by_revenue")
    assert history_service.find_cached(
        "demo", history_service.normalize("top 5 products by revenue"),
        "sig-a", 0.5, intent=None,
    ) is None


def test_semantic_partial_overlap_hit_reports_source_and_score():
    # Stored question has 7 content tokens; the query shares 6 -> Jaccard 6/7≈0.857.
    stored_q = "alpha bravo charlie delta echo foxtrot golf"
    query_q = "alpha bravo charlie delta echo foxtrot"  # drops 'golf'
    _seed(question=stored_q, intent="synthetic")
    hit = history_service.find_cached(
        "demo", history_service.normalize(query_q), "sig-a", 0.85, intent="synthetic",
    )
    assert hit is not None
    assert hit.kind == "semantic"
    assert 0.85 <= hit.similarity < 1.0
    assert hit.source_question == stored_q


def test_semantic_below_threshold_is_a_miss():
    _seed(question="alpha bravo charlie delta echo", intent="synthetic")
    # Shares 2 of 5 -> Jaccard well under 0.85.
    hit = history_service.find_cached(
        "demo", history_service.normalize("alpha bravo whiskey xray yankee"),
        "sig-a", 0.85, intent="synthetic",
    )
    assert hit is None


def test_cache_disabled_skips_lookup(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "cache_enabled", False)
    q = "What are the top 5 products by revenue?"
    client.post("/query", json={"question": q})
    second = client.post("/query", json={"question": q}).json()
    assert second["cache_hit"] is False
