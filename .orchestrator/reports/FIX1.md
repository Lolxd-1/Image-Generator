# FIX1: apply the final-review findings

## What was implemented
Every Important (2) and Minor (11) finding from `.orchestrator/reports/final-review.md` is
fixed, plus the PLAN.md R5 test-matrix row now matches reality.

1. **Login.tsx (Important 1)** - "Remove" -> "Remove all keys"; confirm text now reads
   `Remove all ${me.key_count} Gemini key(s)? This cannot be undone.`; added a link to
   `/settings` under the buttons. `deleteKey` endpoint behaviour untouched.
2. **test_keypool.py (Important 2)** - extracted `keypool._lease_stmt(user_id, now)` (module
   level, used by both `lease` and the new test) and added
   `test_lease_statement_is_skip_locked` (compiles against the postgresql dialect, asserts
   `UPDATE pace_state`, `FOR UPDATE OF pace_state`, `SKIP LOCKED`) and
   `test_migrate_legacy_keys_is_idempotent_by_construction` (asserts via
   `inspect.getsource` that the existing-row check precedes and `continue`s before `db.add`).
   PLAN.md's R5 test-matrix row renamed to the new test.
3. **keypool.py:lease (Minor 4 / T02-review minor 1)** - if the post-lease `ApiKey` SELECT
   returns `None` (row vanished), `release_now` the lease and return `None` instead of
   raising `AttributeError`.
4. **keypool.py:wait_ms (Minor 3)** - switched from `outerjoin` to `join` against
   `PaceState` so a key with no pace row is excluded from the candidate set, matching
   `lease`'s inner join (prevents an infinite `waiting` loop). Added
   `test_wait_ms_uses_inner_join_so_a_keyless_pace_row_is_excluded` (construction check, no
   DB fixture available).
5. **stepper.py (Minor 5)** - widened the `try:` in `generate_step` to start right after
   `leased` is unpacked, now covering the claim statement, the stale-sweep/inflight/complete
   block, and the claim commit. `item` is initialized to `None` before the try; the `except`
   only sets `item.status = QUEUED` when `item is not None`, then always `release_now`s and
   re-raises.
6. **stepper.py (Minor 7)** - the three `item is None` returns (`waiting` x2, `complete`) now
   pass `key_hint=key_hint`.
7. **generateLoop.ts (Minor 6)** - added `runIdRef`, incremented in `start()` and `stopAll()`.
   Each lane captures `runId` before its fetch and bails immediately (before touching
   `laneInFlightRef`/state) if `runIdRef.current` changed by the time the response/error
   arrives - stops a stale pause-then-start response from clearing the new run's in-flight
   marker or calling `stopAll()` on it.
8. **Generate.tsx (Minor 13)** - ETA now divides by `loop.running ? loop.lanes || lanes :
   lanes` instead of always the key-derived `lanes`.
9. **StorageSection.tsx (Minor 8)** - menu/export rows now render their counts as
   "N (not counted)" instead of `formatBytes(0)`; added a line under the usage gauge: "Menu
   photos and exports are counted but not sized."
10. **routers/keys.py + keypool.add_key (Minor 10)** - `create_key` now checks for an
    existing `(user_id, key_hash)` before the live Gemini validation call. `add_key` wraps
    `pacer.get_or_create` (whose own `flush()` can hit the same race, since it shares the
    key_hash as the pace_state PK) and `db.commit()` in a `try/except IntegrityError`,
    re-raising as `AppError("conflict", ..., 409)`.
11. **KeyPoolSection.tsx (Minor 11)** - multi-paste now always sends `label: undefined` per
    key (ignoring the typed label), so the server auto-names each "Key {n}".
12. **storage.py:delete_many (Minor 12)** - raised `logger.warning` to `logger.error` and
    added the batch size and first key to the message.
13. **auth.py (Minor 9)** - deleted `require_gemini_key` (no callers) and its now-unused
    `from app import crypto` import.

## Files changed
`frontend/src/screens/Login.tsx`, `frontend/src/lib/generateLoop.ts`,
`frontend/src/screens/Generate.tsx`, `frontend/src/screens/settings/StorageSection.tsx`,
`frontend/src/screens/settings/KeyPoolSection.tsx`, `backend/app/engine/keypool.py`,
`backend/app/stepper.py`, `backend/app/routers/keys.py`, `backend/app/routers/storage.py`
(untouched - already correct per the review), `backend/app/storage.py`, `backend/app/auth.py`,
`backend/tests/test_keypool.py`, `.orchestrator/PLAN.md`.

Note: `backend/app/routers/storage.py` was in the Write-set but needed no change - finding 8
(Minor) is entirely a frontend rendering fix (StorageSection.tsx); the router's `menu_bytes`/
`export_bytes` being hard-zero is already documented/deliberate per the T05 brief and the
final review itself.

## Tests added (backend/tests/test_keypool.py)
- `test_lease_statement_is_skip_locked` - proves TC1: fails if `skip_locked` or `of=PaceState`
  were removed from the lease statement.
- `test_migrate_legacy_keys_is_idempotent_by_construction` - proves TC2.
- `test_wait_ms_uses_inner_join_so_a_keyless_pace_row_is_excluded` - proves TC4 (the finding-3
  fix) by construction, consistent with this file's no-DB-fixture convention.
- TC3 (finding 4, `lease` returns `None` on a vanished key row) is proved by the Verify
  script's own `inspect.getsource` check (`'release_now' in inspect.getsource(k.lease)`), not
  a new pytest function.
- TC5/TC6 (stepper.py findings 5 and 7) and TC7 (finding 10) have no dedicated test file in
  the Write-set (no `test_stepper.py` exists in this repo - stepper.py has no DB fixture to
  test against) - verified by full-suite pass, `python -c` source inspection where scripted,
  and manual re-read of the whole `generate_step` control flow per the brief's Notes.
- TC8: `npx tsc --noEmit` and `npx vite build` both run clean (vite build isn't in the scripted
  Verify block but was run manually to confirm).
- TC9: proved by the Verify script's node check on `Login.tsx`.

## Verify
`orch.sh verify FIX1` -> exit 0.
```
112 passed in 139.13s
FIX1 backend OK
FIX1 frontend OK
```
(109 pre-existing + 3 new tests = 112. The "bcrypt version" traceback is pre-existing passlib
noise, unrelated to this change.)

Also ran `npx vite build` manually (not in the scripted Verify): built clean in 2.48s.

## Self-review notes
- Caught and fixed a bug in my own first pass: `pacer.get_or_create(db, h)` in `add_key` calls
  `db.flush()` internally, which could itself raise `IntegrityError` on the pace_state PK
  (same key_hash) in the exact race this fix targets. Moved that call inside the
  `try/except IntegrityError` alongside `db.commit()` rather than leaving it unprotected
  before the try block.
- Re-read the entire widened `generate_step` after the stepper.py change per the brief's
  Notes: every `return` inside the new try still returns `waiting`/`complete` exactly as
  before (just with `key_hint` added to three of them); the `except` cannot dereference an
  unbound `item` since it's initialized to `None` before the try and only ever read as
  `item is not None`.
- Confirmed no other change to route paths, response field names, step statuses, or the DB
  schema; no new dependencies; pacer constants untouched.
- `ruff check` on the five changed backend files: all checks passed. `py_compile` on all five:
  clean.

## Concerns
None.

## Discoveries
- `backend/app/routers/storage.py` was listed in the brief's Write-set but required no edit -
  finding 8 is purely a frontend display fix.
- `pacer.get_or_create`'s `db.flush()` is a second place (besides `db.commit()`) where the
  duplicate-key race in `add_key` can surface `IntegrityError` - worth remembering for any
  future work that adds more DB writes between `db.add(key_row)` and its commit.
