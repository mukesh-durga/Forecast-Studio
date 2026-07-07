"""Tests for the free local SQL generator.

No API key, no network. Run with:

    cd backend && pytest app/tests/test_sql_generator.py -v
"""

import pytest

from app.services import schema_service
from app.services.sql_generator import LocalSqlGenerator, get_sql_generator
from app.services.sql_guard import validate_sql


@pytest.fixture
def schema():
    return schema_service.get_schema("demo")


@pytest.fixture
def generator():
    return LocalSqlGenerator()


# (question, expected intent, a substring that must appear in the SQL)
DEMO_CASES = [
    ("What are the top 5 products by revenue?", "top_products_by_revenue", "order_items"),
    ("Which city has the most customers?", "city_most_customers", "GROUP BY city"),
    ("What was the total revenue by month?", "monthly_revenue", "strftime"),
    ("Which product category generated the highest revenue?", "category_revenue", "category"),
    ("What is the average order value?", "average_order_value", "average_order_value"),
    ("Which customers placed the most orders?", "top_customers_by_orders", "order_count"),
    ("How many support tickets are still open?", "open_tickets", "status = 'open'"),
    ("Which issue type has the lowest satisfaction score?", "lowest_satisfaction_issue", "satisfaction_score"),
    ("What marketing channel had the highest spend?", "top_channel_by_spend", "marketing_campaigns"),
    ("Show monthly revenue trend.", "monthly_revenue", "GROUP BY month"),
]


@pytest.mark.parametrize("question,intent,fragment", DEMO_CASES)
def test_demo_question_maps_to_expected_intent(generator, schema, question, intent, fragment):
    result = generator.generate(question, schema)
    assert result.matched is True
    assert result.intent == intent
    assert fragment in result.sql


@pytest.mark.parametrize("question,intent,fragment", DEMO_CASES)
def test_generated_sql_passes_guard(generator, schema, question, intent, fragment):
    result = generator.generate(question, schema)
    safe = validate_sql(result.sql)          # must not raise
    assert safe.upper().startswith("SELECT")


def test_unrecognized_question_is_unsupported(generator, schema):
    result = generator.generate("please compute the meaning of life", schema)
    assert result.matched is False
    assert result.intent == "unsupported"
    # No executable SQL is fabricated for unsupported questions.
    assert result.sql == ""


def test_generated_sql_only_uses_real_tables(generator, schema):
    real_tables = {t.name for t in schema.tables}
    for question, _intent, _frag in DEMO_CASES:
        sql = generator.generate(question, schema).sql.lower()
        for candidate in ("customers", "products", "orders", "order_items",
                          "support_tickets", "marketing_campaigns"):
            if candidate in sql:
                assert candidate in real_tables


def test_example_questions_have_natural_spacing():
    from app.services.sql_generator import EXAMPLE_QUESTIONS

    assert "Which product category generated the highest revenue?" in EXAMPLE_QUESTIONS
    joined = " ".join(EXAMPLE_QUESTIONS)
    for glued in ("generatedthe", "categorygenerated", "highestrevenue"):
        assert glued not in joined


def test_factory_returns_local_generator():
    gen = get_sql_generator()
    assert isinstance(gen, LocalSqlGenerator)
    assert gen.backend_name == "local"


def test_top_products_end_to_end_preserves_whitespace(generator, schema):
    """Regression: 'top 5 products by revenue' must keep 'GROUP BY p.name'
    intact after passing through the guard (bug: 'GROUP BYp.name')."""
    result = generator.generate("What are the top 5 products by revenue?", schema)
    final = validate_sql(result.sql)
    assert "GROUP BY p.name" in final
    assert "GROUP BYp.name" not in final
    assert final.rstrip().endswith("LIMIT 5")
