/** Cron expressions for the visual schedule picker (5 fields, evaluated by the API in a time zone). */

export interface CronFields {
  minute: string;
  hour: string;
  day: string;
  month: string;
  weekday: string;
}

export const CRON_PRESETS: { key: string; expression: string }[] = [
  { key: "every5", expression: "*/5 * * * *" },
  { key: "every15", expression: "*/15 * * * *" },
  { key: "hourly", expression: "0 * * * *" },
  { key: "daily9", expression: "0 9 * * *" },
  { key: "weekdays9", expression: "0 9 * * 1-5" },
  { key: "monday9", expression: "0 9 * * 1" },
  { key: "monthly", expression: "0 9 1 * *" },
];

const PART = /^(\*|(\d{1,2})(?:-(\d{1,2}))?)(?:\/(\d{1,2}))?$/;
const RANGES: Record<keyof CronFields, [number, number]> = {
  minute: [0, 59],
  hour: [0, 23],
  day: [1, 31],
  month: [1, 12],
  weekday: [0, 7],
};

function validField(value: string, [min, max]: [number, number]): boolean {
  return value.split(",").every((part) => {
    const match = PART.exec(part);
    if (!match) return false;
    const [, , from, to, step] = match;
    const numbers = [from, to].filter((n): n is string => n !== undefined).map(Number);
    if (numbers.some((n) => n < min || n > max)) return false;
    if (numbers.length === 2 && (numbers[0] as number) > (numbers[1] as number)) return false;
    return step === undefined || Number(step) >= 1;
  });
}

export function parseCron(expression: string): CronFields | null {
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, day, month, weekday] = parts as [string, string, string, string, string];
  return { minute, hour, day, month, weekday };
}

export function buildCron(fields: CronFields): string {
  return [fields.minute, fields.hour, fields.day, fields.month, fields.weekday].map((f) => f.trim() || "*").join(" ");
}

/** Field names whose value is not valid cron syntax (or out of range). */
export function invalidCronFields(fields: CronFields): (keyof CronFields)[] {
  return (Object.keys(RANGES) as (keyof CronFields)[]).filter((key) => !validField(fields[key].trim() || "*", RANGES[key]));
}

export function presetOf(expression: string): string | null {
  const normalized = expression.trim().replace(/\s+/g, " ");
  return CRON_PRESETS.find((p) => p.expression === normalized)?.key ?? null;
}

const FALLBACK_ZONES = [
  "Europe/Madrid",
  "Europe/Lisbon",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Rome",
  "Europe/Amsterdam",
  "Atlantic/Canary",
  "America/Mexico_City",
  "America/Bogota",
  "America/Buenos_Aires",
  "America/New_York",
  "UTC",
];

export function timeZones(): string[] {
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    return zones.includes("UTC") ? zones : [...zones, "UTC"];
  } catch {
    return FALLBACK_ZONES;
  }
}
