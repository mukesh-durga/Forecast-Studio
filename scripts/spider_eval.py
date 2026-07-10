"""Pure, testable helpers for the Spider-subset evaluation.

Kept free of app/DB imports so the metric logic can be unit-tested with toy
examples (see backend/app/tests/test_spider_eval.py). The orchestration that
actually loads Spider databases and runs the pipeline lives in
``run_spider_subset.py``.

Execution accuracy here is a *result-set* comparison (the Spider convention):
run the predicted SQL and the gold SQL, then compare the returned rows. Order is
only required when the gold query has a top-level ORDER BY.
"""

from __future__ import annotations

import re
from statistics import mean
from typing import Any, Optional

_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


def order_sensitive(gold_sql: str) -> bool:
    """True if the gold query's result order is meaningful (has ORDER BY)."""
    return bool(_ORDER_BY_RE.search(gold_sql or ""))


def normalize_cell(value: Any) -> str:
    """Stringify a cell so rows compare stably across drivers/types."""
    if value is None:
        return "∅"  # ∅ — distinct from the string "None"
    if isinstance(value, float):
        return f"{round(value, 3)}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _row_tuple(row: Any) -> tuple[str, ...]:
    # Rows come back as dicts (column-ordered); fall back to sequences.
    values = row.values() if isinstance(row, dict) else row
    return tuple(normalize_cell(v) for v in values)


def results_match(
    predicted_rows: Optional[list],
    gold_rows: Optional[list],
    order_matters: bool,
) -> bool:
    """Compare two result sets for execution-accuracy.

    ``None`` means "did not execute" and never matches. When order does not
    matter the rows are compared as multisets (sorted), otherwise as sequences.
    """
    if predicted_rows is None or gold_rows is None:
        return False
    pred = [_row_tuple(r) for r in predicted_rows]
    gold = [_row_tuple(r) for r in gold_rows]
    if order_matters:
        return pred == gold
    return sorted(pred) == sorted(gold)


def pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def aggregate_mode(records: list[dict], mode_key: str) -> dict:
    """Aggregate per-example records for one mode ("baseline" | "full").

    Each record is ``{"gold_ok": bool, "baseline": {...}, "full": {...}}`` where
    each mode dict has: generated, unsafe_rejected, pred_executed, correct,
    caught_wrong, latency_ms.
    """
    total = len(records)
    gold_ok = [r for r in records if r["gold_ok"]]
    m = [r[mode_key] for r in records]

    correct = sum(1 for r in gold_ok if r[mode_key]["correct"])
    executed = sum(1 for x in m if x["pred_executed"])
    generated = sum(1 for x in m if x["generated"])
    unsafe = sum(1 for x in m if x["unsafe_rejected"])
    caught = sum(1 for x in m if x.get("caught_wrong"))
    latencies = [x["latency_ms"] for x in m]

    return {
        "total": total,
        "gold_executable": len(gold_ok),
        "generated_count": generated,
        "executed_count": executed,
        "execution_correct": correct,
        # Execution accuracy is over examples whose gold SQL actually executed.
        "execution_accuracy_pct": pct(correct, len(gold_ok)),
        # Generation validity: produced guard-passing SQL that executed cleanly.
        "generation_validity_pct": pct(executed, total),
        "unsafe_rejection_count": unsafe,
        "wrong_answer_caught_count": caught,
        "avg_latency_ms": round(mean(latencies), 3) if latencies else 0.0,
    }


def aggregate(records: list[dict]) -> dict:
    return {
        "baseline": aggregate_mode(records, "baseline"),
        "full": aggregate_mode(records, "full"),
    }
