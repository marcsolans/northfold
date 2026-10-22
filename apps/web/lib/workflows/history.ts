"use client";

/** Undo/redo history for the canvas document. Drags are grouped into a single step. */

import * as React from "react";

const LIMIT = 100;

interface HistoryState<T> {
  past: T[];
  present: T | null;
  future: T[];
}

export interface History<T> {
  present: T | null;
  canUndo: boolean;
  canRedo: boolean;
  /** Apply a change as a new undo step (or, with `record: false`, update the current step in place). */
  set: (update: T | ((prev: T) => T), options?: { record?: boolean }) => void;
  /** Start a grouped change (a drag): the next `end()` records one undo step if anything changed. */
  begin: () => void;
  end: () => void;
  undo: () => void;
  redo: () => void;
  reset: (value: T) => void;
}

export function useHistory<T>(): History<T> {
  const [state, setState] = React.useState<HistoryState<T>>({ past: [], present: null, future: [] });
  const pending = React.useRef<T | null>(null);
  const presentRef = React.useRef<T | null>(null);
  React.useEffect(() => {
    presentRef.current = state.present;
  }, [state.present]);

  const set = React.useCallback((update: T | ((prev: T) => T), options?: { record?: boolean }) => {
    setState((s) => {
      if (s.present === null) return s;
      const next = typeof update === "function" ? (update as (prev: T) => T)(s.present) : update;
      if (next === s.present) return s;
      if (options?.record === false) return { ...s, present: next };
      return { past: [...s.past, s.present].slice(-LIMIT), present: next, future: [] };
    });
  }, []);

  const begin = React.useCallback(() => {
    pending.current = presentRef.current;
  }, []);

  const end = React.useCallback(() => {
    const before = pending.current;
    pending.current = null;
    if (before === null) return;
    setState((s) => (before === s.present ? s : { past: [...s.past, before].slice(-LIMIT), present: s.present, future: [] }));
  }, []);

  const undo = React.useCallback(() => {
    setState((s) => {
      const previous = s.past[s.past.length - 1];
      if (previous === undefined || s.present === null) return s;
      return { past: s.past.slice(0, -1), present: previous, future: [s.present, ...s.future] };
    });
  }, []);

  const redo = React.useCallback(() => {
    setState((s) => {
      const next = s.future[0];
      if (next === undefined || s.present === null) return s;
      return { past: [...s.past, s.present], present: next, future: s.future.slice(1) };
    });
  }, []);

  const reset = React.useCallback((value: T) => {
    pending.current = null;
    setState({ past: [], present: value, future: [] });
  }, []);

  return {
    present: state.present,
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
    set,
    begin,
    end,
    undo,
    redo,
    reset,
  };
}
