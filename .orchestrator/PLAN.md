# PLAN: Gemini key pool (5-6 keys, parallel lanes) + catalog delete/download + Settings page
run: multi-key-pool · branch: orch/multi-key-pool · base: a37b524 · created: 2026-09-18

## Requirement (verbatim)
> now the main that is actually a bottle neck is the Google Gemini API that is rate limited.
> now what we will do is, we will use 5-6 diff api key's from different accounts. that will
> get us images faster atleast 5-6x faster that what is current speed. so for that. I want
> you to change the api routing and this smartly. so whatever I am uploading, this is getting
> generated properly. and make some changes like, there should be one option of delete the
> catlog. and one option of downloading these images. as we only [have] 1 gb of storage on
> supabase. so for that. we want to get it that way. make this. properly. I will paste the
> Gemini keys here. expect 4-5 gemini keys. add settings page, where I can upload the gemini
> keys.

## Goal
Route every Gemini call through a pool of N user-supplied API keys with server-side
per-key leasing and pacing, so the browser can drive N generate lanes in parallel
(~N x throughput); and give the operator a Settings page to manage keys plus
download-then-delete controls to stay inside Supabase's 1 GB free tier.

## Non-goals
- No server-side background worker: generation stays browser-driven `/step` (survives
  restarts, no always-on process on a free host).
- No Alembic. Schema changes are `create_all` plus one idempotent `ADD COLUMN IF NOT EXISTS`.
- No change to prompt building, extraction, classification or export logic.
- No per-key quota accounting or billing dashboards. Pace state is the only per-key telemetry.

## Acceptance criteria
- AC1: With K enabled keys in the pool, K generate `/step` calls can be in flight at once,
  each served by a DIFFERENT key; no two concurrent steps ever receive the same key.
- AC2: A key that just served a call is not handed out again until its own pace delay has
  elapsed; a 429 on one key slows only that key and never blocks the others.
- AC3: An auth failure (bad or revoked key) disables ONLY that key and the run continues on
  the rest; the job fails only when no enabled key is left.
- AC4: `/step` never claims an item when no key is free - it returns `waiting` with the ms
  until the soonest key frees, and no item is ever stranded in `generating` by a busy pool.
- AC5: Settings page lists every key (label, last-4 hint, enabled, last used, current pace,
  next available), and can add (live-validated), rename, enable/disable, test and delete keys.
- AC6: A shop's dish images can be downloaded as one zip from the UI.
- AC7: "Free up space" deletes a shop's dish image blobs and rows and reports bytes freed;
  items, prices and imgbb URLs survive so the SmartBiz export still works.
- AC8: "Delete catalog" removes the shop and every storage object and DB row belonging to it,
  leaving no orphans; it is confirm-gated in the UI.
- AC9: Settings shows storage used against the 1 GB budget, per shop and in total.
- AC10: The whole existing test suite still passes and `tsc --noEmit` is clean.

## Assumptions
- A1: Keys belong to the signed-in user (matches today's `users.gemini_key_enc`) · default: per-user `api_keys` rows · asked user: no
- A2: Lane count = min(enabled keys, 6) · default: cap 6, decided browser-side from a server hint · asked user: no
- A3: The existing single key must keep working after deploy · default: backfilled into the pool at boot · asked user: no
- A4: "Delete the catalog" means the whole shop and its data; "free up space" (images only) is offered alongside it · asked user: no
- A5: The same key added by two users shares one pace row (the quota belongs to the key, not the user) · asked user: no

## Context map
- `backend/app/models.py` - every table; `PaceState` is keyed by api-key hash already.
- `backend/app/engine/pacer.py` - grow/shrink/backoff maths, DB-backed per key hash. Reuse verbatim.
- `backend/app/engine/gemini.py` - `key_hash`, `build_client`, `is_auth_error`, `is_rate_limit`, typed errors.
- `backend/app/stepper.py:generate_step` - the one-image-per-request loop; today takes a single `api_key` string.
- `backend/app/routers/jobs.py` - decrypts `user.gemini_key_enc` and passes it in.
- `backend/app/routers/auth.py` - single-key PUT/DELETE plus `/me`.
- `backend/app/routers/images.py` - `_zip_dish_images` streaming zip already exists (AC6 is UI-only).
- `backend/app/storage.py` - Supabase/local object store; `delete` handles one key at a time.
- `frontend/src/lib/generateLoop.ts` - single-lane client driver; `runningRef` guards one loop.
- `frontend/src/screens/Generate.tsx` - starts the loop, shows progress and ETA.

Flow: browser POST /api/jobs/{id}/step -> stepper.generate_step -> [NEW: lease a key] ->
claim one QUEUED item (FOR UPDATE SKIP LOCKED) -> gemini call in a thread -> store JPEG in
Supabase -> commit -> return status and timings -> browser schedules the next step.

Reuse: `app/engine/pacer.py` (pace maths), `app/routers/images.py:_zip_dish_images` (zip),
`app/crypto.py:encrypt/key_hint` (key at rest), `app/engine/gemini.py:key_hash` (pool key id).

## Decisions
- D1: Server-side leasing, not client-side key assignment - the browser never sees a key, and
  two tabs or devices can share the pool safely. Rejected: sending the key list to the client
  (leaks secrets, races on pacing).
- D2: The lease is a column on `pace_state` (`leased_until`), claimed with `UPDATE ... WHERE
  api_key_hash = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING` - one round trip,
  no advisory locks, no new table. Rejected: an in-process asyncio semaphore (dies on
  restart, wrong across processes).
- D3: Lease the key BEFORE claiming an item, and release it if no item was claimed. Claiming
  first would strand items in `generating` whenever the pool is busy.
- D4: Success now also sets `next_allowed_at = now + delay_s` (previously only 429s did).
  With lanes running concurrently the pace has to be enforced server-side per key; the
  client's `next_delay_ms` sleep is no longer the only thing spacing calls.
- D5: `next_step_ms` is a NEW field: the per-LANE wait, distinct from `next_delay_ms` (the
  per-KEY pace, kept for ETA display). On success a lane steps again immediately and the
  server decides whether a key is free. Rejected: reusing `next_delay_ms` (serialises lanes).
- D6: An auth failure disables that key and returns `waiting`, not `failed`, while other keys
  remain. The six step statuses stay exactly as SPEC.md pins them.
- D7: Two destructive levels: `POST /shops/{id}/purge-images` (blobs only, catalogue intact)
  and `DELETE /shops/{id}` (everything). Download-first is a UI affordance, not enforced
  server-side.

## Global constraints
- Conventions: routers declare paths RELATIVE to /api; errors via `AppError(code, msg, status)`;
  Pydantic v2 `model_config = ConfigDict(from_attributes=True)`; no plaintext key is ever
  logged, returned, or written to a `JobEvent` - hints (`...abcd`) only.
- Forbidden: new runtime dependencies; Alembic; editing files outside a task's write-set;
  re-tuning the pacer constants; touching `engine/prompt.py`, `engine/classify.py`,
  `engine/extract.py`, `engine/export.py`.
- Platform: Python 3.12, FastAPI 0.115, SQLAlchemy 2.0 async with asyncpg (Supabase PgBouncer,
  NullPool), React 18 with TS 5.6, TanStack Query v5, Tailwind, single-instance deploy.

## Verify (global)
```bash
cd backend && python -m pytest -q && cd ../frontend && npx tsc --noEmit
```

## Contracts
```text
# ---------- DB ----------
table api_keys:
  id UUID pk (uuid4) | user_id UUID fk users.id index | label str
  key_enc str (Fernet) | key_hint str ("...abcd") | key_hash str (gemini.key_hash = sha256[:32]) index
  enabled bool default True | disabled_reason str|None
  created_at tstz server_default now() | last_used_at tstz|None
  UniqueConstraint(user_id, key_hash) name="uq_api_keys_user_key"
table pace_state: + leased_until tstz|None
migration in app/db.py init_models(), after create_all, idempotent, best-effort:
  ALTER TABLE pace_state ADD COLUMN IF NOT EXISTS leased_until TIMESTAMPTZ

# ---------- app/engine/keypool.py ----------
LEASE_SECONDS = 150            # > gemini.API_TIMEOUT (90) + storage write headroom
MAX_LANES = 6
WAIT_CAP_MS = 60_000

@dataclass(frozen=True) Candidate:
    key_hash: str; enabled: bool; next_allowed_at: datetime|None
    leased_until: datetime|None; last_used_at: datetime|None

def free_at(c: Candidate) -> datetime|None          # max(next_allowed_at, leased_until); None if both None
def wait_ms_until(cands: Sequence[Candidate], now: datetime) -> int|None
    # None -> no enabled candidate at all;  0 -> one is free now;
    # n>0  -> ms until the soonest enabled candidate frees, capped at WAIT_CAP_MS
def lane_count(enabled: int) -> int                  # min(max(enabled,1), MAX_LANES)

async def lease(db, user_id: UUID) -> tuple[ApiKey, str] | None
async def release(db, key_hash: str, delay_s: float) -> None      # next_allowed_at = now+delay; leased_until = NULL
async def release_now(db, key_hash: str) -> None                  # leased_until = NULL only
async def wait_ms(db, user_id: UUID) -> int|None
async def enabled_count(db, user_id: UUID) -> int
async def disable(db, key_hash: str, reason: str) -> None
async def add_key(db, user_id: UUID, plain: str, label: str) -> ApiKey   # + pace_state row
async def delete_key(db, key: ApiKey) -> None                     # + its pace_state row when unshared
async def pick_any(db, user_id: UUID) -> str                      # plaintext, least-recently-used ENABLED key,
                                                                  # no lease; raises AppError("no_api_key",400)
async def migrate_legacy_keys(db) -> int                          # users.gemini_key_enc -> api_keys, idempotent

# ---------- StepResult (schemas.py + api/types.ts) : ADDITIVE ----------
status/item/next_delay_ms/retry_after_ms/remaining/done/failed   (unchanged)
next_step_ms: int          # ms THIS lane waits before its next /step (0 = right away)
key_hint: str | None       # the key that served this step
lanes: int                 # advised concurrent lanes = keypool.lane_count(enabled keys)

# ---------- HTTP ----------
GET    /api/auth/keys                    -> list[ApiKeyOut]
POST   /api/auth/keys   {key, label?}    -> ApiKeyOut 201 | 400 auth_failure | 409 conflict | 429 rate_limited
PATCH  /api/auth/keys/{id} {label?, enabled?} -> ApiKeyOut | 404 not_found
DELETE /api/auth/keys/{id}               -> 204 | 404 not_found
POST   /api/auth/keys/{id}/test          -> ApiKeyOut   (live ping; re-enables on success, disables on auth_failure)
GET    /api/storage                      -> StorageUsageOut
POST   /api/shops/{id}/purge-images      -> PurgeResultOut
DELETE /api/shops/{id}                   -> 204
ApiKeyOut   { id, label, key_hint, enabled, disabled_reason, created_at, last_used_at,
              delay_s: float, next_allowed_at: datetime|None, busy: bool }
StorageUsageOut  { total_bytes:int, budget_bytes:int = 1_073_741_824, shops: list[ShopStorageOut] }
ShopStorageOut   { shop_id, shop_name, dish_bytes, dish_count, menu_bytes, menu_count,
                   reference_bytes, export_bytes, export_count, total_bytes }
PurgeResultOut   { deleted_images:int, bytes_freed:int }
MeOut: + key_count:int, + enabled_key_count:int ; has_gemini_key/gemini_key_hint now derive from the pool
Storage protocol: + async def delete_many(self, keys: list[str]) -> None   # batches of 100

# ---------- generate_step behaviour (T04) ----------
1 re-fetch job; must be RUNNING and kind==generate, else AppError("job_not_running",409)
2 leased = await keypool.lease(db, user.id)
    None -> w = await keypool.wait_ms(db, user.id)
            w is None -> job FAILED "No enabled Gemini API key" + return status "failed"
            else return "waiting", retry_after_ms = max(w, 250), next_step_ms = max(w, 250)
3 claim ONE queued item (existing SKIP LOCKED UPDATE...RETURNING)
4 no item -> keypool.release_now(); then the EXISTING stale-sweep / inflight / complete logic
5 commit the claim; build prompt; fetch reference; call generate_one in a thread
6 RateLimited   -> item QUEUED; pacer.on_rate_limit -> wait_s; keypool.release(hash, wait_s);
                   "rate_limited", retry_after_ms = max(wait_ms(pool), 250), next_step_ms = same
   AuthFailure  -> item QUEUED; keypool.disable(hash, reason); log "key <hint> disabled: ...";
                   enabled_count == 0 -> job FAILED + "failed"; else "waiting", next_step_ms = 250
   NoImage      -> unchanged attempts/fallback ladder; keypool.release(hash, pace.delay_s);
                   "item_failed", next_step_ms = 0
   success      -> store + pacer.on_success -> delay; keypool.release(hash, delay);
                   "generated", next_delay_ms = delay*1000, next_step_ms = 0
7 any other exception -> item back to QUEUED, keypool.release_now(), re-raise (unchanged)
every return carries key_hint (the leased key) and lanes (keypool.lane_count(enabled_count))
```

## Risks
| R | Scenario | Mitigation | Covering test (task) |
|---|---|---|---|
| R1 | Two lanes get the same key, causing an instant 429 storm | single-statement lease with FOR UPDATE SKIP LOCKED plus leased_until | T02 (`wait_ms_until`, lease SQL shape) plus a manual 2-lane run |
| R2 | A step dies after leasing, so the key stays leased forever | LEASE_SECONDS=150 expiry; the lease predicate treats an expired lease as free | T02 TC4 |
| R3 | An item is claimed while no key is free and strands at `generating` | lease precedes claim (D3); release_now when no item was claimed | T04 TC2 |
| R4 | Lanes race to mark the job DONE and the 409 kills healthy lanes | the client treats a `job_not_running` 409 as a normal stop | T06 TC3 |
| R5 | The legacy single key is lost on deploy and nobody can generate | `migrate_legacy_keys` at boot, idempotent | T02 TC6 |
| R6 | Purge or delete removes blobs but leaves rows (or the reverse) | FK-safe order, null out `shops.reference_image_id` and `items.image_id` first; delete blobs before rows | T05 TC1..TC3 |
| R7 | The `ALTER TABLE` migration fails on a locked DB and takes the app down | best-effort try/except with a logged warning | T01 TC3 |
| R8 | A plaintext key leaks into a JobEvent, log line, or response | only `key_hint` crosses a boundary; grep check in T04 Verify | T04 TC5 |

## Test matrix
| AC or R | Test (file :: name) | Task |
|---|---|---|
| AC1,R1 | backend/tests/test_keypool.py :: test_wait_ms_until_free_key_returns_zero | T02 |
| AC2 | backend/tests/test_keypool.py :: test_wait_ms_until_picks_soonest | T02 |
| AC2 | backend/tests/test_pacer.py :: (existing, unchanged) | T02 |
| AC3 | backend/tests/test_keypool.py :: test_wait_ms_until_ignores_disabled | T02 |
| AC4,R2 | backend/tests/test_keypool.py :: test_expired_lease_counts_as_free | T02 |
| AC1 | backend/tests/test_keypool.py :: test_lane_count_caps_at_max | T02 |
| R5 | backend/tests/test_keypool.py :: test_legacy_migration_is_idempotent | T02 |
| AC7,AC9,R6 | backend/tests/test_storage_usage.py :: test_usage_sums_by_kind / test_purge_plan_lists_only_dish_keys | T05 |
| AC8,R6 | backend/tests/test_storage_usage.py :: test_delete_plan_covers_every_object | T05 |
| R4 | frontend typecheck plus the generateLoop 409 branch (reviewed) | T06 |
| AC10 | full suite via Verify (global) | all |

## Task DAG
| ID | Title | Deps | Wave | Write-set | Risk | Model |
|---|---|---|---|---|---|---|
| T01 | api_keys table, leased_until, schemas | none | 1 | backend/app/models.py, backend/app/db.py, backend/app/schemas.py | med | sonnet |
| T02 | keypool engine plus tests | T01 | 2 | backend/app/engine/keypool.py, backend/tests/test_keypool.py | high | sonnet |
| T03 | keys router, /me, boot migration | T02 | 3 | backend/app/routers/keys.py, backend/app/routers/auth.py, backend/app/main.py | med | sonnet |
| T04 | route generate_step through the pool | T02 | 4 | backend/app/stepper.py, backend/app/routers/jobs.py, backend/app/routers/shops.py | high | sonnet |
| T05 | storage usage, purge, delete catalog | T01 | 5 | backend/app/storage.py, backend/app/routers/storage.py, backend/app/main.py, backend/tests/test_storage_usage.py | high | sonnet |
| T06 | frontend api layer plus N-lane loop | T03,T04,T05 | 6 | frontend/src/api/types.ts, frontend/src/api/hooks.ts, frontend/src/lib/generateLoop.ts | med | sonnet |
| T07 | Settings screen plus delete/download UI | T06 | 7 | frontend/src/screens/Settings.tsx, frontend/src/screens/settings/, frontend/src/router.tsx, frontend/src/screens/Shops.tsx, frontend/src/screens/Catalog.tsx, frontend/src/screens/Generate.tsx, frontend/src/screens/catalog/CatalogCard.tsx | med | sonnet |

## Rollback
`git switch main` - nothing is merged until the user says so. On the deployed instance the
only irreversible pieces are the `api_keys` table (additive, harmless if unused) and the
`pace_state.leased_until` column (nullable, ignored by the old code). Data deletion is
operator-initiated and confirm-gated; there is no automatic purge.
