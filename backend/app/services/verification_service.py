"""Verification service.

A free, deterministic, offline check of whether the generated SQL and the rows
it returned actually answer the user's question. No LLM, no network, no paid
API.

It works from four signals:
  1. the matched intent from the local SQL generator,
  2. the result columns,
  3. the row count (and rows),
  4. the SQL structure (expected aggregate / clause keywords).

Each known intent has an expectation (which columns must appear, whether rows
are required, and which SQL keywords should be present). The verdict and a
0.0-1.0 confidence are derived from how well the actual result meets it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.models.responses import Verification


@dataclass(frozen=True)
class _Expectation:
    columns: tuple[str, ...]              # columns that MUST be present (lowercased)
    needs_rows: bool = True               # must the result be non-empty?
    sql_contains: tuple[str, ...] = field(default_factory=tuple)  # expected SQL keywords


# Keyed by the intent names produced by LocalSqlGenerator.
_EXPECTATIONS: dict[str, _Expectation] = {
    "top_products_by_revenue": _Expectation(("product_name", "revenue"), True, ("sum", "group by")),
    "city_most_customers": _Expectation(("city", "customer_count"), True, ("count", "group by")),
    "monthly_revenue": _Expectation(("month", "revenue"), True, ("sum", "group by")),
    "category_revenue": _Expectation(("category", "revenue"), True, ("sum", "group by")),
    "average_order_value": _Expectation(("average_order_value",), True, ("sum", "count")),
    "top_customers_by_orders": _Expectation(("customer_name", "order_count"), True, ("count", "group by")),
    "open_tickets": _Expectation(("open_tickets",), True, ("count", "status")),
    "lowest_satisfaction_issue": _Expectation(("issue_type", "avg_satisfaction"), True, ("avg", "group by")),
    "top_channel_by_spend": _Expectation(("channel", "total_spend"), True, ("sum", "group by")),
}


def _verify_generic(
    cols: set[str], expected_columns: list[str], row_count: int,
    question: Optional[str], sql: str,
) -> Verification:
    """Verify a generic (non-templated) schema-aware answer.

    Beyond structural checks (expected columns present, non-empty), this checks
    **semantic alignment**: the SQL's tables/columns must fit the question's
    entities. A query is NOT verified merely because it executed and returned
    rows (e.g. a customer-spend question answered from ``marketing_campaigns``).
    """
    from app.services.generic_generator import semantic_mismatch

    reason = semantic_mismatch(question or "", sql)
    if reason:
        return Verification(
            verified=False, confidence=0.2,
            explanation=f"The result does not match the question's intent: {reason}.",
            failure_reason="semantic_mismatch",
        )

    if row_count == 0:
        return Verification(
            verified=False, confidence=0.3,
            explanation="The generic schema-aware query executed but returned no rows.",
            failure_reason="no_rows",
        )
    want = [c.lower() for c in expected_columns]
    missing = [c for c in want if c not in cols]
    if missing:
        return Verification(
            verified=False, confidence=0.4,
            explanation=(
                f"Result columns {sorted(cols)} do not include the expected "
                f"column(s) {missing}."
            ),
            failure_reason=f"missing_expected_columns: {', '.join(missing)}",
        )
    return Verification(
        verified=True, confidence=0.7,
        explanation=(
            f"Generic schema-aware query executed and returned {row_count} row(s) "
            f"with the expected columns {sorted(want) if want else sorted(cols)}. "
            "Answer is grounded in the schema but not matched to a predefined template."
        ),
        failure_reason=None,
    )


def verify(
    *,
    intent: Optional[str],
    matched: bool,
    sql: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    row_count: int,
    generic: bool = False,
    expected_columns: Optional[list[str]] = None,
    question: Optional[str] = None,
) -> Verification:
    """Return a verification verdict for a query result.

    ``generic=True`` verifies a generic schema-aware answer both structurally
    (expected columns present, non-empty) and **semantically** (the SQL's tables
    fit the question) — not merely because rows exist.
    """
    cols = {c.lower() for c in columns}

    if generic:
        return _verify_generic(cols, expected_columns or [], row_count, question, sql)

    # No known template matched → we cannot confidently verify the answer.
    if not matched or intent is None or intent not in _EXPECTATIONS:
        return Verification(
            verified=False,
            confidence=0.2,
            explanation="No known analytics template matched the question, "
            "so the result cannot be verified.",
            failure_reason="unmatched_question",
        )

    spec = _EXPECTATIONS[intent]

    # Required columns missing → the result does not answer the question.
    missing = [c for c in spec.columns if c not in cols]
    if missing:
        return Verification(
            verified=False,
            confidence=0.35,
            explanation=(
                f"Result columns {sorted(cols)} do not include the expected "
                f"column(s) {missing} for this question."
            ),
            failure_reason=f"missing_expected_columns: {', '.join(missing)}",
        )

    # Rows required but none returned → nothing to answer with.
    if spec.needs_rows and row_count == 0:
        return Verification(
            verified=False,
            confidence=0.45,
            explanation="The SQL structure matches the question but returned no rows.",
            failure_reason="no_rows",
        )

    # Columns (and rows) are right. Use SQL structure as a confidence signal.
    structure_ok = all(keyword in sql.lower() for keyword in spec.sql_contains)
    confidence = 0.9 if structure_ok else 0.75
    return Verification(
        verified=True,
        confidence=confidence,
        explanation=(
            f"The query returns {sorted(spec.columns)} and produced {row_count} "
            f"row(s), which matches the intent of the question."
        ),
        failure_reason=None,
    )
