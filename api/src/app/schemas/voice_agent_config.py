from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain.voice_agent_defaults import (
    DEFAULT_VOICE_AGENT_LANGUAGE,
    SUPPORTED_VOICE_AGENT_LANGUAGES,
)


class VoiceAgentConfigResponse(BaseModel):
    id: int
    client_id: int
    client_email_id: str
    client_name: str
    client_business_phone_number: str | None
    voice_agent_language: str
    voice_agent_greeting_message: str
    calcom_username: str | None
    calcom_event_type_slug: str | None
    calcom_event_type_id: int | None
    calcom_organization_slug: str | None
    created_at: datetime
    updated_at: datetime


class VoiceAgentConfigUpdateRequest(BaseModel):
    voice_agent_language: str = Field(default=DEFAULT_VOICE_AGENT_LANGUAGE)
    voice_agent_greeting_message: str = Field(min_length=1, max_length=4000)
    calcom_username: str | None = Field(default=None, max_length=255)
    calcom_event_type_slug: str | None = Field(default=None, max_length=255)
    calcom_event_type_id: int | None = Field(default=None, ge=1)
    calcom_organization_slug: str | None = Field(default=None, max_length=255)

    @field_validator("voice_agent_language")
    @classmethod
    def validate_voice_agent_language(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in SUPPORTED_VOICE_AGENT_LANGUAGES:
            raise ValueError(
                "voice_agent_language must be one of: "
                + ", ".join(SUPPORTED_VOICE_AGENT_LANGUAGES)
            )
        return normalized


class VoiceAgentConfigResolveResponse(BaseModel):
    client_id: int
    client_email_id: str
    client_name: str
    client_business_phone_number: str | None
    voice_agent_language: str
    voice_agent_greeting_message: str
    calcom_username: str | None
    calcom_event_type_slug: str | None
    calcom_event_type_id: int | None
    calcom_organization_slug: str | None
