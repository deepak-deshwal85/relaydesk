from __future__ import annotations

from typing import Any

import httpx


class PlivoApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PlivoClient:
    def __init__(self, auth_id: str, auth_token: str, *, timeout: float = 30.0) -> None:
        self._auth_id = auth_id
        self._auth_token = auth_token
        self._timeout = timeout
        self._base = f"https://api.plivo.com/v1/Account/{auth_id}"

    async def search_voice_numbers(
        self,
        *,
        country_iso: str,
        number_type: str,
        limit: int = 5,
    ) -> list[str]:
        payload = await self._request(
            "GET",
            "/PhoneNumber/",
            params={
                "country_iso": country_iso.upper(),
                "type": number_type,
                "services": "voice",
                "limit": min(max(limit, 1), 20),
            },
        )
        objects = payload.get("objects") or []
        numbers: list[str] = []
        for item in objects:
            if not isinstance(item, dict):
                continue
            if item.get("voice_enabled") is False:
                continue
            number = str(item.get("number") or "").strip()
            if number:
                numbers.append(number)
        return numbers

    async def buy_number(self, number: str) -> dict[str, Any]:
        return await self._request("POST", f"/PhoneNumber/{_digits(number)}/")

    async def assign_number_to_trunk(
        self, number: str, trunk_id: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/Number/{_digits(number)}/",
            json={"app_id": trunk_id},
        )

    async def create_origination_uri(self, *, name: str, uri: str) -> str:
        payload = await self._request(
            "POST",
            "/Zentrunk/URI/",
            json={"name": name, "uri": uri},
        )
        return _require_id(payload, "uri_uuid")

    async def create_inbound_trunk(self, *, name: str, uri_uuid: str) -> str:
        payload = await self._request(
            "POST",
            "/Zentrunk/Trunk/",
            json={
                "name": name,
                "trunk_direction": "inbound",
                "primary_uri_uuid": uri_uuid,
            },
        )
        return _require_id(payload, "trunk_id")

    async def create_credential(
        self, *, name: str, username: str, password: str
    ) -> str:
        payload = await self._request(
            "POST",
            "/Zentrunk/Credential/",
            json={"name": name, "username": username, "password": password},
        )
        return _require_id(payload, "credential_uuid")

    async def create_outbound_trunk(self, *, name: str, credential_uuid: str) -> str:
        payload = await self._request(
            "POST",
            "/Zentrunk/Trunk/",
            json={
                "name": name,
                "trunk_direction": "outbound",
                "credential_uuid": credential_uuid,
                "secure": True,
            },
        )
        return _require_id(payload, "trunk_id")

    async def get_trunk_domain(self, trunk_id: str) -> str:
        payload = await self._request("GET", f"/Zentrunk/Trunk/{trunk_id}/")
        domain = _lookup(payload, "trunk_domain")
        if domain:
            return domain
        return f"{trunk_id}.zt.plivo.com"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(
                method,
                f"{self._base}{path}",
                auth=(self._auth_id, self._auth_token),
                params=params,
                json=json,
                headers={"Accept": "application/json"},
            )
        if response.status_code >= 400:
            raise PlivoApiError(
                _error_message(response),
                status_code=response.status_code,
            )
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"objects": data}


def _digits(number: str) -> str:
    return number.strip().lstrip("+")


def _lookup(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value:
        return str(value)
    nested = payload.get("object")
    if isinstance(nested, dict) and nested.get(key):
        return str(nested[key])
    return None


def _require_id(payload: dict[str, Any], key: str) -> str:
    value = _lookup(payload, key)
    if not value:
        raise PlivoApiError(f"Plivo response did not include {key}")
    return value


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"Plivo request failed ({response.status_code})"
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return f"Plivo request failed ({response.status_code})"
