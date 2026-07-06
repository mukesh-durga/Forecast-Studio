"""SQL generation service.

Turns a natural-language question into a single grounded SELECT statement.

The default backend is a **free, deterministic, offline** rule-based generator
(`LocalSqlGenerator`) — no API key, no network, no paid dependency. It maps a
set of common analytics questions to SQL templates that only reference the real
tables and columns of the demo schema.

The `SqlGenerator` interface is intentionally provider-agnostic so a real LLM
backend can be added later without touching the route or the safety guard. This
module only *generates* SQL — it never executes it, and callers must still pass
the result through `sql_guard.validate_sql`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

from app.config import settings
from app.models.responses import SchemaResponse


@dataclass
class GeneratedSql:
    """Result of a generation attempt."""

    sql: str
    intent: Optional[str] = None  # which template matched (None for fallbacks)
    matched: bool = True          # False when no known template matched


class SqlGenerator(ABC):
    """Provider-agnostic SQL generation interface."""

    #: Human-readable backend name, surfaced in the API response.
    backend_name: str = "unknown"

    @abstractmethod
    def generate(self, question: str, schema: SchemaResponse) -> GeneratedSql:
        """Produce SQL for a question, grounded in the given schema."""


def format_schema(schema: SchemaResponse) -> str:
    """Render the schema as a compact text block (useful for LLM backends)."""
    lines: list[str] = []
    for table in schema.tables:
        cols = ", ".join(
            f"{c.name} {c.type}" + (" PK" if c.primary_key else "")
            for c in table.columns
        )
        lines.append(f"{table.name}({cols})")
    return "\n".join(lines)


# --- Local, deterministic generator -----------------------------------------

# Revenue is derived from order_items: quantity * unit_price.
_TOP_PRODUCTS = (
    "SELECT p.name AS product_name, "
    "SUM(oi.quantity * oi.unit_price) AS revenue "
    "FROM order_items oi JOIN products p ON p.id = oi.product_id "
    "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"
)
_CITY_MOST_CUSTOMERS = (
    "SELECT city, COUNT(*) AS customer_count "
    "FROM customers GROUP BY city ORDER BY customer_count DESC LIMIT 1"
)
_REVENUE_BY_MONTH = (
    "SELECT strftime('%Y-%m', o.order_date) AS month, "
    "SUM(oi.quantity * oi.unit_price) AS revenue "
    "FROM orders o JOIN order_items oi ON oi.order_id = o.id "
    "GROUP BY month ORDER BY month"
)
_CATEGORY_REVENUE = (
    "SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue "
    "FROM order_items oi JOIN products p ON p.id = oi.product_id "
    "GROUP BY p.category ORDER BY revenue DESC LIMIT 1"
)
_AVERAGE_ORDER_VALUE = (
    "SELECT SUM(oi.quantity * oi.unit_price) / COUNT(DISTINCT o.id) "
    "AS average_order_value "
    "FROM orders o JOIN order_items oi ON oi.order_id = o.id"
)
_TOP_CUSTOMERS_BY_ORDERS = (
    "SELECT c.name AS customer_name, COUNT(o.id) AS order_count "
    "FROM customers c JOIN orders o ON o.customer_id = c.id "
    "GROUP BY c.id, c.name ORDER BY order_count DESC LIMIT 5"
)
_OPEN_TICKETS = (
    "SELECT COUNT(*) AS open_tickets "
    "FROM support_tickets WHERE status = 'open'"
)
_LOWEST_SATISFACTION_ISSUE = (
    "SELECT issue_type, AVG(satisfaction_score) AS avg_satisfaction "
    "FROM support_tickets WHERE satisfaction_score IS NOT NULL "
    "GROUP BY issue_type ORDER BY avg_satisfaction ASC LIMIT 1"
)
_TOP_CHANNEL_BY_SPEND = (
    "SELECT channel, SUM(spend) AS total_spend "
    "FROM marketing_campaigns GROUP BY channel ORDER BY total_spend DESC LIMIT 1"
)


@dataclass
class _Rule:
    intent: str
    matches: Callable[[str], bool]
    sql: str


# Ordered most-specific first; the first matching rule wins.
_RULES: list[_Rule] = [
    _Rule(
        "category_revenue",
        lambda n: "category" in n and "revenue" in n,
        _CATEGORY_REVENUE,
    ),
    _Rule(
        "monthly_revenue",
        lambda n: "month" in n and ("revenue" in n or "trend" in n),
        _REVENUE_BY_MONTH,
    ),
    _Rule(
        "top_products_by_revenue",
        lambda n: "product" in n and "revenue" in n and ("top" in n or "best" in n),
        _TOP_PRODUCTS,
    ),
    _Rule(
        "average_order_value",
        lambda n: ("average" in n or "avg" in n) and "order" in n,
        _AVERAGE_ORDER_VALUE,
    ),
    _Rule(
        "top_customers_by_orders",
        lambda n: "customer" in n and "order" in n and ("most" in n or "placed" in n),
        _TOP_CUSTOMERS_BY_ORDERS,
    ),
    _Rule(
        "city_most_customers",
        lambda n: "city" in n and "customer" in n,
        _CITY_MOST_CUSTOMERS,
    ),
    _Rule(
        "open_tickets",
        lambda n: "ticket" in n and "open" in n,
        _OPEN_TICKETS,
    ),
    _Rule(
        "lowest_satisfaction_issue",
        lambda n: "issue" in n and ("satisfaction" in n or "score" in n),
        _LOWEST_SATISFACTION_ISSUE,
    ),
    _Rule(
        "top_channel_by_spend",
        lambda n: ("channel" in n or "marketing" in n) and ("spend" in n or "spent" in n),
        _TOP_CHANNEL_BY_SPEND,
    ),
]


class LocalSqlGenerator(SqlGenerator):
    """Free, offline, deterministic generator based on keyword rules."""

    backend_name = "local"

    def generate(self, question: str, schema: SchemaResponse) -> GeneratedSql:
        norm = question.lower().strip()

        table_names = {t.name for t in schema.tables}
        for rule in _RULES:
            if rule.matches(norm):
                # Only use a template if the schema actually has its tables.
                if _tables_in(rule.sql, table_names):
                    return GeneratedSql(sql=rule.sql, intent=rule.intent, matched=True)

        # No known template — return a safe, grounded fallback preview.
        return GeneratedSql(sql=self._fallback(schema), intent=None, matched=False)

    @staticmethod
    def _fallback(schema: SchemaResponse) -> str:
        first_table = schema.tables[0].name if schema.tables else "sqlite_master"
        return f"SELECT * FROM {first_table}"


# Demo tables referenced by the templates. Used to verify a template is valid
# against the connected schema before returning it.
_TEMPLATE_TABLES = (
    "customers",
    "products",
    "orders",
    "order_items",
    "support_tickets",
    "marketing_campaigns",
)


def _tables_in(sql: str, available: set[str]) -> bool:
    """Return True if every demo table the template *could* reference exists."""
    lowered = sql.lower()
    referenced = [t for t in _TEMPLATE_TABLES if t in lowered]
    return all(t in available for t in referenced)


def get_sql_generator() -> SqlGenerator:
    """Return the configured SQL generator. Defaults to the free local backend."""
    backend = settings.sql_generator_backend.lower()
    if backend == "local":
        return LocalSqlGenerator()
    # Future: an LLM-backed generator would be constructed here.
    raise ValueError(
        f"Unsupported sql_generator_backend: {settings.sql_generator_backend!r}. "
        "Supported backends: local."
    )
