"""Tests for the Spider-subset evaluation harness (Milestone 20).

Two layers:
  1. pure metric logic (spider_eval) on toy records — no DB, no Spider needed;
  2. an end-to-end run of run_spider_subset on a tiny, self-built Spider-format
     fixture (a temp SQLite db + dev.json). This proves the harness executes and
     writes results without any real Spider data — and without inventing numbers.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# Make the scripts/ modules importable.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))

import spider_eval  # noqa: E402


# --- pure metric logic ------------------------------------------------------

def test_order_sensitive_detects_order_by():
    assert spider_eval.order_sensitive("SELECT a FROM t ORDER BY a") is True
    assert spider_eval.order_sensitive("SELECT a FROM t") is False


def test_results_match_unordered_multiset():
    a = [{"x": 1}, {"x": 2}]
    b = [{"x": 2}, {"x": 1}]
    assert spider_eval.results_match(a, b, order_matters=False) is True
    # With order enforced, the differing order fails.
    assert spider_eval.results_match(a, b, order_matters=True) is False


def test_results_match_requires_same_multiset():
    assert spider_eval.results_match([{"x": 1}], [{"x": 1}, {"x": 1}], False) is False
    assert spider_eval.results_match([{"x": 1}], [{"x": 2}], False) is False


def test_results_match_none_never_matches():
    assert spider_eval.results_match(None, [{"x": 1}], False) is False
    assert spider_eval.results_match([{"x": 1}], None, False) is False


def test_results_match_float_and_null_normalization():
    assert spider_eval.results_match(
        [{"v": 1.0000001}], [{"v": 1.0}], order_matters=False
    ) is True
    assert spider_eval.results_match(
        [{"v": None}], [{"v": None}], order_matters=False
    ) is True


def _record(mode_overrides):
    base = {
        "generated": False, "unsafe_rejected": False, "pred_executed": False,
        "correct": False, "caught_wrong": False, "latency_ms": 1.0,
    }
    rec = {"gold_ok": True, "baseline": dict(base), "full": dict(base)}
    for mode, over in mode_overrides.items():
        rec[mode].update(over)
    return rec


def test_aggregate_counts_and_rates():
    records = [
        _record({"baseline": {"generated": True, "pred_executed": True, "correct": True},
                 "full": {"generated": True, "pred_executed": True, "correct": True}}),
        _record({"baseline": {"generated": True, "unsafe_rejected": True},
                 "full": {"generated": True, "pred_executed": True, "correct": False,
                          "caught_wrong": True}}),
    ]
    m = spider_eval.aggregate(records)
    # Baseline: 1/2 correct = 50%, 1/2 executed = 50% valid, 1 unsafe rejection.
    assert m["baseline"]["execution_accuracy_pct"] == 50.0
    assert m["baseline"]["generation_validity_pct"] == 50.0
    assert m["baseline"]["unsafe_rejection_count"] == 1
    assert m["baseline"]["wrong_answer_caught_count"] == 0
    # Full: caught one wrong answer via verification.
    assert m["full"]["wrong_answer_caught_count"] == 1
    assert m["full"]["execution_accuracy_pct"] == 50.0


def test_aggregate_accuracy_denominator_is_gold_executable():
    records = [
        _record({"baseline": {"generated": True, "pred_executed": True, "correct": True}}),
        {"gold_ok": False,
         "baseline": {"generated": True, "unsafe_rejected": False, "pred_executed": True,
                      "correct": False, "caught_wrong": False, "latency_ms": 1.0},
         "full": {"generated": False, "unsafe_rejected": False, "pred_executed": False,
                  "correct": False, "caught_wrong": False, "latency_ms": 1.0}},
    ]
    m = spider_eval.aggregate(records)
    # Only 1 example has an executable gold, and it's correct -> 100%.
    assert m["baseline"]["gold_executable"] == 1
    assert m["baseline"]["execution_accuracy_pct"] == 100.0


# --- end-to-end on a tiny self-built Spider-format fixture ------------------

@pytest.fixture
def toy_spider(tmp_path):
    """Build a minimal dir shaped like Spider: dev.json + database/<id>/<id>.sqlite."""
    db_id = "toydb"
    db_dir = tmp_path / "database" / db_id
    db_dir.mkdir(parents=True)
    con = sqlite3.connect(db_dir / f"{db_id}.sqlite")
    con.executescript(
        "CREATE TABLE city (name TEXT, population INTEGER);"
        "INSERT INTO city VALUES ('Austin', 5), ('Dallas', 3), ('Houston', 9);"
    )
    con.commit()
    con.close()
    dev = [
        {"db_id": db_id, "question": "How many cities are there?",
         "query": "SELECT count(*) FROM city"},
        {"db_id": db_id, "question": "List city names ordered by population.",
         "query": "SELECT name FROM city ORDER BY population"},
    ]
    (tmp_path / "dev.json").write_text(json.dumps(dev))
    return tmp_path


def test_harness_runs_end_to_end_and_writes_results(toy_spider, tmp_path):
    import run_spider_subset as harness

    out_dir = tmp_path / "out"
    results = harness.run_subset(toy_spider, limit=10, out_dir=out_dir)

    # Files written.
    assert (out_dir / "results.json").exists()
    assert (out_dir / "results.md").exists()

    # Structure + provenance recorded (timestamp + provider), nothing hardcoded.
    assert results["count"] == 2
    assert results["provider"] == "local"
    assert "generated_at" in results
    for mode in ("baseline", "full"):
        m = results["metrics"][mode]
        for key in ("execution_accuracy_pct", "generation_validity_pct",
                    "unsafe_rejection_count", "wrong_answer_caught_count",
                    "avg_latency_ms", "gold_executable"):
            assert key in m
    # Gold SQL executes for both toy examples.
    assert results["metrics"]["baseline"]["gold_executable"] == 2
    # Markdown clearly labels this a subset and disclaims the full benchmark.
    md = (out_dir / "results.md").read_text().lower()
    assert "subset" in md
    assert "not the full benchmark" in md
    assert "no full-benchmark claim" in md


def test_build_schema_from_sqlite(toy_spider):
    import run_spider_subset as harness

    db = toy_spider / "database" / "toydb" / "toydb.sqlite"
    schema = harness.build_schema_from_sqlite("toydb", str(db))
    assert schema.dialect == "sqlite"
    assert {t.name for t in schema.tables} == {"city"}
