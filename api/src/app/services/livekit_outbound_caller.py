from __future__ import annotations

import json
import logging
from uuid import UUID

from livekit import api

from app.core.config import Settings
from app.domain.client_models import Client
from app.domain.consumer_models import CallAttemptResult, Consumer, format_sip_phone

logger = logging.getLogger("relaydesk-api")


class LiveKitOutboundCaller:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def place_call(
        self,
        *,
        consumer: Consumer,
        client: Client,
        job_id: UUID,
        sip_trunk_id: str | None = None,
    ) -> CallAttemptResult:
        room_name = f"outbound-{job_id}-{consumer.id}"
        consumer_phone = format_sip_phone(consumer.consumer_phone_number)
        metadata = json.dumps(
            {
                "call_type": "outbound",
                "client_email_id": client.client_email_id,
                "client_business_phone_number": client.client_business_phone_number
                or "",
                "client_name": client.client_name,
                "consumer_phone_number": consumer.consumer_phone_number,
                "consumer_id": consumer.id,
                "job_id": str(job_id),
            }
        )

        logger.info(
            "dialing consumer job_id=%s client=%s (%s) consumer=%s room=%s",
            job_id,
            client.client_business_phone_number,
            client.client_name,
            consumer_phone,
            room_name,
        )

        trunk_id = sip_trunk_id or self._settings.livekit_sip_outbound_trunk_id
        if not trunk_id:
            return CallAttemptResult(
                consumer_id=consumer.id,
                consumer_phone_number=consumer.consumer_phone_number,
                success=False,
                detail=(
                    "No LiveKit outbound trunk is configured for this client. "
                    "Buy a business number first."
                ),
            )
        caller_id = ""
        if client.client_business_phone_number:
            caller_id = format_sip_phone(client.client_business_phone_number)

        try:
            async with api.LiveKitAPI(
                self._settings.livekit_url,
                self._settings.livekit_api_key,
                self._settings.livekit_api_secret,
            ) as lk:
                await lk.agent_dispatch.create_dispatch(
                    api.CreateAgentDispatchRequest(
                        agent_name=self._settings.livekit_agent_name,
                        room=room_name,
                        metadata=metadata,
                    )
                )
                logger.info(
                    "agent dispatch created room=%s agent=%s",
                    room_name,
                    self._settings.livekit_agent_name,
                )

                participant = api.CreateSIPParticipantRequest(
                    room_name=room_name,
                    sip_trunk_id=trunk_id,
                    sip_call_to=consumer_phone,
                    participant_identity=f"consumer-{consumer.id}",
                    participant_name=client.client_name,
                    wait_until_answered=False,
                )
                if caller_id:
                    participant.sip_number = caller_id
                await lk.sip.create_sip_participant(participant)

            detail = (
                f"LiveKit outbound call initiated from client "
                f"{client.client_business_phone_number} to {consumer_phone} in room {room_name}"
            )
            logger.info(detail)
            return CallAttemptResult(
                consumer_id=consumer.id,
                consumer_phone_number=consumer.consumer_phone_number,
                success=True,
                detail=detail,
            )
        except Exception as exc:
            logger.exception(
                "livekit outbound call failed job_id=%s consumer_id=%s",
                job_id,
                consumer.id,
            )
            return CallAttemptResult(
                consumer_id=consumer.id,
                consumer_phone_number=consumer.consumer_phone_number,
                success=False,
                detail=str(exc),
            )
