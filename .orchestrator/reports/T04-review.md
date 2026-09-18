# Review (task): T04

VERDICT: CHANGES_REQUIRED

## Critical
(none)

## Important
1. backend/app/stepper.py:381-390 · The "no reference image configured" `item_failed`
   return silently drops `next_delay_ms` (it is left at the `_step_result` default of
   `None`), where the pre-existing code returned `"next_delay_ms": int(pace.delay_s * 1000)`
   for this exact branch. The brief's Step 3 is explicit: "Keep the existing values for
   status, item, next_delay_ms and retry_after_ms exactly as they are today." Step 5's
   override for this branch only adds `release_now` + `next_step_ms=0`; it does not say to
   drop `next_delay_ms`. This is a real, observable regression: `frontend/src/lib/
   generateLoop.ts:136-139` does `const wait = result.next_delay_ms ?? 0` for `item_failed`
   and schedules the next `/step` call after that wait. Since a shop lacking a reference
   image fails on this exact branch for every item, the client will now hammer `/step`
   in an unpaced busy loop (0ms between calls) for the rest of the run, instead of the
   previous pace-delay-spaced retries — a behavior change outside the brief's Contracts.
   Fix: compute `pace_delay = (await pacer.get_or_create(db, key_hash)).delay_s` here (same
   pattern already used in the `NoImage` branch two blocks down) and pass
   `next_delay_ms=int(pace_delay * 1000)` into the `_step_result(...)` call.

## Minor
1. backend/app/stepper.py:293-358 · Brief Step 5 says "Wrap everything from the item claim
   onwards so the lease is always given back," but the `try:` that releases the lease on
   unexpected exceptions starts at line 358 — after the claim statement (line 307) and the
   whole `item is None` branch (lines 316-350). Those sections do release the lease via
   explicit `release_now` calls for their own logic, but if the claim `UPDATE ... RETURNING`
   itself raised (a DB error between the lease commit and the claim), the lease would not be
   released by any handler and would sit until `keypool.LEASE_SECONDS` (150s) expires it.
   Self-healing and low-probability (this statement runs immediately after a successful
   commit in the same session), so not blocking — but doesn't match the brief's literal
   instruction. Consider starting the try/except at the claim statement, or leave as-is with
   a short comment noting the accepted gap.

## Checked
- Signature change `generate_step(db, job, shop, api_key: str)` -> `(..., user: User)`:
  matches Contracts exactly; verified via `inspect.signature` that `api_key` is gone and
  `user` is present.
- `_step_result` helper signature matches the brief's spec verbatim; every `return` in
  `generate_step` goes through it (no bare dict literals remain) — TC6 holds.
- Step 2 lease block (`lanes`, `keypool.lease`, the `w is None` whole-job-failure path, the
  `wait = max(w, 250)` waiting path, `key_row/api_key` unpack, `job.api_key_hash = key_hash`)
  matches the brief's given code block line for line.
- TC2 holds: `lease is None` returns before the claim `SELECT ... FOR UPDATE SKIP LOCKED`
  statement runs, so no item can be claimed while paced.
- `item is None` sub-branches (recovered / inflight / complete): `release_now` is the first
  action, before any of the pre-existing logic, matching Step 5.
- RateLimited outcome: `pacer.on_rate_limit` unchanged, `keypool.release(db, key_hash,
  wait_s)`, then `keypool.wait_ms` for the pool-wide wait with `max(..., 250)` floor and a
  `wait_s`-based fallback only when no other key exists — TC4 holds (only this key's
  `next_allowed_at` moves; the returned wait is pool-wide, not this key's backoff).
- AuthFailure outcome: `keypool.disable` (verified it also clears `leased_until`, so the
  lease is released as a side effect — no separate release call needed), log line uses only
  `key_hint`, `enabled_count() == 0` keeps the existing whole-job-failure path, otherwise
  `waiting` with `lanes=keypool.lane_count(remaining_keys)` and the job stays RUNNING —
  TC3 holds.
- NoImage outcome: attempts/fallback-ladder logic unchanged; `pace_delay` freshly read via
  `pacer.get_or_create` (necessary since the old top-of-function `pace` variable no longer
  exists) and used for both `keypool.release` and `next_delay_ms` — matches brief.
- Success outcome: unchanged storing logic; `pacer.on_success` -> `keypool.release` ->
  `next_delay_ms=int(next_delay_s * 1000)`, `next_step_ms=0` — matches brief.
- Bottom `except Exception:` safety net: `release_now` added before re-raise, item still
  requeued — matches Step 7.
- TC5 (no raw key leak): read every `log(...)`/`JobEvent`/response-field use in the diff —
  only `key_hint` is ever passed, never `api_key`/the decrypted key. Independently re-ran the
  brief's own `grep -rn "log(db, job.*api_key\b" app/` — no match ("no key leak in logs").
  (Note: `item.last_error = f"auth failure: {e}"` on the AuthFailure path is unchanged from
  before this diff and thus out of scope here — not introduced by T04.)
- routers/jobs.py: `step_job` now calls `stepper.generate_step(db, job, shop, user)` with no
  `no_api_key` pre-check (moved into the pool as designed); `create_job`'s EXTRACT/CLASSIFY
  branch uses `keypool.pick_any(db, user.id)`; `decrypt` import removed and confirmed unused
  elsewhere in the file.
- routers/shops.py: `upload_reference` uses `keypool.pick_any(db, user.id)` in place of
  `require_gemini_key(user)`; the `require_gemini_key` import removed and confirmed unused
  elsewhere in the file.
- Write-set discipline: `git diff` shows only `backend/app/stepper.py`,
  `backend/app/routers/jobs.py`, `backend/app/routers/shops.py` changed — matches the
  brief's Write-set exactly; `backend/app/engine/keypool.py` (T02) untouched.
- Out-of-scope items confirmed untouched: the six step statuses (no new status added), the
  claim SQL, the stale-item sweep (`requeue_stale`), the prompt/fallback ladder, `run_host`,
  `run_export`, `build_export_rows`, and every frontend file.
- Independently re-ran the brief's Verify script's structural `python -c` assertions
  (ast/inspect checks + the log-leak grep) against the current tree — all pass, matching the
  T04 report's claimed Verify output. Did not re-run the full pytest suite (per reviewer
  instructions: rely on the orchestrator's gate, which the T04 report shows passed 104/104).
