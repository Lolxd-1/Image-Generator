"""SQLAlchemy 2.0 declarative models for every table in the schema."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.enums import ImageKind, ItemStatus, JobKind, JobStatus


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)  # bcrypt via passlib
    gemini_key_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    gemini_key_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("user_id", "key_hash", name="uq_api_keys_user_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String, default="")
    key_enc: Mapped[str] = mapped_column(String)
    key_hint: Mapped[str] = mapped_column(String)
    key_hash: Mapped[str] = mapped_column(String, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Shop(Base):
    __tablename__ = "shops"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- the 7 context metrics (free text, all nullable) ---
    brand_archetype: Mapped[str | None] = mapped_column(String, nullable=True)
    cuisine: Mapped[str | None] = mapped_column(String, nullable=True)
    price_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    plating_style: Mapped[str | None] = mapped_column(String, nullable=True)
    lighting_mood: Mapped[str | None] = mapped_column(String, nullable=True)
    background_setting: Mapped[str | None] = mapped_column(String, nullable=True)
    prop_density: Mapped[int] = mapped_column(Integer, default=1)  # 0..3
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- derived / config ---
    style_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reference_image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("images.id", use_alter=True, name="fk_shops_reference_image_id"),
        nullable=True,
    )
    imgbb_key_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    business_category: Mapped[str] = mapped_column(String, default="FOOD_AND_GROCERY")
    default_product_category: Mapped[str] = mapped_column(String, default="Other Food and Grocery")


class MenuUpload(Base):
    __tablename__ = "menu_uploads"
    __table_args__ = (UniqueConstraint("shop_id", "sha256", name="uq_menu_uploads_shop_sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"))
    storage_key: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_menu: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("shop_id", "name", "category", name="uq_items_shop_name_category"),
        Index("ix_items_shop_status", "shop_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # display + generation order
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    description: Mapped[str] = mapped_column(String, default="")
    source_menu: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0..100
    confidence_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    concept_text: Mapped[str | None] = mapped_column(String, nullable=True)  # the review card body
    suggested_vessel: Mapped[str | None] = mapped_column(String, nullable=True)
    suggested_props: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    product_category: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[ItemStatus] = mapped_column(String, default=ItemStatus.NEW, index=True)
    manual_ref_image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("images.id", use_alter=True, name="fk_items_manual_ref_image_id"),
        nullable=True,
    )
    prompt_used: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("images.id", use_alter=True, name="fk_items_image_id"),
        nullable=True,
    )
    imgbb_url: Mapped[str | None] = mapped_column(String, nullable=True)
    price_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", use_alter=True, name="fk_images_item_id"),
        nullable=True,
    )
    kind: Mapped[ImageKind] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    bytes_len: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"), index=True)
    kind: Mapped[JobKind] = mapped_column(String)
    status: Mapped[JobStatus] = mapped_column(String)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    api_key_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String)  # "info" | "warn" | "error"
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message: Mapped[str] = mapped_column(String)


class PaceState(Base):
    """Survives restarts: one row per Gemini API key hash."""

    __tablename__ = "pace_state"

    api_key_hash: Mapped[str] = mapped_column(String, primary_key=True)
    delay_s: Mapped[float] = mapped_column(Float, default=30.0)
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Concurrency lease held by an in-flight /step call for this key.
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_429: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"))
    storage_key: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    row_count: Mapped[int] = mapped_column(Integer)
    included_without_image: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
