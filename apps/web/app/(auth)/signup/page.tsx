import type { Metadata } from "next";
import { Suspense } from "react";

import { SignupForm } from "./signup-form";

export const metadata: Metadata = {
  title: "Crear cuenta",
  description: "Prueba Messer 14 días con el plan Pro, sin tarjeta.",
};

export default function SignupPage() {
  return (
    <Suspense>
      <SignupForm />
    </Suspense>
  );
}
