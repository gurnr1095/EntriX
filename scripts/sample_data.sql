-- EntriX sample data, for showing the site to someone.
--
-- Run it once in the Neon SQL editor (a cleared editor, one run). Change the e-mail on the next
-- line to YOUR organizer account first. It creates, all marked "sample" so they are easy to remove:
--   * 4 events: one open for registration, one whose registration has closed (with check-ins),
--     one that opens in a few days, and one draft only organizers can see
--   * 60 sample students, registrations, a full category with a waitlist, and teams
-- Every number is kept consistent (seat counts, waitlist, one registration per person), so the
-- organizer stats and the seat bars match. No e-mails are queued.
-- To remove everything again, run scripts/sample_data_remove.sql.

DO $sample$
DECLARE
  organizer_email constant text := 'grkr1095@gmail.com';   -- <- your organizer account

  organizer uuid;
  ev_open uuid; ev_closed uuid; ev_soon uuid; ev_draft uuid;
  c_tt uuid; c_bd uuid; c_chess uuid; c_carrom uuid; c_cricket uuid;
  c_sprint uuid; c_jump uuid; c_ms uuid; c_ws uuid; c_mixed uuid; c_quiz uuid;
  u uuid[];
  first_names text[] := ARRAY['Aarav','Vihaan','Aditya','Arjun','Ishaan','Kabir','Rohan','Siddharth','Ananya','Diya','Isha','Kavya',
                              'Meera','Naina','Priya','Riya','Saanvi','Tanvi','Zoya','Yash','Neha','Rahul','Sneha','Varun'];
  last_names  text[] := ARRAY['Sharma','Verma','Gupta','Singh','Kaur','Mehta','Nair','Reddy','Iyer','Patel','Das','Bose',
                              'Khanna','Malhotra','Chopra','Bhatia','Joshi','Kapoor','Saxena','Yadav'];
  colleges    text[] := ARRAY['NIT Delhi','IIT Delhi','DTU','NSUT','Jamia Millia Islamia','Delhi University'];
  i int; t uuid; k int;
  members int[]; team_names text[] := ARRAY['Lions','Hawks','Tigers','Falcons'];
  teams_spec int[][] := ARRAY[[45,48],[49,51],[52,55],[56,58]];   -- first and last user number of each team
BEGIN
  SELECT id INTO organizer FROM users WHERE email = organizer_email;
  IF organizer IS NULL THEN
    RAISE EXCEPTION 'No user with e-mail %. Sign in to the site once with that account, or change organizer_email at the top.', organizer_email;
  END IF;
  IF EXISTS (SELECT 1 FROM events WHERE slug LIKE 'sample-%') THEN
    RAISE EXCEPTION 'Sample data already exists. Run scripts/sample_data_remove.sql first if you want to recreate it.';
  END IF;

  -- 60 sample students ---------------------------------------------------------------------------
  FOR i IN 1..60 LOOP
    INSERT INTO users (auth_id, email, name, college, roll_no, phone)
    VALUES ('sample|' || lpad(i::text, 2, '0'),
            'sample.student' || lpad(i::text, 2, '0') || '@example.test',
            first_names[1 + (i * 5) % array_length(first_names, 1)] || ' ' || last_names[1 + (i * 7) % array_length(last_names, 1)],
            colleges[1 + i % array_length(colleges, 1)],
            '22' || (ARRAY['CS','EC','ME','CE','EE'])[1 + i % 5] || lpad((100 + i)::text, 3, '0'),
            '98' || lpad((10000000 + i * 7919)::text, 8, '0'))
    ON CONFLICT DO NOTHING;
  END LOOP;
  SELECT array_agg(id ORDER BY auth_id) INTO u FROM users WHERE auth_id LIKE 'sample|%';

  -- Events ---------------------------------------------------------------------------------------
  INSERT INTO events (slug, name, description, venue, starts_at, ends_at, reg_opens_at, reg_closes_at, status, created_by)
  VALUES ('sample-zeal-sports-fest', 'Zeal Sports Fest 2026',
          E'The annual inter-college sports festival. Register for your sport, show your QR pass at the gate.\nBring your college ID card and arrive 30 minutes early.',
          'NIT Delhi Main Ground', now() + interval '6 days', now() + interval '7 days',
          now() - interval '2 days', now() + interval '4 days', 'published', organizer)
  RETURNING id INTO ev_open;
  INSERT INTO events (slug, name, description, venue, starts_at, ends_at, reg_opens_at, reg_closes_at, status, created_by)
  VALUES ('sample-autumn-athletics-meet', 'Autumn Athletics Meet',
          'Track and field events. Registration has closed; check-in is under way at the gate.',
          'Stadium Track', now() + interval '1 hour', now() + interval '9 hours',
          now() - interval '10 days', now() - interval '1 day', 'published', organizer)
  RETURNING id INTO ev_closed;
  INSERT INTO events (slug, name, description, venue, starts_at, ends_at, reg_opens_at, reg_closes_at, status, created_by)
  VALUES ('sample-winter-cup-badminton', 'Winter Cup Badminton Open',
          'Singles and mixed doubles. Registration opens in a few days.',
          'Indoor Sports Complex', now() + interval '12 days', now() + interval '13 days',
          now() + interval '3 days', now() + interval '10 days', 'published', organizer)
  RETURNING id INTO ev_soon;
  INSERT INTO events (slug, name, description, venue, starts_at, ends_at, reg_opens_at, reg_closes_at, status, created_by)
  VALUES ('sample-inter-hostel-quiz', 'Inter-Hostel Quiz (draft)',
          'A draft: only organizers can see this until it is published.',
          'Auditorium', now() + interval '20 days', now() + interval '20 days 4 hours',
          now() + interval '5 days', now() + interval '18 days', 'draft', organizer)
  RETURNING id INTO ev_draft;

  -- Categories -----------------------------------------------------------------------------------
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_open, 'Table Tennis Singles', 'table-tennis', 'individual', 32, true) RETURNING id INTO c_tt;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_open, 'Badminton Singles', 'badminton', 'individual', 16, true) RETURNING id INTO c_bd;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_open, 'Chess Open', 'chess', 'individual', 8, true) RETURNING id INTO c_chess;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_open, 'Carrom Singles', 'carrom', 'individual', 4, false) RETURNING id INTO c_carrom;
  INSERT INTO categories (event_id, name, sport, participation, team_size_min, team_size_max, capacity, waitlist_enabled) VALUES (ev_open, 'Cricket', 'cricket', 'team', 3, 4, 6, true) RETURNING id INTO c_cricket;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_closed, '100m Sprint', 'athletics', 'individual', 20, true) RETURNING id INTO c_sprint;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_closed, 'Long Jump', 'athletics', 'individual', 10, true) RETURNING id INTO c_jump;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_soon, 'Men''s Singles', 'badminton', 'individual', 32, true) RETURNING id INTO c_ms;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_soon, 'Women''s Singles', 'badminton', 'individual', 32, true) RETURNING id INTO c_ws;
  INSERT INTO categories (event_id, name, sport, participation, team_size_min, team_size_max, capacity, waitlist_enabled) VALUES (ev_soon, 'Mixed Doubles', 'badminton', 'team', 2, 2, 16, true) RETURNING id INTO c_mixed;
  INSERT INTO categories (event_id, name, sport, participation, capacity, waitlist_enabled) VALUES (ev_draft, 'Quiz Team Round', 'quiz', 'individual', 40, true) RETURNING id INTO c_quiz;

  -- Registrations: Zeal Sports Fest (open) ------------------------------------------------------
  FOR i IN 1..14 LOOP   -- table tennis: 14 of 32
    INSERT INTO registrations (category_id, user_id, status, created_at) VALUES (c_tt, u[i], 'confirmed', now() - (i || ' hours')::interval);
  END LOOP;
  FOR i IN 15..29 LOOP  -- badminton: 15 of 16, one seat left
    INSERT INTO registrations (category_id, user_id, status, created_at) VALUES (c_bd, u[i], 'confirmed', now() - ((i - 10) || ' hours')::interval);
  END LOOP;
  FOR i IN 30..37 LOOP  -- chess: full, 8 of 8
    INSERT INTO registrations (category_id, user_id, status, created_at) VALUES (c_chess, u[i], 'confirmed', now() - ((i - 20) || ' hours')::interval);
  END LOOP;
  FOR i IN 38..40 LOOP  -- chess waitlist of 3, in arrival order
    INSERT INTO registrations (category_id, user_id, status, waitlisted_at, created_at)
    VALUES (c_chess, u[i], 'waitlisted', now() - ((41 - i) * interval '20 minutes'), now() - ((41 - i) * interval '20 minutes'));
  END LOOP;
  FOR i IN 41..44 LOOP  -- carrom: full, 4 of 4, no waitlist
    INSERT INTO registrations (category_id, user_id, status, created_at) VALUES (c_carrom, u[i], 'confirmed', now() - ((i - 30) || ' hours')::interval);
  END LOOP;

  -- Cricket: four registered teams and one still forming
  FOR k IN 1..4 LOOP
    INSERT INTO teams (category_id, name, captain_id, invite_code, status)
    VALUES (c_cricket, team_names[k], u[teams_spec[k][1]], upper(substr(md5(random()::text || k::text), 1, 8)), 'registered')
    RETURNING id INTO t;
    FOR i IN teams_spec[k][1]..teams_spec[k][2] LOOP
      INSERT INTO team_members (team_id, user_id, category_id) VALUES (t, u[i], c_cricket);
    END LOOP;
    INSERT INTO registrations (category_id, user_id, team_id, status, created_at)
    VALUES (c_cricket, u[teams_spec[k][1]], t, 'confirmed', now() - ((k * 3) || ' hours')::interval);
  END LOOP;
  INSERT INTO teams (category_id, name, captain_id, invite_code, status)
  VALUES (c_cricket, 'Wolves', u[59], upper(substr(md5(random()::text || 'w'), 1, 8)), 'forming') RETURNING id INTO t;
  INSERT INTO team_members (team_id, user_id, category_id) VALUES (t, u[59], c_cricket), (t, u[60], c_cricket);

  -- Registrations: Autumn Athletics Meet (closed, check-in under way) ---------------------------
  FOR i IN 1..12 LOOP   -- sprint: 12 confirmed, the first 7 already checked in
    INSERT INTO registrations (category_id, user_id, status, created_at)
    VALUES (c_sprint, u[i], CASE WHEN i <= 7 THEN 'checked_in'::registration_status ELSE 'confirmed'::registration_status END, now() - interval '5 days');
  END LOOP;
  FOR i IN 13..18 LOOP  -- long jump: 6 confirmed, the first 2 checked in
    INSERT INTO registrations (category_id, user_id, status, created_at)
    VALUES (c_jump, u[i], CASE WHEN i <= 14 THEN 'checked_in'::registration_status ELSE 'confirmed'::registration_status END, now() - interval '5 days');
  END LOOP;
  INSERT INTO check_ins (registration_id, checked_in_by, checked_in_at)
  SELECT id, organizer, now() - interval '10 minutes' FROM registrations
  WHERE status = 'checked_in' AND category_id IN (c_sprint, c_jump);

  -- Seat counts must equal confirmed + checked-in registrations (invariant 1) --------------------
  UPDATE categories c SET confirmed_count = (
    SELECT count(*) FROM registrations r WHERE r.category_id = c.id AND r.status IN ('confirmed', 'checked_in'))
  WHERE c.id IN (c_tt, c_bd, c_chess, c_carrom, c_cricket, c_sprint, c_jump, c_ms, c_ws, c_mixed, c_quiz);

  RAISE NOTICE 'Sample data created: 4 events, 11 categories, 60 students.';
END
$sample$;

-- A quick look at the result:
SELECT e.name AS event, e.status, c.name AS category, c.confirmed_count || ' / ' || c.capacity AS seats,
       (SELECT count(*) FROM registrations r WHERE r.category_id = c.id AND r.status = 'waitlisted') AS waitlisted
FROM events e JOIN categories c ON c.event_id = e.id
WHERE e.slug LIKE 'sample-%' ORDER BY e.starts_at, c.name;
