"""HTTP routes for export validation and downloading a finished SmartBiz workbook."""
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import stepper
from app.auth import current_user
from app.db import get_db
from app.engine import export as export_engine
from app.errors import AppError
from app.models import Export, Shop, User
from app.schemas import ExportOut, RowErrorOut
from app.storage import get_storage

router = APIRouter(tags=["export"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/shops/{shop_id}/exports", response_model=list[ExportOut])
async def list_exports(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ExportOut]:
    """Finished exports for this shop, newest first.

    `POST /shops/{id}/jobs/export` returns a Job, but the workbook is an
    `Export` row with its OWN id - the job id will NOT resolve at
    `/api/exports/{id}`. The UI needs this route to find the file it just
    produced.
    """
    rows = (
        await db.scalars(
            select(Export)
            .where(Export.shop_id == shop_id)
            .order_by(Export.created_at.desc())
        )
    ).all()
    return [ExportOut.model_validate(r) for r in rows]


@router.get("/shops/{shop_id}/export/validate", response_model=list[RowErrorOut])
async def validate_export(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[export_engine.RowError]:
    shop = await db.get(Shop, shop_id)
    if shop is None:
        raise AppError("not_found", "Shop not found.", status=404)
    rows = await stepper.build_export_rows(db, shop)
    return export_engine.validate(rows)


@router.get("/exports/{export_id}")
async def download_export(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    export_row = await db.get(Export, export_id)
    if export_row is None:
        raise AppError("not_found", "Export not found.", status=404)
    storage = get_storage()
    data = await storage.get(export_row.storage_key)
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{export_row.filename}"'},
    )
