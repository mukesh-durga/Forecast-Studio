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

# Matches `LIMIT <number>` — used to preserve or clamp the row limit.
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)


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
    """Enforce a row LIMIT while preserving the SQL string verbatim.

    This never rebuilds GROUP BY, ORDER BY, or any other clause. It only:
      - removes a single trailing semicolon,
      - appends `` LIMIT <default_limit>`` when no LIMIT is present,
      - returns the SQL unchanged when the existing LIMIT is in range,
      - rewrites *only* the numeric value when the existing LIMIT is too large.
    """
    cleaned = re.sub(r";\s*$", "", sql.strip())

    match = _LIMIT_RE.search(cleaned)
    if not match:
        # No LIMIT present -> append the default with one separating space.
        return f"{cleaned} LIMIT {default_limit}"

    limit_value = int(match.group(1))
    if limit_value <= max_limit:
        # In range -> return the SQL unchanged.
        return cleaned

    # Too large -> replace ONLY the numeric span; everything else is untouched.
    return cleaned[: match.start(1)] + str(max_limit) + cleaned[match.end(1):]
