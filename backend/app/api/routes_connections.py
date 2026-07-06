"""Connection + schema inspection routes.

Milestone 2: list the available (demo) connection and return its schema.
"""

from fastapi import APIRouter, HTTPException

from app.models.responses import SchemaResponse
from app.services import schema_service

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("")
def list_connections() -> dict:
    """List available connections. For now only the built-in demo DB exists."""
    return {
        "connections": [
            {
                "id": schema_service.DEMO_CONNECTION_ID,
                "label": "Demo (SQLite e-commerce)",
                "dialect": "sqlite",
            }
        ]
    }


@router.get("/{connection_id}/schema", response_model=SchemaResponse)
def get_connection_schema(connection_id: str) -> SchemaResponse:
    try:
        return schema_service.get_schema(connection_id)
    except schema_service.UnknownConnectionError:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {connection_id}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
