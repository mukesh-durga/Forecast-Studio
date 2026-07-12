"""Pure, testable helpers for the Spider-subset evaluation.

Kept free of app/DB imports so the metric logic can be unit-tested with toy
examples (see backend/app/tests/test_spider_eval.py). Orchestration that loads
Spider databases and runs the pipeline lives in ``run_spider_subset.py``.

Execution accuracy is a *result-set* comparison (the Spider convention): run the
predicted SQL and the gold SQL, then compare rows. Order is required only when
the gold query has a top-level ORDER BY. Gold SQL is used **only** here, for
scoring after a prediction is made.
"""

from __future__ import annotations

import hashlib
import re
from statistics import mean
from typing import Any, Optional

_ORDER_BY_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)


def order_sensitive(gold_sql: str) -> bool:
    return bool(_ORDER_BY_RE.search(gold_sql or ""))


def estimate_difficulty(gold_sql: str) -> str:
    """Heuristic difficulty from the gold SQL structure (for reporting only)."""
    s = (gold_sql or "").lower()
    if len(re.findall(r"\bselect\b", s)) > 1 or any(k in s for k in (" union ", " intersect ", " except ")):
        return "hard"
    joins = s.count(" join ")
    if joins >= 2:
        return "hard"
    if joins == 1 or " group by " in s or " having " in s:
        return "medium"
    return "easy"


def normalize_cell(value: Any) -> str:
    if value is None:
        return "∅"
    if isinstance(value, float):
        return f"{round(value, 3)}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _row_tuple(row: Any) -> tuple[str, ...]:
    values = row.values() if isinstance(row, dict) else row
    return tuple(normalize_cell(v) for v in values)


def results_match(predicted_rows: Optional[list], gold_rows: Optional[list], order_matters: bool) -> bool:
    if predicted_rows is None or gold_rows is None:
        return False
    pred = [_row_tuple(r) for r in predicted_rows]
    gold = [_row_tuple(r) for r in gold_rows]
    if order_matters:
        return pred == gold
    return sorted(pred) == sorted(gold)


def pct(numerator: int, denominator: int) -> float:
    return round(100.0 * numerator / denominator, 1) if denominator else 0.0


def result_fingerprint(rows: Optional[list], order_matters: bool) -> Optional[str]:
    """Short hash of a result set; equal iff ``results_match`` would be True.

    ``None`` (did not execute) hashes to ``None``. Uses the same order rule as
    scoring, so baseline/gold/full hashes can be compared directly in debug.
    """
    if rows is None:
        return None
    tuples = [_row_tuple(r) for r in rows]
    if not order_matters:
        tuples = sorted(tuples)
    return hashlib.sha1(repr(tuples).encode()).hexdigest()[:12]


def wrong_answer_status(baseline: dict, full: dict, gold_ok: bool) -> tuple[bool, bool, str]:
    """Classify an example for wrong-answer detection.

    Returns ``(executable_wrong_baseline, caught, reason)``.

    A *wrong-but-executable baseline* is one that passed the guard, executed, and
    whose result did not match gold. It is **caught** when the full pipeline
    either repaired/replaced it with a gold-matching result, or flagged it as
    implausible (failed verification). Syntax errors and unsafe rejections are
    **not** wrong-answer cases (the baseline never produced an executable answer).
    """
    if not gold_ok:
        return (False, False, "gold_not_executable")
    if not baseline.get("guard_passed") or not baseline.get("pred_executed"):
        # Guard-blocked (unsafe) or failed to execute (syntax): not a wrong answer.
        return (False, False, "baseline_not_executable")
    if baseline.get("correct"):
        return (False, False, "baseline_correct")
    if full.get("correct"):
        return (True, True, "repaired_to_correct")
    if not full.get("verified", False):
        return (True, True, "flagged_unverified")
    return (True, False, "missed_still_wrong")


def _mode_metrics(records: list[dict], key: str) -> dict:
    total = len(records)
    gold_ok = [r for r in records if r["gold_ok"]]
    m = [r[key] for r in records]
    correct = sum(1 for r in gold_ok if r[key]["correct"])
    return {
        "total": total,
        "gold_executable": len(gold_ok),
        "generated_count": sum(1 for x in m if x["generated"]),
        "executed_count": sum(1 for x in m if x["pred_executed"]),
        "execution_correct": correct,
        "execution_accuracy_pct": pct(correct, len(gold_ok)),
        "valid_sql_generation_pct": pct(sum(1 for x in m if x.get("guard_passed")), total),
        "execution_success_pct": pct(sum(1 for x in m if x["pred_executed"]), total),
        "unsafe_rejection_count": sum(1 for x in m if x["unsafe_rejected"]),
        "avg_latency_ms": round(mean([x["latency_ms"] for x in m]), 3) if m else 0.0,
        "estimated_cost_usd": 0.0,  # deterministic heuristic, no LLM
    }


def aggregate(records: list[dict]) -> dict:
    baseline = _mode_metrics(records, "baseline")
    full = _mode_metrics(records, "full")

    abs_impr = round(full["execution_accuracy_pct"] - baseline["execution_accuracy_pct"], 1)
    rel_impr = (
        round(100.0 * abs_impr / baseline["execution_accuracy_pct"], 1)
        if baseline["execution_accuracy_pct"] else 0.0
    )

    # Wrong-answer detection (see wrong_answer_status for the exact definition).
    statuses = [wrong_answer_status(r["baseline"], r["full"], r["gold_ok"]) for r in records]
    exec_wrong = sum(1 for exec_wrong_base, _c, _r in statuses if exec_wrong_base)
    caught = sum(1 for exec_wrong_base, c, _r in statuses if exec_wrong_base and c)

    return {
        "baseline": baseline,
        "full": full,
        "improvement": {
            "absolute_pct": abs_impr,
            "relative_pct": rel_impr,
        },
        "executable_wrong_baseline_count": exec_wrong,
        "wrong_answers_caught_count": caught,
        "wrong_answers_caught_rate": pct(caught, exec_wrong),
        "repair_attempted_count": sum(1 for r in records if r["full"].get("repair_attempted")),
        "repair_successful_count": sum(1 for r in records if r["full"].get("repair_successful")),
    }
