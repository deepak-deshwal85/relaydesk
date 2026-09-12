from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres.models import ClientPhoneLineRow
from app.domain.phone_line_models import PhoneLine


class PhoneLineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: ClientPhoneLineRow) -> PhoneLine:
        return PhoneLine(
            id=row.id,
            client_id=row.client_id,
            provider=row.provider,
            status=row.status,
            country_iso=row.country_iso,
            phone_number=row.phone_number,
            phone_number_e164=row.phone_number_e164,
            plivo_origination_uri_uuid=row.plivo_origination_uri_uuid,
            plivo_inbound_trunk_id=row.plivo_inbound_trunk_id,
            plivo_credential_uuid=row.plivo_credential_uuid,
            plivo_outbound_trunk_id=row.plivo_outbound_trunk_id,
            plivo_outbound_domain=row.plivo_outbound_domain,
            sip_username=row.sip_username,
            sip_password=row.sip_password,
            livekit_inbound_trunk_id=row.livekit_inbound_trunk_id,
            livekit_outbound_trunk_id=row.livekit_outbound_trunk_id,
            livekit_dispatch_rule_id=row.livekit_dispatch_rule_id,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get_by_client_id(self, client_id: int) -> PhoneLine | None:
        row = (
            await self._session.execute(
                select(ClientPhoneLineRow).where(ClientPhoneLineRow.client_id == client_id)
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, line: PhoneLine) -> PhoneLine:
        row = None
        if line.id is not None:
            row = await self._session.get(ClientPhoneLineRow, line.id)
        if row is None:
            row = (
                await self._session.execute(
                    select(ClientPhoneLineRow).where(
                        ClientPhoneLineRow.client_id == line.client_id
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            row = ClientPhoneLineRow(client_id=line.client_id, provider=line.provider)
            self._session.add(row)

        row.provider = line.provider
        row.status = line.status
        row.country_iso = line.country_iso
        row.phone_number = line.phone_number
        row.phone_number_e164 = line.phone_number_e164
        row.plivo_origination_uri_uuid = line.plivo_origination_uri_uuid
        row.plivo_inbound_trunk_id = line.plivo_inbound_trunk_id
        row.plivo_credential_uuid = line.plivo_credential_uuid
        row.plivo_outbound_trunk_id = line.plivo_outbound_trunk_id
        row.plivo_outbound_domain = line.plivo_outbound_domain
        row.sip_username = line.sip_username
        row.sip_password = line.sip_password
        row.livekit_inbound_trunk_id = line.livekit_inbound_trunk_id
        row.livekit_outbound_trunk_id = line.livekit_outbound_trunk_id
        row.livekit_dispatch_rule_id = line.livekit_dispatch_rule_id
        row.last_error = line.last_error

        await self._session.commit()
        await self._session.refresh(row)
        return self._to_domain(row)
