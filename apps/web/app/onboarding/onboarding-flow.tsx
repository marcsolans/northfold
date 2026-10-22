"use client";

import { Alert, Button, EmptyState, ErrorState, Field, Skeleton, Textarea, cn, inputClass } from "@messer/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Building2,
  CheckCircle2,
  Circle,
  CircleDashed,
  Database,
  LayoutTemplate,
  type LucideIcon,
  Plug,
  Sparkles,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { http } from "@/lib/api";
import { useMe } from "@/lib/hooks/use-me";
import {
  CHECKLIST_KEY,
  ONBOARDING_KEY,
  type OnboardingPatch,
  type OnboardingState,
  USE_CASES,
  type UseCase,
  WIZARD_STEPS,
  type WizardStep,
  isWizardStep,
} from "@/lib/onboarding";
import { hasRole } from "@/lib/types";

const STEP_ICONS: Record<WizardStep, LucideIcon> = {
  describe: Sparkles,
  template: LayoutTemplate,
  data: Database,
  test: Bot,
};

interface PlanSummary {
  id: string;
  name: string;
}

function stepDone(state: OnboardingState, key: WizardStep): boolean {
  return state.steps.find((s) => s.key === key)?.done ?? false;
}

function firstOpenStep(state: OnboardingState): WizardStep {
  return WIZARD_STEPS.find((key) => !stepDone(state, key) && !state.skipped_steps.includes(key)) ?? "test";
}

function ChoiceCard({
  icon: Icon,
  title,
  body,
  href,
  cta,
  primary,
}: {
  icon: LucideIcon;
  title: string;
  body: string;
  href: string;
  cta: string;
  primary?: boolean;
}) {
  return (
    <div className="flex flex-col rounded-md border border-border bg-surface p-4">
      <Icon className="size-4 text-fg" aria-hidden />
      <p className="mt-3 text-sm font-semibold text-fg">{title}</p>
      <p className="mt-1 flex-1 text-sm text-fg-muted">{body}</p>
      <Button asChild variant={primary ? "primary" : "secondary"} size="sm" className="mt-4 self-start">
        <Link href={href}>
          {cta}
          <ArrowRight />
        </Link>
      </Button>
    </div>
  );
}

function DoneNote({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <Alert tone="success" action={action}>
      <span className="flex items-center gap-2 text-fg">
        <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />
        {children}
      </span>
    </Alert>
  );
}

export function OnboardingFlow() {
  const t = useTranslations("onboarding");
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const me = useMe();
  const hasOrg = Boolean(me.data?.active_org);
  const canEdit = hasRole(me.data, "builder");

  const query = useQuery({
    queryKey: ONBOARDING_KEY,
    queryFn: () => http.get<OnboardingState>("/onboarding"),
    enabled: hasOrg,
  });
  const planId = params.get("plan");
  const plans = useQuery({
    queryKey: ["plans", "public"],
    queryFn: () => http.get<PlanSummary[]>("/plans"),
    enabled: Boolean(planId),
    staleTime: 300_000,
  });

  const [step, setStep] = React.useState<WizardStep | null>(() => {
    const fromUrl = params.get("step");
    return isWizardStep(fromUrl) ? fromUrl : null;
  });
  const [goal, setGoal] = React.useState<string | null>(null);
  const [useCase, setUseCase] = React.useState<UseCase | "" | null>(null);
  const [goalError, setGoalError] = React.useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (patch: OnboardingPatch) => http.patch<OnboardingState>("/onboarding", patch as Record<string, unknown>),
    onSuccess: (state) => {
      qc.setQueryData(ONBOARDING_KEY, state);
      void qc.invalidateQueries({ queryKey: CHECKLIST_KEY });
    },
  });

  if (me.isPending || (hasOrg && query.isPending)) {
    return (
      <div className="grid gap-6 md:grid-cols-[240px_1fr]" aria-busy>
        <div className="flex flex-col gap-2">
          {WIZARD_STEPS.map((key) => (
            <Skeleton key={key} className="h-11 w-full" />
          ))}
        </div>
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }
  if (me.isError || query.isError) {
    return (
      <ErrorState
        title={t("loadErrorTitle")}
        description={t("loadErrorBody")}
        retryLabel={t("retry")}
        onRetry={() => void (me.isError ? me.refetch() : query.refetch())}
      />
    );
  }
  if (!hasOrg || !query.data) {
    return (
      <EmptyState
        icon={<Building2 />}
        title={t("noOrgTitle")}
        description={t("noOrgBody")}
        action={
          <Button asChild variant="primary">
            <Link href="/app">{t("noOrgCta")}</Link>
          </Button>
        }
      />
    );
  }

  const state = query.data;
  const current: WizardStep = step ?? firstOpenStep(state);
  const index = WIZARD_STEPS.indexOf(current);
  const doneCount = WIZARD_STEPS.filter((key) => stepDone(state, key)).length;
  const goalValue = goal ?? state.goal ?? "";
  const useCaseValue = useCase ?? state.use_case ?? "";
  const selectedPlan = planId ? plans.data?.find((p) => p.id === planId) : undefined;

  const go = (key: WizardStep) => {
    setStep(key);
    const url = new URL(window.location.href);
    url.searchParams.set("step", key);
    router.replace(`${url.pathname}${url.search}`, { scroll: false });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const nextStep = () => {
    const next = WIZARD_STEPS[index + 1];
    if (next) go(next);
  };
  const save = async (patch: OnboardingPatch) => {
    try {
      await mutation.mutateAsync(patch);
      return true;
    } catch {
      return false;
    }
  };
  const skip = async () => {
    const skipped = Array.from(new Set([...state.skipped_steps, current]));
    if (canEdit && !(await save({ skipped_steps: skipped }))) return;
    if (index === WIZARD_STEPS.length - 1) router.push("/app");
    else nextStep();
  };
  const saveGoal = async () => {
    if (!goalValue.trim()) {
      setGoalError(t("steps.describe.required"));
      return;
    }
    setGoalError(null);
    const ok = await save({
      goal: goalValue.trim(),
      use_case: useCaseValue === "" ? null : useCaseValue,
      skipped_steps: state.skipped_steps.filter((s) => s !== "describe"),
    });
    if (ok) nextStep();
  };
  const finish = async () => {
    if (canEdit && !(await save({ completed: true }))) return;
    router.push("/app");
  };

  const composerHref = state.goal ? `/app?prompt=${encodeURIComponent(state.goal)}` : "/app";
  const agentHref = state.agent ? `/app/projects/${state.agent.project_id}/agents/${state.agent.id}` : null;

  return (
    <div className="flex flex-col gap-6">
      {planId && selectedPlan ? (
        <Alert
          tone="info"
          title={t("plan.title", { plan: selectedPlan.name })}
          action={
            planId !== "pro" ? (
              <Button asChild size="sm" variant="secondary">
                <Link href={`/app/settings/billing?plan=${encodeURIComponent(planId)}`}>{t("plan.cta")}</Link>
              </Button>
            ) : undefined
          }
        >
          {planId === "pro" ? t("plan.trialBody") : t("plan.body", { plan: selectedPlan.name })}
        </Alert>
      ) : null}
      {!canEdit ? <Alert tone="warning">{t("readOnly")}</Alert> : null}

      <div className="grid gap-6 md:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label={t("eyebrow")}>
          <p className="text-xs text-fg-subtle">{t("progress", { done: doneCount, total: WIZARD_STEPS.length })}</p>
          <ol className="mt-2 flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
            {WIZARD_STEPS.map((key, i) => {
              const done = stepDone(state, key);
              const skipped = !done && state.skipped_steps.includes(key);
              const active = key === current;
              const StatusIcon = done ? CheckCircle2 : skipped ? CircleDashed : Circle;
              return (
                <li key={key} className="shrink-0 md:shrink">
                  <button
                    type="button"
                    onClick={() => go(key)}
                    aria-current={active ? "step" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-md border px-3 py-2 text-left text-sm transition-colors",
                      active ? "border-border bg-surface font-medium text-fg" : "border-transparent text-fg-muted hover:bg-surface",
                    )}
                  >
                    <StatusIcon className={cn("size-4 shrink-0", done ? "text-success" : "text-fg-subtle")} aria-hidden />
                    <span className="min-w-0">
                      <span className="block whitespace-nowrap md:whitespace-normal">
                        {i + 1}. {t(`steps.${key}.nav`)}
                      </span>
                      <span className="sr-only">
                        {" "}
                        ({done ? t("status.done") : skipped ? t("status.skipped") : t("status.pending")})
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        <section className="rounded-md border border-border bg-surface" aria-labelledby="onboarding-step-title">
          <div className="border-b border-border px-5 py-4 sm:px-6">
            <p className="text-xs font-medium text-fg-subtle">{t("stepOf", { current: index + 1, total: WIZARD_STEPS.length })}</p>
            <h2 id="onboarding-step-title" className="mt-1 flex items-center gap-2 text-lg font-semibold text-fg">
              {React.createElement(STEP_ICONS[current], { className: "size-5 text-accent", "aria-hidden": true })}
              {t(`steps.${current}.title`)}
            </h2>
            <p className="mt-1 text-sm text-fg-muted">{t(`steps.${current}.body`)}</p>
          </div>

          <div className="flex flex-col gap-4 px-5 py-5 sm:px-6">
            {mutation.isError ? <Alert tone="danger">{t("saveError")}</Alert> : null}

            {current === "describe" ? (
              <>
                <Field label={t("steps.describe.label")} htmlFor="onboarding-goal" hint={t("steps.describe.hint")} error={goalError}>
                  <Textarea
                    id="onboarding-goal"
                    rows={5}
                    maxLength={2000}
                    value={goalValue}
                    disabled={!canEdit}
                    placeholder={t("steps.describe.placeholder")}
                    aria-invalid={Boolean(goalError)}
                    onChange={(e) => setGoal(e.target.value)}
                  />
                </Field>
                <div>
                  <p className="text-xs font-medium text-fg-subtle">{t("steps.describe.examplesTitle")}</p>
                  <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                    {(t.raw("steps.describe.examples") as string[]).map((example) => (
                      <li key={example}>
                        <button
                          type="button"
                          disabled={!canEdit}
                          onClick={() => {
                            setGoal(example);
                            setGoalError(null);
                          }}
                          className="h-full w-full rounded-md border border-border px-3 py-2 text-left text-sm text-fg-muted transition-colors hover:border-border-strong hover:bg-subtle hover:text-fg disabled:opacity-60"
                        >
                          {example}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
                <Field label={t("steps.describe.useCaseLabel")} htmlFor="onboarding-usecase">
                  <select
                    id="onboarding-usecase"
                    value={useCaseValue}
                    disabled={!canEdit}
                    onChange={(e) => setUseCase(e.target.value as UseCase | "")}
                    className={cn(inputClass, "appearance-auto sm:max-w-xs")}
                  >
                    <option value="">{t("steps.describe.useCaseNone")}</option>
                    {USE_CASES.map((key) => (
                      <option key={key} value={key}>
                        {t(`useCases.${key}`)}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            ) : null}

            {current === "template" ? (
              <>
                {state.project ? (
                  <DoneNote
                    action={
                      <Button asChild size="sm" variant="secondary">
                        <Link href={`/app/projects/${state.project.id}`}>{t("steps.template.openProject")}</Link>
                      </Button>
                    }
                  >
                    {t("steps.template.doneBody", { project: state.project.name })}
                  </DoneNote>
                ) : null}
                <div className="grid gap-3 sm:grid-cols-2">
                  <ChoiceCard
                    icon={LayoutTemplate}
                    title={t("steps.template.templateTitle")}
                    body={t("steps.template.templateBody")}
                    href="/app/templates"
                    cta={t("steps.template.templateCta")}
                  />
                  <ChoiceCard
                    icon={Sparkles}
                    title={t("steps.template.composerTitle")}
                    body={state.goal ? t("steps.template.composerBodyWithGoal") : t("steps.template.composerBody")}
                    href={composerHref}
                    cta={t("steps.template.composerCta")}
                    primary
                  />
                </div>
              </>
            ) : null}

            {current === "data" ? (
              <>
                {stepDone(state, "data") ? <DoneNote>{t("steps.data.doneBody")}</DoneNote> : null}
                <div className="grid gap-3 sm:grid-cols-2">
                  <ChoiceCard
                    icon={Upload}
                    title={t("steps.data.uploadTitle")}
                    body={t("steps.data.uploadBody")}
                    href="/app/knowledge"
                    cta={t("steps.data.uploadCta")}
                    primary
                  />
                  <ChoiceCard
                    icon={Plug}
                    title={t("steps.data.connectTitle")}
                    body={t("steps.data.connectBody")}
                    href="/app/connectors"
                    cta={t("steps.data.connectCta")}
                  />
                </div>
              </>
            ) : null}

            {current === "test" ? (
              <>
                {stepDone(state, "test") ? <DoneNote>{t("steps.test.doneBody")}</DoneNote> : null}
                {state.agent && agentHref ? (
                  <ChoiceCard
                    icon={Bot}
                    title={state.agent.name}
                    body={t("steps.test.body")}
                    href={agentHref}
                    cta={t("steps.test.cta", { agent: state.agent.name })}
                    primary
                  />
                ) : (
                  <EmptyState
                    icon={<Bot />}
                    title={t("steps.test.noAgent")}
                    action={
                      <Button variant="secondary" onClick={() => go("template")}>
                        {t("steps.test.noAgentCta")}
                      </Button>
                    }
                  />
                )}
              </>
            ) : null}
          </div>

          <div className="flex flex-col-reverse gap-2 border-t border-border bg-subtle px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div>
              {index > 0 ? (
                <Button variant="ghost" onClick={() => go(WIZARD_STEPS[index - 1] ?? "describe")}>
                  <ArrowLeft />
                  {t("back")}
                </Button>
              ) : null}
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              {!stepDone(state, current) ? (
                <Button variant="ghost" onClick={() => void skip()} disabled={mutation.isPending}>
                  {t("skip")}
                </Button>
              ) : null}
              {current === "describe" && canEdit ? (
                <Button variant="primary" loading={mutation.isPending} onClick={() => void saveGoal()}>
                  {t("saveContinue")}
                  <ArrowRight />
                </Button>
              ) : current === "test" ? (
                <Button variant="primary" loading={mutation.isPending} onClick={() => void finish()}>
                  {t("finish")}
                </Button>
              ) : (
                <Button variant="primary" onClick={nextStep}>
                  {t("continue")}
                  <ArrowRight />
                </Button>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
