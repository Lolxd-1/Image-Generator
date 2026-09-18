"""Storage usage summaries, the "free up space" dish-image purge, and full shop delete."""
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_db
from app.enums import ImageKind, JobStatus
from app.errors import AppError
from app.models import Export, Image, Item, Job, JobEvent, MenuUpload, Shop, User
from app.schemas import PurgeResultOut, ShopStorageOut, StorageUsageOut
from app.storage import get_storage

router = APIRouter(tags=["storage"])

BUDGET_BYTES = 1_073_741_824

EXPORT_KIND = "export"  # Export rows have no ImageKind; this is their StoredObject.kind


@dataclass(frozen=True)
class StoredObject:
    key: str
    kind: str          # "dish" | "menu" | "reference" | "item_ref" | "export"
    bytes_len: int


def summarise(objects: Sequence[StoredObject]) -> dict[str, tuple[int, int]]:
    """kind -> (count, bytes). Only kinds actually present in `objects` are returned."""
    totals: dict[str, list[int]] = {}
    for obj in objects:
        entry = totals.setdefault(obj.kind, [0, 0])
        entry[0] += 1
        entry[1] += obj.bytes_len
    return {kind: (count, total) for kind, (count, total) in totals.items()}


def purge_plan(objects: Sequence[StoredObject]) -> list[str]:
    """Storage keys to delete for a "free up space" purge: dish images only."""
    return [obj.key for obj in objects if obj.kind == ImageKind.DISH.value]


def delete_plan(objects: Sequence[StoredObject]) -> list[str]:
    """Storage keys to delete for a full catalog delete: every object, deduplicated, order preserved."""
    seen: set[str] = set()
    keys: list[str] = []
    for obj in objects:
        if obj.key not in seen:
            seen.add(obj.key)
            keys.append(obj.key)
    return keys


def _shop_storage_out(shop: Shop, kinds: dict[str, tuple[int, int]]) -> ShopStorageOut:
    """Build a ShopStorageOut from a kind -> (count, bytes) summary. `reference_bytes`
    covers both the `reference` and `item_ref` kinds (both are anchor-style, not budget-eating
    dish images)."""
    dish_count, dish_bytes = kinds.get(ImageKind.DISH.value, (0, 0))
    menu_count, menu_bytes = kinds.get(ImageKind.MENU.value, (0, 0))
    export_count, export_bytes = kinds.get(EXPORT_KIND, (0, 0))
    ref_count, ref_bytes = kinds.get(ImageKind.REFERENCE.value, (0, 0))
    item_ref_count, item_ref_bytes = kinds.get(ImageKind.ITEM_REF.value, (0, 0))
    reference_bytes = ref_bytes + item_ref_bytes
    return ShopStorageOut(
        shop_id=shop.id,
        shop_name=shop.name,
        dish_bytes=dish_bytes,
        dish_count=dish_count,
        menu_bytes=menu_bytes,
        menu_count=menu_count,
        reference_bytes=reference_bytes,
        export_bytes=export_bytes,
        export_count=export_count,
        total_bytes=dish_bytes + menu_bytes + export_bytes + reference_bytes,
    )


async def _get_shop_or_404(db: AsyncSession, shop_id: uuid.UUID) -> Shop:
    shop = await db.get(Shop, shop_id)
    if shop is None:
        raise AppError("not_found", "Shop not found.", status=404)
    return shop


async def _refuse_if_job_running(db: AsyncSession, shop_id: uuid.UUID) -> None:
    """Deleting images (or the whole shop) out from under a generate run corrupts it."""
    running = await db.scalar(
        select(Job.id).where(Job.shop_id == shop_id, Job.status == JobStatus.RUNNING).limit(1)
    )
    if running is not None:
        raise AppError("conflict", "A job is running for this shop.", status=409)


async def _collect(db: AsyncSession, shop_id: uuid.UUID) -> list[StoredObject]:
    """Every stored object a shop owns: images (with real byte counts), plus menu uploads
    and exports, which carry no byte count. Menu photos are bounded at 1600px/q92 by
    shops.py:_prepare_jpeg and are not the budget problem dish images are, so they - like
    exports - are recorded at bytes_len=0 rather than estimated."""
    images = (
        await db.execute(
            select(Image.storage_key, Image.kind, Image.bytes_len).where(Image.shop_id == shop_id)
        )
    ).all()
    menu_keys = (
        await db.execute(select(MenuUpload.storage_key).where(MenuUpload.shop_id == shop_id))
    ).scalars().all()
    export_keys = (
        await db.execute(select(Export.storage_key).where(Export.shop_id == shop_id))
    ).scalars().all()

    objects = [StoredObject(key=key, kind=kind, bytes_len=bytes_len) for key, kind, bytes_len in images]
    objects += [StoredObject(key=key, kind=ImageKind.MENU.value, bytes_len=0) for key in menu_keys]
    objects += [StoredObject(key=key, kind=EXPORT_KIND, bytes_len=0) for key in export_keys]
    return objects


@router.get("/storage", response_model=StorageUsageOut)
async def get_storage_usage(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> StorageUsageOut:
    """Every shop, including archived ones. Grouped queries only - never a query per shop."""
    shops = (await db.execute(select(Shop).order_by(Shop.created_at.desc()))).scalars().all()

    image_rows = (
        await db.execute(
            select(Image.shop_id, Image.kind, func.count(Image.id), func.sum(Image.bytes_len)).group_by(
                Image.shop_id, Image.kind
            )
        )
    ).all()
    menu_rows = (
        await db.execute(select(MenuUpload.shop_id, func.count(MenuUpload.id)).group_by(MenuUpload.shop_id))
    ).all()
    export_rows = (
        await db.execute(select(Export.shop_id, func.count(Export.id)).group_by(Export.shop_id))
    ).all()

    kinds_by_shop: dict[uuid.UUID, dict[str, tuple[int, int]]] = {}
    for shop_id, kind, count, total_bytes in image_rows:
        kinds_by_shop.setdefault(shop_id, {})[kind] = (count, int(total_bytes or 0))
    for shop_id, count in menu_rows:
        kinds_by_shop.setdefault(shop_id, {})[ImageKind.MENU.value] = (count, 0)
    for shop_id, count in export_rows:
        kinds_by_shop.setdefault(shop_id, {})[EXPORT_KIND] = (count, 0)

    shop_summaries = [_shop_storage_out(shop, kinds_by_shop.get(shop.id, {})) for shop in shops]
    return StorageUsageOut(
        total_bytes=sum(s.total_bytes for s in shop_summaries),
        budget_bytes=BUDGET_BYTES,
        shops=shop_summaries,
    )


@router.get("/shops/{shop_id}/storage", response_model=ShopStorageOut)
async def get_shop_storage(
    shop_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ShopStorageOut:
    shop = await _get_shop_or_404(db, shop_id)
    summary = summarise(await _collect(db, shop_id))
    return _shop_storage_out(shop, summary)


@router.post("/shops/{shop_id}/purge-images", response_model=PurgeResultOut)
async def purge_images(
    shop_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> PurgeResultOut:
    await _get_shop_or_404(db, shop_id)
    await _refuse_if_job_running(db, shop_id)

    rows = (
        await db.execute(
            select(Image.id, Image.storage_key, Image.bytes_len).where(
                Image.shop_id == shop_id, Image.kind == ImageKind.DISH.value
            )
        )
    ).all()
    if not rows:
        return PurgeResultOut(deleted_images=0, bytes_freed=0)

    image_ids = [row.id for row in rows]
    objects = [StoredObject(key=row.storage_key, kind=ImageKind.DISH.value, bytes_len=row.bytes_len) for row in rows]

    # Null the FK before the delete so it doesn't block on rows referencing a
    # purged image. Item statuses are deliberately left alone: a `hosted`
    # item keeps its imgbb URL and still exports; a `generated` item simply
    # no longer has local bytes.
    await db.execute(update(Item).where(Item.shop_id == shop_id, Item.image_id.in_(image_ids)).values(image_id=None))
    await get_storage().delete_many(purge_plan(objects))
    await db.execute(delete(Image).where(Image.id.in_(image_ids)))
    await db.commit()

    return PurgeResultOut(deleted_images=len(image_ids), bytes_freed=sum(row.bytes_len for row in rows))


@router.delete("/shops/{shop_id}", status_code=204)
async def delete_shop(
    shop_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    shop = await _get_shop_or_404(db, shop_id)
    await _refuse_if_job_running(db, shop_id)

    # Blobs first: an orphaned blob is worse than an orphaned row because
    # nothing in the app can find it again once the row is gone.
    await get_storage().delete_many(delete_plan(await _collect(db, shop_id)))

    shop.reference_image_id = None
    await db.execute(
        update(Item).where(Item.shop_id == shop_id).values(image_id=None, manual_ref_image_id=None)
    )
    await db.execute(update(Image).where(Image.shop_id == shop_id).values(item_id=None))
    await db.flush()

    await db.execute(delete(JobEvent).where(JobEvent.job_id.in_(select(Job.id).where(Job.shop_id == shop_id))))
    await db.execute(delete(Job).where(Job.shop_id == shop_id))
    await db.execute(delete(Export).where(Export.shop_id == shop_id))
    await db.execute(delete(Image).where(Image.shop_id == shop_id))
    await db.execute(delete(Item).where(Item.shop_id == shop_id))
    await db.execute(delete(MenuUpload).where(MenuUpload.shop_id == shop_id))
    await db.delete(shop)
    await db.commit()
    return Response(status_code=204)
