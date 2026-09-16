"""Serving stored image bytes, single and as a streamed zip of a shop's dishes."""
import re
import uuid
import zipfile
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.db import get_db
from app.enums import ImageKind
from app.errors import AppError
from app.models import Image, Item, Shop, User
from app.storage import get_storage

router = APIRouter(tags=["images"])

CONTENT_TYPE = "image/jpeg"  # every stored image is normalised to .jpg on upload


def _sanitize_filename(name: str) -> str:
    """Strip path separators and non-ASCII so this is safe in a
    Content-Disposition header and on any filesystem."""
    ascii_name = name.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]+", "", ascii_name).strip(" .")
    return cleaned or "image"


async def _filename_for(db: AsyncSession, image: Image) -> str:
    base = image.kind
    if image.item_id is not None:
        item = await db.get(Item, image.item_id)
        if item is not None:
            base = item.name
    return f"{_sanitize_filename(str(base))}.jpg"


class _ChunkedWriter:
    """Minimal file-like object zipfile can write to: buffers bytes written
    since the last pop so the caller can yield them and free the memory,
    rather than materialising the whole archive at once."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._pos = 0

    def write(self, data: bytes) -> int:
        self._chunks.append(bytes(data))
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def flush(self) -> None:  # pragma: no cover - zipfile calls this defensively
        pass

    def pop(self) -> list[bytes]:
        chunks, self._chunks = self._chunks, []
        return chunks


async def _zip_dish_images(db: AsyncSession, shop_id: uuid.UUID) -> AsyncIterator[bytes]:
    writer = _ChunkedWriter()
    zf = zipfile.ZipFile(writer, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True)
    storage = get_storage()

    stmt = (
        select(Image, Item.name)
        .join(Item, Item.image_id == Image.id)
        .where(Item.shop_id == shop_id, Image.kind == ImageKind.DISH.value)
        .order_by(Item.position)
    )
    rows = (await db.execute(stmt)).all()

    used_names: set[str] = set()
    for image, item_name in rows:
        data = await storage.get(image.storage_key)  # one image at a time, never the whole archive
        name = f"{_sanitize_filename(item_name)}.jpg"
        if name in used_names:
            name = f"{_sanitize_filename(item_name)}-{str(image.id)[:8]}.jpg"
        used_names.add(name)
        zf.writestr(name, data)
        for chunk in writer.pop():
            yield chunk

    zf.close()
    for chunk in writer.pop():
        yield chunk


@router.get("/images/{image_id}")
async def get_image(
    image_id: uuid.UUID,
    download: int = Query(0),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    image = await db.get(Image, image_id)
    if image is None:
        raise AppError("not_found", "Image not found.", status=404)
    data = await get_storage().get(image.storage_key)

    headers = {}
    if download:
        filename = await _filename_for(db, image)
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(content=data, media_type=CONTENT_TYPE, headers=headers)


@router.get("/shops/{shop_id}/images.zip")
async def download_images_zip(
    shop_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    shop = await db.get(Shop, shop_id)
    if shop is None:
        raise AppError("not_found", "Shop not found.", status=404)

    filename = f"{_sanitize_filename(shop.name)}-images.zip"
    return StreamingResponse(
        _zip_dish_images(db, shop_id),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
