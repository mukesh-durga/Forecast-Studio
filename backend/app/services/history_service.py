"""Query history + semantic-dedup cache (metadata store).

Stores every executed query in a small SQLite ``query_history`` table (separate
from the read-only demo databases) and answers cache lookups:

  1. exact match on the normalized question, then
  2. near-duplicate match via Jaccard similarity on content tokens.

A cached SQL is only reused when the incoming question shares the same
connection_id, schema_version (schema signature), and intent, and the cached
result was verified — so a schema change, a different intent, or an unverified
prior result all invalidate the reuse.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.models.responses import SchemaResponse, Telemetry

_WORD_RE = re.compile(r"[a-z0-9]+")

# Common filler words removed before computing token similarity, so that
# "What are the top 5 products by revenue" and "Show me the top 5 products by
# revenue" are recognized as the same question.
_STOPWORDS = {
    "the", "a", "an", "of", "is", "are", "was", "were", "to", "in", "on",
    "for", "me", "please", "show", "what", "which", "how", "many", "much",
    "do", "does", "did", "by", "and", "or", "with", "that", "this", "give",
    "list", "tell", "us", "i", "we", "want", "see", "get", "find", "each",
}


@dataclass
class CacheEntry:
    sql: str
    intent: Optional[str]
    kind: str              # "exact" | "semantic"
    similarity: float
    source_question: str   # the original question this cached SQL came from


def normalize(question: str) -> str:
    """Lowercase, keep alphanumerics, collapse whitespace (for exact match)."""
    return " ".join(_WORD_RE.findall(question.lower()))


def content_tokens(text: str) -> set[str]:
    """Alphanumeric tokens with stopwords removed (for similarity)."""
    return {t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def schema_version(schema: SchemaResponse) -> str:
    """Stable short hash of the schema (tables + columns)."""
    parts = [
        f"{t.name}(" + ",".join(f"{c.name}:{c.type}" for c in t.columns) + ")"
        for t in schema.tables
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# Columns added after the original schema (migrated onto pre-existing DBs).
_ADDED_COLUMNS = {
    "provider": "TEXT",
    "planner_ms": "REAL",
    "generation_ms": "REAL",
    "sample_execution_ms": "REAL",
    "final_execution_ms": "REAL",
    "verification_ms": "REAL",
    "total_ms": "REAL",
    "repair_attempted": "INTEGER",
    "prompt_tokens": "INTEGER",
    "completion_tokens": "INTEGER",
    "estimated_cost_usd": "REAL",
    "confidence": "REAL",
    "runtime_ms": "REAL",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.metadata_db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS query_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            connection_id       TEXT NOT NULL,
            question            TEXT NOT NULL,
            normalized_question TEXT NOT NULL,
            generated_sql       TEXT,
            intent              TEXT,
            schema_version      TEXT NOT NULL,
            row_count           INTEGER,
            verified            INTEGER,
            confidence          REAL,
            runtime_ms          REAL,
            cache_hit           INTEGER,
            created_at          TEXT NOT NULL,
            provider            TEXT,
            planner_ms          REAL,
            generation_ms       REAL,
            sample_execution_ms REAL,
            final_execution_ms  REAL,
            verification_ms     REAL,
            total_ms            REAL,
            repair_attempted    INTEGER,
            prompt_tokens       INTEGER,
            completion_tokens   INTEGER,
            estimated_cost_usd  REAL
        )
        """
    )
    # Migrate older tables that predate columns added in later milestones.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(query_history)")}
    for name, col_type in _ADDED_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE query_history ADD COLUMN {name} {col_type}")
    return conn


def record(
    *,
    connection_id: str,
    question: str,
    normalized_question: str,
    generated_sql: Optional[str],
    intent: Optional[str],
    schema_version: str,
    row_count: int,
    verified: bool,
    cache_hit: bool,
    telemetry: Telemetry,
    confidence: float = 0.0,
    runtime_ms: float = 0.0,
) -> None:
    """Append a query (with telemetry) to the history table."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO query_history (
                connection_id, question, normalized_question, generated_sql,
                intent, schema_version, row_count, verified, confidence, runtime_ms,
                cache_hit, created_at,
                provider, planner_ms, generation_ms, sample_execution_ms,
                final_execution_ms, verification_ms, total_ms, repair_attempted,
                prompt_tokens, completion_tokens, estimated_cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                connection_id,
                question,
                normalized_question,
                generated_sql,
                intent,
                schema_version,
                row_count,
                1 if verified else 0,
                confidence,
                runtime_ms,
                1 if cache_hit else 0,
                datetime.now(timezone.utc).isoformat(),
                telemetry.provider,
                telemetry.planner_latency_ms,
                telemetry.generation_latency_ms,
                telemetry.sample_execution_latency_ms,
                telemetry.final_execution_latency_ms,
                telemetry.verification_latency_ms,
                telemetry.total_latency_ms,
                1 if telemetry.repair_attempted else 0,
                telemetry.estimated_prompt_tokens,
                telemetry.estimated_completion_tokens,
                telemetry.estimated_cost_usd,
            ),
        )
        conn.commit()


def find_cached(
    connection_id: str,
    normalized_question: str,
    schema_version: str,
    threshold: float,
    intent: Optional[str],
) -> Optional[CacheEntry]:
    """Return a reusable cached entry (exact first, then near-duplicate).

    A cached SQL is only reused when it shares the same ``connection_id``,
    ``schema_version``, and ``intent`` as the incoming question, and the cached
    result was ``verified``. An unmatched intent (``None``) never hits the cache.
    """
    if not intent:
        return None

    with _connect() as conn:
        conn.row_factory = sqlite3.Row

        # 1. Exact match on the normalized question (same intent + verified).
        exact = conn.execute(
            """
            SELECT question, generated_sql, intent FROM query_history
            WHERE connection_id = ? AND schema_version = ? AND intent = ?
              AND verified = 1
              AND normalized_question = ?
              AND generated_sql IS NOT NULL AND generated_sql != ''
            ORDER BY id DESC LIMIT 1
            """,
            (connection_id, schema_version, intent, normalized_question),
        ).fetchone()
        if exact:
            return CacheEntry(
                sql=exact["generated_sql"], intent=exact["intent"],
                kind="exact", similarity=1.0, source_question=exact["question"],
            )

        # 2. Near-duplicate: only verified rows of the SAME intent are candidates.
        rows = conn.execute(
            """
            SELECT question, normalized_question, generated_sql, intent
            FROM query_history
            WHERE connection_id = ? AND schema_version = ? AND intent = ?
              AND verified = 1
              AND generated_sql IS NOT NULL AND generated_sql != ''
            ORDER BY id DESC LIMIT 300
            """,
            (connection_id, schema_version, intent),
        ).fetchall()

    q_tokens = content_tokens(normalized_question)
    best: Optional[sqlite3.Row] = None
    best_sim = 0.0
    for r in rows:
        sim = jaccard(q_tokens, content_tokens(r["normalized_question"]))
        if sim > best_sim:
            best_sim, best = sim, r

    if best is not None and best_sim >= threshold:
        return CacheEntry(
            sql=best["generated_sql"], intent=best["intent"],
            kind="semantic", similarity=round(best_sim, 3),
            source_question=best["question"],
        )
    return None
