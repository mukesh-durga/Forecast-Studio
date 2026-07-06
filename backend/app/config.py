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

    # Rows shown per table when returning schema context.
    schema_sample_rows: int = 3

    # SQL guard / execution safety limits.
    default_row_limit: int = 100  # LIMIT injected when a query has none
    max_row_limit: int = 1000     # hard ceiling; larger LIMITs are clamped
    query_timeout_seconds: float = 5.0  # wall-clock cap for a single query

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
