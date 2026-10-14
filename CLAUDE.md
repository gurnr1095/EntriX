# Project: EntriX

Read SPEC.md first. It is the source of truth for schema, flows, API and milestones.

## Rules
- Work milestone by milestone (M1, M2, ...). Do not start a milestone until the previous one's acceptance criteria pass.
- Write the tests listed in SPEC.md section 6 for each milestone before or alongside the code. Tests run against real PostgreSQL, never SQLite.
- Seat claims must use the atomic conditional UPDATE in SPEC.md 4.1. Never read-then-write capacity in Python.
- Cancellation and capacity changes lock the category row (SELECT ... FOR UPDATE) before promoting from the waitlist.
- All state changes that need email enqueue an outbox row in the same transaction. Never send email in a request handler.
- Idempotency rows are inserted in the same transaction as the work. Business errors roll back and do not store a response.
- Keep the five invariants from SPEC.md section 3 true and covered by tests.
- Use SQLAlchemy 2.0 async style, Alembic migrations for every schema change (no create_all in app code), Pydantic v2 schemas, and typed code.
- Keep changes small and runnable at every step. After each milestone, run ruff and pytest and report results.
- Do not add dependencies or features outside SPEC.md without asking.
- Do not fabricate metrics. Performance numbers come only from loadtests/ output recorded in LOADTEST.md.

## Commands
- docker compose up -d postgres redis mailhog
- alembic upgrade head
- pytest -x -q
- ruff check .
- uvicorn app.main:app --reload
- python -m app.worker.outbox_worker
````
