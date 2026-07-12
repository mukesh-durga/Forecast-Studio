#!/usr/bin/env python3
"""Spider-subset evaluation harness for Forecast Studio.

Evaluates a schema-aware SQL generator on a deterministic subset of the
**official Spider dev set** (Yale). It is a *subset* harness — it does not run
the full benchmark and makes no full-benchmark claim. Numbers are whatever it
measures; nothing is hardcoded.

Two modes are compared per example:

  * **baseline** — single-shot, schema-aware generation. One candidate, guarded
    and executed. No value linking, no multiple candidates, no repair.
  * **full** — schema linking + safe database **value linking** + foreign-key
    awareness, **multiple candidates** (default 3), guard + execute each, choose
    the most plausible, one **repair** on failure, then verify.

For each example both modes' predicted SQL and the gold SQL are executed and
their result sets compared (order only when the gold has ORDER BY). Gold SQL is
read **only** for scoring, never during generation.

Usage (after installing Spider locally — see scripts/download_spider.py):

    backend/.venv/bin/python scripts/run_spider_subset.py --limit 25 --seed 42

Writes spider/results.json, spider/results.md, and the selected subset to
spider/subsets/dev_<N>_seed<seed>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import spider_eval  # noqa: E402
import spider_generator as sg  # noqa: E402
from spider_generator import SpiderGenerator, SpiderSchema  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.connectors.sqlite_connector import SQLiteConnector  # noqa: E402
from app.models.responses import ColumnSchema, SchemaResponse, TableSchema  # noqa: E402
from app.services.sql_guard import SqlGuardError, validate_sql  # noqa: E402

# Large limits so the safety guard doesn't truncate result sets during scoring.
_SCORE_LIMIT = 100_000
_TIMEOUT = 10.0
_MAX_CANDIDATES = 3


# --- Spider data location + deterministic subset ----------------------------

def find_spider_dir(explicit: str | None = None) -> Path | None:
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


def select_subset(examples: list[dict], limit: int, seed: int, out_dir: Path) -> list[dict]:
    """Deterministically pick `limit` examples with `seed`; save the selection."""
    rng = random.Random(seed)
    idx = sorted(rng.sample(range(len(examples)), min(limit, len(examples))))
    subset = [examples[i] for i in idx]
    subsets_dir = out_dir / "subsets"
    subsets_dir.mkdir(parents=True, exist_ok=True)
    (subsets_dir / f"dev_{limit}_seed{seed}.json").write_text(json.dumps(subset, indent=2) + "\n")
    return subset


def db_path_for(spider_dir: Path, db_id: str) -> Path:
    return spider_dir / "database" / db_id / f"{db_id}.sqlite"


# --- Schema + execution against an arbitrary SQLite file --------------------

def build_schema_from_sqlite(connection_id: str, db_path: str) -> SchemaResponse:
    """Inspect any SQLite file into the app's SchemaResponse shape (used in tests)."""
    connector = SQLiteConnector(db_path)
    tables = connector.inspect(sample_rows=settings.schema_sample_rows)
    table_schemas = [
        TableSchema(
            name=t.name, row_count=t.row_count,
            columns=[ColumnSchema(name=c.name, type=c.type, primary_key=c.primary_key, nullable=c.nullable)
                     for c in t.columns],
            sample_rows=t.sample_rows,
        )
        for t in tables
    ]
    return SchemaResponse(connection_id=connection_id, dialect="sqlite",
                          table_count=len(table_schemas), tables=table_schemas)


def _execute(connector: SQLiteConnector, sql: str):
    try:
        return connector.run_select(sql, timeout_seconds=_TIMEOUT).rows
    except Exception:
        return None


def _blank_mode_record() -> dict:
    return {
        "generated": False, "guard_passed": False, "unsafe_rejected": False,
        "pred_executed": False, "correct": False, "verified": False,
        "repair_attempted": False, "repair_successful": False,
        "latency_ms": 0.0, "sql": None, "result_hash": None,
    }


def _guard(sql: str) -> str:
    return validate_sql(sql, default_limit=_SCORE_LIMIT, max_limit=_SCORE_LIMIT)


def _score_candidate(sql: str, rows: list) -> int:
    """Gold-free plausibility: prefer non-empty and value-filtered candidates."""
    return (2 if rows else 0) + (1 if " WHERE " in sql.upper() else 0)


# --- Per-example evaluation -------------------------------------------------

def _eval_baseline(question, schema, connector, gold_rows, gold_ok, order_matters) -> dict:
    rec = _blank_mode_record()
    t0 = time.perf_counter()
    raw = SpiderGenerator(schema).generate_sql(question)
    if raw:
        rec["generated"] = True
        try:
            safe = _guard(raw)
            rec["guard_passed"] = True
            rec["sql"] = safe
            rows = _execute(connector, safe)
            if rows is not None:
                rec["pred_executed"] = True
                rec["result_hash"] = spider_eval.result_fingerprint(rows, order_matters)
                rec["correct"] = gold_ok and spider_eval.results_match(rows, gold_rows, order_matters)
        except SqlGuardError:
            rec["unsafe_rejected"] = True
    rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return rec


def _eval_full(question, schema, conn, connector, gold_rows, gold_ok, order_matters,
               max_candidates) -> dict:
    rec = _blank_mode_record()
    t0 = time.perf_counter()
    candidates = sg.build_full_candidates(question, schema, conn, max_candidates=max_candidates)
    rec["generated"] = bool(candidates)

    executed: list[tuple[str, list]] = []
    for c in candidates:
        try:
            safe = _guard(c)
        except SqlGuardError:
            rec["unsafe_rejected"] = True
            continue
        rec["guard_passed"] = True
        rows = _execute(connector, safe)
        if rows is not None:
            executed.append((safe, rows))

    # Choose the most plausible executed candidate (no gold used).
    best = max(executed, key=lambda sr: _score_candidate(*sr), default=None)

    # Repair once if nothing plausible ran (all errored, or best is empty).
    if best is None or not best[1]:
        base = _base_table(candidates) or SpiderGenerator(schema).target_table(question)
        if base:
            rec["repair_attempted"] = True
            try:
                safe = _guard(f'SELECT * FROM "{base}"')
                rows = _execute(connector, safe)
                if rows is not None:
                    best = (safe, rows)
                    rec["repair_successful"] = True
            except SqlGuardError:
                pass

    if best is not None:
        rec["sql"] = best[0]
        rec["pred_executed"] = True
        rec["result_hash"] = spider_eval.result_fingerprint(best[1], order_matters)
        rec["correct"] = gold_ok and spider_eval.results_match(best[1], gold_rows, order_matters)
        rec["verified"] = len(best[1]) > 0  # structural: executed + non-empty
    rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return rec


def _base_table(candidates: list[str]) -> str | None:
    for c in candidates:
        m = re.search(r'FROM\s+"([^"]+)"', c)
        if m:
            return m.group(1)
    return None


def evaluate_example(example: dict, spider_dir: Path, max_candidates: int) -> dict:
    db_id = example["db_id"]
    question = example["question"]
    gold_sql = example.get("query") or example.get("gold") or ""
    db_file = str(db_path_for(spider_dir, db_id))

    connector = SQLiteConnector(db_file)
    schema = SpiderSchema.from_sqlite(db_id, db_file)
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        gold_rows = _execute(connector, gold_sql)
        gold_ok = gold_rows is not None
        order_matters = spider_eval.order_sensitive(gold_sql)

        baseline = _eval_baseline(question, schema, connector, gold_rows, gold_ok, order_matters)
        full = _eval_full(question, schema, conn, connector, gold_rows, gold_ok,
                          order_matters, max_candidates)
        gold_result_hash = spider_eval.result_fingerprint(gold_rows, order_matters)
    finally:
        conn.close()

    exec_wrong, caught, caught_reason = spider_eval.wrong_answer_status(baseline, full, gold_ok)

    return {
        "db_id": db_id, "question": question, "gold_sql": gold_sql,
        "difficulty": spider_eval.estimate_difficulty(gold_sql),
        "gold_ok": gold_ok, "order_matters": order_matters,
        "gold_result_hash": gold_result_hash,
        "baseline": baseline, "full": full,
        "executable_wrong_baseline": exec_wrong,
        "caught": caught,
        "caught_reason": caught_reason,
        "failure_reason": _failure_reason(full, gold_ok),
    }


def _failure_reason(full: dict, gold_ok: bool) -> str | None:
    if not gold_ok:
        return "gold_not_executable"
    if full["correct"]:
        return None
    if not full["generated"]:
        return "no_sql_generated"
    if full["unsafe_rejected"] and not full["pred_executed"]:
        return "unsafe_rejected"
    if not full["pred_executed"]:
        return "execution_error"
    return "result_mismatch"


# --- Run + report -----------------------------------------------------------

def _evaluate_all(spider_dir: Path, examples: list[dict], max_candidates: int,
                  progress: bool = False) -> list[dict]:
    records = []
    total = len(examples)
    for i, ex in enumerate(examples, 1):
        records.append(evaluate_example(ex, spider_dir, max_candidates))
        if progress and (i % 100 == 0 or i == total):
            print(f"  … evaluated {i}/{total}", file=sys.stderr)
    return records


def _build_results(spider_dir: Path, records: list[dict], dataset: str,
                   subset_meta: dict) -> dict:
    metrics = spider_eval.aggregate(records)

    failures = [
        {
            "db_id": r["db_id"], "question": r["question"], "difficulty": r["difficulty"],
            "gold_sql": r["gold_sql"],
            "baseline_predicted_sql": r["baseline"]["sql"],
            "full_predicted_sql": r["full"]["sql"],
            "reason": r["failure_reason"],
        }
        for r in records if r["failure_reason"] is not None
    ]

    def _wrong_answer_debug(r):
        return {
            "db_id": r["db_id"], "question": r["question"],
            "baseline_sql": r["baseline"]["sql"],
            "baseline_result_hash": r["baseline"]["result_hash"],
            "gold_result_hash": r["gold_result_hash"],
            "full_sql": r["full"]["sql"],
            "full_result_hash": r["full"]["result_hash"],
            "caught": r["caught"],
            "reason": r["caught_reason"],
        }

    caught_cases = [_wrong_answer_debug(r) for r in records if r["caught"]]

    # Per-difficulty execution accuracy (reporting only; gold structure heuristic).
    by_difficulty: dict[str, dict] = {}
    for r in records:
        if not r["gold_ok"]:
            continue
        d = by_difficulty.setdefault(r["difficulty"], {"gold_executable": 0, "baseline_correct": 0, "full_correct": 0})
        d["gold_executable"] += 1
        d["baseline_correct"] += int(r["baseline"]["correct"])
        d["full_correct"] += int(r["full"]["correct"])
    for d, v in by_difficulty.items():
        v["baseline_accuracy_pct"] = spider_eval.pct(v["baseline_correct"], v["gold_executable"])
        v["full_accuracy_pct"] = spider_eval.pct(v["full_correct"], v["gold_executable"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": dataset,
        "spider_dir": str(spider_dir),
        "generator": "spider-heuristic",
        "subset": subset_meta,
        "count": len(records),
        "metrics": metrics,
        "by_difficulty": by_difficulty,
        "failures": failures,
        "wrong_answer_detection": {
            "executable_wrong_baseline_count": metrics["executable_wrong_baseline_count"],
            "wrong_answers_caught_count": metrics["wrong_answers_caught_count"],
            "wrong_answers_caught_rate": metrics["wrong_answers_caught_rate"],
            "caught_cases": caught_cases,
        },
        "examples": [
            {k: r[k] for k in ("db_id", "question", "difficulty", "gold_sql", "gold_ok",
                               "gold_result_hash", "executable_wrong_baseline", "caught",
                               "caught_reason")}
            | {"baseline": r["baseline"], "full": r["full"], "failure_reason": r["failure_reason"]}
            for r in records
        ],
    }


def _write_results(results: dict, out_dir: Path, basename: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{basename}.json").write_text(json.dumps(results, indent=2) + "\n")
    (out_dir / f"{basename}.md").write_text(write_markdown(results))


def run_subset(spider_dir: Path, limit: int, seed: int, out_dir: Path,
               max_candidates: int = _MAX_CANDIDATES) -> dict:
    all_examples = json.loads((spider_dir / "dev.json").read_text())
    examples = select_subset(all_examples, limit, seed, out_dir)
    records = _evaluate_all(spider_dir, examples, max_candidates)
    results = _build_results(
        spider_dir, records, "Spider dev (subset)",
        {"limit": limit, "seed": seed, "file": f"subsets/dev_{limit}_seed{seed}.json", "full": False},
    )
    _write_results(results, out_dir, "results")
    return results


def run_full(spider_dir: Path, out_dir: Path, max_candidates: int = _MAX_CANDIDATES) -> dict:
    """Evaluate the ENTIRE Spider dev set (every example, in file order)."""
    examples = json.loads((spider_dir / "dev.json").read_text())
    records = _evaluate_all(spider_dir, examples, max_candidates, progress=True)
    results = _build_results(
        spider_dir, records, "Spider dev (full)",
        {"limit": len(examples), "seed": None, "file": None, "full": True},
    )
    _write_results(results, out_dir, "results_full")
    return results


def write_markdown(results: dict) -> str:
    m = results["metrics"]
    b, f, impr = m["baseline"], m["full"], m["improvement"]
    sub = results["subset"]
    full_run = bool(sub.get("full"))

    if full_run:
        title = "# Forecast Studio — Spider **full dev-set** Evaluation (baseline vs full)"
        meta = (
            f"_Generated: {results['generated_at']} · Dataset: **Spider dev (full)** · "
            f"all {results['count']} dev examples · Generator: {results['generator']}_"
        )
        caveat = (
            "> This is the **entire Spider dev set** (every example in `dev.json`, in file "
            "order — no sampling). Numbers are the real measured result of a deterministic "
            "schema-aware heuristic (no LLM); gold SQL is used only for scoring, never during "
            "generation. This is **not** a state-of-the-art text-to-SQL model — the point is a "
            "reproducible, honest full-dev baseline and the pipeline's wrong-answer catch rate."
        )
        scope_line = "Run over the full dev set (`--full`); nothing is subsampled."
    else:
        title = "# Forecast Studio — Spider-subset Evaluation (baseline vs full)"
        meta = (
            f"_Generated: {results['generated_at']} · Dataset: **Spider dev (subset)** · "
            f"{results['count']} examples · seed {sub['seed']} · Generator: {results['generator']}_"
        )
        caveat = (
            "> This is a **subset** of the Spider dev set, not the full benchmark. Numbers "
            "are measured on the examples run; no full-benchmark claim is made. The generator "
            "is a deterministic schema-aware heuristic (no LLM). Gold SQL is used only for "
            "scoring, never during generation."
        )
        scope_line = (
            f"Subset saved to `{sub['file']}` (deterministic for `--limit {sub['limit']} "
            f"--seed {sub['seed']}`)."
        )

    lines = [
        title,
        "",
        meta,
        "",
        caveat,
        "",
        scope_line,
        "",
        "| Metric | Baseline | Full |",
        "|---|---|---|",
        f"| Execution accuracy (of gold-executable) | {b['execution_accuracy_pct']}% | {f['execution_accuracy_pct']}% |",
        f"| Valid SQL generation rate | {b['valid_sql_generation_pct']}% | {f['valid_sql_generation_pct']}% |",
        f"| Execution success rate | {b['execution_success_pct']}% | {f['execution_success_pct']}% |",
        f"| Unsafe rejections | {b['unsafe_rejection_count']} | {f['unsafe_rejection_count']} |",
        f"| Avg latency (ms) | {b['avg_latency_ms']} | {f['avg_latency_ms']} |",
        f"| Est. cost (USD) | {b['estimated_cost_usd']} | {f['estimated_cost_usd']} |",
        "",
        f"**Absolute improvement (full − baseline):** {impr['absolute_pct']} pts  ",
        f"**Relative improvement:** {impr['relative_pct']}%  ",
        f"**Repairs:** {m['repair_successful_count']} successful / "
        f"{m['repair_attempted_count']} attempted  ",
        f"**Examples / gold-executable:** {b['total']} / {b['gold_executable']}",
        "",
    ]

    by_diff = results.get("by_difficulty") or {}
    if by_diff:
        lines += [
            "## Accuracy by estimated difficulty",
            "",
            "_Difficulty is a heuristic from the gold SQL structure (joins / nesting / set ops), "
            "for reporting only._",
            "",
            "| Difficulty | Gold-executable | Baseline acc | Full acc |",
            "|---|---|---|---|",
        ]
        for d in ("easy", "medium", "hard"):
            if d in by_diff:
                v = by_diff[d]
                lines.append(
                    f"| {d} | {v['gold_executable']} | {v['baseline_accuracy_pct']}% | "
                    f"{v['full_accuracy_pct']}% |"
                )
        lines.append("")

    lines += [
        "## Wrong-answer detection",
        "",
        "A *wrong-but-executable baseline* passed the guard, executed, and did not "
        "match gold. It is **caught** when the full pipeline repaired it to a "
        "gold-matching result (`repaired_to_correct`) or flagged it as implausible "
        "(`flagged_unverified`). Syntax errors and unsafe rejections are excluded.",
        "",
        f"- Executable-wrong baseline queries: **{m['executable_wrong_baseline_count']}**",
        f"- Wrong answers caught: **{m['wrong_answers_caught_count']}**",
        f"- Wrong-answer caught rate: **{m['wrong_answers_caught_rate']}%**",
        "",
    ]

    caught_cases = results["wrong_answer_detection"]["caught_cases"]
    if caught_cases:
        lines += ["### Caught cases", ""]
        for c in caught_cases[:20]:
            lines += [
                f"- **{c['db_id']}** — {c['question']}  ",
                f"  baseline: `{c['baseline_sql']}` → hash `{c['baseline_result_hash']}`  ",
                f"  gold hash: `{c['gold_result_hash']}`  ",
                f"  full: `{c['full_sql']}` → hash `{c['full_result_hash']}`  ",
                f"  caught: `{c['caught']}` · reason: `{c['reason']}`",
            ]
        lines.append("")

    if results["failures"]:
        lines += ["## Failed examples (debug)", ""]
        for fx in results["failures"][:20]:
            lines += [
                f"- **{fx['db_id']}** _({fx['difficulty']})_ — {fx['question']}  ",
                f"  gold: `{fx['gold_sql']}`  ",
                f"  baseline: `{fx['baseline_predicted_sql']}`  ",
                f"  full: `{fx['full_predicted_sql']}`  ",
                f"  reason: `{fx['reason']}`",
            ]
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate on the Spider dev set (subset or full).")
    parser.add_argument("--limit", type=int, default=50, help="number of examples (default 50; ignored with --full)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for subset selection (default 42)")
    parser.add_argument("--full", action="store_true",
                        help="evaluate the ENTIRE dev set (every example, no sampling)")
    parser.add_argument("--spider-dir", default=None, help="path to the Spider dir (dev.json + database/)")
    parser.add_argument("--out-dir", default=str(REPO / "spider"), help="where to write results")
    parser.add_argument("--max-candidates", type=int, default=_MAX_CANDIDATES,
                        help="full-mode candidates per example (default 3)")
    args = parser.parse_args()

    spider_dir = find_spider_dir(args.spider_dir)
    if spider_dir is None:
        print(
            "Spider data not found. Download the official Spider dev set and point\n"
            "the harness at it (see scripts/download_spider.py):\n"
            "  export SPIDER_DIR=/path/to/spider   # must contain dev.json + database/\n"
            "Then re-run:  backend/.venv/bin/python scripts/run_spider_subset.py --full",
            file=sys.stderr,
        )
        raise SystemExit(2)

    out_dir = Path(args.out_dir)
    if args.full:
        results = run_full(spider_dir, out_dir, args.max_candidates)
        basename = "results_full"
    else:
        results = run_subset(spider_dir, args.limit, args.seed, out_dir, args.max_candidates)
        basename = "results"

    m = results["metrics"]
    b, f, impr = m["baseline"], m["full"], m["improvement"]
    scope = "full dev set" if args.full else f"subset (seed {args.seed})"
    print(f"Ran {results['count']} Spider dev examples — {scope} · generator: {results['generator']}.")
    print(f"  baseline  exec-acc {b['execution_accuracy_pct']}%  valid-gen {b['valid_sql_generation_pct']}%  "
          f"exec-ok {b['execution_success_pct']}%  latency {b['avg_latency_ms']}ms")
    print(f"  full      exec-acc {f['execution_accuracy_pct']}%  valid-gen {f['valid_sql_generation_pct']}%  "
          f"exec-ok {f['execution_success_pct']}%  latency {f['avg_latency_ms']}ms")
    print(f"  improvement  +{impr['absolute_pct']} pts absolute  ({impr['relative_pct']}% relative)")
    print(f"  wrong-answer caught {m['wrong_answers_caught_count']}/{m['executable_wrong_baseline_count']} "
          f"({m['wrong_answers_caught_rate']}%)   repairs {m['repair_successful_count']}/{m['repair_attempted_count']}")
    print(f"  failures: {len(results['failures'])}")
    if not args.full:
        print(f"  subset saved: spider/{results['subset']['file']}")
    print(f"Wrote spider/{basename}.json and spider/{basename}.md")


if __name__ == "__main__":
    main()
