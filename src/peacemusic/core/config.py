"""Validated infrastructure configuration for the v2 composition root.

Guild behavior is deliberately absent from this module.  It belongs in the
database-backed guild settings module and must not be represented as process
environment configuration.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class _EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class DiscordSettings(_EnvironmentSettings):
    """Secrets and bootstrap options required to connect to Discord."""

    token: SecretStr = Field(
        validation_alias=AliasChoices("DISCORD_BOT_TOKEN", "DISCORD_TOKEN")
    )
    application_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_APPLICATION_ID", "APPLICATION_ID"),
    )


class DatabaseSettings(_EnvironmentSettings):
    """PostgreSQL connection settings."""

    url: str = Field(
        default="postgresql://peacemusic:peacemusic@localhost:5432/peacemusic",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )
    min_pool_size: PositiveInt = Field(default=1, validation_alias="DB_MIN_POOL_SIZE")
    max_pool_size: PositiveInt = Field(default=10, validation_alias="DB_MAX_POOL_SIZE")


class GeminiSettings(_EnvironmentSettings):
    """Gemini credentials and model policy controlled by the operator."""

    api_key: SecretStr = Field(
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY")
    )
    response_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias=AliasChoices("GEMINI_RESPONSE_MODEL", "GEMINI_MODEL"),
    )
    allowed_models: tuple[str, ...] = Field(
        default=("gemini-3.1-flash-lite",),
        validation_alias="ALLOWED_AI_MODELS",
    )
    request_timeout_seconds: PositiveInt = Field(
        default=30, validation_alias="GEMINI_REQUEST_TIMEOUT_SECONDS"
    )


class ObservabilitySettings(_EnvironmentSettings):
    """Logging and optional tracing configuration."""

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    langsmith_api_key: SecretStr | None = Field(
        default=None, validation_alias="LANGSMITH_API_KEY"
    )


class GlobalLimits(_EnvironmentSettings):
    """Operator-owned ceilings that guild administrators cannot exceed."""

    max_concurrent_ai_turns: PositiveInt = Field(
        default=20, validation_alias="GLOBAL_MAX_CONCURRENT_AI_TURNS"
    )
    max_download_size_mb: PositiveInt = Field(
        default=100, validation_alias="GLOBAL_MAX_DOWNLOAD_SIZE_MB"
    )
    max_queue_size: PositiveInt = Field(
        default=1000, validation_alias="GLOBAL_MAX_QUEUE_SIZE"
    )
    health_server_port: Annotated[int, Field(ge=1, le=65535)] = Field(
        default=8080, validation_alias="HEALTH_SERVER_PORT"
    )


class AppSettings:
    """Complete bootstrap configuration assembled from typed settings groups."""

    def __init__(
        self,
        *,
        discord: DiscordSettings | None = None,
        database: DatabaseSettings | None = None,
        gemini: GeminiSettings | None = None,
        observability: ObservabilitySettings | None = None,
        limits: GlobalLimits | None = None,
    ) -> None:
        self.discord = discord or DiscordSettings()
        self.database = database or DatabaseSettings()
        self.gemini = gemini or GeminiSettings()
        self.observability = observability or ObservabilitySettings()
        self.limits = limits or GlobalLimits()

        if self.gemini.response_model not in self.gemini.allowed_models:
            raise ValueError(
                "GEMINI_RESPONSE_MODEL must be included in ALLOWED_AI_MODELS"
            )
        if self.database.min_pool_size > self.database.max_pool_size:
            raise ValueError("DB_MIN_POOL_SIZE cannot exceed DB_MAX_POOL_SIZE")
