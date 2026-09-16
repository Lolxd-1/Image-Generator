/// api/client.ts — typed fetch wrapper: always sends cookies, parses the
/// SPEC.md §3 error envelope into ApiError, and transparently handles 204 /
/// binary responses alongside JSON.
import type { ErrorCode } from "./types";

export class ApiError extends Error {
  readonly code: ErrorCode | "unknown";
  readonly detail: Record<string, unknown> | null;
  readonly status: number;

  constructor(
    code: ErrorCode | "unknown",
    message: string,
    status: number,
    detail: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE = "/api";

type JsonBody = object;
type QueryParams = Record<string, string | number | boolean | undefined | null>;

function buildQuery(params?: QueryParams): string {
  if (!params) return "";
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    sp.set(key, String(value));
  }
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

async function parseErrorBody(res: Response): Promise<ApiError> {
  let code: ErrorCode | "unknown" = "unknown";
  let message = res.statusText || `Request failed (${res.status})`;
  let detail: Record<string, unknown> | null = null;
  try {
    const body = (await res.json()) as unknown;
    if (
      body &&
      typeof body === "object" &&
      "error" in body &&
      body.error &&
      typeof body.error === "object"
    ) {
      const err = body.error as {
        code?: ErrorCode;
        message?: string;
        detail?: Record<string, unknown> | null;
      };
      if (err.code) code = err.code;
      if (err.message) message = err.message;
      detail = err.detail ?? null;
    }
  } catch {
    // body wasn't JSON (or was empty) — fall back to defaults above.
  }
  return new ApiError(code, message, res.status, detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(isForm ? {} : { "Content-Type": "application/json" }),
      ...init.headers,
    },
  });

  if (!res.ok) {
    throw await parseErrorBody(res);
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }

  // Binary payloads: image bytes, .zip streams, .xlsx attachments.
  return (await res.blob()) as unknown as T;
}

export function get<T>(path: string, params?: QueryParams): Promise<T> {
  return request<T>(`${path}${buildQuery(params)}`, { method: "GET" });
}

export function post<T>(path: string, body?: JsonBody): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function patch<T>(path: string, body?: JsonBody): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function put<T>(path: string, body?: JsonBody): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export function postForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, { method: "POST", body: form });
}

/** Fetches a binary/blob response explicitly (images, zip, xlsx). */
export function getBlob(path: string, params?: QueryParams): Promise<Blob> {
  return request<Blob>(`${path}${buildQuery(params)}`, { method: "GET" });
}
