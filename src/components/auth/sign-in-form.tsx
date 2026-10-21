"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import type { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { authClient } from "@/lib/auth-client";
import { signInSchema } from "@/lib/validators/auth";

import { authErrorMessage } from "./auth-errors";
import { PasswordInput } from "./password-input";

type Input = z.input<typeof signInSchema>;
type Output = z.output<typeof signInSchema>;

export function SignInForm({ redirectTo }: { redirectTo: string }) {
  const router = useRouter();
  const [formError, setFormError] = useState<string>();
  const [redirecting, setRedirecting] = useState(false);
  const form = useForm<Input, unknown, Output>({
    resolver: zodResolver(signInSchema),
    defaultValues: { email: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(undefined);
    const { error } = await authClient.signIn.email({ ...values, rememberMe: true });
    if (error) {
      setFormError(authErrorMessage(error));
      return;
    }
    setRedirecting(true);
    router.replace(redirectTo);
    // Re-render server components that depend on the session (navbar, account links).
    router.refresh();
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      {formError ? (
        <p
          role="alert"
          className="rounded-md bg-destructive-soft px-4 py-3 text-sm text-destructive"
        >
          {formError}
        </p>
      ) : null}
      <Field label="Email" error={errors.email?.message}>
        {(field) => (
          <Input
            {...field}
            type="email"
            autoComplete="email"
            inputMode="email"
            {...form.register("email")}
          />
        )}
      </Field>
      <Field label="Password" error={errors.password?.message}>
        {(field) => (
          <PasswordInput
            {...field}
            autoComplete="current-password"
            {...form.register("password")}
          />
        )}
      </Field>
      <Button
        type="submit"
        className="w-full"
        loading={isSubmitting || redirecting}
        loadingText="Signing in…"
      >
        Sign in
      </Button>
    </form>
  );
}
