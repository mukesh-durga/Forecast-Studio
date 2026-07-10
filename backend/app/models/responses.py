"""Pydantic response models for the API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ColumnSchema(BaseModel):
    name: str
    type: str
    primary_key: bool
    nullable: bool


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnSchema]
    row_count: int
    sample_rows: list[dict[str, Any]]


class SchemaResponse(BaseModel):
    connection_id: str
    dialect: str
    table_count: int
    tables: list[TableSchema]


class GenerateSqlResponse(BaseModel):
    question: str
    connection_id: str
    dialect: str
    generator: str                    # which backend produced the SQL (e.g. "local")
    matched: bool                     # did a known template match the question?
    intent: Optional[str] = None      # name of the matched template, if any
    raw_sql: str                      # exactly what the generator produced
    sql: Optional[str] = None         # safe, LIMIT-enforced SQL (when guard passes)
    guard_passed: bool
    guard_error: Optional[str] = None  # why the guard rejected it, if it did


class Verification(BaseModel):
    verified: bool
    confidence: float                 # 0.0 - 1.0
    explanation: str
    failure_reason: Optional[str] = None


class QueryPlan(BaseModel):
    """Structured plan derived from the question before SQL generation.

    The planner decomposes the question into this plan; the local generator
    renders SQL *from the plan* (see ``sql_generator.render_sql_from_plan``)
    and LLM providers receive it as guidance alongside the schema.
    """

    question: str = ""
    intent: str
    matched: bool
    confidence: float = 0.0              # deterministic 0.0-1.0 (see planner)
    target_connection: str = ""          # connection the plan was built against
    required_tables: list[str] = []
    required_columns: list[str] = []     # fully-qualified input columns used
    joins: list[str] = []
    measures: list[str] = []
    dimensions: list[str] = []
    filters: list[str] = []
    group_by: list[str] = []
    order_by: list[str] = []
    limit: Optional[int] = None
    expected_result_columns: list[str] = []  # output column names the SQL must yield


class Telemetry(BaseModel):
    provider: str                          # "local" | "groq" | "cache"
    # Per-phase latencies (milliseconds).
    planner_latency_ms: float = 0.0
    generation_latency_ms: float = 0.0
    sample_execution_latency_ms: float = 0.0
    final_execution_latency_ms: float = 0.0
    verification_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    # Flow flags.
    cache_hit: bool = False
    repair_attempted: bool = False
    # Token + cost estimates (estimated only; exact for local = 0).
    estimated_prompt_tokens: int = 0       # ~chars/4 for Groq; 0 for local/cache
    estimated_completion_tokens: int = 0
    estimated_total_tokens: int = 0
    estimated_cost_usd: float = 0.0        # 0 for local / cache


class QueryResponse(BaseModel):
    question: str
    connection_id: str
    dialect: str
    generator: str                    # backend that produced the SQL (e.g. "local")
    matched: bool                     # did a known template match the question?
    intent: Optional[str] = None      # matched template name, or "unsupported"
    sql: Optional[str] = None         # guarded SQL that was executed; None if unsupported
    guard_passed: bool                # True for executed queries; False when unsupported
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    runtime_ms: float = 0.0
    verification: Optional[Verification] = None  # None when nothing was executed
    message: Optional[str] = None     # user-facing note (set for unsupported questions)
    suggestions: list[str] = []       # example questions to try (unsupported questions)
    plan: Optional[QueryPlan] = None  # structured plan; only included when show_debug=true
    cache_hit: bool = False           # True when SQL was reused from the dedup cache
    cache_match_score: float = 0.0    # 1.0 exact, Jaccard for semantic, 0.0 on miss
    cached_from_question: Optional[str] = None  # source question; only when show_debug=true
    # Sample execution + self-check loop metadata (always present).
    sample_checked: bool = False      # True if the draft was run+checked on a sample
    sample_row_count: int = 0         # rows the sample query returned
    repair_attempted: bool = False    # True if the sample check failed and a repair ran
    repair_successful: bool = False   # True if a repaired query passed the sample check
    telemetry: Optional[Telemetry] = None  # per-query timing/cost; only when show_debug=true
