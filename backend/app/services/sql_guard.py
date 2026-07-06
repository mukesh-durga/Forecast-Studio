"""SQL safety guard.

Every query MUST pass through ``validate_sql`` before it is executed. The guard
is intentionally conservative: it is a defense-in-depth layer, so when in doubt
it rejects. It is designed to be simple and easy to explain:

  1. Reject empty queries.
  2. Reject comments (``--``, ``/* */``) — they can hide unsafe SQL.
  3. Reject multiple statements (any ``;`` other than a single trailing one).
  4. Require the statement to start with SELECT or WITH (a CTE that feeds a
     SELECT). Everything else is read/write-ambiguous and blocked.
  5. Reject any dangerous keyword (INSERT, UPDATE, DELETE, DROP, ALTER,
     TRUNCATE, CREATE, MERGE, COPY, and a few more) via word-boundary matching.
  6. Enforce a LIMIT: inject a default when missing, clamp when it exceeds the
     configured maximum, preserve it otherwise.

On success it returns the sanitized SQL (with LIMIT enforced). On any violation
it raises ``SqlGuardError`` with a human-readable reason.
"""

from __future__ import annotations

import re

from app.config import settings

# Statements the guard is willing to run. Read-only by construction.
ALLOWED_STARTS = ("SELECT", "WITH")

# Keywords that indicate a write, DDL, or otherwise unsafe operation.
BLOCKED_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "MERGE", "COPY", "REPLACE", "GRANT", "REVOKE", "ATTACH", "DETACH",
    "PRAGMA", "VACUUM", "REINDEX", "EXEC", "EXECUTE", "CALL", "INTO",
)

# Precompiled word-boundary matcher for the blocklist.
_BLOCKED_RE = re.compile(
    r"\b(" + "|".join(BLOCKED_KEYWORDS) + r")\b", re.IGNORECASE
)

# Matches a trailing/inner comment marker.
_COMMENT_RE = re.compile(r"(--|/\*|\*/|#)")

# Matches `LIMIT <number>` (optionally the count in `LIMIT n OFFSET m`).
_LIMIT_NUM_RE = re.compile(r"\blimit\b\s+(\d+)", re.IGNORECASE)
# Detects a LIMIT keyword in any form (to catch unsupported `LIMIT ALL`).
_LIMIT_KW_RE = re.compile(r"\blimit\b", re.IGNORECASE)


class SqlGuardError(ValueError):
    """Raised when SQL fails a safety check."""


def validate_sql(
    sql: str,
    *,
    default_limit: int | None = None,
    max_limit: int | None = None,
) -> str:
    """Validate and sanitize a SQL string.

    Returns the safe, LIMIT-enforced SQL. Raises ``SqlGuardError`` if the query
    violates any safety rule.
    """
    default_limit = default_limit if default_limit is not None else settings.default_row_limit
    max_limit = max_limit if max_limit is not None else settings.max_row_limit

    if not sql or not sql.strip():
        raise SqlGuardError("Empty query.")

    stripped = sql.strip()

    # 2. No comments allowed.
    if _COMMENT_RE.search(stripped):
        raise SqlGuardError("Comments are not allowed in queries.")

    # 3. Single statement only. Allow at most one trailing semicolon.
    core = stripped[:-1].rstrip() if stripped.endswith(";") else stripped
    if ";" in core:
        raise SqlGuardError("Multiple SQL statements are not allowed.")

    if not core:
        raise SqlGuardError("Empty query.")

    # 4. Must be a read-only SELECT / WITH ... SELECT.
    first_word = re.match(r"\s*([A-Za-z]+)", core)
    if not first_word or first_word.group(1).upper() not in ALLOWED_STARTS:
        raise SqlGuardError("Only SELECT statements are allowed.")

    # 5. No dangerous keywords anywhere in the statement.
    blocked = _BLOCKED_RE.search(core)
    if blocked:
        raise SqlGuardError(
            f"Disallowed keyword found: {blocked.group(1).upper()}."
        )

    # 6. Enforce a LIMIT.
    return _enforce_limit(core, default_limit=default_limit, max_limit=max_limit)


def _enforce_limit(sql: str, *, default_limit: int, max_limit: int) -> str:
    """Inject, preserve, or clamp the LIMIT clause."""
    num_match = _LIMIT_NUM_RE.search(sql)

    if num_match:
        current = int(num_match.group(1))
        if current > max_limit:
            # Clamp the existing limit down to the maximum.
            return sql[: num_match.start(1)] + str(max_limit) + sql[num_match.end(1):]
        return sql  # Existing, in-range LIMIT is preserved as-is.

    # A LIMIT keyword without a plain integer (e.g. `LIMIT ALL`) is unsupported.
    if _LIMIT_KW_RE.search(sql):
        raise SqlGuardError("Unsupported LIMIT clause; use `LIMIT <number>`.")

    # No LIMIT at all — inject the default.
    return f"{sql} LIMIT {default_limit}"
