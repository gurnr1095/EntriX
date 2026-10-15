"""Check the five SPEC invariants against the database after a load test.

Uses the very same queries as the test suite (tests/invariants.py). Writes a text report and
exits non-zero if anything is violated:

    python -m loadtests.check_invariants [report-path]
"""

import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from tests.invariants import INVARIANT_QUERIES

SUMMARY_QUERIES = {
    "registrations_by_status": (
        "SELECT status::text, count(*) FROM registrations GROUP BY 1 ORDER BY 1"
    ),
    "categories_over_capacity": "SELECT count(*) FROM categories WHERE confirmed_count > capacity",
    "hot_categories": (
        "SELECT c.name, c.capacity, c.confirmed_count, "
        "count(*) FILTER (WHERE r.status = 'confirmed') AS confirmed_rows, "
        "count(*) FILTER (WHERE r.status = 'waitlisted') AS waitlisted_rows "
        "FROM categories c JOIN registrations r ON r.category_id = c.id "
        "GROUP BY c.id ORDER BY count(*) DESC LIMIT 3"
    ),
    "outbox_by_status": "SELECT status::text, count(*) FROM outbox GROUP BY 1 ORDER BY 1",
    "users": "SELECT count(*) FROM users",
}


async def main(report_path: str | None) -> int:
    engine = create_async_engine(get_settings().database_url)
    lines: list[str] = []
    violations = 0
    async with engine.connect() as conn:
        for name, query in INVARIANT_QUERIES.items():
            rows = (await conn.execute(text(query))).all()
            violations += len(rows)
            verdict = "OK" if not rows else f"VIOLATED ({len(rows)} rows)"
            lines.append(f"invariant {name}: {verdict}")
        for name, query in SUMMARY_QUERIES.items():
            rows = [list(map(str, r)) for r in (await conn.execute(text(query))).all()]
            lines.append(f"{name}: {json.dumps(rows)}")
    await engine.dispose()
    lines.append(f"RESULT: {'ALL INVARIANTS HOLD' if violations == 0 else 'INVARIANTS VIOLATED'}")
    report = "\n".join(lines)
    print(report)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report + "\n")
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None)))
