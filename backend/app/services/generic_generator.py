"""Generic, schema-aware text-to-SQL fallback.

The fast path is still the planner + ``LocalSqlGenerator`` for the predefined
analytics intents. When a question does **not** match a known intent, the route
consults this module: it classifies the question and, if it looks answerable
from the connected schema, builds a single grounded ``SELECT`` for common
analytics shapes (count, sum/avg/min/max, group-by, order-by + limit, simple
filters, month bucketing, and joins detected from ``<x>_id`` keys).

It is a deterministic heuristic — no LLM, no network. It never emits anything but
a single SELECT; the route still runs the result through the SQL guard, schema
grounding, a sample execution, and verification before returning it. Non-database
questions (weather, general knowledge) are classified as unsupported, and
questions containing write/DDL keywords are classified unsafe — neither reaches
SQL generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.models.responses import SchemaResponse

# Question categories the classifier returns.
DB_ANALYTICS = "database_analytics_question"
UNSUPPORTED_GENERAL = "unsupported_general_question"
UNSAFE = "unsafe_question"

GENERIC_INTENT = "generic"

_WORD = re.compile(r"[a-z0-9]+")

# Write/DDL words that make a question unsafe to attempt at all.
_UNSAFE_RE = re.compile(
    r"\b(drop|delete|insert|update|truncate|alter|create|grant|revoke|merge|"
    r"replace|attach|detach|pragma|vacuum)\b",
    re.IGNORECASE,
)

_RANK_DESC = ("top", "highest", "most", "largest", "biggest", "greatest", "maximum", "best", "leading")
_RANK_ASC = ("lowest", "least", "smallest", "minimum", "fewest", "bottom")

# Domain synonyms that imply a schema concept even without naming a table/column.
_DOMAIN_TERMS = ("revenue", "sales", "spend", "spent", "average", "count", "total",
                 "paid", "purchased", "bought", "money", "earned")

# "Money changed hands via orders" — customer/product spend & revenue.
_ORDER_MONEY_WORDS = ("revenue", "sales", "spent", "spend", "paid", "purchase",
                      "purchased", "bought", "money", "earned", "sold")
# Words that (with "spend/spent") mean *marketing* spend, not customer spend.
_MARKETING_WORDS = ("marketing", "campaign", "channel", "advertis", "ad spend")
# Wording that means the measure should be labelled "revenue" rather than "total_spent".
_REVENUE_WORDS = ("revenue", "sales", "money", "earned", "sold", "made")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


@dataclass
class GenericSql:
    sql: str
    expected_columns: list[str] = field(default_factory=list)


class _Schema:
    """Convenience view over a ``SchemaResponse``."""

    def __init__(self, schema: SchemaResponse):
        self.schema = schema
        self.dialect = schema.dialect
        self.tables = {t.name: t for t in schema.tables}

    def has(self, table: str, cols: list[str]) -> bool:
        t = self.tables.get(table)
        if not t:
            return False
        names = {c.name for c in t.columns}
        return all(c in names for c in cols)

    def columns(self, table: str) -> list:
        t = self.tables.get(table)
        return list(t.columns) if t else []

    def column_names(self, table: str) -> set[str]:
        return {c.name for c in self.columns(table)}

    def pk(self, table: str) -> str:
        for c in self.columns(table):
            if c.primary_key:
                return c.name
        return "id"

    def is_numeric(self, table: str, col: str) -> bool:
        for c in self.columns(table):
            if c.name == col:
                return any(k in c.type.upper() for k in ("INT", "REAL", "NUM", "DEC", "FLOA", "DOUB"))
        return False

    def find_table(self, qtokens: set[str]) -> Optional[str]:
        """Best table whose (singularized) name tokens are all referenced."""
        best, best_len = None, 0
        for name in self.tables:
            parts = [_singular(p) for p in name.split("_")]
            if all(p in qtokens for p in parts) and len(parts) > best_len:
                best, best_len = name, len(parts)
        return best

    def resolve_join(self, from_table: str, id_col: str) -> Optional[tuple[str, str]]:
        """`<x>_id` -> (target_table, target_pk) via naming convention + PK check."""
        if not id_col.endswith("_id"):
            return None
        stem = id_col[:-3]
        for cand in (stem, stem + "s", _singular(stem)):
            if cand in self.tables and "id" in self.column_names(cand):
                return cand, self.pk(cand)
        return None

    def month_expr(self, table: str, col: str) -> str:
        ref = f"{table}.{col}"
        if self.dialect == "postgresql":
            return f"to_char({ref}, 'YYYY-MM')"
        return f"strftime('%Y-%m', {ref})"

    def date_column(self, table: str) -> Optional[str]:
        for c in self.columns(table):
            if any(k in c.type.upper() for k in ("DATE", "TIME")) or c.name.endswith(("_date", "_at")):
                return c.name
        return None


# --- classifier -------------------------------------------------------------

def classify(question: str, schema: SchemaResponse) -> str:
    """Classify a question as database-analytics, general-unsupported, or unsafe."""
    if _UNSAFE_RE.search(question):
        return UNSAFE

    helper = _Schema(schema)
    qtokens = {_singular(t) for t in _tokens(question)}

    # Any reference to a table/column (or a domain synonym) => database question.
    vocab: set[str] = set()
    for name, table in helper.tables.items():
        for part in name.split("_"):
            vocab.add(_singular(part))
        for c in table.columns:
            for part in c.name.split("_"):
                vocab.add(_singular(part))
    vocab.update(_DOMAIN_TERMS)

    if qtokens & vocab:
        return DB_ANALYTICS
    return UNSUPPORTED_GENERAL


# --- generation -------------------------------------------------------------

def generate(question: str, schema: SchemaResponse) -> Optional[GenericSql]:
    """Public entry: build a single grounded SELECT, or None. See _generate_impl."""
    return _generate_impl(question, schema)


def repair(question: str, schema: SchemaResponse) -> Optional[GenericSql]:
    """Re-derive SQL constrained to the question's implied table group.

    Used by the route when the first generic candidate fails semantic
    verification (e.g. a customer-spend question that reached for
    ``marketing_campaigns``). Routing here is semantic, so the repaired query
    targets the correct tables. Implemented against ``_generate_impl`` so it is
    unaffected if the public ``generate`` is overridden.
    """
    return _generate_impl(question, schema)


def _wants_marketing_spend(q: str) -> bool:
    return ("spend" in q or "spent" in q) and any(w in q for w in _MARKETING_WORDS)


def _generate_impl(question: str, schema: SchemaResponse) -> Optional[GenericSql]:
    s = _Schema(schema)
    q = question.lower()
    qtokens = {_singular(t) for t in _tokens(q)}

    desc = any(w in q for w in _RANK_DESC)
    asc = any(w in q for w in _RANK_ASC)
    limit = _detect_limit(q)

    # 1) Marketing spend — ONLY when the question is explicitly about marketing
    #    (channel/campaign/ad). "customers spent" must NOT land here.
    if _wants_marketing_spend(q) and s.has("marketing_campaigns", ["spend"]):
        return _spend_query(q, qtokens, s, desc, asc, limit)

    # 2) Order-based money — customer/product/category/status/month revenue or
    #    spend, derived from order_items(quantity * unit_price).
    if any(w in q for w in _ORDER_MONEY_WORDS) and s.has("order_items", ["quantity", "unit_price"]):
        return _order_money_query(q, qtokens, s, desc, asc, limit)

    # 3) Count.
    if re.search(r"\bhow many\b|\bnumber of\b|\bcount\b", q):
        return _count_query(q, qtokens, s, desc, asc, limit)

    # 4) Single aggregate over a named numeric column (average/min/max/sum).
    agg = _detect_aggregate(q, qtokens, s)
    if agg:
        return agg

    # 5) List/select columns from a detected table.
    return _select_query(q, qtokens, s, desc, asc, limit)


# --- semantic verification (question <-> SQL entity alignment) --------------

def semantic_mismatch(question: str, sql: str) -> Optional[str]:
    """Return a reason string if the SQL's tables don't fit the question, else None.

    This is what stops generic mode from marking a query "verified" just because
    it executed and returned rows.
    """
    q = (question or "").lower()
    s = (sql or "").lower()

    if ("customer" in q and any(w in q for w in ("spent", "spend", "paid", "purchase", "bought"))
            and "marketing_campaigns" in s):
        return "customer-spend question used marketing_campaigns.spend (ad spend, not customer spend)"
    if "customer" in q and "customers" not in s and "customer_id" not in s:
        return "question mentions customers but the SQL has no customer table/column"
    if "marketing_campaigns" in s and not any(w in q for w in _MARKETING_WORDS):
        return "used marketing_campaigns without a marketing/campaign/channel reference"
    if (("product" in q or "category" in q)
            and any(w in q for w in _REVENUE_WORDS)
            and "products" not in s and "order_items" not in s):
        return "product/category revenue question without products/order_items"
    return None


def _detect_limit(q: str) -> Optional[int]:
    m = re.search(r"\b(?:top|first|bottom|limit)\s+(\d+)\b", q)
    return int(m.group(1)) if m else None


def _order_clause(measure_alias: str, desc: bool, asc: bool) -> str:
    direction = "DESC" if desc or not asc else "ASC"
    return f" ORDER BY {measure_alias} {direction}"


def _order_money_query(q, qtokens, s: _Schema, desc, asc, limit) -> GenericSql:
    """Money that flowed through orders: revenue / customer spend, by dimension."""
    # Label the measure "revenue" for revenue/sales/money wording, else "total_spent".
    alias = "revenue" if any(w in q for w in _REVENUE_WORDS) else "total_spent"
    measure = f"SUM(order_items.quantity * order_items.unit_price) AS {alias}"
    joins, dim_select, group, expected = [], None, None, [alias]

    if "customer" in qtokens and s.has("orders", ["customer_id"]) and s.has("customers", ["name"]):
        joins = [
            'JOIN orders ON order_items.order_id = orders.id',
            'JOIN customers ON orders.customer_id = customers.id',
        ]
        dim_select, group, expected = "customers.name AS customer_name", "customers.name", ["customer_name", alias]
    elif "category" in qtokens and s.has("products", ["category"]):
        joins = ['JOIN products ON order_items.product_id = products.id']
        dim_select, group, expected = "products.category", "products.category", ["category", alias]
    elif "product" in qtokens and s.has("products", ["name"]):
        joins = ['JOIN products ON order_items.product_id = products.id']
        dim_select, group, expected = "products.name AS product_name", "products.name", ["product_name", alias]
    elif "status" in q and s.has("orders", ["status"]):
        joins = ['JOIN orders ON order_items.order_id = orders.id']
        dim_select, group, expected = "orders.status", "orders.status", ["status", alias]
    elif ("month" in q or "monthly" in q) and s.has("orders", ["order_date"]):
        joins = ['JOIN orders ON order_items.order_id = orders.id']
        me = s.month_expr("orders", "order_date")
        dim_select, group, expected = f"{me} AS month", "month", ["month", alias]

    select = f"{dim_select}, {measure}" if dim_select else measure
    sql = f"SELECT {select} FROM order_items"
    for j in joins:
        sql += f" {j}"
    if group:
        sql += f" GROUP BY {group}"
        if desc or asc:
            sql += _order_clause(alias, desc, asc)
            # "who spent the most" implies a short leaderboard when none is given.
            if limit is None:
                limit = 5
    if limit:
        sql += f" LIMIT {limit}"
    return GenericSql(sql, expected)


def _spend_query(q, qtokens, s: _Schema, desc, asc, limit) -> GenericSql:
    measure = "SUM(marketing_campaigns.spend) AS total_spend"
    if "channel" in qtokens and s.has("marketing_campaigns", ["channel"]):
        sql = ("SELECT marketing_campaigns.channel, " + measure +
               " FROM marketing_campaigns GROUP BY marketing_campaigns.channel")
        if desc or asc or limit:
            sql += _order_clause("total_spend", desc, asc)
        if limit:
            sql += f" LIMIT {limit}"
        return GenericSql(sql, ["channel", "total_spend"])
    return GenericSql(f"SELECT {measure} FROM marketing_campaigns", ["total_spend"])


def _count_query(q, qtokens, s: _Schema, desc, asc, limit) -> Optional[GenericSql]:
    table = s.find_table(qtokens)
    if table is None:
        return None

    # Month bucketing first ("orders each month").
    if ("month" in q or "monthly" in q) and s.date_column(table):
        me = s.month_expr(table, s.date_column(table))
        sql = f"SELECT {me} AS month, COUNT(*) AS count FROM {table} GROUP BY month"
        if desc or asc or limit:
            sql += _order_clause("count", desc, asc)
        if limit:
            sql += f" LIMIT {limit}"
        return GenericSql(sql, ["month", "count"])

    # Group by a named categorical column ("tickets by status", "per city").
    grouped = bool(re.search(r"\bfor each\b|\bper\b|\bgrouped by\b|\beach\b|\bby\b", q))
    if grouped:
        for c in s.columns(table):
            named = c.name in qtokens or _singular(c.name) in qtokens
            if named and not s.is_numeric(table, c.name):
                sql = (f"SELECT {table}.{c.name}, COUNT(*) AS count FROM {table} "
                       f"GROUP BY {table}.{c.name}")
                if desc or asc or limit:
                    sql += _order_clause("count", desc, asc)
                if limit:
                    sql += f" LIMIT {limit}"
                return GenericSql(sql, [c.name, "count"])

    return GenericSql(f"SELECT COUNT(*) AS count FROM {table}", ["count"])


def _detect_aggregate(q, qtokens, s: _Schema) -> Optional[GenericSql]:
    funcs = []
    for word, fn in (("average", "AVG"), ("avg", "AVG"), ("mean", "AVG"),
                     ("minimum", "MIN"), ("maximum", "MAX"),
                     ("total", "SUM"), ("sum", "SUM")):
        if word in q:
            funcs.append((q.find(word), fn))
    if not funcs:
        return None
    # Find a numeric column named in the question and its table.
    for table in s.tables:
        for c in s.columns(table):
            if s.is_numeric(table, c.name) and not c.primary_key:
                if c.name in qtokens or _singular(c.name) in qtokens:
                    funcs.sort(key=lambda x: x[0])
                    seen, sel, exp = set(), [], []
                    for _, fn in funcs:
                        if fn in seen:
                            continue
                        seen.add(fn)
                        alias = f"{fn.lower()}_{c.name}"
                        sel.append(f"{fn}({table}.{c.name}) AS {alias}")
                        exp.append(alias)
                    return GenericSql(f"SELECT {', '.join(sel)} FROM {table}", exp)
    return None


def _select_query(q, qtokens, s: _Schema, desc, asc, limit) -> Optional[GenericSql]:
    table = s.find_table(qtokens)
    if table is None:
        return None
    cols = [c.name for c in s.columns(table)
            if (c.name in qtokens or _singular(c.name) in qtokens) and not c.primary_key]
    select = ", ".join(f"{table}.{c}" for c in cols) if cols else "*"
    sql = f"SELECT {select} FROM {table}"
    order_col = None
    if desc or asc or re.search(r"\border(ed)?\b|\bsort", q):
        for c in s.columns(table):
            if (c.name in qtokens or _singular(c.name) in qtokens) and s.is_numeric(table, c.name):
                order_col = c.name
                break
    if order_col:
        sql += f" ORDER BY {table}.{order_col} {'DESC' if desc or not asc else 'ASC'}"
    if limit:
        sql += f" LIMIT {limit}"
    return GenericSql(sql, cols or ["*"])
