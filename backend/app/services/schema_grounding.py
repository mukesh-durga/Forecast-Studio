"""Schema-grounding validation for generated SQL.

This is separate from ``sql_guard`` (which enforces SQL *safety* — SELECT-only,
single statement, no dangerous keywords, LIMIT). Grounding checks that a
generated query actually queries the connected database schema:

  - it references at least one real table from the inspected schema, and
  - it does not reference unknown tables (only known schema tables / local CTEs).

This rejects synthetic placeholder queries that pass the safety guard but do
not answer a database analytics question, e.g.::

    SELECT NULL AS weather_tomorrow WHERE 1=0 LIMIT 1
    SELECT 1
    SELECT 'text'

(constant SELECTs with no FROM).
"""

from __future__ import annotations

import re

# Identifier that appears immediately after FROM or JOIN (the table name).
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)

# CTE names defined via `WITH name AS (` or `, name AS (` — allowed references.
_CTE_RE = re.compile(r"(?:\bWITH|,)\s+([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", re.IGNORECASE)


def referenced_tables(sql: str) -> set[str]:
    """Table names referenced after FROM / JOIN (lowercased)."""
    return {m.group(1).lower() for m in _TABLE_REF_RE.finditer(sql)}


def cte_names(sql: str) -> set[str]:
    """Names defined as CTEs (lowercased) — treated as valid local references."""
    return {m.group(1).lower() for m in _CTE_RE.finditer(sql)}


def is_grounded(sql: str, table_names: set[str]) -> bool:
    """Return True if the SQL queries the real schema.

    Requires at least one real schema table referenced via FROM/JOIN, and no
    references to tables that are neither real schema tables nor local CTEs.
    A query with no table reference at all (placeholder / constant SELECT) is
    rejected.
    """
    known = {t.lower() for t in table_names}
    refs = referenced_tables(sql)
    if not refs:
        return False  # no FROM / no table -> placeholder or constant SELECT

    ctes = cte_names(sql)
    real_tables_used = refs & known
    unknown = refs - known - ctes
    return bool(real_tables_used) and not unknown
