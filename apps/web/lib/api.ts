/**
 * Browser/server client for the Messer platform API.
 * In the browser, requests go to same-origin /api/v1 (rewritten to the API service) with cookies.
 * On the server, requests go to MESSER_API_URL forwarding the user's cookies.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isPlanLimit(): boolean {
    return this.status === 402;
  }
}

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: Json | FormData;
  query?: Record<string, string | number | boolean | null | undefined>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Server-side only: forward these cookies. */
  cookie?: string;
}

function baseUrl(): string {
  if (typeof window !== "undefined") return "";
  return process.env.MESSER_API_URL ?? "http://localhost:8000";
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const p = path.startsWith("/api/") || path.startsWith("/v1/") ? path : `/api/v1${path.startsWith("/") ? "" : "/"}${path}`;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const suffix = qs.toString();
  return `${baseUrl()}${p}${suffix ? `?${suffix}` : ""}`;
}

let refreshing: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  refreshing ??= fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      window.setTimeout(() => (refreshing = null), 0);
    });
  return refreshing;
}

async function parseError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = res.statusText || "Error";
  let details: Record<string, unknown> = {};
  try {
    const data = (await res.json()) as { error?: { code?: string; message?: string; details?: Record<string, unknown> } };
    if (data.error) {
      code = data.error.code ?? code;
      message = data.error.message ?? message;
      details = data.error.details ?? {};
    }
  } catch {
    // non-JSON error body
  }
  return new ApiError(res.status, code, message, details);
}

export async function apiFetch(path: string, opts: RequestOptions = {}, retried = false): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (opts.cookie) headers.cookie = opts.cookie;
  const res = await fetch(apiUrl(path, opts.query), {
    method: opts.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    credentials: "include",
    signal: opts.signal,
    cache: "no-store",
  });
  if (res.status === 401 && !retried && !path.includes("/auth/")) {
    if (await tryRefresh()) return apiFetch(path, opts, true);
  }
  if (!res.ok) throw await parseError(res);
  return res;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await apiFetch(path, opts);
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  if (!type.includes("application/json")) return (await res.text()) as T;
  return (await res.json()) as T;
}

export const http = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) => api<T>(path, { query, signal }),
  post: <T>(path: string, body?: Json | FormData) => api<T>(path, { method: "POST", body: body ?? {} }),
  put: <T>(path: string, body?: Json) => api<T>(path, { method: "PUT", body: body ?? {} }),
  patch: <T>(path: string, body?: Json) => api<T>(path, { method: "PATCH", body: body ?? {} }),
  del: <T = void>(path: string) => api<T>(path, { method: "DELETE" }),
};
