from __future__ import annotations

import logging
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request
from fastapi import status as http_status
from fastapi import UploadFile

from app.core.collections import collection_from_email
from app.core.config import Settings, get_settings
from app.core.dependencies import (
    get_call_job_service,
    get_call_summary_service,
    get_document_service,
    get_client_repository,
    get_client_service,
    get_client_voice_agent_config_service,
    get_collection_service,
    get_consumer_service,
    get_search_service,
    get_voice_agent_schedule_service,
    require_permission,
    verify_access_token,
)
from app.core.oauth import AuthenticatedPrincipal
from app.core.qdrant_errors import is_qdrant_connection_error, qdrant_unavailable_detail
from app.core.rbac import Permission
from app.core.tenant import is_scope_unrestricted, principal_email, resolve_mobile_client_email
from app.db.postgres.client_repository import ClientRepository
from app.schemas.call_jobs import CallJobListResponse, CallJobResponse, TriggerCallJobResponse
from app.schemas.call_summaries import (
    CallSummaryCreateRequest,
    CallSummaryListResponse,
    CallSummaryResponse,
)
from app.schemas.clients import (
    ClientApproveRequest,
    ClientAdminListResponse,
    ClientAdminProfileResponse,
    ClientDeleteResponse,
    ClientProfileResponse,
    ClientProfileUpsertRequest,
)
from app.schemas.collections import (
    CollectionDeleteResponse,
    CollectionInfoResponse,
    CollectionListResponse,
)
from app.schemas.consumers import (
    ConsumerCreateRequest,
    ConsumerListResponse,
    ConsumerResponse,
    ConsumerUpdateRequest,
)
from app.schemas.documents import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentSummaryResponse,
    DocumentUploadResponse,
)
from app.schemas.mobile import MobileSessionResponse
from app.schemas.search import SearchHitResponse, SearchRequest, SearchResponse
from app.schemas.voice_agent_config import VoiceAgentConfigResponse, VoiceAgentConfigUpdateRequest
from app.schemas.voice_agent_schedules import (
    VoiceAgentScheduleOverviewResponse,
    VoiceAgentScheduleTriggerResponse,
    VoiceAgentScheduleUpdateRequest,
)
from app.services.call_job_service import CallJobService
from app.services.call_summary_service import CallSummaryService
from app.services.client_service import ClientService
from app.services.client_voice_agent_config_service import ClientVoiceAgentConfigService
from app.services.collection_service import CollectionService
from app.services.consumer_service import ConsumerService
from app.services.document_service import DocumentService
from app.services.search_service import SearchService
from app.services.voice_agent_schedule_service import VoiceAgentScheduleService

logger = logging.getLogger("relaydesk-api")

router = APIRouter(
    prefix="/v1/mobile",
    tags=["mobile"],
    dependencies=[Depends(verify_access_token)],
)


async def _resolve_client_context(
    request: Request,
    principal: AuthenticatedPrincipal,
    repository: ClientRepository,
    client_email_id: str | None,
) -> tuple[str, str]:
    resolved_email = await resolve_mobile_client_email(
        principal,
        repository,
        client_email_id=client_email_id,
        session_email=request.headers.get("x-relaydesk-user-email"),
    )
    return resolved_email, collection_from_email(resolved_email)


@router.get("/me", response_model=MobileSessionResponse)
async def get_mobile_session(
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    service: Annotated[ClientService, Depends(get_client_service)],
    selected_client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> MobileSessionResponse:
    if principal.is_m2m:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Mobile session is not available for machine clients",
        )

    clients: list[ClientAdminProfileResponse]
    selected_client: ClientProfileResponse | None = None

    if is_scope_unrestricted(principal):
        admin_clients = await service.list_clients_admin()
        clients = admin_clients.clients
        selected_email = (
            selected_client_email_id.strip().lower() if selected_client_email_id else None
        )
        if not selected_email and clients:
            selected_email = clients[0].client_email_id
        if selected_email:
            profile = await service.get_profile(selected_email)
            selected_client = profile
    else:
        email = principal_email(principal)
        if not email:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Authenticated user email is required",
            )
        profile = await service.ensure_on_sign_in(client_email_id=email)
        clients = [
            ClientAdminProfileResponse(
                **profile.model_dump(),
                is_approved=bool(profile.client_business_phone_number),
            )
        ]
        selected_client = profile

    return MobileSessionResponse(
        user_email=principal_email(principal),
        role=getattr(principal.role, "value", principal.role) if principal.role else None,
        is_admin=bool(principal.has_permission(Permission.ADMIN)),
        is_guest=principal.role is None or not principal.has_permission(Permission.DOCUMENT_WRITE),
        can_upload_documents=principal.has_permission(Permission.DOCUMENT_WRITE),
        can_manage_data=principal.has_permission(Permission.ADMIN),
        clients=clients,
        selected_client=selected_client,
    )


@router.get("/clients", response_model=ClientAdminListResponse)
async def mobile_list_clients(
    service: Annotated[ClientService, Depends(get_client_service)],
    _principal: Annotated[object, Depends(require_permission(Permission.ADMIN))] = ...,
) -> ClientAdminListResponse:
    return await service.list_clients_admin()


@router.post("/clients/approve", response_model=ClientAdminProfileResponse)
async def mobile_approve_client(
    body: ClientApproveRequest,
    service: Annotated[ClientService, Depends(get_client_service)],
    _principal: Annotated[object, Depends(require_permission(Permission.ADMIN))] = ...,
) -> ClientAdminProfileResponse:
    try:
        return await service.approve_client(
            client_email_id=body.client_email_id.strip().lower(),
            client_business_phone_number=body.client_business_phone_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/clients/{client_email_id}", response_model=ClientDeleteResponse)
async def mobile_delete_client(
    client_email_id: str,
    service: Annotated[ClientService, Depends(get_client_service)],
    _principal: Annotated[object, Depends(require_permission(Permission.ADMIN))] = ...,
) -> ClientDeleteResponse:
    try:
        return await service.delete_client(client_email_id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc


@router.get("/profile", response_model=ClientProfileResponse)
async def get_mobile_profile(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    service: Annotated[ClientService, Depends(get_client_service)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> ClientProfileResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    profile = await service.get_profile(resolved_email)
    if profile is None:
        raise HTTPException(status_code=404, detail="Client profile not found")
    return profile


@router.put("/profile", response_model=ClientProfileResponse)
async def update_mobile_profile(
    request: Request,
    body: ClientProfileUpsertRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    service: Annotated[ClientService, Depends(get_client_service)],
) -> ClientProfileResponse:
    if principal.is_m2m:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Client profile is not available for machine clients",
        )
    if is_scope_unrestricted(principal):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Admin users cannot update client profiles from this endpoint",
        )
    resolved_email, _collection = await _resolve_client_context(
        request,
        principal,
        repository,
        None,
    )
    try:
        return await service.upsert_profile(body, client_email_id=resolved_email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/consumers", response_model=ConsumerListResponse)
async def mobile_list_consumers(
    request: Request,
    service: Annotated[ConsumerService, Depends(get_consumer_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ConsumerListResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    consumers = await service.list(client_id=client.id, skip=skip, limit=limit)
    return ConsumerListResponse(consumers=consumers, count=len(consumers))


@router.post("/consumers", response_model=ConsumerResponse, status_code=http_status.HTTP_201_CREATED)
async def mobile_create_consumer(
    request: Request,
    body: ConsumerCreateRequest,
    service: Annotated[ConsumerService, Depends(get_consumer_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> ConsumerResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    if not client.client_business_phone_number:
        raise HTTPException(status_code=400, detail="Client business phone number is not configured")
    try:
        return await service.create(client, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/consumers/{consumer_id}", response_model=ConsumerResponse)
async def mobile_get_consumer(
    consumer_id: int,
    request: Request,
    service: Annotated[ConsumerService, Depends(get_consumer_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> ConsumerResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    consumer = await service.get(consumer_id, client_id=client.id)
    if consumer is None:
        raise HTTPException(status_code=404, detail="Consumer not found")
    return consumer


@router.put("/consumers/{consumer_id}", response_model=ConsumerResponse)
async def mobile_update_consumer(
    consumer_id: int,
    request: Request,
    body: ConsumerUpdateRequest,
    service: Annotated[ConsumerService, Depends(get_consumer_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> ConsumerResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    try:
        consumer = await service.update(consumer_id, client_id=client.id, body=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if consumer is None:
        raise HTTPException(status_code=404, detail="Consumer not found")
    return consumer


@router.delete("/consumers/{consumer_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def mobile_delete_consumer(
    consumer_id: int,
    request: Request,
    service: Annotated[ConsumerService, Depends(get_consumer_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> None:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    deleted = await service.delete(consumer_id, client_id=client.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Consumer not found")


@router.get("/call-summaries", response_model=CallSummaryListResponse)
async def mobile_list_call_summaries(
    request: Request,
    service: Annotated[CallSummaryService, Depends(get_call_summary_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
    consumer_id: Annotated[int | None, Query(ge=1)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CallSummaryListResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    summaries = await service.list(
        client_id=client.id,
        consumer_id=consumer_id,
        skip=skip,
        limit=limit,
    )
    return CallSummaryListResponse(summaries=summaries, count=len(summaries))


@router.post("/call-summaries", response_model=CallSummaryResponse, status_code=http_status.HTTP_201_CREATED)
async def mobile_create_call_summary(
    request: Request,
    body: CallSummaryCreateRequest,
    service: Annotated[CallSummaryService, Depends(get_call_summary_service)],
    consumer_service: Annotated[ConsumerService, Depends(get_consumer_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> CallSummaryResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    consumer = await consumer_service.get(body.consumer_id, client_id=client.id)
    if consumer is None:
        raise HTTPException(status_code=404, detail="Consumer not found")
    try:
        return await service.create(client_id=client.id, body=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/call-summaries/{summary_id}", response_model=CallSummaryResponse)
async def mobile_get_call_summary(
    summary_id: int,
    request: Request,
    service: Annotated[CallSummaryService, Depends(get_call_summary_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> CallSummaryResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    summary = await service.get(summary_id, client_id=client.id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Call summary not found")
    return summary


@router.get("/call-jobs", response_model=CallJobListResponse)
async def mobile_list_call_jobs(
    request: Request,
    service: Annotated[CallJobService, Depends(get_call_job_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CallJobListResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    jobs = await service.list_jobs(client_id=client.id, limit=limit)
    return CallJobListResponse(jobs=jobs, count=len(jobs))


@router.get("/call-jobs/{job_id}", response_model=CallJobResponse)
async def mobile_get_call_job(
    job_id: UUID,
    request: Request,
    service: Annotated[CallJobService, Depends(get_call_job_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> CallJobResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    job = await service.get_job(job_id, client_id=client.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Call job not found")
    return job


@router.post("/call-jobs/trigger", response_model=TriggerCallJobResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def mobile_trigger_call_job(
    request: Request,
    background_tasks: BackgroundTasks,
    service: Annotated[CallJobService, Depends(get_call_job_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> TriggerCallJobResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    if not client.client_business_phone_number:
        raise HTTPException(status_code=400, detail="Client business phone number is not configured")
    try:
        job = await service.create_job(client.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(service.run_job, job.id)
    return TriggerCallJobResponse(
        job_id=job.id,
        status=job.status,
        message=(
            f"Campaign queued for client {client.client_business_phone_number}. "
            f"Poll GET /v1/mobile/call-jobs/{job.id} for status."
        ),
    )


@router.get("/voice-agent-config", response_model=VoiceAgentConfigResponse)
async def mobile_get_voice_agent_config(
    request: Request,
    service: Annotated[
        ClientVoiceAgentConfigService, Depends(get_client_voice_agent_config_service)
    ],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> VoiceAgentConfigResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        return await service.get(client_email_id=resolved_email)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/voice-agent-config", response_model=VoiceAgentConfigResponse)
async def mobile_update_voice_agent_config(
    request: Request,
    body: VoiceAgentConfigUpdateRequest,
    service: Annotated[
        ClientVoiceAgentConfigService, Depends(get_client_voice_agent_config_service)
    ],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> VoiceAgentConfigResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        return await service.update(client_email_id=resolved_email, body=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/voice-agent-schedule", response_model=VoiceAgentScheduleOverviewResponse)
async def mobile_get_voice_agent_schedule(
    request: Request,
    service: Annotated[VoiceAgentScheduleService, Depends(get_voice_agent_schedule_service)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> VoiceAgentScheduleOverviewResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        return await service.get_overview(client_email_id=resolved_email)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/voice-agent-schedule", response_model=VoiceAgentScheduleOverviewResponse)
async def mobile_update_voice_agent_schedule(
    request: Request,
    body: VoiceAgentScheduleUpdateRequest,
    service: Annotated[VoiceAgentScheduleService, Depends(get_voice_agent_schedule_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> VoiceAgentScheduleOverviewResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        return await service.update(client_email_id=resolved_email, body=body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/voice-agent-schedule/trigger", response_model=VoiceAgentScheduleTriggerResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def mobile_trigger_voice_agent_schedule(
    request: Request,
    background_tasks: BackgroundTasks,
    service: Annotated[VoiceAgentScheduleService, Depends(get_voice_agent_schedule_service)],
    call_job_service: Annotated[CallJobService, Depends(get_call_job_service)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> VoiceAgentScheduleTriggerResponse:
    resolved_email, _collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        result = await service.trigger_now(client_email_id=resolved_email, run_job=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(call_job_service.run_job, result.job_id)
    return result


@router.get("/collections", response_model=CollectionListResponse)
async def mobile_list_collections(
    request: Request,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> CollectionListResponse:
    resolved_email, collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        all_collections = service.list_collections()
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        raise
    filtered = [name for name in all_collections if name == collection]
    client = await repository.get_by_email(resolved_email)
    return CollectionListResponse(
        collections=filtered,
        count=len(filtered),
        client_business_phone_number=client.client_business_phone_number,
        client_email_id=resolved_email,
    )


@router.get("/collections/{collection}", response_model=CollectionInfoResponse)
async def mobile_get_collection(
    collection: str,
    request: Request,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> CollectionInfoResponse:
    resolved_email, expected_collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    if collection.strip() != expected_collection:
        raise HTTPException(status_code=403, detail="Collection not allowed for this client")
    try:
        info = service.get_collection(collection)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        raise
    client = await repository.get_by_email(resolved_email)
    return CollectionInfoResponse(
        name=str(info["name"]),
        points_count=int(info["points_count"]),
        vector_size=int(info["vector_size"]),
        client_business_phone_number=client.client_business_phone_number,
    )


@router.delete("/collections/{collection}", response_model=CollectionDeleteResponse)
async def mobile_delete_collection(
    collection: str,
    request: Request,
    service: Annotated[CollectionService, Depends(get_collection_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.ADMIN)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> CollectionDeleteResponse:
    _resolved_email, expected_collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    if collection.strip() != expected_collection:
        raise HTTPException(status_code=403, detail="Collection not allowed for this client")
    try:
        service.delete_collection(collection)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        raise
    return CollectionDeleteResponse(status="deleted", collection=collection)


@router.get("/documents", response_model=DocumentListResponse)
async def mobile_list_documents(
    request: Request,
    service: Annotated[DocumentService, Depends(get_document_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> DocumentListResponse:
    resolved_email, collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        documents = service.list_documents(collection)
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        raise
    client = await repository.get_by_email(resolved_email)
    return DocumentListResponse(
        collection=collection,
        documents=[
            DocumentSummaryResponse(
                document_id=doc.document_id,
                source_uri=doc.source_uri,
                chunk_count=doc.chunk_count,
            )
            for doc in documents
        ],
        count=len(documents),
        client_business_phone_number=client.client_business_phone_number,
    )


@router.post("/documents", response_model=DocumentUploadResponse)
async def mobile_upload_document(
    request: Request,
    file: UploadFile = File(...),
    service: Annotated[DocumentService, Depends(get_document_service)] = ...,
    settings: Annotated[Settings, Depends(get_settings)] = ...,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ] = ...,
    repository: Annotated[ClientRepository, Depends(get_client_repository)] = ...,
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> DocumentUploadResponse:
    resolved_email, collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename or "upload.txt"
    started = time.perf_counter()
    try:
        result = service.ingest_upload(collection=collection, filename=filename, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info(
        "POST /v1/mobile/documents collection=%s file=%r chunks=%d total_ms=%.0f",
        collection,
        filename,
        result.chunks_indexed,
        (time.perf_counter() - started) * 1000,
    )
    client = await repository.get_by_email(resolved_email)
    return DocumentUploadResponse(
        collection=result.collection,
        document_id=result.document_id,
        source_uri=result.source_uri,
        chunks_indexed=result.chunks_indexed,
        client_business_phone_number=client.client_business_phone_number,
    )


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def mobile_delete_document(
    document_id: str,
    request: Request,
    service: Annotated[DocumentService, Depends(get_document_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(Permission.DOCUMENT_WRITE)),
    ],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
    client_email_id: Annotated[str | None, Query(min_length=3)] = None,
) -> DocumentDeleteResponse:
    _resolved_email, collection = await _resolve_client_context(
        request, principal, repository, client_email_id
    )
    try:
        service.delete_document(collection, document_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentDeleteResponse(status="deleted", document_id=document_id)


@router.post("/search", response_model=SearchResponse)
async def mobile_search(
    request: Request,
    body: SearchRequest,
    service: Annotated[SearchService, Depends(get_search_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    principal: Annotated[AuthenticatedPrincipal, Depends(verify_access_token)],
    repository: Annotated[ClientRepository, Depends(get_client_repository)],
) -> SearchResponse:
    resolved_email, collection = await _resolve_client_context(
        request, principal, repository, body.client_email_id
    )
    client = await repository.get_by_email(resolved_email)
    mobile_body = SearchRequest(
        query=body.query,
        max_results=body.max_results,
        collection=collection,
        phone_number=None,
        client_email_id=resolved_email,
    )
    started = time.perf_counter()
    try:
        hits, resolved_collection = service.search(
            query=mobile_body.query,
            max_results=mobile_body.max_results,
            collection=mobile_body.collection,
            client_email_id=mobile_body.client_email_id,
            phone_number=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if is_qdrant_connection_error(exc):
            raise HTTPException(status_code=503, detail=qdrant_unavailable_detail(settings)) from exc
        logger.exception("mobile search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info(
        "POST /v1/mobile/search collection=%s hits=%d total_ms=%.0f query=%r",
        resolved_collection,
        len(hits),
        (time.perf_counter() - started) * 1000,
        body.query[:80],
    )
    return SearchResponse(
        hits=[
            SearchHitResponse(
                text=hit.text,
                score=hit.score,
                source_uri=hit.source_uri,
            )
            for hit in hits
        ],
        count=len(hits),
        collection=resolved_collection,
        client_business_phone_number=client.client_business_phone_number,
        client_email_id=resolved_email,
    )
