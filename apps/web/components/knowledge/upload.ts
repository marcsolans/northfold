"use client";

import { ApiError, apiUrl } from "@/lib/api";

import type { UploadResult } from "./types";

function send(url: string, file: File, onProgress: (fraction: number) => void): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText });
    xhr.onerror = () => reject(new ApiError(0, "network_error", "network"));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "aborted"));
    const form = new FormData();
    form.append("files", file, file.name);
    xhr.send(form);
  });
}

function toError(status: number, body: string): ApiError {
  try {
    const data = JSON.parse(body) as { error?: { code?: string; message?: string; details?: Record<string, unknown> } };
    return new ApiError(status, data.error?.code ?? "http_error", data.error?.message ?? String(status), data.error?.details ?? {});
  } catch {
    return new ApiError(status, "http_error", String(status));
  }
}

/** Upload one file with progress (XMLHttpRequest: fetch has no upload progress). Refreshes the session once on 401. */
export async function uploadKnowledgeFile<T = UploadResult>(
  path: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<T> {
  const url = apiUrl(path);
  let res = await send(url, file, onProgress);
  if (res.status === 401) {
    const refreshed = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
      .then((r) => r.ok)
      .catch(() => false);
    if (refreshed) res = await send(url, file, onProgress);
  }
  if (res.status < 200 || res.status >= 300) throw toError(res.status, res.body);
  return JSON.parse(res.body) as T;
}
