"""Query routes.

Milestone 4: a single endpoint to test SQL generation in isolation. It runs
schema inspection -> local SQL generation -> SQL safety guard, and returns the
result. It does NOT execute the SQL (that arrives in Milestone 5) and needs no
API key or network access.
"""

import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.models.requests import GenerateSqlRequest, QueryRequest
from app.models.responses import GenerateSqlResponse, QueryResponse, Telemetry, Verification
from app.services import (
    execution_service,
    history_service,
    planner_service,
    schema_service,
    self_check_service,
    sql_generator,
    verification_service,
)
from app.services.sql_generator import SqlGenerator, get_sql_generator
from app.services.sql_guard import SqlGuardError, validate_sql

router = APIRouter(prefix="/query", tags=["query"])


def provide_sql_generator() -> SqlGenerator:
    """FastAPI dependency: build the configured SQL generator."""
    return get_sql_generator()


def _estimate_cost(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated USD cost. Zero for local/cache; token-priced for Groq."""
    if provider != "groq":
        return 0.0
    cost = (
        prompt_tokens / 1_000_000 * settings.groq_price_input_per_mtok
        + completion_tokens / 1_000_000 * settings.groq_price_output_per_mtok
    )
    return round(cost, 6)


def _run_sample(connection_id: str, safe_sql: str, plan):
    """Execute a small sample of ``safe_sql`` and self-check it against the plan.

    Returns ``(SampleCheck, sample_row_count)``. If the sample cannot execute,
    it is treated as a failed check so a repair is attempted.
    """
    try:
        sample_sql = self_check_service.build_sample_sql(safe_sql)
        sample = execution_service.execute(connection_id, sample_sql)
    except Exception:
        return self_check_service.SampleCheck(False, 0, "sample_execution_error"), 0
    check = self_check_service.check_sample(
        plan, sample.columns, sample.rows, sample.row_count
    )
    return check, sample.row_count


def _sample_check_and_repair(connection_id: str, safe_sql: str, plan):
    """Draft SQL is run on a sample and self-checked; one repair on failure.

    Flow: build sample (stricter LIMIT) -> execute -> self-check. On failure,
    attempt exactly one deterministic repair (canonical SQL re-rendered from the
    plan), re-guard it (never weakening the guard — an unsafe repair is
    rejected), and re-check its sample. The repair is adopted only if it passes.

    Returns ``(final_safe_sql, meta)`` where meta carries sample_checked,
    sample_row_count, repair_attempted, repair_successful.
    """
    meta = {
        "sample_checked": False,
        "sample_row_count": 0,
        "repair_attempted": False,
        "repair_successful": False,
    }

    check, sample_rows = _run_sample(connection_id, safe_sql, plan)
    meta["sample_checked"] = True
    meta["sample_row_count"] = sample_rows
    if check.passed:
        return safe_sql, meta

    # Sample check failed -> attempt one repair.
    meta["repair_attempted"] = True
    repaired_raw = self_check_service.repair_sql(plan)
    if repaired_raw:
        try:
            repaired_safe = validate_sql(repaired_raw)  # SAFETY GATE, unchanged
        except SqlGuardError:
            return safe_sql, meta  # unsafe repair rejected -> keep original
        rcheck, rsample_rows = _run_sample(connection_id, repaired_safe, plan)
        if rcheck.passed:
            meta["repair_successful"] = True
            meta["sample_row_count"] = rsample_rows
            return repaired_safe, meta

    return safe_sql, meta


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
    except schema_service.ConnectionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
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
    """Full flow: schema -> plan -> (cache | generate) -> guard -> execute -> verify."""
    total_start = time.perf_counter()

    # 1. Load the schema for grounding.
    try:
        schema = schema_service.get_schema(request.connection_id)
    except schema_service.UnknownConnectionError:
        raise HTTPException(status_code=404, detail=f"Unknown connection: {request.connection_id}")
    except schema_service.ConnectionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # 2. Plan the question (structured intent/tables/measures/…).
    plan_start = time.perf_counter()
    plan = planner_service.create_plan(request.question, schema)
    planner_ms = round((time.perf_counter() - plan_start) * 1000, 2)
    debug_plan = plan if request.show_debug else None
    schema_ver = history_service.schema_version(schema)
    normalized = history_service.normalize(request.question)

    # 2a. CACHE lookup + (on miss) generation — measured as the generation phase.
    gen_start = time.perf_counter()
    cache_hit = False
    cache_match_score = 0.0
    cached_from_question = None
    intent = None
    prompt_tokens = 0
    completion_tokens = 0
    sql_to_run = None
    # Only matched questions can hit the cache (dedup is scoped by intent).
    if settings.cache_enabled and plan.matched:
        cached = history_service.find_cached(
            request.connection_id, normalized, schema_ver,
            settings.semantic_cache_threshold, plan.intent,
        )
        if cached is not None:
            cache_hit = True
            cache_match_score = cached.similarity
            cached_from_question = cached.source_question
            sql_to_run = cached.sql
            intent = cached.intent

    if not cache_hit:
        result = generator.generate(request.question, schema, plan)

        # UNSUPPORTED: no confident match -> never fabricate or execute SQL.
        if not result.matched:
            generation_ms = round((time.perf_counter() - gen_start) * 1000, 2)
            telemetry = Telemetry(
                provider="local",
                planner_latency_ms=planner_ms,
                generation_latency_ms=generation_ms,
                total_latency_ms=round((time.perf_counter() - total_start) * 1000, 2),
            )
            history_service.record(
                connection_id=request.connection_id, question=request.question,
                normalized_question=normalized, generated_sql=None,
                intent=sql_generator.UNSUPPORTED_INTENT, schema_version=schema_ver,
                row_count=0, verified=False, cache_hit=False, telemetry=telemetry,
                confidence=0.0, runtime_ms=0.0,
            )
            return QueryResponse(
                question=request.question,
                connection_id=request.connection_id,
                dialect=schema.dialect,
                generator="local",
                matched=False,
                intent=sql_generator.UNSUPPORTED_INTENT,
                sql=None,
                guard_passed=False,
                columns=[],
                rows=[],
                row_count=0,
                runtime_ms=0.0,
                verification=Verification(
                    verified=False,
                    confidence=0.0,
                    explanation="No supported database analytics question matched, so no SQL was generated or executed.",
                    failure_reason=sql_generator.UNSUPPORTED_FAILURE_REASON,
                ),
                message=sql_generator.UNSUPPORTED_MESSAGE,
                suggestions=sql_generator.EXAMPLE_QUESTIONS,
                plan=debug_plan,
                cache_hit=False,
                telemetry=telemetry if request.show_debug else None,
            )
        sql_to_run = result.sql
        intent = result.intent
        prompt_tokens = result.prompt_tokens
        completion_tokens = result.completion_tokens
    generation_ms = round((time.perf_counter() - gen_start) * 1000, 2)

    # Provider actually used (cache / groq / local).
    provider = "cache" if cache_hit else ("groq" if intent == sql_generator.GROQ_INTENT else "local")
    if cache_hit:
        prompt_tokens = completion_tokens = 0

    # 3. SAFETY GATE: guard the SQL before execution (idempotent for cached SQL).
    try:
        safe_sql = validate_sql(sql_to_run)
    except SqlGuardError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Generated SQL was rejected by the safety guard: {exc}",
        )

    # 3b. Sample execution + self-check: run the draft on a small sample, check
    #     it against the plan, and repair once if it fails (repaired SQL is
    #     re-guarded). ``safe_sql`` becomes the repaired query only if it passed.
    sample_start = time.perf_counter()
    safe_sql, sample_meta = _sample_check_and_repair(request.connection_id, safe_sql, plan)
    sample_execution_ms = round((time.perf_counter() - sample_start) * 1000, 2)

    # 4. Execute the (possibly repaired) guarded SQL read-only, with a timeout.
    exec_start = time.perf_counter()
    try:
        query_result = execution_service.execute(request.connection_id, safe_sql)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # e.g. sqlite3.OperationalError on invalid SQL
        raise HTTPException(status_code=400, detail=f"Query execution failed: {exc}")
    execution_ms = round((time.perf_counter() - exec_start) * 1000, 2)

    # 5. Verify the result answers the question.
    ver_start = time.perf_counter()
    verification = verification_service.verify(
        intent=intent,
        matched=True,
        sql=safe_sql,
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
    )
    verification_ms = round((time.perf_counter() - ver_start) * 1000, 2)

    telemetry = Telemetry(
        provider=provider,
        planner_latency_ms=planner_ms,
        generation_latency_ms=generation_ms,
        sample_execution_latency_ms=sample_execution_ms,
        final_execution_latency_ms=execution_ms,
        verification_latency_ms=verification_ms,
        total_latency_ms=round((time.perf_counter() - total_start) * 1000, 2),
        cache_hit=cache_hit,
        repair_attempted=sample_meta["repair_attempted"],
        estimated_prompt_tokens=prompt_tokens,
        estimated_completion_tokens=completion_tokens,
        estimated_total_tokens=prompt_tokens + completion_tokens,
        estimated_cost_usd=_estimate_cost(provider, prompt_tokens, completion_tokens),
    )

    # 6. Record in history (for future cache lookups + the history log).
    history_service.record(
        connection_id=request.connection_id, question=request.question,
        normalized_question=normalized, generated_sql=safe_sql, intent=intent,
        schema_version=schema_ver, row_count=query_result.row_count,
        verified=verification.verified, cache_hit=cache_hit, telemetry=telemetry,
        confidence=verification.confidence, runtime_ms=query_result.runtime_ms,
    )

    return QueryResponse(
        question=request.question,
        connection_id=request.connection_id,
        dialect=schema.dialect,
        generator=provider,
        matched=True,
        intent=intent,
        sql=safe_sql,
        guard_passed=True,
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
        runtime_ms=query_result.runtime_ms,
        verification=verification,
        plan=debug_plan,
        cache_hit=cache_hit,
        cache_match_score=cache_match_score,
        cached_from_question=cached_from_question if request.show_debug else None,
        sample_checked=sample_meta["sample_checked"],
        sample_row_count=sample_meta["sample_row_count"],
        repair_attempted=sample_meta["repair_attempted"],
        repair_successful=sample_meta["repair_successful"],
        telemetry=telemetry if request.show_debug else None,
    )
