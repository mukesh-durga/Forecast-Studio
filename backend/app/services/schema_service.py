"""Schema inspection service.

Turns a connector's raw schema snapshot into the compact, API-friendly
``SchemaResponse`` used by the frontend and (later) the SQL-generation prompt.

Milestone 2 supports a single built-in connection: the seeded SQLite demo DB.
A real connection registry (metadata DB) arrives in a later milestone.
"""

from __future__ import annotations

from app.config import settings
from app.db.connectors.base import BaseConnector
from app.db.connectors.sqlite_connector import SQLiteConnector
from app.models.responses import ColumnSchema, SchemaResponse, TableSchema

DEMO_CONNECTION_ID = "demo"


class UnknownConnectionError(ValueError):
    """Raised when a connection_id is not recognized."""


def get_connector(connection_id: str) -> BaseConnector:
    """Resolve a connection_id to a connector instance."""
    if connection_id == DEMO_CONNECTION_ID:
        return SQLiteConnector(settings.demo_db_path)
    raise UnknownConnectionError(f"Unknown connection_id: {connection_id!r}")


def get_schema(connection_id: str) -> SchemaResponse:
    """Return a compact schema snapshot for the given connection."""
    connector = get_connector(connection_id)
    tables = connector.inspect(sample_rows=settings.schema_sample_rows)

    table_schemas = [
        TableSchema(
            name=t.name,
            row_count=t.row_count,
            columns=[
                ColumnSchema(
                    name=c.name,
                    type=c.type,
                    primary_key=c.primary_key,
                    nullable=c.nullable,
                )
                for c in t.columns
            ],
            sample_rows=t.sample_rows,
        )
        for t in tables
    ]

    return SchemaResponse(
        connection_id=connection_id,
        dialect=connector.dialect,
        table_count=len(table_schemas),
        tables=table_schemas,
    )
