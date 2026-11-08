# Reference-site teardown: structure, motion, interaction & design system

**Subject:** the public marketing site of an enterprise AI-agent platform (analysed live in Chrome, 8 Nov 2026, desktop viewport 1126×710 plus iframe-emulated 390 / 768 / 1024 / 1440).
**Purpose:** rebuild a site with the same polish and dynamism under your own brand. No copy, logos or imagery are reproduced here — every text slot is described and rewritten with placeholders (`[BRAND]`, `[PRODUCT]`, `[CLIENT]`, `[PERSON]`, `[FIGURE]`, `[INDUSTRY]`).
**Method:** DOM walking, `getComputedStyle`, CSSOM rule extraction (keyframes, media queries), `document.getAnimations()`, rAF sampling of scroll-linked values, live hover/click tests, GIF capture. Forms were focused but never filled or submitted; cookies were declined via the consent panel.

> Naming used below: the platform's four-layer pyramid diagram is called **"Layer Diamond"** (the site's own name for its top layer is a product name, replaced here by `[PRODUCT-PRISMA]` where needed).

---

## Contents
1. Sitemap
2. Interactive & animated components (detailed)
3. Reconstruction recipes (code)
4. Design tokens (CSS)
5. Responsive behaviour
6. Pages one by one (structure + copy slots + rewrites)
7. Tech stack
8. GIFs recorded
9. Decisions taken autonomously

---

# 1. Sitemap

```
/                                   Home
├── Announcement bar → /blog/<series-c-announcement>      (blog article)
├── PLATFORM (mega menu)
│   ├── /product/platform-overview             Platform overview
│   ├── /prisma                                Top-layer orchestration product ("[PRODUCT-PRISMA]")
│   ├── /product/esi                           Vision page ("Enterprise Superintelligence")
│   ├── Agents
│   │   ├── /product/agents/agents-overview
│   │   ├── /product/agents/workflow-logic     (chip: Workflows)
│   │   ├── /product/agents/voice-ai           (chip: Conversational AI)
│   │   ├── /product/agents/signals            (chip: Reasoning agents)
│   │   └── /product/agents/scalability        (chip: Scalability)
│   ├── Performance
│   │   ├── /product/governance                (overview)
│   │   ├── /product/governance/northstars
│   │   ├── /product/governance/audits-and-tests   (chip: Tests)
│   │   ├── /product/governance/audits
│   │   └── /product/governance/wayfinder      (chip: Self-improving agents)
│   ├── Context
│   │   ├── /product/context/context-overview
│   │   ├── /product/context/memory
│   │   ├── /product/context/edge
│   │   └── /product/context/external-systems
│   ├── /product/interfaces                    Interfaces
│   ├── /product/security-and-reliability      Security & reliability
│   └── /product/developer-tools               Developer tools
├── SOLUTIONS (mega menu)
│   ├── By industry (8)
│   │   ├── /solutions/industries/logistics-providers
│   │   ├── /solutions/industries/utilities
│   │   ├── /solutions/industries/airlines
│   │   ├── /solutions/industries/financial-services
│   │   ├── /solutions/industries/insurance
│   │   ├── /solutions/industries/manufacturers-suppliers
│   │   ├── /solutions/industries/retail
│   │   └── /solutions/industries/telecom
│   └── By function (5)
│       ├── /solutions/functions/customer-support
│       ├── /solutions/functions/sales
│       ├── /solutions/functions/finance
│       ├── /solutions/functions/operations
│       └── /solutions/functions/hr-recruiting
├── COMPANY
│   ├── /customers                              Customers listing (11 stories)
│   │   └── /customer-story/<slug>              e.g. dhl, naturgy, kuehne-nagel, cma-cgm-…, mode, wwex, circle, encompass, werner, habitissimo, primera-plus
│   ├── /press                                  Newsroom
│   ├── /hub                                    SEO content hub (84 articles, filterable)
│   ├── /careers                                Careers (values, offices globe, open roles)
│   ├── /blog                                   Blog listing (29 posts, filterable)
│   │   └── /blog/<slug>                        Article template (incl. /blog/<media-kit>)
│   └── trust.<domain> (external)               Trust center
├── CONNECT
│   ├── /contact                                Contact form
│   ├── /contact/demo                           Book-a-demo (standalone, multi-step form)
│   ├── LinkedIn, X (external)
│   └── /#newsletter                            Newsletter anchor
└── LEGAL
    ├── /legal/terms-and-conditions
    ├── /legal/privacy-policy                   (analysed as template)
    ├── /legal/cookie-policy
    └── "Consent Preferences" → opens consent-manager modal (not a page)
```

**Global chrome present on every page:** fixed header (announcement bar on the homepage only), footer with 4 link columns + brand statement + policies + compliance chips + language selector. `/contact/demo` drops the footer and uses a split layout.

---

# 2. Interactive & animated components

Global motion vocabulary (extracted from CSS):

| Token | Value | Used for |
|---|---|---|
| `--ease-brand` | `cubic-bezier(0.33, 0, 0.15, 1)` | nearly every hover/transition (nav underline, menu height, arrow swap, captions, logo cells) |
| `--ease-inout` | `cubic-bezier(0.65, 0, 0.35, 1)` | hero grid line drawing, underline sweep keyframe |
| `--ease-out-soft` | `cubic-bezier(0.22, 1, 0.36, 1)` | FAQ accordion, scroll reveals |
| Durations | 120–140 ms (border draw segments), 280 ms (crossfade), 300 ms (captions/accordion rows), 350 ms (buttons, hover-dim), 420 ms (mega-menu height), 450 ms (blur), 500 ms (FAQ), 600 ms (image zoom, reveals, underline sweep) | |
| Reduced motion | every keyframe/transition is wrapped in `@media (prefers-reduced-motion: no-preference)` or neutralised with `motion-reduce:transition-none`; the animated logo swaps to a still image | |

Corners are **square everywhere** (no border-radius on buttons, cards, inputs, images). Elevation is almost absent (only dropdowns/popup use a soft `shadow-lg`). Depth is created with 1-px hairlines, flat tonal surfaces and photography.

---

## 2.1 Announcement bar (homepage only)

- **Layout:** full-width strip, background `#2e2e2e` (carbon), 1-px bottom border; inner `<a>` is the whole bar, max-width 1440, centred flex, gap 14 px, padding 9 px 20 px (48 px ≥768). Text: mono 11 px, uppercase, letter-spacing 0.04em, colour `#f2f2f2`. Height 36 px.
- **"New" badge:** not a pill — a **6×6 px square** in rust `#d59566` followed by the word "NEW". The square runs `hr-blink`: opacity 1 → 0.2 → 1, **2.4 s ease-in-out infinite**.
- **Copy variants:** long sentence ≥640 px (`hidden sm:inline`), a shorter em-dash version below 640 px (`sm:hidden`). A trailing "Read the announcement" + arrow is shown only ≥768 px (`md:inline-flex`).
- **Hover:** whole bar `opacity: .7` (transition-opacity, default 150 ms).
- **Dismiss:** none. It scrolls with the fixed header (it is inside the fixed wrapper) and stays visible.
- **A11y:** plain link; the blinking square is decorative.

## 2.2 Header / navigation

- **Structure:** `div.fixed.inset-x-0.top-0.z-[60]` containing the announcement bar and `<nav>`. Nav inner: max-width 1440, padding 12 px 20 px (48 px ≥768), height 68 px.
- **Logo:** 128×20 box containing an **animated WebP loop** (`<picture><source media="(prefers-reduced-motion: no-preference)" srcset="logo-loop.webp"><img src="logo-still.webp">`). The loop "types" the wordmark: the mark dissolves into pixel blocks, letters appear one by one, then it resolves into the full wordmark (visible as partial "Happ…", "…ot", pixel squares in screenshots). Under reduced motion the still image shows. In light sections a CSS filter inverts it (`--wordmark-filter: invert(1)`).
- **Desktop links (≥1024):** Suisse 11 px, uppercase, ls 0.12em, colour ink-1. Two `<button>`s (Platform, Solutions) with chevrons + three links. Each label has an **underline wipe**: a 1-px `span` absolutely positioned at `bottom:-4px`, `scale-x-0 origin-right` → on hover `scale-x-100 origin-left`, **300 ms cubic-bezier(.33,0,.15,1)** — it grows left→right on enter and retracts towards the right on leave.
- **Hover-dim group:** the link group carries `.hover-dim`: when any link is hovered, siblings fade to **opacity .4** (`:has(a:hover)` selector), 350 ms brand ease. Same class on the footer.
- **CTA:** solid black button "Book a demo" with a square 18-px icon box containing an arrow (see 2.5 arrow swap).
- **Sticky behaviour:** always fixed, never hides. On the homepage, while the hero is under the nav, the nav gets an **inline background identical to the hero gradient** so header and hero read as one surface; once the hero has scrolled past (~600 px at 710 px viewport) the inline style switches to `background: var(--surface)` (solid white). Swap is instant (no transition). On inner pages the nav is solid white from the start and there is no announcement bar.
- **Mobile (<1024):** links hidden; a compact "Book a demo" button + hamburger (two 1-px lines, `aria-label="Open menu"` → "Close menu", X icon). See 2.4.

## 2.3 Mega menus (Platform / Solutions)

- **Trigger:** **hover OR click.** `mouseenter` opens immediately; leaving both trigger and panel starts closing after **~150 ms** grace; click toggles; **Escape closes**. Buttons expose `aria-haspopup="true"` + `aria-expanded`. Panel has no `role`/`aria-controls` (improve this in your build).
- **One shared panel:** `div.absolute.inset-x-0.top-full.overflow-hidden.bg-surface` animating **`height` from 0 to the measured content height (336 px Platform / 317 px Solutions) in 420 ms cubic-bezier(.33,0,.15,1)** via inline `style="height:…px"`. Inside, both menus are stacked absolutely; the inactive one is `opacity:0; pointer-events:none`, **cross-fade 280 ms**. Switching from Platform to Solutions therefore morphs the height and cross-fades content without closing.
- **Platform panel layout:** top row — large link "Platform Overview →" (20 px) + two bulleted secondary links (small square bullet) for the orchestration product and the vision page; hairline divider; grid `repeat(4, minmax(0,216px))` gap 40/32: four columns (Agents / Performance / Context / Interfaces) each with a heading link, a muted one-line descriptor, and **chips**; a right column separated by a vertical hairline with two arrow links (Security & reliability, Developer tools).
- **Chips (`.chip-draw`):** 1-px border, 11.5 px text, padding 4×10. Hover draws a **rust border around the chip in four sequential strokes**: `::before` draws top (width 0→100 %, 140 ms linear) then right (height, 140 ms, delay 140 ms); `::after` draws bottom (delay 280 ms) then left (delay 420 ms). Total 560 ms. On leave it retracts in 120 ms. Text darkens.
- **Solutions panel layout:** two lists with mono uppercase captions ("By industry" in 2 columns × 4, "By function" 1 column × 5), plus a **promo card** on the right (1-px border box, mono eyebrow, 20-px headline, 13-px paragraph). Each list item gets the underline sweep keyframe on hover: `hr-underline-sweep` 600 ms cubic-bezier(.65,0,.35,1) — the underline retracts to the right then redraws from the left. The promo card is static (does not change with hovered item).
- **Hover-dim** applies inside panels too.

## 2.4 Mobile menu

- Hamburger toggles `aria-expanded`. A `grid` wrapper transitions **`grid-template-rows: 0fr → 1fr` in 300 ms brand ease** (`lg:hidden`). The inner scroller has `max-height: calc(100svh − header)` (inline, e.g. 586 px), `overflow-y:auto; overscroll-behavior:contain`.
- Items: 13 px uppercase rows with bottom hairlines (Platform ▾, Solutions ▾, Customers, Newsroom, Careers). Platform/Solutions are **nested accordions** using the same 0fr→1fr technique + opacity (300 ms). Inside: big arrow links, then the same chip groups as desktop.
- The page behind is not dimmed; the panel simply pushes down under the fixed header.

## 2.5 Buttons & links

- **Primary (solid):** black bg / white text in light sections (tokens `--cta-solid-bg/fg` flip in dark sections). Mono 11 px uppercase ls 0.01em, padding 13 px 12 px 13 px 20 px, gap 12 px, `active:scale(.98)`, `focus-visible: outline 2px rust, offset 2px`, transitions 350 ms brand ease.
- **Arrow swap icon:** a bordered square (18 px in buttons, 27 px on image cards) with `overflow:hidden`; inside, a wrapper rotated **−45°** holds two identical 9-px arrows. Arrow A sits centred; arrow B waits at `translateX(-24px)` (in rotated space = bottom-left). On hover A moves to `translateX(24px)` (exits top-right) and B moves to 0 — **350 ms cubic-bezier(.33,0,.15,1)**. Net effect: a "↗" that shoots out and is replaced. Some buttons use an un-rotated "→" variant.
- **Secondary (ghost) button:** light grey `#f2f2f2`-ish fill, mono uppercase, same arrow box (used in feature sections: "Explore …").
- **Inline text link with arrow:** "Read more →", "Learn more →": 14–15 px, arrow nudges right on hover.

## 2.6 Hero (homepage)

- **Section:** `height: 100svh; min-height: 680px; overflow:hidden`, background `linear-gradient(98deg, color-mix(stone 46%, white) 0%, color-mix(stone 18%, white) 48%, white 100%)` → `#dedad5 → #f2f0ee → #fff`.
- **Headline:** H1 with transparent text and `background-clip:text`. Default gradient 105° obsidian → carbon → concrete. On ≥1024 the class `.title-glow` replaces it by a **repeating-linear-gradient whose stop positions follow the pointer**: JS writes `--hero-gx: <pointer x relative to the H1>px` on `pointermove`, CSS uses `repeating-linear-gradient(105deg, #070707 var(--hero-gx), #736f6a calc(var(--hero-gx)+60%), #070707 calc(var(--hero-gx)+120%))`. Moving the mouse sweeps a soft grey "sheen" across the letters. No entrance animation on the text (it is visible at first paint; SSR).
- **Sizes:** 44 → 64 (md) → 76 (lg) → `clamp(84px, 5.95vw, 112px)` (xl). Line-height 1.04, letter-spacing −0.055em, max-width 11.5em, extra padding/negative margins (±0.1–0.14em) so descenders aren't clipped by background-clip.
- **Inline email form:** `<form noValidate>`; visually-hidden label; `input[type=email][required]` (14 px, padding 13×16, 1-px border `--border-cta` (= stone in light), transparent bg on lg, focus → border stone, no outline ring), followed by the primary button flush right (no gap, input has `border-right:0` ≥640). Below 640 px they stack: full-width input then full-width button. Validation is handled in JS (noValidate), so no native bubbles; submission goes to the demo flow (not triggered during the audit). Autofill styling neutralised (`.autofill` class).
- **Sub-headline:** 20 px / 1.4, colour carbon, max ~2 lines.
- **Background visual — the animated grid ("hero grid"):** an inline **SVG** (no canvas/WebGL/video), `viewBox="0 0 1600 800"`, `preserveAspectRatio="xMinYMin slice"`, absolutely positioned (`inset:0` with a left offset `var(--hg-left)` on desktop, `bottom:-14.29%`), masked by two gradients (left fade 0→240 px and top fade 8 %→30 %) composited with `mask-composite: intersect`; opacity .75 mobile → 1 desktop.
  - Geometry: a 100-unit cell lattice. Elements are `path`s with `pathLength="1"`, `stroke-dasharray:1`, stroke obsidian, width .5, `stroke-opacity:.1`: vertical stubs (`M100,0V300`), square cells (`M300,100h100v100h-100Z`) and a few cubic S-curves connecting cells (`M200,600 L200,606 C… 300,693 L300,700`).
  - Three "scenes" (A, B, C) of ~20 cells each + shared lines (AB, BC, ABC) + **3 photo tiles per scene** (`<image>` 100×100, `preserveAspectRatio="xMidYMid slice"`).
  - **Timing:** one 18 s infinite cycle, 6 s per scene. Per element: line draws (`stroke-dashoffset 1→0`) during 0–1.6 s, holds to 5 s, fades out 5–6 s, then resets invisibly. Photos fade in 0.5→1.7 s, hold, fade out 5–6 s. Scene B keyframes are the same shifted by 33.333 %, C by 66.667 %. Shared AB lines stay drawn across A+B (fade at 66.6 %), BC across B+C. ABC lines draw once (`hg-intro`, 1.6 s) and stay.
  - **Stagger:** each element has `--hg-delay = 0.06 s × (column + row)` → the grid "unfolds" diagonally from the top-left.
  - **Easing:** cubic-bezier(.65,0,.35,1). Animations are `paused` until JS sets `<html data-hero-ready>` (after first images decode) → `animation-play-state: running`.
  - Photos at opacity .14 below 1024 (texture only), 1 on desktop.
  - Reduced motion: no animation is declared, so the static first scene shows.

## 2.7 Customer story cards ("proof" section)

- **Header row:** H2 with a two-tone ending (last two words in concrete grey) + right-aligned mono link "Customers [→]". Reveal: opacity 0/translateY 16 → 1/0.
- **Grid:** 2 columns (<1024, gap 12/40; md 24/56) → 4 columns ≥1024. Not a carousel.
- **Card = one `<a class="group">`:**
  - Square image (aspect 1:1, bg cell colour while loading), `object-cover`, **hover zoom `scale(1.04)` in 600 ms brand ease**.
  - Bottom gradient overlay `linear-gradient(transparent 52%, rgba(7,7,7,.62))`.
  - Bottom-left: client logo rendered as a **CSS mask** (`background: currentColor; mask: url(logo.svg) center/100% no-repeat`, white) at 84×18 → 136×28 (md), then a visually-hidden "Read story" label, then the 27-px bordered **arrow-swap box** (↗).
  - One card has a **hover video**: `<video muted loop playsinline preload="none" class="opacity-0 transition-opacity duration-300 data-[playing]:opacity-100">`. On `pointerenter` JS calls `play()`; when playback starts it sets `data-playing` → 300 ms fade over the still. (Loop 13.5 s.) On leave it pauses and the attribute is removed.
  - Below image: category (mono 10→11 px, uppercase, ls 0.18em, ink-3) and metric line (19 → 26 (md) → 24 (lg) → 30 (xl) px, lh 1.06, ls −0.025em, max-width 8.4em, `&nbsp;` before last word to avoid widows).
- **"Read story" appearance:** there is no hover-revealed text — the CTA is the arrow box that is always visible; the hover feedback is the photo zoom + arrow swap.

## 2.8 Customer logo wall

- **Not a marquee** on the homepage (the marquee keyframe is used on the demo page). It is a **hairline grid**: `display:grid; gap:1px; background: var(--line)` with `ring-1` — the 1-px gaps reveal the background as grid lines. Columns: 3 (<768) / 5 (md) / 7 (lg); 25 cells exist, 21 visible at 7 columns; on mobile each cell reorders with `order: var(--po)` (custom per-cell order) and resets to source order at md.
- **Cells:** square, centred logo drawn as a **mask** over a solid colour (`background-color: var(--lw-ink)` = concrete; `mask: var(--lw-src) center / var(--lw-fit) no-repeat`), so every logo is monochrome and recolourable.
- **Hover:** cell bg → carbon `#2e2e2e`, logo colour → surface (white), both **280 ms**. Cells with a case study are `<a>` and show a bottom label "CASE STUDY ↗" in mono 9 px, ls 0.12em, rust-deep `#b06a38`.
- Unused-but-shipped CSS for a "story" variant: blurred photo (blur 24 px → 3.5 px on hover, 450 ms) with a sharp copy masked by a radial gradient following the pointer (`--mx/--my`). Worth reusing.

## 2.9 Platform section + Layer Diamond (scroll-linked)

- **Section:** bg `#f2f2f2` (signal), top border warm grey. Grid `minmax(0,502fr) / …` 2 columns ≥1024 with `min-height:160vh` (creates the scroll runway). Left: H2, black button "Platform overview", then **three pillar rows** (16 px title + 14 px muted description, 26 px vertical padding, top hairlines). The rows are static (no hover link to the diagram).
- **Diagram container:** `lg:sticky; top: max(5.5rem, calc(50vh − 324px))`, width `min(647px, (100svh − 8rem) × 1.061)`. Pinned while the left column scrolls.
- **Construction:** inline SVG, `viewBox="56 56 488 488"`, centre (300,300). 4 `<polygon>` fills, a `<g stroke=obsidian fill=none>` with outer edges split into **8 half-edges** grouped in 4 `<g>` (one per side, so a side can be faded independently), inner-diamond edges, 4 "spokes", one dashed edge (`stroke-dasharray:3 3`), and 20 `<text>` labels. All coordinates are recomputed by JS every frame (React state) from scroll progress.
- **Final geometry:** outer diamond radius 230 (vertices (300,70),(530,300),(300,530),(70,300)); inner diamond radius 76 (vertices (300,224),(376,300),(300,376),(224,300)); spokes join each inner vertex to the matching outer vertex. Quadrants: top-left = carbon `#2e2e2e` (Performance, white labels); top-right = concrete `#736f6a` (Interfaces, white label); bottom-right = stone `#b8aea4` (Context, dark labels); centre = white (Agents); bottom-left = **left empty**, outlined with a dashed outer edge and dashed vertical spoke (external integrations — "outside the system"). A dotted vertical leader runs from the top-right label block (product name + 2-line descriptor) down to the Interfaces quadrant.
- **Labels:** large caps 10.5 px (rendered), ls 0.02em; sub-items 7.4 px; Performance items right-aligned above their caption; Agents/Context items left-aligned below.
- **Scroll timeline** (p = progress of the section through the viewport; measured at 710 px viewport):
  1. *p 0 → .15* — **Draw:** an axis-aligned square (half-side 162.6) appears as four corner brackets whose strokes extend toward the side midpoints (half-edges drawn from both corners), plus an inner square drawing its first two sides.
  2. *p .15 → .45* — **Rotate:** outer and inner squares rotate together 0 → 45° about the centre, becoming diamonds; the four spokes grow from the inner vertices outward.
  3. *p .45 → .65* — **Fill:** polygon opacities ramp with a stagger: Performance & Agents first (0 → 1), Interfaces (~0.15 behind), Context last; simultaneously the solid bottom-left half-edges fade to 0 and the dashed edge/spoke fade in.
  4. *p .65 → .8* — **Label:** all 20 labels fade 0 → 1 together (≈ 150 px of scroll).
  Values are a pure function of scroll (no time-based easing, no smoothing) — scrolling back reverses everything.
- **Mobile (<1024):** not sticky; the diagram sits full-width under the text and plays the same scroll timeline across its own pass through the viewport.
- **Interaction:** no hover/click on the diagram.

## 2.10 Industries rail

- **Header:** H2 left, paragraph (15.5 px, concrete) right, revealed with the standard fade-up.
- **Rail:** a horizontally scrollable flex row that **bleeds to the viewport edges** while staying aligned to the container: `margin-left: calc(var(--rail-gutter) * -1); width: calc(100% + 2*var(--rail-gutter)); padding-inline: var(--rail-gutter); scroll-padding-inline: var(--rail-gutter)` with `--rail-gutter: max(48px, calc((100vw − 1440px)/2 + 48px))` (20 px on mobile). `scroll-snap-type: x proximity`, children `snap-start`, `overscroll-behavior-x: contain`, hidden scrollbar.
- **Card width** uses container units: `--sector-card: calc((100cqw − 12px)/1.2)` mobile (1.2 cards visible), `(100cqw − 48px)/3` md, `(100cqw − 72px)/4` lg; gap 12 → 24 px.
- **Drag to scroll:** `cursor: grab; user-select:none`; pointer-drag translates into `scrollLeft` (verified: a 500-px drag moved 527 px, then snapped).
- **Card:** square `<a>`; photo; **film-grain overlay** (SVG `feTurbulence` data-URI, 140 px tile, `mix-blend-mode: overlay`, opacity .16, desktop only); bottom gradient `rgba(18,16,14,.1) 40% → .9 100%`; top-left mono index "01"…"08"; bottom-left 18→21 px white title; a **caption row (mono 10 px uppercase, two use-cases separated by "·") that expands on hover**: wrapper `display:grid; grid-template-rows: 0fr → 1fr; opacity 0 → 1; 300 ms brand ease` (desktop `:hover`); on <1024 it is shown for cards that have `.is-colored` (set by an IntersectionObserver when the card is in view).
- **Controls (below, right-aligned):** Previous / Next square buttons 44×44 (1-px border, disabled state = faded), and a dot pager inside a bordered box: 6-px squares, one per reachable snap position (5 dots at 4-up desktop, 8 on mobile), active = black, others stone; each dot is a `<button aria-label="Go to <industry>">` with an enlarged hit area (`::before inset:-8px`); active dot has `aria-current="true"`. Next/prev scroll by one card (+gap) with smooth behaviour; the active dot updates from scroll position.

## 2.11 Depth / Ownership / Breadth + stats

- **Section bg:** stone `#b8aea4`. H2 (2 lines) then a **bordered panel** on `#f2f2f2`: row 1 = 3 equal columns divided by hairlines (padding ~36 px); each has a mono 11 px uppercase label with a **6 px rust square bullet**, a 21 px H3, and a 14.5 px/1.65 paragraph. Row 2 = 4 stat cells (2×2 on mobile).
- **Entrance:** the panel uses the standard fade-up (opacity 0, y 16 → 0, ~600 ms).
- **Stat counters:** big number (34 → 40 px, ls .005em) + suffix span ("M+", "%+", "%", "X") + mono 10 px label.
  - SSR renders the **final values** (good for SEO/no-JS). On first intersection (fired as soon as the row is ~20 % in view) the numbers reset to 0 and count up.
  - Measured: 92 ms → 13 %, 216 ms → 40 %, 309 ms → 60 %, 412 ms → 73 %, 542 ms → 87 %, 826 ms → 98 %, final at ~1.08 s. This fits **duration ≈ 1.2 s, ease-out cubic**, integer rounding (`Math.round`), all four counters in sync, **runs once** (scrolling away/back does not replay).
  - Suffix is static; numbers are not padded (layout shift avoided because the final value was already rendered and the cell width is fixed by the grid).

## 2.12 Vision ("Enterprise Superintelligence") teaser

- White section, 2 columns (1.1fr / .9fr). Left: H2, paragraph, black button. Right: a **looping MP4** (720×720, 10.75 s, `muted loop playsinline preload="none"` + poster), `mix-blend-mode: multiply` so its white background disappears into the page, scaled to `min(565px, 42vw)`. It shows a wireframe octahedron (pyramid + inverted pyramid) slowly rotating with an inner plane. Playback is started by JS when in view (`autoplay` is false; `preload=none` keeps it off the critical path).

## 2.13 Closing CTA (shared across pages)

- CSS-module section, `min-height: 34.23vw`, same warm 98° gradient as the hero; padding in vw (`8.22vw` top, `6.9vw` bottom); H1-sized heading with the **same pointer-driven sheen** (`--hero-gx`) ≥1024; inline email form fixed at 480 px wide, controls 44 px tall; transparent input with 30 % carbon border.
- Right side: a **static** collage on a `--cell: 7.93vw` lattice — bordered cells, five quarter-circle `curve.svg` tiles and two photo tiles (ship, material). It echoes the hero grid without animating.

## 2.14 Footer

- Bg `#f2f2f2`, hairline top/bottom borders, hover-dim behaviour on links.
- Grid `1.1fr 1fr 1fr 1fr 1.3fr` (≥768; 2 cols sm; 1 col xs): big brand **monogram** (black glyph ~70×60 px) vertically centred in col 1; three link columns with mono 10 px uppercase captions (ls .16em) and 13 px links (ink-2 → ink-strong on hover; links have an underline wipe); last column = rust square + 2-line brand statement + muted descriptor, then a hairline and "Terms & policies" list including **"Consent Preferences"** (opens the consent manager modal with "Decline all / Allow all" and per-category toggles).
- **No newsletter form in the footer** — "Newsletter" is a link to `#newsletter`; the actual subscribe UI is (a) a form block on the Newsroom page and (b) a **floating dialog** (see 2.21).
- **Bottom bar:** © line left; **compliance chips** right — 7 bordered boxes (mono 10 px): SOC 2, ISO 27001, GDPR, HIPAA, EU AI Act, NIST CSF, DORA — then a vertical divider and the **language selector**: a bordered button "English ▾" with `aria-haspopup="listbox"`; opens upward (`bottom-full`) a 10-rem listbox on `#fcfcfc` with `shadow-lg` and 4 `role=option` rows (English ✓ selected; ES/FR/DE greyed). Escape closes.

## 2.15 Scroll reveals (site-wide)

- Implemented with **Motion (framer-motion) `whileInView`** — elements are SSR'd with inline `style="opacity:0;transform:translateY(16px)"` and end with `opacity:1;transform:none`.
- Measured curve: 0 → 0.57 opacity at 108 ms, 0.85 at 207 ms, 0.97 at 332 ms, settles at ~600 ms → **~0.6 s, strong ease-out** (≈ cubic-bezier(.22,1,.36,1)). Distance 16 px. Fires once, after the element is ~100–150 px inside the viewport. Applied to section headers, card grids, diagram wrappers, CTA bands; children are not individually staggered on the homepage (grids reveal as one block). Product pages also reveal feature visuals with longer fades.

## 2.16 Platform overview page — sticky mini-diagram + scroll-spy

- Hero: 2 columns — H1 + paragraph + ghost button left; the fully assembled Layer Diamond (static, labels visible) right, with the dotted product leader line.
- Body: grid `280px / 1fr`. Left column `md:sticky top-[20vh]`: a **mini dotted diamond** (all edges dotted) where the active layer's quadrant fills grey and a **leader line** (1-px) runs from that quadrant down-left to the active item in a numbered list (01 Agents … 05 [PRODUCT-PRISMA]); the active item shows a rust square marker and full-ink text, others are muted. Updates as each content block crosses the viewport (scroll-spy).
- Right column: per layer — mono eyebrow, 20 px lead paragraph, hairline, 4 bullets (rust square + 19 px title + 15 px description), ghost "Explore …" button, and a **simulated product UI** (see 2.17).

## 2.17 Simulated product interfaces (Platform overview / Interfaces / Agents / Developer tools)

All are HTML/CSS mockups with JS state, framed in 1-px bordered windows with a title bar (breadcrumb "Workflows / …", status pill), on a dotted-grid canvas background (`radial-gradient` dots ~16 px pitch).
- **Ops console with globe:** left nav (Overview, Live Map, Calls, Customers, Engineers — `aria-pressed` buttons), a Global/California segmented toggle, and a **canvas 2D dotted globe** (DPR-aware, e.g. 860×1000 backing store) slowly rotating, with square markers for plants/ports/DCs and great-circle arcs; legend row. Toggling California swaps to a dotted state outline with city markers and a route; a city tab bar (3 cities) and shipment rows ("In transit", "Arriving") appear.
- **Interfaces page app launcher:** "Apps" breadcrumb bar; 2×2 tiles (Support Desk, Fleet Tracker, Collections, Escalations) that **fade in staggered** on reveal; clicking a tile opens that app inside the frame with breadcrumb "Apps / <app>" and an "All apps" back link.
- **Workflow builder (Agents hero):** nodes ("Inbound to number → New caller detected", "Voice agent", …) appear one by one connected by vertical lines, like a build log replay.
- **Voice waveform (Conversational AI):** ~90 vertical bars; a playhead (rust square + 1-px line) moves left→right; bars left of it render dark, right of it light grey.
- **Live-signals diagram (Reasoning agents):** three source boxes (Weather / Capacity / Contact memory) with elbow connectors into a "Live session" box with a rust status square.
- **Developer tools hero:** 2-pane window — code editor (line numbers, TS snippet) + terminal output on the left; JSON response ("201 Created") + "Session stream" event list with timestamps and check/rust status squares on the right — events appear sequentially.

## 2.18 Orchestration-product page (/prisma)

- **Hero mockup autoplay:** an empty chat composer ("Let's build something") types a prompt, sends it, then shows a run log of **4 tool calls** (Agents → Performance → Context → Interfaces) with the active row highlighted black and a timer, while a workflow canvas below builds nodes. Loops/plays on view; no user input needed (input is not interactive).
- **"How it works" stepper:** 8 numbered mono tabs (01–08) in a row; active = 1-px bordered box + rust square under it; `aria-current="step"`, `title` attribute holds the step name. Clicking changes the left text (H3 + paragraph) and the right **layer diagram**: four labelled rows (Interfaces/Context/Performance/Agents) of evenly spaced grey dots; a rust square representing the product moves to the relevant row/dot; the active row label gets a left bar. Colour transitions 300 ms. Not auto-advancing.
- Build / Manage two-column feature lists, FAQ accordion, dark band, CTA.

## 2.19 Vision page (/product/esi) — dark theme scrollytelling

- Entire page is a **dark scope** (`--surface #070707`, ink white, lines `#1f1f1f`). H1 uses the gradient sheen in light greys on black.
- Numbered chapters 01–05: each is a 2-column row where the text column is `lg:sticky top:16vh` inside a 500 px-tall wrapper, and the right column holds a visual in a bordered dark frame:
  - 01 agents grid: a lattice of node squares with "plus" connectors and a live **"Active runs" counter** ticking upward (tabular mono).
  - 02 schema grid: ~150 small table glyphs; a connected cluster highlights (lighter fill + connector lines).
  - **03 pinned pyramid (main scrollytelling):** wrapper height ≈ 6142 px; inner `sticky top:0; height:100vh`. Right: a **canvas 2D** (1004×1000 @2× DPR) chart — x-axis "volume of work" with 6 function labels, y-axis "criticality", three bands (routine / complex / critical) marked by dashed lines and rust-tick labels on the right. Cells of a pyramid light up progressively; a second track "context" (connected squares) fills under the axis. Left: step counter "01 / 05" … "05 / 05" and a 2-line statement that cross-fades per step. Bottom-right: a large **agent counter** that increases continuously with scroll (e.g. 180 → 241 → 7,400 → 9,167 → 10,284) with thousands separators. ≈1,000 px of scroll per step.
  - 04 particles canvas: four clusters of dots drifting toward rust "goal" squares.
  - 05 convergence diagram: four horizontal layer rails of dots with fan-in lines to a single rust node at the top.
- Then a carbon band with a statement H2, and the shared CTA.

## 2.20 Industry, function, customer, newsroom, hub, careers, contact, demo, blog, legal

- **Industry pages:** centred hero (2-line H1, second line in muted grey; small pixel-monogram icon; 14 px paragraph; black button) → full-bleed-in-container 16:9 photo → centred H2 + subtitle → repeated **use-case blocks**: H2 left, 5 bordered list items (title + description) left, a product screenshot composited on a tinted photo background right → split "system of record" panel (grey left text panel / photo right) → full-bleed photo band with 2×2 feature grid over it ("Designed for enterprise") → grey "Where do you want to start?" CTA box. Headings exist twice (desktop/mobile variants toggled by breakpoint).
- **Function pages:** hero split (H1 left, paragraph + ghost CTA right) → "Trusted by" logo grid (5 cols) → two-tone H2 + paragraph + ghost CTA with an animated **run transcript mockup** (event cards "Account due for recall", "Call the buyer" with Agent/Buyer lines) → two-tone H2 + **2×2 numbered use-case grid** (hairline-separated cells, rust-bullet outcome line at the bottom) → benefits (3) → "From kickoff to live in [FIGURE] weeks" (Build/Test/Deploy steps) → numbers → FAQ (7) → CTA.
- **FAQ accordion (global):** button rows (18 px question, 5-px square bullet that fills on hover/open, a 12-px "+" whose vertical bar rotates/scales away to form "−" in 500 ms); panel `role=region`, `aria-controls`/`aria-expanded`, `grid-template-rows: 0fr → 1fr` **500 ms cubic-bezier(.22,1,.36,1)**; independent items (several can be open).
- **Customers listing:** split hero → featured story band (grey bg): image with a frosted "Watch the film" button (`backdrop-blur-sm`, 45 % black, 1-px white/40 border) that **swaps the poster for an inline native `<video controls>`** (2:44) in place — no modal; right: H2, 2×2 stats (number + mono caption), quote, attribution, outlined "Read the story" button → 3-column card grid (3:2 tiles with brand-colour gradients and a white logo, H3, 2-line excerpt, mono "Read more [→]") → CTA.
- **Customer story:** centred client logo, breadcrumb "Case Studies / [CLIENT]", centred H1 (2 lines), 16:9 hero photo (≈750 px wide) → body grid: left sticky rail (`md:sticky top-24`) with Key metrics (2 numbers), Products (outlined mono chips), Table of contents (left-border active marker); right: quote card (grey, rust square, 20 px quote, avatar + name + mono role) then H2 sections with paragraphs, italic pull quotes, bold-lead lists → related CTA.
- **Newsroom:** H1 → 2 columns: intro + "Media kit →" + **newsletter form** (email + disabled "Subscribe" until valid, consent microcopy) | category index (4 rows with arrows, hairlines) → Featured post (image + title + excerpt + author avatar + "Learn more") → category rows of 3 cards (dark-framed cover graphics) with "See all … →".
- **Hub (SEO library):** H1 → search input → category filter buttons (active = medium weight + full ink, others 60 % ink) → result count "Showing N results out of 84" → sort dropdown "Most recent" → 3-col cards (blurred warm-gradient covers with serif title + monogram, date, 2-line title, 3-line excerpt clamp, "Read more →"). **Filtering is client-side** (instant, URL unchanged).
- **Blog listing:** same pattern as Hub with more categories (Engineering, Press releases, Enterprise AI strategy, Customers & impact, Company news, Product launches); covers are designed graphics.
- **Article:** breadcrumb, centred H1, dek, author avatar + date + read time, wide cover → body with left sticky "On this page" TOC (active left border) and 15 px body, 46 px H2s.
- **Careers:** split hero (3-line H1 with muted middle words, CTA pair: solid "Open positions →" + text link) → full-width team photo → "Who we are" (H2 left / 2 paragraphs right) → grey statement band with rust square → values grid (6 cells, 3×2, photos interleaved, numbered) → logos of former employers → **offices list + dotted globe** (10+ rows: index, city, country, rust outline square; hovering a row makes it active and rotates a **canvas** globe to that city; cycles automatically when idle) → open roles list (filter input) → CTA.
- **Contact:** split: eyebrow + 2-line H1 + paragraph + "book a demo" inline link | form card (Full name*, Email*, Company (optional), Phone (optional), Topic select, Message* textarea, black "Send message →"). Inputs are filled grey boxes (no border) with placeholder text.
- **Demo (standalone):** no footer; left: H1 "Book a demo" style with muted word, one-line dek, **multi-step form** (step 1 work email + "Next" disabled until valid; later steps: first/last name, phone with country-flag selector, "How did you hear about us" dropdown); right panel: grid collage with photos (hero-grid vocabulary), headline + "Trusted by …" and a **logo marquee** (`translateX(0 → −50%)`, **32 s linear infinite**, list duplicated, `will-change: transform`).
- **Legal:** policy content injected by the consent vendor's embed (`<div name="termly-embed">` → iframe), white card, generic vendor typography; shared header/footer and CTA.

## 2.21 Floating newsletter dialog

- Appears after deep scroll on long product pages (seen at ~5,400 px scroll on Platform overview). `position:fixed; bottom:96px; right:24px` (left/right 16 px on mobile), max-width 24 rem, `#fcfcfc`, 10 % black border, `shadow-lg`, padding 20/32. `role="dialog"`, `aria-modal="false"` (non-blocking), close button `aria-label="Close"`. Content: title, one-line description, email field, full-width disabled Subscribe button (enables on valid email), policy microcopy.

## 2.22 Route transitions

- None custom: standard Next.js client navigation (instant swap). Perceived transition comes from in-view reveals on the new page. Native scroll (no smooth-scroll library).

---

# 3. Reconstruction recipes

All recipes are vanilla HTML/CSS/JS (the reference is React + Motion; a React/Motion version of the two most reused primitives is at the end). Every recipe assumes the token block from **§4** is loaded. Placeholder content only. Each block is self-contained: paste into one HTML file together with §4.

### 3.0 Shared base (load once)

```html
<style>
  *,*::before,*::after{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--surface);color:var(--ink-strong);font-family:var(--font-body);-webkit-font-smoothing:antialiased}
  img,video,svg,canvas{display:block;max-width:100%}
  a{color:inherit;text-decoration:none}
  button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
  .container{max-width:var(--container);margin-inline:auto;padding-inline:var(--gutter)}
  .mono{font-family:var(--font-mono);text-transform:uppercase;letter-spacing:.08em;font-size:11px}
  .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
  .bullet-sq{display:inline-block;width:6px;height:6px;background:var(--rust);flex:none}
  @media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
```

### 3.1 Scroll reveal (vanilla equivalent of Motion `whileInView`)

```html
<style>
  [data-reveal]{opacity:0;transform:translateY(16px);transition:opacity .6s var(--ease-out-soft),transform .6s var(--ease-out-soft)}
  [data-reveal].is-in{opacity:1;transform:none}
  @media (prefers-reduced-motion:reduce){[data-reveal]{opacity:1;transform:none}}
</style>
<script>
  (() => {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); } });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0 });
    document.querySelectorAll('[data-reveal]').forEach(el => {
      const d = el.dataset.revealDelay; if (d) el.style.transitionDelay = d + 'ms';
      io.observe(el);
    });
  })();
</script>
```

### 3.2 Announcement bar

```html
<style>
  .announce{background:var(--carbon);border-bottom:1px solid var(--line-soft)}
  .announce a{max-width:var(--container);margin:auto;display:flex;align-items:center;justify-content:center;gap:14px;
    padding:9px var(--gutter);font:400 11px/1.5 var(--font-mono);text-transform:uppercase;letter-spacing:.04em;color:var(--signal);transition:opacity .15s}
  .announce a:hover{opacity:.7}
  .announce .badge{display:inline-flex;align-items:center;gap:8px}
  .announce .dot{width:6px;height:6px;background:var(--rust);animation:blink 2.4s ease-in-out infinite}
  .announce .short{display:none}.announce .cta{display:none;align-items:center;gap:6px}
  @media (max-width:639px){.announce .long{display:none}.announce .short{display:inline}}
  @media (min-width:768px){.announce .cta{display:inline-flex}}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
</style>
<div class="announce">
  <a href="/news/placeholder">
    <span class="badge"><span class="dot" aria-hidden="true"></span>New</span>
    <span class="long">[BRAND] closes its [FIGURE] round to scale [PRODUCT] across [INDUSTRY]</span>
    <span class="short">[FIGURE] round — [PRODUCT] for [INDUSTRY]</span>
    <span class="cta">Read the news <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg></span>
  </a>
</div>
```

### 3.3 Buttons & link micro-interactions (arrow swap, underline wipe, sweep, hover-dim, chip border-draw)

```html
<style>
  /* Primary button with arrow-swap box */
  .btn{display:inline-flex;align-items:center;gap:12px;padding:13px 12px 13px 20px;background:var(--cta-solid-bg);color:var(--cta-solid-fg);
    font:400 11px/1.5 var(--font-mono);letter-spacing:.01em;text-transform:uppercase;transition:transform .35s var(--ease-brand),opacity .35s var(--ease-brand)}
  .btn:active{transform:scale(.98)}
  .btn:focus-visible{outline:2px solid var(--rust);outline-offset:2px}
  .btn--ghost{background:var(--signal);color:var(--ink-strong)}
  .arrowbox{position:relative;flex:none;width:18px;height:18px;border:1px solid color-mix(in srgb,currentColor 60%,transparent);overflow:hidden}
  .arrowbox--lg{width:27px;height:27px}
  .arrowbox .rot{position:absolute;inset:0}
  .arrowbox.diag .rot{transform:rotate(-45deg)}
  .arrowbox svg{position:absolute;left:50%;top:50%;width:9px;height:9px;margin:-4.5px 0 0 -4.5px;transition:transform .35s var(--ease-brand)}
  .arrowbox svg:last-child{transform:translateX(-24px)}
  :is(.btn,.card,a):hover .arrowbox svg:first-child,:is(.btn,.card,a):focus-visible .arrowbox svg:first-child{transform:translateX(24px)}
  :is(.btn,.card,a):hover .arrowbox svg:last-child,:is(.btn,.card,a):focus-visible .arrowbox svg:last-child{transform:none}

  /* Underline wipe (nav, footer) */
  .ul{position:relative}
  .ul::after{content:"";position:absolute;left:0;right:0;bottom:-4px;height:1px;background:currentColor;transform:scaleX(0);transform-origin:right;transition:transform .3s var(--ease-brand)}
  a:hover>.ul::after,button:hover>.ul::after,.ul:hover::after{transform:scaleX(1);transform-origin:left}

  /* Underline sweep (menu items): retract right, redraw from left */
  .sweep{position:relative}
  .sweep::after{content:"";position:absolute;left:0;right:0;bottom:-3px;height:1px;background:currentColor;transform:scaleX(0)}
  @media (hover:hover){.sweep:hover::after{animation:sweep .6s var(--ease-inout) forwards}}
  @keyframes sweep{0%{transform-origin:right;transform:scaleX(1)}49%{transform-origin:right;transform:scaleX(0)}51%{transform-origin:left;transform:scaleX(0)}100%{transform-origin:left;transform:scaleX(1)}}

  /* Hover-dim: siblings fade when one is hovered */
  .hover-dim :is(a,button){transition:opacity .35s var(--ease-brand),color .35s var(--ease-brand)}
  .hover-dim:has(a:hover,button:hover) :is(a,button):not(:hover){opacity:.4}

  /* Chip with 4-stroke border draw */
  .chip{position:relative;display:inline-block;border:1px solid var(--line);padding:4px 10px;font-size:11.5px;color:var(--ink-2);transition:color .2s}
  .chip:hover{color:var(--ink-strong)}
  .chip::before,.chip::after{content:"";position:absolute;width:0;height:0;opacity:0;pointer-events:none;box-sizing:border-box;transition:width .12s linear,height .12s linear,opacity .12s linear}
  .chip::before{top:0;left:0;border-top:1px solid var(--rust);border-right:1px solid var(--rust)}
  .chip::after{bottom:0;right:0;border-bottom:1px solid var(--rust);border-left:1px solid var(--rust)}
  .chip:hover::before{opacity:1;width:100%;height:100%;transition:opacity 10ms linear,width .14s linear,height .14s linear .14s}
  .chip:hover::after{opacity:1;width:100%;height:100%;transition:opacity 10ms linear .28s,width .14s linear .28s,height .14s linear .42s}
  @media (prefers-reduced-motion:reduce){.chip::before,.chip::after{transition:none}}
</style>

<a class="btn" href="#">Book a call
  <span class="arrowbox diag"><span class="rot">
    <svg viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg>
    <svg viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg>
  </span></span>
</a>
<nav class="hover-dim"><a href="#"><span class="ul">Customers</span></a> <a href="#"><span class="ul">News</span></a></nav>
<a class="chip" href="#">Workflows</a>
```

### 3.4 Header, mega menus and mobile menu

```html
<style>
  .hdr{position:fixed;inset:0 0 auto;z-index:60}
  .nav{position:relative;background:var(--surface)}
  .nav__in{max-width:var(--container);margin:auto;display:flex;align-items:center;justify-content:space-between;padding:12px var(--gutter);height:68px}
  .nav__links{display:none;align-items:stretch;gap:14px;font:400 11px/1.5 var(--font-body);text-transform:uppercase;letter-spacing:.12em;color:var(--ink-1)}
  .nav__links>*{display:inline-flex;align-items:center;gap:4px;padding:0 14px}
  .nav__links :is(a,button):hover{color:var(--ink-strong)}
  .chev{transition:transform .3s var(--ease-brand)} [aria-expanded=true] .chev{transform:rotate(180deg)}
  @media (min-width:1024px){.nav__links{display:flex}.burger{display:none}}
  /* shared mega panel */
  .mega{position:absolute;inset:100% 0 auto;height:0;overflow:hidden;background:var(--surface);transition:height .42s var(--ease-brand)}
  .mega__pane{position:absolute;inset:0 0 auto;opacity:0;pointer-events:none;transition:opacity .28s var(--ease-brand)}
  .mega__pane.is-active{opacity:1;pointer-events:auto}
  .mega__grid{max-width:var(--container);margin:auto;padding:24px var(--gutter) 32px;display:grid;grid-template-columns:repeat(4,minmax(0,216px)) 1fr;gap:32px 40px}
  .mega h4{margin:0 0 4px;font:400 14px var(--font-body)} .mega p{margin:0 0 12px;font-size:12px;color:var(--ink-4)}
  .mega .chips{display:flex;flex-wrap:wrap;gap:6px}
  @media (max-width:1023px){.mega{display:none}}
  /* mobile */
  .burger{display:flex;flex-direction:column;gap:4px;padding:6px}
  .burger i{display:block;width:24px;height:1px;background:currentColor;transition:transform .3s var(--ease-brand)}
  .burger[aria-expanded=true] i:first-child{transform:translateY(2.5px) rotate(45deg)}
  .burger[aria-expanded=true] i:last-child{transform:translateY(-2.5px) rotate(-45deg)}
  .mmenu{display:grid;grid-template-rows:0fr;transition:grid-template-rows .3s var(--ease-brand)}
  .mmenu.is-open{grid-template-rows:1fr}
  .mmenu>div{min-height:0;overflow:hidden}
  .mmenu__scroll{overflow-y:auto;overscroll-behavior:contain;padding:16px 20px;max-height:calc(100svh - 104px)}
  .macc>button{display:flex;width:100%;justify-content:space-between;padding:14px 0;font:400 13px var(--font-body);text-transform:uppercase;letter-spacing:.12em;border-bottom:1px solid var(--line)}
  .macc__panel{display:grid;grid-template-rows:0fr;opacity:0;transition:grid-template-rows .3s var(--ease-brand),opacity .3s var(--ease-brand)}
  .macc.is-open .macc__panel{grid-template-rows:1fr;opacity:1}
  .macc__panel>div{min-height:0;overflow:hidden}
  @media (min-width:1024px){.mmenu{display:none}}
</style>

<header class="hdr">
  <nav class="nav" aria-label="Main">
    <div class="nav__in">
      <a href="/" aria-label="[BRAND] home">[BRAND]</a>
      <div class="nav__links hover-dim">
        <button data-mega="platform" aria-haspopup="true" aria-expanded="false" aria-controls="mega"><span class="ul">Platform</span><svg class="chev" width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor"><path d="M1 2.5 4 5.5 7 2.5"/></svg></button>
        <button data-mega="solutions" aria-haspopup="true" aria-expanded="false" aria-controls="mega"><span class="ul">Solutions</span><svg class="chev" width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor"><path d="M1 2.5 4 5.5 7 2.5"/></svg></button>
        <a href="/customers"><span class="ul">Customers</span></a><a href="/news"><span class="ul">News</span></a>
      </div>
      <button class="burger" aria-label="Open menu" aria-expanded="false" aria-controls="mmenu"><i></i><i></i></button>
    </div>
    <div class="mega" id="mega" role="region" aria-label="Menu">
      <div class="mega__pane" data-pane="platform">
        <div class="mega__grid">
          <div><h4>Layer one</h4><p>Short descriptor</p><div class="chips"><a class="chip" href="#">Item</a><a class="chip" href="#">Item</a></div></div>
          <div><h4>Layer two</h4><p>Short descriptor</p><div class="chips"><a class="chip" href="#">Item</a></div></div>
          <div><h4>Layer three</h4><p>Short descriptor</p><div class="chips"><a class="chip" href="#">Item</a></div></div>
          <div><h4>Layer four</h4><p>Short descriptor</p></div>
          <div style="border-left:1px solid var(--line);padding-left:28px"><a href="#">Security →</a><br><br><a href="#">Developers →</a></div>
        </div>
      </div>
      <div class="mega__pane" data-pane="solutions">
        <div class="mega__grid" style="grid-template-columns:1fr 1fr 1fr 1fr">
          <div><p class="mono">By industry</p><a class="sweep" href="#">[INDUSTRY]</a></div><div></div>
          <div><p class="mono">By function</p><a class="sweep" href="#">Support</a></div>
          <div style="border:1px solid var(--line);padding:20px"><p class="mono">Solutions</p><h4 style="font-size:20px">Promo headline</h4><p>Two-line promo text.</p></div>
        </div>
      </div>
    </div>
    <div class="mmenu" id="mmenu"><div><div class="mmenu__scroll">
      <div class="macc"><button aria-expanded="false">Platform <span>▾</span></button><div class="macc__panel"><div><p>…links and chips…</p></div></div></div>
      <div class="macc"><button aria-expanded="false">Solutions <span>▾</span></button><div class="macc__panel"><div><p>…</p></div></div></div>
      <a class="macc" href="/customers" style="display:block;padding:14px 0;border-bottom:1px solid var(--line)">CUSTOMERS</a>
    </div></div></div>
  </nav>
</header>

<script>
(() => {
  const mega = document.getElementById('mega');
  const triggers = [...document.querySelectorAll('[data-mega]')];
  const panes = [...mega.querySelectorAll('.mega__pane')];
  let current = null, closeT = null;
  const open = (key) => {
    clearTimeout(closeT); current = key;
    triggers.forEach(t => t.setAttribute('aria-expanded', String(t.dataset.mega === key)));
    panes.forEach(p => p.classList.toggle('is-active', p.dataset.pane === key));
    const pane = panes.find(p => p.dataset.pane === key);
    mega.style.height = pane.scrollHeight + 'px';            // 420ms height morph
  };
  const close = () => { current = null; mega.style.height = '0px';
    triggers.forEach(t => t.setAttribute('aria-expanded', 'false'));
    panes.forEach(p => p.classList.remove('is-active')); };
  const scheduleClose = () => { clearTimeout(closeT); closeT = setTimeout(close, 150); };
  triggers.forEach(t => {
    t.addEventListener('mouseenter', () => open(t.dataset.mega));
    t.addEventListener('mouseleave', scheduleClose);
    t.addEventListener('click', () => current === t.dataset.mega ? close() : open(t.dataset.mega));
  });
  mega.addEventListener('mouseenter', () => clearTimeout(closeT));
  mega.addEventListener('mouseleave', scheduleClose);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && current) { const t = triggers.find(x => x.dataset.mega === current); close(); t?.focus(); } });
  window.addEventListener('resize', () => { if (current) open(current); });

  // mobile
  const burger = document.querySelector('.burger'), mm = document.getElementById('mmenu');
  burger.addEventListener('click', () => {
    const o = !mm.classList.contains('is-open'); mm.classList.toggle('is-open', o);
    burger.setAttribute('aria-expanded', String(o)); burger.setAttribute('aria-label', o ? 'Close menu' : 'Open menu');
  });
  mm.querySelectorAll('.macc>button').forEach(b => b.addEventListener('click', () => {
    const item = b.parentElement, o = !item.classList.contains('is-open');
    item.classList.toggle('is-open', o); b.setAttribute('aria-expanded', String(o));
  }));
})();
</script>
```

**Hero-matching nav background (homepage):** give the nav the hero gradient while the hero is under it.

```js
const nav = document.querySelector('.nav'), hero = document.querySelector('.hero');
new IntersectionObserver(([e]) => {
  nav.style.background = e.isIntersecting ? getComputedStyle(hero).backgroundImage : 'var(--surface)';
}, { rootMargin: '-68px 0px 0px 0px', threshold: 0.12 }).observe(hero);
```

### 3.5 Hero: pointer-sheen headline, inline form, animated grid

```html
<style>
  .hero{position:relative;height:100svh;min-height:680px;overflow:hidden;color:var(--ink-strong);
    background:linear-gradient(98deg,color-mix(in srgb,var(--stone) 46%,#fff) 0%,color-mix(in srgb,var(--stone) 18%,#fff) 48%,#fff 100%)}
  .hero__in{position:relative;z-index:1;max-width:var(--container);margin:auto;height:100%;display:flex;flex-direction:column;justify-content:center;padding:104px var(--gutter) 40px}
  .glow{width:fit-content;max-width:11.5em;margin:-.1em 0 -.14em;padding:.1em 0 .14em;cursor:default;
    font:400 var(--fs-display)/1.04 var(--font-body);letter-spacing:-.055em;color:transparent;-webkit-background-clip:text;background-clip:text;
    background-image:linear-gradient(105deg,var(--obsidian) 0%,var(--carbon) 55%,var(--concrete) 100%)}
  @media (min-width:1024px){.glow{background-image:repeating-linear-gradient(105deg,var(--obsidian) var(--gx,8%),var(--concrete) calc(var(--gx,8%) + 60%),var(--obsidian) calc(var(--gx,8%) + 120%))}}
  .inline-form{display:flex;flex-direction:column;gap:8px;width:min(480px,100%);margin-top:40px}
  .inline-form input{flex:1;min-width:0;padding:13px 16px;font:400 14px var(--font-body);border:1px solid var(--border-cta);background:transparent;color:var(--ink-strong);outline:none;transition:border-color .2s}
  .inline-form input::placeholder{color:var(--ink-4)} .inline-form input:focus{border-color:var(--stone)}
  .inline-form input[aria-invalid=true]{border-color:var(--alert)}
  .inline-form .err{font-size:12px;color:var(--alert);min-height:16px}
  @media (min-width:640px){.inline-form{flex-direction:row;gap:0}.inline-form input{border-right:0}}
  .hero__sub{max-width:28em;margin:24px 0 0;font-size:20px;line-height:1.4;color:var(--ink-1)}
  /* grid art */
  .hg-root{position:absolute;inset:0 0 0 -15svh;opacity:.75;pointer-events:none;-webkit-mask-image:linear-gradient(transparent 8%,#000 30%);mask-image:linear-gradient(transparent 8%,#000 30%)}
  .hg-root svg{width:100%;height:100%}
  .hg-photos{opacity:.14}
  @media (min-width:1024px){
    .hg-root{left:var(--hg-left,46%);bottom:-14.2857%;opacity:1;
      -webkit-mask-image:linear-gradient(to right,transparent,#000 240px),linear-gradient(transparent 8%,#000 30%);-webkit-mask-composite:source-in;
      mask-image:linear-gradient(to right,transparent,#000 240px),linear-gradient(transparent 8%,#000 30%);mask-composite:intersect}
    .hg-photos{opacity:1}}
  .hg-line{stroke-dasharray:1;stroke-dashoffset:1}
  @media (prefers-reduced-motion:no-preference){
    .hg-anim{animation-fill-mode:both;animation-play-state:paused;animation-timing-function:cubic-bezier(.65,0,.35,1);animation-delay:var(--d,0s);animation-duration:18s;animation-iteration-count:infinite}
    :root[data-hero-ready] .hg-anim{animation-play-state:running}
    .l-abc{animation-name:hg-intro;animation-duration:1.6s;animation-iteration-count:1}
    .l-a{animation-name:l-a}.l-b{animation-name:l-b}.l-c{animation-name:l-c}.l-ab{animation-name:l-ab}.l-bc{animation-name:l-bc}
    .p-a{animation-name:p-a}.p-b{animation-name:p-b}.p-c{animation-name:p-c}}
  @media (prefers-reduced-motion:reduce){.l-abc,.l-a,.l-ab{stroke-dashoffset:0}.p-b,.p-c,.l-b,.l-c,.l-bc{opacity:0}}
  @keyframes hg-intro{from{stroke-dashoffset:1}to{stroke-dashoffset:0}}
  @keyframes l-a{0%{opacity:1;stroke-dashoffset:1}8.889%,27.778%{opacity:1;stroke-dashoffset:0}33.278%{opacity:0;stroke-dashoffset:0}33.333%,99.944%{opacity:0;stroke-dashoffset:1}100%{opacity:1;stroke-dashoffset:1}}
  @keyframes l-b{0%,33.278%{opacity:0;stroke-dashoffset:1}33.333%{opacity:1;stroke-dashoffset:1}42.222%,61.111%{opacity:1;stroke-dashoffset:0}66.611%{opacity:0;stroke-dashoffset:0}66.667%,100%{opacity:0;stroke-dashoffset:1}}
  @keyframes l-c{0%,66.611%{opacity:0;stroke-dashoffset:1}66.667%{opacity:1;stroke-dashoffset:1}75.556%,94.444%{opacity:1;stroke-dashoffset:0}99.944%{opacity:0;stroke-dashoffset:0}100%{opacity:0;stroke-dashoffset:1}}
  @keyframes l-ab{0%{opacity:1;stroke-dashoffset:1}8.889%,61.111%{opacity:1;stroke-dashoffset:0}66.611%{opacity:0;stroke-dashoffset:0}66.667%,99.944%{opacity:0;stroke-dashoffset:1}100%{opacity:1;stroke-dashoffset:1}}
  @keyframes l-bc{0%,33.278%{opacity:0;stroke-dashoffset:1}33.333%{opacity:1;stroke-dashoffset:1}42.222%,94.444%{opacity:1;stroke-dashoffset:0}99.944%{opacity:0;stroke-dashoffset:0}100%{opacity:0;stroke-dashoffset:1}}
  @keyframes p-a{0%,2.778%{opacity:0}9.444%,27.778%{opacity:1}33.278%,100%{opacity:0}}
  @keyframes p-b{0%,36.111%{opacity:0}42.778%,61.111%{opacity:1}66.611%,100%{opacity:0}}
  @keyframes p-c{0%,69.444%{opacity:0}76.111%,94.444%{opacity:1}99.944%,100%{opacity:0}}
</style>

<section class="hero" id="hero">
  <div class="hg-root" aria-hidden="true"><svg id="hg" viewBox="0 0 1600 800" preserveAspectRatio="xMinYMin slice"></svg></div>
  <div class="hero__in">
    <h1 class="glow" id="glow">Your core promise in four words.</h1>
    <form class="inline-form" id="heroForm" novalidate>
      <label class="sr-only" for="heroEmail">Work email</label>
      <input id="heroEmail" type="email" required placeholder="Your work email" autocomplete="email" aria-describedby="heroErr">
      <button class="btn" type="submit">Book a call <span class="arrowbox diag"><span class="rot"><svg viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg><svg viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg></span></span></button>
    </form>
    <div class="err" id="heroErr" aria-live="polite"></div>
    <p class="hero__sub">One sentence that explains what [PRODUCT] does and for whom, at enterprise scale.</p>
  </div>
</section>

<script>
(() => {
  /* 1) pointer sheen */
  const h = document.getElementById('glow');
  h.addEventListener('pointermove', e => { const r = h.getBoundingClientRect(); h.style.setProperty('--gx', (e.clientX - r.left) + 'px'); });

  /* 2) inline form: client validation only (wire submit to your own endpoint/route) */
  const f = document.getElementById('heroForm'), i = document.getElementById('heroEmail'), err = document.getElementById('heroErr');
  f.addEventListener('submit', e => {
    e.preventDefault();
    const ok = i.value.trim() !== '' && i.checkValidity();
    i.setAttribute('aria-invalid', String(!ok));
    err.textContent = !i.value.trim() ? 'Enter your work email.' : (!ok ? 'That email doesn’t look right.' : '');
    if (ok) { /* location.href = '/demo?email=' + encodeURIComponent(i.value) */ }
  });
  i.addEventListener('input', () => { if (i.getAttribute('aria-invalid') === 'true' && i.checkValidity()) { i.setAttribute('aria-invalid','false'); err.textContent=''; } });

  /* 3) grid art generator — edit the scene arrays to taste */
  const svg = document.getElementById('hg'), NS = 'http://www.w3.org/2000/svg', U = 100;
  const scenes = {
    abc: { cells: [[3,1],[3,2],[3,3],[3,4],[2,4],[0,4],[1,4],[4,3],[5,3],[2,5],[3,5],[2,6],[3,6]], stubs: [[1,0,3],[4,0,1],[5,0,1],[6,0,2]], curves: [[2,6]] },
    a:   { cells: [[3,0],[5,1],[0,2],[5,2],[1,3],[7,4],[5,5],[6,5],[8,5],[7,6],[3,7],[8,3]], photos: [[5,2],[8,3],[1,5]] },
    b:   { cells: [[6,1],[7,1],[9,2],[6,3],[4,5],[9,5],[10,4],[1,6],[6,7],[10,2]], photos: [[7,1],[4,5],[10,4]] },
    c:   { cells: [[4,1],[8,1],[2,2],[8,2],[0,3],[6,4],[10,6],[9,7],[1,7],[11,3]], photos: [[8,2],[0,3],[11,3]] },
    ab:  { cells: [[4,0],[7,3]] }, bc: { cells: [[9,4],[2,7]] }
  };
  const add = (tag, attrs) => { const el = document.createElementNS(NS, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); svg.appendChild(el); return el; };
  const line = (d, cls, c, r) => add('path', { d, pathLength: 1, stroke: 'var(--obsidian)', 'stroke-width': .5, 'stroke-opacity': .1, fill: 'none',
    class: `hg-line hg-anim ${cls}`, style: `--d:${(0.06 * (c + r)).toFixed(2)}s` });
  const photos = add('g', { class: 'hg-photos' });
  Object.entries(scenes).forEach(([k, s]) => {
    (s.cells || []).forEach(([c, r]) => line(`M${c*U},${r*U}h${U}v${U}h-${U}Z`, 'l-' + k, c, r));
    (s.stubs || []).forEach(([c, r, len]) => line(`M${c*U},${r*U}V${(r+len)*U}`, 'l-' + k, c, r));
    (s.curves || []).forEach(([c, r]) => line(`M${c*U},${r*U} L${c*U},${r*U+6} C${c*U},${r*U+16} ${c*U+2},${r*U+22} ${c*U+15},${r*U+30} C${c*U+29},${r*U+38} ${c*U+74},${r*U+64} ${c*U+87},${r*U+72} C${(c+1)*U},${r*U+79} ${(c+1)*U},${r*U+86} ${(c+1)*U},${r*U+94} L${(c+1)*U},${(r+1)*U}`, 'l-' + k, c, r));
    (s.photos || []).forEach(([c, r], n) => { const im = document.createElementNS(NS, 'image');
      Object.entries({ href: `https://picsum.photos/seed/${k}${n}/200/200`, x: c*U, y: r*U, width: U, height: U, preserveAspectRatio: 'xMidYMid slice',
        class: `hg-anim p-${k}`, style: `--d:${(0.06*(c+r)).toFixed(2)}s` }).forEach(([a, v]) => im.setAttribute(a, v)); photos.appendChild(im); });
  });
  /* start when photos decoded (mirrors data-hero-ready) */
  Promise.all([...svg.querySelectorAll('image')].map(im => new Promise(r => { const t = new Image(); t.onload = t.onerror = r; t.src = im.getAttribute('href'); })))
    .then(() => document.documentElement.setAttribute('data-hero-ready', ''));
})();
</script>
```

### 3.6 Customer story cards (with hover video)

```html
<style>
  .stories{display:grid;grid-template-columns:repeat(2,1fr);gap:40px 12px}
  @media (min-width:768px){.stories{gap:56px 24px}} @media (min-width:1024px){.stories{grid-template-columns:repeat(4,1fr)}}
  .card{display:block}
  .card__media{position:relative;aspect-ratio:1;overflow:hidden;background:var(--cell)}
  .card__media img{width:100%;height:100%;object-fit:cover;transition:transform .6s var(--ease-brand)}
  .card:hover .card__media img{transform:scale(1.04)}
  .card__media video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s}
  .card__media video[data-playing]{opacity:1}
  .card__shade{position:absolute;inset:0;background:linear-gradient(transparent 52%,rgb(7 7 7 / .62));pointer-events:none}
  .card__foot{position:absolute;left:12px;bottom:12px;display:flex;align-items:center;gap:9px;color:#fff}
  @media (min-width:768px){.card__foot{left:20px;bottom:20px}}
  .card__logo{width:84px;height:18px;background:currentColor;-webkit-mask:var(--logo) left center/contain no-repeat;mask:var(--logo) left center/contain no-repeat}
  @media (min-width:768px){.card__logo{width:136px;height:28px}}
  .card__cat{margin-top:16px;font:400 10px/1 var(--font-mono);text-transform:uppercase;letter-spacing:.18em;color:var(--ink-3)}
  .card__metric{margin-top:12px;max-width:8.4em;font:400 19px/1.06 var(--font-body);letter-spacing:-.025em}
  @media (min-width:768px){.card__cat{font-size:11px;margin-top:24px}.card__metric{font-size:26px;margin-top:16px}}
  @media (min-width:1024px){.card__metric{font-size:24px}} @media (min-width:1280px){.card__metric{font-size:30px}}
</style>
<div class="stories" data-reveal>
  <a class="card" href="/stories/one">
    <div class="card__media">
      <img src="https://picsum.photos/seed/s1/800/800" alt="">
      <video muted loop playsinline preload="none" aria-hidden="true" data-src="/media/hover-loop.mp4"></video>
      <div class="card__shade"></div>
      <span class="card__foot"><span class="card__logo" style="--logo:url(/logos/client.svg)"></span><span class="sr-only">Read story</span>
        <span class="arrowbox arrowbox--lg diag" style="border-color:rgb(255 255 255 / .7)"><span class="rot"><svg viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg><svg viewBox="0 0 10 10" fill="none" stroke="currentColor"><path d="M1 5h8M5.5 1.5 9 5 5.5 8.5"/></svg></span></span></span>
    </div>
    <div class="card__cat">Category</div>
    <div class="card__metric">[FIGURE] outcome in&nbsp;words</div>
  </a>
  <!-- ×4 -->
</div>
<script>
document.querySelectorAll('.card').forEach(card => {
  const v = card.querySelector('video[data-src]'); if (!v || matchMedia('(hover:none)').matches) return;
  card.addEventListener('pointerenter', () => { if (!v.src) v.src = v.dataset.src; v.play().then(() => v.setAttribute('data-playing','')).catch(()=>{}); });
  card.addEventListener('pointerleave', () => { v.pause(); v.removeAttribute('data-playing'); });
});
</script>
```

### 3.7 Logo wall (hairline grid, masked monochrome logos) + optional "story" cell

```html
<style>
  .lw{--lw-bg:var(--surface);--lw-ink:var(--concrete);--lw-hover:var(--carbon);display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);outline:1px solid var(--line);margin-top:64px}
  @media (min-width:768px){.lw{grid-template-columns:repeat(5,1fr);margin-top:96px}} @media (min-width:1024px){.lw{grid-template-columns:repeat(7,1fr)}}
  .lw__cell{position:relative;aspect-ratio:1;display:flex;align-items:center;justify-content:center;padding:0 12px;background:var(--lw-bg);transition:background-color .28s;order:var(--po,0)}
  @media (min-width:768px){.lw__cell{order:0}}
  .lw__cell:hover{background:var(--lw-hover)}
  .lw__mark{width:78%;max-width:190px;height:40px;background:var(--lw-ink);-webkit-mask:var(--src) center/contain no-repeat;mask:var(--src) center/contain no-repeat;transition:background-color .28s}
  @media (min-width:768px){.lw__mark{height:48px}}
  .lw__cell:hover .lw__mark{background:var(--lw-bg)}
  .lw__tag{position:absolute;inset:auto 0 12px;display:flex;justify-content:center;gap:4px;font:400 9px/1 var(--font-mono);text-transform:uppercase;letter-spacing:.12em;color:var(--rust-deep)}
  /* story variant: blurred photo sharpened around the pointer */
  .lw__cell--story{--mx:50%;--my:50%;overflow:hidden}
  .lw__cell--story img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .lw__blur{filter:blur(24px);transition:filter .45s var(--ease-brand)}
  .lw__cell--story:hover .lw__blur{filter:blur(3.5px)}
  .lw__sharp{opacity:0;-webkit-mask-image:radial-gradient(ellipse 42% 42% at var(--mx) var(--my),#000 0,#000 32%,transparent 72%);mask-image:radial-gradient(ellipse 42% 42% at var(--mx) var(--my),#000 0,#000 32%,transparent 72%);transition:opacity .3s}
  .lw__cell--story:hover .lw__sharp{opacity:1}
  .lw__cell--story .lw__mark{position:relative;background:var(--lw-bg)}
</style>
<div class="lw">
  <div class="lw__cell" style="--po:3"><span class="lw__mark" style="--src:url(/logos/a.svg)"></span></div>
  <a class="lw__cell" href="/stories/b" style="--po:1"><span class="lw__mark" style="--src:url(/logos/b.svg)"></span><span class="lw__tag">Case study ↗</span></a>
  <a class="lw__cell lw__cell--story" href="/stories/c"><img class="lw__blur" src="https://picsum.photos/seed/c/400/400" alt=""><img class="lw__sharp" src="https://picsum.photos/seed/c/400/400" alt=""><span class="lw__mark" style="--src:url(/logos/c.svg)"></span></a>
</div>
<script>
document.querySelectorAll('.lw__cell--story').forEach(c => c.addEventListener('pointermove', e => {
  const r = c.getBoundingClientRect(); c.style.setProperty('--mx', ((e.clientX-r.left)/r.width*100)+'%'); c.style.setProperty('--my', ((e.clientY-r.top)/r.height*100)+'%');
}));
</script>
```

### 3.8 Layer Diamond — full SVG rebuild with scroll-linked assembly

```html
<style>
  .plat{background:var(--signal);border-top:1px solid #dad5cc}
  .plat__grid{max-width:var(--container);margin:auto;padding:80px var(--gutter);display:grid;gap:56px;align-items:center}
  @media (min-width:768px){.plat__grid{padding:150px var(--gutter)}}
  @media (min-width:1024px){.plat__grid{grid-template-columns:minmax(0,502fr) minmax(0,647fr);min-height:160vh}
    .dia-wrap{position:sticky;top:max(5.5rem,calc(50vh - 324px));align-self:start;width:min(647px,calc((100svh - 8rem)*1.061))}}
  .pillar{border-top:1px solid #c9c4b9;padding:26px 0}.pillar:last-child{border-bottom:1px solid #c9c4b9}
  .pillar h3{margin:0 0 10px;font:400 16px var(--font-body)} .pillar p{margin:0;font-size:14px;line-height:1.6;color:var(--ink-3)}
  #dia{width:100%;height:auto;font-family:var(--font-body);overflow:visible}
  #dia text{font-size:10.5px;letter-spacing:.02em;fill:var(--obsidian)} #dia text.s{font-size:7.4px;letter-spacing:0}
  #dia text.inv{fill:#fff}
  #dia .stroke{fill:none;stroke:var(--obsidian);stroke-width:1;vector-effect:non-scaling-stroke}
</style>

<section class="plat"><div class="plat__grid" id="platRunway">
  <div>
    <h2 style="font:400 var(--fs-h2)/1.04 var(--font-body);letter-spacing:-.025em;margin:0 0 32px">The system to build &amp; run [PRODUCT].</h2>
    <a class="btn" href="#">Explore the platform</a>
    <div style="margin-top:56px">
      <div class="pillar"><h3>Quality is measured</h3><p>Every agent is benchmarked before launch and reviewed in production.</p></div>
      <div class="pillar"><h3>Memory compounds</h3><p>Live work turns into reusable context that sharpens future decisions.</p></div>
      <div class="pillar"><h3>People stay in control</h3><p>Tailored workspaces surface what matters and let teams steer.</p></div>
    </div>
  </div>
  <div class="dia-wrap">
    <svg id="dia" viewBox="56 56 488 488" role="img" aria-label="Four-layer platform diagram">
      <g id="rot">
        <!-- fills (pre-rotation coordinates; the group rotates 0→45°) -->
        <polygon id="fPerf" fill="var(--carbon)"   opacity="0"/>
        <polygon id="fInt"  fill="var(--concrete)" opacity="0"/>
        <polygon id="fCtx"  fill="var(--stone)"    opacity="0"/>
        <polygon id="fAg"   fill="#fff"            opacity="0"/>
        <!-- outer half-edges: 2 per side, drawn from the corners toward the midpoints -->
        <g class="stroke" id="outer"></g>
        <path id="dashEdge" class="stroke" stroke-dasharray="3 3" opacity="0"/>
        <g class="stroke" id="inner"></g>
        <g class="stroke" id="spokes"></g>
        <path id="dashSpoke" class="stroke" stroke-dasharray="2 2" opacity="0"/>
      </g>
      <!-- labels in final (unrotated) coordinates -->
      <g id="labels" opacity="0">
        <path d="M376 112V300" class="stroke" stroke-dasharray="1 2"/>
        <text x="380" y="86">PRODUCT</text><text class="s" x="380" y="98">One-line descriptor</text><text class="s" x="380" y="107">second line</text>
        <g text-anchor="end"><text class="s inv" x="275" y="165">Item one</text><text class="s inv" x="275" y="176">Item two</text><text class="s inv" x="275" y="186">Item three</text><text class="s inv" x="275" y="197">Item four</text><text class="inv" x="275" y="212">LAYER A</text></g>
        <text class="inv" x="392" y="276">LAYER B</text>
        <text x="270" y="276">CORE</text><text class="s" x="270" y="289">Item one</text><text class="s" x="270" y="300">Item two</text><text class="s" x="270" y="311">Item three</text>
        <text x="323" y="386">LAYER C</text><text class="s" x="323" y="401">Item one</text><text class="s" x="323" y="411">Item two</text><text class="s" x="323" y="422">Item three</text>
        <text x="138" y="323">EXTERNAL</text><text x="138" y="335">SYSTEMS</text>
      </g>
    </svg>
  </div>
</div></section>

<script>
(() => {
  const C = 300, H = 230 / Math.SQRT2, h = 76 / Math.SQRT2;          // outer & inner half-sides (pre-rotation)
  const O = { tl:[C-H,C-H], tr:[C+H,C-H], br:[C+H,C+H], bl:[C-H,C+H] };
  const I = { tl:[C-h,C-h], tr:[C+h,C-h], br:[C+h,C+h], bl:[C-h,C+h] };
  const mid = (a,b) => [(a[0]+b[0])/2,(a[1]+b[1])/2];
  const pts = (...p) => p.map(q => q.join(',')).join(' ');
  const $ = id => document.getElementById(id), NS = 'http://www.w3.org/2000/svg';
  const mk = (parent, d, extra={}) => { const p = document.createElementNS(NS,'path'); p.setAttribute('d', d); p.setAttribute('pathLength', 1);
    p.setAttribute('stroke-dasharray', 1); p.setAttribute('stroke-dashoffset', 1); for (const k in extra) p.setAttribute(k, extra[k]); parent.appendChild(p); return p; };
  const M = (a,b) => `M${a[0]} ${a[1]}L${b[0]} ${b[1]}`;

  // sides: top(tl→tr)=final "upper-right", right(tr→br)=final "lower-right", bottom(br→bl)=final "lower-left" (dashed), left(bl→tl)=final "upper-left"
  const sides = { top:[O.tl,O.tr], right:[O.tr,O.br], bottom:[O.br,O.bl], left:[O.bl,O.tl] };
  const sideGroups = {};
  for (const [k,[a,b]] of Object.entries(sides)) { const g = document.createElementNS(NS,'g'); $('outer').appendChild(g); sideGroups[k]=g;
    const m = mid(a,b); mk(g, M(a,m)); mk(g, M(b,m)); }
  $('dashEdge').setAttribute('d', M(O.br,O.bl));
  [[I.tl,I.tr],[I.tr,I.br],[I.br,I.bl],[I.bl,I.tl]].forEach(([a,b]) => mk($('inner'), M(a,b)));
  const spokes = [[I.tl,O.tl],[I.tr,O.tr],[I.bl,O.bl]].map(([a,b]) => mk($('spokes'), M(a,b)));
  $('dashSpoke').setAttribute('d', M(I.br,O.br));
  $('fPerf').setAttribute('points', pts(O.tl,O.bl,I.bl,I.tl));
  $('fInt').setAttribute('points',  pts(O.tl,O.tr,I.tr,I.tl));
  $('fCtx').setAttribute('points',  pts(O.tr,O.br,I.br,I.tr));
  $('fAg').setAttribute('points',   pts(I.tl,I.tr,I.br,I.bl));

  const clamp = (v,a=0,b=1) => Math.min(b,Math.max(a,v));
  const seg = (p,a,b) => clamp((p-a)/(b-a));                   // local 0..1 inside [a,b]
  const ease = t => 1 - Math.pow(1-t,3);
  const runway = $('platRunway'), reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function render(p){
    // 1) draw .00–.15
    const d = ease(seg(p,0,.15));
    $('outer').querySelectorAll('path').forEach(x => x.setAttribute('stroke-dashoffset', 1-d));
    $('inner').querySelectorAll('path').forEach((x,i) => x.setAttribute('stroke-dashoffset', 1-clamp(d*2-i*.35)));
    // 2) rotate .15–.45 (+ spokes)
    const r = ease(seg(p,.15,.45));
    $('rot').setAttribute('transform', `rotate(${45*r} ${C} ${C})`);
    spokes.forEach(s => s.setAttribute('stroke-dashoffset', 1-seg(p,.25,.45)));
    // 3) fills .45–.65 staggered; lower-left becomes dashed
    $('fPerf').setAttribute('opacity', seg(p,.45,.57)); $('fAg').setAttribute('opacity', seg(p,.45,.57));
    $('fInt').setAttribute('opacity', seg(p,.49,.61));  $('fCtx').setAttribute('opacity', seg(p,.53,.65));
    sideGroups.bottom.setAttribute('opacity', 1-seg(p,.5,.62));
    $('dashEdge').setAttribute('opacity', seg(p,.5,.62)); $('dashSpoke').setAttribute('opacity', seg(p,.5,.62));
    // 4) labels .65–.80
    $('labels').setAttribute('opacity', seg(p,.65,.8));
  }
  function progress(){
    const r = runway.getBoundingClientRect(), vh = innerHeight;
    // 0 when the runway top hits 80% of the viewport, 1 when ~60% of the runway has scrolled past the top
    return clamp((vh*.8 - r.top) / (r.height*.6 + vh*.3));
  }
  if (reduce) { render(1); return; }
  let ticking = false;
  const onScroll = () => { if (!ticking) { ticking = true; requestAnimationFrame(() => { render(progress()); ticking = false; }); } };
  addEventListener('scroll', onScroll, { passive:true }); addEventListener('resize', onScroll); onScroll();
})();
</script>
```

### 3.9 Industries rail (bleed, snap, drag, prev/next, dot pager, hover caption)

```html
<style>
  .rail-wrap{container-type:inline-size;max-width:var(--container);margin:auto;padding-inline:var(--gutter)}
  .rail{--rail-gutter:max(20px,calc((100vw - 1440px)/2 + 20px));--card:calc((100cqw - 12px)/1.2);
    margin-left:calc(var(--rail-gutter)*-1);width:calc(100% + 2*var(--rail-gutter));padding-inline:var(--rail-gutter);scroll-padding-inline:var(--rail-gutter);
    display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x proximity;overscroll-behavior-x:contain;scrollbar-width:none;cursor:grab;user-select:none}
  .rail::-webkit-scrollbar{display:none} .rail.dragging{cursor:grabbing;scroll-snap-type:none}
  @media (min-width:768px){.rail{--rail-gutter:max(48px,calc((100vw - 1440px)/2 + 48px));--card:calc((100cqw - 48px)/3);gap:24px}}
  @media (min-width:1024px){.rail{--card:calc((100cqw - 72px)/4)}}
  .sector{position:relative;flex:none;width:var(--card);aspect-ratio:1;overflow:hidden;background:var(--cell);scroll-snap-align:start;color:#fff}
  .sector img{width:100%;height:100%;object-fit:cover;pointer-events:none}
  .sector .grain{position:absolute;inset:0;display:none;opacity:.16;mix-blend-mode:overlay;background-size:140px 140px;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E")}
  @media (min-width:1024px){.sector .grain{display:block}}
  .sector .shade{position:absolute;inset:0;background:linear-gradient(rgb(18 16 14 / .1) 40%,rgb(18 16 14 / .9))}
  .sector .idx{position:absolute;left:18px;top:18px;font:400 10px var(--font-mono);letter-spacing:.14em}
  .sector .txt{position:absolute;left:18px;bottom:18px;right:18px}
  .sector .ttl{font:400 18px var(--font-body);letter-spacing:-.015em}
  .sector .cap{display:grid;grid-template-rows:0fr;opacity:0;transition:grid-template-rows .3s var(--ease-brand),opacity .3s var(--ease-brand)}
  .sector .cap>div{min-height:0;overflow:hidden;margin-top:6px;font:400 10px var(--font-mono);text-transform:uppercase;letter-spacing:.08em;color:var(--stone)}
  @media (min-width:768px){.sector .ttl{font-size:21px}}
  @media (min-width:1024px){.sector .idx,.sector .txt{left:24px}.sector .idx{top:24px;font-size:11px}.sector .txt{bottom:24px}.sector:hover .cap{grid-template-rows:1fr;opacity:1}}
  @media (max-width:1023px){.sector.is-colored .cap{grid-template-rows:1fr;opacity:1}}
  .rail-ctl{display:flex;justify-content:flex-end;gap:8px;margin-top:24px}
  .rail-ctl .nav-btn{width:44px;height:44px;border:1px solid var(--line-strong);display:grid;place-items:center;transition:opacity .2s}
  .rail-ctl .nav-btn:disabled{opacity:.35;cursor:default}
  .dots{display:flex;align-items:center;gap:6px;padding:0 16px;border:1px solid var(--line-strong)}
  .dots button{position:relative;width:6px;height:6px;background:var(--stone)} .dots button::before{content:"";position:absolute;inset:-8px}
  .dots button[aria-current=true]{background:var(--ink-strong)}
</style>
<div class="rail-wrap">
  <div class="rail" id="rail">
    <a class="sector" href="#"><img src="https://picsum.photos/seed/i1/700/700" alt=""><span class="grain"></span><span class="shade"></span><span class="idx">01</span>
      <span class="txt"><span class="ttl">[INDUSTRY]</span><span class="cap"><div>Use case · use case</div></span></span></a>
    <!-- repeat 8× -->
  </div>
  <div class="rail-ctl"><button class="nav-btn" id="prev" aria-label="Previous">←</button><div class="dots" id="dots"></div><button class="nav-btn" id="next" aria-label="Next">→</button></div>
</div>
<script>
(() => {
  const rail = document.getElementById('rail'), cards = [...rail.children], dots = document.getElementById('dots');
  const step = () => cards[0].getBoundingClientRect().width + parseFloat(getComputedStyle(rail).columnGap || 12);
  const positions = () => { const n = Math.max(1, cards.length - Math.round(rail.clientWidth / step()) + 1); return Math.min(cards.length, n); };
  function buildDots(){ dots.innerHTML=''; for (let i=0;i<positions();i++){ const b=document.createElement('button');
    b.setAttribute('aria-label', 'Go to ' + (cards[i].querySelector('.ttl')?.textContent || i+1)); b.onclick=()=>rail.scrollTo({left:i*step(),behavior:'smooth'}); dots.appendChild(b);} sync(); }
  function sync(){ const i = Math.round(rail.scrollLeft / step()); [...dots.children].forEach((d,k)=>d.setAttribute('aria-current', String(k===i)));
    document.getElementById('prev').disabled = rail.scrollLeft < 4; document.getElementById('next').disabled = rail.scrollLeft > rail.scrollWidth - rail.clientWidth - 4; }
  document.getElementById('prev').onclick = () => rail.scrollBy({left:-step(),behavior:'smooth'});
  document.getElementById('next').onclick = () => rail.scrollBy({left: step(),behavior:'smooth'});
  rail.addEventListener('scroll', () => requestAnimationFrame(sync), {passive:true});
  addEventListener('resize', buildDots); buildDots();
  // drag to scroll (mouse/pen only; touch keeps native momentum)
  let x0, s0, moved=false;
  rail.addEventListener('pointerdown', e => { if (e.pointerType==='touch') return; x0=e.clientX; s0=rail.scrollLeft; moved=false; rail.setPointerCapture(e.pointerId); rail.classList.add('dragging'); });
  rail.addEventListener('pointermove', e => { if (x0==null) return; const dx=e.clientX-x0; if (Math.abs(dx)>3) moved=true; rail.scrollLeft = s0 - dx; });
  const end = () => { if (x0==null) return; x0=null; rail.classList.remove('dragging'); rail.scrollTo({left:Math.round(rail.scrollLeft/step())*step(),behavior:'smooth'}); };
  rail.addEventListener('pointerup', end); rail.addEventListener('pointercancel', end);
  rail.addEventListener('click', e => { if (moved) { e.preventDefault(); moved=false; } }, true);
  // in-view colouring (mobile caption)
  const io = new IntersectionObserver(es => es.forEach(en => en.target.classList.toggle('is-colored', en.intersectionRatio > .6)), {root:rail, threshold:[0,.6,1]});
  cards.forEach(c => io.observe(c));
})();
</script>
```

### 3.10 Pillars panel + stat counters

```html
<style>
  .pillars{background:var(--stone);padding:120px 0}
  .panel{display:grid;background:var(--line-strong);gap:1px;border:1px solid var(--line-strong)}
  .panel__row{display:grid;gap:1px;grid-template-columns:1fr}
  @media (min-width:768px){.panel__row--3{grid-template-columns:repeat(3,1fr)}}
  .panel__row--4{grid-template-columns:repeat(2,1fr)} @media (min-width:1024px){.panel__row--4{grid-template-columns:repeat(4,1fr)}}
  .panel__cell{background:var(--signal);padding:36px}
  .panel__lab{display:flex;align-items:center;gap:8px;font:400 11px var(--font-mono);text-transform:uppercase;letter-spacing:.04em;color:var(--ink-3)}
  .panel__cell h3{margin:24px 0 14px;font:400 21px/1.15 var(--font-body);letter-spacing:-.01em}
  .panel__cell p{margin:0;font-size:14.5px;line-height:1.65;color:var(--ink-1)}
  .stat{font:400 34px/1.5 var(--font-body);letter-spacing:.005em;font-variant-numeric:tabular-nums} @media (min-width:768px){.stat{font-size:40px}}
  .stat-lab{margin-top:8px;font:400 10px var(--font-mono);text-transform:uppercase;letter-spacing:.12em;color:var(--ink-3)}
</style>
<section class="pillars"><div class="container">
  <h2 style="font:400 var(--fs-h2)/1.04 var(--font-body);letter-spacing:-.025em;margin:0 0 56px;max-width:12em">We take on the work that can't fail.</h2>
  <div class="panel" data-reveal>
    <div class="panel__row panel__row--3">
      <div class="panel__cell"><div class="panel__lab"><i class="bullet-sq"></i>Depth</div><h3>Messy processes, handled</h3><p>Two lines on granular logic for real-world exceptions.</p></div>
      <div class="panel__cell"><div class="panel__lab"><i class="bullet-sq"></i>Ownership</div><h3>Built around you</h3><p>Two lines on a transparent, fully custom setup wired into your stack.</p></div>
      <div class="panel__cell"><div class="panel__lab"><i class="bullet-sq"></i>Breadth</div><h3>Learning that spreads</h3><p>Two lines on improvements in one place lifting every agent.</p></div>
    </div>
    <div class="panel__row panel__row--4" id="stats">
      <div class="panel__cell"><div class="stat"><span data-count="15">15</span><span>M+</span></div><div class="stat-lab">Conversations / month</div></div>
      <div class="panel__cell"><div class="stat"><span data-count="70">70</span><span>%+</span></div><div class="stat-lab">Resolved without humans</div></div>
      <div class="panel__cell"><div class="stat"><span data-count="75">75</span><span>%</span></div><div class="stat-lab">Lower cost</div></div>
      <div class="panel__cell"><div class="stat"><span data-count="10">10</span><span>X</span></div><div class="stat-lab">More capacity</div></div>
    </div>
  </div>
</div></section>
<script>
(() => {
  const nums = [...document.querySelectorAll('#stats [data-count]')];
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;          // keep SSR final values
  const fmt = new Intl.NumberFormat('en-US');
  const io = new IntersectionObserver(([e]) => { if (!e.isIntersecting) return; io.disconnect();
    const t0 = performance.now(), D = 1200, easeOutCubic = t => 1 - Math.pow(1 - t, 3);
    nums.forEach(n => n.textContent = '0');
    (function tick(now){ const t = Math.min(1, (now - t0) / D), k = easeOutCubic(t);
      nums.forEach(n => n.textContent = fmt.format(Math.round(+n.dataset.count * k)));
      if (t < 1) requestAnimationFrame(tick); })(t0);
  }, { threshold: .2 });
  io.observe(document.getElementById('stats'));
})();
</script>
```

### 3.11 Lazy looping video teaser (multiply-blended)

```html
<div style="position:relative;aspect-ratio:1;max-width:400px">
  <video class="teaser" muted loop playsinline preload="none" poster="/media/teaser-poster.jpg"
         style="position:absolute;left:50%;top:50%;width:112%;max-width:none;transform:translate(-50%,-50%);mix-blend-mode:multiply;pointer-events:none">
    <source src="/media/teaser-loop.mp4" type="video/mp4"></video>
</div>
<script>
document.querySelectorAll('video.teaser').forEach(v => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;          // poster only
  new IntersectionObserver(([e]) => e.isIntersecting ? v.play().catch(()=>{}) : v.pause(), { threshold: .25 }).observe(v);
});
</script>
```

### 3.12 Closing CTA band (vw lattice collage)

```html
<style>
  .cta{--cell:7.93vw;position:relative;isolation:isolate;overflow:hidden;min-height:34.23vw;
    background:linear-gradient(98deg,#dcd7d2 0%,#f0eeeb 48%,#fff 100%)}
  .cta__content{position:relative;z-index:1;padding:8.22vw calc(48px + max(0px,50vw - 824px)) 6.9vw}
  .cta h2{max-width:min(71.24vw,1200px);margin:0;font:400 44px/1.04 var(--font-body);letter-spacing:-.055em;color:transparent;-webkit-background-clip:text;background-clip:text;
    background-image:linear-gradient(105deg,#070707 0%,#2e2e2e 55%,#736f6a 100%)}
  @media (min-width:64rem){.cta h2{font-size:76px;background-image:repeating-linear-gradient(105deg,#070707 var(--gx,8%),#736f6a calc(var(--gx,8%) + 60%),#070707 calc(var(--gx,8%) + 120%))}}
  @media (min-width:80rem){.cta h2{font-size:clamp(84px,5.95vw,112px)}}
  .cta .inline-form{width:480px;max-width:100%;margin-top:4.1vw}
  .cta .inline-form :is(input,button){height:44px;padding-block:0}
  .cta__art{position:absolute;right:6vw;top:0;display:grid;grid-template-columns:repeat(4,var(--cell));grid-auto-rows:var(--cell);z-index:0}
  .cta__art>*{border:1px solid rgb(46 46 46 / .18);margin:-1px 0 0 -1px} .cta__art img{width:100%;height:100%;object-fit:cover}
  @media (max-width:767px){.cta__art{opacity:.25}}
</style>
<section class="cta">
  <div class="cta__art" aria-hidden="true"><i></i><i></i><i style="grid-column:4;grid-row:2"><img src="https://picsum.photos/seed/c1/200/200" alt=""></i><i style="grid-column:3;grid-row:4"><img src="https://picsum.photos/seed/c2/200/200" alt=""></i><i style="grid-column:3;grid-row:3"></i><i style="grid-column:4;grid-row:3"></i></div>
  <div class="cta__content"><h2 class="glow-cta">Bring [PRODUCT] into your operation.</h2>
    <form class="inline-form" novalidate><label class="sr-only" for="ctaEmail">Work email</label><input id="ctaEmail" type="email" placeholder="Your work email" required><button class="btn">Book a call</button></form></div>
</section>
<script>document.querySelectorAll('.glow-cta').forEach(h=>h.addEventListener('pointermove',e=>{const r=h.getBoundingClientRect();h.style.setProperty('--gx',(e.clientX-r.left)+'px')}));</script>
```

### 3.13 Footer language selector (listbox) + compliance chips

```html
<style>
  .chips-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .cbadge{border:1px solid var(--line);padding:5px 11px;font:400 10px var(--font-mono);letter-spacing:.06em}
  .lang{position:relative}
  .lang>button{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);padding:5px 11px;font:400 10px var(--font-body);letter-spacing:.06em}
  .lang ul{position:absolute;bottom:100%;right:0;margin:0 0 4px;padding:0;list-style:none;min-width:10rem;background:var(--hull-white);border:1px solid var(--line);box-shadow:0 10px 15px -3px rgb(0 0 0 / .1);display:none}
  .lang.open ul{display:block}
  .lang li{display:flex;justify-content:space-between;padding:8px 14px;font-size:13px;color:var(--ink-4);cursor:pointer}
  .lang li[aria-selected=true]{color:var(--ink-strong);background:var(--signal)} .lang li:focus{outline:2px solid var(--rust);outline-offset:-2px}
</style>
<div class="chips-row"><span class="cbadge">SOC 2</span><span class="cbadge">ISO 27001</span><span class="cbadge">GDPR</span>
  <span style="width:1px;height:24px;background:var(--line)"></span>
  <div class="lang"><button aria-haspopup="listbox" aria-expanded="false">English <span>▾</span></button>
    <ul role="listbox" tabindex="-1"><li role="option" aria-selected="true" tabindex="0">English <span>✓</span></li><li role="option" aria-selected="false" tabindex="-1">Español</li><li role="option" aria-selected="false" tabindex="-1">Français</li></ul></div></div>
<script>
document.querySelectorAll('.lang').forEach(l => {
  const b = l.querySelector('button'), opts = [...l.querySelectorAll('[role=option]')];
  const set = o => { l.classList.toggle('open', o); b.setAttribute('aria-expanded', String(o)); if (o) (opts.find(x=>x.getAttribute('aria-selected')==='true')||opts[0]).focus(); };
  b.onclick = () => set(!l.classList.contains('open'));
  l.addEventListener('keydown', e => { const i = opts.indexOf(document.activeElement);
    if (e.key==='Escape'){ set(false); b.focus(); }
    if (e.key==='ArrowDown'){ e.preventDefault(); opts[Math.min(opts.length-1,i+1)]?.focus(); }
    if (e.key==='ArrowUp'){ e.preventDefault(); opts[Math.max(0,i-1)]?.focus(); }
    if (e.key==='Enter'&&i>-1){ opts[i].click(); } });
  opts.forEach(o => o.onclick = () => { opts.forEach(x=>x.setAttribute('aria-selected','false')); o.setAttribute('aria-selected','true'); b.firstChild.textContent = o.firstChild.textContent.trim()+' '; set(false); b.focus(); });
  document.addEventListener('click', e => { if (!l.contains(e.target)) set(false); });
});
</script>
```

### 3.14 FAQ accordion (grid-rows, plus→minus)

```html
<style>
  .faq-item{border-top:1px solid var(--line)} .faq-item:last-child{border-bottom:1px solid var(--line)}
  .faq-q{display:flex;width:100%;gap:20px;align-items:flex-start;padding:24px 0;text-align:left}
  @media (min-width:768px){.faq-q{gap:32px;padding:28px 0}}
  .faq-q .sq{margin-top:.55em;width:5px;height:5px;border:1px solid var(--ink-3);flex:none;transition:background .3s,border-color .3s}
  .faq-q:hover .sq,.faq-q[aria-expanded=true] .sq{border-color:var(--ink-strong)} .faq-q[aria-expanded=true] .sq{background:var(--ink-strong)}
  .faq-q .t{flex:1;font:400 18px/1.25 var(--font-body);letter-spacing:-.01em;text-wrap:pretty}
  .faq-q .pm{position:relative;margin-top:.35em;width:12px;height:12px;flex:none;color:var(--ink-3);transition:color .3s}
  .faq-q:hover .pm{color:var(--ink-strong)}
  .faq-q .pm::before,.faq-q .pm::after{content:"";position:absolute;background:currentColor}
  .faq-q .pm::before{left:0;top:50%;width:12px;height:1px;transform:translateY(-50%)}
  .faq-q .pm::after{left:50%;top:0;width:1px;height:12px;transform:translateX(-50%);transition:transform .5s var(--ease-out-soft)}
  .faq-q[aria-expanded=true] .pm::after{transform:translateX(-50%) rotate(90deg) scaleY(0)}
  .faq-a{display:grid;grid-template-rows:0fr;margin:0 32px 0 calc(5px + 1.25rem);transition:grid-template-rows .5s var(--ease-out-soft)}
  @media (min-width:768px){.faq-a{margin-left:calc(5px + 2rem)}}
  .faq-a.open{grid-template-rows:1fr} .faq-a>div{min-height:0;overflow:hidden} .faq-a p{margin:0 0 28px;color:var(--ink-3);line-height:1.6}
  @media (prefers-reduced-motion:reduce){.faq-a,.faq-q .pm::after{transition:none}}
</style>
<div class="faq">
  <div class="faq-item"><button class="faq-q" aria-expanded="false" aria-controls="a1" id="q1"><span class="sq"></span><span class="t">What does [PRODUCT] replace?</span><span class="pm"></span></button>
    <div class="faq-a" id="a1" role="region" aria-labelledby="q1"><div><p>Two or three sentences of answer.</p></div></div></div>
</div>
<script>
document.querySelectorAll('.faq-q').forEach(q => q.addEventListener('click', () => {
  const o = q.getAttribute('aria-expanded') !== 'true'; q.setAttribute('aria-expanded', String(o));
  document.getElementById(q.getAttribute('aria-controls')).classList.toggle('open', o);
}));
</script>
```

### 3.15 Sticky mini-diagram with scroll-spy (Platform overview pattern)

```html
<style>
  .spy{display:grid;gap:40px;max-width:var(--container);margin:auto;padding:112px var(--gutter)}
  @media (min-width:768px){.spy{grid-template-columns:280px minmax(0,1fr);gap:56px}.spy__rail{position:sticky;top:20vh;align-self:start}}
  .mini{width:240px;height:auto;overflow:visible}
  .mini .q{fill:transparent;transition:fill .4s var(--ease-brand)} .mini .q.on{fill:#d9d9d9}
  .mini path{fill:none;stroke:var(--ink-3);stroke-width:1;stroke-dasharray:2 3}
  .mini .lead{stroke:var(--ink-strong);stroke-dasharray:none;transition:d .45s var(--ease-brand)}
  .spy__list{list-style:none;margin:24px 0 0;padding:0}
  .spy__list li{display:flex;gap:10px;align-items:baseline;padding:10px 0 10px 16px;color:var(--ink-4);font-size:15px;transition:color .3s;position:relative}
  .spy__list li small{font:400 10px var(--font-mono)} .spy__list li.on{color:var(--ink-strong)}
  .spy__list li.on::before{content:"";position:absolute;left:-2px;top:50%;width:10px;height:10px;margin-top:-5px;background:var(--rust)}
  .spy__block{min-height:80vh;padding-bottom:80px}
</style>
<div class="spy">
  <aside class="spy__rail">
    <svg class="mini" viewBox="0 0 240 240" aria-hidden="true">
      <polygon class="q" data-q="0" points="120,10 10,120 82,120 120,82"/>   <!-- upper-left -->
      <polygon class="q" data-q="1" points="120,10 230,120 158,120 120,82"/> <!-- upper-right -->
      <polygon class="q" data-q="2" points="230,120 120,230 120,158 158,120"/>
      <polygon class="q" data-q="3" points="120,82 158,120 120,158 82,120"/>
      <path d="M120 10 230 120 120 230 10 120Z M120 82 158 120 120 158 82 120Z M120 10V82 M230 120H158 M120 230V158 M10 120H82"/>
      <path class="lead" id="lead" d="M120 120 L0 240"/>
    </svg>
    <ol class="spy__list" id="spyList"><li class="on"><small>01</small>Layer one</li><li><small>02</small>Layer two</li><li><small>03</small>Layer three</li><li><small>04</small>Core</li></ol>
  </aside>
  <div><section class="spy__block" data-step="0"><h3>Layer one</h3><p>…</p></section><section class="spy__block" data-step="1"><h3>Layer two</h3></section><section class="spy__block" data-step="2"><h3>Layer three</h3></section><section class="spy__block" data-step="3"><h3>Core</h3></section></div>
</div>
<script>
(() => {
  const items = [...document.querySelectorAll('#spyList li')], qs = [...document.querySelectorAll('.mini .q')], lead = document.getElementById('lead');
  const centers = [[75,75],[165,75],[165,165],[120,120]];
  const set = i => { items.forEach((li,k)=>li.classList.toggle('on',k===i)); qs.forEach(q=>q.classList.toggle('on', +q.dataset.q===i));
    const [x,y] = centers[i]; lead.setAttribute('d', `M${x} ${y} L0 ${y + x} L0 ${262 + i*41}`); };  // diagonal to the left edge, then down to the active list row
  const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) set(+e.target.dataset.step); }), { rootMargin: '-45% 0px -50% 0px' });
  document.querySelectorAll('.spy__block').forEach(b => io.observe(b));
})();
</script>
```

### 3.16 Numbered stepper driving a layer diagram (orchestration "How it works")

```html
<style>
  .stepper{display:grid;gap:40px} @media (min-width:1024px){.stepper{grid-template-columns:1fr 1fr;gap:64px}}
  .steps{display:flex;gap:4px;border-top:1px solid var(--line);padding-top:24px}
  .steps button{position:relative;padding:4px 10px;font:400 12px/1 var(--font-mono);font-variant-numeric:tabular-nums;letter-spacing:.04em;color:var(--ink-4);border:1px solid transparent;transition:color .3s cubic-bezier(.25,.1,.25,1),border-color .3s}
  .steps button[aria-current=step]{color:var(--ink-strong);border-color:var(--ink-strong)}
  .steps button[aria-current=step]::after{content:"";position:absolute;left:10px;top:calc(100% + 6px);width:6px;height:6px;background:var(--rust)}
  .step-copy h3{margin:40px 0 12px;font:500 26px var(--font-body)} .step-copy p{margin:0;font-size:16px;line-height:1.45;color:var(--ink-1)}
  .layers{border-top:1px solid var(--line);padding-top:24px}
  .layers svg{width:100%} .layers text{font:400 11px var(--font-body);fill:var(--ink-strong)}
  .layers circle{fill:#cfcfcf} .layers .hot{fill:var(--obsidian)}
  #token{transition:transform .5s var(--ease-brand)}
</style>
<div class="stepper">
  <div><div class="steps" id="steps"></div><div class="step-copy" aria-live="polite"><h3 id="stTitle"></h3><p id="stText"></p></div></div>
  <div class="layers"><svg id="layerSvg" viewBox="0 0 460 200"></svg></div>
</div>
<script>
(() => {
  const data = [
    {t:'Detect',      x:'One sentence on watching live signals across every layer.', row:-1, col:6},
    {t:'Diagnose',    x:'One sentence on narrowing the cause.',                       row:0,  col:3},
    {t:'Trace: Layer B', x:'…', row:0, col:7}, {t:'Trace: Layer C', x:'…', row:1, col:4},
    {t:'Trace: Layer A', x:'…', row:2, col:6}, {t:'Trace: Core', x:'…', row:3, col:8},
    {t:'Root cause', x:'…', row:3, col:2}, {t:'Ship the fix', x:'…', row:-1, col:6}];
  const rows = ['Layer B','Layer C','Layer A','Core'], NS='http://www.w3.org/2000/svg', svg=document.getElementById('layerSvg');
  const el=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);svg.appendChild(e);return e};
  el('text',{x:216,y:16}).textContent='[PRODUCT]';
  rows.forEach((r,i)=>{ const y=48+i*38; el('text',{x:0,y:y-8}).textContent=r; el('line',{x1:60,x2:455,y1:y,y2:y,stroke:'#e5e5e5'});
    for(let c=0;c<12;c++) el('circle',{cx:60+c*36,cy:y,r:2}); });
  const token = el('rect',{id:'token',x:-4,y:-4,width:8,height:8,fill:'var(--rust)'});
  const wrap = document.getElementById('steps');
  data.forEach((d,i)=>{ const b=document.createElement('button'); b.textContent=String(i+1).padStart(2,'0'); b.title=d.t; b.onclick=()=>go(i); wrap.appendChild(b); });
  function go(i){ const d=data[i]; [...wrap.children].forEach((b,k)=>k===i?b.setAttribute('aria-current','step'):b.removeAttribute('aria-current'));
    document.getElementById('stTitle').textContent=d.t; document.getElementById('stText').textContent=d.x;
    const x = d.row<0 ? 230 : 60+d.col*36, y = d.row<0 ? 26 : 48+d.row*38; token.style.transform=`translate(${x}px,${y}px)`; }
  go(1);
})();
</script>
```

### 3.17 Pinned pyramid scrollytelling (canvas 2D + step text + live counter)

```html
<style>
  .pyr{--steps:5;position:relative;height:calc(var(--steps) * 100vh + 100vh);background:#070707;color:#fff}
  .pyr__pin{position:sticky;top:0;height:100vh;overflow:hidden;display:grid;align-content:center;gap:32px;padding:92px var(--gutter) 24px;max-width:var(--container);margin:auto}
  @media (min-width:1024px){.pyr__pin{grid-template-columns:1fr 1fr;gap:64px}}
  .pyr__step{position:relative;min-height:5em}
  .pyr__step p{position:absolute;inset:0;margin:0;font-size:17px;line-height:1.6;color:#c7beb2;opacity:0;transform:translateY(8px);transition:opacity .45s var(--ease-brand),transform .45s var(--ease-brand)}
  .pyr__step p.on{opacity:1;transform:none}
  .pyr__count{margin-top:24px;padding-top:16px;border-top:1px solid #1f1f1f;font:400 34px var(--font-body);font-variant-numeric:tabular-nums}
  .pyr__count small{margin-left:12px;font:400 11px var(--font-mono);letter-spacing:.08em;color:#9c9288}
  canvas#pyr{width:100%;aspect-ratio:1/1;max-height:70vh}
</style>
<section class="pyr" id="pyrSec">
  <div class="pyr__pin">
    <div>
      <p class="mono" style="color:#9c9288">03 · Chapter label</p>
      <h2 style="font:400 var(--fs-h2)/1.04 var(--font-body);margin:0 0 48px">Agents climb the ladder of complexity</h2>
      <p class="mono" id="pyrIdx" style="color:#d59566">01 / 05</p>
      <div class="pyr__step" id="pyrText"><p class="on">Step one statement.</p><p>Step two statement.</p><p>Step three statement.</p><p>Step four statement.</p><p>Step five statement.</p></div>
    </div>
    <div><canvas id="pyr"></canvas><div class="pyr__count"><span id="pyrN">0</span><small>AGENTS</small></div></div>
  </div>
</section>
<script>
(() => {
  const sec = document.getElementById('pyrSec'), cv = document.getElementById('pyr'), ctx = cv.getContext('2d');
  const texts = [...document.querySelectorAll('#pyrText p')], idx = document.getElementById('pyrIdx'), nEl = document.getElementById('pyrN');
  const COLS = 36, ROWS = 18, fmt = new Intl.NumberFormat('en-US');
  const counts = [180, 260, 7400, 9200, 10300];                       // counter keyframes per step (placeholders)
  // lit threshold per cell: pyramid shape, lower rows light first, left columns light first in early steps
  const cells = []; for (let r=0;r<ROWS;r++) for (let c=0;c<COLS;c++){ const fromBottom = ROWS-1-r; const half = (ROWS-fromBottom)*(COLS/2)/ROWS;
    const inPyr = Math.abs(c - COLS/2 + .5) < half; if (!inPyr) { cells.push({r,c,t:9}); continue; }
    const t = fromBottom/ROWS*0.65 + (c/COLS)*0.35*(fromBottom<6?1:0.2); cells.push({r,c,t}); }
  function size(){ const d = devicePixelRatio||1, w = cv.clientWidth; cv.width = w*d; cv.height = w*d; ctx.setTransform(d,0,0,d,0,0); }
  function draw(p){ const w = cv.clientWidth, cell = w/COLS, gap = cell*.18; ctx.clearRect(0,0,w,w);
    const lit = p*1.05;                                               // 0..1 progress maps onto threshold t
    for (const k of cells){ const x = k.c*cell, y = k.r*cell*0.9 + w*.05; const on = k.t <= lit;
      ctx.fillStyle = k.t>1 ? '#141414' : on ? `rgba(224,218,210,${.55 + .45*Math.min(1,(lit-k.t)*6)})` : '#1d1d1d';
      ctx.fillRect(x+gap/2, y+gap/2, cell-gap, cell*0.9-gap); }
    ctx.strokeStyle = '#3a3a3a'; ctx.setLineDash([3,3]);
    [ROWS*.33, ROWS*.66].forEach(r => { const y = r*cell*0.9 + w*.05; ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(w,y); ctx.stroke(); });
    ctx.setLineDash([]); }
  const clamp = v => Math.max(0,Math.min(1,v));
  function update(){ const r = sec.getBoundingClientRect(), p = clamp(-r.top / (r.height - innerHeight));
    const steps = texts.length, s = Math.min(steps-1, Math.floor(p*steps));
    texts.forEach((t,i)=>t.classList.toggle('on', i===s)); idx.textContent = `${String(s+1).padStart(2,'0')} / ${String(steps).padStart(2,'0')}`;
    const f = p*(steps-1), i0 = Math.floor(f), i1 = Math.min(steps-1,i0+1);
    nEl.textContent = fmt.format(Math.round(counts[i0] + (counts[i1]-counts[i0])*(f-i0)));
    draw(p); }
  size(); update(); addEventListener('resize', () => { size(); update(); });
  addEventListener('scroll', () => requestAnimationFrame(update), { passive:true });
})();
</script>
```

### 3.18 Dotted globe on canvas (ops console / offices list)

```html
<style>
  .offices{display:grid;gap:32px} @media (min-width:1024px){.offices{grid-template-columns:420px 1fr;gap:64px}}
  .offices ol{list-style:none;margin:0;padding:0;counter-reset:o}
  .offices li{display:grid;grid-template-columns:52px 1fr auto 14px;align-items:center;gap:8px;padding:14px 0;border-top:1px solid var(--line);cursor:pointer;color:var(--ink-4);transition:color .3s}
  .offices li::before{counter-increment:o;content:counter(o,decimal-leading-zero);font:400 11px var(--font-mono)}
  .offices li .city{font-size:20px;letter-spacing:-.01em} .offices li .ctry{font:400 10px var(--font-mono);letter-spacing:.08em}
  .offices li .sq{width:7px;height:7px;border:1px solid var(--rust)} .offices li.on{color:var(--ink-strong)} .offices li.on .sq{background:var(--rust)}
  .globe-box{border:1px solid var(--line);aspect-ratio:1;display:grid;place-items:center}
  #globe{width:92%;aspect-ratio:1}
</style>
<div class="offices">
  <ol id="cities">
    <li data-lat="37.77" data-lon="-122.42"><span class="city">City one</span><span class="ctry">COUNTRY</span><span class="sq"></span></li>
    <li data-lat="40.71" data-lon="-74.0"><span class="city">City two</span><span class="ctry">COUNTRY</span><span class="sq"></span></li>
    <li data-lat="51.5" data-lon="-0.12"><span class="city">City three</span><span class="ctry">COUNTRY</span><span class="sq"></span></li>
    <li data-lat="40.42" data-lon="-3.7"><span class="city">City four</span><span class="ctry">COUNTRY</span><span class="sq"></span></li>
    <li data-lat="-23.55" data-lon="-46.63"><span class="city">City five</span><span class="ctry">COUNTRY</span><span class="sq"></span></li>
  </ol>
  <div class="globe-box"><canvas id="globe" aria-hidden="true"></canvas></div>
</div>
<script>
(() => {
  const cv = document.getElementById('globe'), ctx = cv.getContext('2d'), list = [...document.querySelectorAll('#cities li')];
  // Land test: plug a real land mask here (e.g. sample a 360×180 equirectangular PNG). Fallback = rough blobs so the demo renders.
  const blobs = [[45,-100,28,40],[-15,-60,25,18],[50,15,18,30],[5,20,30,22],[50,90,22,55],[-25,135,12,20]];
  const isLand = (lat,lon) => blobs.some(([a,b,ra,rb]) => ((lat-a)/ra)**2 + ((((lon-b+540)%360)-180)/rb)**2 < 1);
  const dots = []; const N = 5200, ga = Math.PI*(3-Math.sqrt(5));
  for (let i=0;i<N;i++){ const y = 1 - 2*(i+.5)/N, r = Math.sqrt(1-y*y), th = ga*i;
    const lat = Math.asin(y)*180/Math.PI, lon = (Math.atan2(Math.sin(th)*r, Math.cos(th)*r))*180/Math.PI;
    if (isLand(lat,lon)) dots.push([lat,lon]); }
  let rotLon = 0, rotLat = -15, tgtLon = 0, tgtLat = -15, active = 0, idleT;
  const toRad = d => d*Math.PI/180;
  function project(lat,lon,R,cx,cy){ const la=toRad(lat), lo=toRad(lon+rotLon), p=toRad(rotLat);
    const x = Math.cos(la)*Math.sin(lo), y = Math.sin(la), z = Math.cos(la)*Math.cos(lo);
    const y2 = y*Math.cos(p) - z*Math.sin(p), z2 = y*Math.sin(p) + z*Math.cos(p);
    return [cx + x*R, cy - y2*R, z2]; }
  function size(){ const d=devicePixelRatio||1, w=cv.clientWidth; cv.width=w*d; cv.height=w*d; ctx.setTransform(d,0,0,d,0,0); }
  function frame(){ rotLon += (tgtLon-rotLon)*.06; rotLat += (tgtLat-rotLat)*.06;
    const w = cv.clientWidth, R = w*.48, c = w/2; ctx.clearRect(0,0,w,w);
    ctx.strokeStyle='#cfcfcf'; ctx.beginPath(); ctx.arc(c,c,R,0,Math.PI*2); ctx.stroke();
    for (const [la,lo] of dots){ const [x,y,z] = project(la,lo,R,c,c); if (z<0) continue; ctx.fillStyle=`rgba(115,111,106,${.25+.6*z})`; ctx.fillRect(x-.9,y-.9,1.8,1.8); }
    list.forEach((li,i) => { const [x,y,z] = project(+li.dataset.lat,+li.dataset.lon,R,c,c); if (z<0) return;
      ctx.strokeStyle='#d59566'; ctx.lineWidth=1; ctx.strokeRect(x-4,y-4,8,8); if (i===active){ ctx.fillStyle='#d59566'; ctx.fillRect(x-4,y-4,8,8);
        ctx.fillStyle='#736f6a'; ctx.font='10px "Suisse Intl Mono", monospace'; ctx.fillText(li.querySelector('.city').textContent.toUpperCase(), x+10, y+3); } });
    requestAnimationFrame(frame); }
  function focus(i){ active=i; list.forEach((li,k)=>li.classList.toggle('on',k===i)); tgtLon = -list[i].dataset.lon; tgtLat = -list[i].dataset.lat*.6;
    // shortest path
    while (tgtLon - rotLon > 180) tgtLon -= 360; while (tgtLon - rotLon < -180) tgtLon += 360; }
  const cycle = () => { clearInterval(idleT); idleT = setInterval(() => focus((active+1)%list.length), 3500); };
  list.forEach((li,i) => { li.addEventListener('mouseenter', () => { focus(i); clearInterval(idleT); }); li.addEventListener('mouseleave', cycle); li.addEventListener('click', () => focus(i)); });
  size(); addEventListener('resize', size); focus(0); if (!matchMedia('(prefers-reduced-motion: reduce)').matches) cycle(); frame();
})();
</script>
```

### 3.19 Logo marquee (demo page)

```html
<style>
  .marquee{overflow:hidden;-webkit-mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent);mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent)}
  .marquee ul{display:flex;align-items:center;gap:48px;width:max-content;margin:0;padding:0;list-style:none;will-change:transform;animation:mq var(--mq-dur,32s) linear infinite}
  .marquee:hover ul{animation-play-state:paused}
  .marquee li{width:96px;height:28px;background:var(--concrete);-webkit-mask:var(--src) center/contain no-repeat;mask:var(--src) center/contain no-repeat}
  @keyframes mq{from{transform:translateX(0)}to{transform:translateX(-50%)}}
  @media (prefers-reduced-motion:reduce){.marquee ul{animation:none}}
</style>
<div class="marquee"><ul id="mq"><li style="--src:url(/logos/a.svg)"></li><li style="--src:url(/logos/b.svg)"></li><li style="--src:url(/logos/c.svg)"></li></ul></div>
<script>const u=document.getElementById('mq');u.innerHTML+=u.innerHTML;[...u.children].slice(u.children.length/2).forEach(li=>li.setAttribute('aria-hidden','true'));</script>
```

### 3.20 Client-side content filter (Hub / Blog listing)

```html
<div class="filters">
  <input id="q" type="search" placeholder="Search articles" style="border:1px solid var(--line);padding:10px 12px;width:min(380px,100%)">
  <div style="display:flex;gap:16px;margin-top:12px;font-size:14px"><span style="color:var(--ink-4)">Filter by category:</span>
    <button class="cat" data-cat="strategy">Strategy</button><button class="cat" data-cat="engineering">Engineering</button></div>
  <div style="display:flex;justify-content:space-between;margin-top:20px"><span id="count" aria-live="polite"></span>
    <select id="sort"><option value="new">Most recent</option><option value="old">Oldest</option></select></div>
</div>
<div id="posts" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:48px 16px;margin-top:24px">
  <article data-cat="strategy" data-date="2026-10-21"><h3>Post title</h3></article>
  <article data-cat="engineering" data-date="2026-09-02"><h3>Another title</h3></article>
</div>
<style>.cat{color:color-mix(in srgb,var(--ink-strong) 60%,transparent);transition:color .2s}.cat:hover{color:var(--ink-strong)}.cat[aria-pressed=true]{color:var(--ink-strong);font-weight:500}</style>
<script>
(() => {
  const posts=[...document.querySelectorAll('#posts article')], total=posts.length, q=document.getElementById('q'), sort=document.getElementById('sort'); let cat=null;
  document.querySelectorAll('.cat').forEach(b=>{ b.setAttribute('aria-pressed','false'); b.onclick=()=>{ cat = cat===b.dataset.cat?null:b.dataset.cat;
    document.querySelectorAll('.cat').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.cat===cat))); apply(); }; });
  function apply(){ const term=q.value.trim().toLowerCase(); let n=0;
    posts.sort((a,b)=> sort.value==='new' ? b.dataset.date.localeCompare(a.dataset.date) : a.dataset.date.localeCompare(b.dataset.date)).forEach(p=>p.parentNode.appendChild(p));
    posts.forEach(p=>{ const ok=(!cat||p.dataset.cat===cat)&&(!term||p.textContent.toLowerCase().includes(term)); p.hidden=!ok; if(ok)n++; });
    document.getElementById('count').textContent=`Showing ${n} results out of ${total}`; }
  q.addEventListener('input',apply); sort.addEventListener('change',apply); apply();
})();
</script>
```

### 3.21 Floating newsletter dialog (non-modal, scroll-triggered)

```html
<style>
  .nl{position:fixed;z-index:50;left:16px;right:16px;bottom:96px;max-width:24rem;padding:20px 20px 32px;background:var(--hull-white);border:1px solid rgb(14 13 12 / .1);
    box-shadow:0 10px 15px -3px rgb(0 0 0 / .1);font-size:14px;opacity:0;transform:translateY(12px);pointer-events:none;transition:opacity .35s var(--ease-brand),transform .35s var(--ease-brand)}
  @media (min-width:640px){.nl{left:auto;right:24px}}
  .nl.show{opacity:1;transform:none;pointer-events:auto}
  .nl input{width:100%;margin:14px 0 10px;padding:12px;border:1px solid var(--carbon);background:#fff}
  .nl button[type=submit]{width:100%;padding:12px;background:var(--obsidian);color:#fff;font:400 11px var(--font-mono);letter-spacing:.08em;text-transform:uppercase}
  .nl button[type=submit]:disabled{background:#e4e4e4;color:#a5a5a5}
</style>
<div class="nl" role="dialog" aria-modal="false" aria-labelledby="nlT">
  <button aria-label="Close" style="position:absolute;right:14px;top:12px">×</button>
  <strong id="nlT">Get our engineering notes</strong><p style="margin:6px 0 0;color:var(--ink-3)">New posts from the team, by email.</p>
  <form novalidate><input type="email" placeholder="you@company.com" aria-label="Email"><button type="submit" disabled>Subscribe</button></form>
  <p style="font-size:11px;color:var(--ink-4)">By subscribing you accept our privacy policy.</p>
</div>
<script>
(() => { const d=document.querySelector('.nl'), KEY='nl-dismissed'; let shown=false;
  try{ if(localStorage.getItem(KEY)) return; }catch(e){}
  addEventListener('scroll',()=>{ if(!shown && scrollY > document.body.scrollHeight*0.6){ shown=true; d.classList.add('show'); } },{passive:true});
  d.querySelector('[aria-label=Close]').onclick=()=>{ d.classList.remove('show'); try{localStorage.setItem(KEY,'1')}catch(e){} };
  const i=d.querySelector('input'), b=d.querySelector('[type=submit]'); i.addEventListener('input',()=>b.disabled=!i.checkValidity()||!i.value);
  d.querySelector('form').addEventListener('submit',e=>{ e.preventDefault(); /* send to your ESP */ });
})();
</script>
```

### 3.22 Simulated app window: tab rail + segmented toggle (ops console)

```html
<style>
  .app{border:1px solid var(--line);display:grid;grid-template-rows:auto 1fr;min-height:578px;background:#fff}
  .app__bar{display:flex;justify-content:space-between;padding:10px 16px;border-bottom:1px solid var(--line);font-size:12px}
  .app__body{display:grid;grid-template-columns:1fr} @media (min-width:640px){.app__body{grid-template-columns:128px minmax(0,1fr)}}
  .app__nav{border-right:1px solid var(--line);padding:12px 8px;display:flex;flex-direction:column;gap:4px}
  .app__nav button{text-align:left;padding:7px 8px;font-size:11px;color:var(--ink-1)} .app__nav button[aria-pressed=true]{background:var(--obsidian);color:#fff}
  .app__main{position:relative;background-image:radial-gradient(circle,#d9d9d9 1px,transparent 1.2px);background-size:16px 16px}
  .seg{display:inline-flex;border:1px solid var(--line);margin:12px} .seg button{padding:5px 10px;font-size:11px} .seg button[aria-pressed=true]{background:var(--obsidian);color:#fff}
  .view{position:absolute;inset:48px 0 0;opacity:0;transition:opacity .35s var(--ease-brand);pointer-events:none} .view.on{opacity:1;pointer-events:auto}
</style>
<div class="app">
  <div class="app__bar"><span>Workspace / <b>Ops</b></span><span>Build 12 <i class="bullet-sq"></i></span></div>
  <div class="app__body">
    <div class="app__nav" id="appNav"><button aria-pressed="false" data-v="overview">Overview</button><button aria-pressed="true" data-v="map">Live map</button><button aria-pressed="false" data-v="calls">Calls</button></div>
    <div class="app__main">
      <div class="seg" id="seg"><button aria-pressed="true" data-s="global">Global</button><button aria-pressed="false" data-s="region">Region</button></div>
      <div class="view" data-v="overview">…KPIs…</div><div class="view on" data-v="map">…canvas globe (3.18)…</div><div class="view" data-v="calls">…call list…</div>
    </div>
  </div>
</div>
<script>
const press=(group,btn)=>[...group.children].forEach(b=>b.setAttribute('aria-pressed',String(b===btn)));
document.querySelectorAll('#appNav button').forEach(b=>b.onclick=()=>{ press(b.parentElement,b); document.querySelectorAll('.view').forEach(v=>v.classList.toggle('on',v.dataset.v===b.dataset.v)); });
document.querySelectorAll('#seg button').forEach(b=>b.onclick=()=>{ press(b.parentElement,b); /* swap globe ↔ region outline */ });
</script>
```

### 3.23 Autoplaying "build log" mockup (orchestration hero / dev-tools stream)

```html
<style>
  .log{border:1px solid var(--line);font-size:12px}
  .log__prompt{margin:16px;padding:12px;background:var(--signal);min-height:42px}
  .log__prompt .caret{display:inline-block;width:1px;height:1em;background:currentColor;vertical-align:-2px;animation:blink 1s steps(1) infinite}
  .log ol{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
  .log li{display:flex;gap:10px;padding:8px 16px;color:var(--ink-4);transition:background .25s,color .25s}
  .log li.run{background:var(--obsidian);color:#fff} .log li.done{color:var(--ink-strong)}
  .node{margin:12px auto;width:200px;border:1px solid var(--line);background:#fff;padding:8px;opacity:0;transform:translateY(6px);transition:opacity .4s var(--ease-brand),transform .4s var(--ease-brand)}
  .node.in{opacity:1;transform:none}
</style>
<div class="log" id="log">
  <div class="log__prompt"><span id="typed"></span><span class="caret"></span></div>
  <ol><li>1. Layer one</li><li>2. Layer two</li><li>3. Layer three</li><li>4. Layer four</li></ol>
  <div class="app__main" style="min-height:220px;padding:12px"><div class="node">Trigger</div><div class="node">Agent</div><div class="node">Action</div></div>
</div>
<script>
(() => {
  const root=document.getElementById('log'), typed=document.getElementById('typed'), items=[...root.querySelectorAll('li')], nodes=[...root.querySelectorAll('.node')];
  const prompt='Build a support flow that answers every call and logs each visit.';
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  async function run(){ typed.textContent=''; items.forEach(i=>i.className=''); nodes.forEach(n=>n.classList.remove('in'));
    for (const ch of prompt){ typed.textContent+=ch; await sleep(28); } await sleep(500);
    for (let i=0;i<items.length;i++){ items[i].className='run'; await sleep(900); if(nodes[i]) nodes[i].classList.add('in'); items[i].className='done'; }
    await sleep(4000); run(); }
  new IntersectionObserver(([e],o)=>{ if(e.isIntersecting){ o.disconnect(); run(); } },{threshold:.4}).observe(root);
})();
</script>
```

### 3.24 Voice waveform with travelling playhead

```html
<svg id="wave" viewBox="0 0 470 420" style="width:100%;border:1px solid var(--line);background:#fff"></svg>
<script>
(() => { const s=document.getElementById('wave'), NS='http://www.w3.org/2000/svg', N=88, bars=[];
  for (let i=0;i<N;i++){ const h=40+Math.abs(Math.sin(i*.37)*Math.cos(i*.11))*220+Math.random()*30, x=6+i*5.3, l=document.createElementNS(NS,'line');
    Object.entries({x1:x,x2:x,y1:250-h/2,y2:250+h/2,'stroke-width':2}).forEach(([k,v])=>l.setAttribute(k,v)); s.appendChild(l); bars.push(l); }
  const ph=document.createElementNS(NS,'g'); ph.innerHTML='<rect x="-4" y="54" width="8" height="8" fill="#d59566" opacity=".6"/><line x1="0" x2="0" y1="62" y2="420" stroke="#cfcfcf"/>'; s.appendChild(ph);
  let t0=performance.now(); (function loop(now){ const p=((now-t0)/9000)%1, x=6+p*N*5.3; ph.setAttribute('transform',`translate(${x},0)`);
    bars.forEach((b,i)=>b.setAttribute('stroke', 6+i*5.3<=x ? '#5f5f5f' : '#dcdcdc')); requestAnimationFrame(loop); })(t0);
})();
</script>
```

### 3.25 Poster → inline video swap ("Watch the film")

```html
<div class="film" style="position:relative;aspect-ratio:16/10;background:#000">
  <img src="https://picsum.photos/seed/film/1200/750" alt="" style="width:100%;height:100%;object-fit:cover">
  <button class="film__btn" style="position:absolute;left:16px;bottom:16px;display:inline-flex;gap:9px;padding:10px 12px;border:1px solid rgb(255 255 255 / .4);background:rgb(7 7 7 / .45);backdrop-filter:blur(4px);color:#fff;font:400 11px var(--font-mono);text-transform:uppercase;letter-spacing:.08em">▶ Watch the film</button>
</div>
<script>
document.querySelectorAll('.film').forEach(f => f.querySelector('.film__btn').onclick = () => {
  const v = document.createElement('video'); Object.assign(v, { src: '/media/film.mp4', controls: true, autoplay: true, playsInline: true });
  v.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block'; f.replaceChildren(v); v.focus();
});
</script>
```

### 3.26 React + Motion equivalents (the reference stack)

```tsx
// Reveal.tsx — matches the reference: opacity 0 / y 16 → 1 / 0, once, ~0.6 s strong ease-out
'use client';
import { motion, useReducedMotion } from 'motion/react';
export function Reveal({ children, delay = 0, className }: { children: React.ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div className={className}
      initial={reduce ? false : { opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -12% 0px' }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay }}>
      {children}
    </motion.div>
  );
}

// CountUp.tsx — SSR renders the final value; animates once on view
'use client';
import { animate, useInView } from 'motion/react';
import { useEffect, useRef } from 'react';
export function CountUp({ to }: { to: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.2 });
  useEffect(() => {
    if (!inView || !ref.current || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const c = animate(0, to, { duration: 1.2, ease: [0.33, 1, 0.68, 1], onUpdate: v => { ref.current!.textContent = Math.round(v).toLocaleString('en-US'); } });
    return () => c.stop();
  }, [inView, to]);
  return <span ref={ref}>{to.toLocaleString('en-US')}</span>;
}

// Scroll-linked diagram progress with Motion (alternative to 3.8's manual listener)
import { useScroll, useTransform } from 'motion/react';
// const { scrollYProgress } = useScroll({ target: runwayRef, offset: ['start 80%', 'end 40%'] });
// const rotate = useTransform(scrollYProgress, [0.15, 0.45], [0, 45]);
// const fillPerf = useTransform(scrollYProgress, [0.45, 0.57], [0, 1]);
```

---

# 4. Design tokens (CSS)

Values below are exact computed values from the live site; names are generic so you can rebrand. The site ships **dark values on `:root`** and overrides them for light scopes (`html[data-theme=light]`, the default). Below, light is the default and dark is the opt-in scope (used by the vision page).

```css
/* Fonts — reference uses self-hosted "Suisse Intl" (Regular/Book) + "Suisse Intl Mono" as woff2.
   Swap for your licence (close free alternatives: "Inter Tight"/"Geist" + "Geist Mono"/"JetBrains Mono"). */
@font-face{font-family:"Brand Sans";src:url(/fonts/brand-sans-regular.woff2) format("woff2");font-weight:400;font-display:swap}
@font-face{font-family:"Brand Sans";src:url(/fonts/brand-sans-book.woff2) format("woff2");font-weight:350;font-display:swap}
@font-face{font-family:"Brand Mono";src:url(/fonts/brand-mono-regular.woff2) format("woff2");font-weight:400;font-display:swap}

:root{
  /* ---------- raw palette ---------- */
  --obsidian:#070707;   /* near-black: text, solid CTAs, dark surfaces */
  --anchor-black:#0e0d0c;
  --carbon:#2e2e2e;     /* announcement bar, hover fill, dark quadrant */
  --concrete:#736f6a;   /* warm grey: muted headings, logo ink */
  --stone:#b8aea4;      /* warm taupe: section bg, lines, accent */
  --signal:#f2f2f2;     /* light grey surface */
  --hull-white:#fcfcfc; /* dropdown / popup bg */
  --white:#fff;
  --rust:#d59566;       /* the one accent: bullets, focus ring, active markers */
  --rust-deep:#b06a38;  /* accent text on light ("Case study ↗") */
  --neutral:#cacaca; --neutral-light:#d9d9d9; --neutral-dark:#858585; --muted-heading:#858484; --neutral-darker:#333;
  --deck-green:#a9c59d; --success:#5fa46b; --success-strong:#027a48; --alert:#d9584b; --error:#b42318;
  --warm-hairline:#dad5cc; --warm-hairline-2:#c9c4b9;

  /* ---------- semantic (LIGHT, default) ---------- */
  --surface:#fff;
  --surface-2:#f2f2f2;
  --ink-strong:#070707;
  --ink-1:#2e2e2e; --ink-2:#2e2e2e;
  --ink-3:#736f6a; --ink-4:#736f6a; --ink-5:#736f6a; --ink-6:#2e2e2e; --ink-7:#736f6a;
  --line:#b8aea480;           /* 50% stone */
  --line-strong:#b8aea4; --line-soft:#2e2e2e; --line-warm:#b8aea4;
  --border-cta:#b8aea4;
  --cell:#b8aea4;             /* image placeholder */
  --accent:#736f6a;           /* second clause of two-tone headings */
  --cta-solid-bg:#070707; --cta-solid-fg:#fff;
  --nav-top:#fffffff5; --nav-bottom:#ffffffbf;
  --wordmark:#070707; --wordmark-filter:invert(1);
  --announce-bg:#2e2e2e;

  /* ---------- gradients ---------- */
  --grad-hero:linear-gradient(98deg,color-mix(in srgb,var(--stone) 46%,#fff) 0%,color-mix(in srgb,var(--stone) 18%,#fff) 48%,#fff 100%); /* ≈ #dedad5 → #f2f0ee → #fff */
  --grad-cta:linear-gradient(98deg,#dcd7d2 0%,#f0eeeb 48%,#fff 100%);
  --grad-title:linear-gradient(105deg,var(--obsidian) 0%,var(--carbon) 55%,var(--concrete) 100%);
  --grad-card-shade:linear-gradient(transparent 52%,rgb(7 7 7 / .62));
  --grad-sector-shade:linear-gradient(rgb(18 16 14 / .1) 40%,rgb(18 16 14 / .9));

  /* ---------- diagram ---------- */
  --dia-q1:var(--carbon); --dia-q2:var(--concrete); --dia-q3:var(--stone); --dia-core:#fff; --dia-stroke:var(--obsidian); --dia-marker:var(--rust);

  /* ---------- typography ---------- */
  --font-body:"Brand Sans","Suisse Intl",Arial,sans-serif;
  --font-display:var(--font-body);
  --font-mono:"Brand Mono","Suisse Intl Mono",ui-monospace,monospace;
  --fs-display:44px;   /* H1: 44 → 64 (md) → 76 (lg) → clamp(84px,5.95vw,112px) (xl) ; lh 1.04 ; ls -0.055em */
  --fs-h2:29px;        /* H2: 29 → 46 (md) ; lh 1.04 ; ls -0.02/-0.025em */
  --fs-h3:20px;        /* H3: 20 → 21 ; lh 1.15 ; ls -0.01em */
  --fs-lead:16px;      /* hero sub: 16 → 20 (lg) ; lh 1.4 */
  --fs-body:15.5px;    /* section intro paragraphs ; lh 1.65 */
  --fs-body-s:14.5px;  /* card / pillar paragraphs ; lh 1.65 */
  --fs-small:13px;     /* footer links, menu descriptors */
  --fs-nav:11px;       /* nav: uppercase, ls .12em, sans (not mono) */
  --fs-mono:11px;      /* eyebrows / buttons: uppercase mono ; ls .04em (labels) .01em (buttons) */
  --fs-mono-s:10px;    /* captions, stat labels, footer captions ; ls .12–.18em */
  --fs-stat:34px;      /* → 40 (md) ; lh 1.5 ; ls .005em */
  --fs-metric:19px;    /* story metric → 26 (md) → 24 (lg) → 30 (xl) ; lh 1.06 ; ls -0.025em */
  --fs-dia-l:10.5px; --fs-dia-s:7.4px;
  --lh-tight:1.04; --lh-snug:1.15; --lh-body:1.65;

  /* ---------- layout ---------- */
  --container:1440px;
  --gutter:20px;                       /* 48px ≥768 */
  --section-y:64px;                    /* 80 (md) → 120 desktop sections; 150 on the platform section; 112 on product bodies */
  --header-h:68px; --announce-h:36px;
  --radius:0;                          /* everything is square */
  --hairline:1px;
  --shadow-pop:0 10px 15px -3px rgb(0 0 0 / .1),0 4px 6px -4px rgb(0 0 0 / .1);
  --blur-glass:4px;                    /* film button backdrop */
  --grain-opacity:.16;

  /* ---------- spacing scale (Tailwind 4px base; values actually used) ---------- */
  --s-1:4px;--s-1_5:6px;--s-2:8px;--s-2_5:10px;--s-3:12px;--s-3_5:14px;--s-4:16px;--s-5:20px;--s-6:24px;--s-7:28px;--s-8:32px;--s-10:40px;--s-12:48px;--s-14:56px;--s-16:64px;--s-20:80px;--s-24:96px;--s-28:112px;--s-30:120px;

  /* ---------- motion ---------- */
  --ease-brand:cubic-bezier(.33,0,.15,1);
  --ease-inout:cubic-bezier(.65,0,.35,1);
  --ease-out-soft:cubic-bezier(.22,1,.36,1);
  --ease-ui:cubic-bezier(.25,.1,.25,1);
  --dur-xs:140ms; --dur-s:280ms; --dur-m:350ms; --dur-l:420ms; --dur-xl:600ms;
  --hero-cycle:18s; --marquee-dur:32s; --blink-dur:2.4s;
}
@media (min-width:768px){:root{--gutter:48px;--fs-display:64px;--fs-h2:46px;--fs-stat:40px;--fs-metric:26px;--section-y:120px}}
@media (min-width:1024px){:root{--fs-display:76px;--fs-h3:21px;--fs-lead:20px;--fs-metric:24px}}
@media (min-width:1280px){:root{--fs-display:clamp(84px,5.95vw,112px);--fs-metric:30px}}

/* ---------- dark scope (vision page, any [data-theme=dark] block) ---------- */
[data-theme=dark]{
  --surface:#070707; --surface-2:#070707;
  --ink-strong:#fff; --ink-1:#c7beb2; --ink-2:#b0a79c; --ink-3:#9c9288; --ink-4:#8f867b; --ink-5:#7e766b; --ink-6:#736f6a; --ink-7:#5f574d;
  --line:#1f1f1f; --line-strong:#262626; --line-soft:#222; --line-warm:#353535; --border-cta:#444;
  --cell:#2e2e2e; --accent:#b8aea4;
  --cta-solid-bg:#fff; --cta-solid-fg:#070707;
  --nav-top:#070707f0; --nav-bottom:#0707079e; --wordmark:#fff; --wordmark-filter:none;
}

/* ---------- section backgrounds used on the homepage, top→bottom ---------- */
/* hero: --grad-hero | proof/logos: --surface | platform: --signal | industries: --surface |
   pillars: --stone (panel cells --signal) | vision teaser: --surface | CTA: --grad-cta | footer: --surface-2 */
```

**Breakpoints** (Tailwind defaults + two CSS-module queries): `sm 640px`, `md 768px`, `lg 1024px (64rem)`, `xl 1280px (80rem)`. Custom: rail gutter switches at 1440px via `max()`; CTA content padding uses `max(0px, 50vw − 824px)`.

**Iconography:** 1-px stroke, 9–10 px arrows (`M1 5h8M5.5 1.5 9 5 5.5 8.5`), chevrons 8 px, square bullets 5–6 px, everything `currentColor`.

---

# 5. Responsive behaviour

Measured on the homepage with the page rendered in iframes of exact widths, plus visual checks of inner pages.

| Element | 390 | 768 | 1024 | 1440 |
|---|---|---|---|---|
| Announcement | short copy, wraps to 2 lines, no trailing CTA | long copy + trailing "read" link | same | same |
| Nav | logo + compact solid CTA + hamburger | same | full links + mega menus (lg) | same, max-width 1440 centred |
| H1 | 44 px, 2–3 lines | 64 px | 76 px | ~86 px (5.95vw clamp) |
| Hero form | stacked: full-width input, full-width button (44–48 px tall) | inline row (input border-right removed) | inline | inline |
| Hero grid art | behind the text, photos at 14 % opacity, top-fade mask only | same | positioned right (`--hg-left`), photos 100 %, left+top masks | same |
| H2 | 29 px | 46 px | 46 px | 46 px |
| Story cards | 2 columns, metric 19 px | 2 cols, 26 px | 4 cols from exactly 1024 (2 cols just below) | 4 cols, 24–30 px |
| Logo wall | 3 cols, custom order (`--po`) | 5 cols | 5–7 cols | 7 cols |
| Layer Diamond | full width below text, not sticky, same scroll timeline | same | sticky right column, 160vh runway | same, max 647 px |
| Industries rail | 1.2 cards (≈278 px), captions shown on in-view card, 8 dots, gutter 20 | 3 cards (gutter 48 from md) | 4 cards (~292 px) | 4 cards (~317 px), rail bleeds to viewport edge |
| Pillars | stacked 1 col; stats 2×2 | 3 cols; stats 2×2 | 3 cols; stats 4×1 | same |
| Vision teaser | video 300 px square under text | 400 px | 2 cols, video `min(565px,42vw)` | same |
| Closing CTA | heading 44 px, art faded behind | — | 76 px with pointer sheen | clamp up to 112 px |
| Footer | 1 col → 2 cols (sm) | 5-col grid `1.1fr 1fr 1fr 1fr 1.3fr` | same | same |

**Inner pages:**
- Product sub-pages: hero switches from stacked (H1 then paragraph) to 2 columns at lg; feature rows alternate text/visual sides at lg and stack (text first) below; mockup windows keep their internal layout and scale down (the ops console nav column collapses above the map below 640 px via `grid-rows-[auto_1fr]`).
- Platform overview: sticky rail becomes static above the content below 768 px.
- Industry pages: duplicate desktop/mobile heading variants; use-case list stacks above the screenshot; the "Designed for enterprise" 2×2 grid becomes 1 column.
- Customer story: left rail (metrics/products/TOC) moves above the body below 768 px (not sticky).
- Hub/Blog: 3 → 2 → 1 column cards; filter row wraps.
- Careers: values grid 3 → 1 col; offices list stacks above the globe.
- Demo page: right visual panel hidden on small screens; form full width.
- ESI page: chapter text loses `sticky` below lg; the pyramid chapter keeps its pinned 100vh frame and stacks text above the canvas.

**Touch:** hover-only effects (image zoom, captions, chip draw, sweep) are gated with `@media (hover:hover)` or `lg:` so mobile shows the end state where it matters (captions via `.is-colored`).

---

# 6. Pages one by one

Slot notation: `[TYPE · lines · ~words · role]`. "Rewrite" = new wording built from the underlying idea, same length/role, placeholders for anything company-specific. Original wording is intentionally not reproduced.

## 6.0 Site-wide voice

- **Tone:** calm, declarative, enterprise-confident. Headlines are short sentences that **end with a full stop**. No exclamation marks, no questions except closing CTAs ("Where do you want to start?").
- **Devices:** (1) **two-tone headlines** — the second clause rendered in warm grey (`--accent`) to create a statement + qualifier rhythm; (2) **mono uppercase eyebrows** with a rust square bullet; (3) **numbered structure** ("01", "02 / 05") everywhere — sections, cards, steps; (4) concrete metrics as proof in place of adjectives; (5) a recurring "real world / real economy / physical operations" motif; (6) verbs of labour ("put to work", "do the work", "in command") applied to software.
- **Message hierarchy (homepage and most pages):** promise → proof (named customers, metrics) → mechanism (platform layers) → fit (industries/functions) → differentiation (depth/ownership/breadth + numbers) → vision → single CTA repeated (book a demo).

## 6.1 Homepage `/`

| # | Section | Layout |
|---|---|---|
| 0 | Announcement bar | full-width strip, centred single line |
| 1 | Hero | 100svh, text left (max 11.5em), animated SVG grid right/behind |
| 2 | Proof: story cards + logo wall | header row (H2 + link), 4-col image cards, 7-col hairline logo grid |
| 3 | Platform | 2 cols: text + 3 pillar rows / sticky scroll-assembled diagram |
| 4 | Industries | header (H2 + paragraph), bleeding horizontal rail of 8 square cards, controls |
| 5 | Depth/Ownership/Breadth + stats | stone background, bordered panel 3 + 4 cells |
| 6 | Vision teaser | 2 cols: text + looping blended video |
| 7 | Closing CTA | gradient band, huge heading, inline form, static lattice art |
| 8 | Footer | 5-col grid + bottom bar |

**Slots and rewrites**

- **0 · Announcement**
  - `[Badge · 1 word · status]` → "New"
  - `[Sentence · 1 line · ~14 words · company news hook]` → "[BRAND] secures [FIGURE] to bring AI workers into the operations behind [INDUSTRY]."
  - `[Short variant · 1 line · ~7 words · mobile]` → "[FIGURE] raised — AI workers for [INDUSTRY]"
  - `[Link · 3 words]` → "Read the news →"
- **Nav** `[5 labels + CTA]` → Platform · Solutions · Customers · News · Careers · "Book a call"
- **1 · Hero**
  - `[H1 · 1 line · ~4 words · core promise]` → "Your agents, on shift."
  - `[Input placeholder · ~4 words]` → "Your company email"
  - `[Button · 3 words · primary CTA]` → "Book a call"
  - `[Lead · 2 lines · ~14 words · what + for whom]` → "Design and run AI agents that handle the calls, emails and messages your operation depends on — at full scale."
  - Asset: SVG lattice, 100-unit cells, 3 scenes × 3 square photo tiles (≈ 1:1, shown ~90–110 px), masked fade.
- **2 · Proof**
  - `[H2 · 1 line · ~5 words · proof claim, last 2 words muted]` → "Already running **in production.**"
  - `[Link · 1 word]` → "Customers"
  - 4 × card: `[Eyebrow · 2 words · proof category]` + `[Metric · 2–3 lines · 5–8 words · quantified outcome]` + client logo on image
    - "Footprint" — "[FIGURE] workflows live across [FIGURE] business units"
    - "Satisfaction" — "[FIGURE]/10 rating within the first month"
    - "Autonomy" — "[FIGURE]% of critical tasks completed end to end"
    - "Time to value" — "Live in production after [FIGURE] weeks"
  - Logo wall: 21–25 `[Logo]` cells, 8 with `[Tag · 2 words]` → "Case study ↗"
  - Assets: 4 square photos (~317 px rendered, delivered via image CDN), 1 hover MP4 loop (1:1, ~13 s), 25 monochrome SVG logos used as masks.
- **3 · Platform**
  - `[H2 · 2–4 lines · ~7 words · category definition]` → "One system to design and run every agent."
  - `[Button · 2 words]` → "See the platform"
  - 3 × `[Title · 1 line · ~5 words]` + `[Text · 2 lines · ~14 words]`:
    - "Quality is measured" — "Each agent is benchmarked before launch and reviewed continuously once it's live."
    - "Memory compounds" — "Everyday work becomes reusable context that sharpens insight and keeps improving results."
    - "People stay in control" — "Workspaces shaped around your teams surface what matters and let humans steer the AI."
  - Diagram labels (rename to your model): top product `[Name + 2-line descriptor]` → "[PRODUCT] / runs the whole stack end to end"; Layer A "QUALITY" with 4 items (Goals · Test suites · Reviews · Self-tuning); Layer B "WORKSPACES"; Core "AGENTS" with 4 items (Flows · Voice & chat · Reasoning · Scale); Layer C "MEMORY" with 3 items (History · On-site data · Connected systems); outside "YOUR SYSTEMS".
  - Asset: inline SVG, 1:1, max 647 px.
- **4 · Industries**
  - `[H2 · 2 lines · ~7 words · market scope]` → "Built for the sectors that keep things moving."
  - `[Paragraph · 3 lines · ~22 words · tailoring promise]` → "Every process your business relies on, coordinated from first touch to last. Configured for your sector, and for the way your teams actually operate."
  - 8 × card `[Index · 2 digits]` + `[Title · 1 word · industry]` + `[Caption · 2 short use cases]` e.g. "[INDUSTRY]" / "Quoting · shipment updates".
  - Assets: 8 square photos (~317 px), grain overlay, gradient.
- **5 · Depth / Ownership / Breadth**
  - `[H2 · 2 lines · ~7 words · positioning]` → "We take on the work that can't fail."
  - 3 × `[Eyebrow · 1 word]` + `[H3 · 2 words]` + `[Text · 2–3 lines · ~14 words]`:
    - "Depth" — "Messy processes, handled" — "Logic detailed enough for real-world exceptions, not just the happy path."
    - "Ownership" — "Built around you" — "A transparent platform tailored to your stack and connected to the way you work."
    - "Breadth" — "Learning that spreads" — "An improvement made by one agent lifts every other agent, wherever it runs."
  - 4 × stat `[Number + suffix]` + `[Label · 2–3 words]`: "[FIGURE]M+ conversations / month", "[FIGURE]%+ resolved autonomously", "[FIGURE]% lower cost", "[FIGURE]X more capacity".
- **6 · Vision teaser**
  - `[H2 · 2 lines · ~4 words · named vision]` → "Meet the self-improving enterprise."
  - `[Paragraph · 2 lines · ~20 words · mechanism]` → "What your agents learn on the job builds into a living model of the business — one that gets sharper with every task."
  - `[Button · 2 words]` → "Explore the vision"
  - Asset: MP4 loop 720×720 (1:1), multiply-blended wireframe solid, rendered ~470 px.
- **7 · Closing CTA**
  - `[H2-as-display · 2 lines · ~7 words · action]` → "Bring AI workers into your operation."
  - Inline email + button (same as hero).
  - Asset: lattice of ~7.9vw cells, 5 curve tiles, 2 square photos.
- **8 · Footer**
  - Column captions `[mono · 1 word]`: Product / Company / Connect / Terms & policies.
  - `[Brand statement · 2 lines · ~4 words]` → "Intelligence that compounds."
  - `[Descriptor · 2 lines · ~8 words]` → "The operating layer for [INDUSTRY]-scale businesses."
  - Compliance chips `[7 × acronym]`, language selector `[4 options]`, © line.

## 6.2 Platform overview `/product/platform-overview`

1. **Hero** — 2 cols. `[H1 · 1 line · 2 words · page name]` → "The System"; `[Paragraph · 5 lines · ~45 words · problem→solution]` → "Agents take on the work. Making that reliable at scale needs more: a way to grade them against goals, turn live experience into usable memory, and keep people in charge — all coordinated by [PRODUCT]."; ghost button "Book a call". Visual: completed Layer Diamond (static, 1:1, ~620 px).
2. **Layer walkthrough** — sticky mini-diagram rail (280 px) + content; 5 blocks (Agents, Performance, Context, Interfaces, [PRODUCT]). Each block: `[Eyebrow · 3 words]` → "Do the work"; `[Lead · 2 lines · ~18 words]` → "Put voice, chat and reasoning agents inside complex flows so whole processes run start to finish."; 4 × `[Bullet title · 2 words]` + `[Bullet text · 2 lines · ~18 words]` (e.g. "Flows" — "Branches, loops, maths, files and code: every key decision written down, never guessed."); `[Ghost button · 2 words]` → "Explore agents"; an interactive mockup (workflow canvas, metrics, memory graph, ops console with globe, orchestration chat).
3. **Closing CTA** (shared).

## 6.3 Orchestration product `/prisma`

1. **Hero split** — `[Eyebrow · ~6 words]` → "The command layer for your platform"; `[H1 · 1 word · product name]` → "[PRODUCT]"; `[Paragraph · 4 lines · ~40 words]` → "An always-on layer that runs the platform for you, like a chief of staff. Describe what you need and it builds it, keeps an eye on operations in the background, and flags and explains problems as they appear."; button.
2. **Autoplay demo window** (≈ 1030×560): prompt → 4 tool calls → workflow canvas.
3. **Build / Manage** — two columns, each `[H2 · 1 word]` + `[Subline · ~8 words]` + 3 × `[H3 · 1–2 words]` + `[Text · ~10 words]`. Rewrite: "Build — Say what you need; it assembles it." / "Manage — A watchful layer that spots risks and openings as they happen."
4. **How it works** — `[H2 · 3 words]` → "Under the hood"; 8-step stepper (step names: Detect · Diagnose · Trace ×4 · Root cause · Ship the fix) + layer diagram.
5. **Dark band** — `[H2 · ~8 words]` → "One window onto every layer of the business."
6. **FAQ** (5 Q&A) → rewrite each question as "What is [PRODUCT]?", "Can it change live systems?", "What can it build?", "Does it learn our setup?", "Do we have to use it?".
7. **Closing CTA**.

## 6.4 Vision page `/product/esi` (dark)

1. **Hero** — `[Eyebrow · 2 words]` → "The vision"; `[H1 · 1–2 lines · 2 words · named concept, gradient sheen]` → "Compounding Enterprise"; `[Paragraph · 3 lines · ~40 words]` → "A business where every entity, process, decision and behaviour is recorded as it happens, merging into one live picture that the whole company runs from."
2. **Chapters 01–05**, each: `[Index]`, `[Eyebrow · ~5 words]`, `[H2 · 2 lines · ~6 words]`, `[Paragraph · 6 lines · ~60 words]`, `[Mono stat line · ~5 words]`, visual (bordered dark frame ~500×500).
   - 01 "Thousands of agents, moving as one" — live runs counter.
   - 02 "Every agent works like a veteran" — schema grid; stat "[FIGURE] schemas · [FIGURE] rows".
   - 03 "Agents climb the ladder of complexity" — pinned canvas pyramid, 5 statements (~15 words each): routine work first → point tools can't connect → shared context crosses functions → context unlocks harder reasoning → the whole pyramid is covered.
   - 04 "Optimising the whole, not the parts" — particle clusters; stat "[FIGURE] agents · [FIGURE] goals".
   - 05 "One window across the enterprise" — layer convergence; stat "[FIGURE] layers, 1 command".
3. **Statement band** — `[H2 · ~6 words]` → "[BRAND] speeds the shift."
4. **Closing CTA**.

## 6.5 Product sub-page template (Agents overview, Interfaces, Developer tools, Performance, Context, Security, and their children)

1. **Hero** — back link `[← parent · 2 words]` → "← The system"; `[Eyebrow · ~4 words]` → "Built to do the work"; `[H1 · 1 word]` → "[PRODUCT AREA]"; `[Paragraph · 4 lines · ~40 words]`; ghost button. Big demo window below (~1030×600) on a dotted grid.
2. **Numbered feature rows 01–04** — alternating sides; `[Index]`, `[H2 · 1–2 words]`, `[Paragraph · 3–4 lines · ~35 words]`, hairline, 2–3 × (`[Bullet title · 2 words]` + `[Text · 2 lines · ~22 words]`), `[Ghost button · 1–2 words]`; mockup on the other side (workflow, waveform, live-signals, app launcher, code editor…).
   - Rewrite example (row 02): "Voice & chat" — "One agent mind across phone and every written channel, running on a voice stack tuned for real calls: it uses tools, reads and updates your systems, and hands over mid-conversation."
3. **Scale statement** — `[H2 · ~6 words]` → "Thousands of flows, one standard."
4. **FAQ** — 5 items.
5. **Closing CTA**.

## 6.6 Industry page template (example: logistics)

1. **Centred hero** — `[H1 · 2 lines · ~7 words, line 2 muted]` → "Win more freight / **and land it on time.**"; pixel monogram; `[Paragraph · 3 lines · ~30 words]` → "For [INDUSTRY] teams, [BRAND] agents capture more demand, negotiate sharper prices, follow every shipment and gather paperwork — without adding headcount."; solid button.
2. **Hero image** — 16:9 photo, container width (1030 px).
3. **Intro** — `[H2 · 1 line · ~4 words, centred]` → "From first quote to final proof."; `[Sub · ~5 words]` → "Where most teams begin".
4. **Use-case blocks ×4–5** — `[H2 · 2 lines · ~6 words]` → "More loads, better margins."; 5 × `[Item title · 3 words]` + `[Item text · 2 lines · ~16 words]` (e.g. "Catch every inbound request" — "Sort tenders, screen for fraud and reply to each enquiry the moment it lands."); visual: product screenshot (≈ 570×430) on a tinted photo.
5. **System-of-record split** — `[Eyebrow]` → "Record keeping"; `[H2 · 3 lines · ~8 words]` → "A database that writes itself, call by call."; 2 paragraphs (~30 words each); photo right (1:1).
6. **Enterprise band** — photo background, `[H2 · ~3 words]` → "Ready for enterprise."; 2×2 (`[Title · 1 word]` + `[Text · ~15 words]`): Observable · Explainable · Secure · Scalable.
7. **Start box** — `[H2 · ~5 words, question]` → "Where should we begin?"; `[Text · ~14 words]`; button.

## 6.7 Function page template (example: sales)

1. **Hero split** — `[Breadcrumb · 1 word]`; `[H1 · 2 lines · ~4 words]` → "AI that closes."; `[Paragraph · 4 lines · ~30 words]`; ghost button.
2. **Trusted-by grid** — `[Mono caption · ~5 words]` → "Relied on by [FIGURE]+ enterprises"; 10 logos (5×2).
3. **Positioning** — `[Eyebrow]` → "Made for real revenue work"; `[H2 two-tone · 2 lines · ~5 words]` → "Revenue, **on autopilot.**"; `[Paragraph · 4 lines · ~40 words]`; button; animated run transcript (≈475×520).
4. **Use cases** — `[H2 two-tone · 2 lines · ~7 words]` → "From quiet accounts **to booked revenue.**"; 2×2+ grid of `[Index]`, `[H3 · 2–3 words]`, `[Text · 3 lines · ~25 words]`, `[Outcome · 1 line · ~6 words]` with rust bullet.
5. **Benefits ×3**, **Kickoff-to-live steps** (Build / Test / Deploy, "[FIGURE] weeks"), **numbers**, **FAQ ×7**, **CTA**.

## 6.8 Customers `/customers`

1. **Hero split** — `[Breadcrumb]`; `[H1 · 1 line · 2 words]` → "Who we serve."; `[Paragraph · 2 lines · ~12 words]` → "See how leading operators are reshaping the way work gets done."
2. **Featured story band** (grey) — video poster 4:3 left with "Watch the film"; right: `[Eyebrow]` "Featured story"; `[H2 · 3 lines · ~7 words]` → "Agents across sales, service and billing at [CLIENT]."; 4 stats (`[FIGURE]` + `[Mono caption · ~8 words]`); `[Quote · 3 lines · ~22 words]`; `[Attribution · mono]` → "[PERSON], [ROLE], [CLIENT]"; outlined button "Read the story".
3. **Story grid** — 11 × (`[Tile: gradient + white logo, 3:2]`, `[H3 · client name]`, `[Excerpt · 2–3 lines · ~14 words]`, `[Link · 2 words]` "Read more").
4. **CTA band** — `[H2 · ~6 words]` → "Run your operation on [BRAND]."

## 6.9 Customer story (template; analysed: two stories)

1. Centred client logo (mono), breadcrumb "Case studies / [CLIENT]", `[H1 · 2 lines · ~10 words]` → "How [CLIENT] reinvented its operational work with [BRAND]", hero photo 16:9 (~750 px).
2. **Body grid** — left sticky: `[Key metrics: 2 × number + mono label]`, `[Products: 3–4 chips]`, `[Table of contents: 4–10 links]`; right: quote card (`[Quote · 4 lines · ~30 words]`, avatar 40 px, name, mono role), then H2 sections (Challenge / Partnership / What's live / Results — or a longer narrative of 8–10 headed sections in the second story), with paragraphs, italic quotes + attributions, and bold-lead bullet paragraphs.
3. Related CTA `[H2 · ~8 words]` → "See what [BRAND] could change for you."

## 6.10 Newsroom `/press`

1. `[H1 · 1 line · 2 words]` → "[BRAND] News."
2. Left: `[Paragraph · 6 lines · ~45 words]` company boilerplate; "Media kit →"; newsletter block (`[Title · 4 words]`, `[Text · ~12 words]`, email + Subscribe, consent microcopy). Right: 4 category links with arrows.
3. Featured post (image 16:10 left; title, excerpt, author avatar, "Learn more →").
4. Category rails ×4 (Engineering, Strategy, Coverage, Releases) — 3 cards each + "See all … →".

## 6.11 Hub `/hub` and Blog `/blog`

- `[H1 · 1–2 lines]` (Hub: "[BRAND] Library." / Blog: "Fresh from [BRAND].") → search → category filters → "Showing N of M" + sort → 3-col card grid (cover 3:2, date, H3 2 lines, excerpt 3 lines, "Read more →").
- Hub covers: blurred warm gradient + serif title + monogram (templated, ~330×220). Blog covers: designed graphics (product UI on dark frame, data viz, team photo).

## 6.12 Article `/blog/<slug>`

- Breadcrumb (Home / Blog / title), centred `[H1 · 2 lines]`, `[Dek · 2 lines]`, author row (avatar · name · date · read time), cover (16:9, ~1000 px), body with sticky "On this page" TOC (4–8 items) and 46-px H2s, 15-px paragraphs, quotes inline.

## 6.13 Careers `/careers`

1. Hero split — `[H1 · 3 lines · ~7 words, middle words muted]` → "Help us change how the world works."; `[Paragraph · 3 lines · ~16 words]`; solid "See open roles →" + text link "Talk to us".
2. Team photo (full container, ~3:1).
3. "Who we are" — `[H2 · 3 words]` + 2 paragraphs (~35 words each).
4. Statement band — rust square + `[H2 · 2–3 lines · ~16 words]` (manifesto line).
5. Values — `[H2 · 3 words]` → "How we operate."; 6 × (`[Index]`, `[H3 · 2–4 words]`, `[Text · 3–4 lines · ~22 words]`), with 3 photos interleaved (3:2).
6. Alumni logos — `[H2 · ~8 words]`.
7. Offices — `[H2 · 2 lines · ~7 words]` → "[FIGURE] offices, [FIGURE] continents, one crew."; list + canvas globe.
8. Open roles — list rows (role · team · location · arrow) with filter input.
9. CTA.

## 6.14 Contact `/contact`

- Left: eyebrow "Contact", `[H1 · 2 lines · 3 words]` → "Let's talk.", `[Paragraph · 2 lines · ~14 words]` → "Tell us what you need and the right person will reply soon.", `[Inline link line · ~8 words]` → "Want a walkthrough instead? Book a call".
- Right: form card — 2-col grid: Full name*, Email*, Company (optional), Phone (optional); full-width Topic select, Message* (textarea ~5 rows); black "Send message →".

## 6.15 Demo `/contact/demo`

- Left (50 %): logo; `[H1 · 1 line · 3 words, last word muted]` → "Book a **walkthrough**"; `[Dek · 1 line · ~8 words]` → "See how [FIGURE]+ enterprises put AI workers to use."; step 1 field "Work email*" + "Next" (disabled until valid) → step 2: first name, last name, phone (+country flag), "How did you hear about us?" select → booking/calendar step (not entered).
- Right (50 %): lattice collage with photos (top 60 %), `[H2 · ~4 words, two-tone]` → "See [BRAND] **live**", `[Text · ~6 words]` → "Trusted by [FIGURE]+ enterprises", logo marquee (32 s).

## 6.16 Legal (template: privacy policy)

- Shared header/footer + CTA band; body = consent-vendor embed in an iframe (white card, vendor typography: bold uppercase H2s, 14-px Arial-like body, summary list, table of contents links). Other legal pages use the same template: Terms of service, Cookie policy. "Consent Preferences" opens the vendor modal.

---

# 7. Tech stack

| Area | Finding | Evidence |
|---|---|---|
| Framework | **Next.js 16.2.5, App Router**, React Server Components, built with **Turbopack** | `window.next.version`, `self.__next_f` RSC payload, `/_next/static/chunks/turbopack-*.js` |
| Hosting | **Vercel** | `?dpl=dpl_…` deployment query on every chunk |
| Styling | **Tailwind CSS v4** (arbitrary values, `hrlight:` custom variant, container queries `cqw`) + **CSS Modules** for bespoke blocks (`HomeClosingCTA-module__…`, `AnimatedWordmark-module__…`) + a global layer of custom classes (`hr-logo-cell`, `hg-*`, `hr-chip-draw`, `hr-hover-dim`) | class names, CSSOM |
| Theming | CSS custom properties with `data-theme="light|dark"` scopes; `color-mix()` for derived tints | `:root` / `[data-theme]` rules |
| Animation | **Motion (framer-motion)** for in-view reveals (inline `opacity/transform` styles); **pure CSS keyframes** for the hero grid, blink, marquee, chip draw, underline sweep; **React state + rAF** for scroll-linked SVG (Layer Diamond) and pinned canvas scenes; **Canvas 2D** for globes, pyramid, particles | inline styles, `getAnimations()`, canvas contexts |
| Not used | No GSAP, no Lenis/Locomotive (native scroll), no Three.js/WebGL, no Lottie/Rive/Spline, no Swiper (rail is native scroll-snap) | globals + DOM checks |
| Fonts | Self-hosted **woff2**: Suisse Intl Regular & Book, Suisse Intl Mono Regular (served from the site origin) | resource timing |
| Images | `next/image` (`/_next/image?url=…&w=…`, responsive `srcset`), plus a **Bunny CDN** origin for logos (SVG masks) | URLs |
| Video | MP4 loops with posters, `preload="none"`, JS-started (in-view or hover) | `<video>` attributes |
| Logo | animated WebP loop + still fallback via `<picture>` media query | `source media="(prefers-reduced-motion: no-preference)"` |
| Consent | **Termly** (resource blocker with auto-block off, preferences modal, policy embeds) | `app.termly.io` script, `div[name=termly-embed]` |
| Analytics / ads | Google Tag Manager → GA4, Google Ads; Meta Pixel; X (Twitter) pixel; LinkedIn Insight; Leadfeeder; an extra CloudFront-hosted visitor-ID script — all gated by consent (after "Decline all" only GTM/GA basics loaded) | script list, resource hosts |
| Forms | Custom React forms (`noValidate`, JS validation, disabled submit until valid), multi-step demo form with phone country picker | DOM |
| Accessibility | `aria-expanded/haspopup` on menus, `aria-current` on pagers/steppers, `role=region` on FAQ panels, `role=listbox/option` language picker, visually hidden labels, `focus-visible` rust outline, reduced-motion fallbacks throughout. Gaps: mega panel lacks `aria-controls`/landmark, story cards hide the CTA text visually only, sticky TOC scroll-spy not exposed | DOM |

**Rebuild suggestion:** Next.js (App Router) + Tailwind v4 + Motion for reveals/scroll values, CSS keyframes for ambient loops, Canvas 2D for globes/pyramids, `next/image` + a CDN for media, a CMP of your choice. Everything above runs without WebGL.

---

# 8. GIFs recorded

Exported by the browser to your **Downloads** folder (1126×710):

1. `01-hero-grid-animation.gif` — lattice drawing in, photo tiles cycling through scenes, pointer sheen on the headline.
2. `02-mega-menus.gif` — Platform panel open, chip border-draw on hover, morph to Solutions panel, close.
3. `03-customer-cards-and-logo-wall.gif` — story cards, logo wall hover inversion.
4. `04-prisma-diagram-scroll.gif` — Layer Diamond: draw → rotate → fill → labels while scrolling.
5. `05-industries-rail.gif` — hover caption reveal, next-button stepping, drag back, dot pager.
6. `06-pillars-stats-esi.gif` — pillars panel, stat counters counting up, vision teaser video.
7. `07-platform-simulated-interface.gif` — ops console Global → California toggle, then navigation into the Interfaces page and its app launcher (an Explore link was hit mid-recording).
8. `08-esi-pyramid-scrollytelling.gif` — pinned canvas pyramid stepping 01→04 with the live agent counter.

---

# 9. Decisions taken autonomously

1. **Viewport sizes:** the Chrome window could not be resized from the side panel (the window stayed at 1126 px), so 390/768/1024/1440 were emulated by loading pages inside same-origin iframes of those exact widths (media queries fire correctly; the iframe scrollbar makes inner width ~4 px narrower, e.g. 764 instead of 768 — noted where it mattered).
2. **Forms:** inputs were only focused. Validation states were inferred from code (`noValidate`, required, disabled-until-valid buttons) rather than by submitting; empty-submit was not clicked because the hero form posts into the demo flow. The demo page's later steps were read from the DOM, not reached.
3. **Cookies:** no banner appeared on load; the consent panel was opened from the footer and **"Decline All"** was chosen.
4. **Coverage depth:** every page listed in Step 1 was opened. Pages sharing a template (8 industries, 5 functions, product children such as memory/edge/signals/scalability/northstars/audits/wayfinder) were verified by heading/feature scans and documented once as templates with one worked example, instead of duplicating near-identical tables 20 times.
5. **Copy:** original wording is not quoted anywhere; slots carry rewrites with placeholders. Diagram layer names were genericised ("Quality / Workspaces / Agents / Memory / Your systems") so you can map your own architecture.
6. **Scroll-linked timings** are expressed as progress fractions of the section's pass through a 710-px viewport (they are scroll-driven, not time-driven); the recipe maps the same fractions.
7. **Counter easing** was fitted from rAF samples (best fit: 1.2 s ease-out cubic); **reveal easing** fitted from samples (0.6 s, ≈ cubic-bezier(.22,1,.36,1)).
8. **Mega-menu close delay (~150 ms)** was measured from the moment the pointer left; part of it may be input latency, so treat 120–180 ms as the target range.
9. **Fonts:** the reference uses a commercial typeface; the token block names a neutral "Brand Sans/Brand Mono" with fallbacks so you can drop in your licensed fonts.
10. **Image placeholders** in recipes use a public placeholder service; replace with your own assets.
11. **GIF 7** includes an accidental navigation (a click landed on an "Explore" link after the layout shifted); the Interfaces page it reached was then analysed as part of the product pages.
12. The **"story" logo-cell variant** (blur + pointer-masked sharpness) exists in the reference CSS but is not used on the live homepage; it is included as an optional recipe.
