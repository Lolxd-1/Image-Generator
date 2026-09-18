# Review (rereview): FIX1 (1246b1030d77da84f4529634763ff1f12d25f1b2..HEAD)
VERDICT: APPROVE

## Critical
_none_

## Important

1. **Login.tsx destructive "Remove" button** — FIXED. `Login.tsx:56-58` now reads
   `` `Remove all ${count} Gemini key(s)? This cannot be undone.` `` using `me?.key_count`, the
   button is relabeled "Remove all keys" (`Login.tsx:133`), and a new `Link to="/settings"`
   ("Manage the key pool in Settings") was added below it. `onRemoveKey` still calls the same
   `deleteKey.mutateAsync()` — endpoint behaviour untouched, as the brief required. No regression:
   `key_count` was already on `MeOut`, confirmed present pre-fix.

2. **test_keypool.py missing R1/R5 coverage** — FIXED. `test_lease_statement_is_skip_locked`
   compiles `keypool._lease_stmt` (a new module-level helper both `lease` and the test call, so
   they cannot drift) against the postgresql dialect and asserts `UPDATE pace_state`,
   `FOR UPDATE OF pace_state`, and `SKIP LOCKED` all appear — I ran it, passes.
   `test_migrate_legacy_keys_is_idempotent_by_construction` asserts via `inspect.getsource` that
   the existing-row check precedes `db.add(` and that a `continue` sits between them — a
   source-shape test, not a DB-backed one, but that matches the "no DB fixture" constraint the
   original T02 brief set, and PLAN.md's R5 row was updated to name this test exactly. Ran the
   full suite: 112 passed (109 baseline + 3 new: these two plus the wait_ms inner-join test below).

## Minor

3. **keypool.py `wait_ms` outer-join mismatch** — FIXED. `wait_ms` now uses `.join(PaceState, ...)`
   (inner join, matching `lease`'s candidate predicate) instead of `.outerjoin`, and the
   `Candidate` construction no longer needs the `pace.x if pace else None` guards since a row is
   never `None` under an inner join. New test
   `test_wait_ms_uses_inner_join_so_a_keyless_pace_row_is_excluded` asserts `"outerjoin" not in
   src` and `.join(PaceState` is present — passes.

4. **keypool.py `lease` AttributeError on vanished key row** — FIXED. `lease` now checks
   `if key_row is None: await release_now(db, leased_hash); return None` before touching
   `key_row.last_used_at` (`keypool.py:119-125`). Matches T02-review minor #1 and this report's
   finding 4 identically.

5. **stepper.py widened try block** — FIXED, and the specific regression risk called out in the
   dispatch does not materialize. Traced the whole rewritten `generate_step`:
   - `item: Item | None = None` is declared immediately before the `try:`, and the `try:` now
     starts right after `leased` is unpacked — before the claim statement, the stale-sweep /
     inflight / complete block, and the claim commit, exactly as directed.
   - The `except Exception:` now does `if item is not None: item.status = ItemStatus.QUEUED`
     before `release_now` — so a failure *before* Step 3 claims an item (e.g. the claim UPDATE
     itself raising) cannot dereference an unbound `item`. Confirmed by reading every line between
     `try:` and `except Exception:` — no other code path leaves `item` in an inconsistent
     half-bound state.
   - All three `item is None` returns (`waiting`/recovered, `waiting`/inflight, `complete`) now
     pass `key_hint=key_hint` — this also closes finding 7 (see below), and I checked `_step_result`
     accepts and forwards `key_hint` for all of them.
   - Regression check on the "release twice" path: if `release_now(db, key_hash)` at the top of
     the `item is None` block itself raises, or if the later `db.commit()` in that block raises,
     the `except` re-runs `release_now` on the same `key_hash`. `release_now` does an unconditional
     `UPDATE ... SET leased_until=None` with no precondition, so a second call is a no-op, not a
     double-release of a different lease — matches the file's own comment ("an extra release is
     harmless, a missed one is not"). This is the same accepted risk class the *original*,
     narrower `try` already carried for Step 5-8 (which already contains many DB writes -
     `pacer.get_or_create`, `keypool.release`/`disable`, `db.add(image)` - that can raise and be
     followed by another DB write in the `except`); widening the `try` extends an existing,
     accepted failure mode to more statements rather than introducing a new one. I did not find a
     path where `except` runs with `item` bound to a row it never claimed, or where the lease is
     left leased after an exception.
   - No test exercises TC5 (exception during the claim releases the lease) with a live DB — the
     project has no `test_stepper.py` and no DB fixture (same constraint test_keypool.py declares),
     so this was necessarily verified by code reading only, consistent with the brief's own Verify
     block (which also only source-inspects, not DB-tests, the stepper.py changes). Not a new gap
     introduced by this fix; stepper.py had zero tests before it either.

6. **generateLoop.ts pause/start race** — FIXED. `runIdRef` is bumped in both `stopAll()` and
   `start()` (`generateLoop.ts:114-116,162-163,325-326`); each lane's step function captures
   `runId = runIdRef.current` before the fetch and bails (`return`, before touching
   `laneInFlightRef`/`laneAliveRef`/`runningRef`) if `runId !== runIdRef.current` on both the
   catch path and the success path. Verified `stopAll()` already clears `laneInFlightRef` and
   `laneAliveRef` wholesale, so the stale-response early-return correctly leaves those to the new
   run's own bookkeeping rather than needing to "undo" anything itself. `tsc --noEmit` clean.

7. **stepper.py missing key_hint on `item is None` returns** — FIXED (same edit as finding 5):
   all three returns now carry `key_hint=key_hint`.

8. **StorageSection.tsx "0 B" for uncounted menu/export bytes** — FIXED. Row now renders
   `Menu {shop.menu_count} (not counted)` and `Export {shop.export_count} (not counted)` instead
   of `formatBytes(shop.menu_bytes/export_bytes)`, and a caption "Menu photos and exports are
   counted but not sized." was added under the usage bar. `menu_count`/`export_count` already
   existed on both `schemas.py`'s `ShopStorage` and `types.ts` pre-fix, so no new field was needed.

9. **auth.py dead `require_gemini_key`** — FIXED. Function and the now-unused `from app import
   crypto` import are both removed. Grepped the whole repo: no remaining references outside
   `.orchestrator/` docs.

10. **routers/keys.py validate-before-duplicate-check / IntegrityError race** — FIXED. `create_key`
    now looks up `(user_id, key_hash)` and raises the 409 `conflict` `AppError` *before* calling
    `_validate_live` (`routers/keys.py:78-84`, ahead of the `anyio.to_thread.run_sync` call).
    `keypool.add_key` wraps `pacer.get_or_create` + `db.commit()` in `try/except IntegrityError`,
    rolls back, and re-raises as the same `AppError("conflict", ..., 409)` — the `await
    db.rollback()` before re-raising avoids leaving the session in a needs-rollback state for the
    caller, which is the correct pattern (and notably more careful than the "extra DB call inside
    an except" pattern discussed in finding 5, though that one is pre-existing and accepted).

11. **KeyPoolSection.tsx multi-paste label collision** — FIXED. The loop now calls
    `addKey.mutateAsync({ key, label: undefined })` unconditionally inside the multi-paste branch,
    so the server's blank-label auto-naming (`Key {n}`) applies to every key; a comment explains
    why. Single-paste (the `parts.length === 1` branch, unchanged) still sends the user's label.

12. **storage.py `delete_many` swallowed failure** — FIXED. Log level raised from `warning` to
    `error`, and the message now includes the batch size and `batch[0]` (the first key) for a
    searchable trace, per the brief. Still swallows (intentional, to avoid stranding DB rows).

13. **Generate.tsx ETA divide-by-wrong-lanes** — FIXED. `etaLanes = loop.running ? (loop.lanes ||
    lanes) : lanes` — divides by the server-reported running lane count once the loop is running
    (falling back to the key-derived estimate only if `loop.lanes` is still 0, e.g. immediately
    after start), and by the key-derived `lanes` before start. Cannot divide by zero: `lanes` is
    derived from the key list and `loop.lanes` falls back to it.

## Checked
- Full diff `1246b103..HEAD` matches FIX1's write-set exactly (11 code files + PLAN.md + this
  report's predecessor); nothing outside the findings changed.
- `cd backend && python -m pytest -q`: **112 passed in 145s** (109 baseline + 3 new tests).
- FIX1's Verify script (backend half): ran verbatim, printed `FIX1 backend OK` (the bcrypt
  `__about__` AttributeError in the same output is an unrelated, pre-existing passlib/bcrypt
  version-probe warning, not a failure — exit path reached `print(...)`).
- `cd frontend && npx tsc --noEmit`: clean, exit 0.
- FIX1's Verify script (frontend half, the inline `node -e`): ran verbatim, printed
  `FIX1 frontend OK`.
- Re-read all of `generate_step` end-to-end after the finding-5/7 edit (not just the diff hunk) to
  confirm the `except` branch, the three early returns, and every other return in Steps 5-9 still
  match their pre-fix behavior aside from the added `key_hint`.
- Grepped for `require_gemini_key` and `label.trim()` remnants to confirm findings 9 and 11 left
  no dangling references.
- Confirmed `menu_count`/`export_count` predate this fix in both `schemas.py` and `types.ts`, so
  finding 8's fix doesn't rely on an undeclared field.
