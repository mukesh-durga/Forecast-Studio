"""Health check route.

Milestone 1: a single, dependency-free endpoint used to confirm the backend
is running before any database or LLM logic exists.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
