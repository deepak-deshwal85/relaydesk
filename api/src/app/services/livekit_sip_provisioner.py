from __future__ import annotations

import json

from livekit import api


class LiveKitSipProvisioner:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        api_secret: str,
        agent_name: str,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._agent_name = agent_name

    async def create_inbound_trunk(self, *, name: str, e164_number: str) -> str:
        async with self._client() as lk:
            created = await lk.sip.create_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name=name,
                        numbers=[e164_number],
                    )
                )
            )
        return created.sip_trunk_id

    async def create_dispatch_rule(
        self,
        *,
        name: str,
        inbound_trunk_id: str,
        e164_number: str,
        client_email_id: str,
        client_name: str,
    ) -> str:
        metadata = json.dumps(
            {
                "call_type": "inbound",
                "client_email_id": client_email_id,
                "client_business_phone_number": e164_number,
                "client_name": client_name,
            }
        )
        async with self._client() as lk:
            created = await lk.sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    dispatch_rule=api.SIPDispatchRuleInfo(
                        name=name,
                        trunk_ids=[inbound_trunk_id],
                        inbound_numbers=[e164_number],
                        rule=api.SIPDispatchRule(
                            dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                                room_prefix="inbound-",
                            )
                        ),
                        room_config=api.RoomConfiguration(
                            agents=[
                                api.RoomAgentDispatch(
                                    agent_name=self._agent_name,
                                    metadata=metadata,
                                )
                            ]
                        ),
                    )
                )
            )
        return created.sip_dispatch_rule_id

    async def create_outbound_trunk(
        self,
        *,
        name: str,
        address: str,
        e164_number: str,
        username: str,
        password: str,
    ) -> str:
        async with self._client() as lk:
            created = await lk.sip.create_outbound_trunk(
                api.CreateSIPOutboundTrunkRequest(
                    trunk=api.SIPOutboundTrunkInfo(
                        name=name,
                        address=address,
                        numbers=[e164_number],
                        auth_username=username,
                        auth_password=password,
                        transport=api.SIPTransport.SIP_TRANSPORT_TLS,
                        media_encryption=api.SIPMediaEncryption.SIP_MEDIA_ENCRYPT_REQUIRE,
                    )
                )
            )
        return created.sip_trunk_id

    def _client(self) -> api.LiveKitAPI:
        return api.LiveKitAPI(self._url, self._api_key, self._api_secret)
