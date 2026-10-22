/** Interface theme → CSS variables on the page wrapper (accent, density, forced light/dark). */

import type * as React from "react";

import type { ThemeDef } from "./types";

/** Light tokens, to force light mode inside a dark document (mirror of packages/ui theme.css :root). */
const LIGHT: Record<string, string> = {
  "--bg": "#ffffff",
  "--surface": "#ffffff",
  "--subtle": "#f7f6f4",
  "--muted": "#efede9",
  "--border": "#e7e5e1",
  "--border-strong": "#d6d3cd",
  "--fg": "#111111",
  "--fg-muted": "#57534e",
  "--fg-subtle": "#78716c",
  "--success": "#15803d",
  "--success-soft": "#e8f5ec",
  "--warning": "#b45309",
  "--warning-soft": "#fdf3e2",
  "--danger": "#b42318",
  "--danger-soft": "#fdecea",
  "--info": "#1d4ed8",
  "--info-soft": "#e8efff",
};

function luminance(hex: string): number {
  const v = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(v.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function isHexColor(value: string | undefined | null): value is string {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value);
}

export function themeClass(theme: ThemeDef | undefined): string {
  return theme?.mode === "dark" ? "dark" : "";
}

export function themeStyle(theme: ThemeDef | undefined): React.CSSProperties {
  const style: Record<string, string> = {};
  if (theme?.mode === "light") Object.assign(style, LIGHT, { colorScheme: "light" });
  if (theme?.mode === "dark") style.colorScheme = "dark";
  const accent = theme?.accent;
  if (isHexColor(accent)) {
    style["--accent"] = accent;
    style["--ring"] = accent;
    style["--accent-hover"] = `color-mix(in srgb, ${accent} 85%, black)`;
    style["--accent-soft"] = `color-mix(in srgb, ${accent} 12%, var(--surface))`;
    style["--accent-fg"] = luminance(accent) > 0.45 ? "#111111" : "#ffffff";
  }
  style["--row"] = theme?.density === "compact" ? "44px" : "56px";
  return style as React.CSSProperties;
}
