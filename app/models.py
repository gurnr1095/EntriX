import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRole(enum.StrEnum):
    participant = "participant"
    volunteer = "volunteer"
    organizer = "organizer"
    admin = "admin"


class EventStatus(enum.StrEnum):
    draft = "draft"
    published = "published"
    closed = "closed"


class ParticipationType(enum.StrEnum):
    individual = "individual"
    team = "team"


class RegistrationStatus(enum.StrEnum):
    confirmed = "confirmed"
    waitlisted = "waitlisted"
    cancelled = "cancelled"
    checked_in = "checked_in"


class TeamStatus(enum.StrEnum):
    forming = "forming"
    registered = "registered"
    cancelled = "cancelled"


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


def pg_enum(cls: type[enum.Enum], name: str) -> SAEnum:
    # The types are created by the Alembic migration, never by the app.
    return SAEnum(cls, name=name, create_type=False, values_callable=lambda e: [m.value for m in e])


_uuid_pk = {"primary_key": True, "server_default": text("gen_random_uuid()")}
_now = {"server_default": func.now()}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_uuid_pk)
    auth_id: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    name: Mapped[str] = mapped_column(Text)
    college: Mapped[str | None] = mapped_column(Text)
    roll_no: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), server_default=UserRole.participant.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("reg_opens_at < reg_closes_at"),
        CheckConstraint("reg_closes_at <= ends_at"),
        CheckConstraint("starts_at < ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_uuid_pk)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reg_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reg_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[EventStatus] = mapped_column(
        pg_enum(EventStatus, "event_status"), server_default=EventStatus.draft.value
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("event_id", "name"),
        CheckConstraint("capacity > 0"),
        CheckConstraint("confirmed_count >= 0 AND confirmed_count <= capacity"),
        CheckConstraint(
            "(participation = 'individual' AND team_size_min IS NULL AND team_size_max IS NULL)"
            " OR (participation = 'team' AND team_size_min >= 1 AND team_size_max >= team_size_min)"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_uuid_pk)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    sport: Mapped[str] = mapped_column(Text)
    participation: Mapped[ParticipationType] = mapped_column(
        pg_enum(ParticipationType, "participation_type")
    )
    team_size_min: Mapped[int | None] = mapped_column(Integer)
    team_size_max: Mapped[int | None] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    confirmed_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    waitlist_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("category_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_uuid_pk)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    captain_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    invite_code: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[TeamStatus] = mapped_column(
        pg_enum(TeamStatus, "team_status"), server_default=TeamStatus.forming.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("category_id", "user_id"),)

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class Registration(Base):
    __tablename__ = "registrations"
    __table_args__ = (
        Index(
            "uq_active_registration",
            "category_id",
            "user_id",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        Index(
            "ix_reg_waitlist",
            "category_id",
            "waitlisted_at",
            "id",
            postgresql_where=text("status = 'waitlisted'"),
        ),
        Index("ix_reg_category_status", "category_id", "status"),
        Index("ix_reg_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_uuid_pk)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[RegistrationStatus] = mapped_column(
        pg_enum(RegistrationStatus, "registration_status")
    )
    waitlisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class CheckIn(Base):
    __tablename__ = "check_ins"

    registration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("registrations.id"), primary_key=True
    )
    checked_in_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    method: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        Index(
            "ix_outbox_pending",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[OutboxStatus] = mapped_column(
        pg_enum(OutboxStatus, "outbox_status"), server_default=OutboxStatus.pending.value
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
