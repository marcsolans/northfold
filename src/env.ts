import "server-only";

import { z } from "zod";

/**
 * Server environment, validated once at startup (see `src/instrumentation.ts`).
 * Integrations (Stripe, Google, Cloudinary) are optional so the store runs locally with only
 * a database; each one must be configured completely or not at all.
 */
const optional = z
  .string()
  .trim()
  .transform((value) => (value === "" ? undefined : value))
  .optional();

const schema = z
  .object({
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),

    DATABASE_URL: z.url({ error: "DATABASE_URL must be a postgres connection URL" }),
    DIRECT_URL: z.url().optional(),

    BETTER_AUTH_SECRET: z
      .string()
      .min(32, { error: "BETTER_AUTH_SECRET must be at least 32 characters" }),
    BETTER_AUTH_URL: z.url(),
    NEXT_PUBLIC_APP_URL: z.url(),

    GOOGLE_CLIENT_ID: optional,
    GOOGLE_CLIENT_SECRET: optional,

    STRIPE_SECRET_KEY: optional.pipe(
      z
        .string()
        .regex(/^(sk|rk)_(test|live)_/, { error: "STRIPE_SECRET_KEY must start with sk_ or rk_" })
        .optional(),
    ),
    STRIPE_WEBHOOK_SECRET: optional.pipe(
      z
        .string()
        .startsWith("whsec_", { error: "STRIPE_WEBHOOK_SECRET must start with whsec_" })
        .optional(),
    ),

    CLOUDINARY_CLOUD_NAME: optional,
    CLOUDINARY_API_KEY: optional,
    CLOUDINARY_API_SECRET: optional,

    ADMIN_EMAILS: z
      .string()
      .default("")
      .transform((value) =>
        value
          .split(",")
          .map((email) => email.trim().toLowerCase())
          .filter(Boolean),
      )
      .pipe(z.array(z.email({ error: "ADMIN_EMAILS must be a comma-separated list of emails" }))),
  })
  .superRefine((env, ctx) => {
    const groups: Record<string, (keyof typeof env)[]> = {
      Google: ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
      Stripe: ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
      Cloudinary: ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"],
    };
    for (const [name, keys] of Object.entries(groups)) {
      const present = keys.filter((key) => env[key] !== undefined);
      if (present.length > 0 && present.length < keys.length) {
        for (const key of keys.filter((k) => env[k] === undefined)) {
          ctx.addIssue({
            code: "custom",
            path: [key],
            message: `${key} is required when other ${name} variables are set`,
          });
        }
      }
    }
  });

export type Env = z.infer<typeof schema>;

function loadEnv(): Env {
  const parsed = schema.safeParse(process.env);
  if (!parsed.success) {
    const details = parsed.error.issues
      .map((issue) => `  • ${issue.path.join(".") || "env"}: ${issue.message}`)
      .join("\n");
    throw new Error(
      `Invalid environment configuration:\n${details}\nSee .env.example for every variable.`,
    );
  }
  return parsed.data;
}

export const env = loadEnv();

export const features = {
  googleAuth: Boolean(env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET),
  stripe: Boolean(env.STRIPE_SECRET_KEY && env.STRIPE_WEBHOOK_SECRET),
  cloudinary: Boolean(
    env.CLOUDINARY_CLOUD_NAME && env.CLOUDINARY_API_KEY && env.CLOUDINARY_API_SECRET,
  ),
} as const;
