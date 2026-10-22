/** SSE streams of the Studio (playground chat and streamed approval decisions). */

import { ApiError } from "@/lib/api";
import { streamSse } from "@/lib/sse";

import type { DecisionBody } from "./types";

/** A Studio stream event: `{"type": "...", ...}` in the `data:` line. */
export type StreamEvent = { type: string } & Record<string, unknown>;

async function refreshSession(): Promise<boolean> {
  try {
    const res = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" });
    return res.ok;
  } catch {
    return false;
  }
}

/** POST an SSE request; on an expired access token, refresh the session once and retry. */
export async function postStream(
  path: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const run = () =>
    streamSse<unknown>(path, {
      body,
      method: "POST",
      signal,
      onMessage: (message) => {
        const data = message.data;
        if (data && typeof data === "object" && !Array.isArray(data) && typeof (data as { type?: unknown }).type === "string") {
          onEvent(data as StreamEvent);
        }
      },
    });
  try {
    await run();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401 && (await refreshSession())) {
      await run();
      return;
    }
    throw err;
  }
}

export function chatStream(
  projectId: string,
  member: string,
  body: { message: string; conversation_id?: string | null; attachments?: string[] },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const payload: Record<string, unknown> = { message: body.message };
  if (body.conversation_id) payload.conversation_id = body.conversation_id;
  if (body.attachments && body.attachments.length > 0) payload.attachments = body.attachments;
  return postStream(`/projects/${projectId}/workforce/${encodeURIComponent(member)}/chat`, payload, onEvent, signal);
}

export function decisionStream(
  approvalId: string,
  body: DecisionBody,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return postStream(`/approvals/${approvalId}/decision?stream=true`, body, onEvent, signal);
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException ? err.name === "AbortError" : err instanceof Error && err.name === "AbortError";
}
