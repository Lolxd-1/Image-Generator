"""Enum types shared across models, schemas, and engine modules."""
from enum import Enum


class ItemStatus(str, Enum):
    NEW = "new"            # extracted, not yet classified
    NEEDS_REVIEW = "needs_review"   # confidence < 90, waiting on admin
    AWAITING_REF = "awaiting_ref"   # admin asked to supply their own reference
    APPROVED = "approved"       # cleared for generation
    QUEUED = "queued"         # in an active generate job
    GENERATING = "generating"     # claimed by a step call, in flight
    GENERATED = "generated"      # image bytes stored
    HOSTED = "hosted"         # imgbb url present
    FAILED = "failed"         # retries exhausted
    SKIPPED = "skipped"        # admin excluded it


class JobKind(str, Enum):
    EXTRACT = "extract"
    CLASSIFY = "classify"
    GENERATE = "generate"
    HOST = "host"
    EXPORT = "export"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageKind(str, Enum):
    REFERENCE = "reference"      # the shop-wide style anchor
    ITEM_REF = "item_ref"       # admin-supplied reference for ONE dish
    MENU = "menu"           # an uploaded menu photograph
    DISH = "dish"           # a generated dish photo


# Terminal statuses for an item.
TERMINAL_ITEM_STATUSES = (
    ItemStatus.GENERATED,
    ItemStatus.HOSTED,
    ItemStatus.FAILED,
    ItemStatus.SKIPPED,
)
