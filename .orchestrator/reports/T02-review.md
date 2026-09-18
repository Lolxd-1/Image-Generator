# Review (task): T02

VERDICT: APPROVE

## Critical
(none)

## Important
(none)

## Minor
1. backend/app/engine/keypool.py:110-117 · In `lease()`, after the UPDATE...RETURNING
   commits nothing yet, the code does `key_row.last_used_at = now` without checking
   `key_row is None`. Under READ COMMITTED, a concurrent `delete_key()` on the same
   `key_hash` (no FK/lock ties `ApiKey` to the `PaceState` row this transaction holds)
   could delete the `ApiKey` row between the UPDATE and this SELECT, making `key_row`
   `None` and raising `AttributeError` instead of a clean `AppError`/`None`. This
   exact shape was prescribed verbatim in the brief's Step 5 code sample, so it is a
   latent gap in the plan rather than a deviation by the implementer, and the window
   is narrow (delete racing an in-flight lease of the same physical key). Worth a
   `if key_row is None: return None` guard in a follow-up, not blocking here.
2. backend/app/engine/keypool.py:177-197 `add_key()` has a check-then-insert race on
   the `(user_id, key_hash)` uniqueness (SELECT-if-exists, then INSERT) rather than
   catching the DB's `UniqueConstraint("user_id", "key_hash")` on conflict. This
   mirrors the existing convention in `stepper.py:169-171` (`start_job`'s
   "one job running" check) exactly, so it's not a new pattern introduced here —
   noting only because a concurrent double-submit would surface as an unhandled
   `IntegrityError` (500) instead of the intended 409. Same latent gap pre-exists in
   the codebase; not specific to this task.

## Checked
- Diff scope: only `backend/app/engine/keypool.py` and `backend/tests/test_keypool.py`
  created, matching the brief's write-set exactly; no router/stepper/main.py/pacer.py
  touched (respects Out of scope).
- Contracts: every name (`LEASE_SECONDS`, `MAX_LANES`, `WAIT_CAP_MS`, `Candidate`,
  `free_at`, `wait_ms_until`, `lane_count`, `lease`, `release`, `release_now`,
  `wait_ms`, `enabled_count`, `disable`, `add_key`, `delete_key`, `pick_any`,
  `migrate_legacy_keys`) exists with the exact signature from the brief; verified via
  `inspect.iscoroutinefunction` per the Verify block plus manual signature diff.
- `free_at`/`wait_ms_until`/`lane_count` logic traced by hand against brief Steps
  2-4, including naive-datetime handling (`_aware`), expired-lease-as-free, disabled
  filtering, and the `WAIT_CAP_MS` cap — matches.
- `lease()`: single UPDATE driven by a `FOR UPDATE SKIP LOCKED` subquery with
  `of=PaceState`, statement shape is a verbatim match to the brief's prescribed SQL
  and to the existing claim pattern in `backend/app/stepper.py:255-270`; commits
  before returning so a concurrent caller can observe the lease (per brief's
  explicit requirement).
- `release`/`release_now`: correct columns touched, safe no-op on a hash with no
  pace row (UPDATE matching 0 rows raises nothing).
- `wait_ms`: outer join confirmed so a key with no pace row still counts as free.
- `disable`: updates every `api_keys` row sharing the hash (cross-user, as
  specified) and clears `leased_until`; reason truncated to 300 chars.
- `add_key`/`delete_key`/`pick_any`/`migrate_legacy_keys`: traced against Steps
  10-13, including `pick_any`'s exact `AppError` code/message/status,
  `delete_key`'s "delete pace row only if no other `api_keys` row shares the hash",
  and `migrate_legacy_keys`' decrypt-failure log-and-skip (confirmed it logs only
  `user.id`, never ciphertext/plaintext).
- Grepped the whole file for `logger`/`JobEvent`/return-value leaks of plaintext:
  only the two documented `str` returns (`lease`'s tuple element, `pick_any`) ever
  carry plaintext.
- Cross-checked field names/types against `backend/app/models.py`
  (`ApiKey`, `PaceState`, `User`) — all match.
- Cross-checked `pacer.get_or_create` and constants against
  `backend/app/engine/pacer.py` — used unchanged, not re-tuned, no edits to that
  file in the diff.
- Cross-checked `crypto.encrypt/decrypt/key_hint` and `gemini.key_hash`/
  `API_TIMEOUT` signatures — match usage.
- All 9 named test cases (TC1-TC9) present in `test_keypool.py` with matching
  names and assertions; no DB fixture added (respects Out of scope).
- Ran Verify exactly: `pytest tests/test_keypool.py tests/test_pacer.py` → 17
  passed; full `pytest -q` → 104 passed in 146.53s; contract-signature script →
  `T02 OK`.
