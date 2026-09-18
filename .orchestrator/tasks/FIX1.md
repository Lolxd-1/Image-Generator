# FIX1: apply the final-review findings
Wave: 8 · Deps: T07 · Risk: med · Model: sonnet

## Goal
Every Important and Minor finding in the final review is fixed or explicitly ruled on, with
the full suite and typecheck still green.

## Context
The run is feature-complete and gated. `.orchestrator/reports/final-review.md` lists 2
Important and 11 Minor findings (plus one deferred from the T02 review). This task closes
them. Read that report first - it has the exact file:line and rationale for each.

## Read first
- `.orchestrator/reports/final-review.md`: the findings, numbered 1-13. THE source for this task.
- `.orchestrator/reports/T02-review.md`: its minor #1 is the same issue as final-review #4.
- `.orchestrator/PLAN.md`: the Contracts block and the Test matrix (one row gets struck here).
- The files named in each finding.

## Write-set
- modify: frontend/src/screens/Login.tsx
- modify: frontend/src/lib/generateLoop.ts
- modify: frontend/src/screens/Generate.tsx
- modify: frontend/src/screens/settings/StorageSection.tsx
- modify: frontend/src/screens/settings/KeyPoolSection.tsx
- modify: backend/app/engine/keypool.py
- modify: backend/app/stepper.py
- modify: backend/app/routers/keys.py
- modify: backend/app/routers/storage.py
- modify: backend/app/storage.py
- modify: backend/app/auth.py
- modify: backend/tests/test_keypool.py
- modify: .orchestrator/PLAN.md

## Contracts
No signature changes. `Storage.delete_many` keeps returning `None`. The six step statuses,
every route path and every response field stay exactly as they are.

## Steps
Work through the findings in this order. Each numbered item is that finding's number in the
review report.

1. **(Important 1) `Login.tsx`** - the Gemini-key card's "Remove" now destroys the whole pool.
   Replace that card's destructive action: keep showing whether a key is on file, but change
   the confirm text to name the real scope using `me.key_count`, e.g.
   `Remove all ${me.key_count} Gemini key(s)? This cannot be undone.`, and label the button
   "Remove all keys". Add a line under it linking to `/settings` ("Manage the key pool in
   Settings"). Do not change what the endpoint does.
2. **(Important 2) `tests/test_keypool.py`** - add `test_lease_statement_is_skip_locked`: build
   the same statement `keypool.lease` uses (extract it into a module-level helper
   `def _lease_stmt(user_id, now)` in `keypool.py` that both `lease` and the test call, so the
   test cannot drift from the real query), compile it against
   `sqlalchemy.dialects.postgresql.dialect()` and assert the compiled SQL contains
   `FOR UPDATE OF pace_state` and `SKIP LOCKED` and `UPDATE pace_state`.
   For R5, add `test_migrate_legacy_keys_is_idempotent_by_construction`: assert via
   `inspect.getsource(keypool.migrate_legacy_keys)` that it skips an existing
   `(user_id, key_hash)` rather than inserting - and in `PLAN.md`'s Test matrix, change the R5
   row's test name to this one so the matrix matches reality.
3. **(Minor 4, also T02 review minor 1) `keypool.py:lease`** - after the lease UPDATE, if the
   follow-up `ApiKey` SELECT returns `None`, call `await release_now(db, leased_hash)` and
   return `None` instead of raising `AttributeError` on a leaked lease.
4. **(Minor 3) `keypool.py:wait_ms`** - an outer-joined key with no `pace_state` row currently
   reports "free now" while `lease`'s inner join can never pick it, which would loop a lane
   forever. Make the two agree: use the same inner-join predicate in `wait_ms` (a key with no
   pace row is not a candidate).
5. **(Minor 5) `stepper.py`** - widen the `try:` so it starts immediately after `leased` is
   unpacked, covering the claim statement, the stale-sweep / inflight / complete block and the
   claim commit. Its `except` must still `release_now` and re-raise. Keep the existing
   item-requeue behaviour for the paths that already have it, and make sure a failure BEFORE an
   item is claimed does not try to touch `item`.
6. **(Minor 7) `stepper.py`** - the three `item is None` returns (`waiting` x2, `complete`) must
   carry `key_hint`, per PLAN's contract ("every return carries key_hint").
7. **(Minor 6) `generateLoop.ts`** - add a `runIdRef` incremented by `start()` and `stopAll()`;
   each lane captures it before its fetch and bails out after the response if it changed. This
   stops a stale in-flight response from a paused run from clearing the new run's in-flight
   marker or calling `stopAll()` on the run the user just restarted.
8. **(Minor 13) `Generate.tsx`** - divide the ETA by the lanes actually running when the loop is
   running (`loop.lanes || lanes`), falling back to the key-derived `lanes` before start so it
   can never divide by zero.
9. **(Minor 8) `StorageSection.tsx`** - menu and export bytes are not measured (neither row
   carries a byte count). Render those two as "not counted" with their counts, not as `0 B`,
   so the gauge does not claim a precision it does not have. Add one line under the gauge:
   "Menu photos and exports are counted but not sized."
10. **(Minor 10) `routers/keys.py` + `keypool.add_key`** - check for an existing
    `(user_id, key_hash)` BEFORE spending a live validation call, and in `add_key` catch
    `sqlalchemy.exc.IntegrityError` and re-raise it as the documented
    `AppError("conflict", ..., 409)` so a concurrent double-add cannot 500.
11. **(Minor 11) `routers/keys.py` or `KeyPoolSection.tsx`** - in a multi-paste, every key
    currently gets the same label. Fix it in `KeyPoolSection.tsx`: when the paste splits into
    more than one key, send no label and let the server auto-name them `Key {n}`.
12. **(Minor 12) `storage.py:delete_many`** - raise the swallowed-failure log from `warning` to
    `error` and include the batch size and the first key in the message, so an orphaned blob
    leaves a searchable trace. Keep swallowing (the alternative strands DB rows).
13. **(Minor 9) `auth.py`** - delete `require_gemini_key`; it has no callers left. Remove any
    import that becomes unused.

## Test cases
- TC1 (happy): `test_lease_statement_is_skip_locked` passes and would fail if `skip_locked` or
  `of=PaceState` were removed from `keypool.lease`.
- TC2 (happy): `test_migrate_legacy_keys_is_idempotent_by_construction` passes.
- TC3 (edge, finding 4): `lease` returns `None` (not an exception) when the key row vanishes,
  and the lease it just took is released.
- TC4 (edge, finding 3): a `Candidate` built for a key with no pace row is excluded from
  `wait_ms`'s candidate list.
- TC5 (error, finding 5): an exception raised by the claim statement releases the lease.
- TC6 (edge, finding 7): the `complete` return includes a non-null `key_hint`.
- TC7 (edge, finding 10): adding a key already in the pool returns 409 without making a Gemini
  call (assert by reading the code path - the duplicate check precedes `_validate_live`).
- TC8 (happy): `npx tsc --noEmit` clean; `npx vite build` succeeds.
- TC9 (edge, finding 1): `Login.tsx` no longer offers a singular "Remove the stored Gemini key?"
  confirm.

## Verify
```bash
cd backend && python -m pytest -q && python -c "
import inspect, app.engine.keypool as k, app.auth as a, app.stepper as s
assert not hasattr(a, 'require_gemini_key'), 'dead require_gemini_key still present'
src = inspect.getsource(k.lease); assert 'release_now' in src, 'lease does not release on a vanished key row'
assert '_lease_stmt' in inspect.getsource(k), 'shared lease statement helper missing'
print('FIX1 backend OK')" && cd ../frontend && npx tsc --noEmit && node -e "
const fs=require('fs');
const l=fs.readFileSync('src/screens/Login.tsx','utf8');
if(/Remove the stored Gemini key\?/.test(l)){console.error('singular confirm still present');process.exit(1)}
const g=fs.readFileSync('src/lib/generateLoop.ts','utf8');
if(!g.includes('runIdRef')){console.error('runIdRef missing');process.exit(1)}
console.log('FIX1 frontend OK')"
```

## Done when
- [ ] every finding above is fixed, or (only where the brief says so) explicitly reflected in PLAN
- [ ] every test case passes via Verify
- [ ] the full backend suite and `tsc --noEmit` are green
- [ ] no behaviour outside the findings changed

## Out of scope
- Any change to the six step statuses, route paths, response field names, or the DB schema.
- Re-tuning the pacer or the lease duration.
- New dependencies or a frontend test runner.

## Notes
- Finding 5 (widening the `try`) is the one with real regression potential: re-read the whole
  `generate_step` after the change and confirm the `item is None` path still returns `waiting`
  or `complete` exactly as before, and that the `except` cannot dereference an unbound `item`.
- The review's "Checked" section lists what is already correct - do not rework any of it.
