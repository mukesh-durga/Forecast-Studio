"""Shared test fixtures."""

import pytest

from app.config import settings
from app.db import sample_seed


@pytest.fixture(scope="session", autouse=True)
def seeded_demo_db():
    """Ensure the SQLite demo database exists and is seeded for the test session."""
    sample_seed.seed(settings.demo_db_path)
    yield


@pytest.fixture(autouse=True)
def _default_local_provider(monkeypatch):
    """Force the local SQL provider for tests, independent of any dev backend/.env.

    Groq-specific tests override these explicitly.
    """
    monkeypatch.setattr(settings, "sql_generator_provider", "local")
    monkeypatch.setattr(settings, "groq_api_key", "")
