/** Server-Sent Events over fetch (supports POST bodies and cookies, unlike EventSource). */

import { ApiError, apiUrl } from "./api";

export interface SseMessage<T = unknown> {
  event: string;
  data: T;
  id?: string;
}

export async function streamSse<T = unknown>(
  path: string,
  {
    body,
    method,
    signal,
    onMessage,
  }: {
    body?: unknown;
    method?: "GET" | "POST";
    signal?: AbortSignal;
    onMessage: (message: SseMessage<T>) => void;
  },
): Promise<void> {
  const res = await fetch(apiUrl(path), {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers: { Accept: "text/event-stream", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    signal,
  });
  if (!res.ok || !res.body) {
    let message = res.statusText;
    let code = "stream_error";
    try {
      const data = (await res.json()) as { error?: { code?: string; message?: string } };
      message = data.error?.message ?? message;
      code = data.error?.code ?? code;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, code, message);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index: number;
    while ((index = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index).replace(/^\r?\n\r?\n/, "");
      let event = "message";
      let id: string | undefined;
      const dataLines: string[] = [];
      for (const line of raw.split(/\r?\n/)) {
        if (line.startsWith(":")) continue;
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("id:")) id = line.slice(3).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      if (dataLines.length === 0) continue;
      const text = dataLines.join("\n");
      let data: unknown = text;
      try {
        data = JSON.parse(text);
      } catch {
        // plain text payload
      }
      onMessage({ event, data: data as T, id });
    }
  }
}
