from __future__ import annotations

from pydantic import BaseModel, Field


class BuyPhoneLineRequest(BaseModel):
    country_iso: str | None = Field(default=None, min_length=2, max_length=2)
    number_type: str | None = Field(default=None, min_length=3, max_length=16)


class PhoneLineResponse(BaseModel):
    status: str
    phone_number: str | None
    phone_number_e164: str | None
    provider: str | None
    message: str
    last_error: str | None = None
