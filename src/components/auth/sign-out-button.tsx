"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";
import toast from "react-hot-toast";

import { authClient } from "@/lib/auth-client";
import { cn } from "@/lib/utils";
import { useCartStore } from "@/stores/cart-store";

export function SignOutButton({
  className,
  children,
}: {
  className?: string;
  children?: ReactNode;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function signOut() {
    setPending(true);
    const { error } = await authClient.signOut();
    if (error) {
      setPending(false);
      toast.error("Could not sign out. Please try again.");
      return;
    }
    // The cart lives in this browser, not the account: never leave it for the next person.
    useCartStore.getState().clear();
    router.replace("/");
    // Drops cached, user-specific server output from the client router.
    router.refresh();
  }

  return (
    <button
      type="button"
      onClick={signOut}
      disabled={pending}
      className={cn("disabled:opacity-60", className)}
    >
      {children ?? "Sign out"}
    </button>
  );
}
