"""Query execution service.

Executes an **already-guarded** SELECT against a connection's read-only
connector, enforcing the configured timeout. It never generates or validates
SQL — the caller must pass SQL that has already been through ``sql_guard`` — so
this layer cannot be used to run unsafe queries.
"""

from __future__ import annotations

from app.config import settings
from app.db.connectors.base import QueryResult
from app.services import schema_service


def execute(connection_id: str, safe_sql: str) -> QueryResult:
    """Run a guarded SELECT on the given connection.

    Raises:
        UnknownConnectionError: if the connection_id is not recognized.
        FileNotFoundError: if the demo database has not been seeded.
        TimeoutError: if the query exceeds the configured timeout.
    """
    connector = schema_service.get_connector(connection_id)
    return connector.run_select(safe_sql, timeout_seconds=settings.query_timeout_seconds)
