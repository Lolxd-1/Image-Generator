"""One-image-per-HTTP-request job orchestration: job lifecycle, the atomic
claim-and-generate /step loop, and the extract/classify/host/export batch jobs.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.engine import classify, export, extract, gemini, generate, imgbb, keypool, pacer, prompt
from app.enums import ImageKind, ItemStatus, JobKind, JobStatus
from app.errors import AppError
from app.models import Export, Image, Item, Job, JobEvent, MenuUpload, Shop, User
from app.storage import get_storage

# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------

# Reference-image bytes are re-used by every item in a run (the shop reference,
# or occasionally a per-item manual override). Caching avoids re-downloading
# the same object from storage on every single /step call. Module-level and
# unbounded-but-capped: fine for a single-process deployment; a multi-process
# deployment simply pays one extra download per process, which is harmless.
_REF_CACHE_MAX = 8
_ref_cache: "OrderedDict[uuid.UUID, bytes]" = OrderedDict()


def _shop_dict(shop: Shop) -> dict[str, Any]:
    return {
        "name": shop.name,
        "brand_archetype": shop.brand_archetype,
        "cuisine": shop.cuisine,
        "price_tier": shop.price_tier,
        "plating_style": shop.plating_style,
        "lighting_mood": shop.lighting_mood,
        "background_setting": shop.background_setting,
        "prop_density": shop.prop_density,
        "notes": shop.notes,
    }


def _item_dict(item: Item) -> dict[str, Any]:
    return {
        "name": item.name,
        "category": item.category,
        "description": item.description,
        "concept_text": item.concept_text,
        "suggested_vessel": item.suggested_vessel,
        "suggested_props": item.suggested_props,
    }


def _step_item(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "status": item.status,
        "image_id": item.image_id,
        "error": item.last_error,
    }


def _remaining(job: Job) -> int:
    return max(job.total - job.done - job.failed, 0)


def _safe_filename(name: str, suffix: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_ ") else "-" for c in (name or "shop")).strip() or "shop"
    return f"{cleaned}{suffix}"


async def _get_ref_bytes(db: AsyncSession, image_id: uuid.UUID) -> bytes:
    cached = _ref_cache.get(image_id)
    if cached is not None:
        _ref_cache.move_to_end(image_id)
        return cached
    image = await db.get(Image, image_id)
    if image is None:
        raise ValueError(f"reference image {image_id} not found")
    storage = get_storage()
    raw = await storage.get(image.storage_key)
    # Downscale ONCE per shop, then serve every item in the run from the cache.
    data = await asyncio.to_thread(generate.prepare_reference, raw)
    _ref_cache[image_id] = data
    _ref_cache.move_to_end(image_id)
    while len(_ref_cache) > _REF_CACHE_MAX:
        _ref_cache.popitem(last=False)
    return data


async def log(db: AsyncSession, job: Job, level: str, message: str, item_id: uuid.UUID | None = None) -> None:
    """Write one JobEvent and commit immediately, so it survives even if the
    caller's own work later fails or the process dies before its own commit.

    Never pass a decrypted API key (or anything derived from one) as `message`.
    """
    event = JobEvent(id=uuid.uuid4(), job_id=job.id, level=level, item_id=item_id, message=message[:2000])
    db.add(event)
    await db.commit()


async def log_many(db: AsyncSession, job: Job, level: str, messages: list[str],
                   cap: int = 15) -> None:
    """Write many related events in ONE commit, capped.

    `log()` commits per call so a single important line survives a crash. That
    is wrong for bulk notes: one real extraction produced ~160 of them, and at
    a ~2.7s round-trip to the pooled database that alone took nearly 8 minutes
    of the user's time. Here we write at most `cap` lines plus a summary, in a
    single transaction.
    """
    if not messages:
        return
    shown = messages[:cap]
    for m in shown:
        db.add(JobEvent(id=uuid.uuid4(), job_id=job.id, level=level, message=m[:2000]))
    if len(messages) > cap:
        db.add(JobEvent(
            id=uuid.uuid4(), job_id=job.id, level=level,
            message=f"... and {len(messages) - cap} more similar messages "
                    f"({len(messages)} total).",
        ))
    await db.commit()


# ---------------------------------------------------------------------------
# job lifecycle
# ---------------------------------------------------------------------------


async def requeue_stale(db: AsyncSession, shop_id: uuid.UUID, older_than_seconds: int = 600) -> int:
    """Reclaim items stuck at GENERATING (a /step request that crashed, was
    killed, or lost its connection mid-flight) back to QUEUED.

    This is the backstop for the crash case a local except-block can never
    catch: the process dies between the claim commit and the result commit.
    Recovery only needs `items.updated_at` (bumped by the claim's own UPDATE)
    plus this age check — no extra bookkeeping table required.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    stmt = (
        update(Item)
        .where(Item.shop_id == shop_id, Item.status == ItemStatus.GENERATING, Item.updated_at < cutoff)
        .values(status=ItemStatus.QUEUED)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


async def start_job(db: AsyncSession, shop: Shop, user: User, kind: JobKind) -> Job:
    """Create a job for `shop`, enforcing "only one RUNNING job per shop".

    For `generate`, also reclaims any stale GENERATING items and promotes
    every APPROVED item (plus any already-QUEUED leftovers from an aborted
    previous run) to QUEUED, so `job.total` reflects exactly what /step will
    work through.
    """
    existing = await db.execute(
        select(Job.id).where(Job.shop_id == shop.id, Job.status == JobStatus.RUNNING).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError("conflict", "A job is already running for this shop.", status=409)

    job = Job(
        id=uuid.uuid4(),
        shop_id=shop.id,
        kind=kind,
        status=JobStatus.RUNNING,
        total=0,
        done=0,
        failed=0,
        started_at=datetime.now(timezone.utc),
        created_by=user.id,
    )
    db.add(job)
    await db.flush()

    if kind == JobKind.GENERATE:
        await requeue_stale(db, shop.id)
        await db.execute(
            update(Item)
            .where(Item.shop_id == shop.id, Item.status == ItemStatus.APPROVED)
            .values(status=ItemStatus.QUEUED)
            .execution_options(synchronize_session=False)
        )
        count_result = await db.execute(
            select(func.count()).select_from(Item).where(Item.shop_id == shop.id, Item.status == ItemStatus.QUEUED)
        )
        job.total = count_result.scalar_one()

    await db.commit()
    await db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# the /step loop - one image per HTTP request
# ---------------------------------------------------------------------------


def _step_result(status, *, item=None, next_delay_ms=None, retry_after_ms=None,
                  next_step_ms=0, key_hint=None, lanes=1, job) -> dict[str, Any]:
    """Build one `generate_step` return dict. Routing every `return` through
    this (rather than a dict literal per branch) means no return path can
    forget `next_step_ms`/`key_hint`/`lanes` or the `remaining`/`done`/`failed`
    counters, which every branch must carry."""
    return {
        "status": status,
        "item": item,
        "next_delay_ms": next_delay_ms,
        "retry_after_ms": retry_after_ms,
        "remaining": _remaining(job),
        "done": job.done,
        "failed": job.failed,
        "next_step_ms": next_step_ms,
        "key_hint": key_hint,
        "lanes": lanes,
    }


async def generate_step(db: AsyncSession, job: Job, shop: Shop, user: User) -> dict[str, Any]:
    """Advance one `generate` job by exactly one item. See SPEC.md §6.

    `status` in the returned dict is one of the six values SPEC.md pins down:
    generated | item_failed | rate_limited | waiting | complete | failed.
    `failed` is reserved *exclusively* for a whole-job AuthFailure abort — a
    single bad dish must never stop the loop, so any per-item problem (a
    blocked prompt that never clears, or a missing reference image) reports
    `item_failed` and leaves the job RUNNING.

    The pace gate (SPEC.md's Step 2) is now a per-key LEASE (app.engine.
    keypool): each call leases one free, enabled key out of the user's pool
    instead of gating on a single key's own pace, so K concurrent callers can
    run on K different keys. `next_delay_ms` stays the per-KEY pace (how long
    the key this call used should wait before its next use); `next_step_ms`
    is the per-LANE wait (how soon the caller should retry /step at all),
    which is usually much shorter since another key in the pool may already
    be free. An AuthFailure now disables just the one key that produced it
    (`keypool.disable`) instead of failing the whole job - the run continues
    on the user's other enabled keys, and only the job itself fails once none
    remain.
    """
    # Step 1: job must be RUNNING. Re-fetch: the `job` the caller passed in
    # may be stale if a second tab/request changed it since it was loaded.
    fresh_job = await db.get(Job, job.id)
    if fresh_job is None or fresh_job.status != JobStatus.RUNNING:
        raise AppError("job_not_running", "Job is not running.", status=409)
    job = fresh_job
    # Defensive, beyond the letter of SPEC.md's 9 steps: /step only makes
    # sense for a `generate` job. extract/classify/host/export run to
    # completion inside their own POST and stay RUNNING for that request's
    # whole duration - a /step call racing against that request must not be
    # allowed to claim (there is nothing queued) and prematurely mark that
    # job DONE out from under the request that is still writing to it.
    if job.kind != JobKind.GENERATE:
        raise AppError("job_not_running", "This job does not use the step loop.", status=409)

    now = datetime.now(timezone.utc)

    # Step 2 (SPEC.md numbering: pace gate) -> a per-key lease. Do NOT claim
    # an item until a key is actually leased.
    lanes = keypool.lane_count(await keypool.enabled_count(db, user.id))
    leased = await keypool.lease(db, user.id)
    if leased is None:
        w = await keypool.wait_ms(db, user.id)
        if w is None:            # no enabled key at all -> the job cannot continue
            job.status = JobStatus.FAILED
            job.error = "No enabled Gemini API key. Add one in Settings."
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            await log(db, job, "error", job.error)
            return _step_result("failed", job=job, lanes=lanes)
        wait = max(w, 250)
        return _step_result("waiting", retry_after_ms=wait, next_step_ms=wait, job=job, lanes=lanes)
    key_row, api_key = leased
    key_hash, key_hint = key_row.key_hash, key_row.key_hint
    job.api_key_hash = key_hash  # informational only: records the LAST key used

    # `item` stays None until Step 3 actually claims one; the except below
    # must not dereference it when a failure happens before that point.
    item: Item | None = None
    try:
        # Step 3: atomically claim ONE item. A single UPDATE ... RETURNING driven
        # by a FOR UPDATE SKIP LOCKED subquery, so two concurrent callers (two
        # browser tabs, two users hitting the same shop) can never claim the same
        # row - there is no separate SELECT-then-UPDATE to race.
        claim_subq = (
            select(Item.id)
            .where(Item.shop_id == shop.id, Item.status == ItemStatus.QUEUED)
            .order_by(Item.position)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        claim_stmt = (
            update(Item)
            .where(Item.id == claim_subq.scalar_subquery())
            .values(status=ItemStatus.GENERATING)
            .returning(Item)
            .execution_options(synchronize_session=False)
        )
        item = (await db.execute(claim_stmt)).scalars().first()

        # Step 4: nothing left to claim -> the job *may* be done.
        #
        # Before declaring completion, sweep for items stranded in GENERATING by a
        # request that died mid-flight (a host restart, a dropped connection). Doing
        # the sweep here rather than only at job start means a long run self-heals:
        # otherwise a single crashed step would silently drop that dish from the
        # catalogue and the run would report "complete" while being one image short.
        if item is None:
            # No item claimed with this leased key -> give it back before doing
            # anything else, so it is immediately available to the next caller.
            await keypool.release_now(db, key_hash)

            # A step request cannot outlive gemini.API_TIMEOUT (90s) by much, so
            # anything at GENERATING for 3 minutes is genuinely stranded, not busy.
            recovered = await requeue_stale(db, shop.id, older_than_seconds=180)
            if recovered:
                await log(
                    db, job, "warn",
                    f"Recovered {recovered} item(s) stranded mid-generation and "
                    f"returned them to the queue.",
                )
                await db.commit()
                # Do not complete: the loop should come straight back for them.
                return _step_result(
                    "waiting", retry_after_ms=1000, next_step_ms=1000,
                    key_hint=key_hint, lanes=lanes, job=job,
                )

            # Still-young GENERATING rows mean another caller (a second tab, or a
            # colleague on the same shop) is mid-flight on the last item(s). Marking
            # the job DONE here would end their run and drop those dishes from the
            # catalogue, so wait for them instead of completing.
            inflight = await db.scalar(
                select(func.count())
                .select_from(Item)
                .where(Item.shop_id == shop.id, Item.status == ItemStatus.GENERATING)
            )
            if inflight:
                await db.commit()
                return _step_result(
                    "waiting", retry_after_ms=5000, next_step_ms=5000,
                    key_hint=key_hint, lanes=lanes, job=job,
                )

            job.status = JobStatus.DONE
            job.finished_at = now
            await db.commit()
            return _step_result("complete", key_hint=key_hint, lanes=lanes, job=job)

        # Commit the claim in its own transaction, separately from everything
        # that follows. If the process dies anywhere below, this item is durably
        # parked at GENERATING - never lost, never double-claimed - and
        # requeue_stale() reclaims it once older_than_seconds has passed.
        await db.commit()

        # Step 5: build the prompt. attempts > 0 means a previous call on
        # this same item already failed with NoImage, so use the fallback
        # ladder instead of the full prompt. Persist whichever was used.
        if item.attempts > 0:
            prompt_text = prompt.fallback_prompt(
                item.name, item.description, item.category, item.attempts - 1, shop.style_profile,
            )
        else:
            prompt_text = prompt.build_prompt(
                shop.style_profile, _shop_dict(shop), _item_dict(item), seed=item.position,
            )
        item.prompt_used = prompt_text

        # Step 6: resolve + fetch the reference image bytes (manual per-item
        # override wins over the shop-wide reference), via the module cache.
        ref_image_id = item.manual_ref_image_id or shop.reference_image_id
        if ref_image_id is None:
            # SPEC-GAP: SPEC.md's algorithm assumes a reference image is
            # always configured before a generate job starts; it does not say
            # what to do if one is missing. Treated as a per-item failure
            # (not a whole-job AuthFailure-style abort) so one misconfigured
            # item never halts the rest of the run.
            item.status = ItemStatus.FAILED
            item.last_error = "no reference image configured for this shop or item"
            job.failed += 1
            pace_delay = (await pacer.get_or_create(db, key_hash)).delay_s
            await keypool.release_now(db, key_hash)
            await db.commit()
            await log(db, job, "error", item.last_error, item.id)
            return _step_result(
                "item_failed", item=_step_item(item), next_delay_ms=int(pace_delay * 1000),
                next_step_ms=0, key_hint=key_hint, lanes=lanes, job=job,
            )
        ref_jpeg = await _get_ref_bytes(db, ref_image_id)

        # Step 7: call generate_one exactly once. No loop, no sleep here.
        client = gemini.build_client(api_key)
        try:
            raw = await asyncio.to_thread(generate.generate_one, client, prompt_text, ref_jpeg)
        except gemini.RateLimited as e:
            # Step 7 outcome: back to the queue, not counted as failed,
            # attempts untouched. Only THIS key's pace backs off; release it
            # to the pool at that backoff and wait only for the pool's
            # soonest free key (usually much sooner than this key's own).
            item.status = ItemStatus.QUEUED
            wait_s = await pacer.on_rate_limit(db, key_hash)
            await keypool.release(db, key_hash, wait_s)
            await db.commit()
            await log(db, job, "warn", f"rate limited: {e}", item.id)
            w = await keypool.wait_ms(db, user.id)
            wait = max(w if w is not None else int(wait_s * 1000), 250)
            return _step_result(
                "rate_limited", item=_step_item(item), retry_after_ms=wait,
                next_step_ms=wait, key_hint=key_hint, lanes=lanes, job=job,
            )
        except gemini.AuthFailure as e:
            # This key is bad - disable just it and hand the item back to the
            # queue so it is not stranded. The job only dies (Step 9) once no
            # enabled key remains; otherwise the run continues on the others.
            item.status = ItemStatus.QUEUED
            item.last_error = f"auth failure: {e}"
            await keypool.disable(db, key_hash, str(e)[:300])
            await log(db, job, "error", f"API key {key_hint} disabled: {e}", item.id)
            remaining_keys = await keypool.enabled_count(db, user.id)
            if remaining_keys == 0:
                job.status = JobStatus.FAILED
                job.error = str(e)[:500]
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
                return _step_result(
                    "failed", item=_step_item(item), key_hint=key_hint, lanes=lanes, job=job,
                )
            return _step_result(
                "waiting", item=_step_item(item), retry_after_ms=250, next_step_ms=250,
                key_hint=key_hint, lanes=keypool.lane_count(remaining_keys), job=job,
            )
        except gemini.NoImage as e:
            # Step 8: increment attempts; retry via the fallback ladder up to
            # 3 times, then this one item - and only this item - fails.
            # Either way this is `item_failed`, never the job-level `failed`;
            # `item.status` (queued vs failed) and `job.failed` carry the
            # distinction. Pacer is intentionally left untouched here (SPEC
            # step 8 names no pacer call), so next_delay_ms is the pace's
            # current, unmodified cadence.
            item.attempts += 1
            item.last_error = str(e)[:500]
            if item.attempts <= 3:
                item.status = ItemStatus.QUEUED
            else:
                item.status = ItemStatus.FAILED
                job.failed += 1
            pace_delay = (await pacer.get_or_create(db, key_hash)).delay_s
            await keypool.release(db, key_hash, pace_delay)
            await db.commit()
            await log(db, job, "warn", f"no image (attempt {item.attempts}): {e}", item.id)
            return _step_result(
                "item_failed", item=_step_item(item), next_delay_ms=int(pace_delay * 1000),
                next_step_ms=0, key_hint=key_hint, lanes=lanes, job=job,
            )

        # Step 6 (success branch of SPEC.md's numbering): store bytes, mark
        # generated, advance pacing.
        jpeg_bytes, width, height = generate.to_jpeg(raw)
        image_id = uuid.uuid4()
        storage_key = f"shops/{shop.id}/dish/{image_id}.jpg"
        storage = get_storage()
        await storage.put(storage_key, jpeg_bytes, "image/jpeg")
        image = Image(
            id=image_id,
            shop_id=shop.id,
            item_id=item.id,
            kind=ImageKind.DISH,
            storage_key=storage_key,
            sha256=hashlib.sha256(jpeg_bytes).hexdigest(),
            bytes_len=len(jpeg_bytes),
            width=width,
            height=height,
        )
        db.add(image)
        item.image_id = image_id
        item.status = ItemStatus.GENERATED
        item.last_error = None
        job.done += 1
        next_delay_s = await pacer.on_success(db, key_hash)
        await keypool.release(db, key_hash, next_delay_s)
        await db.commit()
        await log(db, job, "info", f"generated '{item.name}'", item.id)
        return _step_result(
            "generated", item=_step_item(item), next_delay_ms=int(next_delay_s * 1000),
            next_step_ms=0, key_hint=key_hint, lanes=lanes, job=job,
        )
    except Exception:
        # Crash safety net: covers everything from Step 3 (the claim) through
        # Step 8, not just the generation call - a DB error while claiming,
        # sweeping stale items, or checking for in-flight items must release
        # the lease too, not just a failure inside generate_one. A claimed
        # item goes straight back in the queue - not counted as failed,
        # attempts untouched, since this was not a generation rejection -
        # then the exception surfaces to the caller (FastAPI will turn it
        # into a 500; requeue_stale() is the remaining backstop if even this
        # commit never runs). `item` is still None when the failure happened
        # before Step 3 claimed one, so there is nothing to requeue. The
        # lease is released either way: an extra release is harmless, a
        # missed one is not.
        if item is not None:
            item.status = ItemStatus.QUEUED
        await keypool.release_now(db, key_hash)
        await db.commit()
        raise


# ---------------------------------------------------------------------------
# extract / classify / host / export - each runs to completion in one request
# ---------------------------------------------------------------------------


async def run_extract(db: AsyncSession, job: Job, shop: Shop, api_key: str) -> None:
    """Read every un-extracted MenuUpload for `shop`, merge across photos, and
    upsert the result into `items`.

    # SPEC-GAP: SPEC.md's §6 step algorithm only pins down /step in detail;
    # it does not specify how extracted items get merged into the `items`
    # table (upsert keys, position assignment, price-conflict handling).
    # This upserts by the same (name, category) key `extract.merge` already
    # dedupes photos by, appends genuinely new items after the current max
    # `position`, and flags - rather than duplicate-inserts - a same-key
    # price conflict, since (shop_id, name, category) is a DB unique
    # constraint (see models.py).
    """
    try:
        client = gemini.build_client(api_key)
        storage = get_storage()
        result = await db.execute(
            select(MenuUpload).where(MenuUpload.shop_id == shop.id, MenuUpload.extracted_at.is_(None))
        )
        uploads = result.scalars().all()
        job.total = len(uploads)
        await db.flush()

        per_photo: list[tuple[str, list[dict]]] = []
        for mu in uploads:
            try:
                raw_bytes = await storage.get(mu.storage_key)
                prepped = extract.prepare_image(raw_bytes)
                data = await asyncio.to_thread(extract.read_menu, client, prepped)
                items, warns = extract.normalise_items(data.get("items", []), mu.filename)
                mu.raw_json = data
                mu.is_menu = bool(data.get("is_menu"))
                mu.extracted_at = datetime.now(timezone.utc)
                per_photo.append((mu.filename, items))
                for w in warns:
                    await log(db, job, "warn", f"{mu.filename}: {w}")
                job.done += 1
                await db.flush()
            except gemini.AuthFailure as e:
                job.status = JobStatus.FAILED
                job.error = str(e)[:500]
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
                await log(db, job, "error", f"auth failure reading {mu.filename}: {e}")
                return
            except Exception as e:
                mu.error = str(e)[:500]
                job.failed += 1
                await log(db, job, "error", f"failed to read {mu.filename}: {e}")
                await db.flush()

        merged, notes = extract.merge(per_photo)
        await log_many(db, job, "info", list(notes))

        existing_result = await db.execute(select(Item).where(Item.shop_id == shop.id))
        existing_items = existing_result.scalars().all()
        existing_by_key = {extract.norm_key(it.name, it.category): it for it in existing_items}
        next_position = max((it.position for it in existing_items), default=-1) + 1

        seen_this_run: dict[str, Item] = {}
        conflict_notes: list[str] = []
        for m in merged:
            key = extract.norm_key(m["item_name"], m["category"])
            if key in seen_this_run:
                # A genuine price conflict across photos for the SAME item -
                # flag it rather than violate the (shop, name, category)
                # unique constraint with a second row.
                seen_this_run[key].price_conflict = True
                conflict_notes.append(f"price conflict for '{m['item_name']}'")
                continue
            existing = existing_by_key.get(key)
            if existing is not None:
                existing.price = m["price"]
                if m["description"]:
                    existing.description = m["description"]
                existing.source_menu = m["source"]
                seen_this_run[key] = existing
            else:
                new_item = Item(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    position=next_position,
                    name=m["item_name"],
                    category=m["category"],
                    price=m["price"],
                    description=m["description"],
                    source_menu=m["source"],
                    status=ItemStatus.NEW,
                )
                next_position += 1
                db.add(new_item)
                existing_by_key[key] = new_item
                seen_this_run[key] = new_item

        await log_many(db, job, "warn", conflict_notes)
        await db.commit()

        # Chain classification. Extraction alone leaves every item at NEW with
        # no confidence score, so the Review screen has nothing to show and the
        # user is dumped on an empty page believing the run failed. Doing it
        # here (rather than as a second call from the browser) also means
        # closing the tab between the two steps cannot strand the items.
        n_new = await db.scalar(
            select(func.count()).select_from(Item)
            .where(Item.shop_id == shop.id, Item.status == ItemStatus.NEW)
        )
        if n_new:
            await log(db, job, "info", f"extracted {n_new} item(s); classifying...")
            await run_classify(db, job, shop, api_key)
            if job.status == JobStatus.FAILED:
                return

        job.status = JobStatus.DONE
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)[:500]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise


async def run_classify(db: AsyncSession, job: Job, shop: Shop, api_key: str) -> None:
    """Classify every NEW item for `shop`, CLASSIFY_BATCH_SIZE at a time."""
    try:
        client = gemini.build_client(api_key)
        result = await db.execute(select(Item).where(Item.shop_id == shop.id, Item.status == ItemStatus.NEW).order_by(Item.position))
        items = result.scalars().all()
        job.total = len(items)
        await db.flush()

        shop_dict = _shop_dict(shop)
        batch_size = classify.CLASSIFY_BATCH_SIZE
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batch_dicts = [
                {"name": it.name, "category": it.category, "description": it.description} for it in batch
            ]
            try:
                results = await asyncio.to_thread(classify.classify_batch, client, shop_dict, batch_dicts)
            except Exception as e:
                # classify_batch does not classify its own SDK exceptions
                # (unlike generate_one/read_menu, it raises no typed
                # AuthFailure/RateLimited) - so detect auth failure from the
                # message the same way gemini.py's own markers do.
                msg = str(e)
                if gemini.is_auth_error(msg):
                    job.status = JobStatus.FAILED
                    job.error = msg[:500]
                    job.finished_at = datetime.now(timezone.utc)
                    await db.commit()
                    await log(db, job, "error", f"auth failure during classify: {msg}")
                    return
                # SPEC-GAP: SPEC.md does not define a retry/backoff policy for
                # a classify-batch rate limit or transient failure; this
                # fails just that batch (its items stay NEW for a future
                # classify run) rather than blocking the rest of the shop.
                job.failed += len(batch)
                await log(db, job, "error", f"classify batch failed: {msg}")
                await db.flush()
                continue

            for it, cls in zip(batch, results):
                it.confidence = cls["confidence"]
                it.confidence_reason = cls["reason"]
                it.concept_text = cls["concept"]
                it.suggested_vessel = cls["vessel"]
                it.suggested_props = cls["props"]
                it.product_category = cls["product_category"]
                it.status = (
                    ItemStatus.APPROVED
                    if cls["confidence"] >= classify.CONFIDENCE_AUTO_APPROVE
                    else ItemStatus.NEEDS_REVIEW
                )
                job.done += 1
            await db.flush()

        job.status = JobStatus.DONE
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)[:500]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise


async def run_host(db: AsyncSession, job: Job, shop: Shop) -> None:
    """Upload every GENERATED item's image to ImgBB, pacing PACE_SECONDS
    between uploads. An ImgbbUploadCap aborts the whole job immediately."""
    try:
        if not shop.imgbb_key_enc:
            job.status = JobStatus.FAILED
            job.error = "Shop has no imgbb key configured."
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return
        api_key = decrypt(shop.imgbb_key_enc)
        storage = get_storage()

        result = await db.execute(
            select(Item).where(Item.shop_id == shop.id, Item.status == ItemStatus.GENERATED).order_by(Item.position)
        )
        items = result.scalars().all()
        job.total = len(items)
        await db.flush()

        for idx, item in enumerate(items):
            image = await db.get(Image, item.image_id) if item.image_id else None
            if image is None:
                item.last_error = "no stored image to host"
                job.failed += 1
                await log(db, job, "error", item.last_error, item.id)
                await db.flush()
                continue
            try:
                data = await storage.get(image.storage_key)
                uploaded = await imgbb.upload(api_key, data, name=f"{shop.id}-{item.id}")
                item.imgbb_url = uploaded["url"]
                item.status = ItemStatus.HOSTED
                item.last_error = None
                job.done += 1
                await db.flush()
            except imgbb.ImgbbUploadCap as e:
                # Account-level cap - retrying anything achieves nothing.
                # Abort the whole job; remaining items simply stay GENERATED
                # for a future host run once the cap clears.
                job.status = JobStatus.FAILED
                job.error = str(e)[:500]
                job.finished_at = datetime.now(timezone.utc)
                await db.commit()
                await log(db, job, "error", f"imgbb upload cap hit: {e}", item.id)
                return
            except Exception as e:
                item.last_error = str(e)[:500]
                job.failed += 1
                await log(db, job, "error", f"host failed for {item.name}: {e}", item.id)
                await db.flush()

            if idx < len(items) - 1:
                await asyncio.sleep(imgbb.PACE_SECONDS)

        job.status = JobStatus.DONE
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)[:500]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise


async def build_export_rows(db: AsyncSession, shop: Shop) -> list[dict[str, Any]]:
    """Build SmartBiz row dicts (see app.engine.export's SPEC-GAP note on the
    row shape) from every non-SKIPPED item. HOSTED items carry an image URL;
    everything else is included without one (tracked by
    Export.included_without_image), so the workbook is still useful before a
    host run has finished."""
    result = await db.execute(
        select(Item).where(Item.shop_id == shop.id, Item.status != ItemStatus.SKIPPED).order_by(Item.position)
    )
    items = result.scalars().all()
    rows: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        rows.append({
            "row": i + 2,
            "id": str(it.id),
            "name": it.name,
            "price": float(it.price) if it.price is not None else None,
            "category": it.category,
            "product_category": it.product_category,
            "description": it.description or it.concept_text or "",
            "imgbb_url": it.imgbb_url if it.status == ItemStatus.HOSTED else None,
            "default_product_category": shop.default_product_category,
        })
    return rows


async def run_export(db: AsyncSession, job: Job, shop: Shop, user: User) -> Export:
    """Validate + build the SmartBiz workbook, store it, and record an Export row."""
    try:
        rows = await build_export_rows(db, shop)
        errors = export.validate(rows)
        if errors:
            job.status = JobStatus.FAILED
            job.error = f"{len(errors)} row(s) failed export validation."
            job.finished_at = datetime.now(timezone.utc)
            await db.commit()
            raise AppError(
                "validation_failed",
                f"{len(errors)} row(s) failed export validation.",
                status=400,
                detail={"errors": [e.__dict__ for e in errors]},
            )

        workbook_bytes = export.build_workbook(rows, shop.business_category)
        export_id = uuid.uuid4()
        storage_key = f"shops/{shop.id}/exports/{export_id}.xlsx"
        storage = get_storage()
        await storage.put(
            storage_key,
            workbook_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        included_without_image = sum(1 for r in rows if not r.get("imgbb_url"))
        export_row = Export(
            id=export_id,
            shop_id=shop.id,
            storage_key=storage_key,
            filename=_safe_filename(shop.name, "-export.xlsx"),
            row_count=len(rows),
            included_without_image=included_without_image,
            created_by=user.id,
        )
        db.add(export_row)

        job.total = len(rows)
        job.done = len(rows)
        job.status = JobStatus.DONE
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(export_row)
        return export_row
    except AppError:
        raise
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = str(e)[:500]
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        raise
