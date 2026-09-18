/// api/types.ts — TypeScript types mirroring app/schemas.py per SPEC.md §1 and §6.
//
// # SPEC-GAP: SPEC.md never shows app/schemas.py itself, only the model
// definitions (§2) and the API contract (§6). Response shapes below are the
// simplest types consistent with those two sections. Anywhere the exact
// field set was a guess is flagged with an inline "# SPEC-GAP" comment.

// ---------------------------------------------------------------------------
// Enums (SPEC.md §1) as string literal unions
// ---------------------------------------------------------------------------

export type ItemStatus =
  | "new"
  | "needs_review"
  | "awaiting_ref"
  | "approved"
  | "queued"
  | "generating"
  | "generated"
  | "hosted"
  | "failed"
  | "skipped";

export type JobKind = "extract" | "classify" | "generate" | "host" | "export";

export type JobStatus =
  | "pending"
  | "running"
  | "paused"
  | "done"
  | "failed"
  | "cancelled";

export type ImageKind = "reference" | "item_ref" | "menu" | "dish";

/** Terminal item statuses per SPEC.md §1. */
export const TERMINAL_ITEM_STATUSES: readonly ItemStatus[] = [
  "generated",
  "hosted",
  "failed",
  "skipped",
];

// ---------------------------------------------------------------------------
// Error envelope (SPEC.md §3)
// ---------------------------------------------------------------------------

export type ErrorCode =
  | "unauthorized"
  | "not_found"
  | "validation_failed"
  | "no_api_key"
  | "auth_failure"
  | "rate_limited"
  | "imgbb_cap"
  | "conflict"
  | "job_not_running";

export interface ErrorEnvelope {
  error: {
    code: ErrorCode;
    message: string;
    detail: Record<string, unknown> | null;
  };
}

// ---------------------------------------------------------------------------
// Core entities (SPEC.md §2)
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  username: string;
  created_at: string;
  last_login_at: string | null;
}

/** app/engine/prompt.py StyleProfile TypedDict (SPEC.md §5), imported by shape only. */
export interface StyleProfile {
  camera_angle: string;
  lighting: string;
  surface: string;
  background: string;
  colour_palette: string[];
  mood: string;
  vessel_in_reference: string;
  props_in_reference: string[];
}

export interface Shop {
  id: string;
  name: string;
  created_by: string;
  created_at: string;
  archived_at: string | null;
  brand_archetype: string | null;
  cuisine: string | null;
  price_tier: string | null;
  plating_style: string | null;
  lighting_mood: string | null;
  background_setting: string | null;
  prop_density: number;
  notes: string | null;
  style_profile: StyleProfile | null;
  reference_image_id: string | null;
  business_category: string;
  default_product_category: string;
  /** derived flag; the encrypted imgbb key itself is never returned. */
  has_imgbb_key: boolean; // SPEC-GAP: field name inferred, not shown verbatim in §6.
}

/** GET /api/shops item — Shop plus item-status counters. */
export interface ShopSummary {
  id: string;
  name: string;
  created_at: string;
  archived_at: string | null;
  item_counts: Partial<Record<ItemStatus, number>>; // SPEC-GAP: exact counter shape not specified.
  total_items: number;
}

export interface MenuUpload {
  id: string;
  shop_id: string;
  filename: string;
  sha256: string;
  is_menu: boolean | null;
  error: string | null;
  extracted_at: string | null;
  raw_json: Record<string, unknown> | null;
}

export interface Item {
  id: string;
  shop_id: string;
  position: number;
  name: string;
  category: string;
  price: number | null;
  description: string;
  source_menu: string;
  confidence: number | null;
  confidence_reason: string | null;
  concept_text: string | null;
  suggested_vessel: string | null;
  suggested_props: string[] | null;
  product_category: string | null;
  status: ItemStatus;
  manual_ref_image_id: string | null;
  prompt_used: string | null;
  attempts: number;
  last_error: string | null;
  image_id: string | null;
  imgbb_url: string | null;
  price_conflict: boolean;
  updated_at: string;
}

export interface ImageMeta {
  id: string;
  shop_id: string;
  item_id: string | null;
  kind: ImageKind;
  storage_key: string;
  sha256: string;
  bytes_len: number;
  width: number | null;
  height: number | null;
  created_at: string;
}

export interface Job {
  id: string;
  shop_id: string;
  kind: JobKind;
  status: JobStatus;
  total: number;
  done: number;
  failed: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_by: string;
}

export interface JobEvent {
  id: string;
  job_id: string;
  ts: string;
  level: "info" | "warn" | "error";
  item_id: string | null;
  message: string;
}

export interface ExportRecord {
  id: string;
  shop_id: string;
  filename: string;
  row_count: number;
  included_without_image: number;
  created_at: string;
  created_by: string;
}

export interface RowError {
  row: number;
  item_id: string;
  field: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Pagination (SPEC.md §6: "paginated [Item]" — exact envelope unspecified)
// ---------------------------------------------------------------------------

// SPEC-GAP: SPEC.md says GET /api/shops/{id}/items returns "paginated [Item]"
// but never shows the envelope. Assuming the simplest common shape.
export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ---------------------------------------------------------------------------
// Endpoint-specific request/response shapes
// ---------------------------------------------------------------------------

export interface LoginPayload {
  username: string;
  password: string;
}

export interface LoginResponse {
  user: User;
}

export interface MeResponse {
  user: User;
  has_gemini_key: boolean;
  gemini_key_hint: string | null;
  key_count: number;
  enabled_key_count: number;
}

// SPEC-GAP: PUT /api/auth/gemini-key's success response isn't shown in §6
// (only the 400 auth_failure case is). Assuming it echoes the same key-status
// shape as GET /api/auth/me so the UI can update without a refetch.
export interface GeminiKeyResponse {
  has_gemini_key: boolean;
  gemini_key_hint: string | null;
}

/** POST /api/shops body — name plus the 7 context metrics, all optional except name. */
export interface CreateShopPayload {
  name: string;
  brand_archetype?: string | null;
  cuisine?: string | null;
  price_tier?: string | null;
  plating_style?: string | null;
  lighting_mood?: string | null;
  background_setting?: string | null;
  prop_density?: number;
  notes?: string | null;
  business_category?: string;
  default_product_category?: string;
}

/** PATCH /api/shops/{id} body — partial context update. */
export type UpdateShopPayload = Partial<Omit<CreateShopPayload, "name">> & {
  name?: string;
  /** ISO timestamp to archive, explicit null to unarchive. Omit to leave as-is. */
  archived_at?: string | null;
};

export interface ReferenceUploadResponse {
  image_id: string;
  style_profile: StyleProfile;
}

export interface SetKeyPayload {
  key: string;
}

// ---------------------------------------------------------------------------
// Key pool (backend/app/schemas.py ApiKeyOut/ApiKeyIn/ApiKeyPatch)
// ---------------------------------------------------------------------------

export interface ApiKey {
  id: string;
  label: string;
  key_hint: string;
  enabled: boolean;
  disabled_reason: string | null;
  created_at: string;
  last_used_at: string | null;
  delay_s: number;
  next_allowed_at: string | null;
  busy: boolean;
}

export interface AddKeyPayload {
  key: string;
  label?: string;
}

export interface UpdateKeyPayload {
  label?: string;
  enabled?: boolean;
}

// ---------------------------------------------------------------------------
// Storage (backend/app/schemas.py ShopStorageOut/StorageUsageOut/PurgeResultOut)
// ---------------------------------------------------------------------------

export interface ShopStorage {
  shop_id: string;
  shop_name: string;
  dish_bytes: number;
  dish_count: number;
  menu_bytes: number;
  menu_count: number;
  reference_bytes: number;
  export_bytes: number;
  export_count: number;
  total_bytes: number;
}

export interface StorageUsage {
  total_bytes: number;
  budget_bytes: number;
  shops: ShopStorage[];
}

export interface PurgeResult {
  deleted_images: number;
  bytes_freed: number;
}

export interface UpdateItemPayload {
  name?: string;
  category?: string;
  price?: number | null;
  description?: string;
  concept_text?: string | null;
  product_category?: string | null;
}

export interface ItemsQuery {
  status?: ItemStatus;
  min_conf?: number;
  q?: string;
  page?: number;
}

// ---------------------------------------------------------------------------
// The /step endpoint (SPEC.md §6 "The step endpoint")
// ---------------------------------------------------------------------------

export type StepStatus =
  | "generated"     // one image succeeded              -> loop continues
  | "item_failed"   // ONE item exhausted its retries   -> loop CONTINUES
  | "rate_limited"  // 429, item requeued               -> loop continues
  | "waiting"       // pace gate closed, nothing claimed -> loop continues
  | "complete"      // nothing left to claim            -> loop STOPS
  | "failed";       // the whole JOB died (auth only)   -> loop STOPS

export interface StepResultItem {
  id: string;
  name: string;
  status: ItemStatus;
  image_id: string | null;
  error: string | null;
}

export interface StepResult {
  status: StepStatus;
  /** null when no item was claimed this step (waiting/complete). */
  item: StepResultItem | null;
  next_delay_ms: number | null;
  retry_after_ms: number | null;
  remaining: number;
  done: number;
  failed: number;
  /** The server's authoritative wait before THIS lane's next step, in ms. */
  next_step_ms: number;
  /** Hint of the key this lane just used, null if none was leased. */
  key_hint: string | null;
  /** How many lanes the server wants the client running right now. */
  lanes: number;
}
