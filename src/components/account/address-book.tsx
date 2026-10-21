"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import toast from "react-hot-toast";
import { HiOutlineMapPin, HiPlus } from "react-icons/hi2";

import { AddressSummary } from "@/components/store/address-summary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Modal } from "@/components/ui/modal";
import { deleteAddress, setDefaultAddress } from "@/server/actions/account";
import type { AddressDTO } from "@/server/queries/addresses";

import { AddressFormModal } from "./address-form-modal";

type Editing = { mode: "closed" } | { mode: "new" } | { mode: "edit"; address: AddressDTO };

export function AddressBook({ addresses }: { addresses: AddressDTO[] }) {
  const router = useRouter();
  const [editing, setEditing] = useState<Editing>({ mode: "closed" });
  const [deleting, setDeleting] = useState<AddressDTO | null>(null);
  const [pending, startTransition] = useTransition();

  function run(
    action: () => Promise<{ ok: boolean; error?: string }>,
    success: string,
    after?: () => void,
  ) {
    startTransition(async () => {
      const result = await action();
      if (!result.ok) {
        toast.error(result.error ?? "Something went wrong.");
        return;
      }
      toast.success(success);
      after?.();
      router.refresh();
    });
  }

  const formKey = editing.mode === "edit" ? editing.address.id : editing.mode;

  return (
    <>
      <div className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-3xl font-light tracking-tight">Addresses</h1>
        <Button onClick={() => setEditing({ mode: "new" })} size="sm">
          <HiPlus aria-hidden="true" className="size-4" />
          Add address
        </Button>
      </div>

      {addresses.length === 0 ? (
        <EmptyState
          icon={<HiOutlineMapPin />}
          title="No saved addresses"
          description="Save an address to check out faster next time."
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {addresses.map((address) => (
            <li
              key={address.id}
              className="flex flex-col rounded-lg border border-border bg-card p-5"
            >
              <div className="flex-1">
                {address.isDefault ? (
                  <Badge tone="accent" className="mb-3">
                    Default
                  </Badge>
                ) : null}
                <AddressSummary address={address} />
              </div>
              <div className="mt-5 flex flex-wrap gap-x-4 gap-y-2 border-t border-border pt-4 text-sm">
                <button
                  type="button"
                  className="underline-offset-4 hover:underline"
                  onClick={() => setEditing({ mode: "edit", address })}
                >
                  Edit<span className="sr-only"> address of {address.fullName}</span>
                </button>
                {!address.isDefault ? (
                  <button
                    type="button"
                    disabled={pending}
                    className="underline-offset-4 hover:underline disabled:opacity-50"
                    onClick={() =>
                      run(() => setDefaultAddress(address.id), "Default address updated")
                    }
                  >
                    Set as default
                  </button>
                ) : null}
                <button
                  type="button"
                  className="text-destructive underline-offset-4 hover:underline"
                  onClick={() => setDeleting(address)}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <AddressFormModal
        key={formKey}
        open={editing.mode !== "closed"}
        onClose={() => setEditing({ mode: "closed" })}
        address={editing.mode === "edit" ? editing.address : null}
      />

      <Modal
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title="Delete this address?"
        description={deleting ? `${deleting.line1}, ${deleting.city}` : undefined}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleting(null)} disabled={pending}>
              Keep it
            </Button>
            <Button
              variant="destructive"
              loading={pending}
              onClick={() => {
                if (deleting)
                  run(
                    () => deleteAddress(deleting.id),
                    "Address deleted",
                    () => setDeleting(null),
                  );
              }}
            >
              Delete
            </Button>
          </>
        }
      />
    </>
  );
}
