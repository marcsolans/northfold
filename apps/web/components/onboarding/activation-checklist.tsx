"use client";

import { Button, Card, ErrorState, Skeleton, cn, toast } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { http } from "@/lib/api";
import { useRole } from "@/lib/hooks/use-me";
import { CHECKLIST_KEY, type Checklist, ONBOARDING_KEY, type OnboardingState } from "@/lib/onboarding";

/**
 * Activation checklist for the Home page (computed by the API from real data: projects, knowledge files,
 * connections, runs and deployments). Hidden once every step is done or after "Ocultar".
 */
export function ActivationChecklist({ className }: { className?: string }) {
  const t = useTranslations("onboarding.checklist");
  const qc = useQueryClient();
  const canEdit = useRole("builder");
  const query = useQuery({
    queryKey: CHECKLIST_KEY,
    queryFn: () => http.get<Checklist>("/onboarding/checklist"),
    staleTime: 30_000,
  });
  const dismiss = useMutation({
    mutationFn: () => http.patch<OnboardingState>("/onboarding", { dismissed: true }),
    onSuccess: (state) => {
      qc.setQueryData(ONBOARDING_KEY, state);
      qc.setQueryData<Checklist>(CHECKLIST_KEY, { steps: state.steps, complete: state.complete, dismissed: state.dismissed });
    },
    onError: () => toast.error(t("hideError")),
  });

  if (query.isPending) {
    return (
      <Card className={cn("p-4", className)} aria-busy>
        <Skeleton className="h-5 w-40" />
        <Skeleton className="mt-3 h-1.5 w-full" />
        <div className="mt-4 grid gap-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </Card>
    );
  }
  if (query.isError) {
    return (
      <div className={className}>
        <ErrorState title={t("errorTitle")} onRetry={() => void query.refetch()} retryLabel={t("retry")} />
      </div>
    );
  }

  const { steps, complete, dismissed } = query.data;
  if (complete || dismissed) return null;
  const done = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done);

  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-fg">{t("title")}</h2>
          <p className="mt-0.5 text-sm text-fg-muted">{t("subtitle")}</p>
        </div>
        {canEdit ? (
          <Button variant="ghost" size="sm" loading={dismiss.isPending} onClick={() => dismiss.mutate()}>
            {t("hide")}
          </Button>
        ) : null}
      </div>
      <div className="px-4 pt-3">
        <div className="flex items-center justify-between text-xs text-fg-muted">
          <span>{t("progress", { done, total: steps.length })}</span>
        </div>
        <div
          className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-label={t("progressLabel")}
          aria-valuemin={0}
          aria-valuemax={steps.length}
          aria-valuenow={done}
        >
          <div className="h-full rounded-full bg-success transition-[width]" style={{ width: `${(done / steps.length) * 100}%` }} />
        </div>
      </div>
      <ol className="flex flex-col p-2">
        {steps.map((step) => {
          const isNext = next?.key === step.key;
          return (
            <li key={step.key}>
              <Link
                href={step.href}
                className={cn(
                  "group flex items-center gap-3 rounded-md px-2 py-2.5 transition-colors hover:bg-subtle",
                  isNext && "bg-subtle",
                )}
              >
                {step.done ? (
                  <CheckCircle2 className="size-4 shrink-0 text-success" aria-label={t("done")} />
                ) : (
                  <Circle className="size-4 shrink-0 text-fg-subtle" aria-hidden />
                )}
                <span className="min-w-0 flex-1">
                  <span className={cn("block text-sm font-medium", step.done ? "text-fg-muted line-through decoration-border-strong" : "text-fg")}>
                    {t(`steps.${step.key}.title`)}
                  </span>
                  {!step.done ? <span className="block text-xs text-fg-muted">{t(`steps.${step.key}.body`)}</span> : null}
                </span>
                {isNext ? (
                  <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-fg">
                    {t("go")}
                    <ArrowRight className="size-3.5" aria-hidden />
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
