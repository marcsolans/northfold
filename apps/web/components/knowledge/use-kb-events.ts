"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { ApiError } from "@/lib/api";
import { streamSse } from "@/lib/sse";

import { kbKeys } from "./queries";
import type { FileList, KbEvent } from "./types";

export interface LiveFileState {
  status: string;
  progress: number;
  error?: string;
}

const TERMINAL = new Set(["ready", "error"]);

/**
 * Live knowledge base events over SSE (`GET /knowledge-bases/{id}/events`), reconnecting with backoff.
 * File status updates patch the cached file lists; terminal states refresh the affected queries.
 */
export function useKbEvents(kbId: string) {
  const qc = useQueryClient();
  const [files, setFiles] = React.useState<Record<string, LiveFileState>>({});
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    const controller = new AbortController();
    let attempt = 0;

    const handle = (event: KbEvent) => {
      switch (event.type) {
        case "file": {
          const fileId = event.file_id;
          const status = event.status;
          if (!fileId || !status) return;
          setFiles((prev) => ({
            ...prev,
            [fileId]: {
              status,
              progress: typeof event.progress === "number" ? event.progress : (prev[fileId]?.progress ?? 0),
              error: event.error,
            },
          }));
          let known = false;
          qc.setQueriesData<FileList>({ queryKey: kbKeys.files(kbId) }, (data) => {
            if (!data) return data;
            return {
              ...data,
              items: data.items.map((f) => {
                if (f.id !== fileId) return f;
                known = true;
                return {
                  ...f,
                  status: status as typeof f.status,
                  error: event.error ?? (status === "error" ? f.error : null),
                  chunk_count: typeof event.chunk_count === "number" ? event.chunk_count : f.chunk_count,
                };
              }),
            };
          });
          if (!known || TERMINAL.has(status)) {
            void qc.invalidateQueries({ queryKey: kbKeys.files(kbId) });
          }
          if (TERMINAL.has(status)) {
            void qc.invalidateQueries({ queryKey: kbKeys.detail(kbId), exact: true });
            void qc.invalidateQueries({ queryKey: kbKeys.tables(kbId) });
            void qc.invalidateQueries({ queryKey: kbKeys.schema(kbId) });
            void qc.invalidateQueries({ queryKey: kbKeys.chunks(kbId) });
          }
          return;
        }
        case "file_deleted":
          void qc.invalidateQueries({ queryKey: kbKeys.files(kbId) });
          void qc.invalidateQueries({ queryKey: kbKeys.detail(kbId), exact: true });
          return;
        case "table_deleted":
          void qc.invalidateQueries({ queryKey: kbKeys.tables(kbId) });
          void qc.invalidateQueries({ queryKey: kbKeys.schema(kbId) });
          return;
        case "chunk":
          void qc.invalidateQueries({ queryKey: kbKeys.chunks(kbId) });
          return;
        case "entities":
          void qc.invalidateQueries({ queryKey: kbKeys.entities(kbId) });
          return;
        case "backup":
          void qc.invalidateQueries({ queryKey: kbKeys.backups(kbId) });
          if (event.status === "restored") void qc.invalidateQueries({ queryKey: kbKeys.detail(kbId) });
          return;
        default:
          return;
      }
    };

    const loop = async () => {
      while (!controller.signal.aborted) {
        try {
          setConnected(true);
          await streamSse<KbEvent>(`/knowledge-bases/${kbId}/events`, {
            method: "GET",
            signal: controller.signal,
            onMessage: (message) => {
              attempt = 0;
              if (message.data && typeof message.data === "object") handle(message.data);
            },
          });
        } catch (err) {
          if (controller.signal.aborted) return;
          if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
            setConnected(false);
            return;
          }
        }
        setConnected(false);
        attempt += 1;
        const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5));
        await new Promise((resolve) => window.setTimeout(resolve, delay));
      }
    };
    void loop();
    return () => controller.abort();
  }, [kbId, qc]);

  return { files, connected };
}
