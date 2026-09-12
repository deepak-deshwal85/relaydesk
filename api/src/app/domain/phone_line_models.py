from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime


@dataclass
class PhoneLine:
    id: int | None
    client_id: int
    provider: str
    status: str
    country_iso: str
    phone_number: str | None = None
    phone_number_e164: str | None = None
    plivo_origination_uri_uuid: str | None = None
    plivo_inbound_trunk_id: str | None = None
    plivo_credential_uuid: str | None = None
    plivo_outbound_trunk_id: str | None = None
    plivo_outbound_domain: str | None = None
    sip_username: str | None = None
    sip_password: str | None = None
    livekit_inbound_trunk_id: str | None = None
    livekit_outbound_trunk_id: str | None = None
    livekit_dispatch_rule_id: str | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active" and bool(self.livekit_outbound_trunk_id)

    def with_updates(self, **changes: object) -> PhoneLine:
        return replace(self, **changes)
