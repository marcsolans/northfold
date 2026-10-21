"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";
import type { z } from "zod";

import { authErrorMessage } from "@/components/auth/auth-errors";
import { PasswordInput } from "@/components/auth/password-input";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { authClient } from "@/lib/auth-client";
import { changePasswordSchema, PASSWORD_MIN_LENGTH } from "@/lib/validators/auth";

type Input = z.input<typeof changePasswordSchema>;

/**
 * Calls Better Auth's change-password endpoint from the browser so its rate limit applies.
 * Other sessions are signed out; this one gets a fresh cookie.
 */
export function PasswordForm() {
  const form = useForm<Input>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { currentPassword: "", newPassword: "", confirmPassword: "" },
  });
  const { errors, isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async ({ currentPassword, newPassword }) => {
    const { error } = await authClient.changePassword({
      currentPassword,
      newPassword,
      revokeOtherSessions: true,
    });
    if (error) {
      const message = authErrorMessage(error);
      if (error.code === "INVALID_PASSWORD")
        form.setError("currentPassword", { type: "server", message });
      toast.error(message);
      return;
    }
    toast.success("Password changed. Other devices have been signed out.");
    form.reset();
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      <Field label="Current password" error={errors.currentPassword?.message}>
        {(field) => (
          <PasswordInput
            {...field}
            autoComplete="current-password"
            {...form.register("currentPassword")}
          />
        )}
      </Field>
      <Field
        label="New password"
        hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
        error={errors.newPassword?.message}
      >
        {(field) => (
          <PasswordInput {...field} autoComplete="new-password" {...form.register("newPassword")} />
        )}
      </Field>
      <Field label="Confirm new password" error={errors.confirmPassword?.message}>
        {(field) => (
          <PasswordInput
            {...field}
            autoComplete="new-password"
            {...form.register("confirmPassword")}
          />
        )}
      </Field>
      <Button type="submit" loading={isSubmitting} loadingText="Updating…">
        Change password
      </Button>
    </form>
  );
}
