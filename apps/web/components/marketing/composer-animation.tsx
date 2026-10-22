import { cn } from "@messer/ui";
import { Bot, Check, CircleDot, Database, GitBranch, LayoutPanelTop, Sparkles } from "lucide-react";
import { getTranslations } from "next-intl/server";

import styles from "./composer-animation.module.css";

const PLAN_ICONS = [Bot, GitBranch, Database, LayoutPanelTop] as const;
const BAR_CLASSES = [styles.bar1, styles.bar2, styles.bar3, styles.bar4, styles.bar5] as const;
const CHECK_CLASSES = [styles.check1, styles.check2, styles.check3, styles.check4, styles.check5] as const;
const STEP_CLASSES = [styles.step1, styles.step2, styles.step3, styles.step4, styles.step5] as const;
const STEP_KEYS = ["request", "questions", "plan", "builders", "deployed"] as const;

/**
 * The Composer flow (request → questions → plan → builders → deployed) in HTML/CSS: no video, no client JS.
 * Every element keeps its space, so the animation causes no layout shift; with reduced motion it is static.
 */
export async function ComposerAnimation() {
  const t = await getTranslations("marketing.composer");
  const planItems = t.raw("planItems") as { kind: string; name: string }[];
  const builders = t.raw("builders") as string[];

  return (
    <figure
      role="img"
      aria-label={t("label")}
      className="overflow-hidden rounded-md border border-border bg-surface text-left shadow-[0_1px_0_rgba(0,0,0,0.02)]"
    >
      <div className="flex h-9 items-center justify-between border-b border-border bg-subtle px-3" aria-hidden>
        <span className="flex items-center gap-1.5 text-xs font-medium text-fg-muted">
          <Sparkles className="size-3.5 text-accent" />
          {t("windowTitle")}
        </span>
        <span className="flex gap-1">
          <span className="size-2 rounded-full bg-border-strong" />
          <span className="size-2 rounded-full bg-border-strong" />
          <span className="size-2 rounded-full bg-border-strong" />
        </span>
      </div>

      <ol className="flex gap-1 overflow-hidden border-b border-border px-3 py-2" aria-hidden>
        {STEP_KEYS.map((key, i) => (
          <li
            key={key}
            className={cn(
              "flex min-w-0 items-center gap-1 whitespace-nowrap text-[11px] font-medium text-fg",
              STEP_CLASSES[i],
              i > 0 && "before:mr-1 before:text-fg-subtle before:content-['→']",
            )}
          >
            <span className="truncate">{t(`steps.${key}`)}</span>
          </li>
        ))}
      </ol>

      <div className="grid gap-3 p-3 sm:p-4 md:grid-cols-2" aria-hidden>
        <div className="flex flex-col gap-3">
          <div className={cn("rounded-md border border-border bg-subtle p-3", styles.request)}>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{t("you")}</p>
            <p className="mt-1 text-sm leading-relaxed text-fg">{t("request")}</p>
          </div>
          <div className="rounded-md border border-border p-3">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">
              <Sparkles className="size-3 text-accent" />
              {t("questionsTitle")}
            </p>
            <div className="mt-2 flex flex-col gap-2 text-sm">
              <p className={cn("text-fg", styles.q1)}>{t("q1")}</p>
              <p className={cn("self-end rounded-md bg-fg px-2 py-1 text-xs font-medium text-bg", styles.a1)}>{t("a1")}</p>
              <p className={cn("text-fg", styles.q2)}>{t("q2")}</p>
              <p className={cn("self-end rounded-md bg-fg px-2 py-1 text-xs font-medium text-bg", styles.a2)}>{t("a2")}</p>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <div className={cn("rounded-md border border-border p-3", styles.plan)}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-semibold text-fg">{t("planTitle")}</p>
              <span
                className={cn(
                  "whitespace-nowrap rounded-sm border border-accent bg-accent px-2 py-0.5 text-[11px] font-medium text-accent-fg",
                  styles.approve,
                )}
              >
                {t("approve")}
              </span>
            </div>
            <ul className="mt-2 flex flex-col gap-2">
              {planItems.map((item, i) => {
                const Icon = PLAN_ICONS[i % PLAN_ICONS.length] ?? Bot;
                return (
                  <li key={item.name} className="flex items-start gap-2">
                    <Icon className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
                    <span className="min-w-0">
                      <span className="block text-[10px] font-semibold uppercase tracking-wide text-fg-subtle">
                        {item.kind}
                      </span>
                      <span className="block text-xs leading-snug text-fg">{item.name}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className={cn("rounded-md border border-border p-3", styles.builders)}>
            <p className="text-sm font-semibold text-fg">{t("buildersTitle")}</p>
            <ul className="mt-2 flex flex-col gap-2">
              {builders.map((name, i) => (
                <li key={name} className="grid grid-cols-[minmax(0,1fr)_4.5rem_0.875rem] items-center gap-2 text-xs">
                  <span className="truncate text-fg-muted">{name}</span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <span className={cn("block h-full w-full rounded-full bg-fg", styles.bar, BAR_CLASSES[i % 5])} />
                  </span>
                  <Check className={cn("size-3.5 text-success", CHECK_CLASSES[i % 5])} />
                </li>
              ))}
            </ul>
          </div>

          <div
            className={cn(
              "flex items-center gap-2 rounded-md border border-success/25 bg-success-soft px-3 py-2",
              styles.deployed,
            )}
          >
            <CircleDot className="size-4 shrink-0 text-success" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-fg">{t("deployedTitle")}</p>
              <p className="font-mono text-[11px] text-fg-muted">{t("deployedMeta")}</p>
            </div>
          </div>
        </div>
      </div>
    </figure>
  );
}
