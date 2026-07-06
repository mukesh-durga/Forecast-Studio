"""Pydantic response models for the API."""

from __future__ import annotations

from typing import Any

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
