import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.core.dependencies import (
    get_client_repository,
    get_client_voice_agent_config_service,
    verify_access_token,
)
from app.core.oauth import AuthenticatedPrincipal
from app.main import create_app
from app.schemas.voice_agent_config import (
    VoiceAgentConfigResolveResponse,
    VoiceAgentConfigResponse,
)


def _m2m_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="m2m-client",
        client_id="voice-agent",
        username=None,
        email=None,
        scopes=frozenset({"relaydesk-api/access"}),
        token_use="access",
        groups=frozenset(),
        role=None,
        is_m2m=True,
    )


def _ui_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="user-1",
        client_id="ui",
        username=None,
        email="acme@example.com",
        scopes=frozenset({"relaydesk-api/access"}),
        token_use="access",
        groups=frozenset({"approved-clients"}),
        role="approved-clients",
        is_m2m=False,
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    service = AsyncMock()
    now = datetime.now(UTC)
    service.get.return_value = VoiceAgentConfigResponse(
        id=1,
        client_id=10,
        client_email_id="acme@example.com",
        client_name="Acme Support",
        client_business_phone_number="911171366880",
        voice_agent_language="hi-IN",
        voice_agent_greeting_message="Hello from Acme.",
        calcom_username="acme-user",
        calcom_event_type_slug="30min",
        calcom_event_type_id=123,
        calcom_organization_slug=None,
        created_at=now,
        updated_at=now,
    )
    service.update.return_value = service.get.return_value
    service.resolve_by_phone.return_value = VoiceAgentConfigResolveResponse(
        client_id=10,
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
    return service


def test_get_voice_agent_config(mock_service: AsyncMock) -> None:
    app = create_app()
    app.dependency_overrides[get_client_voice_agent_config_service] = lambda: mock_service
    app.dependency_overrides[get_client_repository] = lambda: AsyncMock()
    app.dependency_overrides[verify_access_token] = lambda: _ui_principal()
    client = TestClient(app)

    response = client.get(
        "/v1/voice-agent-config?client_email_id=acme@example.com",
    )
    assert response.status_code == 200
    assert response.json()["client_email_id"] == "acme@example.com"
    assert response.json()["voice_agent_language"] == "hi-IN"


def test_update_voice_agent_config(mock_service: AsyncMock) -> None:
    app = create_app()
    app.dependency_overrides[get_client_voice_agent_config_service] = lambda: mock_service
    app.dependency_overrides[get_client_repository] = lambda: AsyncMock()
    app.dependency_overrides[verify_access_token] = lambda: _ui_principal()
    client = TestClient(app)

    response = client.put(
        "/v1/voice-agent-config?client_email_id=acme@example.com",
        json={
            "voice_agent_language": "ta-IN",
            "voice_agent_greeting_message": "Updated greeting with service offerings.",
            "calcom_username": "acme-user",
            "calcom_event_type_slug": "30min",
            "calcom_event_type_id": 123,
        },
    )
    assert response.status_code == 200
    mock_service.update.assert_awaited_once()


def test_update_voice_agent_config_rejects_invalid_language(mock_service: AsyncMock) -> None:
    app = create_app()
    app.dependency_overrides[get_client_voice_agent_config_service] = lambda: mock_service
    app.dependency_overrides[get_client_repository] = lambda: AsyncMock()
    app.dependency_overrides[verify_access_token] = lambda: _ui_principal()
    client = TestClient(app)

    response = client.put(
        "/v1/voice-agent-config?client_email_id=acme@example.com",
        json={
            "voice_agent_language": "fr-FR",
            "voice_agent_greeting_message": "Updated greeting with service offerings.",
        },
    )
    assert response.status_code == 422


def test_resolve_by_phone_requires_m2m(mock_service: AsyncMock) -> None:
    app = create_app()
    app.dependency_overrides[get_client_voice_agent_config_service] = lambda: mock_service

    app.dependency_overrides[verify_access_token] = lambda: _ui_principal()
    client = TestClient(app)

    response = client.get(
        "/v1/voice-agent-config/resolve-by-phone",
        params={"phone_number": "911171366880"},
    )
    assert response.status_code == 403


def test_resolve_by_phone_returns_config(mock_service: AsyncMock) -> None:
    app = create_app()
    app.dependency_overrides[get_client_voice_agent_config_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _m2m_principal
    client = TestClient(app)

    response = client.get(
        "/v1/voice-agent-config/resolve-by-phone",
        params={"phone_number": "911171366880"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["client_email_id"] == "acme@example.com"
    assert data["voice_agent_language"] == "hi-IN"
    assert data["calcom_username"] == "acme-user"
    assert "knowledge_base_topic" not in data
