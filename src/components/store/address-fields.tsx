"use client";

import { type FieldErrors, useFormContext } from "react-hook-form";

import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { COUNTRY_OPTIONS } from "@/lib/countries";
import type { AddressDraft } from "@/lib/validators/checkout";

type WithAddress = { address: AddressDraft };

/** Address inputs for any form whose values contain an `address` object. */
export function AddressFields({ disabled = false }: { disabled?: boolean }) {
  const { register, formState } = useFormContext<WithAddress>();
  const errors: FieldErrors<AddressDraft> = formState.errors.address ?? {};

  return (
    <div className="grid gap-5 sm:grid-cols-2">
      <Field label="Full name" error={errors.fullName?.message} className="sm:col-span-2">
        {(field) => (
          <Input
            {...field}
            autoComplete="name"
            disabled={disabled}
            {...register("address.fullName")}
          />
        )}
      </Field>
      <Field label="Address" error={errors.line1?.message} className="sm:col-span-2">
        {(field) => (
          <Input
            {...field}
            autoComplete="address-line1"
            disabled={disabled}
            {...register("address.line1")}
          />
        )}
      </Field>
      <Field
        label="Apartment, suite, etc."
        optional
        error={errors.line2?.message}
        className="sm:col-span-2"
      >
        {(field) => (
          <Input
            {...field}
            autoComplete="address-line2"
            disabled={disabled}
            {...register("address.line2")}
          />
        )}
      </Field>
      <Field label="City" error={errors.city?.message}>
        {(field) => (
          <Input
            {...field}
            autoComplete="address-level2"
            disabled={disabled}
            {...register("address.city")}
          />
        )}
      </Field>
      <Field label="State / region" error={errors.state?.message}>
        {(field) => (
          <Input
            {...field}
            autoComplete="address-level1"
            disabled={disabled}
            {...register("address.state")}
          />
        )}
      </Field>
      <Field label="Postal code" error={errors.postalCode?.message}>
        {(field) => (
          <Input
            {...field}
            autoComplete="postal-code"
            disabled={disabled}
            {...register("address.postalCode")}
          />
        )}
      </Field>
      <Field label="Country" error={errors.country?.message}>
        {(field) => (
          <Select
            {...field}
            autoComplete="country"
            disabled={disabled}
            options={COUNTRY_OPTIONS}
            {...register("address.country")}
          />
        )}
      </Field>
      <Field
        label="Phone"
        hint="For delivery questions only."
        error={errors.phone?.message}
        className="sm:col-span-2"
      >
        {(field) => (
          <Input
            {...field}
            type="tel"
            autoComplete="tel"
            disabled={disabled}
            {...register("address.phone")}
          />
        )}
      </Field>
    </div>
  );
}
