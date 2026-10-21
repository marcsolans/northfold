"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useMemo, useState } from "react";
import { FormProvider, useForm, useWatch } from "react-hook-form";
import toast from "react-hot-toast";
import { HiOutlineBanknotes, HiOutlineCreditCard, HiOutlineShoppingBag } from "react-icons/hi2";

import { Button, buttonClasses } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMoney, lineTotal } from "@/lib/money";
import { cn } from "@/lib/utils";
import {
  type AddressDraft,
  checkoutFormSchema,
  type CheckoutFormValues,
  EMPTY_ADDRESS,
  toPlaceOrderInput,
} from "@/lib/validators/checkout";
import { placeOrder } from "@/server/actions/checkout";
import type { AddressDTO } from "@/server/queries/addresses";
import { selectTotals, useCartStore } from "@/stores/cart-store";

import { AddressFields } from "./address-fields";
import { AddressSummary } from "./address-summary";
import { CartChanges } from "./cart-changes";
import { OrderSummary } from "./order-summary";
import { useValidatedCart } from "./use-validated-cart";

const ADDRESS_FIELDS: readonly (keyof AddressDraft)[] = [
  "fullName",
  "phone",
  "line1",
  "line2",
  "city",
  "state",
  "postalCode",
  "country",
];

function ChoiceCard({
  checked,
  disabled,
  children,
}: {
  checked: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer gap-4 rounded-lg border bg-card p-4 transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
        checked ? "border-foreground" : "border-border hover:border-input",
        disabled && "cursor-not-allowed opacity-60",
      )}
    >
      {children}
    </label>
  );
}

export function CheckoutForm({
  addresses,
  stripeEnabled,
}: {
  addresses: AddressDTO[];
  stripeEnabled: boolean;
}) {
  const router = useRouter();
  const { status, changes, revalidate } = useValidatedCart();
  const lines = useCartStore((state) => state.lines);
  const totals = useMemo(() => selectTotals({ lines }), [lines]);
  const [redirecting, setRedirecting] = useState(false);

  const form = useForm<CheckoutFormValues>({
    resolver: zodResolver(checkoutFormSchema),
    defaultValues: {
      shippingChoice: addresses[0]?.id ?? "new",
      address: EMPTY_ADDRESS,
      saveAddress: addresses.length === 0,
      paymentMethod: stripeEnabled ? "STRIPE" : "CASH_ON_DELIVERY",
    },
  });
  const shippingChoice = useWatch({ control: form.control, name: "shippingChoice" });
  const paymentMethod = useWatch({ control: form.control, name: "paymentMethod" });
  const { isSubmitting, errors } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const items = lines.map((line) => ({ variantId: line.variantId, quantity: line.quantity }));
    const result = await placeOrder(toPlaceOrderInput(values, items));
    if (!result.ok) {
      toast.error(result.error);
      for (const field of ADDRESS_FIELDS) {
        const message = result.fieldErrors?.[`shipping.address.${field}`]?.[0];
        if (message) form.setError(`address.${field}`, { type: "server", message });
      }
      // Stock or prices may have moved: re-check the bag so the summary is accurate.
      revalidate();
      return;
    }
    setRedirecting(true);
    if (values.paymentMethod === "STRIPE") {
      window.location.assign(result.data.redirectUrl);
    } else {
      router.push(result.data.redirectUrl);
    }
  });

  if (status === "validating" && lines.length === 0) {
    return (
      <div aria-busy="true" className="grid gap-10 lg:grid-cols-[1fr_24rem]">
        <Skeleton className="h-96" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (lines.length === 0 && !redirecting) {
    return (
      <div className="space-y-6">
        <CartChanges changes={changes} />
        <EmptyState
          icon={<HiOutlineShoppingBag />}
          title="Your bag is empty"
          description="Add something you love before checking out."
          action={
            <Link href="/shop" className={buttonClasses()}>
              Continue shopping
            </Link>
          }
        />
      </div>
    );
  }

  const busy = isSubmitting || redirecting;

  return (
    <FormProvider {...form}>
      <form
        onSubmit={onSubmit}
        noValidate
        className="grid items-start gap-10 lg:grid-cols-[1fr_24rem]"
      >
        <div className="space-y-10">
          <CartChanges changes={changes} />

          <section aria-labelledby="shipping-heading">
            <h2 id="shipping-heading" className="text-lg font-medium">
              Shipping address
            </h2>
            <fieldset className="mt-5 space-y-3" disabled={busy}>
              <legend className="sr-only">Choose a shipping address</legend>
              {addresses.map((address) => (
                <ChoiceCard key={address.id} checked={shippingChoice === address.id}>
                  <input
                    type="radio"
                    value={address.id}
                    className="mt-1 size-4 accent-accent"
                    {...form.register("shippingChoice")}
                  />
                  <span className="flex-1">
                    <AddressSummary address={address} />
                    {address.isDefault ? (
                      <span className="mt-2 inline-block text-xs text-accent">Default address</span>
                    ) : null}
                  </span>
                </ChoiceCard>
              ))}
              {addresses.length > 0 ? (
                <ChoiceCard checked={shippingChoice === "new"}>
                  <input
                    type="radio"
                    value="new"
                    className="mt-1 size-4 accent-accent"
                    {...form.register("shippingChoice")}
                  />
                  <span className="text-sm font-medium">Use a new address</span>
                </ChoiceCard>
              ) : null}
            </fieldset>
            {shippingChoice === "new" ? (
              <div className="mt-6 space-y-5">
                <AddressFields disabled={busy} />
                <Checkbox
                  label="Save this address to my account"
                  disabled={busy}
                  {...form.register("saveAddress")}
                />
              </div>
            ) : null}
          </section>

          <section aria-labelledby="payment-heading">
            <h2 id="payment-heading" className="text-lg font-medium">
              Payment
            </h2>
            <fieldset className="mt-5 space-y-3" disabled={busy}>
              <legend className="sr-only">Choose a payment method</legend>
              <ChoiceCard checked={paymentMethod === "STRIPE"} disabled={!stripeEnabled}>
                <input
                  type="radio"
                  value="STRIPE"
                  disabled={!stripeEnabled}
                  className="mt-1 size-4 accent-accent"
                  {...form.register("paymentMethod")}
                />
                <HiOutlineCreditCard aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
                <span className="text-sm">
                  <span className="font-medium">Card</span>
                  <span className="mt-1 block text-muted-foreground">
                    {stripeEnabled
                      ? "Pay securely with Stripe. You’ll return here once payment is complete."
                      : "Card payments are temporarily unavailable."}
                  </span>
                </span>
              </ChoiceCard>
              <ChoiceCard checked={paymentMethod === "CASH_ON_DELIVERY"}>
                <input
                  type="radio"
                  value="CASH_ON_DELIVERY"
                  className="mt-1 size-4 accent-accent"
                  {...form.register("paymentMethod")}
                />
                <HiOutlineBanknotes aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
                <span className="text-sm">
                  <span className="font-medium">Cash on delivery</span>
                  <span className="mt-1 block text-muted-foreground">
                    Pay in cash when your order arrives.
                  </span>
                </span>
              </ChoiceCard>
            </fieldset>
            {errors.paymentMethod?.message ? (
              <p role="alert" className="mt-2 text-xs text-destructive">
                {errors.paymentMethod.message}
              </p>
            ) : null}
          </section>
        </div>

        <aside className="lg:sticky lg:top-24">
          <OrderSummary totals={totals}>
            <ul
              className="mb-6 divide-y divide-border border-y border-border"
              aria-label="Items in your order"
            >
              {lines.map((line) => (
                <li key={line.variantId} className="flex gap-3 py-3">
                  <div className="relative aspect-[4/5] w-12 shrink-0 overflow-hidden rounded bg-surface">
                    {line.snapshot.imageUrl ? (
                      <Image
                        src={line.snapshot.imageUrl}
                        alt=""
                        fill
                        sizes="48px"
                        className="object-cover"
                      />
                    ) : null}
                  </div>
                  <div className="min-w-0 flex-1 text-sm">
                    <p className="truncate font-medium">{line.snapshot.productName}</p>
                    <p className="text-muted-foreground">
                      {line.snapshot.size} · {line.snapshot.colorName} · Qty {line.quantity}
                    </p>
                  </div>
                  <p className="text-sm tabular-nums">
                    {formatMoney(lineTotal(line.snapshot.unitPrice, line.quantity))}
                  </p>
                </li>
              ))}
            </ul>
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={status === "validating"}
              loading={busy}
              loadingText={paymentMethod === "STRIPE" ? "Redirecting to Stripe…" : "Placing order…"}
            >
              {status === "validating"
                ? "Checking availability…"
                : paymentMethod === "STRIPE"
                  ? `Pay ${formatMoney(totals.total)}`
                  : "Place order"}
            </Button>
            <p className="mt-4 text-center text-xs text-muted-foreground">
              Prices and stock are confirmed when you place your order.
            </p>
          </OrderSummary>
        </aside>
      </form>
    </FormProvider>
  );
}
