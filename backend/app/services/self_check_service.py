"""Sample execution + self-check loop.

Before returning the full result, the query flow drafts SQL, runs it on a small
**sample** (a stricter LIMIT), and self-checks that sample against the structured
plan. If the sample fails the check, we attempt exactly one deterministic repair
(re-rendering canonical SQL from the plan), re-guard it, and re-check the repaired
sample. A repair is only adopted if it passes; an unsafe repair is rejected by the
guard and discarded.

This module contains only pure logic (build a sample query, check a sample
result, propose a repair). It never executes SQL itself — the route wires those
functions to ``execution_service`` — and it never weakens ``sql_guard``: the
sample and repaired SQL both go through ``validate_sql``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import settings
from app.models.responses import QueryPlan
from app.services.sql_generator import render_sql_from_plan
from app.services.sql_guard import validate_sql


@dataclass
class SampleCheck:
    """Outcome of self-checking a sample result against the plan."""

    passed: bool
    sample_row_count: int
    reason: Optional[str] = None  # why it failed (None when passed)


def build_sample_sql(safe_sql: str) -> str:
    """Return a cheaper, sample version of an already-guarded query.

    Re-runs the guard with a stricter LIMIT (``settings.sample_row_limit``) as
    both the default (injected when missing) and the max (clamps anything
    larger). This reuses the guard's LIMIT logic — it does not weaken it — so
    the sample is always SELECT-only and small.
    """
    return validate_sql(
        safe_sql,
        default_limit=settings.sample_row_limit,
        max_limit=settings.sample_row_limit,
    )


def check_sample(
    plan: QueryPlan,
    columns: list[str],
    rows: list[dict[str, Any]],
    row_count: int,
) -> SampleCheck:
    """Self-check a sample result against what the plan says it should be.

    Checks, in order:
      1. every expected result column is present,
      2. the column *shape* matches (no extra/missing projected columns),
      3. the result is non-empty (all supported intents return >= 1 row),
      4. aggregation/dimension shape is plausible: a grouped query (has
         dimensions) should be able to return more than one group, while a
         single-aggregate query (no dimensions) must return exactly one row.
    """
    result_cols = {c.lower() for c in columns}
    expected = [c.lower() for c in plan.expected_result_columns]

    missing = [c for c in expected if c not in result_cols]
    if missing:
        return SampleCheck(False, row_count, f"missing_columns: {', '.join(missing)}")

    if expected and len(columns) != len(plan.expected_result_columns):
        return SampleCheck(False, row_count, "column_shape_mismatch")

    if row_count == 0:
        return SampleCheck(False, row_count, "empty_result")

    # A single-aggregate query (no GROUP BY dimensions, has a measure) must
    # collapse to exactly one row; anything else means the shape is wrong.
    if plan.measures and not plan.dimensions and row_count != 1:
        return SampleCheck(False, row_count, "aggregate_shape_mismatch")

    return SampleCheck(True, row_count, None)


def repair_sql(plan: QueryPlan) -> Optional[str]:
    """Propose one repaired SQL string for a failed sample check.

    Deterministic local repair rule: re-render canonical SQL directly from the
    structured plan. Because the plan is grounded in the real schema, this
    produces correct, safe SQL for any matched intent — repairing a candidate
    (e.g. an LLM draft) that drifted from the plan's expected columns/shape.
    Returns ``None`` when there is nothing to repair against (unmatched plan).
    """
    if plan.matched and plan.measures and plan.required_tables:
        return render_sql_from_plan(plan)
    return None
