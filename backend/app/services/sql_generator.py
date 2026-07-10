"""SQL generation service.

Turns a natural-language question into a single grounded SELECT statement.

The default backend is a **free, deterministic, offline** generator
(`LocalSqlGenerator`) — no API key, no network, no paid dependency. It renders
SQL clause-by-clause from the structured ``QueryPlan`` produced by
``planner_service`` (tables, joins, measures, dimensions, filters, group_by,
order_by, limit), so every query is grounded in the real schema.

The `SqlGenerator` interface is intentionally provider-agnostic so a real LLM
backend can be added later without touching the route or the safety guard. This
module only *generates* SQL — it never executes it, and callers must still pass
the result through `sql_guard.validate_sql`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.models.responses import QueryPlan, SchemaResponse


# Marker intent + user-facing message for questions the local generator can't
# confidently answer. We never fabricate SQL for these.
UNSUPPORTED_INTENT = "unsupported"
UNSUPPORTED_FAILURE_REASON = "unsupported_question"
UNSUPPORTED_MESSAGE = (
    "This local demo currently supports predefined database analytics questions. "
    "Try one of the examples below."
)

# Canonical supported questions (used as suggestions in unsupported responses).
EXAMPLE_QUESTIONS = [
    "What are the top 5 products by revenue?",
    "Which city has the most customers?",
    "What was the total revenue by month?",
    "Which product category generated the highest revenue?",
    "What is the average order value?",
    "Which customers placed the most orders?",
    "How many support tickets are still open?",
    "Which issue type has the lowest satisfaction score?",
    "What marketing channel had the highest spend?",
    "Show monthly revenue trend.",
]


@dataclass
class GeneratedSql:
    """Result of a generation attempt."""

    sql: str
    intent: Optional[str] = None  # matched template name, or "unsupported"
    matched: bool = True          # False when no known template matched
    prompt_tokens: int = 0        # estimated (Groq only; 0 for local/cache)
    completion_tokens: int = 0    # estimated (Groq only)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token). Used for Groq cost telemetry."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


class SqlGenerator(ABC):
    """Provider-agnostic SQL generation interface."""

    #: Human-readable backend name, surfaced in the API response.
    backend_name: str = "unknown"

    @abstractmethod
    def generate(
        self, question: str, schema: SchemaResponse, plan: Optional[QueryPlan] = None
    ) -> GeneratedSql:
        """Produce SQL for a question, grounded in the given schema.

        ``plan`` is the structured query plan (from ``planner_service``). When
        not provided, the generator builds one itself.
        """


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


# --- Prompt + parsing (shared by LLM providers) -----------------------------

SQL_SYSTEM_PROMPT = """\
You are a careful analytics engineer for a read-only reporting database.

Rules:
- Generate exactly ONE SQL statement, and it MUST be a single SELECT.
- Use ONLY the tables and columns listed in the provided schema. Never invent
  tables or columns.
- NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE, or
  COPY, and never use multiple statements.
- Add a reasonable LIMIT unless the query returns a single aggregate row.
- Return ONLY the raw SQL. No explanation, no markdown, no code fences.
"""


def build_user_prompt(
    question: str, schema: SchemaResponse, plan: Optional[QueryPlan] = None
) -> str:
    plan_block = ""
    if plan is not None:
        plan_block = f"Query plan (guidance):\n{plan.model_dump_json(indent=2)}\n\n"
    return (
        f"Database dialect: {schema.dialect}\n\n"
        f"Schema:\n{format_schema(schema)}\n\n"
        f"{plan_block}"
        f"Question: {question}\n\n"
        "Return only the SQL SELECT statement."
    )


def _extract_sql(text: str) -> str:
    """Strip surrounding markdown code fences and whitespace, if present."""
    import re

    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


# --- Local, deterministic generator -----------------------------------------


def render_sql_from_plan(plan: QueryPlan) -> str:
    """Render one SELECT statement from a matched, structured ``QueryPlan``.

    The SQL is assembled clause-by-clause from the plan's structured fields
    (dimensions/measures -> SELECT, required_tables + joins -> FROM/JOIN,
    filters -> WHERE, group_by, order_by, limit) — no per-question string
    templates. Callers must still pass the result through the safety guard.
    """
    select_list = ", ".join(plan.dimensions + plan.measures)
    sql = f"SELECT {select_list} FROM {plan.required_tables[0]}"
    # One join condition per additional table, in plan order.
    for table, condition in zip(plan.required_tables[1:], plan.joins):
        sql += f" JOIN {table} ON {condition}"
    if plan.filters:
        sql += " WHERE " + " AND ".join(plan.filters)
    if plan.group_by:
        sql += " GROUP BY " + ", ".join(plan.group_by)
    if plan.order_by:
        sql += " ORDER BY " + ", ".join(plan.order_by)
    if plan.limit is not None:
        sql += f" LIMIT {plan.limit}"
    return sql


def _ensure_plan(question: str, schema: SchemaResponse, plan: Optional[QueryPlan]) -> QueryPlan:
    if plan is not None:
        return plan
    from app.services.planner_service import create_plan  # lazy: avoid import cycle

    return create_plan(question, schema)


class LocalSqlGenerator(SqlGenerator):
    """Free, offline, deterministic generator: renders SQL from the query plan."""

    backend_name = "local"

    def generate(
        self, question: str, schema: SchemaResponse, plan: Optional[QueryPlan] = None
    ) -> GeneratedSql:
        plan = _ensure_plan(question, schema, plan)
        if plan.matched and plan.measures and plan.required_tables:
            return GeneratedSql(sql=render_sql_from_plan(plan), intent=plan.intent, matched=True)

        # No confident plan: produce NO executable SQL. The caller returns an
        # honest "unsupported" response.
        return GeneratedSql(sql="", intent=UNSUPPORTED_INTENT, matched=False)


# --- Optional Groq provider (falls back to local on any problem) ------------

# Groq intent marker. Not in the verification templates, so Groq answers show
# as "unverified" — honest, since we can't template-verify a free-form query.
GROQ_INTENT = "groq"


class GroqSqlGenerator(SqlGenerator):
    """Generate SQL via the Groq API, falling back to a local generator.

    Safety: the generated SQL is passed through ``sql_guard.validate_sql`` here.
    If Groq errors, times out, rate-limits, or returns SQL the guard rejects,
    we defer to the local generator (which either matches a template or returns
    an honest "unsupported" result). Groq is never used to execute anything.
    """

    backend_name = "groq"

    def __init__(self, api_key: str, model: str, fallback: SqlGenerator, timeout: float):
        self._api_key = api_key
        self._model = model
        self._fallback = fallback
        self._timeout = timeout

    def generate(
        self, question: str, schema: SchemaResponse, plan: Optional[QueryPlan] = None
    ) -> GeneratedSql:
        plan = _ensure_plan(question, schema, plan)
        user_prompt = build_user_prompt(question, schema, plan)
        try:
            # Groq receives the structured plan + schema context.
            raw = self._complete(user_prompt)
        except Exception:
            # Network error, timeout, rate limit, bad key, SDK missing, etc.
            return self._fallback.generate(question, schema, plan)

        sql = _extract_sql(raw)
        if not sql:
            return self._fallback.generate(question, schema, plan)

        # 1. Groq output MUST pass the same safety guard. Reject -> fall back.
        from app.services.sql_guard import SqlGuardError, validate_sql

        try:
            safe_sql = validate_sql(sql)
        except SqlGuardError:
            return self._fallback.generate(question, schema, plan)

        # 2. It must also be GROUNDED in the real schema (references a real
        #    table, no placeholder/constant SELECT). Reject -> fall back.
        from app.services.schema_grounding import is_grounded

        table_names = {t.name for t in schema.tables}
        if not is_grounded(safe_sql, table_names):
            return self._fallback.generate(question, schema, plan)

        return GeneratedSql(
            sql=safe_sql,
            intent=GROQ_INTENT,
            matched=True,
            prompt_tokens=estimate_tokens(SQL_SYSTEM_PROMPT + "\n" + user_prompt),
            completion_tokens=estimate_tokens(raw),
        )

    def _complete(self, user_prompt: str) -> str:
        """Call Groq chat completions. Imported lazily so 'local' never needs it."""
        from groq import Groq

        client = Groq(api_key=self._api_key)
        resp = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SQL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=512,
            timeout=self._timeout,
        )
        return resp.choices[0].message.content or ""


def get_sql_generator() -> SqlGenerator:
    """Return the configured SQL generator. Defaults to the free local provider.

    Selection is via SQL_GENERATOR_PROVIDER (local | groq). Anything other than
    "groq" — including a missing value or a missing GROQ_API_KEY — resolves to
    the local generator, so the app is always safe by default.
    """
    local = LocalSqlGenerator()
    provider = settings.sql_generator_provider.lower()

    if provider == "groq" and settings.groq_api_key:
        return GroqSqlGenerator(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            fallback=local,
            timeout=settings.groq_timeout_seconds,
        )

    return local
