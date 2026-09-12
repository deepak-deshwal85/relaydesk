from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres.base import Base


class ClientRow(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_business_phone_number: Mapped[str | None] = mapped_column(
        String(32), nullable=True, unique=True
    )
    client_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    client_email_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConsumerRow(Base):
    __tablename__ = "consumers"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "consumer_phone_number",
            name="uq_consumers_client_consumer",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    consumer_phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    consumer_email_id: Mapped[str] = mapped_column(String(255), nullable=False)
    consumer_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    consumer_address: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="READY")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CallJobRow(Base):
    __tablename__ = "call_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_consumers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calls_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    results_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CallSummaryRow(Base):
    __tablename__ = "call_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consumer_id: Mapped[int] = mapped_column(
        ForeignKey("consumers.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    call_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    call_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    call_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("call_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClientVoiceAgentConfigRow(Base):
    __tablename__ = "client_voice_agent_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    voice_agent_language: Mapped[str] = mapped_column(
        String(16), nullable=False, default="hi-IN", server_default="hi-IN"
    )
    voice_agent_greeting_message: Mapped[str] = mapped_column(Text, nullable=False)
    calcom_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calcom_event_type_slug: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    calcom_event_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calcom_organization_slug: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ClientPhoneLineRow(Base):
    __tablename__ = "client_phone_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="plivo")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="provisioning"
    )
    country_iso: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_number_e164: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plivo_origination_uri_uuid: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    plivo_inbound_trunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plivo_credential_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plivo_outbound_trunk_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    plivo_outbound_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sip_username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sip_password: Mapped[str | None] = mapped_column(String(64), nullable=True)
    livekit_inbound_trunk_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    livekit_outbound_trunk_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    livekit_dispatch_rule_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ClientVoiceAgentScheduleRow(Base):
    __tablename__ = "client_voice_agent_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_time: Mapped[str] = mapped_column(String(5), nullable=False, default="09:00")
    days_of_week: Mapped[str] = mapped_column(
        String(32), nullable=False, default="1,2,3,4,5"
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Kolkata"
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("call_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
