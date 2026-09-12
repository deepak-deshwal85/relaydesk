from __future__ import annotations

import logging

from app.domain.client_models import Client
from app.domain.consumer_models import CallAttemptResult, Consumer

logger = logging.getLogger("relaydesk-api")


class SimulatedOutboundCaller:
    async def place_call(
        self,
        *,
        consumer: Consumer,
        client: Client,
        job_id,
        sip_trunk_id: str | None = None,
    ) -> CallAttemptResult:
        detail = (
            f"SIMULATED call from client {client.client_business_phone_number} "
            f"({client.client_name}) to consumer {consumer.consumer_phone_number}. "
            "Configure LiveKit SIP env vars for real dialing."
        )
        logger.warning(detail)
        return CallAttemptResult(
            consumer_id=consumer.id,
            consumer_phone_number=consumer.consumer_phone_number,
            success=True,
            detail=detail,
        )
