"""Pydantic request models for the API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateSqlRequest(BaseModel):
    question: str = Field(..., min_length=1, description="Plain-English question")
    connection_id: str = "demo"
