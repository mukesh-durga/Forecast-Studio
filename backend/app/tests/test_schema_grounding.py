"""Tests for schema-grounding validation (separate from SQL safety)."""

from app.services.schema_grounding import is_grounded

TABLES = {"customers", "products", "orders", "order_items", "support_tickets", "marketing_campaigns"}


def test_placeholder_select_null_is_not_grounded():
    assert is_grounded("SELECT NULL AS weather_tomorrow WHERE 1=0 LIMIT 1", TABLES) is False


def test_constant_selects_without_from_are_not_grounded():
    assert is_grounded("SELECT 1", TABLES) is False
    assert is_grounded("SELECT 'text' AS x", TABLES) is False
    assert is_grounded("SELECT 42 AS answer LIMIT 1", TABLES) is False


def test_query_with_real_table_is_grounded():
    assert is_grounded("SELECT city, COUNT(*) AS c FROM customers GROUP BY city", TABLES) is True


def test_query_with_join_of_real_tables_is_grounded():
    sql = (
        "SELECT p.name, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi JOIN products p ON p.id = oi.product_id GROUP BY p.name"
    )
    assert is_grounded(sql, TABLES) is True


def test_query_with_unknown_table_is_not_grounded():
    assert is_grounded("SELECT * FROM weather LIMIT 5", TABLES) is False


def test_query_mixing_real_and_unknown_table_is_not_grounded():
    assert is_grounded("SELECT * FROM customers JOIN weather ON 1=1", TABLES) is False


def test_cte_referencing_real_table_is_grounded():
    sql = (
        "WITH totals AS (SELECT customer_id, COUNT(*) c FROM orders GROUP BY customer_id) "
        "SELECT * FROM totals"
    )
    assert is_grounded(sql, TABLES) is True
