"""Pydantic v2 request/response models for the API layer (app/routers/*)."""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.enums import ImageKind, ItemStatus, JobKind, JobStatus


# --- auth ---------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class GeminiKeyIn(BaseModel):
    key: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    created_at: datetime
    last_login_at: datetime | None = None


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserOut
    has_gemini_key: bool
    gemini_key_hint: str | None = None
    key_count: int = 0
    enabled_key_count: int = 0


class ApiKeyIn(BaseModel):
    key: str
    label: str | None = None


class ApiKeyPatch(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    key_hint: str
    enabled: bool
    disabled_reason: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    delay_s: float = 30.0                     # from the key's PaceState
    next_allowed_at: datetime | None = None   # from the key's PaceState
    busy: bool = False                        # PaceState.leased_until is in the future


# --- shops ----------------------------------------------------------------

class ShopContextFields(BaseModel):
    brand_archetype: str | None = None
    cuisine: str | None = None
    price_tier: str | None = None
    plating_style: str | None = None
    lighting_mood: str | None = None
    background_setting: str | None = None
    prop_density: int | None = None
    notes: str | None = None


class ShopIn(ShopContextFields):
    name: str


class ShopPatch(ShopContextFields):
    name: str | None = None
    # Archive / unarchive. Router uses exclude_unset=True, so an explicit null
    # unarchives and an omitted field leaves the current value alone.
    archived_at: datetime | None = None
    business_category: str | None = None
    default_product_category: str | None = None


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_by: uuid.UUID
    created_at: datetime
    archived_at: datetime | None = None
    brand_archetype: str | None = None
    cuisine: str | None = None
    price_tier: str | None = None
    plating_style: str | None = None
    lighting_mood: str | None = None
    background_setting: str | None = None
    prop_density: int
    notes: str | None = None
    style_profile: dict[str, Any] | None = None
    reference_image_id: uuid.UUID | None = None
    business_category: str
    default_product_category: str
    # The ciphertext itself is never serialised. The Setup screen only needs to
    # know whether a key is on file, so it can show "stored" vs an empty field.
    has_imgbb_key: bool = False


class ShopSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime
    archived_at: datetime | None = None
    item_counts: dict[str, int] = {}
    total_items: int = 0


# --- menus ------------------------------------------------------------------

class MenuUploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shop_id: uuid.UUID
    storage_key: str
    filename: str
    sha256: str
    is_menu: bool | None = None
    error: str | None = None
    extracted_at: datetime | None = None


# --- items ------------------------------------------------------------------

class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shop_id: uuid.UUID
    position: int
    name: str
    category: str
    price: float | None = None
    description: str = ""
    source_menu: str = ""
    confidence: int | None = None
    confidence_reason: str | None = None
    concept_text: str | None = None
    suggested_vessel: str | None = None
    suggested_props: list[Any] | None = None
    product_category: str | None = None
    status: ItemStatus
    manual_ref_image_id: uuid.UUID | None = None
    prompt_used: str | None = None
    attempts: int = 0
    last_error: str | None = None
    image_id: uuid.UUID | None = None
    imgbb_url: str | None = None
    price_conflict: bool = False
    updated_at: datetime


class ItemPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    price: float | None = None
    description: str | None = None
    concept_text: str | None = None
    product_category: str | None = None


class ItemPage(BaseModel):
    """Envelope for GET /api/shops/{id}/items."""
    items: list[ItemOut]
    total: int
    page: int
    page_size: int


class GeminiKeyOut(BaseModel):
    has_gemini_key: bool
    gemini_key_hint: str | None = None


# --- jobs ---------------------------------------------------------------

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shop_id: uuid.UUID
    kind: JobKind
    status: JobStatus
    total: int = 0
    done: int = 0
    failed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_by: uuid.UUID


class JobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    ts: datetime
    level: str
    item_id: uuid.UUID | None = None
    message: str


class StepItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: ItemStatus
    image_id: uuid.UUID | None = None
    error: str | None = None


StepStatus = Literal[
    "generated",    # one image succeeded            -> loop continues
    "item_failed",  # ONE item exhausted its retries -> loop CONTINUES
    "rate_limited", # 429, item requeued             -> loop continues
    "waiting",      # pace gate closed, nothing claimed -> loop continues
    "complete",     # nothing left to claim          -> loop STOPS
    "failed",       # the whole JOB died (AuthFailure only) -> loop STOPS
]


class StepResult(BaseModel):
    # `item_failed` and `failed` are deliberately distinct: one bad dish must
    # never halt a 100-item run. Only a job-level abort returns `failed`.
    status: StepStatus
    item: StepItemOut | None = None
    next_delay_ms: int | None = None
    retry_after_ms: int | None = None
    remaining: int | None = None
    done: int | None = None
    failed: int | None = None
    next_step_ms: int = 0
    key_hint: str | None = None
    lanes: int = 1


# --- images ---------------------------------------------------------------

class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shop_id: uuid.UUID
    item_id: uuid.UUID | None = None
    kind: ImageKind
    storage_key: str
    sha256: str
    bytes_len: int
    width: int | None = None
    height: int | None = None
    created_at: datetime


# --- storage ----------------------------------------------------------------

class ShopStorageOut(BaseModel):
    shop_id: uuid.UUID
    shop_name: str
    dish_bytes: int = 0
    dish_count: int = 0
    menu_bytes: int = 0
    menu_count: int = 0
    reference_bytes: int = 0
    export_bytes: int = 0
    export_count: int = 0
    total_bytes: int = 0


class StorageUsageOut(BaseModel):
    total_bytes: int = 0
    budget_bytes: int = 1_073_741_824
    shops: list[ShopStorageOut] = []


class PurgeResultOut(BaseModel):
    deleted_images: int = 0
    bytes_freed: int = 0


# --- export -----------------------------------------------------------------

class RowErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row: int
    item_id: str
    field: str
    message: str


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shop_id: uuid.UUID
    storage_key: str
    filename: str
    row_count: int
    included_without_image: int
    created_at: datetime
    created_by: uuid.UUID
