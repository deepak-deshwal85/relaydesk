from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.postgres.client_repository import ClientRepository
from app.db.postgres.phone_line_repository import PhoneLineRepository
from app.domain.client_models import Client
from app.domain.consumer_models import format_sip_phone, normalize_phone_number
from app.domain.phone_line_models import PhoneLine
from app.services.livekit_sip_provisioner import LiveKitSipProvisioner
from app.services.plivo_client import PlivoApiError, PlivoClient

logger = logging.getLogger("relaydesk-api")


class PhoneProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhoneLineView:
    status: str
    phone_number: str | None
    phone_number_e164: str | None
    provider: str | None
    message: str
    last_error: str | None = None


class PhoneLineService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        plivo: PlivoClient | None = None,
        livekit: LiveKitSipProvisioner | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._plivo = plivo
        self._livekit = livekit

    async def get_line(self, client: Client) -> PhoneLineView:
        async with self._session_factory() as session:
            line = await PhoneLineRepository(session).get_by_client_id(client.id)
        if line is None:
            return PhoneLineView(
                status="none",
                phone_number=client.client_business_phone_number,
                phone_number_e164=_e164(client.client_business_phone_number),
                provider=None,
                message="No Plivo number is assigned to this user yet.",
            )
        return _view(line)

    async def buy_and_provision(
        self,
        client: Client,
        *,
        country_iso: str | None = None,
        number_type: str | None = None,
    ) -> PhoneLineView:
        self._require_config()
        country = (country_iso or self._settings.plivo_number_country).strip().upper()
        kind = (number_type or self._settings.plivo_number_type).strip().lower()

        async with self._session_factory() as session:
            repository = PhoneLineRepository(session)
            existing = await repository.get_by_client_id(client.id)
            if existing and existing.is_active:
                return _view(existing)
            line = existing or PhoneLine(
                id=None,
                client_id=client.id,
                provider="plivo",
                status="provisioning",
                country_iso=country,
            )
            if existing is None:
                line = await repository.save(line)

        try:
            line = await self._provision(
                client, line, country=country, number_type=kind
            )
        except (PhoneProvisioningError, PlivoApiError) as exc:
            line = line.with_updates(status="failed", last_error=str(exc))
            async with self._session_factory() as session:
                await PhoneLineRepository(session).save(line)
            raise PhoneProvisioningError(str(exc)) from exc

        async with self._session_factory() as session:
            await ClientRepository(session).set_business_phone(
                client_email_id=client.client_email_id,
                client_business_phone_number=line.phone_number or "",
            )
        return _view(line)

    async def _provision(
        self,
        client: Client,
        line: PhoneLine,
        *,
        country: str,
        number_type: str,
    ) -> PhoneLine:
        plivo = self._plivo_client()
        livekit = self._livekit_client()
        label = f"relaydesk-{client.id}"

        if not line.phone_number:
            numbers = await plivo.search_voice_numbers(
                country_iso=country,
                number_type=number_type,
            )
            if not numbers:
                raise PhoneProvisioningError(
                    f"No voice numbers are available for {country} ({number_type}). "
                    "Check Plivo inventory and KYC requirements."
                )
            purchased = numbers[0]
            await plivo.buy_number(purchased)
            digits = normalize_phone_number(purchased)
            line = await self._save(
                line.with_updates(
                    phone_number=digits,
                    phone_number_e164=format_sip_phone(digits),
                    country_iso=country,
                    status="provisioning",
                    last_error=None,
                )
            )
            logger.info(
                "purchased plivo number client_id=%s number=%s",
                client.id,
                digits,
            )

        sip_host = _sip_host(self._settings.livekit_sip_host or "")
        if not line.plivo_origination_uri_uuid:
            uri_uuid = await plivo.create_origination_uri(
                name=f"{label}-livekit",
                uri=f"{sip_host};transport=tcp",
            )
            line = await self._save(
                line.with_updates(plivo_origination_uri_uuid=uri_uuid)
            )

        if not line.plivo_inbound_trunk_id:
            trunk_id = await plivo.create_inbound_trunk(
                name=f"{label}-inbound",
                uri_uuid=line.plivo_origination_uri_uuid or "",
            )
            line = await self._save(line.with_updates(plivo_inbound_trunk_id=trunk_id))

        await plivo.assign_number_to_trunk(
            line.phone_number or "",
            line.plivo_inbound_trunk_id or "",
        )

        if (
            not line.plivo_credential_uuid
            or not line.sip_username
            or not line.sip_password
        ):
            username, password = generate_sip_credentials(client.id)
            credential_uuid = await plivo.create_credential(
                name=f"{label}-outbound",
                username=username,
                password=password,
            )
            line = await self._save(
                line.with_updates(
                    plivo_credential_uuid=credential_uuid,
                    sip_username=username,
                    sip_password=password,
                )
            )

        if not line.plivo_outbound_trunk_id:
            outbound_id = await plivo.create_outbound_trunk(
                name=f"{label}-outbound",
                credential_uuid=line.plivo_credential_uuid or "",
            )
            line = await self._save(
                line.with_updates(plivo_outbound_trunk_id=outbound_id)
            )

        if not line.plivo_outbound_domain:
            domain = await plivo.get_trunk_domain(line.plivo_outbound_trunk_id or "")
            line = await self._save(line.with_updates(plivo_outbound_domain=domain))

        e164 = line.phone_number_e164 or format_sip_phone(line.phone_number or "")
        if not line.livekit_inbound_trunk_id:
            inbound_id = await livekit.create_inbound_trunk(
                name=f"{label}-inbound",
                e164_number=e164,
            )
            line = await self._save(
                line.with_updates(livekit_inbound_trunk_id=inbound_id)
            )

        if not line.livekit_dispatch_rule_id:
            rule_id = await livekit.create_dispatch_rule(
                name=f"{label}-dispatch",
                inbound_trunk_id=line.livekit_inbound_trunk_id or "",
                e164_number=e164,
                client_email_id=client.client_email_id,
                client_name=client.client_name,
            )
            line = await self._save(line.with_updates(livekit_dispatch_rule_id=rule_id))

        if not line.livekit_outbound_trunk_id:
            outbound_id = await livekit.create_outbound_trunk(
                name=f"{label}-outbound",
                address=line.plivo_outbound_domain or "",
                e164_number=e164,
                username=line.sip_username or "",
                password=line.sip_password or "",
            )
            line = await self._save(
                line.with_updates(livekit_outbound_trunk_id=outbound_id)
            )

        return await self._save(
            line.with_updates(status="active", last_error=None, phone_number_e164=e164)
        )

    async def _save(self, line: PhoneLine) -> PhoneLine:
        async with self._session_factory() as session:
            return await PhoneLineRepository(session).save(line)

    def _require_config(self) -> None:
        missing = []
        if not self._settings.plivo_auth_id or not self._settings.plivo_auth_token:
            missing.append("PLIVO_AUTH_ID/PLIVO_AUTH_TOKEN")
        if not self._settings.livekit_configured:
            missing.append("LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET")
        if not self._settings.livekit_sip_host:
            missing.append("LIVEKIT_SIP_HOST")
        if missing:
            raise PhoneProvisioningError(
                "Phone purchase is not configured. Set " + ", ".join(missing) + "."
            )

    def _plivo_client(self) -> PlivoClient:
        if self._plivo is not None:
            return self._plivo
        return PlivoClient(
            self._settings.plivo_auth_id or "",
            self._settings.plivo_auth_token or "",
        )

    def _livekit_client(self) -> LiveKitSipProvisioner:
        if self._livekit is not None:
            return self._livekit
        return LiveKitSipProvisioner(
            url=self._settings.livekit_url or "",
            api_key=self._settings.livekit_api_key or "",
            api_secret=self._settings.livekit_api_secret or "",
            agent_name=self._settings.livekit_agent_name,
        )


def generate_sip_credentials(client_id: int) -> tuple[str, str]:
    username = f"lk{client_id}{secrets.token_hex(4)}"[:20]
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(11))
    password += secrets.choice("!@#$%^*_+")
    return username, password


def resolve_outbound_trunk_id(
    *,
    line_status: str | None,
    line_trunk_id: str | None,
    fallback_trunk_id: str | None,
) -> str | None:
    if line_status == "active" and line_trunk_id:
        return line_trunk_id
    return fallback_trunk_id


def _sip_host(value: str) -> str:
    host = value.strip()
    if host.lower().startswith("sip:"):
        host = host[4:]
    return host.split(";", 1)[0].split("/", 1)[0]


def _e164(number: str | None) -> str | None:
    if not number:
        return None
    return format_sip_phone(number)


def _view(line: PhoneLine) -> PhoneLineView:
    if line.status == "active":
        message = (
            f"Business number {line.phone_number_e164 or line.phone_number} is ready. "
            "Outbound campaigns will call from this number."
        )
        if line.country_iso.upper() == "IN":
            message += " India calling requires LiveKit region pinning."
    elif line.status == "failed":
        message = line.last_error or "Number setup failed. Try again to resume."
    else:
        message = (
            "Number setup is incomplete. Try again to finish wiring Plivo and LiveKit."
        )
    return PhoneLineView(
        status=line.status,
        phone_number=line.phone_number,
        phone_number_e164=line.phone_number_e164,
        provider=line.provider,
        message=message,
        last_error=line.last_error,
    )
