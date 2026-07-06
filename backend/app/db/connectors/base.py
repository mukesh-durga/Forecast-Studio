"""Connector interface.

A connector knows how to open a (read-only) connection to a specific database
and how to inspect its schema. Dialect-specific details (e.g. SQLite PRAGMA vs.
Postgres information_schema) live in the concrete subclasses so the rest of the
app can stay dialect-agnostic.

Milestone 2 only needs schema inspection. Query execution is added later and
will reuse the same connection primitives.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ColumnInfo:
    name: str
    type: str
    primary_key: bool = False
    nullable: bool = True


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[dict] = field(default_factory=list)
    row_count: int = 0


@dataclass
class QueryResult:
    columns: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    row_count: int = 0
    runtime_ms: float = 0.0


class BaseConnector(ABC):
    """Base class for all database connectors."""

    #: SQL dialect name, e.g. "sqlite" or "postgresql".
    dialect: str = "unknown"

    @abstractmethod
    def list_tables(self) -> list[str]:
        """Return user table names (excluding internal/system tables)."""

    @abstractmethod
    def get_columns(self, table: str) -> list[ColumnInfo]:
        """Return column metadata for a table."""

    @abstractmethod
    def get_sample_rows(self, table: str, limit: int) -> list[dict]:
        """Return up to ``limit`` sample rows for a table."""

    @abstractmethod
    def count_rows(self, table: str) -> int:
        """Return the total number of rows in a table."""

    def inspect(self, sample_rows: int) -> list[TableInfo]:
        """Assemble a compact schema snapshot for every table."""
        tables: list[TableInfo] = []
        for name in self.list_tables():
            tables.append(
                TableInfo(
                    name=name,
                    columns=self.get_columns(name),
                    sample_rows=self.get_sample_rows(name, sample_rows),
                    row_count=self.count_rows(name),
                )
            )
        return tables
