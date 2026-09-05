import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from client_config import ClientConfig, client_config_from_resolved
from voice_agent_config_client import ResolvedVoiceAgentConfig


def _sample_resolved(**overrides) -> ResolvedVoiceAgentConfig:
    defaults = dict(
        client_id=1,
        client_email_id="acme@example.com",
        client_name="Acme Support",
        client_business_phone_number="911171366880",
        voice_agent_language="hi-IN",
        voice_agent_greeting_message="Hello from Acme.",
        calcom_username="acme-user",
        calcom_event_type_slug="30min",
        calcom_event_type_id=123,
        calcom_organization_slug=None,
    )
    defaults.update(overrides)
    return ResolvedVoiceAgentConfig(**defaults)


def test_client_config_from_resolved_builds_calcom():
    config = client_config_from_resolved(
        phone_digits="911171366880",
        resolved=_sample_resolved(),
    )
    assert config.phone_number == "911171366880"
    assert config.client_name == "Acme Support"
    assert config.client_email_id == "acme@example.com"
    assert config.voice_agent_language == "hi-IN"
    assert config.greeting_message == "Hello from Acme."
    assert config.calcom is not None
    assert config.calcom.username == "acme-user"
    assert config.calcom.event_type_slug == "30min"


def test_client_config_from_resolved_defaults_language_to_hindi():
    config = client_config_from_resolved(
        phone_digits="911171366880",
        resolved=_sample_resolved(voice_agent_language=""),
    )
    assert config.voice_agent_language == "hi-IN"


@pytest.mark.asyncio
async def test_resolve_client_config_uses_api():
    resolved = _sample_resolved()
    with patch(
        "voice_agent_config_client.resolve_voice_agent_config_by_phone",
        new=AsyncMock(return_value=resolved),
    ):
        from client_config import resolve_client_config

        config = await resolve_client_config("911171366880")
        assert config is not None
        assert config.client_email_id == "acme@example.com"


@pytest.mark.asyncio
async def test_resolve_client_config_falls_back_to_email():
    resolved = _sample_resolved()
    with patch(
        "voice_agent_config_client.resolve_voice_agent_config_by_phone",
        new=AsyncMock(return_value=None),
    ), patch(
        "voice_agent_config_client.resolve_voice_agent_config_by_email",
        new=AsyncMock(return_value=resolved),
    ):
        from client_config import resolve_client_config

        config = await resolve_client_config(
            "",
            metadata_email="acme@example.com",
        )
        assert config is not None
        assert config.client_name == "Acme Support"
