import { z } from "zod";

/** Trimmed, required text with a friendly error. */
export const requiredText = (label: string, max = 200) =>
  z
    .string({ error: `${label} is required` })
    .trim()
    .min(1, { error: `${label} is required` })
    .max(max, { error: `${label} must be at most ${max} characters` });

/** Optional text: empty strings become undefined. */
export const optionalText = (max = 200) =>
  z
    .string()
    .trim()
    .max(max, { error: `Must be at most ${max} characters` })
    .optional()
    .transform((value) => (value ? value : undefined));

/** Database ids are cuid strings; keep the check loose but bounded. */
export const idSchema = z
  .string({ error: "Invalid id" })
  .trim()
  .min(1, { error: "Invalid id" })
  .max(64, { error: "Invalid id" })
  .regex(/^[a-zA-Z0-9_-]+$/, { error: "Invalid id" });

export const emailSchema = z
  .string({ error: "Email is required" })
  .trim()
  .toLowerCase()
  .pipe(z.email({ error: "Enter a valid email address" }));

/** "19.90"-style amount with at most two decimals. */
export const moneyStringSchema = z
  .string({ error: "Price is required" })
  .trim()
  .regex(/^\d{1,8}(\.\d{1,2})?$/, { error: "Enter an amount like 49 or 49.90" });

export const pageSchema = z.coerce.number().int().min(1).max(10_000).catch(1);

/** A raw URL search param value as Next.js provides it. */
export const rawParam = z.union([z.string(), z.array(z.string())]).optional();
export type RawParam = z.infer<typeof rawParam>;

export function firstParam(raw: RawParam): string | undefined {
  return Array.isArray(raw) ? raw[0] : raw;
}

/** Field errors keyed by dotted path ("shipping.address.city"), for forms and ActionResult. */
export function fieldErrorsFrom(error: z.ZodError): Record<string, string[]> {
  const errors: Record<string, string[]> = {};
  for (const issue of error.issues) {
    const key = issue.path.map(String).join(".") || "_form";
    (errors[key] ??= []).push(issue.message);
  }
  return errors;
}
