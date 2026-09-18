"""HTTP routes for job lifecycle: create, poll, cancel, and the /step generate loop."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import stepper
from app.auth import current_user
from app.db import get_db
from app.engine import keypool
from app.enums import ItemStatus, JobKind, JobStatus
from app.errors import AppError
from app.models import Item, Job, JobEvent, Shop, User
from app.schemas import JobEventOut, JobOut, StepResult

router = APIRouter(tags=["jobs"])


async def _load_shop(db: AsyncSession, shop_id: uuid.UUID) -> Shop:
    shop = await db.get(Shop, shop_id)
    if shop is None:
        raise AppError("not_found", "Shop not found.", status=404)
    return shop


async def _load_job(db: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise AppError("not_found", "Job not found.", status=404)
    return job


@router.post("/shops/{shop_id}/jobs/{kind}", response_model=JobOut)
async def create_job(
    shop_id: uuid.UUID,
    kind: JobKind,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Job:
    """Create a job. `generate` only starts the job (the browser drives it via
    /step); extract, classify, host and export run to completion here and
    return a finished Job. Only one RUNNING job per shop is allowed at a time
    (enforced in stepper.start_job)."""
    shop = await _load_shop(db, shop_id)

    if kind == JobKind.GENERATE:
        return await stepper.start_job(db, shop, user, kind)

    if kind in (JobKind.EXTRACT, JobKind.CLASSIFY):
        api_key = await keypool.pick_any(db, user.id)
        job = await stepper.start_job(db, shop, user, kind)
        if kind == JobKind.EXTRACT:
            await stepper.run_extract(db, job, shop, api_key)
        else:
            await stepper.run_classify(db, job, shop, api_key)
        return job

    if kind == JobKind.HOST:
        job = await stepper.start_job(db, shop, user, kind)
        await stepper.run_host(db, job, shop)
        return job

    # kind == JobKind.EXPORT
    job = await stepper.start_job(db, shop, user, kind)
    await stepper.run_export(db, job, shop, user)
    return job


@router.get("/shops/{shop_id}/jobs/active", response_model=JobOut | None)
async def active_job(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Job | None:
    """The shop's currently RUNNING job, if any.

    Without this, resuming an interrupted generate run depends on the browser
    remembering the job id, so a different browser or a cleared cache would
    strand a half-finished run. The DB already knows; this just exposes it.
    """
    return await db.scalar(
        select(Job)
        .where(Job.shop_id == shop_id, Job.status == JobStatus.RUNNING)
        .order_by(Job.started_at.desc())
        .limit(1)
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)) -> Job:
    return await _load_job(db, job_id)


@router.get("/jobs/{job_id}/events", response_model=list[JobEventOut])
async def get_job_events(
    job_id: uuid.UUID,
    after: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[JobEvent]:
    await _load_job(db, job_id)  # 404 if the job doesn't exist
    stmt = select(JobEvent).where(JobEvent.job_id == job_id)
    if after is not None:
        stmt = stmt.where(JobEvent.ts > after)
    stmt = stmt.order_by(JobEvent.ts.asc()).limit(500)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)) -> Job:
    job = await _load_job(db, job_id)
    if job.status in (JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED):
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(timezone.utc)
        if job.kind == JobKind.GENERATE:
            # QUEUED means "in an ACTIVE generate job" - once cancelled there
            # is no active job, so hand any still-queued items back to
            # APPROVED rather than leaving them in a state that claims to
            # belong to a job that no longer exists.
            await db.execute(
                update(Item)
                .where(Item.shop_id == job.shop_id, Item.status == ItemStatus.QUEUED)
                .values(status=ItemStatus.APPROVED)
                .execution_options(synchronize_session=False)
            )
        await db.commit()
        await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/step", response_model=StepResult)
async def step_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(current_user)) -> dict:
    job = await _load_job(db, job_id)
    shop = await _load_shop(db, job.shop_id)
    return await stepper.generate_step(db, job, shop, user)
