# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-09-18T08:30:28Z init run=multi-key-pool branch=orch/multi-key-pool base=a37b524
- T01 done: api_keys + leased_until + schemas. gate PASS.
- T02 done: app/engine/keypool.py + 17 unit tests. gate PASS.
- T02 review: APPROVE, 0 critical/important, 2 minor.
- Ruling: T02 minor #1 (lease() does not null-check the ApiKey row after the pace UPDATE; a
  concurrent delete_key could make it None) is deferred to FIX1 rather than re-opening T02 —
  why: the window is a concurrent delete of a key mid-lease, the blast radius is one 500 on
  one /step call, and the lane retries — cost if wrong: one spurious 500 in a log.
- T03 done: /api/auth/keys CRUD + test, pool-aware /me, boot backfill. gate PASS.
- T04 done: generate_step leases a key per call; auth failure disables one key, not the job. gate PASS.
- T05 done: /api/storage, /shops/{id}/storage, purge-images, DELETE /shops/{id}. gate PASS.
- T04 review: CHANGES_REQUIRED, 1 important (no-reference-image branch drops next_delay_ms ->
  the client busy-loops /step at 0ms). Fix dispatched to the T04 executor, round 1.
- T04 fix round 1 applied (next_delay_ms restored on the missing-reference branch). re-gate PASS.
- Finding (operator, not code): all 7 of the user's Gemini keys return 403 SERVICE_DISABLED -
  aiplatform.googleapis.com is not enabled in any of their 7 GCP projects. The pool stays
  empty until the user enables it; nothing in the build depends on it.
- T06 done: N-lane generate loop + key/storage hooks. gate PASS.
