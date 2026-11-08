import { getTranslations } from "next-intl/server";
import type { Locale } from "@/i18n/routing";
import { getCopy } from "@/lib/copy";
import { site } from "@/lib/site";
import { ConsoleClient } from "./ConsoleClient";

/** Section 3: simulated product window on a dotted-grid frame (#try). */
export async function LiveConsole({ locale }: { locale: Locale }) {
  const copy = await getCopy(locale);
  const t = await getTranslations({ locale, namespace: "ui" });
  const c = copy.console;
  return (
    <section className="gutter-x pb-10 pt-24">
      <div className="mx-auto max-w-[var(--container)]" data-reveal="">
        <ConsoleClient
          copy={{
            demoBadge: c.demoBadge,
            hint: c.hint,
            group: c.group,
            agentsRunning: c.agentsRunning,
            agentName: c.agentName,
            working: c.working,
            approve: c.approve,
            play: c.play,
            pause: c.pause,
            scenarios: Object.values(c.scenarios),
          }}
          composer={{ ...copy.composer, chips: Object.values(copy.composer.chips) }}
          labels={{ scenarios: t("scenarios"), timeline: t("timeline") }}
          email={site.email}
        />
      </div>
    </section>
  );
}
