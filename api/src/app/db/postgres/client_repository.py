from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres.models import CallJobRow, ClientRow, ConsumerRow
from app.domain.client_models import Client
from app.domain.consumer_models import normalize_email, normalize_phone_number
from app.domain.phone_validation import normalize_optional_phone_number

logger = logging.getLogger("relaydesk-api")


class ClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(row: ClientRow) -> Client:
        return Client(
            id=row.id,
            client_phone_number=row.client_phone_number,
            client_business_phone_number=row.client_business_phone_number,
            client_name=row.client_name,
            client_email_id=row.client_email_id,
            created_at=row.created_at,
        )

    async def get_by_business_phone(self, phone_number: str) -> Client | None:
        normalized = normalize_phone_number(phone_number)
        rows = (
            await self._session.execute(
                select(ClientRow)
                .where(ClientRow.client_business_phone_number == normalized)
                .order_by(ClientRow.id.asc())
                .limit(2)
            )
        ).scalars().all()
        if not rows:
            return None
        if len(rows) > 1:
            logger.warning(
                "multiple clients share business phone %s; using client_id=%s email=%s",
                normalized,
                rows[0].id,
                rows[0].client_email_id,
            )
        return self._to_domain(rows[0])

    async def get_by_email(self, client_email_id: str) -> Client | None:
        row = (
            await self._session.execute(
                select(ClientRow).where(
                    ClientRow.client_email_id == normalize_email(client_email_id)
                )
            )
        ).scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_id(self, client_id: int) -> Client | None:
        row = await self._session.get(ClientRow, client_id)
        return self._to_domain(row) if row else None

    async def ensure_on_sign_in(
        self,
        *,
        client_email_id: str,
    ) -> Client:
        normalized_email = normalize_email(client_email_id)
        row = (
            await self._session.execute(
                select(ClientRow).where(ClientRow.client_email_id == normalized_email)
            )
        ).scalar_one_or_none()

        if row is None:
            row = ClientRow(
                client_phone_number=None,
                client_business_phone_number=None,
                client_name="",
                client_email_id=normalized_email,
            )
            self._session.add(row)
            await self._session.commit()
            await self._session.refresh(row)
        return self._to_domain(row)

    async def upsert_personal_profile(
        self,
        *,
        client_name: str,
        client_phone_number: str | None,
        client_email_id: str,
    ) -> Client:
        normalized_email = normalize_email(client_email_id)
        normalized_personal_phone = normalize_optional_phone_number(client_phone_number)
        name = client_name.strip()
        if not name:
            raise ValueError("client_name is required")

        row = (
            await self._session.execute(
                select(ClientRow).where(ClientRow.client_email_id == normalized_email)
            )
        ).scalar_one_or_none()

        if row is None:
            row = ClientRow(
                client_phone_number=normalized_personal_phone,
                client_business_phone_number=None,
                client_name=name,
                client_email_id=normalized_email,
            )
            self._session.add(row)
        else:
            row.client_name = name
            row.client_phone_number = normalized_personal_phone

        await self._session.commit()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def set_business_phone(
        self,
        *,
        client_email_id: str,
        client_business_phone_number: str,
    ) -> Client:
        normalized_email = normalize_email(client_email_id)
        normalized_business_phone = normalize_phone_number(client_business_phone_number)

        row = (
            await self._session.execute(
                select(ClientRow).where(ClientRow.client_email_id == normalized_email)
            )
        ).scalar_one_or_none()

        if row is None:
            row = ClientRow(
                client_phone_number=None,
                client_business_phone_number=normalized_business_phone,
                client_name="",
                client_email_id=normalized_email,
            )
            self._session.add(row)
        else:
            row.client_business_phone_number = normalized_business_phone

        await self._session.commit()
        await self._session.refresh(row)
        return self._to_domain(row)

    async def list_all(self) -> list[Client]:
        rows = (
            await self._session.execute(
                select(ClientRow).order_by(ClientRow.client_email_id)
            )
        ).scalars().all()
        return [self._to_domain(row) for row in rows]

    async def delete_by_email(self, client_email_id: str) -> tuple[int, int] | None:
        """Delete client row and related consumers/call jobs. Returns counts or None."""
        normalized = normalize_email(client_email_id)
        row = (
            await self._session.execute(
                select(ClientRow).where(ClientRow.client_email_id == normalized)
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        consumers_result = await self._session.execute(
            delete(ConsumerRow).where(ConsumerRow.client_id == row.id)
        )
        call_jobs_result = await self._session.execute(
            delete(CallJobRow).where(CallJobRow.client_id == row.id)
        )
        await self._session.execute(
            delete(ClientRow).where(ClientRow.client_email_id == normalized)
        )
        await self._session.commit()
        return (
            int(consumers_result.rowcount or 0),
            int(call_jobs_result.rowcount or 0),
        )
