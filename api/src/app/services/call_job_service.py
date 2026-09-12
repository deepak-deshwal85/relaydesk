from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.postgres.call_job_repository import CallJobRepository
from app.db.postgres.client_repository import ClientRepository
from app.db.postgres.consumer_repository import ConsumerRepository
from app.db.postgres.phone_line_repository import PhoneLineRepository
from app.db.postgres.session import get_session_factory
from app.domain.consumer_models import CallAttemptResult
from app.schemas.call_jobs import CallAttemptResponse, CallJobResponse
from app.services.outbound_caller import OutboundCaller, build_outbound_caller
from app.services.phone_line_service import resolve_outbound_trunk_id

logger = logging.getLogger("relaydesk-api")


class CallJobService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        outbound_caller: OutboundCaller,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._outbound_caller = outbound_caller

    @staticmethod
    def _to_response(job) -> CallJobResponse:
        results = None
        if job.results:
            results = [
                CallAttemptResponse(
                    consumer_id=result.consumer_id,
                    consumer_phone_number=result.consumer_phone_number,
                    success=result.success,
                    detail=result.detail,
                )
                for result in job.results
            ]
        return CallJobResponse(
            id=job.id,
            client_id=job.client_id,
            status=job.status,
            total_consumers=job.total_consumers,
            calls_completed=job.calls_completed,
            error_message=job.error_message,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
            results=results,
        )

    async def create_job(self, client_id: int) -> CallJobResponse:
        async with self._session_factory() as session:
            repository = CallJobRepository(session)
            job = await repository.create(client_id=client_id)
            return self._to_response(job)

    async def get_job(
        self, job_id: UUID, *, client_id: int | None = None
    ) -> CallJobResponse | None:
        async with self._session_factory() as session:
            repository = CallJobRepository(session)
            job = await repository.get(job_id)
            if job and client_id is not None and job.client_id != client_id:
                return None
            return self._to_response(job) if job else None

    async def list_jobs(
        self,
        *,
        client_id: int | None = None,
        limit: int = 20,
    ) -> list[CallJobResponse]:
        async with self._session_factory() as session:
            repository = CallJobRepository(session)
            jobs = await repository.list_recent(client_id=client_id, limit=limit)
            return [self._to_response(job) for job in jobs]

    async def run_job(self, job_id: UUID) -> None:
        logger.info("call job started job_id=%s", job_id)
        results: list[CallAttemptResult] = []
        try:
            async with self._session_factory() as session:
                job_repository = CallJobRepository(session)
                consumer_repository = ConsumerRepository(session)
                client_repository = ClientRepository(session)

                job = await job_repository.get(job_id)
                if job is None:
                    logger.error("call job not found job_id=%s", job_id)
                    return

                client = await client_repository.get_by_id(job.client_id)
                if client is None:
                    logger.error(
                        "call job client not found job_id=%s client_id=%s",
                        job_id,
                        job.client_id,
                    )
                    return

                consumers = await consumer_repository.list_ready_for_campaign(
                    client_id=job.client_id
                )
                logger.info(
                    "campaign job loaded consumers job_id=%s client_id=%s ready=%d",
                    job_id,
                    job.client_id,
                    len(consumers),
                )

                await job_repository.mark_running(
                    job_id, total_consumers=len(consumers)
                )
                phone_line = await PhoneLineRepository(session).get_by_client_id(
                    client.id
                )

            trunk_id = resolve_outbound_trunk_id(
                line_status=phone_line.status if phone_line else None,
                line_trunk_id=(
                    phone_line.livekit_outbound_trunk_id if phone_line else None
                ),
                fallback_trunk_id=self._settings.livekit_sip_outbound_trunk_id,
            )

            completed = 0
            for consumer in consumers:
                result = await self._outbound_caller.place_call(
                    consumer=consumer,
                    client=client,
                    job_id=job_id,
                    sip_trunk_id=trunk_id,
                )
                results.append(result)
                if result.success:
                    completed += 1
                logger.info(
                    "call attempt job_id=%s consumer_id=%s consumer=%s success=%s detail=%s",
                    job_id,
                    consumer.id,
                    consumer.consumer_phone_number,
                    result.success,
                    result.detail,
                )

                async with self._session_factory() as session:
                    job_repository = CallJobRepository(session)
                    await job_repository.update_progress(
                        job_id,
                        calls_completed=completed,
                        results=results,
                    )

            async with self._session_factory() as session:
                job_repository = CallJobRepository(session)
                await job_repository.mark_completed(job_id, results=results)

            logger.info(
                "call job completed job_id=%s calls=%d/%d",
                job_id,
                completed,
                len(consumers),
            )
        except Exception as exc:
            logger.exception("call job failed job_id=%s", job_id)
            async with self._session_factory() as session:
                job_repository = CallJobRepository(session)
                await job_repository.mark_failed(
                    job_id,
                    error_message=str(exc),
                    results=results or None,
                )


def build_call_job_service(settings: Settings) -> CallJobService:
    return CallJobService(
        settings=settings,
        session_factory=get_session_factory(),
        outbound_caller=build_outbound_caller(settings),
    )
