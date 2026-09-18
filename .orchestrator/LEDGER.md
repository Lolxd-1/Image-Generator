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
