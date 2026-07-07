# Forecast Studio — backend (FastAPI).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Safe-by-default: free, offline, deterministic SQL generation.
    SQL_GENERATOR_PROVIDER=local

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app ./app

# The demo SQLite database is seeded automatically on startup (see main.py),
# so no build-time seeding is required.

EXPOSE 8000

# Honor the platform-provided $PORT (Render/Railway/Fly), default 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
