#!/usr/bin/env python3
"""Evaluation harness for Forecast Studio.

Runs every question in ``eval/questions.json`` through the backend services
(in-process, no HTTP server) and measures generation / execution / verification
rates, unsupported-rejection accuracy, and latency. Compares a baseline
(generate + execute, no verification) against the full planner+verification
pipeline.

Run from the repo root with the backend venv:

    backend/.venv/bin/python scripts/run_eval.py

Writes eval/results.json and eval/results.md. Numbers are measured, not faked.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config import settings  # noqa: E402

settings.cache_enabled = False  # eval measures generation, not the dedup cache

from app.api import routes_query  # noqa: E402
from app.db import sample_seed  # noqa: E402
from app.services import (  # noqa: E402
    execution_service,
    planner_service,
    schema_service,
    verification_service,
)
from app.services.sql_generator import LocalSqlGenerator  # noqa: E402
from app.services.sql_guard import validate_sql  # noqa: E402

EVAL_DIR = REPO / "eval"
CONNECTION_ID = "demo"


def row_count_ok(expected: str, count: int) -> bool:
    return {
        "zero": count == 0,
        "one": count == 1,
        "at_most_5": 1 <= count <= 5,
        "positive": count > 0,
    }.get(expected, True)


def pct(values: list[bool]) -> float:
    return round(100.0 * (sum(values) / len(values)), 1) if values else 0.0


def run() -> dict:
    sample_seed.seed(settings.demo_db_path)  # deterministic demo data
    schema = schema_service.get_schema(CONNECTION_ID)
    questions = json.loads((EVAL_DIR / "questions.json").read_text())
    gen = LocalSqlGenerator()

    per_question = []
    baseline_latencies = []
    full_latencies = []
    full_costs = []

    for item in questions:
        q = item["question"]
        supported = item["expected_supported"]

        # --- Baseline: plan -> generate -> guard -> execute (NO verification) ---
        t0 = time.perf_counter()
        plan = planner_service.create_plan(q, schema)
        result = gen.generate(q, schema, plan)
        gen_ok = result.matched
        exec_ok = False
        row_count = 0
        columns: list[str] = []
        if gen_ok:
            try:
                safe = validate_sql(result.sql)
                qr = execution_service.execute(CONNECTION_ID, safe)
                exec_ok = True
                row_count = qr.row_count
                columns = qr.columns
            except Exception:
                exec_ok = False
        baseline_ms = (time.perf_counter() - t0) * 1000
        baseline_latencies.append(baseline_ms)

        # --- Full: same, plus sample self-check/repair, plus verification ---
        t1 = time.perf_counter()
        plan_f = planner_service.create_plan(q, schema)
        result_f = gen.generate(q, schema, plan_f)
        verified = False
        sample_checked = False
        sample_passed = None      # True/False for supported; None if not run
        repair_attempted = False
        repair_successful = False
        if result_f.matched:
            try:
                safe_f = validate_sql(result_f.sql)
                # Sample execution + self-check + one repair (production helper).
                safe_f, meta = routes_query._sample_check_and_repair(
                    CONNECTION_ID, safe_f, plan_f
                )
                sample_checked = meta["sample_checked"]
                repair_attempted = meta["repair_attempted"]
                repair_successful = meta["repair_successful"]
                # Passed the first sample check == checked and no repair needed.
                sample_passed = sample_checked and not repair_attempted
                qr_f = execution_service.execute(CONNECTION_ID, safe_f)
                v = verification_service.verify(
                    intent=result_f.intent, matched=True, sql=safe_f,
                    columns=qr_f.columns, rows=qr_f.rows, row_count=qr_f.row_count,
                )
                verified = v.verified
            except Exception:
                verified = False
        full_ms = (time.perf_counter() - t1) * 1000
        full_latencies.append(full_ms)

        # Estimated per-query cost (local provider -> 0; same logic the API uses).
        est_cost = routes_query._estimate_cost(
            "local", result_f.prompt_tokens, result_f.completion_tokens
        )
        full_costs.append(est_cost)

        per_question.append({
            "question": q,
            "expected_intent": item["expected_intent"],
            "expected_supported": supported,
            "planner_intent": plan.intent,
            "planner_confidence": plan.confidence,
            "planner_intent_correct": plan.intent == item["expected_intent"],
            "actual_intent": result.intent,
            "generation_success": gen_ok,
            "intent_correct": result.intent == item["expected_intent"],
            "execution_success": exec_ok,
            "columns_ok": all(c in columns for c in item["required_columns"]),
            "row_count": row_count,
            "row_count_ok": row_count_ok(item["expected_row_count"], row_count),
            "verified": verified,
            "estimated_cost_usd": est_cost,
            "sample_checked": sample_checked,
            "sample_passed": sample_passed,
            "repair_attempted": repair_attempted,
            "repair_successful": repair_successful,
            "rejected_correctly": (not gen_ok) if not supported else None,
            "baseline_latency_ms": round(baseline_ms, 3),
            "full_latency_ms": round(full_ms, 3),
        })

    sup = [r for r in per_question if r["expected_supported"]]
    uns = [r for r in per_question if not r["expected_supported"]]
    sup_exec = [r for r in sup if r["execution_success"]]

    metrics = {
        "sql_generation_success_rate": pct([r["generation_success"] for r in sup]),
        # Planner accuracy over ALL questions: supported must hit their intent,
        # unsupported must plan as "unsupported".
        "planner_intent_accuracy": pct([r["planner_intent_correct"] for r in per_question]),
        "avg_planner_confidence_supported": round(
            mean([r["planner_confidence"] for r in sup]), 3
        ) if sup else 0.0,
        "intent_accuracy": pct([r["intent_correct"] for r in sup]),
        "execution_success_rate": pct([r["execution_success"] for r in sup]),
        "column_match_rate": pct([r["columns_ok"] for r in sup_exec]),
        "row_count_ok_rate": pct([r["row_count_ok"] for r in sup_exec]),
        "verification_pass_rate": pct([r["verified"] for r in sup]),
        "unsupported_rejection_accuracy": pct([r["rejected_correctly"] for r in uns]),
        # Sample execution + self-check loop.
        "sample_check_pass_rate": pct([r["sample_passed"] for r in sup]),
        "sample_check_failures": sum(1 for r in sup if r["repair_attempted"]),
        "repairs_attempted": sum(1 for r in sup if r["repair_attempted"]),
        "repairs_successful": sum(1 for r in sup if r["repair_successful"]),
    }

    modes = {
        "baseline_no_verification": {
            "avg_latency_ms": round(mean(baseline_latencies), 3),
            "verification_pass_rate": None,
        },
        "planner_plus_verification": {
            "avg_latency_ms": round(mean(full_latencies), 3),
            "avg_estimated_cost_usd": round(mean(full_costs), 6),
            "verification_pass_rate": metrics["verification_pass_rate"],
        },
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"total": len(questions), "supported": len(sup), "unsupported": len(uns)},
        "metrics": metrics,
        "modes": modes,
        "questions": per_question,
    }


def write_markdown(results: dict) -> str:
    m = results["metrics"]
    modes = results["modes"]
    d = results["dataset"]
    lines = [
        "# Forecast Studio — Evaluation Results",
        "",
        f"_Generated: {results['generated_at']} · Dataset: {d['total']} questions "
        f"({d['supported']} supported, {d['unsupported']} unsupported) · "
        "Provider: local (deterministic)_",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| SQL generation success rate (supported) | {m['sql_generation_success_rate']}% |",
        f"| Planner intent accuracy (all questions) | {m['planner_intent_accuracy']}% |",
        f"| Avg planner confidence (supported) | {m['avg_planner_confidence_supported']} |",
        f"| Intent accuracy (supported) | {m['intent_accuracy']}% |",
        f"| Execution success rate (supported) | {m['execution_success_rate']}% |",
        f"| Result-column match rate | {m['column_match_rate']}% |",
        f"| Row-count behavior correct | {m['row_count_ok_rate']}% |",
        f"| Verification pass rate (supported) | {m['verification_pass_rate']}% |",
        f"| Unsupported rejection accuracy | {m['unsupported_rejection_accuracy']}% |",
        f"| Sample self-check pass rate (supported) | {m['sample_check_pass_rate']}% |",
        f"| Sample-check failures / repairs attempted / successful | "
        f"{m['sample_check_failures']} / {m['repairs_attempted']} / {m['repairs_successful']} |",
        "",
        "## Mode comparison (average latency)",
        "",
        "| Mode | Avg latency | Avg est. cost (USD) | Verification |",
        "|---|---|---|---|",
        f"| Baseline (generate + execute) | {modes['baseline_no_verification']['avg_latency_ms']} ms | — | — |",
        f"| Planner + verification (full) | {modes['planner_plus_verification']['avg_latency_ms']} ms | "
        f"${modes['planner_plus_verification']['avg_estimated_cost_usd']} | "
        f"{modes['planner_plus_verification']['verification_pass_rate']}% pass |",
        "",
        "_Both modes use the same schema-grounded local generator; the full mode "
        "adds the verification loop. Numbers are measured by `scripts/run_eval.py`._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    results = run()
    (EVAL_DIR / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (EVAL_DIR / "results.md").write_text(write_markdown(results))

    m = results["metrics"]
    print(f"Ran {results['dataset']['total']} questions.")
    for k, v in m.items():
        suffix = "%" if (k.endswith("_rate") or k.endswith("_accuracy")) else ""
        print(f"  {k:<34} {v}{suffix}")
    print(f"  baseline avg latency               {results['modes']['baseline_no_verification']['avg_latency_ms']} ms")
    print(f"  full avg latency                   {results['modes']['planner_plus_verification']['avg_latency_ms']} ms")
    print(f"  full avg estimated cost (USD)      ${results['modes']['planner_plus_verification']['avg_estimated_cost_usd']}")
    print("Wrote eval/results.json and eval/results.md")


if __name__ == "__main__":
    main()
