"""Shared test fixtures."""

import pytest

from app.config import settings
from app.db import sample_seed


@pytest.fixture(scope="session", autouse=True)
def seeded_demo_db():
    """Ensure the SQLite demo database exists and is seeded for the test session."""
    sample_seed.seed(settings.demo_db_path)
    yield
