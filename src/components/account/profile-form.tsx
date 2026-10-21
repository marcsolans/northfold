"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { type UpdateProfileInput, updateProfileSchema } from "@/lib/validators/auth";
import { updateProfile } from "@/server/actions/account";

export function ProfileForm({ name, email }: { name: string; email: string }) {
  const router = useRouter();
  const form = useForm<UpdateProfileInput>({
    resolver: zodResolver(updateProfileSchema),
    defaultValues: { name },
  });
  const { errors, isSubmitting, isDirty } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const result = await updateProfile(values);
    if (!result.ok) {
      const message = result.fieldErrors?.name?.[0];
      if (message) form.setError("name", { type: "server", message });
      toast.error(result.error);
      return;
    }
    toast.success("Profile updated");
    form.reset(values);
    router.refresh();
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      <Field label="Full name" error={errors.name?.message}>
        {(field) => <Input {...field} autoComplete="name" {...form.register("name")} />}
      </Field>
      <Field label="Email" hint="Your email address can’t be changed.">
        {(field) => <Input {...field} type="email" value={email} readOnly disabled />}
      </Field>
      <Button type="submit" loading={isSubmitting} loadingText="Saving…" disabled={!isDirty}>
        Save changes
      </Button>
    </form>
  );
}
