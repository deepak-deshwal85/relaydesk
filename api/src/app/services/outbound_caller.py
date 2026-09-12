from __future__ import annotations

import logging
from uuid import UUID

from app.core.config import Settings
from app.domain.client_models import Client
from app.domain.consumer_models import CallAttemptResult, Consumer
from app.services.livekit_outbound_caller import LiveKitOutboundCaller
from app.services.simulated_outbound_caller import SimulatedOutboundCaller

logger = logging.getLogger("relaydesk-api")


class OutboundCaller:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if settings.livekit_configured:
            self._inner = LiveKitOutboundCaller(settings)
            logger.info(
                "outbound caller mode=livekit agent=%s fallback_trunk=%s",
                settings.livekit_agent_name,
                settings.livekit_sip_outbound_trunk_id or "none",
            )
        else:
            self._inner = SimulatedOutboundCaller()
            logger.warning(
                "outbound caller mode=simulated — set LIVEKIT_URL, LIVEKIT_API_KEY, "
                "LIVEKIT_API_SECRET, and LIVEKIT_SIP_OUTBOUND_TRUNK_ID for real calls"
            )

    async def place_call(
        self,
        *,
        consumer: Consumer,
        client: Client,
        job_id: UUID,
        sip_trunk_id: str | None = None,
    ) -> CallAttemptResult:
        return await self._inner.place_call(
            consumer=consumer,
            client=client,
            job_id=job_id,
            sip_trunk_id=sip_trunk_id,
        )


def build_outbound_caller(settings: Settings) -> OutboundCaller:
    return OutboundCaller(settings)
