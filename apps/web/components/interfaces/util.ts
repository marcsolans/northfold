import { ApiError } from "@/lib/api";

export function messageOf(err: unknown, fallback: string): string {
  if (err instanceof ApiError || err instanceof Error) return err.message || fallback;
  return fallback;
}

export function isApiError(err: unknown, status?: number, code?: string): err is ApiError {
  return err instanceof ApiError && (status === undefined || err.status === status) && (code === undefined || err.code === code);
}
