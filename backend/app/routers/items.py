"""Item listing/editing and the review-queue actions (approve/hold/skip/regenerate)."""
import hashlib
import io
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_db
from app.enums import ImageKind, ItemStatus
from app.errors import AppError
from app.models import Image, Item, User
from app.schemas import ItemOut, ItemPage, ItemPatch
from app.storage import get_storage

router = APIRouter(tags=["items"])


# Legal transition targets, keyed by the destination status, with the set of
# statuses an item may move FROM to reach it. QUEUED and GENERATING are never
# reachable from an admin action here — they belong to the generate job/
# stepper only, so an item mid-pipeline can't be edited out from under it.
#
# SPEC-GAP: SPEC §1 documents the enum and terminal statuses but not the full
# legal-transition table for admin actions. The sets below are the reasonable
# reading of the four described actions (approve/hold/skip/regenerate) plus
# the AWAITING_REF -> APPROVED move POST /items/{id}/reference performs; in
# particular APPROVED's allowed-from set is the union needed by both
# "approve" and "regenerate" since both funnel through this one helper.
_TRANSITIONS: dict[ItemStatus, frozenset[ItemStatus]] = {
    ItemStatus.APPROVED: frozenset(
        {
            ItemStatus.NEW,
            ItemStatus.NEEDS_REVIEW,
            ItemStatus.AWAITING_REF,
            ItemStatus.FAILED,
            ItemStatus.GENERATED,
            ItemStatus.HOSTED,
        }
    ),
    ItemStatus.AWAITING_REF: frozenset(
        {
            ItemStatus.NEW,
            ItemStatus.NEEDS_REVIEW,
            ItemStatus.APPROVED,
            ItemStatus.FAILED,
        }
    ),
    ItemStatus.SKIPPED: frozenset(
        {
            ItemStatus.NEW,
            ItemStatus.NEEDS_REVIEW,
            ItemStatus.AWAITING_REF,
            ItemStatus.APPROVED,
            ItemStatus.FAILED,
        }
    ),
}


def _transition(item: Item, new_status: ItemStatus) -> None:
    """The single place item.status is ever written outside the stepper.

    Rejects any move not in _TRANSITIONS with 409 conflict instead of
    scattering ad-hoc status writes across the endpoints below.
    """
    allowed_from = _TRANSITIONS.get(new_status)
    if allowed_from is None or ItemStatus(item.status) not in allowed_from:
        raise AppError(
            "conflict",
            f"Cannot move item from '{item.status}' to '{new_status.value}'.",
            status=409,
        )
    item.status = new_status


def _prepare_jpeg(data: bytes) -> tuple[bytes, int, int]:
    from PIL import Image as PILImage

    try:
        img = PILImage.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise AppError("validation_failed", "Uploaded file is not a readable image.", status=400)
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue(), img.width, img.height


async def _get_item_or_404(db: AsyncSession, item_id: uuid.UUID) -> Item:
    item = await db.get(Item, item_id)
    if item is None:
        raise AppError("not_found", "Item not found.", status=404)
    return item


@router.get("/shops/{shop_id}/items", response_model=ItemPage)
async def list_items(
    shop_id: uuid.UUID,
    status: ItemStatus | None = Query(None),
    min_conf: int | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ItemPage:
    stmt = select(Item).where(Item.shop_id == shop_id)
    if status is not None:
        stmt = stmt.where(Item.status == status.value)
    if min_conf is not None:
        stmt = stmt.where(Item.confidence >= min_conf)
    if q:
        stmt = stmt.where(Item.name.ilike(f"%{q}%"))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    stmt = stmt.order_by(Item.position).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()

    return ItemPage(
        items=[ItemOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/items/{item_id}", response_model=ItemOut)
async def patch_item(
    item_id: uuid.UUID, payload: ItemPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_item_or_404(db, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.post("/items/{item_id}/approve", response_model=ItemOut)
async def approve_item(
    item_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_item_or_404(db, item_id)
    _transition(item, ItemStatus.APPROVED)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.post("/items/{item_id}/hold", response_model=ItemOut)
async def hold_item(
    item_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_item_or_404(db, item_id)
    _transition(item, ItemStatus.AWAITING_REF)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.post("/items/{item_id}/skip", response_model=ItemOut)
async def skip_item(
    item_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_item_or_404(db, item_id)
    _transition(item, ItemStatus.SKIPPED)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.post("/items/{item_id}/regenerate", response_model=ItemOut)
async def regenerate_item(
    item_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ItemOut:
    item = await _get_item_or_404(db, item_id)
    _transition(item, ItemStatus.APPROVED)
    item.image_id = None
    item.last_error = None
    item.attempts = 0
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.post("/items/{item_id}/reference", response_model=ItemOut)
async def upload_item_reference(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    item = await _get_item_or_404(db, item_id)
    raw = await file.read()
    jpeg, width, height = _prepare_jpeg(raw)

    image_id = uuid.uuid4()
    storage_key = f"shops/{item.shop_id}/{ImageKind.ITEM_REF.value}/{image_id}.jpg"
    await get_storage().put(storage_key, jpeg, "image/jpeg")

    db.add(
        Image(
            id=image_id,
            shop_id=item.shop_id,
            item_id=item.id,
            kind=ImageKind.ITEM_REF,
            storage_key=storage_key,
            sha256=hashlib.sha256(jpeg).hexdigest(),
            bytes_len=len(jpeg),
            width=width,
            height=height,
        )
    )
    item.manual_ref_image_id = image_id
    _transition(item, ItemStatus.APPROVED)

    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)
