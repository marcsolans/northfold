"use client";

import { useState } from "react";
import toast from "react-hot-toast";
import { FcGoogle } from "react-icons/fc";

import { Button } from "@/components/ui/button";
import { authClient } from "@/lib/auth-client";

export function GoogleButton({ redirectTo }: { redirectTo: string }) {
  const [pending, setPending] = useState(false);

  async function signInWithGoogle() {
    setPending(true);
    const { error } = await authClient.signIn.social({
      provider: "google",
      callbackURL: redirectTo,
      errorCallbackURL: "/sign-in",
    });
    if (error) {
      setPending(false);
      toast.error("Could not start Google sign-in. Please try again.");
    }
  }

  return (
    <Button variant="outline" className="w-full" loading={pending} onClick={signInWithGoogle}>
      <FcGoogle aria-hidden="true" className="size-5" />
      Continue with Google
    </Button>
  );
}

export function OrDivider() {
  return (
    <div className="my-6 flex items-center gap-4 text-xs tracking-widest text-muted-foreground uppercase">
      <span className="h-px flex-1 bg-border" />
      or
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
