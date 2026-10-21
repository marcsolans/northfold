"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { cancelOrder } from "@/server/actions/account";

export function CancelOrderButton({ orderId }: { orderId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  function confirm() {
    startTransition(async () => {
      const result = await cancelOrder({ orderId });
      if (!result.ok) {
        toast.error(result.error);
        return;
      }
      toast.success("Your order has been cancelled.");
      setOpen(false);
      router.refresh();
    });
  }

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Cancel order
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Cancel this order?"
        description="Your items will be released and you won’t be charged anything."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              Keep order
            </Button>
            <Button
              variant="destructive"
              onClick={confirm}
              loading={pending}
              loadingText="Cancelling…"
            >
              Cancel order
            </Button>
          </>
        }
      />
    </>
  );
}
