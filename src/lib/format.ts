// Dates are rendered on the server, so they use one fixed time zone instead of the server's.
const dateFormatter = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" });
const dateTimeFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function formatDate(iso: string | Date): string {
  return dateFormatter.format(typeof iso === "string" ? new Date(iso) : iso);
}

/** e.g. "Oct 21, 2026, 9:06 AM UTC". */
export function formatDateTime(iso: string | Date): string {
  return `${dateTimeFormatter.format(typeof iso === "string" ? new Date(iso) : iso)} UTC`;
}
