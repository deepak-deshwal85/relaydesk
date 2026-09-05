from __future__ import annotations

import io
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.core.dependencies import (  # noqa: E402
    get_call_job_service,
    get_call_summary_service,
    get_client_repository,
    get_client_service,
    get_client_voice_agent_config_service,
    get_collection_service,
    get_consumer_service,
    get_document_service,
    get_search_service,
    get_voice_agent_schedule_service,
    verify_access_token,
)
from app.core.oauth import AuthenticatedPrincipal  # noqa: E402
from app.main import create_app  # noqa: E402
from app.schemas.call_jobs import CallJobResponse  # noqa: E402
from app.schemas.call_summaries import CallSummaryResponse  # noqa: E402
from app.schemas.clients import ClientAdminListResponse, ClientAdminProfileResponse, ClientProfileResponse  # noqa: E402
from app.schemas.consumers import ConsumerResponse  # noqa: E402
from app.schemas.voice_agent_config import VoiceAgentConfigResponse  # noqa: E402
from app.schemas.voice_agent_schedules import (  # noqa: E402
    VoiceAgentScheduleOverviewResponse,
    VoiceAgentScheduleResponse,
    VoiceAgentScheduleTriggerResponse,
)


def _approved_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="user-1",
        client_id="mobile-client",
        username="acme@example.com",
        email="acme@example.com",
        scopes=frozenset({"relaydesk-api/access"}),
        token_use="access",
        groups=frozenset({"approved-clients"}),
        role="approved-clients",
        is_m2m=False,
    )


def _admin_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        subject="admin-1",
        client_id="mobile-client",
        username="admin@example.com",
        email="admin@example.com",
        scopes=frozenset({"relaydesk-api/access"}),
        token_use="access",
        groups=frozenset({"relaydesk-admins"}),
        role="relaydesk-admins",
        is_m2m=False,
    )


def test_mobile_me_for_client_user() -> None:
    now = datetime.now(UTC)
    mock_service = AsyncMock()
    profile = ClientProfileResponse(
        id=7,
        client_phone_number="919999999999",
        client_business_phone_number="911171366880",
        client_name="Acme",
        client_email_id="acme@example.com",
        created_at=now,
    )
    mock_service.ensure_on_sign_in.return_value = profile

    app = create_app()
    app.dependency_overrides[get_client_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    response = client.get("/v1/mobile/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_email"] == "acme@example.com"
    assert payload["is_admin"] is False
    assert payload["can_upload_documents"] is True
    assert payload["selected_client"]["client_email_id"] == "acme@example.com"
    assert payload["clients"][0]["is_approved"] is True


def test_mobile_admin_can_choose_client_scope() -> None:
    now = datetime.now(UTC)
    mock_service = AsyncMock()
    mock_service.list_clients_admin.return_value = ClientAdminListResponse(
        clients=[
            ClientAdminProfileResponse(
                id=7,
                client_phone_number=None,
                client_business_phone_number="911171366880",
                client_name="Acme",
                client_email_id="acme@example.com",
                created_at=now,
                is_approved=True,
            )
        ],
        count=1,
    )
    mock_service.get_profile.return_value = ClientProfileResponse(
        id=7,
        client_phone_number=None,
        client_business_phone_number="911171366880",
        client_name="Acme",
        client_email_id="acme@example.com",
        created_at=now,
    )

    app = create_app()
    app.dependency_overrides[get_client_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _admin_principal
    client = TestClient(app)

    response = client.get("/v1/mobile/me?selected_client_email_id=acme@example.com")
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_admin"] is True
    assert payload["selected_client"]["client_email_id"] == "acme@example.com"


def test_mobile_consumers_default_to_authenticated_scope() -> None:
    now = datetime.now(UTC)
    mock_repository = AsyncMock()
    mock_repository.get_by_email.return_value = type(
        "ClientStub",
        (),
        {
            "id": 42,
            "client_email_id": "acme@example.com",
            "client_business_phone_number": "911171366880",
        },
    )()
    mock_service = AsyncMock()
    mock_service.list.return_value = [
        ConsumerResponse(
            id=1,
            client_id=42,
            consumer_phone_number="919900000001",
            consumer_email_id="lead@example.com",
            consumer_name="Lead",
            consumer_address="Street 1",
            is_approved=True,
            status="READY",
            created_at=now,
            updated_at=now,
        )
    ]

    app = create_app()
    app.dependency_overrides[get_client_repository] = lambda: mock_repository
    app.dependency_overrides[get_consumer_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    response = client.get("/v1/mobile/consumers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    mock_service.list.assert_awaited_once_with(client_id=42, skip=0, limit=100)


def test_mobile_call_job_trigger_uses_mobile_scope() -> None:
    now = datetime.now(UTC)
    job_id = uuid4()
    mock_repository = AsyncMock()
    mock_repository.get_by_email.return_value = type(
        "ClientStub",
        (),
        {
            "id": 42,
            "client_email_id": "acme@example.com",
            "client_business_phone_number": "911171366880",
        },
    )()
    mock_service = AsyncMock()
    mock_service.create_job.return_value = CallJobResponse(
        id=job_id,
        client_id=42,
        status="pending",
        total_consumers=0,
        calls_completed=0,
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        results=None,
    )
    mock_service.run_job = AsyncMock()

    app = create_app()
    app.dependency_overrides[get_client_repository] = lambda: mock_repository
    app.dependency_overrides[get_call_job_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    response = client.post("/v1/mobile/call-jobs/trigger")
    assert response.status_code == 202
    assert response.json()["job_id"] == str(job_id)
    mock_service.create_job.assert_awaited_once_with(42)


def test_mobile_search_uses_scoped_client_email() -> None:
    mock_repository = AsyncMock()
    mock_repository.get_by_email.return_value = type(
        "ClientStub",
        (),
        {
            "id": 42,
            "client_email_id": "acme@example.com",
            "client_business_phone_number": "911171366880",
        },
    )()
    mock_service = MagicMock()
    mock_service.search.return_value = (
        [type("Hit", (), {"text": "Pricing info", "score": 0.91, "source_uri": "pricing.pdf"})()],
        "acme@example.com",
    )

    app = create_app()
    app.dependency_overrides[get_client_repository] = lambda: mock_repository
    app.dependency_overrides[get_search_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    response = client.post("/v1/mobile/search", json={"query": "pricing"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["client_email_id"] == "acme@example.com"
    assert payload["hits"][0]["source_uri"] == "pricing.pdf"


def test_mobile_documents_upload_and_list() -> None:
    mock_repository = AsyncMock()
    mock_repository.get_by_email.return_value = type(
        "ClientStub",
        (),
        {
            "id": 42,
            "client_email_id": "acme@example.com",
            "client_business_phone_number": "911171366880",
        },
    )()

    uploaded = type(
        "UploadResult",
        (),
        {
            "collection": "acme@example.com",
            "document_id": "doc-1",
            "source_uri": "pricing.pdf",
            "chunks_indexed": 3,
        },
    )()
    listed = [
        type(
            "DocSummary",
            (),
            {"document_id": "doc-1", "source_uri": "pricing.pdf", "chunk_count": 3},
        )()
    ]

    mock_document_service = MagicMock()
    mock_document_service.ingest_upload.return_value = uploaded
    mock_document_service.list_documents.return_value = listed

    app = create_app()
    app.dependency_overrides[get_client_repository] = lambda: mock_repository
    app.dependency_overrides[get_document_service] = lambda: mock_document_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    upload_response = client.post(
        "/v1/mobile/documents",
        files={"file": ("pricing.pdf", io.BytesIO(b"hello world"), "application/pdf")},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["document_id"] == "doc-1"

    list_response = client.get("/v1/mobile/documents")
    assert list_response.status_code == 200
    assert list_response.json()["documents"][0]["source_uri"] == "pricing.pdf"


def test_mobile_voice_agent_schedule_and_config() -> None:
    now = datetime.now(UTC)
    mock_repository = AsyncMock()
    mock_repository.get_by_email.return_value = type(
        "ClientStub",
        (),
        {
            "id": 42,
            "client_email_id": "acme@example.com",
            "client_business_phone_number": "911171366880",
        },
    )()
    config = VoiceAgentConfigResponse(
        id=1,
        client_id=42,
        client_email_id="acme@example.com",
        client_name="Acme",
        client_business_phone_number="911171366880",
        voice_agent_language="hi-IN",
        voice_agent_greeting_message="Hello",
        calcom_username="acme-user",
        calcom_event_type_slug="30min",
        calcom_event_type_id=123,
        calcom_organization_slug=None,
        created_at=now,
        updated_at=now,
    )
    schedule = VoiceAgentScheduleOverviewResponse(
        client_email_id="acme@example.com",
        client_name="Acme",
        client_business_phone_number="911171366880",
        ready_consumer_count=2,
        has_active_job=False,
        voice_agent_config=config,
        schedule=VoiceAgentScheduleResponse(
            id=1,
            client_id=42,
            enabled=True,
            run_time="09:00",
            days_of_week=[1, 2, 3, 4, 5],
            timezone="Asia/Kolkata",
            next_run_at=now,
            last_run_at=None,
            last_job_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    mock_config_service = AsyncMock()
    mock_config_service.get.return_value = config
    mock_schedule_service = AsyncMock()
    mock_schedule_service.get_overview.return_value = schedule
    mock_schedule_service.trigger_now.return_value = VoiceAgentScheduleTriggerResponse(
        job_id=uuid4(),
        status="pending",
        message="Campaign queued",
    )
    mock_call_job_service = AsyncMock()
    mock_call_job_service.run_job = AsyncMock()

    app = create_app()
    app.dependency_overrides[get_client_repository] = lambda: mock_repository
    app.dependency_overrides[get_client_voice_agent_config_service] = lambda: mock_config_service
    app.dependency_overrides[get_voice_agent_schedule_service] = lambda: mock_schedule_service
    app.dependency_overrides[get_call_job_service] = lambda: mock_call_job_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    config_response = client.get("/v1/mobile/voice-agent-config")
    assert config_response.status_code == 200
    schedule_response = client.get("/v1/mobile/voice-agent-schedule")
    assert schedule_response.status_code == 200
    trigger_response = client.post("/v1/mobile/voice-agent-schedule/trigger")
    assert trigger_response.status_code == 202


def test_mobile_call_summaries_list() -> None:
    now = datetime.now(UTC)
    mock_repository = AsyncMock()
    mock_repository.get_by_email.return_value = type(
        "ClientStub",
        (),
        {
            "id": 42,
            "client_email_id": "acme@example.com",
            "client_business_phone_number": "911171366880",
        },
    )()
    mock_service = AsyncMock()
    mock_service.list.return_value = [
        CallSummaryResponse(
            id=1,
            consumer_id=9,
            client_id=42,
            call_start_time=now,
            call_end_time=now,
            call_summary="Booked follow-up call",
            job_id=None,
            created_at=now,
            consumer_phone_number="919900000001",
            consumer_email_id="lead@example.com",
        )
    ]

    app = create_app()
    app.dependency_overrides[get_client_repository] = lambda: mock_repository
    app.dependency_overrides[get_call_summary_service] = lambda: mock_service
    app.dependency_overrides[verify_access_token] = _approved_principal
    client = TestClient(app)

    response = client.get("/v1/mobile/call-summaries")
    assert response.status_code == 200
    assert response.json()["summaries"][0]["consumer_id"] == 9
