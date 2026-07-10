#!/usr/bin/env python3
"""Spider-subset evaluation harness for Forecast Studio.

Evaluates the SQL pipeline on a configurable subset of the **official Spider dev
set** (Yale). It is a *subset* harness — it does not run the full benchmark and
makes no full-benchmark claim. Numbers are whatever it measures on the examples
you run; nothing is hardcoded.

For every example it:
  1. loads the example's SQLite database schema,
  2. generates SQL in **baseline** mode (single-shot, schema-grounded, no
     sample-check / verification / repair),
  3. generates SQL in **full** mode (planner + guard + sample-check +
     verification + optional repair),
  4. executes the predicted SQL (guarded) and the gold SQL (read-only),
  5. compares result-set equality (order only when the gold has ORDER BY).

Usage (after installing Spider locally — see scripts/download_spider.py):

    backend/.venv/bin/python scripts/run_spider_subset.py --limit 50
    backend/.venv/bin/python scripts/run_spider_subset.py --limit 10 --spider-dir /path/to/spider

Writes spider/results.json and spider/results.md (timestamped, with provider).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import spider_eval  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.connectors.sqlite_connector import SQLiteConnector  # noqa: E402
from app.models.responses import ColumnSchema, SchemaResponse, TableSchema  # noqa: E402
from app.services import planner_service, self_check_service, verification_service  # noqa: E402
from app.services.sql_generator import get_sql_generator  # noqa: E402
from app.services.sql_guard import SqlGuardError, validate_sql  # noqa: E402

# Large limits so the safety guard doesn't truncate result sets during scoring.
_SCORE_LIMIT = 100_000
_TIMEOUT = 10.0


# --- Spider data location ---------------------------------------------------

def find_spider_dir(explicit: str | None = None) -> Path | None:
    """Locate a directory containing dev.json + database/ (official Spider)."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.getenv("SPIDER_DIR"):
        candidates.append(Path(os.environ["SPIDER_DIR"]))
    candidates += [REPO / "spider", REPO / "spider" / "spider", REPO / "data" / "spider"]
    for c in candidates:
        if (c / "dev.json").exists() and (c / "database").is_dir():
            return c
    return None


def load_examples(spider_dir: Path, limit: int) -> list[dict]:
    examples = json.loads((spider_dir / "dev.json").read_text())
    return examples[:limit]


def db_path_for(spider_dir: Path, db_id: str) -> Path:
    return spider_dir / "database" / db_id / f"{db_id}.sqlite"


# --- Schema + execution against an arbitrary SQLite file --------------------

def build_schema_from_sqlite(connection_id: str, db_path: str) -> SchemaResponse:
    """Inspect any SQLite file into the app's SchemaResponse shape."""
    connector = SQLiteConnector(db_path)
    tables = connector.inspect(sample_rows=settings.schema_sample_rows)
    table_schemas = [
        TableSchema(
            name=t.name,
            row_count=t.row_count,
            columns=[
                ColumnSchema(name=c.name, type=c.type, primary_key=c.primary_key, nullable=c.nullable)
                for c in t.columns
            ],
            sample_rows=t.sample_rows,
        )
        for t in tables
    ]
    return SchemaResponse(
        connection_id=connection_id, dialect="sqlite",
        table_count=len(table_schemas), tables=table_schemas,
    )


def _execute(connector: SQLiteConnector, sql: str):
    """Run SQL read-only; return rows (list[dict]) or None on any error."""
    try:
        return connector.run_select(sql, timeout_seconds=_TIMEOUT).rows
    except Exception:
        return None


def _blank_mode_record() -> dict:
    return {
        "generated": False, "unsafe_rejected": False, "pred_executed": False,
        "correct": False, "caught_wrong": False, "latency_ms": 0.0, "sql": None,
    }


# --- Per-example evaluation -------------------------------------------------

def evaluate_example(example: dict, spider_dir: Path, generator) -> dict:
    db_id = example["db_id"]
    question = example["question"]
    gold_sql = example.get("query") or example.get("gold") or ""
    db_file = str(db_path_for(spider_dir, db_id))

    connector = SQLiteConnector(db_file)
    schema = build_schema_from_sqlite(db_id, db_file)

    # Gold result (reference truth), executed read-only without our guard.
    gold_rows = _execute(connector, gold_sql)
    gold_ok = gold_rows is not None
    order_matters = spider_eval.order_sensitive(gold_sql)

    # --- baseline: single-shot generation, guard, execute (no self-check) ---
    baseline = _blank_mode_record()
    t0 = time.perf_counter()
    plan = planner_service.create_plan(question, schema)
    gen = generator.generate(question, schema, plan)
    if gen.matched and gen.sql:
        baseline["generated"] = True
        try:
            safe = validate_sql(gen.sql, default_limit=_SCORE_LIMIT, max_limit=_SCORE_LIMIT)
            baseline["sql"] = safe
            rows = _execute(connector, safe)
            if rows is not None:
                baseline["pred_executed"] = True
                baseline["correct"] = gold_ok and spider_eval.results_match(rows, gold_rows, order_matters)
        except SqlGuardError:
            baseline["unsafe_rejected"] = True
    baseline["latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)

    # --- full: planner + guard + sample-check + verification + repair -------
    full = _blank_mode_record()
    t1 = time.perf_counter()
    plan_f = planner_service.create_plan(question, schema)
    gen_f = generator.generate(question, schema, plan_f)
    if gen_f.matched and gen_f.sql:
        full["generated"] = True
        try:
            safe_f = validate_sql(gen_f.sql, default_limit=_SCORE_LIMIT, max_limit=_SCORE_LIMIT)
            # Sample self-check + one repair (executes samples against this db).
            safe_f = _sample_check_and_repair(connector, safe_f, plan_f)
            full["sql"] = safe_f
            rows_f = _execute(connector, safe_f)
            if rows_f is not None:
                full["pred_executed"] = True
                full["correct"] = gold_ok and spider_eval.results_match(rows_f, gold_rows, order_matters)
                # Our verification's verdict on the final result.
                v = verification_service.verify(
                    intent=gen_f.intent, matched=True, sql=safe_f,
                    columns=list(rows_f[0].keys()) if rows_f else [],
                    rows=rows_f, row_count=len(rows_f),
                )
                # "Caught" a wrong answer = executed, wrong, and we flagged it unverified.
                if gold_ok and not full["correct"] and not v.verified:
                    full["caught_wrong"] = True
        except SqlGuardError:
            full["unsafe_rejected"] = True
    full["latency_ms"] = round((time.perf_counter() - t1) * 1000, 3)

    return {
        "db_id": db_id, "question": question, "gold_ok": gold_ok,
        "order_matters": order_matters, "baseline": baseline, "full": full,
    }


def _sample_check_and_repair(connector: SQLiteConnector, safe_sql: str, plan) -> str:
    """Harness copy of the route's sample-check/repair, executing on `connector`."""
    def run_sample(sql: str):
        try:
            sample_sql = self_check_service.build_sample_sql(sql)
            rows = connector.run_select(sample_sql, timeout_seconds=_TIMEOUT).rows
        except Exception:
            return self_check_service.SampleCheck(False, 0, "sample_execution_error")
        cols = list(rows[0].keys()) if rows else []
        return self_check_service.check_sample(plan, cols, rows, len(rows))

    if run_sample(safe_sql).passed:
        return safe_sql
    repaired = self_check_service.repair_sql(plan)
    if repaired:
        try:
            repaired_safe = validate_sql(repaired, default_limit=_SCORE_LIMIT, max_limit=_SCORE_LIMIT)
        except SqlGuardError:
            return safe_sql
        if run_sample(repaired_safe).passed:
            return repaired_safe
    return safe_sql


# --- Run + report -----------------------------------------------------------

def run_subset(spider_dir: Path, limit: int, out_dir: Path) -> dict:
    examples = load_examples(spider_dir, limit)
    generator = get_sql_generator()
    provider = settings.sql_generator_provider.lower()

    records = [evaluate_example(ex, spider_dir, generator) for ex in examples]
    metrics = spider_eval.aggregate(records)

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": "Spider dev (subset)",
        "spider_dir": str(spider_dir),
        "provider": provider,
        "count": len(records),
        "metrics": metrics,
        "examples": [
            {k: r[k] for k in ("db_id", "question", "gold_ok", "order_matters")}
            | {"baseline": r["baseline"], "full": r["full"]}
            for r in records
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (out_dir / "results.md").write_text(write_markdown(results))
    return results


def write_markdown(results: dict) -> str:
    b, f = results["metrics"]["baseline"], results["metrics"]["full"]
    lines = [
        "# Forecast Studio — Spider-subset Evaluation",
        "",
        f"_Generated: {results['generated_at']} · Dataset: **Spider dev (subset)** · "
        f"{results['count']} examples · Provider: {results['provider']}_",
        "",
        "> This is a **subset** of the Spider dev set, not the full benchmark. "
        "Numbers below are measured on the examples run; no full-benchmark claim "
        "is made.",
        "",
        "| Metric | Baseline | Full |",
        "|---|---|---|",
        f"| Execution accuracy (of gold-executable) | {b['execution_accuracy_pct']}% | {f['execution_accuracy_pct']}% |",
        f"| Generation validity | {b['generation_validity_pct']}% | {f['generation_validity_pct']}% |",
        f"| Unsafe rejections | {b['unsafe_rejection_count']} | {f['unsafe_rejection_count']} |",
        f"| Wrong-answer caught | {b['wrong_answer_caught_count']} | {f['wrong_answer_caught_count']} |",
        f"| Avg latency | {b['avg_latency_ms']} ms | {f['avg_latency_ms']} ms |",
        f"| Examples / gold-executable | {b['total']} / {b['gold_executable']} | {f['total']} / {f['gold_executable']} |",
        "",
        "_Baseline = single-shot schema-grounded generation. "
        "Full = planner + guard + sample self-check + verification + optional repair. "
        "Execution accuracy compares result sets (order only when the gold has ORDER BY)._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate on a Spider dev subset.")
    parser.add_argument("--limit", type=int, default=50, help="number of examples (default 50)")
    parser.add_argument("--spider-dir", default=None, help="path to the Spider dir (dev.json + database/)")
    parser.add_argument("--out-dir", default=str(REPO / "spider"), help="where to write results")
    args = parser.parse_args()

    spider_dir = find_spider_dir(args.spider_dir)
    if spider_dir is None:
        print(
            "Spider data not found. Download the official Spider dev set and point\n"
            "the harness at it (see scripts/download_spider.py):\n"
            "  export SPIDER_DIR=/path/to/spider   # must contain dev.json + database/\n"
            "Then re-run:  backend/.venv/bin/python scripts/run_spider_subset.py --limit 50",
            file=sys.stderr,
        )
        raise SystemExit(2)

    results = run_subset(spider_dir, args.limit, Path(args.out_dir))
    b, f = results["metrics"]["baseline"], results["metrics"]["full"]
    print(f"Ran {results['count']} Spider-subset examples (provider: {results['provider']}).")
    print(f"  baseline  exec-acc {b['execution_accuracy_pct']}%  valid {b['generation_validity_pct']}%  "
          f"unsafe {b['unsafe_rejection_count']}  latency {b['avg_latency_ms']}ms")
    print(f"  full      exec-acc {f['execution_accuracy_pct']}%  valid {f['generation_validity_pct']}%  "
          f"unsafe {f['unsafe_rejection_count']}  caught {f['wrong_answer_caught_count']}  "
          f"latency {f['avg_latency_ms']}ms")
    print("Wrote spider/results.json and spider/results.md")


if __name__ == "__main__":
    main()
