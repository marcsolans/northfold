# Kofen web

Production marketing site for Kofen: forward-deployed engineers and AI agents for complex operations (Barcelona / San Francisco).

- **Stack:** Next.js 16 (App Router, TypeScript), Tailwind CSS 4, next-intl 4, Motion. No UI kit.
- **Locales:** `en` (default), `es`, `de`, `fr`, `it`, `pt`, `zh`, `ar` (RTL). Every URL carries its locale (`/en`, `/es`…); `/` redirects by `Accept-Language` (or the visitor's last choice), falling back to `en`.
- **Rendering:** fully static (SSG). The only server code is the locale proxy and `POST /api/lead`.
- **Source of truth:** `../reference/kofen-landing-reference.html` (prototype: structure, copy, behaviour) and `../reference/site-teardown__2_.md` (design system).

## Run

Requires Node 20.9+ (developed on Node 22) and npm.

```bash
npm install
npm run dev          # http://localhost:3000 → redirects to /en
```

`predev` / `prebuild` copy the self-hosted zh/ar fonts into `public/fonts/` (generated, gitignored).

## Build and check

```bash
npm run build && npm start   # production build on http://localhost:3000
npm run lint
npm run typecheck
npm run test:e2e             # Playwright against the production build (starts `next start` on :3100 if needed)
```

The Playwright suite (`tests/e2e`) checks en/es/ar at 390, 768, 1024 and 1440px (lang/dir, every section, no horizontal overflow, all reveals fire) and saves full-page screenshots to `artifacts/screenshots/`. It also covers the console autoplay and controls, the industries rail in LTR and RTL, phases autoplay, the language listbox, the mobile menu, the FAQ, form validation and mailto fallback, reduced motion, and no-JS rendering. It uses the Chromium that ships with Playwright 1.63 (`npx playwright install chromium` on a new machine).

## Deploy to Vercel

1. Import the GitHub repository in Vercel.
2. **Root Directory:** `kofen` (the site lives in this folder of the repository). Framework preset: Next.js. Build command and output stay at their defaults.
3. Set the environment variables below for Production (and Preview if you want working forms there).
4. Add the domain (`kofen.ai`, placeholder) under Project → Domains and set `NEXT_PUBLIC_SITE_URL` to match.

The build fetches Geist subsets from Google Fonts for the Open Graph images (and Noto Sans SC for `/zh`). If that request fails, the cards fall back to the default font.

## Environment variables

Copy `.env.example` to `.env.local` for local work. All are optional; without them the site works and the forms fall back to `mailto:`.

| Variable | Purpose | Default |
| --- | --- | --- |
| `RESEND_API_KEY` | Sends lead emails through [Resend](https://resend.com). Without it, `/api/lead` answers `503 { fallback: "mailto" }` and the form opens the visitor's mail app. | unset |
| `RESEND_FROM` | Sender address. Must be on a domain verified in Resend, e.g. `Kofen <web@kofen.ai>`. | `Kofen website <onboarding@resend.dev>` (Resend test sender: only delivers to your own Resend account address) |
| `LEAD_TO` | Inbox that receives leads. | `NEXT_PUBLIC_CONTACT_EMAIL` |
| `NEXT_PUBLIC_SITE_URL` | Canonical URLs, hreflang, sitemap, Open Graph. | `https://kofen.ai` |
| `NEXT_PUBLIC_CONTACT_EMAIL` | Public address on the site and in mailto links. | `hello@kofen.ai` |

`NEXT_PUBLIC_*` values are inlined at build time: redeploy after changing them.

### Lead form

`POST /api/lead` (`app/api/lead/route.ts`) accepts JSON from the enhanced forms or a normal form post when JS is off. It:

- validates the email;
- rejects cross-origin posts;
- silently drops submissions that fill the honeypot field (`website`);
- limits each IP to 5 requests per 10 minutes, in memory per server instance (`lib/server/rateLimit.ts`; swap for a shared store such as Upstash if needed);
- emails `LEAD_TO` with `reply_to` set to the visitor.

The console composer ("Request a proposal") has no email field, so it opens a prefilled email, as in the prototype.

## Where to edit things

| What | Where |
| --- | --- |
| **All copy** (8 languages) | `messages/<locale>.json`. Keys follow the page order: `announcement`, `nav`, `hero`, `console`, `composer`, `systems`, `manifesto`, `platform`, `phases`, `depth`, `industries`, `pricing`, `faq`, `company`, `closing`, `footer`. |
| **Prices** | `messages/<locale>.json` → `pricing.plans.diagnostic.price` and `pricing.plans.deployment.price` (one per locale, already in each locale's number format), with the matching `note`. |
| UI strings not in the prototype | `messages/<locale>.json` → `ui` (form messages, menu/language/slider labels, 404). Authored for this build: please review. |
| Domain, contact email | Environment variables above (defaults in `lib/site.ts`). |
| Legal pages | `content/legal.ts` (Spanish reference text + English). Fill every `[TO COMPLETE: …]`, then set `LEGAL_READY = true` in `lib/legal.ts` to make them indexable and add them to the sitemap. |
| "Our story" / "Open positions" targets | `lib/site.ts` → `links` (no pages yet: `#company` and a prefilled careers email). |
| Systems marquee | `lib/systems.ts` |
| Stat values (7 · 5× · 2 · 100%) | `components/sections/depth/Depth.tsx` → `STAT_VALUES` (labels are in `messages`). |
| Console orbit chips | `components/sections/console/ConsoleClient.tsx` → `ORBIT` |
| Design tokens | `app/globals.css` → `@theme` (palette, easings, shadows) and `:root` (container, gutter, gradients, type scale). |

### Re-extracting copy from the prototype

`npm run copy:extract` rebuilds `messages/*.json` from the prototype's `T` and `X` objects, keeping the hand-written `ui` and `legal` namespaces. **It overwrites every other key**, so once you have edited copy in `messages/`, edit there and stop re-extracting. The script fails if the locales stop sharing one key structure.

Three prototype keys are extracted but not rendered: `hero.unusedHeadline`, `hero.unusedSecondaryCta` and `pricing.unusedConditions*` (the brief drops the conditions list).

## Project structure

```
app/
  layout.tsx, not-found.tsx       pass-through root + 404 for non-locale paths
  [locale]/layout.tsx             <html lang dir>, fonts, metadata base, reveal controller
  [locale]/page.tsx               the single page (sections in order) + JSON-LD
  [locale]/legal/[page]/page.tsx  notice, privacy, cookies
  [locale]/opengraph-image.tsx    OG/Twitter card per locale (next/og)
  api/lead/route.ts               lead endpoint
  sitemap.ts, robots.ts, icon.svg, apple-icon.tsx
components/
  layout/      Header (announcement + NavBar), Footer
  sections/    Hero, LiveConsole, SystemsStrip, Manifesto, Platform, Phases, Depth,
               Industries, Pricing, Faq, Company, ClosingCta
  ui/          primitives (ArrowBox, ButtonLink, Eyebrow, TwoToneHeading…), EmailForm, LanguageSelect
  system/      RevealController
content/legal.ts   legal page drafts
i18n/              routing, request config, navigation helpers
lib/               copy access, site config, SEO helpers, fonts, lattice data, server utils
messages/          copy, one file per locale
proxy.ts           next-intl locale detection and redirects
scripts/           extract-copy.mjs, copy-script-fonts.mjs
tests/e2e/         Playwright specs
```

## Behaviour notes

- **Scroll reveals** (opacity 0 / translateY 16px → visible, 600ms out-soft, once). The server HTML is always visible; only elements below the fold are hidden, after hydration.
- **Reduced motion:**
  - no console, phases or lattice autoplay, and no rotator;
  - the marquee and orbit lights stand still;
  - counters stay at their final values and swaps are instant.
  - The console rests on scenario 1, approved.
- **Without JS:**
  - all content renders, the console in its approved state;
  - FAQ answers are expanded;
  - the email forms post normally to `/api/lead`.
- **Single clocks:**
  - the console runs on one `requestAnimationFrame` loop, only while it is on screen and the tab is visible;
  - the phases autoplay and the hero lattice pause off-screen too.
- **Fonts:**
  - Geist and Geist Mono via `next/font`;
  - Noto Sans SC and Noto Sans Arabic are self-hosted stylesheets linked only on `/zh` and `/ar`. Through `next/font` they would have added about 186 KB of render-blocking CSS to every locale.
- **Cookies:** only `NEXT_LOCALE` (first-party session cookie set by next-intl to remember the language), so there is no consent banner. Add one if analytics are ever added.

## Quality (production build, Lighthouse 13, mobile)

| Page | Performance | Accessibility | Best Practices | SEO |
| --- | --- | --- | --- | --- |
| `/en` | 97–99 | 100 | 100 | 100 |
| `/es` | 97 | 100 | 100 | 100 |
| `/ar` | 97 | 100 | 100 | 100 |
| `/zh` | 96 | 100 | 100 | 100 |

LCP 0.9–1.2s and CLS 0. The counters and phrase rotator reserve their final size, and the console reserves the height of its longest scene, so nothing shifts.

## Placeholders to confirm

- Domain `kofen.ai` and address `hello@kofen.ai` (env vars).
- Prices: `messages/*/pricing.plans`.
- Legal entity data and policy details: every `[TO COMPLETE]` in `content/legal.ts`.
- Authored `ui` strings in all 8 languages.
- The diagram labels, the "FAQ" eyebrow and "Barcelona / San Francisco" are English in every locale, as in the prototype.

## Known limitations

- **Arabic Open Graph card** uses the English headline: `next/og` cannot shape Arabic script.
- **Unknown URLs** return 404 with `noindex`. Next.js 16 renders the localized 404 content on the client, so a visitor without JS sees an empty page there.
- **Rate limit** is per server instance and resets on cold starts.
