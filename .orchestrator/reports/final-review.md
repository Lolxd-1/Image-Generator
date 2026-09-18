# Review (final): multi-key-pool run (a37b524..HEAD)
VERDICT: CHANGES_REQUIRED

## Critical
_none_

## Important

1. **frontend/src/screens/Login.tsx:56-58 (with backend/app/routers/auth.py:138-143)** · The legacy
   "Remove" button now silently deletes the operator's ENTIRE key pool. T03 changed
   `delete_gemini_key` to iterate every `ApiKey` row for the caller and `keypool.delete_key`
   each one (per T03 brief step 10), but no task's write-set included `Login.tsx`, so the card
   still renders a single hint (`me.gemini_key_hint`, now "oldest enabled pool key") above a
   confirm that reads *"Remove the stored Gemini key?"* - singular. · **Why it matters:** one
   click on a misleading, singular confirm irreversibly destroys 5-6 hand-pasted keys, which is
   exactly the asset this whole run exists to manage. There is no undo; the keys are Fernet
   blobs the operator must re-source. · **Fix:** in `Login.tsx`, either replace the Gemini-key
   card with a link to `/settings` (the pool is managed there now), or change the confirm to
   name the real scope - e.g. `Remove all ${me.key_count} Gemini key(s)?` - and label the button
   "Remove all keys". `MeOut.key_count` is already on the wire for exactly this.

2. **backend/tests/test_keypool.py (whole file)** · Two rows of PLAN's Test matrix are unmet:
   `test_legacy_migration_is_idempotent` (R5) is absent, and R1's row promises a test of the
   "lease SQL shape" that does not exist either. T02's brief scoped both out ("no DB fixture;
   do not add one"), so `migrate_legacy_keys` - the one thing standing between this deploy and
   every existing user losing their key - and the lease statement itself ship with no coverage.
   · **Why it matters:** PLAN's acceptance model is "every risk maps to a mitigation *and a
   test*"; two high-value risks currently rest on review alone. · **Fix:** the lease half needs
   no DB - add a pure test that compiles the statement and asserts the shape, e.g.
   `assert "FOR UPDATE OF pace_state SKIP LOCKED" in str(stmt.compile(dialect=postgresql.dialect()))`
   (I ran exactly this by hand; it passes - see Checked). For R5, either add the same kind of
   statement-level assertion or strike the row from PLAN's matrix so the gap is explicit rather
   than silent.

## Minor

3. **backend/app/engine/keypool.py:137-155** · `wait_ms` uses an OUTER join, so a key with no
   `pace_state` row yields `free_at(...) is None` -> `0` ("a key is free now"), while `lease`'s
   INNER join can never select it. A lane would then loop `waiting`/250ms forever and the job
   would neither progress nor fail. No current path creates that state (`add_key` and
   `migrate_legacy_keys` both create the pace row; `delete_key` only drops it when unshared), so
   this is defensive. Fix: give `wait_ms` the same inner-join predicate, or treat a missing pace
   row as "not available".

4. **backend/app/engine/keypool.py:110-115** · If the `ApiKey` row disappears between the lease
   UPDATE and the follow-up SELECT, `key_row` is `None` and `key_row.last_used_at = now` raises
   `AttributeError` (a 500) *after* `leased_until` was written - the lease then leaks for the
   full `LEASE_SECONDS`. Fix: `if key_row is None: await release_now(db, leased_hash); return None`.

5. **backend/app/stepper.py:293-356** · The claim statement, the stale-sweep / inflight /
   complete block and the claim commit all sit *outside* the `try:` that starts at line 358, so
   a DB error in any of them leaks the lease. Self-healing after 150s (R2), but the file's own
   comment at 498-500 ("an extra release is harmless, a missed one is not") argues for widening
   the `try` to start immediately after `leased` is unpacked.

6. **frontend/src/lib/generateLoop.ts:236-302** · `pause()` followed by `start()` while a step is
   in flight: the stale response's guards at line 265 now pass (the new run set `runningRef` and
   re-added lane `i` to `laneAliveRef`), so it (a) deletes the *new* run's in-flight marker at
   line 263, briefly allowing two concurrent requests on lane `i`, and (b) if it carries
   `complete`/`failed`/`job_not_running`/an error, calls `stopAll()` and kills the run the user
   just restarted. Both self-heal (the shared per-lane timer slot re-merges the chains; the user
   can click start again), and server-side leasing still prevents two lanes sharing a key. Fix:
   capture a `runIdRef.current` before the fetch and bail after it if the value changed.

7. **backend/app/stepper.py:319,332,345,350** · The three `item is None` returns (`waiting` x2,
   `complete`) omit `key_hint` even though a key *was* leased and released. PLAN's generate_step
   contract says "every return carries key_hint (the leased key)". Cosmetic - it only thins the
   `keyHints` list in the UI.

8. **backend/app/routers/storage.py:115-117,145-148** · `menu_bytes` and `export_bytes` are
   hard-zero (neither `MenuUpload` nor `Export` carries a byte count), so AC9's 1 GB gauge
   undercounts by everything that is not a dish/reference image. Deliberate per the T05 brief
   note, but `StorageSection.tsx:137-140` renders "Menu 0 B · Export 0 B" as if measured. Fix:
   render those two as "not counted" rather than `0 B`.

9. **backend/app/auth.py:88** · `require_gemini_key` has no callers left (T04 re-pointed
   `shops.py:upload_reference` at `keypool.pick_any`). Dead code; delete it.

10. **backend/app/routers/keys.py:77** · `_validate_live` runs *before* the duplicate check, so
    re-pasting a key already in the pool spends a real Gemini call and then 409s. Two concurrent
    adds of the same key also race `uq_api_keys_user_key` into an IntegrityError 500 rather than
    the documented 409. Fix: check for the existing `(user_id, key_hash)` first, and catch
    `IntegrityError` in `add_key` and re-raise it as the `conflict` AppError.

11. **backend/app/routers/keys.py:79-83 with KeyPoolSection.tsx:245-252** · In a multi-paste the
    single `label` field is sent with every key, so five keys all end up named the same string;
    the auto-`Key {n+1}` naming only applies when the label is blank. Fix: ignore `label` when
    `parts.length > 1`.

12. **backend/app/storage.py:54-64** · `delete_many` logs and swallows a failed Supabase
    `remove()`, so `DELETE /shops/{id}` can return 204 having deleted the rows while the blobs
    survive - AC8's "leaving no orphans" becomes "no orphan rows". Reasonable (the alternative
    strands the rows), but the operator gets no signal. Fix: count failures and surface them, or
    at least raise the log line to `error`.

13. **frontend/src/screens/Generate.tsx:90** · The ETA divides by `lanes` derived from the key
    list, not `loop.lanes` (the number actually running). Right after start, or while the server
    is shrinking lanes, the ETA is optimistic by that ratio.

## Checked

- **AC1 / R1 (no two concurrent steps share a key)** - compiled `keypool.lease`'s statement
  against the postgresql dialect. It emits
  `UPDATE pace_state SET leased_until=... WHERE api_key_hash = (SELECT ... JOIN api_keys ...
  ORDER BY ... LIMIT 1 FOR UPDATE OF pace_state SKIP LOCKED) RETURNING api_key_hash` - one
  statement, row-locked, skip-locked, the same shape as the pre-existing item claim. Two callers
  cannot select the same row; the loser gets `None` -> `waiting`. Correct.
- **AC2 (per-key pacing, 429 isolation)** - `release(delay)` writes `next_allowed_at` for one key
  hash only; `pacer.on_rate_limit` touches one `PaceState`; `wait_ms_until` returns the minimum
  over enabled keys, so a backed-off key never gates the others.
- **AC3 (auth failure disables one key)** - stepper.py:414-434: item back to QUEUED,
  `keypool.disable(hash, reason)`, job FAILED only when `enabled_count == 0`, else `waiting`
  with the recomputed `lanes`. Matches D6 and the six SPEC statuses.
- **AC4 / R3 (no strand at `generating`)** - lease precedes the claim (D3); `release_now` on the
  no-item path (line 319); the crash handler at 490-504 puts the item back to QUEUED and
  releases; the claim is only durable after the line-356 commit, so a mid-claim failure rolls
  back to QUEUED. Traced every `return` and `except` in `generate_step`: each one after a
  successful lease reaches exactly one of `release` / `release_now` / `disable` (which also nulls
  `leased_until`), except the window called out in finding 5, which the 150s expiry covers.
- **Lease leak audit** - `release`, `release_now` and `disable` all null `leased_until` and
  commit; `LEASE_SECONDS=150 > API_TIMEOUT=90`; the lease predicate treats an expired lease as
  free, so no leak is permanent.
- **Session/commit safety** - `expire_on_commit=False` (db.py:54), so the mid-step commits inside
  `lease`/`release` do not trigger a MissingGreenlet lazy-load on `job`/`shop`/`item`. The
  `job.api_key_hash` write autoflushes at the claim and holds the jobs-row lock across two
  statements only, not across the Gemini call.
- **AC5 (Settings key management)** - KeyPoolSection shows label (inline rename), `key_hint`,
  enabled/disabled plus reason, last used, pace, next-available and a Busy badge; add
  (live-validated, single or multi-paste), enable/disable, test and delete are all wired to
  `/auth/keys*`. Matches the contract.
- **AC6 (zip download)** - `shopImagesZipUrl` (pre-existing, backed by
  `images.py:_zip_dish_images`) is linked from the Catalog header and per shop in
  StorageSection. UI-only, as PLAN said.
- **AC7 (purge-images)** - nulls `Item.image_id` first, deletes blobs, then the `Image` rows, one
  commit; items/prices/imgbb URLs untouched; `CatalogCard` degrades to a placeholder when
  `image_id` is null so the catalogue still renders.
- **AC8 / R6 (delete catalog, no orphans)** - enumerated every table with a `shop_id` FK
  (`menu_uploads`, `items`, `images`, `jobs`, `exports`) plus `job_events` via `jobs`; all six
  are deleted, and `shops.reference_image_id`, `items.image_id`, `items.manual_ref_image_id` and
  `images.item_id` are nulled first, blobs before rows. No orphaned rows. Orphaned *blobs* only
  under finding 12.
- **AC9 (storage budget)** - `GET /storage` is grouped (three group-by queries, no N+1); UsageBar
  renders against 1 GiB with a per-shop breakdown. Accuracy caveat in finding 8.
- **AC10** - ran `python -m pytest -q` in backend: **109 passed in 142s**. Ran `npx tsc --noEmit`
  in frontend: **clean, exit 0**.
- **Multi-lane driver (generateLoop)** - lane lifecycle traced: `laneAlive`/`laneInFlight`/
  `laneTimers` stay consistent; grow and shrink both converge (a surplus lane stops itself on its
  next response; a dead lane is relaunched by `reconcileLanes` because `target > aliveSize`);
  lane 0 can never be stopped by the shrink path because `target >= 1`. Timer cleanup: the
  unmount effect has a stable `[clearAllTimers]` dep, clears every timer and both sets, and
  `mountedRef` gates every setState. `pause()` runs the same `stopAll()`. The only gap is
  finding 6 (pause -> start with a request in flight).
- **job_not_running stop path (R4)** - generateLoop.ts:247-252 catches `ApiError` with that code,
  clears `error` and calls `stopAll()`; `job_not_running` is in the `ErrorCode` union, and
  `stepper` raises it both for a non-RUNNING job and a non-generate kind. Healthy lanes are not
  surfaced as failures.
- **R8 (no plaintext key crosses a boundary)** - grepped the whole diff: plaintext only flows
  `lease`/`pick_any` -> `gemini.build_client`. `JobEvent` messages carry `key_hint` only;
  `keys.py:_validate_live` deliberately drops the raw exception text; `ApiKeyOut` exposes no
  ciphertext. (`disabled_reason` stores `str(e)[:300]` from the SDK and is shown in the UI -
  vendor auth errors do not echo the key today, but it is the one unsanitised provider string
  that reaches a response.)
- **Contracts vs PLAN** - the `keypool` constants and all nine coroutine signatures match;
  `StepResult` gained exactly `next_step_ms`/`key_hint`/`lanes` in both schemas.py and types.ts;
  the `api_keys` table, `uq_api_keys_user_key`, `pace_state.leased_until` and the best-effort
  idempotent `ALTER TABLE` (db.py:72-78, R7) match; every HTTP route in Contracts exists and the
  routers declare paths relative to `/api`.
- **Conventions and slop** - no new runtime dependency, no Alembic, no pacer constant re-tuned;
  `prompt.py`/`classify.py`/`extract.py`/`export.py` untouched; errors raised as
  `AppError(code, msg, status)`; `ConfigDict(from_attributes=True)` on `ApiKeyOut`; zip reuse via
  the existing `_zip_dish_images`; no TODO/FIXME/print/console.log added. Shops are not
  user-scoped anywhere in this codebase, so `storage.py`'s unscoped `_get_shop_or_404` follows
  the existing convention rather than opening a new hole.
