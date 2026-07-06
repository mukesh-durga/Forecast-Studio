"""Pydantic response models for the API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ColumnSchema(BaseModel):
    name: str
    type: str
    primary_key: bool
    nullable: bool


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnSchema]
    row_count: int
    sample_rows: list[dict[str, Any]]


class SchemaResponse(BaseModel):
    connection_id: str
    dialect: str
    table_count: int
    tables: list[TableSchema]


class GenerateSqlResponse(BaseModel):
    question: str
    connection_id: str
    dialect: str
    generator: str                    # which backend produced the SQL (e.g. "local")
    matched: bool                     # did a known template match the question?
    intent: Optional[str] = None      # name of the matched template, if any
    raw_sql: str                      # exactly what the generator produced
    sql: Optional[str] = None         # safe, LIMIT-enforced SQL (when guard passes)
    guard_passed: bool
    guard_error: Optional[str] = None  # why the guard rejected it, if it did
