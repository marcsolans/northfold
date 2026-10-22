/**
 * Where an interface gets its data and runs its actions.
 *
 * - Studio preview: `/api/v1/interfaces/{id}/components/{cid}/…` (development environment, HEAD, drafts allowed)
 * - Public app:     `/api/public/v1/apps/{org}/{project}/{slug}/components/{cid}/…` (production)
 * - Public chat:    `/api/public/v1/chat/{org}/{project}/{agent}/…` (production; the only component is the chat)
 */

import { ApiError, api, apiUrl } from "@/lib/api";

import type { ActionResult, ChatEvent, ComponentDef, ConversationView, DataResult, UploadResult } from "./types";

export interface ActionBody {
  values?: Record<string, unknown>;
  row?: Record<string, unknown>;
  inputs?: Record<string, unknown>;
  row_action?: boolean;
}

export interface InterfaceSource {
  /** Query-key prefix (one cache per source). */
  key: string;
  /** Unsaved components can be previewed (Studio editor). */
  drafts: boolean;
  /** The viewer can upload files and see approvals (signed-in member). */
  member: boolean;
  data(componentId: string, inputs: Record<string, unknown>, draft?: ComponentDef | null): Promise<DataResult>;
  action(componentId: string, body: ActionBody, draft?: ComponentDef | null): Promise<ActionResult>;
  upload(componentId: string, file: File): Promise<UploadResult>;
  chat(componentId: string, message: string, onEvent: (event: ChatEvent) => void, signal?: AbortSignal): Promise<void>;
  conversation(componentId: string): Promise<ConversationView>;
  resetConversation(componentId: string): Promise<void>;
  decide(componentId: string, approvalId: string, decision: "approve" | "deny", comment: string | null): Promise<void>;
}

/** POST an SSE request and call `onEvent` for every `data:` JSON line (headers supported, unlike lib/sse). */
export async function postEvents(
  path: string,
  body: unknown,
  onEvent: (event: ChatEvent) => void,
  { signal, headers, onResponse }: { signal?: AbortSignal; headers?: Record<string, string>; onResponse?: (res: Response) => void } = {},
): Promise<void> {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
    credentials: "include",
    signal,
  });
  onResponse?.(res);
  if (!res.ok || !res.body) {
    let message = res.statusText;
    let code = "stream_error";
    let details: Record<string, unknown> = {};
    try {
      const data = (await res.json()) as { error?: { code?: string; message?: string; details?: Record<string, unknown> } };
      message = data.error?.message ?? message;
      code = data.error?.code ?? code;
      details = data.error?.details ?? {};
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, code, message, details);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index: number;
    while ((index = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data:")) continue;
        try {
          const event = JSON.parse(line.slice(5).trim()) as ChatEvent;
          if (event && typeof event === "object" && "type" in event) onEvent(event);
        } catch {
          // ignore malformed lines
        }
      }
    }
  }
}

function enc(value: string): string {
  return encodeURIComponent(value);
}

export function previewSource(interfaceId: string): InterfaceSource {
  const base = (cid: string) => `/interfaces/${interfaceId}/components/${enc(cid)}`;
  return {
    key: `preview:${interfaceId}`,
    drafts: true,
    member: true,
    data: (cid, inputs, draft) => api<DataResult>(`${base(cid)}/data`, { method: "POST", body: { inputs, draft: draft ?? null } }),
    action: (cid, body, draft) => api<ActionResult>(`${base(cid)}/action`, { method: "POST", body: { ...body, draft: draft ?? null } }),
    upload: (cid, file) => {
      const form = new FormData();
      form.append("file", file);
      return api<UploadResult>(`${base(cid)}/upload`, { method: "POST", body: form });
    },
    chat: (cid, message, onEvent, signal) => postEvents(`/api/v1${base(cid)}/chat`, { message }, onEvent, { signal }),
    conversation: (cid) => api<ConversationView>(`${base(cid)}/conversation`),
    resetConversation: (cid) => api<void>(`${base(cid)}/conversation`, { method: "DELETE" }),
    decide: async (cid, approvalId, decision, comment) => {
      await api(`${base(cid)}/approvals/${approvalId}/decision`, { method: "POST", body: { decision, comment } });
    },
  };
}

export function publicAppSource(org: string, project: string, slug: string, member: boolean): InterfaceSource {
  const base = (cid: string) => `/api/public/v1/apps/${enc(org)}/${enc(project)}/${enc(slug)}/components/${enc(cid)}`;
  return {
    key: `public:${org}/${project}/${slug}`,
    drafts: false,
    member,
    data: (cid, inputs) => api<DataResult>(`${base(cid)}/data`, { method: "POST", body: { inputs } }),
    action: (cid, body) => api<ActionResult>(`${base(cid)}/action`, { method: "POST", body: { ...body } }),
    upload: (cid, file) => {
      const form = new FormData();
      form.append("file", file);
      return api<UploadResult>(`${base(cid)}/upload`, { method: "POST", body: form });
    },
    chat: (cid, message, onEvent, signal) => postEvents(`${base(cid)}/chat`, { message }, onEvent, { signal }),
    conversation: (cid) => api<ConversationView>(`${base(cid)}/conversation`),
    resetConversation: (cid) => api<void>(`${base(cid)}/conversation`, { method: "DELETE" }),
    decide: async (cid, approvalId, decision, comment) => {
      await api(`${base(cid)}/approvals/${approvalId}/decision`, { method: "POST", body: { decision, comment } });
    },
  };
}

const TOKEN_KEY = (org: string, project: string) => `messer:eu:${org}/${project}`;

/** Signed end-user token kept by embedded widgets whose third-party cookies are blocked. */
export const endUserToken = {
  read(org: string, project: string): string | null {
    try {
      return window.localStorage.getItem(TOKEN_KEY(org, project));
    } catch {
      return null;
    }
  },
  write(org: string, project: string, token: string): void {
    try {
      window.localStorage.setItem(TOKEN_KEY(org, project), token);
    } catch {
      // storage unavailable (private mode): the cookie is the only identity
    }
  },
};

export function publicChatSource(org: string, project: string, agent: string, embed: boolean): InterfaceSource {
  const base = `/api/public/v1/chat/${enc(org)}/${enc(project)}/${enc(agent)}`;
  const headers = (): Record<string, string> => {
    if (!embed || typeof window === "undefined") return {};
    const token = endUserToken.read(org, project);
    return token ? { "X-Messer-End-User": token } : {};
  };
  const remember = (res: Response) => {
    const token = res.headers.get("X-Messer-End-User");
    if (embed && token) endUserToken.write(org, project, token);
  };
  const unsupported = () => Promise.reject(new ApiError(400, "unsupported", "Unsupported"));
  return {
    key: `chat:${org}/${project}/${agent}`,
    drafts: false,
    member: false,
    data: unsupported,
    action: unsupported,
    upload: unsupported,
    chat: (_cid, message, onEvent, signal) =>
      postEvents(`${base}/messages`, { message }, onEvent, { signal, headers: headers(), onResponse: remember }),
    conversation: () => api<ConversationView>(`${base}/conversation`, { headers: headers() }),
    resetConversation: () => api<void>(`${base}/conversation`, { method: "DELETE", headers: headers() }),
    decide: unsupported,
  };
}
