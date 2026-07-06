"""Query routes.

Milestone 4: a single endpoint to test SQL generation in isolation. It runs
schema inspection -> local SQL generation -> SQL safety guard, and returns the
result. It does NOT execute the SQL (that arrives in Milestone 5) and needs no
API key or network access.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.models.requests import GenerateSqlRequest, QueryRequest
from app.models.responses import GenerateSqlResponse, QueryResponse
from app.services import execution_service, schema_service, sql_generator
from app.services.sql_generator import SqlGenerator, get_sql_generator
from app.services.sql_guard import SqlGuardError, validate_sql

router = APIRouter(prefix="/query", tags=["query"])


def provide_sql_generator() -> SqlGenerator:
    """FastAPI dependency: build the configured SQL generator."""
    return get_sql_generator()


@router.post("/generate-sql", response_model=GenerateSqlResponse)
def generate_sql_endpoint(
    request: GenerateSqlRequest,
    generator: SqlGenerator = Depends(provide_sql_generator),
) -> GenerateSqlResponse:
    # 1. Load the schema for grounding.
    try:
        schema = schema_service.get_schema(request.connection_id)
    except schema_service.UnknownConnectionError:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {request.connection_id}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # 2. Generate SQL from the question (free, deterministic, offline).
    result = generator.generate(request.question, schema)

    # 3. Every generated query MUST pass through the guard before anything else.
    common = dict(
        question=request.question,
        connection_id=request.connection_id,
        dialect=schema.dialect,
        generator=generator.backend_name,
        matched=result.matched,
        intent=result.intent,
        raw_sql=result.sql,
    )
    try:
        safe_sql = validate_sql(result.sql)
        return GenerateSqlResponse(**common, sql=safe_sql, guard_passed=True)
    except SqlGuardError as exc:
        return GenerateSqlResponse(**common, sql=None, guard_passed=False, guard_error=str(exc))


@router.post("", response_model=QueryResponse)
def run_query(
    request: QueryRequest,
    generator: SqlGenerator = Depends(provide_sql_generator),
) -> QueryResponse:
    """Full flow: schema -> generate SQL -> guard -> execute -> return results."""
    # 1. Load the schema for grounding.
    try:
        schema = schema_service.get_schema(request.connection_id)
    except schema_service.UnknownConnectionError:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {request.connection_id}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # 2. Generate SQL from the question (free, deterministic, offline).
    result = generator.generate(request.question, schema)

    # 3. SAFETY GATE: only guard-approved SQL is ever executed.
    try:
        safe_sql = validate_sql(result.sql)
    except SqlGuardError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Generated SQL was rejected by the safety guard: {exc}",
        )

    # 4. Execute the guarded SQL read-only, with a timeout.
    try:
        query_result = execution_service.execute(request.connection_id, safe_sql)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # e.g. sqlite3.OperationalError on invalid SQL
        raise HTTPException(status_code=400, detail=f"Query execution failed: {exc}")

    return QueryResponse(
        question=request.question,
        connection_id=request.connection_id,
        dialect=schema.dialect,
        generator=generator.backend_name,
        matched=result.matched,
        intent=result.intent,
        sql=safe_sql,
        guard_passed=True,
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
        runtime_ms=query_result.runtime_ms,
    )
