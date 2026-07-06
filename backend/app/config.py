"""Application configuration.

Loads settings from environment variables (and an optional local .env file).
Keep all secrets and environment-specific values here so the rest of the app
never reads os.environ directly.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App metadata
    app_name: str = "Forecast Studio API"
    app_version: str = "0.1.0"

    # CORS allowlist for the frontend (comma-separated in the env var).
    # Defaults to the local Next.js dev server.
    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
