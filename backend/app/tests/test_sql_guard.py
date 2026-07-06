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


# Regression: the guard must never collapse internal whitespace such as the
# space in "GROUP BY p.name" (bug: it became "GROUP BYp.name").
TOP_PRODUCTS_SQL = (
    "SELECT p.name AS product_name, SUM(oi.quantity * oi.unit_price) AS revenue "
    "FROM order_items oi JOIN products p ON p.id = oi.product_id "
    "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"
)


def test_sql_guard_preserves_group_by_whitespace_in_range_limit():
    result = guard(TOP_PRODUCTS_SQL)  # LIMIT 5 is in range → preserved as-is
    assert "GROUP BY p.name" in result
    assert "GROUP BYp.name" not in result


def test_sql_guard_preserves_group_by_whitespace_when_clamping():
    # Force the clamp path; whitespace elsewhere must stay intact.
    over_limit = TOP_PRODUCTS_SQL.replace("LIMIT 5", "LIMIT 100000")
    result = guard(over_limit)
    assert "GROUP BY p.name" in result
    assert "GROUP BYp.name" not in result
    assert f"LIMIT {MAX_LIMIT}" in result


def test_sql_guard_preserves_group_by_whitespace_when_injecting():
    # No LIMIT → guard appends one; the GROUP BY space must be untouched.
    no_limit = "SELECT city, COUNT(*) AS c FROM customers GROUP BY city"
    result = guard(no_limit)
    assert "GROUP BY city LIMIT" in result
    assert "GROUP BYcity" not in result


def test_sql_guard_exact_top_products_input_is_not_mangled():
    """Regression for the reported bug using the exact reported input."""
    sql = (
        "SELECT p.name AS product_name, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"
    )
    result = validate_sql(sql)  # real config defaults; LIMIT 5 is in range
    assert "GROUP BY p.name" in result
    assert "GROUP BYp.name" not in result
    assert "ORDER BY revenue DESC" in result
    assert result == sql  # in-range LIMIT → original SQL returned unchanged


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
