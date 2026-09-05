from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = _PROJECT_ROOT / "data"

load_dotenv(_PROJECT_ROOT / ".env.local")
load_dotenv(_PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_PROJECT_ROOT / ".env.local", _PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RelayDesk API"
    app_version: str = "2.0.0"
    api_host: str = Field(default="127.0.0.1", alias="RAG_API_HOST")
    api_port: int = Field(default=8090, alias="RAG_API_PORT")

    rag_backend: str = Field(default="qdrant", alias="RAG_BACKEND")
    rag_max_results: int = Field(default=5, alias="RAG_MAX_RESULTS")
    rag_min_score: float = Field(default=0.3, alias="RAG_MIN_SCORE")

    embedder_provider: str = Field(default="openai", alias="RAG_EMBEDDER_PROVIDER")
    embedder_model: str = Field(
        default="text-embedding-3-small",
        alias="RAG_EMBEDDER_MODEL",
    )
    embedder_dimensions: int = Field(default=1536, alias="RAG_EMBEDDER_DIMENSIONS")
    embedder_cache_enabled: bool = Field(default=True, alias="RAG_EMBEDDER_CACHE")
    embedder_cache_path: Path = Field(
        default=_DATA_DIR / "embedding_cache.sqlite",
        alias="RAG_EMBEDDER_CACHE_PATH",
    )

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_timeout: float = Field(default=30.0, alias="OPENAI_TIMEOUT")

    qdrant_url: str = Field(default="", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_timeout: float = Field(default=10.0, alias="QDRANT_TIMEOUT")
    qdrant_cluster_endpoint: str | None = Field(
        default=None, alias="QDRANT_CLUSTER_ENDPOINT"
    )
    qdrant_cluster_name: str | None = Field(default=None, alias="QDRANT_CLUSTER_NAME")
    cors_origins: str = Field(
        default=(
            "http://localhost:3000,"
            "http://127.0.0.1:3000,"
            "http://localhost:8081,"
            "http://127.0.0.1:8081,"
            "http://localhost:19006,"
            "http://127.0.0.1:19006"
        ),
        alias="CORS_ORIGINS",
    )
    cors_origin_regex: str | None = Field(
        default=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        alias="CORS_ORIGIN_REGEX",
    )

    oauth_disabled: bool = Field(default=False, alias="OAUTH_DISABLED")
    cognito_region: str | None = Field(default=None, alias="COGNITO_REGION")
    cognito_user_pool_id: str | None = Field(default=None, alias="COGNITO_USER_POOL_ID")
    cognito_ui_client_id: str | None = Field(default=None, alias="COGNITO_UI_CLIENT_ID")
    cognito_m2m_client_id: str | None = Field(
        default=None, alias="COGNITO_M2M_CLIENT_ID"
    )
    cognito_required_scope: str = Field(
        default="relaydesk-api/access",
        alias="COGNITO_REQUIRED_SCOPE",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cognito_issuer(self) -> str | None:
        if not self.cognito_region or not self.cognito_user_pool_id:
            return None
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
            f"{self.cognito_user_pool_id}"
        )

    @property
    def cognito_jwks_url(self) -> str | None:
        issuer = self.cognito_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None

    @model_validator(mode="after")
    def resolve_qdrant_cloud_url(self) -> Settings:
        if not self.qdrant_cluster_endpoint:
            return self
        url = self.qdrant_cluster_endpoint.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        if ":6333" not in url:
            url = f"{url}:6333"
        self.qdrant_url = url
        return self

    @model_validator(mode="after")
    def require_managed_backends(self) -> Settings:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return self
        if not self.qdrant_cluster_endpoint or not self.qdrant_api_key:
            raise ValueError(
                "QDRANT_CLUSTER_ENDPOINT and QDRANT_API_KEY are required "
                "(managed Qdrant Cloud only)."
            )
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL is required (local Docker default: "
                "postgresql+asyncpg://relaydesk:relaydesk@127.0.0.1:5434/relaydesk)."
            )
        return self

    database_url: str = Field(default="", alias="DATABASE_URL")
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")
    outbound_call_webhook_url: str | None = Field(
        default=None, alias="OUTBOUND_CALL_WEBHOOK_URL"
    )

    livekit_url: str | None = Field(default=None, alias="LIVEKIT_URL")
    livekit_api_key: str | None = Field(default=None, alias="LIVEKIT_API_KEY")
    livekit_api_secret: str | None = Field(default=None, alias="LIVEKIT_API_SECRET")
    livekit_sip_outbound_trunk_id: str | None = Field(
        default=None, alias="LIVEKIT_SIP_OUTBOUND_TRUNK_ID"
    )
    livekit_agent_name: str = Field(
        default="relaydesk-agent", alias="LIVEKIT_AGENT_NAME"
    )
    voice_agent_schedule_enabled: bool = Field(
        default=True, alias="VOICE_AGENT_SCHEDULE_ENABLED"
    )

    @property
    def livekit_outbound_enabled(self) -> bool:
        return bool(
            self.livekit_url
            and self.livekit_api_key
            and self.livekit_api_secret
            and self.livekit_sip_outbound_trunk_id
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
