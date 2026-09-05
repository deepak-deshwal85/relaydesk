from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from client_config import ClientConfig

logger = logging.getLogger("relaydesk-agent")

RAG_BACKEND = "qdrant"


@dataclass(frozen=True)
class RagClientSettings:
    max_results: int
    rag_api_base_url: str
    min_score: float


def load_rag_settings() -> RagClientSettings:
    backend = os.getenv("RAG_BACKEND", RAG_BACKEND).strip().lower()
    if backend != RAG_BACKEND:
        raise ValueError(
            f"Unsupported RAG_BACKEND {backend!r}. Only {RAG_BACKEND!r} is supported."
        )

    return RagClientSettings(
        max_results=int(os.getenv("RAG_MAX_RESULTS", "3")),
        rag_api_base_url=os.getenv(
            "RAG_API_BASE_URL", "http://127.0.0.1:8090"
        ).strip().rstrip("/"),
        min_score=float(os.getenv("RAG_MIN_SCORE", "0.3")),
    )


def resolve_rag_api_url(
    client_config: ClientConfig,
    settings: RagClientSettings | None = None,
) -> str:
    rag_settings = settings or load_rag_settings()
    if client_config.rag_api_url:
        return client_config.rag_api_url.strip().rstrip("/")
    return rag_settings.rag_api_base_url
