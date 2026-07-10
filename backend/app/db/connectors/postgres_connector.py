"""PostgreSQL connector.

Mirrors the SQLite connector's interface using ``information_schema`` for schema
inspection. Queries run under a read-only transaction with a server-side
statement timeout. The ``psycopg`` driver is imported lazily so the rest of the
app (and the SQLite demo) never require it.
"""

from __future__ import annotations

import time

from app.db.connectors.base import BaseConnector, ColumnInfo, QueryResult


class PostgresConnector(BaseConnector):
    dialect = "postgresql"

    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg  # lazy: only needed when Postgres is actually used

        return psycopg.connect(self.dsn)

    def list_tables(self) -> list[str]:
        sql = (
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [r[0] for r in cur.fetchall()]

    def get_columns(self, table: str) -> list[ColumnInfo]:
        pk_sql = (
            "SELECT kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_schema = 'public' AND tc.table_name = %s"
        )
        col_sql = (
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(pk_sql, (table,))
                pks = {r[0] for r in cur.fetchall()}
                cur.execute(col_sql, (table,))
                rows = cur.fetchall()
        return [
            ColumnInfo(
                name=name,
                type=(data_type or "").upper() or "UNKNOWN",
                primary_key=name in pks,
                nullable=(is_nullable == "YES"),
            )
            for (name, data_type, is_nullable) in rows
        ]

    def get_sample_rows(self, table: str, limit: int) -> list[dict]:
        # `table` comes from list_tables (trusted); quote it defensively.
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM public."{table}" LIMIT %s', (limit,))
                columns = [d.name for d in cur.description] if cur.description else []
                return [dict(zip(columns, r)) for r in cur.fetchall()]

    def count_rows(self, table: str) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM public."{table}"')
                return int(cur.fetchone()[0])

    def run_select(self, sql: str, timeout_seconds: float) -> QueryResult:
        """Execute an already-guarded SELECT read-only, with a server-side timeout."""
        started = time.perf_counter()
        with self._connect() as conn:
            # Read-only transaction: even if a write slipped past the guard, PG rejects it.
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {int(timeout_seconds * 1000)}")
                cur.execute(sql)
                columns = [d.name for d in cur.description] if cur.description else []
                rows = [dict(zip(columns, r)) for r in cur.fetchall()]
        runtime_ms = round((time.perf_counter() - started) * 1000, 2)
        return QueryResult(columns=columns, rows=rows, row_count=len(rows), runtime_ms=runtime_ms)
