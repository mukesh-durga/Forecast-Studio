"""Query planning service.

Decomposes a natural-language question into a structured ``QueryPlan`` *before*
SQL generation — a real multi-step flow:

  1. detect intent (keyword matchers, most-specific first),
  2. look up the intent's structured spec (tables, columns, joins, measures,
     dimensions, filters, group_by, order_by, limit, expected result columns),
  3. ground the spec against the live schema (missing tables => unsupported),
  4. adapt dialect-specific expressions (e.g. month bucketing),
  5. score a deterministic confidence from question-token coverage.

- The local generator renders SQL directly from the plan
  (``sql_generator.render_sql_from_plan``) — no separate string templates.
- The Groq generator receives the plan (plus schema context) as guidance.

Owning intent detection here (rather than in the SQL generator) keeps a single
source of truth for "what is this question asking?" and avoids import cycles.
"""

from __future__ import annotations

import re
from typing import Callable

from app.models.responses import QueryPlan, SchemaResponse

# Words that signal a "highest / ranked" intent. Shared by the ranking matchers.
_RANKING_WORDS = (
    "top", "best", "most", "highest", "largest", "leading", "biggest", "greatest",
)


def _ranked(n: str) -> bool:
    return any(w in n for w in _RANKING_WORDS)


# Intent matchers, ordered most-specific first (first match wins).
_MATCHERS: list[tuple[str, Callable[[str], bool]]] = [
    ("category_revenue", lambda n: "category" in n and "revenue" in n),
    ("monthly_revenue", lambda n: "month" in n and ("revenue" in n or "trend" in n)),
    # "product(s)" + "revenue" ranked highest — covers paraphrases like "products
    # that made the most revenue", "highest sales revenue", "best-selling ... by
    # revenue". The "revenue" gate keeps non-analytics questions unsupported.
    ("top_products_by_revenue", lambda n: "product" in n and "revenue" in n and _ranked(n)),
    ("average_order_value", lambda n: ("average" in n or "avg" in n) and "order" in n),
    ("top_customers_by_orders", lambda n: "customer" in n and "order" in n and ("most" in n or "placed" in n)),
    ("city_most_customers", lambda n: "city" in n and "customer" in n),
    ("open_tickets", lambda n: "ticket" in n and "open" in n),
    ("lowest_satisfaction_issue", lambda n: "issue" in n and ("satisfaction" in n or "score" in n)),
    ("top_channel_by_spend", lambda n: ("channel" in n or "marketing" in n) and ("spend" in n or "spent" in n)),
]

# Dialect-specific month-bucket expression. "{MONTH}" in a spec dimension is
# replaced with the right expression for the target connection's dialect.
_MONTH_EXPR = {
    "sqlite": "strftime('%Y-%m', orders.order_date)",
    "postgresql": "to_char(orders.order_date, 'YYYY-MM')",
}

_REVENUE = "SUM(order_items.quantity * order_items.unit_price) AS revenue"

# Structured plan per intent. `required_tables` are validated against the live
# schema; a plan whose tables are missing is treated as unsupported.
PLAN_SPECS: dict[str, dict] = {
    "top_products_by_revenue": {
        "required_tables": ["order_items", "products"],
        "required_columns": [
            "order_items.product_id", "order_items.quantity",
            "order_items.unit_price", "products.id", "products.name",
        ],
        "joins": ["order_items.product_id = products.id"],
        "measures": [_REVENUE],
        "dimensions": ["products.name AS product_name"],
        "filters": [],
        "group_by": ["products.name"],
        "order_by": ["revenue DESC"],
        "limit": 5,
        "expected_result_columns": ["product_name", "revenue"],
    },
    "city_most_customers": {
        "required_tables": ["customers"],
        "required_columns": ["customers.city"],
        "joins": [],
        "measures": ["COUNT(*) AS customer_count"],
        "dimensions": ["customers.city"],
        "filters": [],
        "group_by": ["customers.city"],
        "order_by": ["customer_count DESC"],
        "limit": 1,
        "expected_result_columns": ["city", "customer_count"],
    },
    "monthly_revenue": {
        "required_tables": ["orders", "order_items"],
        "required_columns": [
            "orders.id", "orders.order_date", "order_items.order_id",
            "order_items.quantity", "order_items.unit_price",
        ],
        "joins": ["order_items.order_id = orders.id"],
        "measures": [_REVENUE],
        "dimensions": ["{MONTH} AS month"],
        "filters": [],
        "group_by": ["month"],
        "order_by": ["month ASC"],
        "limit": None,
        "expected_result_columns": ["month", "revenue"],
    },
    "category_revenue": {
        "required_tables": ["order_items", "products"],
        "required_columns": [
            "order_items.product_id", "order_items.quantity",
            "order_items.unit_price", "products.id", "products.category",
        ],
        "joins": ["order_items.product_id = products.id"],
        "measures": [_REVENUE],
        "dimensions": ["products.category"],
        "filters": [],
        "group_by": ["products.category"],
        "order_by": ["revenue DESC"],
        "limit": 1,
        "expected_result_columns": ["category", "revenue"],
    },
    "average_order_value": {
        "required_tables": ["orders", "order_items"],
        "required_columns": [
            "orders.id", "order_items.order_id",
            "order_items.quantity", "order_items.unit_price",
        ],
        "joins": ["order_items.order_id = orders.id"],
        "measures": [
            "SUM(order_items.quantity * order_items.unit_price) / COUNT(DISTINCT orders.id) "
            "AS average_order_value"
        ],
        "dimensions": [],
        "filters": [],
        "group_by": [],
        "order_by": [],
        "limit": None,
        "expected_result_columns": ["average_order_value"],
    },
    "top_customers_by_orders": {
        "required_tables": ["customers", "orders"],
        "required_columns": [
            "customers.id", "customers.name", "orders.customer_id", "orders.id",
        ],
        "joins": ["orders.customer_id = customers.id"],
        "measures": ["COUNT(orders.id) AS order_count"],
        "dimensions": ["customers.name AS customer_name"],
        "filters": [],
        # Group by id too, so distinct customers sharing a name stay separate.
        "group_by": ["customers.id", "customers.name"],
        "order_by": ["order_count DESC"],
        "limit": 5,
        "expected_result_columns": ["customer_name", "order_count"],
    },
    "open_tickets": {
        "required_tables": ["support_tickets"],
        "required_columns": ["support_tickets.status"],
        "joins": [],
        "measures": ["COUNT(*) AS open_tickets"],
        "dimensions": [],
        "filters": ["support_tickets.status = 'open'"],
        "group_by": [],
        "order_by": [],
        "limit": None,
        "expected_result_columns": ["open_tickets"],
    },
    "lowest_satisfaction_issue": {
        "required_tables": ["support_tickets"],
        "required_columns": [
            "support_tickets.issue_type", "support_tickets.satisfaction_score",
        ],
        "joins": [],
        "measures": ["AVG(support_tickets.satisfaction_score) AS avg_satisfaction"],
        "dimensions": ["support_tickets.issue_type"],
        "filters": ["support_tickets.satisfaction_score IS NOT NULL"],
        "group_by": ["support_tickets.issue_type"],
        "order_by": ["avg_satisfaction ASC"],
        "limit": 1,
        "expected_result_columns": ["issue_type", "avg_satisfaction"],
    },
    "top_channel_by_spend": {
        "required_tables": ["marketing_campaigns"],
        "required_columns": ["marketing_campaigns.channel", "marketing_campaigns.spend"],
        "joins": [],
        "measures": ["SUM(marketing_campaigns.spend) AS total_spend"],
        "dimensions": ["marketing_campaigns.channel"],
        "filters": [],
        "group_by": ["marketing_campaigns.channel"],
        "order_by": ["total_spend DESC"],
        "limit": 1,
        "expected_result_columns": ["channel", "total_spend"],
    },
}

UNSUPPORTED_INTENT = "unsupported"

# Tokens that carry no analytics signal when scoring confidence.
_STOPWORDS = {
    "a", "an", "the", "what", "which", "who", "is", "are", "was", "were",
    "by", "of", "in", "for", "to", "me", "show", "how", "many", "much",
    "still", "there", "that", "this", "per", "across", "all", "over",
    "time", "and", "or", "with", "from", "on", "at", "has", "have", "had",
    "do", "does", "did", "give", "list", "their", "our", "my", "its", "it",
}

# Generic analytics vocabulary recognized on top of schema-derived words.
_ANALYTICS_VOCAB = {
    "top", "best", "most", "highest", "lowest", "total", "average", "avg",
    "revenue", "month", "monthly", "trend", "open", "spend", "spent",
    "placed", "value", "score", "count", "number",
}


def _schema_vocab(schema: SchemaResponse) -> set[str]:
    """Table names, column names, and their underscore-split parts."""
    vocab: set[str] = set()
    for table in schema.tables:
        vocab.add(table.name.lower())
        vocab.update(table.name.lower().split("_"))
        for col in table.columns:
            vocab.add(col.name.lower())
            vocab.update(col.name.lower().split("_"))
    return vocab


def _confidence(norm_question: str, schema: SchemaResponse, matched: bool) -> float:
    """Deterministic 0.0-1.0 score: how much of the question the plan understood.

    Fraction of content tokens recognized in the schema/analytics vocabulary,
    mapped to [0.5, 1.0] for matched plans (a match already implies the required
    keywords were present). Unmatched plans are 0.0 — we claim no understanding.
    """
    if not matched:
        return 0.0
    vocab = _schema_vocab(schema) | _ANALYTICS_VOCAB
    tokens = [t for t in re.findall(r"[a-z]+", norm_question) if t not in _STOPWORDS]
    if not tokens:
        return 0.5
    hits = sum(1 for t in tokens if t in vocab or t.rstrip("s") in vocab)
    return round(min(1.0, 0.5 + 0.5 * hits / len(tokens)), 2)


def create_plan(question: str, schema: SchemaResponse) -> QueryPlan:
    """Decompose a question into a structured plan, grounded in the schema."""
    norm = question.lower().strip()
    available = {t.name.lower() for t in schema.tables}
    month_expr = _MONTH_EXPR.get(schema.dialect, _MONTH_EXPR["sqlite"])

    for intent, matches in _MATCHERS:
        if matches(norm):
            spec = PLAN_SPECS[intent]
            # Only a valid plan if the schema actually has the required tables.
            if all(t in available for t in spec["required_tables"]):
                dimensions = [d.replace("{MONTH}", month_expr) for d in spec["dimensions"]]
                return QueryPlan(
                    question=question,
                    intent=intent,
                    matched=True,
                    confidence=_confidence(norm, schema, matched=True),
                    target_connection=schema.connection_id,
                    **{**spec, "dimensions": dimensions},
                )

    return QueryPlan(
        question=question,
        intent=UNSUPPORTED_INTENT,
        matched=False,
        confidence=0.0,
        target_connection=schema.connection_id,
    )
