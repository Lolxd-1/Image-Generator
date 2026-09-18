/// api/hooks.ts — TanStack Query v5 hooks, one per endpoint in SPEC.md §6
/// (except POST /api/jobs/{id}/step, which is driven by lib/generateLoop.ts,
/// not a query/mutation hook).
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { del, get, patch, post, postForm, put } from "./client";
import type {
  AddKeyPayload,
  ApiKey,
  CreateShopPayload,
  ExportRecord,
  GeminiKeyResponse,
  Item,
  ItemsQuery,
  Job,
  JobEvent,
  JobKind,
  LoginPayload,
  LoginResponse,
  MeResponse,
  MenuUpload,
  Paginated,
  PurgeResult,
  ReferenceUploadResponse,
  RowError,
  SetKeyPayload,
  Shop,
  ShopStorage,
  ShopSummary,
  StorageUsage,
  UpdateItemPayload,
  UpdateKeyPayload,
  UpdateShopPayload,
} from "./types";

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const qk = {
  me: ["auth", "me"] as const,
  keys: ["auth", "keys"] as const,
  shops: ["shops"] as const,
  shop: (id: string) => ["shops", id] as const,
  items: (shopId: string, query: ItemsQuery) =>
    ["shops", shopId, "items", query] as const,
  job: (id: string) => ["jobs", id] as const,
  jobEvents: (id: string, after?: string) =>
    ["jobs", id, "events", after ?? null] as const,
  exportValidate: (shopId: string) =>
    ["shops", shopId, "export", "validate"] as const,
  shopExports: (shopId: string) => ["shops", shopId, "exports"] as const,
  activeJob: (shopId: string) => ["shops", shopId, "jobs", "active"] as const,
  storage: ["storage"] as const,
  shopStorage: (id: string) => ["shops", id, "storage"] as const,
};

// ---------------------------------------------------------------------------
// Binary/redirect endpoints — plain URL builders, used directly as
// <img src>/<a href> rather than fetched through TanStack Query.
// ---------------------------------------------------------------------------

export function imageUrl(imageId: string, download = false): string {
  return `/api/images/${imageId}${download ? "?download=1" : ""}`;
}

/**
 * A stored menu photograph. menu_uploads are not `images` rows, so they cannot
 * be served through imageUrl(); they have their own route.
 */
export function menuFileUrl(shopId: string, menuId: string): string {
  return `/api/shops/${shopId}/menus/${menuId}/file`;
}

export function shopImagesZipUrl(shopId: string): string {
  return `/api/shops/${shopId}/images.zip`;
}

export function exportFileUrl(exportId: string): string {
  return `/api/exports/${exportId}`;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export function useMe(options?: Partial<UseQueryOptions<MeResponse>>) {
  return useQuery({
    queryKey: qk.me,
    queryFn: () => get<MeResponse>("/auth/me"),
    retry: false,
    ...options,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: LoginPayload) =>
      post<LoginResponse>("/auth/login", payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<void>("/auth/logout"),
    onSuccess: () => {
      qc.removeQueries();
    },
  });
}

export function useSetGeminiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SetKeyPayload) =>
      put<GeminiKeyResponse>("/auth/gemini-key", payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

export function useDeleteGeminiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => del<void>("/auth/gemini-key"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

// ---------------------------------------------------------------------------
// Key pool
// ---------------------------------------------------------------------------

export function useApiKeys() {
  return useQuery({
    queryKey: qk.keys,
    queryFn: () => get<ApiKey[]>("/auth/keys"),
  });
}

function useInvalidateKeys() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: qk.keys });
    void qc.invalidateQueries({ queryKey: qk.me });
  };
}

export function useAddApiKey() {
  const invalidate = useInvalidateKeys();
  return useMutation({
    mutationFn: (payload: AddKeyPayload) => post<ApiKey>("/auth/keys", payload),
    onSuccess: invalidate,
  });
}

export function useUpdateApiKey() {
  const invalidate = useInvalidateKeys();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateKeyPayload }) =>
      patch<ApiKey>(`/auth/keys/${id}`, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteApiKey() {
  const invalidate = useInvalidateKeys();
  return useMutation({
    mutationFn: (id: string) => del<void>(`/auth/keys/${id}`),
    onSuccess: invalidate,
  });
}

export function useTestApiKey() {
  const invalidate = useInvalidateKeys();
  return useMutation({
    mutationFn: (id: string) => post<ApiKey>(`/auth/keys/${id}/test`),
    onSuccess: invalidate,
  });
}

// ---------------------------------------------------------------------------
// Shops
// ---------------------------------------------------------------------------

export function useShops() {
  return useQuery({
    queryKey: qk.shops,
    queryFn: () => get<ShopSummary[]>("/shops"),
  });
}

export function useCreateShop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateShopPayload) => post<Shop>("/shops", payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shops });
    },
  });
}

export function useShop(id: string | undefined) {
  return useQuery({
    queryKey: qk.shop(id ?? ""),
    queryFn: () => get<Shop>(`/shops/${id}`),
    enabled: Boolean(id),
  });
}

export function useUpdateShop(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateShopPayload) =>
      patch<Shop>(`/shops/${id}`, payload),
    onSuccess: (shop) => {
      qc.setQueryData(qk.shop(id), shop);
      void qc.invalidateQueries({ queryKey: qk.shops });
    },
  });
}

export function useUploadReference(shopId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return postForm<ReferenceUploadResponse>(
        `/shops/${shopId}/reference`,
        form,
      );
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
    },
  });
}

export function useUploadMenus(shopId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => {
      const form = new FormData();
      for (const file of files) form.append("files", file);
      return postForm<MenuUpload[]>(`/shops/${shopId}/menus`, form);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
      void qc.invalidateQueries({ queryKey: qk.shops });
      void qc.invalidateQueries({ queryKey: ["shops", shopId, "menus"] });
    },
  });
}

export function useShopMenus(shopId: string | undefined) {
  return useQuery({
    queryKey: ["shops", shopId ?? "", "menus"],
    queryFn: () => get<MenuUpload[]>(`/shops/${shopId}/menus`),
    enabled: Boolean(shopId),
  });
}

export function useDeleteMenu(shopId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (menuId: string) =>
      del<void>(`/shops/${shopId}/menus/${menuId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
    },
  });
}

export function useSetImgbbKey(shopId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SetKeyPayload) =>
      put<void>(`/shops/${shopId}/imgbb-key`, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
    },
  });
}

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export function useCreateJob(shopId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kind: JobKind) => post<Job>(`/shops/${shopId}/jobs/${kind}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
      void qc.invalidateQueries({ queryKey: qk.shops });
    },
  });
}

export function useJob(
  jobId: string | undefined,
  options?: Partial<UseQueryOptions<Job>>,
) {
  return useQuery({
    queryKey: qk.job(jobId ?? ""),
    queryFn: () => get<Job>(`/jobs/${jobId}`),
    enabled: Boolean(jobId),
    ...options,
  });
}

/** Polled every 2s per SPEC.md §6. Pass the ISO timestamp of the last event seen. */
export function useJobEvents(jobId: string | undefined, after?: string) {
  return useQuery({
    queryKey: qk.jobEvents(jobId ?? "", after),
    queryFn: () => get<JobEvent[]>(`/jobs/${jobId}/events`, { after }),
    enabled: Boolean(jobId),
    refetchInterval: 2000,
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => post<Job>(`/jobs/${jobId}/cancel`),
    onSuccess: (job) => {
      qc.setQueryData(qk.job(job.id), job);
    },
  });
}

/** The shop's currently RUNNING job, if any — lets a run resume without relying on localStorage. */
export function useActiveJob(shopId: string | undefined) {
  return useQuery({
    queryKey: qk.activeJob(shopId ?? ""),
    queryFn: () => get<Job | null>(`/shops/${shopId}/jobs/active`),
    enabled: Boolean(shopId),
  });
}

// ---------------------------------------------------------------------------
// Items
// ---------------------------------------------------------------------------

export function useItems(shopId: string | undefined, query: ItemsQuery = {}) {
  return useQuery({
    queryKey: qk.items(shopId ?? "", query),
    queryFn: () =>
      get<Paginated<Item>>(`/shops/${shopId}/items`, {
        status: query.status,
        min_conf: query.min_conf,
        q: query.q,
        page: query.page,
      }),
    enabled: Boolean(shopId),
  });
}

function useInvalidateItems(shopId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["shops", shopId, "items"] });
    void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
  };
}

export function useUpdateItem(shopId: string) {
  const invalidate = useInvalidateItems(shopId);
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateItemPayload }) =>
      patch<Item>(`/items/${id}`, payload),
    onSuccess: invalidate,
  });
}

export function useApproveItem(shopId: string) {
  const invalidate = useInvalidateItems(shopId);
  return useMutation({
    mutationFn: (id: string) => post<Item>(`/items/${id}/approve`),
    onSuccess: invalidate,
  });
}

export function useHoldItem(shopId: string) {
  const invalidate = useInvalidateItems(shopId);
  return useMutation({
    mutationFn: (id: string) => post<Item>(`/items/${id}/hold`),
    onSuccess: invalidate,
  });
}

export function useSkipItem(shopId: string) {
  const invalidate = useInvalidateItems(shopId);
  return useMutation({
    mutationFn: (id: string) => post<Item>(`/items/${id}/skip`),
    onSuccess: invalidate,
  });
}

export function useRegenerateItem(shopId: string) {
  const invalidate = useInvalidateItems(shopId);
  return useMutation({
    mutationFn: (id: string) => post<Item>(`/items/${id}/regenerate`),
    onSuccess: invalidate,
  });
}

export function useUploadItemReference(shopId: string) {
  const invalidate = useInvalidateItems(shopId);
  return useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return postForm<Item>(`/items/${id}/reference`, form);
    },
    onSuccess: invalidate,
  });
}

// ---------------------------------------------------------------------------
// Storage
// ---------------------------------------------------------------------------

export function useStorageUsage() {
  return useQuery({
    queryKey: qk.storage,
    queryFn: () => get<StorageUsage>("/storage"),
  });
}

export function useShopStorage(shopId: string | undefined) {
  return useQuery({
    queryKey: qk.shopStorage(shopId ?? ""),
    queryFn: () => get<ShopStorage>(`/shops/${shopId}/storage`),
    enabled: Boolean(shopId),
  });
}

export function usePurgeShopImages() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shopId: string) => post<PurgeResult>(`/shops/${shopId}/purge-images`),
    onSuccess: (_result, shopId) => {
      void qc.invalidateQueries({ queryKey: qk.storage });
      void qc.invalidateQueries({ queryKey: qk.shopStorage(shopId) });
      void qc.invalidateQueries({ queryKey: ["shops", shopId, "items"] });
      void qc.invalidateQueries({ queryKey: qk.shop(shopId) });
    },
  });
}

export function useDeleteShop() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shopId: string) => del<void>(`/shops/${shopId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.shops });
      void qc.invalidateQueries({ queryKey: qk.storage });
    },
  });
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export function useExportValidate(shopId: string | undefined) {
  return useQuery({
    queryKey: qk.exportValidate(shopId ?? ""),
    queryFn: () => get<RowError[]>(`/shops/${shopId}/export/validate`),
    enabled: Boolean(shopId),
  });
}

/** Finished exports for this shop, newest first. */
export function useShopExports(shopId: string | undefined) {
  return useQuery({
    queryKey: qk.shopExports(shopId ?? ""),
    queryFn: () => get<ExportRecord[]>(`/shops/${shopId}/exports`),
    enabled: Boolean(shopId),
  });
}

// Re-exported so screens can reference the Export entity shape without a
// second import from api/types.
export type { ExportRecord };
