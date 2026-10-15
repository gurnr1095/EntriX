## Observations

Written after reading the numbers above. The figures themselves are generated; this section
only interprets them, and says where it is guessing.

- **Correctness held under load.** In both runs the hot category ended with exactly its capacity
  confirmed and the seat counter equal to it, with a large number of people waitlisted, no failed
  requests, and all five invariants intact. That is the property the project exists to provide.
- **The system saturated; I did not find out which resource was the limit.** In the per-second
  history, latency climbed while the users ramped up, and throughput then flattened at a plateau
  for the rest of the run even though the user count stayed at its peak (with caching off the
  plateau was lower and the latency higher). That pattern means something was at capacity. I did
  not profile CPU per process, so I cannot say whether it was the single API process (which can use
  at most one CPU core), Postgres, or the shared laptop. The API process is the prime suspect, but
  that is a guess.
- **Caching on made browse responses much faster, and that is measured.** Cached reads skip the
  database entirely (the test suite checks that a cache hit sends no SQL), and the table above shows
  the effect on both browse endpoints.
- **Registration also got faster with caching on, but registrations do not use the cache.** The
  likely reason is that they no longer compete with browse requests for the same API process and
  database connections. That is an inference from one run each; I did not isolate it (for example
  by running registrations alone), so treat it as a hypothesis.
- **Registration is the slowest endpoint in both runs.** It does the most work per request (create
  the person on first sight, run the transaction, queue the email), and once the category is full
  every new registration takes the category lock to join the waitlist in order, so those requests
  queue behind one another by design. I would expect that serialization to be part of the cost, but I
  did not measure how much of the latency it accounts for. It is the price of exact ordering and of
  invariant 3, and the hot-row trade-off discussed in DESIGN.md.
- **The achieved request mix is not 80/20.** The 4:1 ratio is by number of virtual users. Because
  registration responses were slow, launch users sent fewer requests than browse users, so the
  registration share of requests came out lower than 20% (see the share lines above). The spec's
  "80% browse, 20% launch" was met in users, not in requests.
- **Rows in the database exceed what Locust counted.** The most likely cause is registrations that
  were still in flight when Locust stopped: the server finished them, but the client had already
  moved on, so they were never recorded. I did not verify this directly. No request failed and no
  invariant broke, so it does not indicate a correctness problem.
- **Only one run per configuration.** The difference between caching off and on is large, but the
  exact multiples should not be quoted as precise.
- **Not measured here:** more than one API worker, a database on separate hardware, Clerk token
  verification, and the rate limiter under load. This is a baseline on a laptop, not a capacity
  claim for a deployed system.
