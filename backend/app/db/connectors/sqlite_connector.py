"""SQLite connector.

Opens the database read-only (URI mode=ro) for inspection so that no code path
in the request lifecycle can accidentally write to the demo database. The seed
script uses its own writable connection separately.
"""

from __future__ import annotations

import os
import sqlite3
import time

from app.db.connectors.base import BaseConnector, ColumnInfo, QueryResult

# SQLite's own bookkeeping tables — never expose these as user schema.
_INTERNAL_TABLE_PREFIXES = ("sqlite_",)


class SQLiteConnector(BaseConnector):
    dialect = "sqlite"

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(
                f"Demo database not found at {self.db_path}. "
                "Seed it first: python -m app.db.sample_seed"
            )
        # Read-only URI connection. Any write attempt raises OperationalError.
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def list_tables(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' ORDER BY name"
            ).fetchall()
        return [
            r["name"]
            for r in rows
            if not r["name"].startswith(_INTERNAL_TABLE_PREFIXES)
        ]

    def get_columns(self, table: str) -> list[ColumnInfo]:
        with self._connect() as conn:
            # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
            rows = conn.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()
        return [
            ColumnInfo(
                name=r["name"],
                type=(r["type"] or "").upper() or "UNKNOWN",
                primary_key=bool(r["pk"]),
                nullable=not bool(r["notnull"]),
            )
            for r in rows
        ]

    def get_sample_rows(self, table: str, limit: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT * FROM "{table}" LIMIT ?', (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_rows(self, table: str) -> int:
        with self._connect() as conn:
            row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()
        return int(row["c"])

    def run_select(self, sql: str, timeout_seconds: float) -> QueryResult:
        """Execute an already-guarded SELECT read-only, with a wall-clock timeout.

        The SQL passed here MUST have already been through ``sql_guard``. A
        SQLite progress handler aborts the query if it runs past the deadline.
        """
        conn = self._connect()
        deadline = time.perf_counter() + timeout_seconds

        def _abort_if_timed_out() -> int:
            # Returning non-zero from the progress handler aborts the query.
            return 1 if time.perf_counter() > deadline else 0

        # Handler fires roughly every N virtual-machine instructions.
        conn.set_progress_handler(_abort_if_timed_out, 1000)
        started = time.perf_counter()
        try:
            cursor = conn.execute(sql)
            rows = [dict(r) for r in cursor.fetchall()]
            columns = [d[0] for d in cursor.description] if cursor.description else []
        except sqlite3.OperationalError as exc:
            # A progress-handler abort surfaces here as "interrupted".
            if "interrupt" in str(exc).lower():
                raise TimeoutError(
                    f"Query exceeded the {timeout_seconds}s timeout."
                ) from exc
            raise
        finally:
            conn.set_progress_handler(None, 0)
            conn.close()

        runtime_ms = round((time.perf_counter() - started) * 1000, 2)
        return QueryResult(
            columns=columns, rows=rows, row_count=len(rows), runtime_ms=runtime_ms
        )
