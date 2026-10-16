import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    EventStatus,
    ParticipationType,
    RegistrationStatus,
    TeamStatus,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- users ----
class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str
    college: str | None
    roll_no: str | None
    phone: str | None
    role: UserRole


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    college: str | None = None
    roll_no: str | None = None
    phone: str | None = None


# ---- events ----
def _check_event_times(
    starts_at: datetime, ends_at: datetime, opens: datetime, closes: datetime
) -> None:
    if not starts_at < ends_at:
        raise ValueError("starts_at must be before ends_at")
    if not opens < closes:
        raise ValueError("reg_opens_at must be before reg_closes_at")
    if not closes <= ends_at:
        raise ValueError("reg_closes_at must be at or before ends_at")


class EventCreate(BaseModel):
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    description: str | None = None
    venue: str | None = None
    starts_at: datetime
    ends_at: datetime
    reg_opens_at: datetime
    reg_closes_at: datetime

    @model_validator(mode="after")
    def _times(self) -> Self:
        _check_event_times(self.starts_at, self.ends_at, self.reg_opens_at, self.reg_closes_at)
        return self


class EventPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    venue: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    reg_opens_at: datetime | None = None
    reg_closes_at: datetime | None = None
    status: EventStatus | None = None


class EventOut(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    venue: str | None
    starts_at: datetime
    ends_at: datetime
    reg_opens_at: datetime
    reg_closes_at: datetime
    status: EventStatus


class EventPage(BaseModel):
    items: list[EventOut]
    next_cursor: str | None


# ---- categories ----
class CategoryCreate(BaseModel):
    name: str = Field(min_length=1)
    sport: str = Field(min_length=1)
    participation: ParticipationType
    team_size_min: int | None = None
    team_size_max: int | None = None
    capacity: int = Field(gt=0)
    waitlist_enabled: bool = True

    @model_validator(mode="after")
    def _team_sizes(self) -> Self:
        if self.participation == ParticipationType.individual:
            if self.team_size_min is not None or self.team_size_max is not None:
                raise ValueError("individual categories cannot set team sizes")
        else:
            if self.team_size_min is None or self.team_size_max is None:
                raise ValueError("team categories need team_size_min and team_size_max")
            if self.team_size_min < 1 or self.team_size_max < self.team_size_min:
                raise ValueError("require 1 <= team_size_min <= team_size_max")
        return self


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    sport: str | None = Field(default=None, min_length=1)
    capacity: int | None = Field(default=None, gt=0)
    waitlist_enabled: bool | None = None


class CategoryOut(ORMModel):
    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    sport: str
    participation: ParticipationType
    team_size_min: int | None
    team_size_max: int | None
    capacity: int
    confirmed_count: int
    waitlist_enabled: bool
    seats_left: int


class EventDetail(EventOut):
    categories: list[CategoryOut]


# ---- registrations ----
class RegistrationOut(BaseModel):
    registration_id: uuid.UUID
    status: RegistrationStatus
    waitlist_position: int | None = Field(default=None, description="Only when waitlisted")


# ---- teams ----
class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class TeamJoin(BaseModel):
    invite_code: str = Field(min_length=1)


class TeamOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    captain_id: uuid.UUID
    status: TeamStatus
    invite_code: str | None = Field(default=None, description="Captain and organizers only")


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    name: str
    is_captain: bool


class TeamDetail(TeamOut):
    members: list[TeamMemberOut]


# ---- organizer tools ----
class ParticipantOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    college: str | None
    roll_no: str | None
    phone: str | None


class RegistrationRow(BaseModel):
    registration_id: uuid.UUID
    status: RegistrationStatus
    category_id: uuid.UUID
    category_name: str
    team_name: str | None
    participant: ParticipantOut
    created_at: datetime
    waitlisted_at: datetime | None


class RegistrationRowPage(BaseModel):
    items: list[RegistrationRow]
    next_cursor: str | None


class CategoryStats(BaseModel):
    id: uuid.UUID
    name: str
    capacity: int
    confirmed: int
    waitlisted: int
    checked_in: int


class EventStats(BaseModel):
    categories: list[CategoryStats]


class QrOut(BaseModel):
    token: str


class CheckInIn(BaseModel):
    token: str = Field(min_length=1)


class CheckInParticipant(BaseModel):
    name: str
    category: str


class CheckInOut(BaseModel):
    registration_id: uuid.UUID
    status: RegistrationStatus
    already_checked_in: bool
    participant: CheckInParticipant


class MyRegistrationOut(BaseModel):
    registration_id: uuid.UUID
    category_id: uuid.UUID
    status: RegistrationStatus
    waitlist_position: int | None
    created_at: datetime
    event_id: uuid.UUID
    event_name: str
    event_starts_at: datetime
    venue: str | None
    category_name: str
    sport: str
    team_id: uuid.UUID | None
    team_name: str | None


class MyTeamOut(BaseModel):
    id: uuid.UUID
    name: str
    status: TeamStatus
    category_id: uuid.UUID
    category_name: str
    event_id: uuid.UUID
    event_name: str
    captain_id: uuid.UUID
    invite_code: str | None = Field(default=None, description="Captain only")
    member_count: int
    team_size_min: int
    team_size_max: int
    is_captain: bool


class MyRegistrationPage(BaseModel):
    items: list[MyRegistrationOut]
    next_cursor: str | None
