from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ClientVoiceAgentConfig:
    id: int
    client_id: int
    voice_agent_language: str
    voice_agent_greeting_message: str
    calcom_username: str | None
    calcom_event_type_slug: str | None
    calcom_event_type_id: int | None
    calcom_organization_slug: str | None
    created_at: datetime
    updated_at: datetime
    client_email_id: str
    client_name: str
    client_business_phone_number: str | None
