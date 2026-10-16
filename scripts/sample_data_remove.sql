-- Removes everything scripts/sample_data.sql created (the events slugged 'sample-...' and the
-- students whose auth_id starts with 'sample|'). Nothing else is touched. Run it in the Neon SQL
-- editor (a cleared editor, one run).

DO $remove$
DECLARE ev uuid[];
BEGIN
  SELECT array_agg(id) INTO ev FROM events WHERE slug LIKE 'sample-%';
  IF ev IS NOT NULL THEN
    DELETE FROM check_ins WHERE registration_id IN (
      SELECT r.id FROM registrations r JOIN categories c ON c.id = r.category_id WHERE c.event_id = ANY (ev));
    DELETE FROM registrations WHERE category_id IN (SELECT id FROM categories WHERE event_id = ANY (ev));
    DELETE FROM team_members WHERE category_id IN (SELECT id FROM categories WHERE event_id = ANY (ev));
    DELETE FROM teams WHERE category_id IN (SELECT id FROM categories WHERE event_id = ANY (ev));
    DELETE FROM categories WHERE event_id = ANY (ev);
    DELETE FROM events WHERE id = ANY (ev);
  END IF;
  DELETE FROM users WHERE auth_id LIKE 'sample|%';
  RAISE NOTICE 'Sample data removed.';
END
$remove$;
