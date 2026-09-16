# SPEC.md — implementation contract

**Read this file and only the files your task assigns you. Do not explore the
wider repo; everything you need is here.** If something is genuinely
underspecified, implement the simplest thing consistent with this file and
leave a `# SPEC-GAP:` comment. Never invent a new dependency, never rename a
symbol defined here, never touch a file another agent owns.

- Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, asyncpg.
- Frontend: React 18 + Vite + TypeScript + TailwindCSS + TanStack Query.
- Money/prices are `Numeric(10,2)`. All timestamps `TIMESTAMPTZ`, UTC, server-side default.
- All ids are `UUID` (`uuid4`, generated app-side).
- Every module gets a module docstring: one line on what it owns.

---

## 0. Environment variables

```
DATABASE_URL          postgresql+asyncpg://...      (Supabase pooler URI)
SUPABASE_URL          https://xxxx.supabase.co
SUPABASE_SERVICE_KEY  service-role key (server only, never sent to client)
SUPABASE_BUCKET       menu-catalog
SESSION_SECRET        random 32+ bytes, signs the session cookie
FERNET_KEY            urlsafe base64 32-byte key, encrypts stored API keys
APP_USERS             JSON: [{"username":"omkar","password":"..."}, ...]
STORAGE_BACKEND       "supabase" (default) | "local"   ("local" = tests/dev)
LOCAL_STORAGE_DIR     ./_storage  (only when STORAGE_BACKEND=local)
```

`config.py` exposes a single `Settings(BaseSettings)` instance named
`settings`. Nothing else in the app may read `os.environ` directly.

---

## 1. Enums (`app/enums.py`)

```python
class ItemStatus(str, Enum):
    NEW          = "new"            # extracted, not yet classified
    NEEDS_REVIEW = "needs_review"   # confidence < 90, waiting on admin
    AWAITING_REF = "awaiting_ref"   # admin asked to supply their own reference
    APPROVED     = "approved"       # cleared for generation
    QUEUED       = "queued"         # in an active generate job
    GENERATING   = "generating"     # claimed by a step call, in flight
    GENERATED    = "generated"      # image bytes stored
    HOSTED       = "hosted"         # imgbb url present
    FAILED       = "failed"         # retries exhausted
    SKIPPED      = "skipped"        # admin excluded it

class JobKind(str, Enum):
    EXTRACT = "extract"; CLASSIFY = "classify"; GENERATE = "generate"
    HOST = "host"; EXPORT = "export"

class JobStatus(str, Enum):
    PENDING = "pending"; RUNNING = "running"; PAUSED = "paused"
    DONE = "done"; FAILED = "failed"; CANCELLED = "cancelled"

class ImageKind(str, Enum):
    REFERENCE = "reference"      # the shop-wide style anchor
    ITEM_REF  = "item_ref"       # admin-supplied reference for ONE dish
    MENU      = "menu"           # an uploaded menu photograph
    DISH      = "dish"           # a generated dish photo
```

Terminal statuses for an item: `GENERATED`, `HOSTED`, `FAILED`, `SKIPPED`.

---

## 2. Database models (`app/models.py`)

SQLAlchemy 2.0 declarative, `Mapped[...]` / `mapped_column`. Base in `app/db.py`.
Table names are the plural snake_case shown. Add the indexes marked.

```python
class User(Base):            # users
    id: UUID pk
    username: str unique index
    password_hash: str                  # bcrypt via passlib
    gemini_key_enc: str | None          # Fernet ciphertext
    gemini_key_hint: str | None         # last 4 chars only, for the UI
    created_at, last_login_at: datetime | None

class Shop(Base):            # shops
    id: UUID pk
    name: str
    created_by: UUID fk users.id
    created_at: datetime; archived_at: datetime | None
    # --- the 7 context metrics (free text, all nullable) ---
    brand_archetype, cuisine, price_tier, plating_style,
    lighting_mood, background_setting: str | None
    prop_density: int = 1               # 0..3
    notes: str | None
    # --- derived / config ---
    style_profile: dict | None          # JSONB, see StyleProfile §5
    reference_image_id: UUID | None fk images.id
    imgbb_key_enc: str | None
    business_category: str = "FOOD_AND_GROCERY"
    default_product_category: str = "Other Food and Grocery"

class MenuUpload(Base):      # menu_uploads
    id, shop_id fk, storage_key: str, filename: str
    sha256: str                          # UniqueConstraint(shop_id, sha256)
    raw_json: dict | None                # JSONB, the model's reply
    is_menu: bool | None
    error: str | None
    extracted_at: datetime | None

class Item(Base):            # items
    id: UUID pk
    shop_id: UUID fk index
    position: int                        # display + generation order
    name: str; category: str; price: Numeric(10,2) | None
    description: str = ""; source_menu: str = ""
    confidence: int | None               # 0..100
    confidence_reason: str | None
    concept_text: str | None             # the review card body
    suggested_vessel: str | None
    suggested_props: list | None         # JSONB
    product_category: str | None         # one of EXPORT_FOOD_CATEGORIES
    status: ItemStatus = NEW  index
    manual_ref_image_id: UUID | None fk images.id
    prompt_used: str | None
    attempts: int = 0
    last_error: str | None
    image_id: UUID | None fk images.id
    imgbb_url: str | None
    price_conflict: bool = False
    updated_at: datetime  (onupdate=now)
    # UniqueConstraint(shop_id, name, category)
    # Index(shop_id, status)

class Image(Base):           # images
    id, shop_id fk, item_id: UUID | None fk
    kind: ImageKind
    storage_key: str; sha256: str
    bytes_len: int; width: int | None; height: int | None
    created_at

class Job(Base):             # jobs
    id, shop_id fk index, kind: JobKind, status: JobStatus
    total: int = 0; done: int = 0; failed: int = 0
    started_at, finished_at: datetime | None
    error: str | None
    created_by: UUID fk users.id
    api_key_hash: str | None

class JobEvent(Base):        # job_events
    id, job_id fk index, ts: datetime
    level: str                           # "info" | "warn" | "error"
    item_id: UUID | None
    message: str

class PaceState(Base):       # pace_state    <-- survives restarts
    api_key_hash: str primary key
    delay_s: float = 30.0
    next_allowed_at: datetime | None
    consecutive_429: int = 0
    updated_at: datetime

class Export(Base):          # exports
    id, shop_id fk, storage_key: str, filename: str
    row_count: int; included_without_image: int
    created_at; created_by fk users.id
```

Schema is created with `Base.metadata.create_all` on startup (no Alembic —
this is an internal tool with one deployment).

---

## 3. Conventions

### Error envelope
Every non-2xx returns:
```json
{ "error": { "code": "rate_limited", "message": "human readable", "detail": {} } }
```
Raise `app.errors.AppError(code, message, status=400, detail=None)`; one
exception handler in `main.py` renders it. Codes used: `unauthorized`,
`not_found`, `validation_failed`, `no_api_key`, `auth_failure`,
`rate_limited`, `imgbb_cap`, `conflict`, `job_not_running`.

### Auth
- Session cookie `session`, signed with `SESSION_SECRET` via `itsdangerous`,
  `httponly=True, samesite="lax", secure=True`, 30-day expiry.
- Dependency `current_user(request) -> User` raises `unauthorized` if absent.
- Users are seeded from `APP_USERS` at startup: insert if the username is
  missing, otherwise leave untouched. Passwords hashed with bcrypt.

### Routing convention (do not break this)
Routers declare paths **relative to `/api`** and `main.py` mounts every one of
them with `prefix="/api"`. A router that *also* self-prefixes with `/api`
produces `/api/api/...` and every frontend call to it 404s — this actually
happened and cost a debugging pass.

```python
router = APIRouter(prefix="/auth")     # correct -> /api/auth/login
router = APIRouter(prefix="/api/auth") # WRONG   -> /api/api/auth/login
```

Router imports in `main.py` are eager and unguarded. A `try/except ImportError`
there would boot a healthy-looking app with half its API silently missing.

### Serialising secrets
`ShopOut` and `MeOut` must **never** include `imgbb_key_enc` or
`gemini_key_enc`, not even as ciphertext. Instead they expose booleans —
`ShopOut.has_imgbb_key`, `MeOut.has_gemini_key` — plus `gemini_key_hint`
(last 4 chars). Routers compute these from `bool(row.<field>_enc)`.

### API key handling
- `app/crypto.py`: `encrypt(plain: str) -> str`, `decrypt(token: str) -> str`,
  both Fernet with `settings.FERNET_KEY`.
- A decrypted key exists only inside a request. **Never** log it, never return
  it, never put it in an error message or a `JobEvent`.
- `gemini_key_hint` is `"…" + key[-4:]`.

### Storage (`app/storage.py`)
```python
class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None
    async def get(self, key: str) -> bytes
    async def delete(self, key: str) -> None

def get_storage() -> Storage      # picks supabase|local from settings
```
Key layout: `shops/{shop_id}/{kind}/{image_id}.jpg`,
exports at `shops/{shop_id}/exports/{export_id}.xlsx`.

---

## 4. Engine modules (`app/engine/`)

Ported from the existing tool. **Where this spec says "verbatim", copy the
logic exactly — do not improve, reformat, or re-tune constants.**

### `pacer.py` — adaptive rate control, now DB-backed
```python
RATE_START_DELAY  = 30.0
RATE_MIN_DELAY    = 8.0
RATE_MAX_DELAY    = 120.0
RATE_GROW         = 1.5
RATE_SHRINK       = 0.92
RATE_BACKOFF_BASE = 20.0
RATE_BACKOFF_MAX  = 300.0

def grow(delay: float) -> float      # min(delay * RATE_GROW, RATE_MAX_DELAY)
def shrink(delay: float) -> float    # max(delay * RATE_SHRINK, RATE_MIN_DELAY)
def backoff(attempt: int) -> float   # min(RATE_BACKOFF_BASE * 2**attempt, RATE_BACKOFF_MAX)

async def get_or_create(db, api_key_hash: str) -> PaceState
async def on_success(db, api_key_hash: str) -> float   # -> new delay seconds
async def on_rate_limit(db, api_key_hash: str) -> float  # -> seconds to wait
```
`on_rate_limit` grows the delay, increments `consecutive_429`, sets
`next_allowed_at = now + backoff(consecutive_429)` and returns that wait.
`on_success` shrinks the delay and resets `consecutive_429` to 0.

### `gemini.py`
```python
VISION_MODEL = "gemini-2.5-flash"
IMAGE_MODEL  = "gemini-3.1-flash-lite-image"
ASPECT_RATIO = "1:1"
IMAGE_SIZE   = "1K"          # flash-lite-image supports 1K only; 2K/4K -> HTTP 400
API_TIMEOUT  = 90

class RateLimited(Exception); class AuthFailure(Exception); class NoImage(Exception)

def key_hash(api_key: str) -> str        # sha256(key).hexdigest()[:32]
def build_client(api_key: str)           # genai.Client(vertexai=True, api_key=...)
                                         # express-mode. Keys start "AQ.".
def is_rate_limit(msg: str) -> bool      # verbatim markers from main.py
def is_auth_error(msg: str) -> bool      # verbatim markers from main.py
def finish_reason(resp) -> str           # verbatim
def extract_image_bytes(resp) -> bytes | None   # verbatim
```
Marker tuples come verbatim from `main.py` lines 334-354. `build_client` must
use `vertexai=True` **with** `api_key=` — that is express mode; a plain
`genai.Client(api_key=...)` hits the wrong endpoint and 404s.

### `extract.py`
`RESPONSE_SCHEMA` and `EXTRACT_PROMPT` are copied **verbatim** from
`extract_menu.py` (lines 115-176), as are `normalise_items`, `merge`,
`clean_text`, `norm_key`, `parse_price`.
```python
MAX_DIM = 1600; JPEG_QUALITY = 92; MAX_OUTPUT_TOKENS = 32768
def prepare_image(data: bytes) -> bytes          # downscale to MAX_DIM, JPEG q92
def read_menu(client, image_bytes: bytes) -> dict  # -> the parsed JSON reply
```

### `generate.py`
```python
OUTPUT_SIZE = 1024; JPEG_QUALITY = 100
def generate_one(client, prompt: str, ref_jpeg: bytes) -> bytes
    # ONE attempt only. Raises RateLimited / AuthFailure / NoImage.
    # Retry policy lives in the stepper, not here.
def to_jpeg(raw: bytes) -> tuple[bytes, int, int]   # -> (jpeg_bytes, w, h)
```

### `imgbb.py`
```python
API_URL = "https://api.imgbb.com/1/upload"
MAX_BYTES = 32 * 1024 * 1024; TIMEOUT = 60; PACE_SECONDS = 1.5
class ImgbbUploadCap(RuntimeError): ...
def is_upload_cap(body: str) -> bool     # verbatim: error code 111
async def upload(api_key: str, data: bytes, name: str) -> dict
    # -> {"url","display_url","delete_url"} ; raises ImgbbUploadCap
```
An `ImgbbUploadCap` aborts the whole host job immediately — it is an
account-level cap, and retrying achieves nothing.

### `export.py`
```python
TEMPLATE_PATH = "templates/smartbiz_template.xlsx"
SHEET = "bulk_upload_template"
COL_NAME=4; COL_MRP=5; COL_SELLING=6; COL_BUSINESS_CAT=7
COL_PRODUCT_CAT=8; COL_DESCRIPTION=9; COL_IMAGE1=16
MAX_NAME=200; MAX_DESC=2000; MAX_MRP=999999.99

EXPORT_FOOD_CATEGORIES = [           # the ONLY legal column-H values for food
  "Fruits & Vegetables", "Food grains, Oil & Masala", "Bakery", "Dairy",
  "Beverages", "Eggs, Meat & Seafood", "Namkeen, Snacks & Biscuits",
  "Health food", "Instant Food", "Chocolates, desserts and icecream",
  "Mithai (Indian Sweets)", "Baby food", "Gourmet Food", "Pet food",
  "Other Food and Grocery",
]

CATEGORY_KEYWORDS = [...]   # verbatim from smartbiz_export.py:66, the
                            # word-boundary matcher. Used ONLY as fallback.

def product_category_for(menu_category: str, ai_suggestion: str | None,
                         default: str) -> str
    # 1. ai_suggestion if it is in EXPORT_FOOD_CATEGORIES
    # 2. else the keyword map (word-boundary, so "Classics" != lassi)
    # 3. else default

@dataclass
class RowError: row: int; item_id: str; field: str; message: str

def validate(rows: list[dict]) -> list[RowError]
def build_workbook(rows: list[dict], business_category: str) -> bytes
    # MUST load a COPY of TEMPLATE_PATH with openpyxl and write into it.
    # Building a fresh workbook loses the 29 data validations and the
    # import fails. Leave columns A (SKU ID) and B (Variant ID) EMPTY.
```

---

## 5. AI contracts (owned by the orchestrator — do not implement)

`app/engine/prompt.py` and `app/engine/classify.py` are written by the
orchestrator. Other agents may **import** these signatures but must not create
or edit the files:

```python
# prompt.py
class StyleProfile(TypedDict):
    camera_angle: str; lighting: str; surface: str; background: str
    colour_palette: list[str]; mood: str
    vessel_in_reference: str; props_in_reference: list[str]

def derive_style_profile(client, ref_jpeg: bytes) -> StyleProfile
def build_prompt(style, shop, item, seed: int) -> str
def fallback_prompt(name: str, description: str, category: str, attempt: int) -> str
def vessel_for(item_name: str, category: str, suggested: str | None) -> str

# classify.py
CLASSIFY_BATCH_SIZE = 40
class Classification(TypedDict):
    name: str; confidence: int; reason: str; concept: str
    vessel: str; props: list[str]; product_category: str

def classify_batch(client, shop, items: list[dict]) -> list[Classification]
CONFIDENCE_AUTO_APPROVE = 90
```

---

## 6. API contract (`app/routers/`)

All routes are under `/api`. All require a session except `POST /api/auth/login`.
Responses are the Pydantic models in `app/schemas.py`.

### The step endpoint — the core of the generate loop
```
POST /api/jobs/{job_id}/step
```
Server algorithm (exactly this order):
1. Load job; if status is not `RUNNING`, return `409 job_not_running`.
2. Load the caller's decrypted Gemini key; if absent → `400 no_api_key`.
3. Read `PaceState` for `key_hash`. If `next_allowed_at > now`, return early
   with `{"status":"waiting","retry_after_ms":…, "remaining":…}` — do **not**
   claim an item.
4. Atomically claim ONE item:
   `UPDATE items SET status='generating' WHERE id = (SELECT id FROM items
    WHERE shop_id=… AND status='queued' ORDER BY position
    FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`
   If nothing is claimed → job done, return `{"status":"complete"}`.
5. Build the prompt, call `generate_one` **once**.
6. On success: store bytes, set item `GENERATED`, `job.done += 1`,
   `on_success()` → `next_delay_ms`.
7. On `RateLimited`: reset the item to `queued`, `on_rate_limit()`, return
   `{"status":"rate_limited","retry_after_ms":…}`. The item is **not** counted
   as failed.
8. On `NoImage`: increment `attempts`; if `attempts <= 3` reset to `queued`
   (the next attempt uses `fallback_prompt(attempts-1)`), else `FAILED`.
9. On `AuthFailure`: set job `FAILED` with the message and return `auth_failure`.

Response model:
```json
{ "status": "generated|item_failed|rate_limited|waiting|complete|failed",
  "item": { "id": "...", "name": "...", "status": "generated",
            "image_id": "...", "error": null },
  "next_delay_ms": 30000,
  "retry_after_ms": null,
  "remaining": 42, "done": 58, "failed": 0 }
```

**`item_failed` vs `failed` — these are not the same thing and must never be
conflated:**

| status | meaning | browser loop |
|---|---|---|
| `generated` | one image succeeded | wait `next_delay_ms`, continue |
| `item_failed` | **one item** exhausted its retries (step 8, NoImage) | wait `next_delay_ms`, **continue** — the run carries on without it |
| `rate_limited` | 429; the item went back to the queue | wait `retry_after_ms`, continue |
| `waiting` | pace gate not open yet; no item claimed | wait `retry_after_ms`, continue |
| `complete` | no items left to claim | **stop** |
| `failed` | **the whole job** died (only `AuthFailure`, step 9) | **stop** |

One bad dish must never halt a 100-item run. Only a job-level abort stops the
loop. `failed` is returned *exclusively* for `AuthFailure`.

### Remaining routes
```
POST   /api/auth/login          {username,password} -> {user}
POST   /api/auth/logout         -> 204
GET    /api/auth/me             -> {user, has_gemini_key, gemini_key_hint}
PUT    /api/auth/gemini-key     {key} -> validates with a 1-token live call,
                                  then stores encrypted. 400 auth_failure if bad.
DELETE /api/auth/gemini-key     -> 204

GET    /api/shops                          -> [ShopSummary]  (counts by status)
POST   /api/shops               {name, ...context} -> Shop
GET    /api/shops/{id}                     -> Shop
PATCH  /api/shops/{id}          partial context update -> Shop
POST   /api/shops/{id}/reference   multipart file -> {image_id, style_profile}
POST   /api/shops/{id}/menus       multipart files[] -> [MenuUpload]
                                   Re-uploading identical bytes is a SILENT
                                   DEDUPE that returns the EXISTING row with
                                   its original id - never an error. The UI
                                   detects a repeat by id and says "skipped".
GET    /api/shops/{id}/menus               -> [MenuUpload] already attached.
                                   Without this the Setup screen could only
                                   show photos from the current browser
                                   session, and a reload would hide them.
GET    /api/shops/{id}/menus/{mid}/file    -> the stored photo bytes, for
                                   thumbnails (menu_uploads are not `images`
                                   rows, so /api/images/{id} cannot serve them)
DELETE /api/shops/{id}/menus/{mid}         -> 204

`PATCH /api/shops/{id}` also accepts `archived_at` (an ISO timestamp to
archive, explicit `null` to unarchive). The router applies `exclude_unset`, so
omitting the field leaves the current value untouched.
PUT    /api/shops/{id}/imgbb-key   {key}   -> 204  (encrypted)

POST   /api/shops/{id}/jobs/{kind}  kind in extract|classify|generate|host|export
                                    -> Job     (409 if one is already RUNNING)
GET    /api/jobs/{id}                       -> Job + counters
GET    /api/jobs/{id}/events?after=<iso>    -> [JobEvent]   (polled every 2s)
POST   /api/jobs/{id}/cancel                -> Job
POST   /api/jobs/{id}/step                  -> see above

GET    /api/shops/{id}/items?status=&min_conf=&q=&page=  -> paginated [Item]
PATCH  /api/items/{id}      {name?,category?,price?,description?,
                             concept_text?,product_category?}      -> Item
POST   /api/items/{id}/approve | /hold | /skip | /regenerate       -> Item
POST   /api/items/{id}/reference   multipart file -> Item   (sets AWAITING_REF
                                                             -> APPROVED)
GET    /api/images/{id}                -> image bytes; ?download=1 -> attachment
GET    /api/shops/{id}/images.zip      -> streamed zip of all dish images
GET    /api/shops/{id}/export/validate -> [RowError]
GET    /api/exports/{id}               -> the .xlsx as an attachment
```

Job semantics for non-generate kinds: `extract`, `classify`, `host` and
`export` each run to completion **inside their POST request** (they are fast —
seconds, not an hour) and return a finished `Job`. Only `generate` uses the
step loop.

---

## 7. Frontend contract (`frontend/`)

```
src/
  main.tsx  App.tsx  router.tsx
  api/client.ts        typed fetch wrapper, throws ApiError{code,message}
  api/types.ts         mirrors app/schemas.py EXACTLY
  api/hooks.ts         TanStack Query hooks, one per endpoint
  lib/generateLoop.ts  the /step driver (see below)
  components/          Button Input Select Card Badge Modal Toast
                       ConfidenceBar ImageTile DropZone StatusPill EmptyState
  screens/  Login Shops Setup Review Generate Catalog
```

`lib/generateLoop.ts`:
```ts
export function useGenerateLoop(jobId: string): {
  running: boolean; done: number; failed: number; remaining: number;
  start(): void; pause(): void;
}
```
It calls `POST /api/jobs/{id}/step` in a loop, honouring `next_delay_ms` /
`retry_after_ms`, stops on `complete` or `failed`, survives re-mount, and
**must** guard against two concurrent loops in the same tab.

Rules: no component over ~200 lines; every async surface renders loading,
empty, and error states; every destructive action confirms; keyboard shortcuts
on Review (`a` approve, `h` hold, `s` skip, `j`/`k` move). Tailwind only, no
component library beyond what is listed. Dark UI, dense tables, no emoji.

---

## 8. File ownership (do not cross these lines)

| Owner | Files |
|---|---|
| agent-scaffold | `backend/app/{config,db,models,enums,errors,schemas}.py`, `backend/Dockerfile`, `backend/requirements.txt`, `backend/app/main.py` |
| agent-engine | `backend/app/engine/{pacer,gemini,extract,generate,imgbb,export}.py`, `backend/templates/` |
| agent-frontend-shell | `frontend/*` except `src/screens/*` |
| agent-auth | `backend/app/{auth,crypto,storage}.py`, `backend/app/routers/{auth,shops,items,images}.py` |
| agent-stepper | `backend/app/{stepper.py}`, `backend/app/routers/{jobs,export}.py` |
| agent-screens-a | `frontend/src/screens/{Login,Shops,Setup}.tsx` |
| agent-screens-b | `frontend/src/screens/{Review,Generate,Catalog}.tsx` |
| agent-tests | `backend/tests/*` |
| **orchestrator** | `app/engine/{prompt,classify}.py`, this file, `PLAN.md`, `DEPLOY.md` |

---

## 9. Definition of done for any agent

- Code imports cleanly: `python -c "import app.<module>"` (backend) or
  `npx tsc --noEmit` (frontend).
- No `TODO` left without a `# SPEC-GAP:` explaining what is missing.
- No secret is logged, returned, or persisted unencrypted.
- No file outside your ownership row is created or modified.
- Report back: files written, any SPEC-GAP, and anything you believe is wrong
  with this spec.
