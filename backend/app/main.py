"""Forecast Studio — FastAPI application entrypoint."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_connections, routes_health, routes_query
from app.config import settings
from app.db import sample_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Demo mode: ensure the SQLite demo database exists so the app works out of
    # the box locally and in production. Only seeds when missing (never wipes an
    # existing database on restart).
    if not os.path.exists(settings.demo_db_path):
        sample_seed.seed(settings.demo_db_path)
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)
app.include_router(routes_connections.router)
app.include_router(routes_query.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}
