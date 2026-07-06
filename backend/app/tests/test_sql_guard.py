"""Tests for the SQL safety guard.

These are the safety-critical tests called out in CLAUDE.md. Run with:

    cd backend && pytest app/tests/test_sql_guard.py -v
"""

import pytest

from app.services.sql_guard import SqlGuardError, validate_sql

# Small, explicit limits so the assertions are easy to read.
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def guard(sql: str) -> str:
    return validate_sql(sql, default_limit=DEFAULT_LIMIT, max_limit=MAX_LIMIT)


def test_sql_guard_allows_select():
    result = guard("SELECT id, name FROM customers")
    assert result.upper().startswith("SELECT")
    assert "customers" in result


def test_sql_guard_blocks_delete():
    with pytest.raises(SqlGuardError):
        guard("DELETE FROM customers")


def test_sql_guard_blocks_drop():
    with pytest.raises(SqlGuardError):
        guard("DROP TABLE customers")


def test_sql_guard_blocks_insert():
    with pytest.raises(SqlGuardError):
        guard("INSERT INTO customers (name) VALUES ('x')")


def test_sql_guard_blocks_update():
    with pytest.raises(SqlGuardError):
        guard("UPDATE customers SET name = 'x' WHERE id = 1")


def test_sql_guard_blocks_multiple_statements():
    with pytest.raises(SqlGuardError):
        guard("SELECT * FROM customers; DROP TABLE customers")


def test_sql_guard_adds_limit():
    result = guard("SELECT id FROM customers")
    assert f"LIMIT {DEFAULT_LIMIT}" in result


def test_sql_guard_preserves_existing_limit():
    result = guard("SELECT id FROM customers LIMIT 5")
    assert "LIMIT 5" in result
    # Should not append a second LIMIT.
    assert result.upper().count("LIMIT") == 1


def test_sql_guard_blocks_comments():
    with pytest.raises(SqlGuardError):
        guard("SELECT id FROM customers -- DROP TABLE customers")
    with pytest.raises(SqlGuardError):
        guard("SELECT id FROM customers /* hidden */")


def test_sql_guard_enforces_max_limit():
    result = guard("SELECT id FROM customers LIMIT 100000")
    assert f"LIMIT {MAX_LIMIT}" in result
    assert "100000" not in result


# --- A few extra edge cases (not required, but cheap and reassuring) ---

def test_sql_guard_blocks_truncate():
    with pytest.raises(SqlGuardError):
        guard("TRUNCATE TABLE customers")


def test_sql_guard_blocks_alter():
    with pytest.raises(SqlGuardError):
        guard("ALTER TABLE customers ADD COLUMN x TEXT")


def test_sql_guard_blocks_empty():
    with pytest.raises(SqlGuardError):
        guard("   ")


def test_sql_guard_allows_with_cte():
    result = guard(
        "WITH totals AS (SELECT customer_id, COUNT(*) c FROM orders GROUP BY customer_id) "
        "SELECT * FROM totals"
    )
    assert f"LIMIT {DEFAULT_LIMIT}" in result


def test_sql_guard_allows_trailing_semicolon():
    result = guard("SELECT id FROM customers;")
    assert ";" not in result  # trailing semicolon is stripped


def test_sql_guard_column_named_like_keyword_is_ok():
    # `updated_at` / `created_at` must not trip the UPDATE / CREATE blocklist.
    result = guard("SELECT updated_at, created_at FROM orders")
    assert result.upper().startswith("SELECT")
