from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres.models import ClientRow, ClientVoiceAgentConfigRow
from app.domain.client_models import Client
from app.domain.client_voice_agent_config_models import ClientVoiceAgentConfig
from app.domain.consumer_models import normalize_email
from app.domain.voice_agent_defaults import (
    DEFAULT_VOICE_AGENT_GREETING,
    DEFAULT_VOICE_AGENT_LANGUAGE,
    SUPPORTED_VOICE_AGENT_LANGUAGES,
)


class ClientVoiceAgentConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(
        config_row: ClientVoiceAgentConfigRow,
        client_row: ClientRow,
    ) -> ClientVoiceAgentConfig:
        return ClientVoiceAgentConfig(
            id=config_row.id,
            client_id=config_row.client_id,
            voice_agent_language=config_row.voice_agent_language,
            voice_agent_greeting_message=config_row.voice_agent_greeting_message,
            calcom_username=config_row.calcom_username,
            calcom_event_type_slug=config_row.calcom_event_type_slug,
            calcom_event_type_id=config_row.calcom_event_type_id,
            calcom_organization_slug=config_row.calcom_organization_slug,
            created_at=config_row.created_at,
            updated_at=config_row.updated_at,
            client_email_id=client_row.client_email_id,
            client_name=client_row.client_name,
            client_business_phone_number=client_row.client_business_phone_number,
        )

    async def _get_client_row(self, client_email_id: str) -> ClientRow | None:
        return (
            await self._session.execute(
                select(ClientRow).where(
                    ClientRow.client_email_id == normalize_email(client_email_id)
                )
            )
        ).scalar_one_or_none()

    async def _get_config_row(self, client_id: int) -> ClientVoiceAgentConfigRow | None:
        return (
            await self._session.execute(
                select(ClientVoiceAgentConfigRow).where(
                    ClientVoiceAgentConfigRow.client_id == client_id
                )
            )
        ).scalar_one_or_none()

    async def get_by_client_email(
        self, client_email_id: str
    ) -> ClientVoiceAgentConfig | None:
        client_row = await self._get_client_row(client_email_id)
        if client_row is None:
            return None
        config_row = await self._get_config_row(client_row.id)
        if config_row is None:
            return None
        return self._to_domain(config_row, client_row)

    async def get_by_business_phone(
        self, phone_number: str
    ) -> ClientVoiceAgentConfig | None:
        from app.domain.consumer_models import normalize_phone_number

        normalized = normalize_phone_number(phone_number)
        client_row = (
            await self._session.execute(
                select(ClientRow).where(
                    ClientRow.client_business_phone_number == normalized
                )
            )
        ).scalar_one_or_none()
        if client_row is None:
            return None
        config_row = await self._get_config_row(client_row.id)
        if config_row is None:
            return None
        return self._to_domain(config_row, client_row)

    async def ensure_defaults(self, client: Client) -> ClientVoiceAgentConfig:
        config_row = await self._get_config_row(client.id)
        client_row = await self._session.get(ClientRow, client.id)
        if client_row is None:
            raise ValueError("Client not found")

        if config_row is None:
            config_row = ClientVoiceAgentConfigRow(
                client_id=client.id,
                voice_agent_language=DEFAULT_VOICE_AGENT_LANGUAGE,
                voice_agent_greeting_message=DEFAULT_VOICE_AGENT_GREETING,
            )
            self._session.add(config_row)
            await self._session.commit()
            await self._session.refresh(config_row)

        return self._to_domain(config_row, client_row)

    async def upsert(
        self,
        *,
        client_email_id: str,
        voice_agent_language: str,
        voice_agent_greeting_message: str,
        calcom_username: str | None,
        calcom_event_type_slug: str | None,
        calcom_event_type_id: int | None,
        calcom_organization_slug: str | None,
    ) -> ClientVoiceAgentConfig:
        client_row = await self._get_client_row(client_email_id)
        if client_row is None:
            raise ValueError("Client not found")

        greeting = voice_agent_greeting_message.strip()
        if not greeting:
            raise ValueError("voice_agent_greeting_message is required")
        language = voice_agent_language.strip()
        if language not in SUPPORTED_VOICE_AGENT_LANGUAGES:
            raise ValueError("voice_agent_language is not supported")

        config_row = await self._get_config_row(client_row.id)
        if config_row is None:
            config_row = ClientVoiceAgentConfigRow(
                client_id=client_row.id,
                voice_agent_language=language,
                voice_agent_greeting_message=greeting,
            )
            self._session.add(config_row)

        config_row.voice_agent_language = language
        config_row.voice_agent_greeting_message = greeting
        config_row.calcom_username = calcom_username.strip() if calcom_username else None
        config_row.calcom_event_type_slug = (
            calcom_event_type_slug.strip() if calcom_event_type_slug else None
        )
        config_row.calcom_event_type_id = calcom_event_type_id
        config_row.calcom_organization_slug = (
            calcom_organization_slug.strip() if calcom_organization_slug else None
        )

        await self._session.commit()
        await self._session.refresh(config_row)
        return self._to_domain(config_row, client_row)
