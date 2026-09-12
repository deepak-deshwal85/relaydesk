from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import Settings
from app.domain.client_models import Client
from app.domain.phone_line_models import PhoneLine
from app.services.phone_line_service import (
    PhoneLineService,
    generate_sip_credentials,
    resolve_outbound_trunk_id,
)


class MemoryPhoneRepo:
    lines: dict[int, PhoneLine] = {}

    def __init__(self, _session) -> None:
        pass

    async def get_by_client_id(self, client_id: int) -> PhoneLine | None:
        return self.lines.get(client_id)

    async def save(self, line: PhoneLine) -> PhoneLine:
        line.id = line.id or 1
        self.lines[line.client_id] = line
        return line


class MemoryClientRepo:
    phones: dict[str, str] = {}

    def __init__(self, _session) -> None:
        pass

    async def set_business_phone(
        self, *, client_email_id: str, client_business_phone_number: str
    ):
        self.phones[client_email_id] = client_business_phone_number


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class FakePlivo:
    def __init__(self) -> None:
        self.bought: list[str] = []
        self.assigned: list[tuple[str, str]] = []

    async def search_voice_numbers(
        self, *, country_iso: str, number_type: str, limit: int = 5
    ):
        return ["919811122233"]

    async def buy_number(self, number: str):
        self.bought.append(number)
        return {"number": number}

    async def assign_number_to_trunk(self, number: str, trunk_id: str):
        self.assigned.append((number, trunk_id))
        return {"message": "changed"}

    async def create_origination_uri(self, *, name: str, uri: str) -> str:
        return "uri-1"

    async def create_inbound_trunk(self, *, name: str, uri_uuid: str) -> str:
        return "plivo-in"

    async def create_credential(
        self, *, name: str, username: str, password: str
    ) -> str:
        return "cred-1"

    async def create_outbound_trunk(self, *, name: str, credential_uuid: str) -> str:
        return "plivo-out"

    async def get_trunk_domain(self, trunk_id: str) -> str:
        return f"{trunk_id}.zt.plivo.com"


class FakeLiveKit:
    def __init__(self) -> None:
        self.outbound: list[str] = []

    async def create_inbound_trunk(self, *, name: str, e164_number: str) -> str:
        return "lk-in"

    async def create_dispatch_rule(self, **_kwargs) -> str:
        return "lk-rule"

    async def create_outbound_trunk(self, *, address: str, **_kwargs) -> str:
        self.outbound.append(address)
        return "lk-out"


def _client() -> Client:
    return Client(
        id=7,
        client_phone_number=None,
        client_business_phone_number=None,
        client_name="Acme",
        client_email_id="acme@example.com",
        created_at=datetime.now(UTC),
    )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        QDRANT_CLUSTER_ENDPOINT="https://example.cloud.qdrant.io",
        QDRANT_API_KEY="test",
        DATABASE_URL="postgresql+asyncpg://relaydesk:relaydesk@127.0.0.1:5434/relaydesk",
        LIVEKIT_URL="wss://example.livekit.cloud",
        LIVEKIT_API_KEY="key",
        LIVEKIT_API_SECRET="secret",
        LIVEKIT_SIP_HOST="example.sip.livekit.cloud",
        PLIVO_AUTH_ID="auth",
        PLIVO_AUTH_TOKEN="token",
    )


def _service(plivo: FakePlivo, livekit: FakeLiveKit) -> PhoneLineService:
    return PhoneLineService(
        _settings(),
        lambda: FakeSession(),
        plivo=plivo,
        livekit=livekit,
    )


def test_generate_sip_credentials_match_plivo_rules() -> None:
    username, password = generate_sip_credentials(12)
    assert username.isalnum()
    assert 5 <= len(username) <= 20
    assert 5 <= len(password) <= 20
    assert any(char in "!@#$%^*_+" for char in password)


def test_active_line_trunk_wins_over_shared_fallback() -> None:
    assert (
        resolve_outbound_trunk_id(
            line_status="active",
            line_trunk_id="ST_user",
            fallback_trunk_id="ST_shared",
        )
        == "ST_user"
    )
    assert (
        resolve_outbound_trunk_id(
            line_status="failed",
            line_trunk_id="ST_user",
            fallback_trunk_id="ST_shared",
        )
        == "ST_shared"
    )


async def test_buy_provisions_plivo_and_livekit_once(monkeypatch) -> None:
    MemoryPhoneRepo.lines = {}
    MemoryClientRepo.phones = {}
    monkeypatch.setattr(
        "app.services.phone_line_service.PhoneLineRepository", MemoryPhoneRepo
    )
    monkeypatch.setattr(
        "app.services.phone_line_service.ClientRepository", MemoryClientRepo
    )
    plivo = FakePlivo()
    livekit = FakeLiveKit()
    service = _service(plivo, livekit)

    first = await service.buy_and_provision(_client())
    second = await service.buy_and_provision(_client())

    assert first.status == "active"
    assert first.phone_number == "919811122233"
    assert second.phone_number == first.phone_number
    assert plivo.bought == ["919811122233"]
    assert plivo.assigned == [("919811122233", "plivo-in")]
    assert livekit.outbound == ["plivo-out.zt.plivo.com"]
    assert MemoryClientRepo.phones["acme@example.com"] == "919811122233"
    stored = MemoryPhoneRepo.lines[7]
    assert stored.livekit_dispatch_rule_id == "lk-rule"
    assert stored.livekit_outbound_trunk_id == "lk-out"


async def test_retry_does_not_buy_another_number(monkeypatch) -> None:
    MemoryPhoneRepo.lines = {
        7: PhoneLine(
            id=1,
            client_id=7,
            provider="plivo",
            status="failed",
            country_iso="IN",
            phone_number="919811122233",
            phone_number_e164="+919811122233",
            last_error="trunk failed",
        )
    }
    MemoryClientRepo.phones = {}
    monkeypatch.setattr(
        "app.services.phone_line_service.PhoneLineRepository", MemoryPhoneRepo
    )
    monkeypatch.setattr(
        "app.services.phone_line_service.ClientRepository", MemoryClientRepo
    )
    plivo = FakePlivo()
    service = _service(plivo, FakeLiveKit())

    view = await service.buy_and_provision(_client())

    assert view.status == "active"
    assert plivo.bought == []
