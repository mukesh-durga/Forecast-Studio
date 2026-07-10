"""Application configuration.

Loads settings from environment variables (and an optional local .env file).
Keep all secrets and environment-specific values here so the rest of the app
never reads os.environ directly.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # App metadata
    app_name: str = "Forecast Studio API"
    app_version: str = "0.1.0"

    # CORS allowlist for the frontend (comma-separated in the env var).
    # Defaults to the local Next.js dev server.
    cors_origins: str = "http://localhost:3000"

    # Path to the seeded SQLite demo database.
    demo_db_path: str = str(BACKEND_DIR / "demo.sqlite")

    # Optional Postgres demo connection (e.g. Neon). Empty = demo_postgres
    # is unavailable; the SQLite demo always works. Either env var works;
    # POSTGRES_DATABASE_URL takes precedence over DATABASE_URL.
    database_url: str = ""            # env DATABASE_URL
    postgres_database_url: str = ""   # env POSTGRES_DATABASE_URL (preferred)

    # Query history + semantic-dedup cache (metadata SQLite store).
    metadata_db_path: str = str(BACKEND_DIR / "metadata.sqlite")
    cache_enabled: bool = True                 # env CACHE_ENABLED
    semantic_cache_threshold: float = 0.85     # env SEMANTIC_CACHE_THRESHOLD (Jaccard)

    # Rows shown per table when returning schema context.
    schema_sample_rows: int = 3

    # SQL guard / execution safety limits.
    default_row_limit: int = 100  # LIMIT injected when a query has none
    max_row_limit: int = 1000     # hard ceiling; larger LIMITs are clamped
    query_timeout_seconds: float = 5.0  # wall-clock cap for a single query

    # Sample execution + self-check loop: draft SQL is first run on a small
    # sample (this LIMIT) and self-checked before the final query executes.
    sample_row_limit: int = 5

    # SQL generation provider. "local" is a free, deterministic, offline
    # rule-based generator (no API key, no internet). "groq" uses the Groq API
    # for generation and falls back to local on any failure. Default: local.
    sql_generator_provider: str = "local"  # env SQL_GENERATOR_PROVIDER

    # Groq (server-side only — never exposed to the browser).
    groq_api_key: str = ""                 # env GROQ_API_KEY
    groq_model: str = "llama-3.3-70b-versatile"  # env GROQ_MODEL
    groq_timeout_seconds: float = 15.0     # per-request cap for Groq calls

    # Estimated Groq pricing (USD per 1M tokens) for cost telemetry. Defaults are
    # approximate published rates for llama-3.3-70b; override per your model.
    groq_price_input_per_mtok: float = 0.59
    groq_price_output_per_mtok: float = 0.79

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def postgres_url(self) -> str:
        """Effective Postgres DSN for the demo_postgres connection.

        POSTGRES_DATABASE_URL takes precedence over DATABASE_URL so a Neon URL can
        be set without clobbering any generic DATABASE_URL the host injects.
        Empty string means demo_postgres is unavailable (SQLite still works).
        """
        return (self.postgres_database_url or self.database_url).strip()


settings = Settings()
