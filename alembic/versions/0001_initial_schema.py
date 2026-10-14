"""initial schema (SPEC section 3)

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# One statement per entry: asyncpg cannot run several commands in one call.
UPGRADE_STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS citext",
    "CREATE TYPE user_role AS ENUM ('participant', 'volunteer', 'organizer', 'admin')",
    "CREATE TYPE event_status AS ENUM ('draft', 'published', 'closed')",
    "CREATE TYPE participation_type AS ENUM ('individual', 'team')",
    "CREATE TYPE registration_status AS ENUM "
    "('confirmed', 'waitlisted', 'cancelled', 'checked_in')",
    "CREATE TYPE team_status AS ENUM ('forming', 'registered', 'cancelled')",
    "CREATE TYPE outbox_status AS ENUM ('pending', 'sent', 'failed')",
    """
    CREATE TABLE users (
        id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        auth_id     text NOT NULL UNIQUE,
        email       citext NOT NULL UNIQUE,
        name        text NOT NULL,
        college     text,
        roll_no     text,
        phone       text,
        role        user_role NOT NULL DEFAULT 'participant',
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE events (
        id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        slug           text NOT NULL UNIQUE,
        name           text NOT NULL,
        description    text,
        venue          text,
        starts_at      timestamptz NOT NULL,
        ends_at        timestamptz NOT NULL,
        reg_opens_at   timestamptz NOT NULL,
        reg_closes_at  timestamptz NOT NULL,
        status         event_status NOT NULL DEFAULT 'draft',
        created_by     uuid NOT NULL REFERENCES users(id),
        created_at     timestamptz NOT NULL DEFAULT now(),
        CHECK (reg_opens_at < reg_closes_at),
        CHECK (reg_closes_at <= ends_at),
        CHECK (starts_at < ends_at)
    )
    """,
    """
    CREATE TABLE categories (
        id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        event_id         uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        name             text NOT NULL,
        sport            text NOT NULL,
        participation    participation_type NOT NULL,
        team_size_min    int,
        team_size_max    int,
        capacity         int NOT NULL CHECK (capacity > 0),
        confirmed_count  int NOT NULL DEFAULT 0,
        waitlist_enabled boolean NOT NULL DEFAULT true,
        UNIQUE (event_id, name),
        CHECK (confirmed_count >= 0 AND confirmed_count <= capacity),
        CHECK (
            (participation = 'individual' AND team_size_min IS NULL AND team_size_max IS NULL)
            OR
            (participation = 'team' AND team_size_min >= 1 AND team_size_max >= team_size_min)
        )
    )
    """,
    """
    CREATE TABLE teams (
        id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        category_id  uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        name         text NOT NULL,
        captain_id   uuid NOT NULL REFERENCES users(id),
        invite_code  text NOT NULL UNIQUE,
        status       team_status NOT NULL DEFAULT 'forming',
        created_at   timestamptz NOT NULL DEFAULT now(),
        UNIQUE (category_id, name)
    )
    """,
    """
    CREATE TABLE team_members (
        team_id      uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
        user_id      uuid NOT NULL REFERENCES users(id),
        category_id  uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        joined_at    timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (team_id, user_id),
        UNIQUE (category_id, user_id)
    )
    """,
    """
    CREATE TABLE registrations (
        id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        category_id   uuid NOT NULL REFERENCES categories(id),
        user_id       uuid NOT NULL REFERENCES users(id),
        team_id       uuid REFERENCES teams(id),
        status        registration_status NOT NULL,
        waitlisted_at timestamptz,
        created_at    timestamptz NOT NULL DEFAULT now(),
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX uq_active_registration "
    "ON registrations (category_id, user_id) WHERE status <> 'cancelled'",
    "CREATE INDEX ix_reg_waitlist "
    "ON registrations (category_id, waitlisted_at, id) WHERE status = 'waitlisted'",
    "CREATE INDEX ix_reg_category_status ON registrations (category_id, status)",
    "CREATE INDEX ix_reg_user ON registrations (user_id)",
    """
    CREATE TABLE check_ins (
        registration_id uuid PRIMARY KEY REFERENCES registrations(id),
        checked_in_by   uuid NOT NULL REFERENCES users(id),
        checked_in_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE idempotency_keys (
        user_id          uuid NOT NULL REFERENCES users(id),
        key              text NOT NULL,
        method           text NOT NULL,
        path             text NOT NULL,
        request_hash     text NOT NULL,
        response_status  int,
        response_body    jsonb,
        created_at       timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, key)
    )
    """,
    """
    CREATE TABLE outbox (
        id               bigserial PRIMARY KEY,
        event_type       text NOT NULL,
        payload          jsonb NOT NULL,
        status           outbox_status NOT NULL DEFAULT 'pending',
        attempts         int NOT NULL DEFAULT 0,
        next_attempt_at  timestamptz NOT NULL DEFAULT now(),
        last_error       text,
        created_at       timestamptz NOT NULL DEFAULT now(),
        sent_at          timestamptz
    )
    """,
    "CREATE INDEX ix_outbox_pending ON outbox (next_attempt_at) WHERE status = 'pending'",
]

DOWNGRADE_STATEMENTS = [
    "DROP TABLE outbox",
    "DROP TABLE idempotency_keys",
    "DROP TABLE check_ins",
    "DROP TABLE registrations",
    "DROP TABLE team_members",
    "DROP TABLE teams",
    "DROP TABLE categories",
    "DROP TABLE events",
    "DROP TABLE users",
    "DROP TYPE outbox_status",
    "DROP TYPE team_status",
    "DROP TYPE registration_status",
    "DROP TYPE participation_type",
    "DROP TYPE event_status",
    "DROP TYPE user_role",
]


def upgrade() -> None:
    for stmt in UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_STATEMENTS:
        op.execute(stmt)
