from __future__ import annotations

from app.db.postgres.client_repository import ClientRepository
from app.db.postgres.client_voice_agent_config_repository import (
    ClientVoiceAgentConfigRepository,
)
from app.domain.client_voice_agent_config_models import ClientVoiceAgentConfig
from app.schemas.voice_agent_config import (
    VoiceAgentConfigResolveResponse,
    VoiceAgentConfigResponse,
    VoiceAgentConfigUpdateRequest,
)


class ClientVoiceAgentConfigService:
    def __init__(
        self,
        repository: ClientVoiceAgentConfigRepository,
        client_repository: ClientRepository,
    ) -> None:
        self._repository = repository
        self._client_repository = client_repository

    @staticmethod
    def _to_response(config: ClientVoiceAgentConfig) -> VoiceAgentConfigResponse:
        return VoiceAgentConfigResponse(
            id=config.id,
            client_id=config.client_id,
            client_email_id=config.client_email_id,
            client_name=config.client_name,
            client_business_phone_number=config.client_business_phone_number,
            voice_agent_language=config.voice_agent_language,
            voice_agent_greeting_message=config.voice_agent_greeting_message,
            calcom_username=config.calcom_username,
            calcom_event_type_slug=config.calcom_event_type_slug,
            calcom_event_type_id=config.calcom_event_type_id,
            calcom_organization_slug=config.calcom_organization_slug,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

    @staticmethod
    def _to_resolve_response(
        config: ClientVoiceAgentConfig,
    ) -> VoiceAgentConfigResolveResponse:
        return VoiceAgentConfigResolveResponse(
            client_id=config.client_id,
            client_email_id=config.client_email_id,
            client_name=config.client_name,
            client_business_phone_number=config.client_business_phone_number,
            voice_agent_language=config.voice_agent_language,
            voice_agent_greeting_message=config.voice_agent_greeting_message,
            calcom_username=config.calcom_username,
            calcom_event_type_slug=config.calcom_event_type_slug,
            calcom_event_type_id=config.calcom_event_type_id,
            calcom_organization_slug=config.calcom_organization_slug,
        )

    async def _ensure_for_client_email(
        self, client_email_id: str
    ) -> ClientVoiceAgentConfig:
        client = await self._client_repository.get_by_email(client_email_id)
        if client is None:
            raise ValueError("Client not found")
        return await self._repository.ensure_defaults(client)

    async def get(self, *, client_email_id: str) -> VoiceAgentConfigResponse:
        config = await self._ensure_for_client_email(client_email_id)
        return self._to_response(config)

    async def update(
        self,
        *,
        client_email_id: str,
        body: VoiceAgentConfigUpdateRequest,
    ) -> VoiceAgentConfigResponse:
        config = await self._repository.upsert(
            client_email_id=client_email_id,
            voice_agent_language=body.voice_agent_language,
            voice_agent_greeting_message=body.voice_agent_greeting_message,
            calcom_username=body.calcom_username,
            calcom_event_type_slug=body.calcom_event_type_slug,
            calcom_event_type_id=body.calcom_event_type_id,
            calcom_organization_slug=body.calcom_organization_slug,
        )
        return self._to_response(config)

    async def resolve_by_phone(
        self, phone_number: str
    ) -> VoiceAgentConfigResolveResponse | None:
        client = await self._client_repository.get_by_business_phone(phone_number)
        if client is None:
            return None
        config = await self._repository.ensure_defaults(client)
        return self._to_resolve_response(config)

    async def resolve_by_email(
        self, client_email_id: str
    ) -> VoiceAgentConfigResolveResponse | None:
        client = await self._client_repository.get_by_email(client_email_id)
        if client is None:
            return None
        config = await self._repository.ensure_defaults(client)
        return self._to_resolve_response(config)
