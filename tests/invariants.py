from sqlalchemy import text

from app.db import engine

# Each query returns the offending rows; an empty result means the invariant holds.
INVARIANT_QUERIES: dict[str, str] = {
    "1_confirmed_count_matches_registrations": """
        SELECT c.id FROM categories c
        WHERE c.confirmed_count <> (
            SELECT count(*) FROM registrations r
            WHERE r.category_id = c.id AND r.status IN ('confirmed', 'checked_in'))
    """,
    "2_confirmed_count_within_capacity": """
        SELECT id FROM categories WHERE confirmed_count > capacity OR confirmed_count < 0
    """,
    "3_waitlist_implies_full": """
        SELECT c.id FROM categories c
        WHERE c.confirmed_count <> c.capacity
          AND EXISTS (SELECT 1 FROM registrations r
                      WHERE r.category_id = c.id AND r.status = 'waitlisted')
    """,
    "4_one_active_registration_per_user_per_category": """
        SELECT category_id, user_id FROM registrations
        WHERE status <> 'cancelled'
        GROUP BY category_id, user_id HAVING count(*) > 1
    """,
    "5_one_team_per_user_per_category": """
        SELECT category_id, user_id FROM team_members
        GROUP BY category_id, user_id HAVING count(*) > 1
    """,
}


async def assert_invariants() -> None:
    async with engine.connect() as conn:
        for name, query in INVARIANT_QUERIES.items():
            rows = (await conn.execute(text(query))).all()
            assert not rows, f"invariant {name} violated: {rows}"
