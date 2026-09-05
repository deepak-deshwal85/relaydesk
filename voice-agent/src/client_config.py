import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("relaydesk-agent")

DEFAULT_VOICE_AGENT_GREETING = (
    "Greet the caller briefly. Introduce the business and summarize key service "
    "offerings. Say you can answer questions by searching the uploaded documents. "
    "Ask what they would like to know."
)
DEFAULT_VOICE_AGENT_LANGUAGE = "hi-IN"
SUPPORTED_VOICE_AGENT_LANGUAGES = (
    "hi-IN",
    "en-IN",
    "bn-IN",
    "gu-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "od-IN",
    "pa-IN",
    "ta-IN",
    "te-IN",
)
VOICE_AGENT_LANGUAGE_LABELS = {
    "hi-IN": "Hindi",
    "en-IN": "English",
    "bn-IN": "Bengali",
    "gu-IN": "Gujarati",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "od-IN": "Odia",
    "pa-IN": "Punjabi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
}


@dataclass(frozen=True)
class CalComConfig:
    username: str
    event_type_slug: str
    event_type_id: int | None = None
    organization_slug: str | None = None


@dataclass(frozen=True)
class ClientConfig:
    phone_number: str
    client_name: str
    client_email_id: str
    greeting_message: str
    voice_agent_language: str = DEFAULT_VOICE_AGENT_LANGUAGE
    calcom: CalComConfig | None = None
    rag_api_url: str | None = None


def normalize_phone_number(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def voice_agent_language_label(code: str) -> str:
    return VOICE_AGENT_LANGUAGE_LABELS.get(code, code)


def client_config_from_resolved(
    *,
    phone_digits: str,
    resolved,
) -> ClientConfig:
    calcom = None
    if resolved.calcom_username and resolved.calcom_event_type_slug:
        calcom = CalComConfig(
            username=resolved.calcom_username,
            event_type_slug=resolved.calcom_event_type_slug,
            event_type_id=resolved.calcom_event_type_id,
            organization_slug=resolved.calcom_organization_slug,
        )

    phone_number = normalize_phone_number(
        resolved.client_business_phone_number or phone_digits
    )
    language = (resolved.voice_agent_language or "").strip() or DEFAULT_VOICE_AGENT_LANGUAGE
    if language not in SUPPORTED_VOICE_AGENT_LANGUAGES:
        logger.warning("unsupported voice agent language %r; falling back to %s", language, DEFAULT_VOICE_AGENT_LANGUAGE)
        language = DEFAULT_VOICE_AGENT_LANGUAGE
    greeting = resolved.voice_agent_greeting_message.strip() or DEFAULT_VOICE_AGENT_GREETING

    return ClientConfig(
        phone_number=phone_number,
        client_name=resolved.client_name,
        client_email_id=resolved.client_email_id,
        voice_agent_language=language,
        greeting_message=greeting,
        calcom=calcom,
    )


async def resolve_client_config(
    phone_digits: str,
    *,
    metadata_email: str | None = None,
    base_url: str | None = None,
) -> ClientConfig | None:
    """Load per-client voice agent settings from the RelayDesk API at runtime."""
    from rag_client.config import load_rag_settings
    from voice_agent_config_client import (
        resolve_voice_agent_config_by_email,
        resolve_voice_agent_config_by_phone,
    )

    if not phone_digits and not metadata_email:
        return None

    rag_settings = load_rag_settings()
    api_base_url = base_url or rag_settings.rag_api_base_url

    resolved = None
    if phone_digits:
        resolved = await resolve_voice_agent_config_by_phone(
            phone_digits=phone_digits,
            base_url=api_base_url,
        )

    if resolved is None and metadata_email and "@" in metadata_email:
        resolved = await resolve_voice_agent_config_by_email(
            client_email_id=metadata_email,
            base_url=api_base_url,
        )

    if resolved is None:
        logger.warning(
            "No voice agent config matched phone=%s email=%s",
            phone_digits,
            metadata_email,
        )
        return None

    return client_config_from_resolved(
        phone_digits=phone_digits or resolved.client_business_phone_number or "",
        resolved=resolved,
    )
