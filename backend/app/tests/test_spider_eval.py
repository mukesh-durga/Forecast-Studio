"""Tests for the Spider-subset evaluation harness (Milestone 20).

Three layers, none of which need the real Spider download:
  1. pure metric logic (spider_eval) on toy records;
  2. the schema-aware Spider generator (spider_generator) on tiny fake schemas;
  3. an end-to-end run of run_spider_subset on a self-built Spider-format
     fixture (temp SQLite db + dev.json).

Nothing consults gold SQL to generate; no accuracy numbers are asserted.
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
import spider_generator  # noqa: E402
from app.services.sql_guard import validate_sql  # noqa: E402


# --- pure metric logic ------------------------------------------------------

def test_order_sensitive_detects_order_by():
    assert spider_eval.order_sensitive("SELECT a FROM t ORDER BY a") is True
    assert spider_eval.order_sensitive("SELECT a FROM t") is False


def test_results_match_unordered_multiset():
    a = [{"x": 1}, {"x": 2}]
    b = [{"x": 2}, {"x": 1}]
    assert spider_eval.results_match(a, b, order_matters=False) is True
    assert spider_eval.results_match(a, b, order_matters=True) is False


def test_results_match_requires_same_multiset():
    assert spider_eval.results_match([{"x": 1}], [{"x": 1}, {"x": 1}], False) is False
    assert spider_eval.results_match([{"x": 1}], [{"x": 2}], False) is False


def test_results_match_none_never_matches():
    assert spider_eval.results_match(None, [{"x": 1}], False) is False
    assert spider_eval.results_match([{"x": 1}], None, False) is False


def test_results_match_float_and_null_normalization():
    assert spider_eval.results_match([{"v": 1.0000001}], [{"v": 1.0}], False) is True
    assert spider_eval.results_match([{"v": None}], [{"v": None}], False) is True


def _mode(**over):
    base = {
        "generated": False, "guard_passed": False, "unsafe_rejected": False,
        "pred_executed": False, "correct": False, "verified": False,
        "repair_attempted": False, "repair_successful": False, "latency_ms": 1.0,
    }
    base.update(over)
    return base


def test_estimate_difficulty():
    assert spider_eval.estimate_difficulty("SELECT count(*) FROM t") == "easy"
    assert spider_eval.estimate_difficulty("SELECT a FROM t JOIN u ON t.id = u.id") == "medium"
    assert spider_eval.estimate_difficulty("SELECT a FROM t GROUP BY a") == "medium"
    assert spider_eval.estimate_difficulty("SELECT a FROM t WHERE x IN (SELECT y FROM z)") == "hard"
    assert spider_eval.estimate_difficulty("SELECT a FROM t UNION SELECT b FROM u") == "hard"


def test_aggregate_baseline_full_and_caught():
    records = [
        {"gold_ok": True,
         "baseline": _mode(generated=True, guard_passed=True, pred_executed=True, correct=True),
         "full": _mode(generated=True, guard_passed=True, pred_executed=True, correct=True, verified=True)},
        {"gold_ok": True,
         "baseline": _mode(generated=True, guard_passed=True, pred_executed=True, correct=False),
         "full": _mode(generated=True, guard_passed=True, pred_executed=True, correct=False,
                       verified=False, repair_attempted=True, repair_successful=True)},
    ]
    m = spider_eval.aggregate(records)
    assert m["baseline"]["execution_accuracy_pct"] == 50.0
    assert m["full"]["execution_accuracy_pct"] == 50.0
    assert m["improvement"]["absolute_pct"] == 0.0
    # Baseline executed-but-wrong on example 2; full flagged it (verified False) -> caught.
    assert m["executable_wrong_baseline_count"] == 1
    assert m["wrong_answers_caught_count"] == 1
    assert m["wrong_answers_caught_rate"] == 100.0
    assert m["repair_attempted_count"] == 1
    assert m["repair_successful_count"] == 1
    assert m["baseline"]["estimated_cost_usd"] == 0.0


# --- wrong-answer detection classification (Phase 23) -----------------------

def _base(**over):
    return _mode(**over)


def test_wrong_answer_caught_when_full_repairs():
    # baseline executable + wrong; full correct -> caught (repaired).
    exec_wrong, caught, reason = spider_eval.wrong_answer_status(
        _base(guard_passed=True, pred_executed=True, correct=False),
        _base(guard_passed=True, pred_executed=True, correct=True, verified=True),
        gold_ok=True,
    )
    assert (exec_wrong, caught, reason) == (True, True, "repaired_to_correct")


def test_wrong_answer_caught_when_full_flags_unverified():
    exec_wrong, caught, reason = spider_eval.wrong_answer_status(
        _base(guard_passed=True, pred_executed=True, correct=False),
        _base(guard_passed=True, pred_executed=True, correct=False, verified=False),
        gold_ok=True,
    )
    assert (exec_wrong, caught, reason) == (True, True, "flagged_unverified")


def test_wrong_answer_missed_when_full_confidently_wrong():
    exec_wrong, caught, reason = spider_eval.wrong_answer_status(
        _base(guard_passed=True, pred_executed=True, correct=False),
        _base(guard_passed=True, pred_executed=True, correct=False, verified=True),
        gold_ok=True,
    )
    assert (exec_wrong, caught, reason) == (True, False, "missed_still_wrong")


def test_syntax_error_baseline_not_counted():
    # Guard passed but the query failed to execute -> not executable-wrong.
    exec_wrong, caught, reason = spider_eval.wrong_answer_status(
        _base(guard_passed=True, pred_executed=False),
        _base(guard_passed=True, pred_executed=True, correct=True, verified=True),
        gold_ok=True,
    )
    assert exec_wrong is False and caught is False
    assert reason == "baseline_not_executable"


def test_unsafe_baseline_not_counted():
    # Guard blocked the baseline (unsafe) -> never executable, not counted.
    exec_wrong, caught, reason = spider_eval.wrong_answer_status(
        _base(generated=True, unsafe_rejected=True, guard_passed=False, pred_executed=False),
        _base(guard_passed=True, pred_executed=True, correct=True, verified=True),
        gold_ok=True,
    )
    assert exec_wrong is False and caught is False
    assert reason == "baseline_not_executable"


def test_correct_baseline_not_counted():
    exec_wrong, caught, reason = spider_eval.wrong_answer_status(
        _base(guard_passed=True, pred_executed=True, correct=True),
        _base(guard_passed=True, pred_executed=True, correct=True, verified=True),
        gold_ok=True,
    )
    assert exec_wrong is False and caught is False
    assert reason == "baseline_correct"


def test_result_fingerprint_matches_iff_results_match():
    a = [{"n": 1}, {"n": 2}]
    b = [{"n": 2}, {"n": 1}]
    # Order-insensitive: same multiset -> same hash.
    assert spider_eval.result_fingerprint(a, False) == spider_eval.result_fingerprint(b, False)
    # Order-sensitive: different order -> different hash.
    assert spider_eval.result_fingerprint(a, True) != spider_eval.result_fingerprint(b, True)
    assert spider_eval.result_fingerprint(None, False) is None


def test_wrong_answer_detection_on_toy_db(tmp_path):
    """Real toy DB: baseline COUNT is executable but wrong; full SUM matches gold."""
    con = sqlite3.connect(tmp_path / "toy.sqlite")
    con.executescript("CREATE TABLE nums(n INTEGER); INSERT INTO nums VALUES (2),(3),(5);")

    def run(sql):
        try:
            cur = con.execute(sql)
            return [tuple(r) for r in cur.fetchall()]
        except sqlite3.Error:
            return None

    gold = run("SELECT SUM(n) FROM nums")                 # [(10,)]
    baseline_rows = run("SELECT COUNT(n) FROM nums")       # [(3,)] executable + wrong
    full_rows = run("SELECT SUM(n) FROM nums")             # [(10,)] correct

    baseline = _base(generated=True, guard_passed=True, pred_executed=True,
                     correct=spider_eval.results_match(baseline_rows, gold, False))
    full = _base(generated=True, guard_passed=True, pred_executed=True,
                 correct=spider_eval.results_match(full_rows, gold, False), verified=True)

    exec_wrong, caught, reason = spider_eval.wrong_answer_status(baseline, full, gold_ok=True)
    assert exec_wrong is True and caught is True and reason == "repaired_to_correct"
    # Hashes: baseline != gold, full == gold.
    assert spider_eval.result_fingerprint(baseline_rows, False) != spider_eval.result_fingerprint(gold, False)
    assert spider_eval.result_fingerprint(full_rows, False) == spider_eval.result_fingerprint(gold, False)


def test_aggregate_improvement_computed():
    records = [
        {"gold_ok": True,
         "baseline": _mode(generated=True, guard_passed=True, pred_executed=True, correct=False),
         "full": _mode(generated=True, guard_passed=True, pred_executed=True, correct=True, verified=True)},
        {"gold_ok": True,
         "baseline": _mode(generated=True, guard_passed=True, pred_executed=True, correct=True),
         "full": _mode(generated=True, guard_passed=True, pred_executed=True, correct=True, verified=True)},
    ]
    m = spider_eval.aggregate(records)
    assert m["baseline"]["execution_accuracy_pct"] == 50.0
    assert m["full"]["execution_accuracy_pct"] == 100.0
    assert m["improvement"]["absolute_pct"] == 50.0
    assert m["improvement"]["relative_pct"] == 100.0


def test_aggregate_accuracy_denominator_is_gold_executable():
    records = [
        {"gold_ok": True,
         "baseline": _mode(generated=True, guard_passed=True, pred_executed=True, correct=True),
         "full": _mode()},
        {"gold_ok": False,
         "baseline": _mode(generated=True, guard_passed=True, pred_executed=True),
         "full": _mode()},
    ]
    m = spider_eval.aggregate(records)
    assert m["baseline"]["gold_executable"] == 1
    assert m["baseline"]["execution_accuracy_pct"] == 100.0


# --- Spider generator on a tiny fake schema --------------------------------

@pytest.fixture
def gen():
    Column = spider_generator.Column
    schema = spider_generator.SpiderSchema(
        db_id="concert",
        tables={
            "singer": [
                Column("Singer_ID", "INTEGER", pk=True),
                Column("Name", "TEXT"),
                Column("Country", "TEXT"),
                Column("Age", "INTEGER"),
            ],
            "stadium": [
                Column("Stadium_ID", "INTEGER", pk=True),
                Column("Name", "TEXT"),
                Column("Capacity", "INTEGER"),
            ],
        },
    )
    return spider_generator.SpiderGenerator(schema)


def test_generate_count(gen):
    sql = gen.generate_sql("How many singers are there?")
    assert sql == 'SELECT count(*) FROM "singer"'


def test_generate_group_by_count(gen):
    sql = gen.generate_sql("How many singers are in each country?")
    assert sql == 'SELECT "Country", count(*) FROM "singer" GROUP BY "Country"'


def test_generate_aggregate(gen):
    sql = gen.generate_sql("What is the average age of singers?")
    assert sql == 'SELECT AVG("Age") FROM "singer"'


def test_generate_multi_aggregate_in_order(gen):
    sql = gen.generate_sql("What is the average, minimum, and maximum age of singers?")
    assert sql == 'SELECT AVG("Age"), MIN("Age"), MAX("Age") FROM "singer"'


def test_generate_columns_with_order(gen):
    sql = gen.generate_sql("Show the names and ages of singers ordered by age descending.")
    assert sql == 'SELECT "Name", "Age" FROM "singer" ORDER BY "Age" DESC'


def test_generate_numeric_where(gen):
    # The column must be named for the heuristic to filter on it (no semantic
    # "older" -> Age inference is claimed).
    sql = gen.generate_sql("Show the names of singers with age greater than 30.")
    assert 'WHERE "Age" > 30' in sql
    assert sql.startswith("SELECT ")


def test_unknown_table_returns_none(gen):
    assert gen.generate_sql("What is the meaning of life?") is None


def test_generated_sql_is_always_select_and_guard_passes(gen):
    for q in [
        "How many singers are there?",
        "What is the average age of singers?",
        "Show the names and ages of singers ordered by age descending.",
        "How many singers are in each country?",
    ]:
        sql = gen.generate_sql(q)
        assert sql.upper().startswith("SELECT")
        # Passes the app's real safety guard (SELECT-only, single statement).
        assert validate_sql(sql).upper().startswith("SELECT")


# --- full mode: value linking + candidates ---------------------------------

@pytest.fixture
def battle_db():
    """Fake schema + in-memory DB for value-linking tests."""
    Column = spider_generator.Column
    schema = spider_generator.SpiderSchema(
        db_id="battle_death",
        tables={"battle": [
            Column("id", "INTEGER", pk=True),
            Column("name", "TEXT"),
            Column("bulgarian_commander", "TEXT"),
            Column("latin_commander", "TEXT"),
        ]},
    )
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE battle(id INTEGER, name TEXT, bulgarian_commander TEXT, latin_commander TEXT);"
        "INSERT INTO battle VALUES (1, 'Battle of Varna', 'Kaloyan', 'Baldwin I'),"
        " (2, 'Battle of Serres', 'Boril', 'Henry');"
    )
    return schema, conn


def test_value_linking_finds_db_values(battle_db):
    schema, conn = battle_db
    links = spider_generator.link_values(
        "battles between 'Kaloyan' and 'Baldwin I'", schema, conn
    )
    cols = {(t, c, v) for (t, c, v) in links}
    assert ("battle", "bulgarian_commander", "Kaloyan") in cols
    assert ("battle", "latin_commander", "Baldwin I") in cols


def test_full_candidates_use_value_linked_where(battle_db):
    schema, conn = battle_db
    cands = spider_generator.build_full_candidates(
        "What are the distinct battle names between bulgarian commander 'Kaloyan' "
        "and latin commander 'Baldwin I'?",
        schema, conn,
    )
    joined = " ".join(cands)
    assert '"bulgarian_commander" = \'Kaloyan\'' in joined
    assert '"latin_commander" = \'Baldwin I\'' in joined
    assert any(c.strip().upper().startswith("SELECT DISTINCT") for c in cands)
    # Every candidate is a guard-passing SELECT.
    for c in cands:
        assert validate_sql(c).upper().startswith("SELECT")


def test_full_candidates_execute_and_match_gold(battle_db):
    schema, conn = battle_db
    cands = spider_generator.build_full_candidates(
        "What are the battle names with bulgarian commander 'Kaloyan'?", schema, conn
    )
    # A candidate returns exactly the value-filtered row (name only, filter excluded).
    got = [conn.execute(validate_sql(c)).fetchall() for c in cands]
    assert [("Battle of Varna",)] in got


# --- end-to-end on a tiny self-built Spider-format fixture ------------------

@pytest.fixture
def toy_spider(tmp_path):
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
    results = harness.run_subset(toy_spider, limit=10, seed=42, out_dir=out_dir)

    assert (out_dir / "results.json").exists()
    assert (out_dir / "results.md").exists()
    # Deterministic subset was saved.
    assert (out_dir / "subsets" / "dev_10_seed42.json").exists()
    assert results["count"] == 2
    assert "generated_at" in results
    for mode in ("baseline", "full"):
        m = results["metrics"][mode]
        for key in ("execution_accuracy_pct", "valid_sql_generation_pct",
                    "execution_success_pct", "unsafe_rejection_count",
                    "avg_latency_ms", "gold_executable", "estimated_cost_usd"):
            assert key in m
    # Comparison + caught + repair metrics are top-level.
    for key in ("improvement", "executable_wrong_baseline_count",
                "wrong_answers_caught_count", "wrong_answers_caught_rate",
                "repair_attempted_count", "repair_successful_count"):
        assert key in results["metrics"]
    assert results["metrics"]["baseline"]["gold_executable"] == 2
    # The count question generates the exact gold SQL -> a real correct example.
    assert results["metrics"]["full"]["execution_accuracy_pct"] > 0
    # Per-example difficulty + wrong-answer debug fields are recorded.
    assert all(e["difficulty"] in ("easy", "medium", "hard") for e in results["examples"])
    assert all("gold_result_hash" in e and "caught" in e for e in results["examples"])
    assert "wrong_answer_detection" in results
    for e in results["examples"]:
        assert "result_hash" in e["baseline"] and "result_hash" in e["full"]
    md = (out_dir / "results.md").read_text().lower()
    assert "subset" in md
    assert "not the full benchmark" in md
    assert "no full-benchmark claim" in md


def test_harness_full_run_writes_full_artifacts(toy_spider, tmp_path):
    import run_spider_subset as harness

    out_dir = tmp_path / "out"
    results = harness.run_full(toy_spider, out_dir=out_dir)

    # Full-mode artifacts are written under a distinct basename (never clobbering
    # the subset results.json/md).
    assert (out_dir / "results_full.json").exists()
    assert (out_dir / "results_full.md").exists()
    assert not (out_dir / "results.json").exists()
    # No sampling: every dev example is run, and no subset file is saved.
    assert results["count"] == 2
    assert results["dataset"] == "Spider dev (full)"
    assert results["subset"]["full"] is True
    assert results["subset"]["seed"] is None
    assert not (out_dir / "subsets").exists()
    # Per-difficulty breakdown is present and its denominators are gold-executable.
    by_diff = results["by_difficulty"]
    assert by_diff
    assert sum(v["gold_executable"] for v in by_diff.values()) == 2
    md = (out_dir / "results_full.md").read_text().lower()
    assert "full dev-set" in md
    assert "entire spider dev set" in md
    assert "accuracy by estimated difficulty" in md
    # An honest full run makes NO full-benchmark subset caveat but also claims no SOTA.
    assert "not** a state-of-the-art" in md or "not a state-of-the-art" in md


def test_write_markdown_switches_header_on_full_flag():
    import run_spider_subset as harness

    def _fake_results(full: bool) -> dict:
        return {
            "generated_at": "2026-07-12T00:00:00+00:00",
            "generator": "spider-heuristic",
            "count": 1032,
            "subset": ({"limit": 1032, "seed": None, "file": None, "full": True} if full
                       else {"limit": 50, "seed": 42, "file": "subsets/dev_50_seed42.json", "full": False}),
            "by_difficulty": {"easy": {"gold_executable": 1, "baseline_accuracy_pct": 50.0,
                                       "full_accuracy_pct": 100.0, "baseline_correct": 0, "full_correct": 1}},
            "metrics": {
                "baseline": {"execution_accuracy_pct": 11.0, "valid_sql_generation_pct": 98.2,
                             "execution_success_pct": 96.7, "unsafe_rejection_count": 0,
                             "avg_latency_ms": 1.2, "estimated_cost_usd": 0.0,
                             "total": 1032, "gold_executable": 1032},
                "full": {"execution_accuracy_pct": 15.3, "valid_sql_generation_pct": 98.9,
                         "execution_success_pct": 97.7, "unsafe_rejection_count": 0,
                         "avg_latency_ms": 1.5, "estimated_cost_usd": 0.0,
                         "total": 1032, "gold_executable": 1032},
                "improvement": {"absolute_pct": 4.3, "relative_pct": 39.1},
                "executable_wrong_baseline_count": 885, "wrong_answers_caught_count": 49,
                "wrong_answers_caught_rate": 5.5,
                "repair_attempted_count": 13, "repair_successful_count": 0,
            },
            "wrong_answer_detection": {"caught_cases": []},
            "failures": [],
        }

    full_md = harness.write_markdown(_fake_results(full=True))
    assert "full dev-set" in full_md.lower()
    assert "entire Spider dev set" in full_md
    assert "seed" not in full_md.split("## ")[0].lower()  # no seed caveat in the full header block

    sub_md = harness.write_markdown(_fake_results(full=False))
    assert "Spider-subset Evaluation" in sub_md
    assert "not the full benchmark" in sub_md.lower()


def test_build_schema_from_sqlite(toy_spider):
    import run_spider_subset as harness

    db = toy_spider / "database" / "toydb" / "toydb.sqlite"
    schema = harness.build_schema_from_sqlite("toydb", str(db))
    assert schema.dialect == "sqlite"
    assert {t.name for t in schema.tables} == {"city"}
