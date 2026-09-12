from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import (
    get_client_repository,
    get_phone_line_service,
    require_permission,
)
from app.core.oauth import AuthenticatedPrincipal
from app.core.rbac import Permission
from app.core.tenant import verify_client_email_scope
from app.db.postgres.client_repository import ClientRepository
from app.schemas.phone_lines import BuyPhoneLineRequest, PhoneLineResponse
from app.services.phone_line_service import PhoneLineService, PhoneProvisioningError

router = APIRouter(
    prefix="/v1/phone-lines",
    tags=["phone-lines"],
    dependencies=[Depends(require_permission(Permission.DOCUMENT_WRITE))],
)


def _to_response(view) -> PhoneLineResponse:
    return PhoneLineResponse(
        status=view.status,
        phone_number=view.phone_number,
        phone_number_e164=view.phone_number_e164,
        provider=view.provider,
        message=view.message,
        last_error=view.last_error,
    )


@router.get("", response_model=PhoneLineResponse)
async def get_phone_line(
    client_email_id: str,
    service: Annotated[PhoneLineService, Depends(get_phone_line_service)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_permission(Permission.DOCUMENT_WRITE))
    ],
) -> PhoneLineResponse:
    scoped_email = await verify_client_email_scope(
        principal, client_email_id, repository
    )
    client = await repository.get_by_email(scoped_email)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return _to_response(await service.get_line(client))


@router.post(
    "/buy", response_model=PhoneLineResponse, status_code=status.HTTP_201_CREATED
)
async def buy_phone_line(
    client_email_id: str,
    service: Annotated[PhoneLineService, Depends(get_phone_line_service)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_permission(Permission.DOCUMENT_WRITE))
    ],
    body: BuyPhoneLineRequest | None = None,
) -> PhoneLineResponse:
    scoped_email = await verify_client_email_scope(
        principal, client_email_id, repository
    )
    client = await repository.get_by_email(scoped_email)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    payload = body or BuyPhoneLineRequest()
    try:
        view = await service.buy_and_provision(
            client,
            country_iso=payload.country_iso,
            number_type=payload.number_type,
        )
    except PhoneProvisioningError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_response(view)
