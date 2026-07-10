"""Connection + schema inspection routes."""

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.responses import SchemaResponse
from app.services import schema_service

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("")
def list_connections() -> dict:
    """List available connections (the SQLite demo, and Postgres if configured)."""
    return {
        "connections": [
            {
                "id": "demo_sqlite",
                "label": "Demo (SQLite e-commerce)",
                "dialect": "sqlite",
                "available": True,
            },
            {
                "id": "demo_postgres",
                "label": "Demo (Postgres e-commerce)",
                "dialect": "postgresql",
                "available": bool(settings.postgres_url),
            },
        ]
    }


@router.get("/{connection_id}/schema", response_model=SchemaResponse)
def get_connection_schema(connection_id: str) -> SchemaResponse:
    try:
        return schema_service.get_schema(connection_id)
    except schema_service.UnknownConnectionError:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {connection_id}")
    except schema_service.ConnectionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
