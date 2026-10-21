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
import { PASSWORD_MIN_LENGTH, signUpSchema } from "@/lib/validators/auth";

import { authErrorMessage } from "./auth-errors";
import { PasswordInput } from "./password-input";

type Input = z.input<typeof signUpSchema>;
type Output = z.output<typeof signUpSchema>;

export function SignUpForm({ redirectTo }: { redirectTo: string }) {
  const router = useRouter();
  const [formError, setFormError] = useState<string>();
  const [redirecting, setRedirecting] = useState(false);
  const form = useForm<Input, unknown, Output>({
    resolver: zodResolver(signUpSchema),
    defaultValues: { name: "", email: "", password: "", confirmPassword: "" },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async ({ name, email, password }) => {
    setFormError(undefined);
    const { error } = await authClient.signUp.email({ name, email, password });
    if (error) {
      setFormError(authErrorMessage(error));
      return;
    }
    setRedirecting(true);
    router.replace(redirectTo);
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
      <Field label="Full name" error={errors.name?.message}>
        {(field) => <Input {...field} autoComplete="name" {...form.register("name")} />}
      </Field>
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
      <Field
        label="Password"
        hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
        error={errors.password?.message}
      >
        {(field) => (
          <PasswordInput {...field} autoComplete="new-password" {...form.register("password")} />
        )}
      </Field>
      <Field label="Confirm password" error={errors.confirmPassword?.message}>
        {(field) => (
          <PasswordInput
            {...field}
            autoComplete="new-password"
            {...form.register("confirmPassword")}
          />
        )}
      </Field>
      <Button
        type="submit"
        className="w-full"
        loading={isSubmitting || redirecting}
        loadingText="Creating account…"
      >
        Create account
      </Button>
    </form>
  );
}
