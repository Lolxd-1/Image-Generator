"""Shop CRUD, the style-profile reference upload, and menu-photo uploads."""
import hashlib
import io
import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto
from app.auth import current_user
from app.db import get_db
from app.engine import keypool
from app.engine.gemini import build_client
from app.engine.prompt import derive_style_profile
from app.enums import ImageKind
from app.errors import AppError
from app.models import Image, Item, MenuUpload, Shop, User
from app.schemas import MenuUploadOut, ShopIn, ShopOut, ShopPatch, ShopSummary
from app.storage import get_storage

router = APIRouter(prefix="/shops", tags=["shops"])


class ImgbbKeyIn(BaseModel):
    key: str


class ReferenceUploadOut(BaseModel):
    image_id: uuid.UUID
    style_profile: dict


def _to_shop_out(shop: Shop) -> ShopOut:
    out = ShopOut.model_validate(shop)
    out.has_imgbb_key = bool(shop.imgbb_key_enc)
    return out


# extract_menu.py used MAX_DIM=1600 / quality 92: large enough to keep a menu
# board's small print legible, small enough to stay cheap. Without a downscale
# an 8.6 MB phone photo stores as ~2.9 MB and eats the 1 GB storage budget in
# a few shops.
UPLOAD_MAX_DIM = 1600
UPLOAD_QUALITY = 92


def _prepare_jpeg(data: bytes, max_dim: int = UPLOAD_MAX_DIM) -> tuple[bytes, int, int]:
    """Normalise any uploaded image to a bounded JPEG — storage keys end .jpg."""
    from PIL import Image as PILImage

    try:
        img = PILImage.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise AppError("validation_failed", "Uploaded file is not a readable image.", status=400)
    img = img.convert("RGB")
    if max(img.width, img.height) > max_dim:
        img.thumbnail((max_dim, max_dim), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=UPLOAD_QUALITY, optimize=True)
    return buf.getvalue(), img.width, img.height


async def _get_shop_or_404(db: AsyncSession, shop_id: uuid.UUID) -> Shop:
    shop = await db.get(Shop, shop_id)
    if shop is None:
        raise AppError("not_found", "Shop not found.", status=404)
    return shop


@router.get("", response_model=list[ShopSummary])
async def list_shops(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> list[ShopSummary]:
    shops = (await db.execute(select(Shop).order_by(Shop.created_at.desc()))).scalars().all()

    # ONE grouped query for every shop's item_counts — never a query per shop.
    count_rows = (
        await db.execute(select(Item.shop_id, Item.status, func.count(Item.id)).group_by(Item.shop_id, Item.status))
    ).all()
    counts_by_shop: dict[uuid.UUID, dict[str, int]] = {}
    for shop_id, status, count in count_rows:
        counts_by_shop.setdefault(shop_id, {})[str(status)] = count

    result = []
    for shop in shops:
        counts = counts_by_shop.get(shop.id, {})
        result.append(
            ShopSummary(
                id=shop.id,
                name=shop.name,
                created_at=shop.created_at,
                archived_at=shop.archived_at,
                item_counts=counts,
                total_items=sum(counts.values()),
            )
        )
    return result


@router.post("", response_model=ShopOut, status_code=201)
async def create_shop(payload: ShopIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ShopOut:
    shop = Shop(name=payload.name, created_by=user.id, **payload.model_dump(exclude={"name"}, exclude_none=True))
    db.add(shop)
    await db.commit()
    await db.refresh(shop)
    return _to_shop_out(shop)


@router.get("/{shop_id}", response_model=ShopOut)
async def get_shop(shop_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ShopOut:
    shop = await _get_shop_or_404(db, shop_id)
    return _to_shop_out(shop)


@router.patch("/{shop_id}", response_model=ShopOut)
async def patch_shop(
    shop_id: uuid.UUID, payload: ShopPatch, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> ShopOut:
    shop = await _get_shop_or_404(db, shop_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shop, field, value)
    await db.commit()
    await db.refresh(shop)
    return _to_shop_out(shop)


@router.post("/{shop_id}/reference", response_model=ReferenceUploadOut)
async def upload_reference(
    shop_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ReferenceUploadOut:
    shop = await _get_shop_or_404(db, shop_id)
    raw = await file.read()
    jpeg, width, height = _prepare_jpeg(raw)

    image_id = uuid.uuid4()
    storage_key = f"shops/{shop_id}/{ImageKind.REFERENCE.value}/{image_id}.jpg"
    await get_storage().put(storage_key, jpeg, "image/jpeg")

    api_key = await keypool.pick_any(db, user.id)
    client = build_client(api_key)
    try:
        style_profile = derive_style_profile(client, jpeg)
    except Exception as exc:  # noqa: BLE001
        # SPEC-GAP: prompt.derive_style_profile's failure contract (auth vs
        # rate-limit vs generic) isn't documented in SPEC §5 the way
        # generate_one's is. Treated as a generic validation failure here.
        raise AppError("validation_failed", "Could not analyse the reference image.", status=400) from exc

    image = Image(
        id=image_id,
        shop_id=shop_id,
        kind=ImageKind.REFERENCE,
        storage_key=storage_key,
        sha256=hashlib.sha256(jpeg).hexdigest(),
        bytes_len=len(jpeg),
        width=width,
        height=height,
    )
    db.add(image)
    shop.style_profile = style_profile
    shop.reference_image_id = image_id
    await db.commit()

    return ReferenceUploadOut(image_id=image_id, style_profile=style_profile)


@router.post("/{shop_id}/menus", response_model=list[MenuUploadOut])
async def upload_menus(
    shop_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MenuUploadOut]:
    await _get_shop_or_404(db, shop_id)
    storage = get_storage()

    results: list[MenuUpload] = []
    for upload in files:
        raw = await upload.read()
        sha256 = hashlib.sha256(raw).hexdigest()

        existing = await db.scalar(
            select(MenuUpload).where(MenuUpload.shop_id == shop_id, MenuUpload.sha256 == sha256)
        )
        if existing is not None:
            results.append(existing)
            continue

        jpeg, _width, _height = _prepare_jpeg(raw)
        menu_id = uuid.uuid4()
        storage_key = f"shops/{shop_id}/{ImageKind.MENU.value}/{menu_id}.jpg"
        await storage.put(storage_key, jpeg, "image/jpeg")

        menu = MenuUpload(
            id=menu_id,
            shop_id=shop_id,
            storage_key=storage_key,
            filename=upload.filename or f"{menu_id}.jpg",
            sha256=sha256,
        )
        db.add(menu)
        results.append(menu)

    await db.commit()
    for menu in results:
        await db.refresh(menu)
    return [MenuUploadOut.model_validate(menu) for menu in results]


@router.get("/{shop_id}/menus", response_model=list[MenuUploadOut])
async def list_menus(
    shop_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MenuUploadOut]:
    """Menu photos already attached to this shop.

    Without this, the Setup screen can only show photos uploaded in the current
    browser session - reloading the page would make existing uploads invisible
    and invite the user to upload them all over again.
    """
    await _get_shop_or_404(db, shop_id)
    rows = (
        await db.scalars(
            select(MenuUpload)
            .where(MenuUpload.shop_id == shop_id)
            .order_by(MenuUpload.id)
        )
    ).all()
    return [MenuUploadOut.model_validate(r) for r in rows]


@router.get("/{shop_id}/menus/{menu_id}/file")
async def get_menu_file(
    shop_id: uuid.UUID,
    menu_id: uuid.UUID,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """The stored menu photograph itself, for thumbnails on the Setup screen."""
    menu = await db.get(MenuUpload, menu_id)
    if menu is None or menu.shop_id != shop_id:
        raise AppError("not_found", "Menu upload not found.", status=404)
    data = await get_storage().get(menu.storage_key)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/{shop_id}/menus/{menu_id}", status_code=204)
async def delete_menu(
    shop_id: uuid.UUID, menu_id: uuid.UUID, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    menu = await db.get(MenuUpload, menu_id)
    if menu is None or menu.shop_id != shop_id:
        raise AppError("not_found", "Menu upload not found.", status=404)
    await get_storage().delete(menu.storage_key)
    await db.delete(menu)
    await db.commit()
    return Response(status_code=204)


@router.put("/{shop_id}/imgbb-key", status_code=204)
async def put_imgbb_key(
    shop_id: uuid.UUID, payload: ImgbbKeyIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    shop = await _get_shop_or_404(db, shop_id)
    shop.imgbb_key_enc = crypto.encrypt(payload.key.strip())
    await db.commit()
    return Response(status_code=204)
