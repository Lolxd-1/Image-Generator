# LEDGER (append-only, one line per event)
<!-- format: - <UTC time> <event>. Rulings: "Ruling: <decision> — <why> — <cost if wrong>" -->
- 2026-09-18T08:30:28Z init run=multi-key-pool branch=orch/multi-key-pool base=a37b524
- T01 done: api_keys + leased_until + schemas. gate PASS.
- T02 done: app/engine/keypool.py + 17 unit tests. gate PASS.
