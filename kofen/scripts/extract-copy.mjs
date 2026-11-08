#!/usr/bin/env node
/**
 * Extracts the site copy from the prototype's `T` and `X` objects into
 * messages/<locale>.json with meaningful, stable keys.
 *
 *   node scripts/extract-copy.mjs [path/to/kofen-landing-reference.html]
 *
 * The prototype is the source of truth for copy: strings are copied verbatim,
 * never rewritten. Only the key structure changes (terse prototype keys such as
 * `h1a`, `con.scen`, `dark.pillars` become `hero.headline`,
 * `console.scenarios`, `platform.pillars`, …).
 *
 * Namespaces that are NOT in the prototype (`ui`, `legal`) are authored by hand
 * in messages/<locale>.json; this script preserves them when it regenerates.
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(root, process.argv[2] ?? "../reference/kofen-landing-reference.html");
const html = readFileSync(source, "utf8");

/** Pull `const NAME = {...};` out of the prototype script and parse it as JSON. */
function readObject(name) {
  const start = html.indexOf(`const ${name} = {`);
  if (start < 0) throw new Error(`const ${name} not found in ${source}`);
  const open = html.indexOf("{", start);
  const end = html.indexOf("\n};", open);
  if (end < 0) throw new Error(`end of const ${name} not found`);
  return JSON.parse(html.slice(open, end + 2));
}

const T = readObject("T");
const X = readObject("X");

export const LOCALES = ["en", "es", "de", "fr", "it", "pt", "zh", "ar"];
const SCENARIO_IDS = ["tenders", "supplyRisk", "marginAudit"];
const PHASE_IDS = ["deploy", "scale", "run"];
const INDUSTRY_IDS = [
  "manufacturing",
  "logistics",
  "distribution",
  "financialServices",
  "healthcare",
  "construction",
  "publicSector",
];
const DEPTH_IDS = ["complexity", "control", "compounding"];
const FAQ_IDS = ["dataNotReady", "pilotsStalled", "noAiTeam", "gdprAiAct", "paidUpfront", "startSmaller"];
const CHIP_IDS = ["tenders", "supplyChain", "margin", "size"];
const STAT_IDS = ["diagnosticDays", "minimumReturn", "proposalDays", "ownSystems"];

const keyed = (ids, list, map) => {
  if (ids.length !== list.length) throw new Error(`expected ${ids.length} items, got ${list.length}`);
  return Object.fromEntries(ids.map((id, i) => [id, map(list[i], i)]));
};

function build(locale) {
  const t = T[locale];
  const x = X[locale];
  if (!t || !x) throw new Error(`locale ${locale} missing from T or X`);

  return {
    announcement: { text: t.ticker.text, link: t.ticker.link },
    nav: {
      deployment: t.nav.deploy,
      industries: t.nav.industries,
      engagement: t.nav.pricing,
      company: t.nav.company,
      cta: t.nav.cta,
    },
    hero: {
      headline: x.h1a,
      rotator: x.rot,
      sub: t.hero.sub,
      cta: t.hero.b1,
      emailPlaceholder: t.hero.email,
      // Present in the prototype copy but not rendered by it.
      unusedHeadline: t.hero.h1,
      unusedSecondaryCta: t.hero.b2,
    },
    console: {
      demoBadge: x.con.badge,
      hint: x.con.hint,
      group: x.con.group,
      agentsRunning: x.con.agentsOn,
      agentName: x.con.agent,
      working: x.con.working,
      approve: x.con.approve,
      play: x.con.play,
      pause: x.con.pause,
      scenarios: keyed(SCENARIO_IDS, x.con.scen, (s) => ({
        label: s.label,
        slug: s.url,
        from: s.from,
        subject: s.subj,
        body: s.body,
        steps: s.steps,
        reply: s.reply,
        fields: s.fields.map(([label, value]) => ({ label, value })),
        waiting: s.wait,
        done: s.done,
      })),
    },
    composer: {
      label: x.comp.label,
      placeholders: x.comp.phrases,
      chips: keyed(CHIP_IDS, x.comp.chips, ([label, text]) => ({ label, text })),
      send: x.comp.send,
      note: x.comp.note,
      emailSubject: x.comp.subject,
    },
    systems: { title: t.systemsTitle },
    manifesto: { lead: t.statement.pre, emphasis: t.statement.emph },
    platform: {
      title: t.dark.h2,
      pillars: t.dark.pillars.map(([title, body, cta]) => ({ title, body, cta })),
    },
    phases: {
      title: t.phases.h2,
      ledByKofen: t.phases.led,
      tab: t.phases.tab,
      items: keyed(PHASE_IDS, t.phases.items, ([title, kofenShare, body, chips]) => ({
        title,
        kofenShare,
        body,
        chips,
      })),
    },
    depth: {
      title: t.caps.h2,
      pillars: keyed(DEPTH_IDS, t.caps.items, ([label, title, body]) => ({ label, title, body })),
      stats: keyed(STAT_IDS, x.num, (label) => label),
    },
    industries: {
      title: t.ind.h2,
      cta: t.ind.btn,
      items: keyed(INDUSTRY_IDS, t.ind.items, ([name, useCases]) => ({ name, useCases })),
    },
    pricing: {
      title: t.pricing.h2,
      intro: t.pricing.p,
      plans: keyed(["diagnostic", "deployment"], t.pricing.plans, ([name, price, note]) => ({ name, price, note })),
      // Present in the prototype copy but not rendered (brief: no conditions list).
      unusedConditionsTitle: t.pricing.condHead,
      unusedConditions: t.pricing.conds,
    },
    faq: {
      title: x.faq.h2,
      items: keyed(FAQ_IDS, x.faq.items, ([question, answer]) => ({ question, answer })),
    },
    company: {
      title: t.closer.h2,
      body: t.closer.p,
      storyCard: t.closer.c1,
      positionsCard: t.closer.c2,
    },
    closing: { title: t.cta.h2, cta: t.cta.btn },
    footer: {
      tagline: t.footer.tagline,
      headings: {
        services: t.footer.heads[0],
        industries: t.footer.heads[1],
        company: t.footer.heads[2],
        legal: t.footer.heads[3],
      },
      services: { diagnostic: t.footer.services[0], deployment: t.footer.services[1], embeddedTeam: t.footer.services[2] },
      company: { whyKofen: t.footer.company[0], careers: t.footer.company[1], contact: t.footer.company[2] },
      legal: { notice: t.footer.legal[0], privacy: t.footer.legal[1], cookies: t.footer.legal[2] },
    },
  };
}

/** Flatten to "a.b.0.c" → type tag, so locales can be compared structurally. */
function shape(value, prefix = "", out = new Map()) {
  if (Array.isArray(value)) {
    out.set(prefix, `array(${value.length})`);
    value.forEach((v, i) => shape(v, `${prefix}.${i}`, out));
  } else if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) shape(v, prefix ? `${prefix}.${k}` : k, out);
  } else {
    out.set(prefix, typeof value);
  }
  return out;
}

const PRESERVED = ["ui", "legal"];
const built = Object.fromEntries(LOCALES.map((l) => [l, build(l)]));
const reference = shape(built.en);
let problems = 0;

for (const locale of LOCALES) {
  const file = resolve(root, "messages", `${locale}.json`);
  const previous = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};
  const next = { ...built[locale] };
  for (const ns of PRESERVED) if (previous[ns]) next[ns] = previous[ns];

  const s = shape(built[locale]);
  for (const [k, v] of reference) {
    if (s.get(k) !== v) {
      problems++;
      console.error(`[${locale}] ${k}: expected ${v}, got ${s.get(k) ?? "missing"}`);
    }
  }
  for (const k of s.keys()) if (!reference.has(k)) {
    problems++;
    console.error(`[${locale}] unexpected key ${k}`);
  }

  writeFileSync(file, JSON.stringify(next, null, 2) + "\n");
  console.log(`wrote messages/${locale}.json`);
}

if (problems) {
  console.error(`${problems} structural mismatch(es) between locales`);
  process.exit(1);
}
console.log("all locales share the same key structure");
