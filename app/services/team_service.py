import secrets
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import ORGANIZER_ROLES, CurrentUser
from app.errors import AppError
from app.models import (
    ParticipationType,
    Registration,
    RegistrationStatus,
    Team,
    TeamMember,
    TeamStatus,
    User,
)
from app.services import idempotency
from app.services.registration_service import (
    cancel_locked,
    ensure_registration_open,
    load_category_event,
    lock_category,
    place_registration,
    release_team,
)

# No 0/O/1/I so a code read out loud or typed from a screenshot is hard to get wrong.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_invite_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


async def _lock_team(session: AsyncSession, team_id: uuid.UUID) -> Team:
    team = await session.scalar(
        select(Team)
        .where(Team.id == team_id)
        .with_for_update(key_share=True)  # NO KEY UPDATE: see lock_category
        .execution_options(populate_existing=True)
    )
    if team is None:
        raise AppError(404, "not_found", "Team not found")
    return team


async def _member_count(session: AsyncSession, team_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team_id)
        )
        or 0
    )


def _require_forming(team: Team) -> None:
    if team.status == TeamStatus.registered:
        raise AppError(409, "roster_locked", "The team is registered; its roster is locked")
    if team.status == TeamStatus.cancelled:
        raise AppError(409, "team_cancelled", "This team was cancelled")


async def create_team(
    session: AsyncSession, user: CurrentUser, category_id: uuid.UUID, name: str
) -> Team:
    """Create a team in `forming` state with the creator as captain and first member."""
    async with session.begin():
        category, event, db_now = await load_category_event(session, category_id)
        ensure_registration_open(event, db_now)
        if category.participation != ParticipationType.team:
            raise AppError(409, "not_team_category", "This category is for individuals")

        already = await session.scalar(
            select(TeamMember.team_id).where(
                TeamMember.category_id == category_id, TeamMember.user_id == user.id
            )
        )
        if already is not None:
            raise AppError(409, "already_in_team", "You are already in a team for this category")

        team: Team | None = None
        for _ in range(5):  # retry on the (very unlikely) invite-code collision
            candidate = Team(
                category_id=category_id,
                name=name,
                captain_id=user.id,
                invite_code=_new_invite_code(),
            )
            try:
                async with session.begin_nested():
                    session.add(candidate)
                    await session.flush()
            except IntegrityError as exc:
                detail = str(exc.orig)
                if "teams_invite_code_key" in detail:
                    continue
                if "teams_category_id_name_key" in detail:
                    raise AppError(409, "team_name_taken", "Team name already used") from exc
                raise
            team = candidate
            break
        if team is None:
            raise AppError(500, "invite_code_unavailable", "Could not allocate an invite code")

        await _add_member(session, team, user.id)
    return team


async def _add_member(session: AsyncSession, team: Team, user_id: uuid.UUID) -> None:
    session.add(TeamMember(team_id=team.id, user_id=user_id, category_id=team.category_id))
    try:
        await session.flush()
    except IntegrityError as exc:
        # UNIQUE (category_id, user_id): invariant 5 even if two requests race.
        if "team_members_category_id_user_id_key" in str(exc.orig):
            raise AppError(
                409, "already_in_team", "You are already in a team for this category"
            ) from exc
        raise


async def join_team(session: AsyncSession, user: CurrentUser, invite_code: str) -> Team:
    """Join a forming team by invite code. Locks only the team row (see register_team)."""
    async with session.begin():
        found = await session.scalar(select(Team.id).where(Team.invite_code == invite_code))
        if found is None:
            raise AppError(404, "not_found", "No team has this invite code")
        team = await _lock_team(session, found)

        category, event, db_now = await load_category_event(session, team.category_id)
        ensure_registration_open(event, db_now)
        _require_forming(team)

        if await _member_count(session, team.id) >= (category.team_size_max or 0):
            raise AppError(409, "team_full", "The team is already at its maximum size")
        already = await session.scalar(
            select(TeamMember.team_id).where(
                TeamMember.category_id == team.category_id, TeamMember.user_id == user.id
            )
        )
        if already is not None:
            raise AppError(409, "already_in_team", "You are already in a team for this category")
        await _add_member(session, team, user.id)
    return team


async def leave_team(session: AsyncSession, user: CurrentUser, team_id: uuid.UUID) -> None:
    async with session.begin():
        team = await _lock_team(session, team_id)
        if team.captain_id == user.id:
            raise AppError(
                409, "captain_cannot_leave", "The captain must cancel the team instead of leaving"
            )
        _require_forming(team)
        result = await session.execute(
            delete(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user.id)
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError(403, "forbidden", "You are not a member of this team")


async def register_team(
    session: AsyncSession,
    user: CurrentUser,
    team_id: uuid.UUID,
    *,
    idempotency_key: str,
    method: str,
    path: str,
    request_hash: str,
) -> tuple[int, dict[str, Any]]:
    """Register a whole team as one seat (SPEC 4.3). Same seat logic as individuals.

    Lock order is category, then team. Joining only ever locks the team row, so the two
    cannot deadlock, and a join that waits on the team lock sees the locked roster.
    """
    async with session.begin():
        replay = await idempotency.claim(
            session, user.id, idempotency_key, method, path, request_hash
        )
        if replay is not None:
            return replay.status, replay.body

        found = (
            await session.execute(
                select(Team.category_id, Team.captain_id).where(Team.id == team_id)
            )
        ).first()
        if found is None:
            raise AppError(404, "not_found", "Team not found")
        if found.captain_id != user.id:
            raise AppError(403, "forbidden", "Only the captain can register the team")

        category, event, db_now = await load_category_event(session, found.category_id)
        ensure_registration_open(event, db_now)

        await lock_category(session, found.category_id)
        team = await _lock_team(session, team_id)
        if team.status == TeamStatus.registered:
            raise AppError(409, "already_registered", "This team is already registered")
        _require_forming(team)

        members = await _member_count(session, team_id)
        if not (category.team_size_min or 0) <= members <= (category.team_size_max or 0):
            raise AppError(
                409,
                "team_size_invalid",
                f"Team has {members} members; this category needs "
                f"{category.team_size_min} to {category.team_size_max}",
            )

        body = await place_registration(
            session, category_id=found.category_id, user_id=user.id, team_id=team_id
        )
        team.status = TeamStatus.registered
        await idempotency.store_response(session, user.id, idempotency_key, 201, body)
    return 201, body


async def cancel_team(session: AsyncSession, user: CurrentUser, team_id: uuid.UUID) -> Team:
    """Cancel a team and, if it has one, its registration (SPEC 4.2 and 4.3)."""
    async with session.begin():
        found = (
            await session.execute(
                select(Team.category_id, Team.captain_id).where(Team.id == team_id)
            )
        ).first()
        if found is None:
            raise AppError(404, "not_found", "Team not found")
        if found.captain_id != user.id and user.role not in ORGANIZER_ROLES:
            raise AppError(403, "forbidden", "Only the captain or an organizer can cancel a team")

        await lock_category(session, found.category_id)
        team = await _lock_team(session, team_id)
        if team.status == TeamStatus.cancelled:
            raise AppError(409, "already_cancelled", "The team is already cancelled")

        registration = await session.scalar(
            select(Registration)
            .where(
                Registration.team_id == team_id,
                Registration.status != RegistrationStatus.cancelled,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if registration is not None:
            await cancel_locked(session, registration)  # also releases the team
        else:
            await release_team(session, team_id)
    return team


async def team_detail(
    session: AsyncSession, user: CurrentUser, team_id: uuid.UUID
) -> tuple[Team, list[tuple[uuid.UUID, str]], bool]:
    """Team, its members as (user_id, name), and whether the viewer may see the invite code."""
    team = await session.get(Team, team_id)
    if team is None:
        raise AppError(404, "not_found", "Team not found")
    members = [
        (row.user_id, row.name)
        for row in (
            await session.execute(
                select(TeamMember.user_id, User.name)
                .join(User, User.id == TeamMember.user_id)
                .where(TeamMember.team_id == team_id)
                .order_by(TeamMember.joined_at, TeamMember.user_id)
            )
        ).all()
    ]
    is_organizer = user.role in ORGANIZER_ROLES
    if not is_organizer and user.id not in {m[0] for m in members}:
        raise AppError(403, "forbidden", "Only team members and organizers can view this team")
    can_see_code = is_organizer or team.captain_id == user.id
    return team, members, can_see_code

