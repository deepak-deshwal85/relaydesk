from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from rag_client.oauth_token import get_cognito_token_provider

logger = logging.getLogger("relaydesk-agent")


@dataclass(frozen=True)
class ResolvedVoiceAgentConfig:
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


def _parse_resolve_payload(data: dict[str, object]) -> ResolvedVoiceAgentConfig:
    event_type_id = data.get("calcom_event_type_id")
    return ResolvedVoiceAgentConfig(
        client_id=int(data["client_id"]),
        client_email_id=str(data["client_email_id"]).strip().lower(),
        client_name=str(data["client_name"]),
        client_business_phone_number=(
            str(data["client_business_phone_number"])
            if data.get("client_business_phone_number")
            else None
        ),
        voice_agent_language=str(data.get("voice_agent_language") or "hi-IN").strip(),
        voice_agent_greeting_message=str(data["voice_agent_greeting_message"]),
        calcom_username=str(data["calcom_username"]) if data.get("calcom_username") else None,
        calcom_event_type_slug=(
            str(data["calcom_event_type_slug"])
            if data.get("calcom_event_type_slug")
            else None
        ),
        calcom_event_type_id=int(event_type_id) if event_type_id is not None else None,
        calcom_organization_slug=(
            str(data["calcom_organization_slug"])
            if data.get("calcom_organization_slug")
            else None
        ),
    )


async def _fetch_resolve(
    *,
    path: str,
    params: dict[str, str],
    base_url: str,
    http_client: httpx.AsyncClient | None,
) -> ResolvedVoiceAgentConfig | None:
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(15.0, connect=5.0),
    )
    headers: dict[str, str] = {}
    token_provider = get_cognito_token_provider()
    if token_provider is not None:
        token = await token_provider.get_access_token()
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = await client.get(path, params=params, headers=headers)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return _parse_resolve_payload(response.json())
    except Exception:
        logger.exception("failed to resolve voice agent config path=%s params=%s", path, params)
        return None
    finally:
        if owns_client:
            await client.aclose()


async def resolve_voice_agent_config_by_phone(
    *,
    phone_digits: str,
    base_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> ResolvedVoiceAgentConfig | None:
    if not phone_digits:
        return None
    return await _fetch_resolve(
        path="/v1/voice-agent-config/resolve-by-phone",
        params={"phone_number": phone_digits},
        base_url=base_url,
        http_client=http_client,
    )


async def resolve_voice_agent_config_by_email(
    *,
    client_email_id: str,
    base_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> ResolvedVoiceAgentConfig | None:
    email = client_email_id.strip().lower()
    if not email or "@" not in email:
        return None
    return await _fetch_resolve(
        path="/v1/voice-agent-config/resolve-by-email",
        params={"client_email_id": email},
        base_url=base_url,
        http_client=http_client,
    )
