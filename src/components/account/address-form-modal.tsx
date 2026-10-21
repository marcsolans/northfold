"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { FormProvider, useForm } from "react-hook-form";
import toast from "react-hot-toast";
import type { z } from "zod";

import { AddressFields } from "@/components/store/address-fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Modal } from "@/components/ui/modal";
import {
  EMPTY_ADDRESS_INPUT,
  savedAddressSchema,
  toShippingCountry,
} from "@/lib/validators/address";
import { createAddress, updateAddress } from "@/server/actions/account";
import type { AddressDTO } from "@/server/queries/addresses";

type Input = z.input<typeof savedAddressSchema>;
type Output = z.output<typeof savedAddressSchema>;

const FIELDS = [
  "fullName",
  "phone",
  "line1",
  "line2",
  "city",
  "state",
  "postalCode",
  "country",
] as const;

function defaultsFor(address: AddressDTO | null): Input {
  if (!address) return { address: EMPTY_ADDRESS_INPUT, isDefault: false };
  return {
    address: {
      fullName: address.fullName,
      phone: address.phone,
      line1: address.line1,
      line2: address.line2 ?? "",
      city: address.city,
      state: address.state,
      postalCode: address.postalCode,
      country: toShippingCountry(address.country),
    },
    isDefault: address.isDefault,
  };
}

/** Add or edit an address. Remount with a new `key` to reset for another address. */
export function AddressFormModal({
  open,
  onClose,
  address,
}: {
  open: boolean;
  onClose: () => void;
  address: AddressDTO | null;
}) {
  const router = useRouter();
  const form = useForm<Input, unknown, Output>({
    resolver: zodResolver(savedAddressSchema),
    defaultValues: defaultsFor(address),
  });
  const { isSubmitting } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const result = address ? await updateAddress(address.id, values) : await createAddress(values);
    if (!result.ok) {
      for (const field of FIELDS) {
        const message = result.fieldErrors?.[`address.${field}`]?.[0];
        if (message) form.setError(`address.${field}`, { type: "server", message });
      }
      toast.error(result.error);
      return;
    }
    toast.success(address ? "Address updated" : "Address added");
    onClose();
    router.refresh();
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={address ? "Edit address" : "Add an address"}
      className="max-w-2xl"
    >
      <FormProvider {...form}>
        <form onSubmit={onSubmit} noValidate className="space-y-6">
          <AddressFields disabled={isSubmitting} />
          <Checkbox
            label="Use as my default address"
            disabled={isSubmitting || Boolean(address?.isDefault)}
            {...form.register("isDefault")}
          />
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" loading={isSubmitting} loadingText="Saving…">
              Save address
            </Button>
          </div>
        </form>
      </FormProvider>
    </Modal>
  );
}
