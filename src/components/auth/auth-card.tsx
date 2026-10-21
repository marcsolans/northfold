import { type ReactNode } from "react";

import { Card } from "@/components/ui/card";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <Card className="px-6 py-8 sm:px-10 sm:py-10">
      <h1 className="text-2xl font-light tracking-tight">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      <div className="mt-8">{children}</div>
      <div className="mt-8 border-t border-border pt-6 text-center text-sm text-muted-foreground">
        {footer}
      </div>
    </Card>
  );
}
