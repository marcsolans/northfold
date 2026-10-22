/** Value formatting for data components (locale-aware; no copy). */

export type ValueFormat = "text" | "number" | "currency" | "percent" | "date" | "datetime" | "boolean" | "badge";

export type DataRow = Record<string, unknown>;

export interface FormatOptions {
  locale?: string;
  currency?: string;
  decimals?: number | null;
}

export function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function toDate(value: unknown): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === "string" || typeof value === "number") {
    const raw = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00` : value;
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function parseDate(value: unknown): Date | null {
  return toDate(value);
}

export function formatValue(value: unknown, format: ValueFormat = "text", opts: FormatOptions = {}): string {
  const locale = opts.locale ?? "es-ES";
  if (value === null || value === undefined || value === "") return "—";
  const digits = opts.decimals ?? undefined;
  switch (format) {
    case "number": {
      const n = toNumber(value);
      return n === null
        ? String(value)
        : new Intl.NumberFormat(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits ?? 2 }).format(n);
    }
    case "currency": {
      const n = toNumber(value);
      return n === null
        ? String(value)
        : new Intl.NumberFormat(locale, {
            style: "currency",
            currency: opts.currency ?? "EUR",
            minimumFractionDigits: digits,
            maximumFractionDigits: digits ?? 2,
          }).format(n);
    }
    case "percent": {
      const n = toNumber(value);
      return n === null
        ? String(value)
        : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: digits ?? 1 }).format(n);
    }
    case "date": {
      const d = toDate(value);
      return d ? new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(d) : String(value);
    }
    case "datetime": {
      const d = toDate(value);
      return d ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(d) : String(value);
    }
    case "boolean":
      return value === true || value === "true" || value === 1 ? "✓" : "—";
    default:
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
  }
}

/** Columns of a row set in first-seen order. */
export function columnsOf(rows: DataRow[]): string[] {
  const out: string[] = [];
  for (const row of rows) for (const key of Object.keys(row)) if (!out.includes(key)) out.push(key);
  return out;
}

export function humanize(key: string): string {
  const text = key.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : key;
}

export function isNumericColumn(rows: DataRow[], key: string): boolean {
  const values = rows.map((r) => r[key]).filter((v) => v !== null && v !== undefined && v !== "");
  return values.length > 0 && values.every((v) => toNumber(v) !== null);
}

export function matchesSearch(row: DataRow, query: string, keys: string[]): boolean {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  return keys.some((k) => {
    const v = row[k];
    return v !== null && v !== undefined && String(typeof v === "object" ? JSON.stringify(v) : v).toLocaleLowerCase().includes(q);
  });
}
