"""Asynchronous database configuration and persistence models."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def new_uuid() -> str:
    """Return a UUID encoded for portable database storage."""

    return str(uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """Persist timestamps as UTC and restore timezone information on SQLite."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTC timestamps must be timezone-aware")
        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    """Base class for all persistence models."""


class CandidateApplication(Base):
    """Authoritative application received from an external ATS."""

    __tablename__ = "candidate_applications"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_application_id",
            name="uq_application_source_external_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    external_application_id: Mapped[str] = mapped_column(String(255), index=True)
    phone_number: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(100), index=True)
    preferred_language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
    )


class Conversation(Base):
    """Conversation associated with one candidate application."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
    )


class Message(Base):
    """Persisted message belonging to a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_message_conversation_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer())
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text())
    message_type: Mapped[str] = mapped_column(String(32), default="turn")
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    recoverable_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ScreeningRecord(Base):
    """Structured screening state stored independently of model context."""

    __tablename__ = "screening_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict)
    pending_data: Mapped[dict[str, Any]] = mapped_column(JSON(), default=dict)
    clarification_counts: Mapped[dict[str, Any]] = mapped_column(
        JSON(),
        default=dict,
    )
    abuse_count: Mapped[int] = mapped_column(Integer(), default=0)
    service_area_supported: Mapped[bool | None] = mapped_column(
        Boolean(),
        nullable=True,
    )
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disqualification_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    final_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    recoverable_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default=utc_now,
        onupdate=utc_now,
    )


class InboundEvent(Base):
    """Durable idempotency receipt for an inbound webhook request."""

    __tablename__ = "inbound_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON())
    application_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class VoiceTurnReceipt(Base):
    """Idempotency receipt for one external ElevenLabs candidate turn."""

    __tablename__ = "voice_turn_receipts"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "external_turn_id",
            name="uq_voice_turn_conversation_external_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    external_turn_id: Mapped[str] = mapped_column(String(255))
    transcript_hash: Mapped[str] = mapped_column(String(64))
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class InterviewBooking(Base):
    """One qualified-candidate recruiter-contact booking."""

    __tablename__ = "interview_bookings"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_interview_booking_application"),
        UniqueConstraint("conversation_id", name="uq_interview_booking_conversation"),
        UniqueConstraint(
            "country_code",
            "slot_starts_at_utc",
            name="uq_interview_booking_country_slot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE"),
        index=True,
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    country_code: Mapped[str] = mapped_column(String(8), index=True)
    slot_starts_at_utc: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Database:
    """Own the async engine and session factory for one application instance."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(database_url)
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        if database_url.startswith("sqlite"):
            self._enable_sqlite_foreign_keys()

    def _enable_sqlite_foreign_keys(self) -> None:
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: Any,
            connection_record: Any,
        ) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async def initialize(self) -> None:
        """Create the schema required by the current application version."""

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        """Release all pooled database connections."""

        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped asynchronous database session."""

    database: Database = request.app.state.database
    async with database.sessions() as session:
        yield session
