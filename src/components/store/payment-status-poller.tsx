"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Spinner } from "@/components/ui/spinner";
import { getOrderPaymentState } from "@/server/actions/orders";

const INTERVAL_MS = 2000;
const MAX_ATTEMPTS = 30;

/**
 * Shown while a Stripe payment is still PENDING in our database: polls the order (not the URL)
 * until the webhook has recorded the outcome, then re-renders the page from the server.
 */
export function PaymentStatusPoller({ orderId }: { orderId: string }) {
  const router = useRouter();
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    let attempts = 0;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      attempts += 1;
      const result = await getOrderPaymentState({ orderId }).catch(() => null);
      if (cancelled) return;
      if (result?.ok && result.data.paymentStatus !== "PENDING") {
        router.refresh();
        return;
      }
      if (attempts >= MAX_ATTEMPTS) {
        setTimedOut(true);
        return;
      }
      timer = setTimeout(() => void poll(), INTERVAL_MS);
    }

    timer = setTimeout(() => void poll(), INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [orderId, router]);

  if (timedOut) {
    return (
      <p className="text-sm text-muted-foreground">
        Confirmation is taking longer than usual. Your payment is safe — this page will show the
        final status once Stripe confirms it; you can also check your order history.
      </p>
    );
  }

  return (
    <p className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
      <Spinner />
      Confirming your payment with Stripe…
    </p>
  );
}
