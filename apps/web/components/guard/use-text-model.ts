"use client";

import * as React from "react";

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * A text input bound to a structured value (lists, typed numbers): the text the user types is kept as typed
 * (trailing commas, new lines, "5."), and is only reset when the value changes from outside (e.g. JSON mode).
 */
export function useTextModel<T>(
  value: T,
  format: (value: T) => string,
  parse: (text: string) => T,
  onChange: (value: T) => void,
): [string, (text: string) => void] {
  const [text, setText] = React.useState(() => format(value));
  const [seen, setSeen] = React.useState<T>(value);
  if (!same(value, seen)) {
    setSeen(value);
    setText(format(value));
  }
  const update = (next: string) => {
    const parsed = parse(next);
    setText(next);
    setSeen(parsed);
    if (!same(parsed, value)) onChange(parsed);
  };
  return [text, update];
}
