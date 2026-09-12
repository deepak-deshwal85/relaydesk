from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.oauth import (
    AuthenticatedPrincipal,
    dev_bypass_principal,
    enrich_ui_principal_session_email,
    validate_access_token,
)
from app.core.rbac import Permission
from app.db.embedding_provider import EmbeddingProviderFactory
from app.db.postgres.call_summary_repository import CallSummaryRepository
from app.db.postgres.client_repository import ClientRepository
from app.db.postgres.client_voice_agent_config_repository import (
    ClientVoiceAgentConfigRepository,
)
from app.db.postgres.consumer_repository import ConsumerRepository
from app.db.postgres.session import get_db_session, get_session_factory
from app.db.qdrant_repository import QdrantRepository
from app.services.call_job_service import CallJobService, build_call_job_service
from app.services.call_summary_service import CallSummaryService
from app.services.client_service import ClientService
from app.services.client_voice_agent_config_service import ClientVoiceAgentConfigService
from app.services.collection_service import CollectionService
from app.services.consumer_service import ConsumerService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.phone_line_service import PhoneLineService
from app.services.search_service import SearchService
from app.services.voice_agent_schedule_service import VoiceAgentScheduleService

_call_job_service: CallJobService | None = None
_qdrant_repository: QdrantRepository | None = None
_embedding_provider_factory: EmbeddingProviderFactory | None = None


def get_qdrant_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> QdrantRepository:
    global _qdrant_repository
    if _qdrant_repository is None:
        _qdrant_repository = QdrantRepository(settings)
    return _qdrant_repository


def get_embedding_provider_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmbeddingProviderFactory:
    global _embedding_provider_factory
    if _embedding_provider_factory is None:
        _embedding_provider_factory = EmbeddingProviderFactory(settings)
    return _embedding_provider_factory


def get_embedding_service(
    settings: Annotated[Settings, Depends(get_settings)],
    provider_factory: Annotated[
        EmbeddingProviderFactory, Depends(get_embedding_provider_factory)
    ],
) -> EmbeddingService:
    return EmbeddingService(settings, provider_factory)


def get_document_service(
    settings: Annotated[Settings, Depends(get_settings)],
    qdrant: Annotated[QdrantRepository, Depends(get_qdrant_repository)],
    embedding_service: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> DocumentService:
    return DocumentService(settings, qdrant, embedding_service)


def get_search_service(
    settings: Annotated[Settings, Depends(get_settings)],
    qdrant: Annotated[QdrantRepository, Depends(get_qdrant_repository)],
    embedding_service: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> SearchService:
    return SearchService(settings, qdrant, embedding_service)


def get_collection_service(
    qdrant: Annotated[QdrantRepository, Depends(get_qdrant_repository)],
) -> CollectionService:
    return CollectionService(qdrant)


async def get_client_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ClientRepository:
    return ClientRepository(session)


async def get_client_service(
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    collection_service: Annotated[CollectionService, Depends(get_collection_service)],
) -> ClientService:
    from app.services.cognito_admin_service import get_cognito_admin_service

    return ClientService(
        repository,
        get_cognito_admin_service(),
        collection_service,
    )


async def get_consumer_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConsumerRepository:
    return ConsumerRepository(session)


async def get_consumer_service(
    repository: Annotated[ConsumerRepository, Depends(get_consumer_repository)],
) -> ConsumerService:
    return ConsumerService(repository)


async def get_call_summary_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CallSummaryRepository:
    return CallSummaryRepository(session)


async def get_call_summary_service(
    repository: Annotated[CallSummaryRepository, Depends(get_call_summary_repository)],
    consumer_repository: Annotated[
        ConsumerRepository, Depends(get_consumer_repository)
    ],
) -> CallSummaryService:
    return CallSummaryService(repository, consumer_repository)


async def get_client_voice_agent_config_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ClientVoiceAgentConfigRepository:
    return ClientVoiceAgentConfigRepository(session)


async def get_client_voice_agent_config_service(
    repository: Annotated[
        ClientVoiceAgentConfigRepository,
        Depends(get_client_voice_agent_config_repository),
    ],
    client_repository: Annotated[ClientRepository, Depends(get_client_repository)],
) -> ClientVoiceAgentConfigService:
    return ClientVoiceAgentConfigService(repository, client_repository)


async def get_voice_agent_schedule_service(
    config_service: Annotated[
        ClientVoiceAgentConfigService,
        Depends(get_client_voice_agent_config_service),
    ],
    call_job_service: Annotated[CallJobService, Depends(get_call_job_service)],
) -> VoiceAgentScheduleService:
    return VoiceAgentScheduleService(
        session_factory=get_session_factory(),
        config_service=config_service,
        call_job_service=call_job_service,
    )


def get_phone_line_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PhoneLineService:
    return PhoneLineService(settings, get_session_factory())


def get_call_job_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> CallJobService:
    global _call_job_service
    if _call_job_service is None:
        _call_job_service = build_call_job_service(settings)
    return _call_job_service


def reset_call_job_service() -> None:
    global _call_job_service
    _call_job_service = None


def reset_rag_clients() -> None:
    global _qdrant_repository, _embedding_provider_factory
    _qdrant_repository = None
    _embedding_provider_factory = None


_bearer_scheme = HTTPBearer(auto_error=False)


def verify_access_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> AuthenticatedPrincipal:
    if settings.oauth_disabled:
        return dev_bypass_principal(
            session_email=request.headers.get("x-relaydesk-user-email"),
            session_role=request.headers.get("x-relaydesk-user-role"),
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = validate_access_token(credentials.credentials, settings)
    return enrich_ui_principal_session_email(
        principal,
        session_email=request.headers.get("x-relaydesk-user-email"),
        settings=settings,
    )


def require_permission(permission: Permission):
    def _dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    ) -> AuthenticatedPrincipal:
        if not principal.has_permission(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return principal

    return _dependency
