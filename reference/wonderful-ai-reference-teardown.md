# Reference Teardown — wonderful.ai (technical + design analysis)

> Purpose: a measured, rewritten reference for building your own site with your own brand, imagery and copy.
> No original copy, logos or images are reproduced here. Every text block is described by **slot** (role, length) and given a **rewritten version** with placeholders: `[BRAND]`, `[PRODUCT]`, `[CLIENT]`, `[FIGURE]`, `[INDUSTRY]`, `[CITY]`, `[CERTIFICATION]`, `[PARTNER]`, `[YEAR]`.
>
> Captured: 8 Nov 2026. Desktop measurements taken at a **1444 px** viewport (≈1440). Tablet at **1024 px**, phone at **768 px** and **407 px** (the narrowest the browser window allowed; ≈390). All pixel values are computed styles (`getComputedStyle`) unless marked *≈ visual*.

---

## Contents
1. Sitemap
2. Design tokens (CSS)
3. Components
4. Animations & interactions
5. Responsive behaviour
6. Pages one by one (structure, copy slots + rewrites, tone, hierarchy, media)
7. Tech stack
8. Decisions made autonomously

---

## 1. Sitemap

Source: header (incl. 3 mega-menus), mobile menu, footer (5 columns), and in-page links. All internal URLs are appended with `?scLang=en` by the translation layer; that parameter is omitted below.

```
/                                   Home
├── Platform  (mega-menu, 2 columns + featured-article card)
│   ├── /ai-os                      AI OS overview (umbrella product)
│   ├── /agents                     Agents (product 1)
│   ├── /systems                    Systems (product 2)
│   ├── /ai-gateway                 AI Gateway (product 3)
│   ├── /deployment                 Deployment (service: forward-deployed teams)
│   └── /ai-transformation          Strategy (service: transformation advisory)
├── Industries  (mega-menu, 2 columns + featured case-study card)
│   ├── /industries/banking
│   ├── /industries/telecommunication
│   ├── /industries/healthcare
│   ├── /industries/retail
│   ├── /industries/utilities
│   ├── /industries/insurance
│   └── /industries/airlines
├── Company  (mega-menu, 1 link column + "Latest press" with 2 media cards)
│   ├── /about-us
│   ├── /careers
│   │   └── /careers/candidate_notice      (legal template)
│   └── /press                       (25 external press cards)
├── /blog                            Blog listing (~50 posts, 6 category filters)
│   └── /blog-articles/{slug}        Article template (essay variant + news/video variant)
│        e.g. /blog-articles/the-execution-gap-no-model-can-close   ← sample essay analysed
│             /blog-articles/wonderful-raises-550m-series-c          ← sample news/press article analysed
│             /blog-articles/announcing-wonderful-ai-gateway, /ote, /banco-caja-social,
│             /petrol-ofisi, /telefonica, /ppc-energie, /open-by-default-competitive-by-design,
│             /fcbayern-and-wonderful-announce-enterprise-ai-partnership … (case studies & news)
├── /contact                         Contact / meeting request form
├── /safety                          AI Safety (content + report form)
├── Legal
│   ├── /legal                       Legal index (template "index")
│   ├── /legal/privacy               Website Privacy Policy   ← analysed as legal template
│   ├── /legal/websiteterms          Website Terms of Use
│   ├── /legal/bug-bounty-terms      Bug Bounty Terms
│   ├── /legal/msa                   Master Service Agreement
│   ├── /legal/sla                   Service Level Agreement
│   ├── /legal/dpa                   Data Processing Agreement
│   ├── /legal/aup                   Acceptable Use Policy
│   ├── /legal/data-act              Data Act Addendum
│   └── /legal/dora                  Financial-services (DORA) Addendum
└── External
    ├── trust.wonderful.ai           Trust Center (separate site, not analysed)
    ├── LinkedIn, X                  Social
    └── YouTube / news outlets       Press items open off-site
```

**Global chrome on every page:** announcement ticker (2 rotating messages) → header (logo, 4 nav items, language pill, CTA) → page body → CTA band (most pages) → footer (dark variant on most pages; light variant on /safety).

**Language selector options (10):** AR, DE, EN, ES-LA, FR, JP, KO, PT, CN, ZH.

---

## 2. Design tokens

### 2.1 Raw `:root` custom properties found (Framer tokens)

Framer emits ~35 colour tokens with UUID names (`--token-29f96b2e-…`). Values in declaration order:

`#fff · #080808 · #fafafa · #393939 · #6b6b6b · #31313199 · #1f1f1fcc · #ff3f3f · #ffecec · #f0fdf2 · #03a97e · #171719 · #e6e6e6 · #393939 · #e9edf5 · #fffcf1 · #fafafa · #5c5c5c80 · #f5f5f5 · #ff3f3f · #d2eee7 · #ffffffb3 · #ebedf1 · #ece8e1 · #777 · #050505 · #fff · #9ba1a5 · #3286f5 · #1d1d1f · #f5f5f7 · #6e6e73 · #0f1012 · #ffffff2e · #0000001a`

Plus colours that appear only in components (not tokenised): `#fc762f` (dot-grid orange), `#4a4a4a` (statement fill), `rgba(144,144,144,.26)` (statement unfilled), `rgba(250,250,250,.2)` (glass header), `rgba(245,245,245,.2)` (glass card), `rgba(0,0,0,.04)` (focused input), `#eeeeee` (input border), `#696969 / #6e6e6e` (muted text), `rgba(3,3,2,.59)` (mega-menu titles).

### 2.2 Typography (measured)

| Role | Font | Wt | Desktop 1440 | Tablet 1024 | Phone ≤809 | Letter-spacing | Line-height |
|---|---|---|---|---|---|---|---|
| Industry hero H1 | Display | 300 | 200px | — | 70px | −0.06em (−12px) | 1.05 |
| Home hero H1 | Display | 300 | 82px | 82px | 42px | −0.05em (−4.1px / −2.1px) | 1.05 |
| Page H1 (press, legal) | Display | 300 | 72px | — | ≈48px | −0.06em | 1.05 |
| Product hero H1 | Display | 300 | 64px | — | ≈40px | −0.05em | 1.05 |
| Statement (scroll-fill) | Display | 300 | 62px | — | ≈34px | −0.05em (−3.1px) | 1.15 |
| Industry tab title | Display | 300 | 72px | 54px | 38px | −0.06em | 1.05 / 1.2 |
| H2 section | Display | 300 | 48px | 42px | 34px (32px on industry pages) | −0.04em (−1.92px) | 1.05 / 1.15 |
| H2 small (logo strip) | Display | 300 | 26px | 24px | 24px | −0.05em | 1.25 / 1.15 |
| H3 card / row | Display | 300 | 32px | 22px | 24px | −0.04em (−1.28px) | 1.15 |
| H4 feature / blog card | Display | 300 | 26px | — | 24px | −0.05em (−1.3px) | 1.25 |
| Closer card label | Inter | 400 | 42px | 42px | ≈32px | −0.04em | 1.0 |
| Body L (hero sub) | Inter | 400 | 20px | 20px | 17px | −0.02em (−0.4px) | 1.25 |
| Body | Inter | 400 | 17px | 17px | 17px | −0.02em (−0.34px) | 1.28 (21.76px) |
| Legal body | Inter | 400 | 17px | — | — | −0.03em (−0.51px), justified | 1.28 |
| Button L | Inter | 400 | 16px | 16px | 16px | −0.5px | 26px |
| Button S / chip | Inter | 400 | 14px | 14px | 14px | −0.28px | 21px |
| Nav link | Inter | 400 | 16px | 16px | 16px (menu) | normal | 1.2 |
| Header CTA | Inter | 400 | 12px | 12px | — | −0.5px | 10px |
| Tab label | Inter | 400 | 14px | 14px | 14px | −0.84px (−0.06em) | 1.2 |
| Mega-menu title | Inter | 300 | 16px | — | 16px | −0.5px | 1.2 |
| Mega-menu desc | Inter | 300 | 14px | — | — | −0.5px | 1.2 |
| Meta / date | Inter | 400 | 14px | — | — | −0.28px | 1.6 (22.4px) |
| Footer heading / small | Inter | 400 | 12px | — | — | −0.12px | 1.1 |
| Footer link | Inter | 500 | 14px | — | — | −0.5px | 1.2 |
| Diagram tags | Mono (Fragment Mono) | 400 | ≈13px | — | — | normal | — |

*Display font* = **ABC Favorit Light** (Dinamo, commercial licence) — only weight 300 is used site-wide. Suggested free substitutes with similar geometric-grotesk feel: *Geist Light*, *Manrope 300*, *Inter Display 300* (already loaded on the site), *Satoshi Light*.
*Text font* = **Inter** 400/500 (300 in menus).

### 2.3 Spacing, layout & grid (measured)

- **Gutter (page side padding):** 60px desktop · 40px tablet · 24px phone (some components 16–20px on phone).
- **Content width:** fluid = viewport − 2×gutter (1324px at 1440). Narrower inner measures: 1200px (industry tab card, CTA band inner), 980px (legal text), 940px (statement), 800px (article title, industry tab title), 600px (article body, deks).
- **Section vertical padding:** 120px standard · 160px CTA band · 180px careers statement · 140px dark AI-OS section · 80–100px logo/statement sections · 60px phone.
- **Gaps observed:** 4 (logo tiles) · 16 (cards/carousel) · 18 · 24 · 30 (article paragraphs) · 42 · 60 · 80 · 120.
- **Grids:** logo 6×2 desktop / 4×2 industry pages / 3×4 phone · feature grids 3, 4 or 2 columns with 1px vertical dividers · press bento 2-up (696px squares) and 4-up (342px squares) with 12px gaps · blog 3 columns (420px cards, 30px gap).
- **Header:** 109px total (announcement 48 + bar 61) at top; 60px when condensed.

### 2.4 Radius, shadow, blur, opacity

- Radius: 4px (logo tiles, small row images) · 8px (cards, media, inputs) · 10px (case cards 10.37px, submit) · 12px (industry card, closer cards) · 14px (cookie card) · 50px / 999px / 1000px (buttons, pills, tab track, arrows).
- Shadows: essentially **flat design**. Only `inset 0 0 0 1px rgba(0,0,0,.05)` (cookie card) and image overlays. Depth comes from photography and dark/light alternation.
- Blur: header glass `backdrop-filter: blur(10px)`; glass cards `blur(10px)`; word reveal `filter: blur(6px)` → 0.
- Opacity scale used for text on dark: 1 · .88 · .7 · .54; on light: .8 · .6 · .5.

### 2.5 Breakpoints (from media queries)

| Name | Range | Notes |
|---|---|---|
| Wide | ≥1800px | 1 rule (larger card image sizes) |
| Desktop | 1440–1799px | primary design |
| Small desktop | 1200–1439px | |
| Tablet | 810–1199px | centred hero, 40px gutter |
| Phone | 0–809px | burger menu, 24px gutter, stacked |
| Component-level | 600 / 800 / 880px | carousel image `sizes`, header switch |
| Motion | `prefers-reduced-motion: reduce` | present |

### 2.6 Ready-to-use CSS variables

```css
:root {
  /* ---------- Colour: neutrals ---------- */
  --c-white:        #ffffff;
  --c-paper:        #fafafa;   /* off-white text on dark, light section bg, logo tiles */
  --c-surface:      #f5f5f5;   /* tab track, carousel arrows, inputs, light cards */
  --c-surface-2:    #f5f5f7;
  --c-line:         #e6e6e6;   /* hairlines, dividers on light */
  --c-line-input:   #eeeeee;
  --c-ink:          #171719;   /* primary text on light */
  --c-ink-2:        #1d1d1f;
  --c-heading-soft: #393939;   /* big H2s on light */
  --c-muted:        #6b6b6b;   /* secondary text */
  --c-muted-2:      #6e6e6e;   /* inactive tabs */
  --c-muted-3:      #777777;   /* mega-menu descriptions */
  --c-muted-4:      #9ba1a5;
  --c-night:        #080808;   /* dark sections, footer */
  --c-night-2:      #0f1012;
  --c-black:        #050505;

  /* ---------- Colour: tints ---------- */
  --c-cream:        #fffcf1;
  --c-warm:         #ece8e1;
  --c-cool:         #e9edf5;
  --c-cool-2:       #ebedf1;
  --c-mint:         #d2eee7;

  /* ---------- Colour: accents & status ---------- */
  --c-accent:       #3286f5;   /* links, focus ring, progress bars */
  --c-signal:       #fc762f;   /* decorative dots */
  --c-danger:       #ff3f3f;
  --c-danger-bg:    #ffecec;
  --c-success:      #03a97e;
  --c-success-bg:   #f0fdf2;

  /* ---------- Colour: alpha ---------- */
  --a-white-88: rgba(255,255,255,.88);
  --a-white-70: rgba(255,255,255,.70);   /* #ffffffb3 */
  --a-white-54: rgba(255,255,255,.54);
  --a-white-18: rgba(255,255,255,.18);   /* #ffffff2e */
  --a-ink-80:   rgba(31,31,31,.80);      /* #1f1f1fcc */
  --a-ink-60:   rgba(49,49,49,.60);      /* #31313199 */
  --a-ink-50:   rgba(92,92,92,.50);      /* #5c5c5c80 */
  --a-black-10: rgba(0,0,0,.10);         /* #0000001a */
  --a-black-04: rgba(0,0,0,.04);         /* focused input fill */
  --glass-light: rgba(250,250,250,.20);
  --glass-card:  rgba(245,245,245,.20);
  --reveal-off:  rgba(144,144,144,.26);
  --reveal-on:   #4a4a4a;

  /* ---------- Gradients (≈ visual) ---------- */
  --g-card-bottom: linear-gradient(180deg, rgba(0,0,0,0) 45%, rgba(0,0,0,.65) 100%);
  --g-hero-scrim:  linear-gradient(180deg, rgba(0,0,0,.25) 0%, rgba(0,0,0,0) 30%, rgba(0,0,0,.35) 100%);
  --g-dark-fade:   linear-gradient(180deg, rgba(8,8,8,0) 0%, #080808 85%);

  /* ---------- Typography ---------- */
  --font-display: "Your Display", "Inter Display", "Inter", system-ui, sans-serif; /* weight 300 */
  --font-text:    "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono:    "Fragment Mono", ui-monospace, "SFMono-Regular", monospace;

  --fs-giant: 200px;  --fs-hero: 82px;  --fs-h1: 72px;  --fs-h1-sm: 64px;
  --fs-statement: 62px; --fs-h2: 48px; --fs-h3: 32px; --fs-h4: 26px;
  --fs-label-xl: 42px;
  --fs-body-l: 20px;  --fs-body: 17px; --fs-btn: 16px; --fs-s: 14px; --fs-xs: 12px;

  --lh-display: 1.05; --lh-heading: 1.15; --lh-h4: 1.25; --lh-body: 1.28; --lh-meta: 1.6;
  --ls-display-xl: -0.06em; --ls-display: -0.05em; --ls-heading: -0.04em;
  --ls-body: -0.02em; --ls-tab: -0.06em;

  /* ---------- Spacing ---------- */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px; --sp-5: 18px; --sp-6: 24px;
  --sp-7: 30px; --sp-8: 32px; --sp-9: 42px; --sp-10: 48px; --sp-11: 60px;
  --sp-12: 80px; --sp-13: 100px; --sp-14: 120px; --sp-15: 160px; --sp-16: 180px;

  --gutter: 60px;
  --section-y: 120px;
  --cta-y: 160px;
  --measure-xl: 1200px; --measure-l: 980px; --measure-m: 800px; --measure-s: 600px;

  /* ---------- Radius ---------- */
  --r-xs: 4px; --r-s: 8px; --r-m: 10px; --r-l: 12px; --r-xl: 14px; --r-pill: 999px;

  /* ---------- Effects ---------- */
  --shadow-hair: inset 0 0 0 1px rgba(0,0,0,.05);
  --blur-glass: blur(10px);
  --blur-reveal: blur(6px);

  /* ---------- Layout ---------- */
  --header-h: 61px;  --header-h-condensed: 60px;  --announce-h: 48px;  --announce-h-mobile: 40px;

  /* ---------- Motion ---------- */
  --ease-out: cubic-bezier(.22,1,.36,1);
  --ease-std: cubic-bezier(.4,0,.2,1);
  --dur-fast: .15s; --dur: .3s; --dur-slow: .6s;
  --reveal-word-dur: .3s; --reveal-word-stagger: .045s; --reveal-y: 16px;
}

@media (max-width: 1199px) {
  :root { --gutter: 40px; --fs-hero: 82px; --fs-h2: 42px; --fs-h3: 22px; --fs-h2-sm: 24px; }
}
@media (max-width: 809px) {
  :root {
    --gutter: 24px; --section-y: 60px; --cta-y: 100px;
    --fs-giant: 70px; --fs-hero: 42px; --fs-h1: 48px; --fs-h1-sm: 40px; --fs-statement: 34px;
    --fs-h2: 34px; --fs-h3: 24px; --fs-h4: 24px; --fs-body-l: 17px; --fs-label-xl: 32px;
    --announce-h: 40px;
  }
}
@media (prefers-reduced-motion: reduce) {
  :root { --dur: 0s; --dur-slow: 0s; --reveal-word-dur: 0s; --reveal-word-stagger: 0s; --reveal-y: 0px; }
}

html, body { background: var(--c-white); color: var(--c-ink); font-family: var(--font-text); }
h1, h2, h3, h4 { font-family: var(--font-display); font-weight: 300; }
```

---

## 3. Components

### 3.1 Announcement ticker (top bar)
- **Structure:** `div.announce > div.track > [div.item × 2]`; each item = 21×21 round logo (SVG/PNG) + label `p` + link "Read more →".
- **Size:** 48px tall desktop (40px phone); content centred; label Inter 14/21 `#393939`; link Inter 14/21 `#171719`, arrow glyph 14px.
- **Behaviour:** two items alternate every **≈5s** with a vertical slide (~6px offset + clip, ≈0.4s). Background white at 0% → it sits on top of the hero; on scroll the bar collapses (header translates up 48px).
- **Hover:** link only; no underline.

### 3.2 Header / navigation
```html
<header class="hdr" data-theme="on-dark|on-light">
  <a class="hdr__logo">…svg 101×25…</a>
  <nav class="hdr__nav">
    <button class="hdr__item" aria-expanded>Platform</button>   <!-- 77×35 hit area, 16px label -->
    <button class="hdr__item">Industries</button>
    <button class="hdr__item">Company</button>
    <a class="hdr__item">Blog</a>
  </nav>
  <div class="hdr__right">
    <button class="lang">EN</button>                 <!-- pill 66×36, 1px border -->
    <a class="btn btn--sm">Get in touch</a>          <!-- 87×36 -->
  </div>
  <div class="mega" hidden>…</div>
</header>
```
- **Dimensions (desktop):** bar 61px; logo at x=24px; nav starts x≈194px with ~42px between items; right cluster ends at viewport −24px. Position `fixed`, full width.
- **States:**
  - *Top of page over dark hero:* transparent bg, white text, language pill = 1px white border transparent fill, CTA = white pill / black text.
  - *Scrolled (any page):* announcement hides; bar height 60px; bg `rgba(250,250,250,.2)` + `backdrop-filter: blur(10px)`. Text colour adapts to the section underneath: dark (`#171719`) over light sections, white over dark sections. CTA inverts to **black pill / white text** over light.
  - *Light-hero pages (About, Careers, Blog, Legal):* header starts in dark-text mode.
  - *Mega-menu open (hover on item):* whole header becomes solid white (`#fff`) and the panel drops beneath.
- **Mega-menu panel:** full width, height 367px, padding `48px 24px 32px`, flex with 24px gap.
  - Platform/Industries: 2 columns of links (each column 258px text width; column gap ~36px; rows 101px apart for Platform, 64px for Industries). Item = title Inter 300 16px `rgba(3,3,2,.59)` + description Inter 300 14px `#777`, 8px apart.
  - Right side: featured card 368px wide — 16:9 media (image or video with play button, radius 8px) + title 16px + "Read the article" underlined 12px.
  - Company: 1 link column (About, Careers, Press – 16px, 28px spacing) + "Latest press" label 12px + 2 media cards (368×205 each).
- **Language selector:** click opens a 64px-wide white list under the pill, 10 items at 12px, 26px row height, radius 6px, centred text.
- **Mobile (<810px):** logo 94px + "EN" text + burger (2 lines, 20px). Burger → full-screen white sheet: accordion rows (Platform, Industries, Company — 16px, chevron 10px, 68px rows with 1px `#e6e6e6` dividers) + plain "Blog" row + full-width black pill CTA (50px tall, 16px). Expanded group shows its links as 16px/300 items with 30px spacing; group label becomes 12px grey. Burger morphs into an ✕.

### 3.3 Buttons

| Variant | Size | Padding | Fill / text | Radius | Hover |
|---|---|---|---|---|---|
| Primary L (on dark) | 140×50 | 6px 18px | `#fff` / `#000` Inter 16/26 | 50px | fill drops to ~70% white (translucent grey) |
| Secondary L (outline, on dark) | 179×50 | 6px 18px | transparent / `#fff`, 1px `rgba(255,255,255,.7)` border | 50px | border/text dim slightly |
| Primary M | 141×50 | 6px 18px | `#fff`/`#000` | 50px | same as above |
| Primary S | 109–168×37 | 6px 16px | `#fff` / `#171719` 14/21 | 50px | translucent |
| Header CTA | 87×36 | 6px 12px | white→black (theme) 12px | 50px | translucent |
| Solid dark (forms, cookie) | 143×40 / full width | 0 / 12px 16px | `#000` / `#fff` 12–14px | 10px | ≈ `#1d1d1f` |
| Neutral (cookie reject) | ≈160×34 | — | `#eeeeee` / `#171719` | 8px | darker grey |
| Icon circle (carousel) | 36×36 | — | `#f5f5f5`, chevron 14px | 1000px | darker grey; disabled = 40% opacity |
| Icon circle (closer cards) | 44×44 | — | dark `#393939` on light card / white on glass card, arrow 18px | 50% | — |
| Text link | inline | — | `#3286f5` (legal) or underline (menu cards) | — | — |

Transition on all Framer variants is `all` with ≈0.2–0.3s ease (Framer default spring/tween). Focus: none custom on buttons (browser default outline).

### 3.4 Cards
1. **Case-study card (carousel):** `a.card` 583×583 (1:1) at 1440; 480×480 tablet; 330×391 phone. Full-bleed photo `object-fit: cover`, radius 10.37px, padding 32px. Top-left H3 32px (white, 2 lines, max 486px), top-right "↗" glyph 32px, bottom-right client logo (≈100–195×62, white, contain).
2. **Product card (AI OS / platform cards):** 431×618 (≈7:10), radius 8px, abstract blurred-gradient image; centred product wordmark (175–216×28); bottom-centred description 14px white (2 lines) + Primary S "Explore" button.
3. **Feature cell:** inside 3/4/2-column grids. Left border 1px `rgba(255,255,255,.12)` on dark or `#e6e6e6` on light; padding ~32px; 24px line icon top; ~64px space; H4 26px title; 14px body `#6b6b6b` / 70% white. Light variant on `#fafafa` background uses white cells with 1px border.
4. **Pillar card (dark homepage section):** 592×699, radius 8px, photo with bottom dark fade; centred H3 32px + body 17px 70% white (max 490px) + Primary S button; text block anchored ~140px from bottom.
5. **Expandable duo (Deployment, Systems, Strategy):** two cards in a row (≈794 + 470 width, 542 tall at 1440). Default: left card = photo + title + body; right card = `#f5f5f5` panel with title only. **Hover on either swaps widths** (flex-grow transition ≈0.5s) and reveals the hovered card's photo/body.
6. **Closer glass cards (homepage):** "About" 768×312 solid `#f5f5f5`, "Careers" 502×312 `rgba(245,245,245,.2)` + `blur(10px)`; radius 12px; padding 32px; label Inter 42px bottom-left; arrow circle bottom-right.
7. **Press card:** square 696px (2-up) or 342px (4-up); radius 8px; tag chip top-left ("• Type", 14–17px white); outlet logo top-right (≈190×48); full-bleed image; bottom gradient with outlet name (14px, 70% white) + headline (≈26px display, white).
8. **Blog card:** image 420×236 (16:9) radius 8px; 18px gap; H4 26px title (2-line clamp with ellipsis); date 14px `rgba(49,49,49,.6)`.
9. **Story card (About):** image 282×238 radius 4px + 17px title underneath.
10. **Hover row ("Why choose us", careers roles, enterprise rows):** full-width row ~317px pitch, 1px top divider. Columns: title H3 32px left (x=60), reveal image 310×196 at centre (x=688, radius 4px, opacity 0 → 1 on hover), description 14px right (x≈1072, max 300px). Hover: row bg `#f5f5f5`, an em-dash "—" slides in before the title and pushes it ~24px right.

### 3.5 Tabs
- **Industry tabs (homepage):** segmented pill track `#f5f5f5`, radius 999px, padding 4px, width 649px (desktop). Items 35px tall, padding 9px 16px, label Inter 14px −0.84px; inactive `#6e6e6e`; active = white pill + `#141414`. Panel below: 1200×600 photo card radius 12px, centred title 72px white, triad tagline 17px 88% white, "Explore more" white pill 12px (≈110×32). Switching crossfades image and title (≈0.4s); URL updates with `?selected-industry=` query param. No autoplay observed. Phone: track scrolls horizontally, panel 359×460.
- **Phase tabs (Deployment):** dark track `rgba(255,255,255,.08)` with 3 pills ("Phase 01–03"), 12px labels. Panel: title 26px white, progress bar (4px, `#3286f5` fill on white 20% track, width 75/50/25%) with large percentage (≈48px, `#3286f5`) right-aligned, body 14px, 3 grey chips (`rgba(255,255,255,.1)`, radius 4px, 12px text).

### 3.6 Accordions
- **Feature accordion (Agents, Industry "Streamline"):** left column 450px; items separated by 1px dividers; active item = title 20px white + body 14px 70% white; inactive = title 20px 60% white only. Right: media 758×626/700 radius 4–8px swapping per item.
- **Numbered accordion (Strategy):** rows "01 Title" + chevron-down 12px; first row open with paragraph 14px; 1px dividers; 100px row pitch.

### 3.7 Logo strip
Not a moving marquee: a static **grid of tiles** (6×2 desktop home, 4×2 industry pages, 3×4 phone, 3×2 investors on About). Tile 217×80 (home) / 210×80 (industry) / 150×80 (investors), bg `#fafafa`, radius 4px, gap 4px; logos greyscale (≈`#9ba1a5` tone) `object-fit: contain`, ~170×79 box. Title above: H2 26px centred.

### 3.8 Carousel (case studies)
Horizontal flex track (gap 16px), 7 cards, first card aligned to the gutter; overflow visible to the right (peek). Controls top-right in the heading row: two 36px circles (prev disabled at start). Click scrolls by one card with smooth motion; touch-swipe on phone.

### 3.9 News blocks
- Mega-menu featured card (see 3.2).
- About "Stories" row (4 cards).
- Blog featured post: 823×463 image left (radius 8px) + right column (date 14px, H3 32px title, excerpt 17px grey) vertically centred.
- "More posts" row at article end: 3 cards 380×214.

### 3.10 Forms
- **Contact form:** right half of a split screen. Title (≈26px display), intro 12px grey. Grid: 2 columns × 228px, column gap 24px, row gap ≈50px; labels 14px `#000` 8px above fields. Field = wrapper 228×40 (`#f5f5f5`, 1px `#eeeeee`, radius 8px, padding 12px 16px) + bare input 14px, placeholder `#a0a0a0`. **Focus:** border 1px `#3286f5` (≈) + fill `rgba(0,0,0,.04)`, no shadow. Selects are custom buttons with chevron that rotates 180° and open a white list (14px rows, 36px tall, light shadow) under the field. Submit: black 143×40, radius 10px, 12–14px label.
- **Report form (AI Safety):** white card radius 12px with soft shadow, 2×2 inputs + textarea (≈90px) + full-width black submit + 10px legal note.

### 3.11 Cookie banner
Fixed top-right (x = viewport − 380, y = 20). Card 360×179, white, radius 14px, `inset 0 0 0 1px rgba(0,0,0,.05)`, padding 20px. Title 16px; text 12px grey with inline link "Cookie Policy" (grey underline); two buttons side by side: "Reject" (`#eee`) and "Accept" (black), each ≈160×34, radius 8px. Reopened via "Cookie Settings" button in footer.

### 3.12 CTA band (pre-footer)
Full-bleed 1444×640 abstract blurred photo (blue/grey motion blur) fading to `#080808` at the bottom; centred H2 48px white (2 lines) + Primary M button. Padding 160px 60px. On light-footer pages the band is omitted.

### 3.13 Footer
- **Dark variant:** bg `#080808`, height ≈505px. Left block (x=122): logo 122×30, tagline 12px 70% white (2 lines, 183px), Primary S "Get in touch", copyright 12px 70% white. Five columns starting x≈514 (Platform 6 links, Industries 7, Company 6, Social 2, Legal 6 + "Cookie Settings" button); column heading 12px 70% white; links 14px/500 light grey with ≈27px pitch. **Giant wordmark** image 1356×324 at the bottom in `#1a1a1a` on black (cropped by viewport).
- **Light variant (/safety):** same layout, white bg, dark text, watermark very light grey.
- Phone: two-column link groups stacked, watermark 100% width.

---

## 4. Animations & interactions

### 4.1 Libraries detected
- **Framer runtime** (React + Framer Motion bundled inside Framer's `script_main` module and ~40 `modulepreload` chunks). Evidence: `<meta name="generator" content="Framer …">`, `framerusercontent.com/sites/<id>/…` modules, two inline `<script type="framer/appear">` blocks (appear-effect timelines), `data-framer-appear-id` on 6 hero elements, `data-framer-name` on every layer.
- **Not present:** GSAP / ScrollTrigger, Lenis or any smooth-scroll library (native scroll), Lottie/bodymovin, Swiper/Splide, Barba, SplitType (words are split by Framer's text effect), jQuery.
- A **2D `<canvas>`** (1324×910) renders the dotted globe on Careers.
- `@media (prefers-reduced-motion: reduce)` rule exists (Framer disables appear/scroll effects).

### 4.2 Load / appear effects
| Element | From → To | Timing |
|---|---|---|
| Hero H1, sub, buttons (Framer appear) | opacity 0, y ≈20px → 1, 0 | ≈0.6s, staggered ≈0.1s, ease-out, on first paint |
| Hero background video | autoplay muted loop playsinline; multi-scene montage (warehouse robot, airport, plane, office…) cuts every ≈3–4s | continuous |

### 4.3 Scroll-triggered reveals
1. **Word-by-word blur reveal** (every display H2/H3 on light and dark sections, the industry hero H1, card titles in dark sections).
   - Each word is an `inline-block` span. Initial: `opacity: 0; filter: blur(6px); transform: translateY(16px)`.
   - On entering the viewport (≈15–20% visible), each word animates to `opacity 1, blur 0, y 0`. Measured: a single word completes in ≈0.30s; stagger between words ≈0.045s; curve = strong ease-out (≈`cubic-bezier(.22,1,.36,1)`). A 7-word heading finishes in ≈0.6s. Plays once.
2. **Scroll-scrubbed word fill (pinned statement)** — Home "Main" section (800px tall, inner sticky 100vh) and Careers statement.
   - Words start `color: rgba(144,144,144,.26)`; as you scroll, a moving front recolours them to `#4a4a4a`, with ~4 words in transition (graded alphas .88 → .63 → .39). Two keyword runs finish at pure black for emphasis. Fully filled after ≈600px of scroll. No blur, no transform.
3. **Section/card fade-up:** media blocks and cards fade from opacity 0 / y 24–40px on enter (≈0.6s).
4. **Count-up numbers** (Deployment "40+", Utilities 75% / 91% / 77%): start at `0+` / `0%`, count over ≈1.2–1.5s when visible.
5. **Expanding video (AI Gateway):** a 1704px-tall section pins a video that starts at 818×461 (centred, radius 0) and scales up to full-width as you scroll, while a vertical list of model names scrolls past behind a centred product lockup.
6. **Parallax:** none detected on photos (backgrounds are static `object-fit: cover`). Depth comes from pinning, not parallax.

### 4.4 Ambient / looping
- **Dot-grid "OS" animation** (Home dark section, AI OS hero): 264 square dots 7×7 on a ~65px grid; ~38 white at 54% opacity, ~28 orange `#fc762f`, rest invisible — dots toggle in waves. A black 29×29 "cursor" square and a monospace label chip (white `#f5f5f5` pill ≈40×29+, 1px black square marker) hop between grid points, cycling 10 feature names. Background: grainy blurred cloud photograph.
- **Stack diagram (AI OS):** glass panel with 7 layer rows; the highlighted layer and the left caption change in sequence (≈3–4s per layer).
- **Announcement ticker:** ≈5s interval, vertical slide.
- **Globe (Careers):** rotating dotted sphere on canvas; blue city labels (12px, `#3286f5`) with leader lines appear as cities rotate into view.

### 4.5 Hover & click micro-interactions
- Buttons: fill/opacity change ≈0.2s (see 3.3).
- Nav items: open mega-menu on hover with ≈0.25s fade/slide-down; header bg transitions to white.
- Hover rows: bg tint + em-dash slide + image fade (≈0.3s).
- Expandable duo: width swap (≈0.5s ease-in-out).
- Industry tabs / phase tabs: active pill slides (layout animation ≈0.3s), panel crossfade; progress bar width animates.
- Carousel arrows: scroll by one card (smooth ≈0.5s).
- Selects: chevron rotate 180°, list fade-in ≈0.15s (`opacity .15s` transition measured).
- Header CTA / pills: `transition: all` everywhere (Framer default) — 1,200 elements carry `transition: all`.

### 4.6 Auto-playing carousels
None of the content carousels autoplay (case studies are manual). Only the ticker, the hero video, the dot grid, the stack diagram and the globe run on their own.

### 4.7 Recreating it (suggested stack)
- Next.js/Astro + **Motion** (Framer Motion) for appear/whileInView and layout animations, or **GSAP + ScrollTrigger** for the pinned fill and the expanding video.
- Word split: wrap words in spans server-side; animate with `stagger(0.045)`.
- Use `position: sticky` for pinned sections; drive progress with `useScroll({ target, offset: ["start start","end end"] })`.

---

## 5. Responsive behaviour

Method: window resized so the viewport was 1444, 1024, 768 and 407 px; pages reloaded where the header variant is chosen at load (Framer picks the breakpoint variant on load — a live resize without reload kept the desktop header overflowing at 407px).

### 5.1 Global (all pages)

| Aspect | 1440 | 1024 (tablet 810–1199) | 768 (phone variant) | 390/407 |
|---|---|---|---|---|
| Gutter | 60px | 40px | 24px | 24px (16px in menu) |
| Announcement | 48px | 48px | 40px | 40px, label 14px, may truncate |
| Header | full nav + EN pill + CTA | full nav (tighter) | burger + "EN" text, no CTA | same |
| H2 | 48px | 42px | 34px | 34px |
| Hero sub | 20px | 20px | 17px | 17px |
| Section padding | 120px | 120/80px | 60px | 60px |
| Grids | 3–6 columns | 2–3 columns | 1–3 columns | 1 column (logos 3) |
| Footer | logo block + 5 columns in a row | same, compressed | logo block on top, links in 2-col groups | same |

### 5.2 Home
- **1440:** hero 100vh (710px) — H1 bottom-left (x=60, 3 lines, left-aligned), sub + buttons bottom-right (x=1014). Logo grid 6×2 tiles 217×80. Cards 583². Pinned statement 62px. Pillar cards 592×699 side by side. Industry card 1200×600. Closer: H2 left + paragraph right; cards 768 + 502.
- **1024:** hero shrinks to **604px** and becomes **centred** (H1 82px centred, sub and buttons centred under it). H2 42px, card titles 22px, cards 480². Logo tiles shrink (154×72). Industry card 944×600, tab title 54px. Statement section bottom padding 330px.
- **768 / 407:** hero 639px; H1 42px centred (3 lines); buttons 109×44 + 160×44 side by side. Logo grid **3 columns × 4 rows** (tiles ≈117×54 at 407, 237×110 at 768). Carousel cards 330×391 with peek of next card; arrows hidden (swipe). Statement ≈34px. Dark section: dot grid simplified; pillar cards stack full-width (359 wide). Tabs scroll horizontally; tab panel 359×460; title 38px. Closer: H2 34px, paragraph, two stacked cards (≈359×110) with arrow circles. Footer: logo block, then link columns in a 2×3 layout; watermark full width.

### 5.3 Product pages (AI OS, Agents, Systems, Gateway)
- **Hero:** 675px (1252px on Gateway) centred lockup + H1 64px → phone ≈40px, 2–4 lines.
- **Split sections** (text left / media right 758–784px wide) → stack text above media on phone; media full width, aspect preserved.
- **3-up product cards 431×618** → tablet 2-up/horizontal scroll, phone stacked full-width (≈359×515).
- **Feature grids:** 3/4 columns → 2 columns on tablet → 1 column on phone, vertical dividers become horizontal top borders.
- **Enterprise rows** (title | image | text) → phone: title, then text; hover image hidden.
- **Gateway dashboard mock:** scales down; on phone it is cropped inside a horizontally clipped frame.

### 5.4 Service pages (Deployment, Strategy)
- Hero 604px photo; phone ≈520px with H1 ≈36px.
- Expandable duo → stacked cards on phone (hover expansion disabled; both show content).
- Phase tabs remain tabs; percentage drops below the bar on phone.
- Strategy long-form: sticky left heading + right text → single column, heading not sticky.

### 5.5 Industry pages (×7)
- **1440:** giant 200px industry name bottom-left + vertical 1px rule + 20px sub at right.
- **Phone:** H1 70px, sub moves under it with the rule on its left. Logo grid 2 columns. Benefits stack. Accordion: image moves above/below list. Hover rows become static blocks. *Observed overflow bug:* accordion body text is clipped on the right edge at 407px — avoid replicating.

### 5.6 Company & content pages
- **About / Careers:** split hero (H1 left, sub right) → stacked; 1324×800 image → full-width 4:3. Investor grid 3×2 → 2×3. Story cards 4-up → 2-up → 1-up. Globe canvas scales to width.
- **Press:** bento 2-up/4-up → 2-up → 1-up squares.
- **Blog:** featured post side-by-side → image on top; grid 3 → 2 → 1 columns; filter pills scroll horizontally.
- **Article:** 600px column → full width minus 24px gutters; hero media full-bleed-ish.
- **Contact:** 50/50 split → image panel collapses to a short header block with H1, form full width underneath.
- **Legal:** 980px text → full width, 17px stays; justified text kept.

---

## 6. Pages one by one

Format per section: **layout** → **text slots** (`[Type · lines · ~words · role]` + *Rewritten version*) → **media**. Page-level tone and message hierarchy follow each page.

Global slots repeated on every page (rewrite once, reuse):

- `[Ticker item 1 · 1 line · ~4 words · role: marquee partnership credibility]` — *Rewritten:* "[CLIENT] picks [BRAND] for AI" + link `[2 words · role: open story]` *"See story →"*
- `[Ticker item 2 · 1 line · ~5 words · role: funding/traction news]` — *Rewritten:* "[BRAND] secures [FIGURE] to grow"
- `[Header CTA · 3 words · role: contact]` — *Rewritten:* "Talk to us"
- `[CTA band H2 · 2 lines · ~7 words · role: closing invitation]` — *Rewritten:* "Ready to change how your company runs?"
- `[CTA band button · 3 words · role: contact]` — *Rewritten:* "Book a conversation"
- `[Footer tagline · 2 lines · ~7 words · role: brand promise]` — *Rewritten:* "A new way of operating, built with [BRAND]."
- `[Footer copyright · ~5 words]` — *Rewritten:* "© [YEAR] [BRAND] Ltd."

---

### 6.1 Home — `/`  (height 6,708px @1440)

**S1 · Hero** — full-viewport (710px) background **looping video** (16:9 MP4, multi-scene enterprise montage), dark scrim; H1 3 lines bottom-left; sub + 2 buttons bottom-right; header transparent on top.
- `[H1 · 3 lines · ~6 words · role: outcome-driven promise, verb-first]` — *Rewritten:* "Rewire how / your company works / with AI"
- `[Sub · 2 lines · ~13 words · role: who it's for + what they unlock]` — *Rewritten:* "[BRAND] gets large organizations using AI for real, so every team reaches its full capacity."
- `[Primary button · 3 words · role: contact]` — *Rewritten:* "Talk to us"
- `[Secondary button · 3 words · role: product exploration]` — *Rewritten:* "Tour [PRODUCT]"
- Media: video 1444×710 cover, MP4 from own CDN, autoplay/muted/loop/playsinline, no poster.

**S2 · Social proof** — centred small H2 + 6×2 logo tile grid. Padding 80px 60px 0.
- `[H2 small · 1 line · ~6 words · role: social proof framing]` — *Rewritten:* "Chosen by category leaders in every sector"
- Media: 12 client logos (PNG/SVG, 250×70 or 500×140 natural, greyscale), tiles 217×80 `#fafafa`.

**S3 · Case-study carousel** — H2 left + arrows right; horizontal track of 7 square cards.
- `[H2 · 1 line · ~8 words · role: reframe as business outcomes]` — *Rewritten:* "Real results on the work that drives revenue."
- `[Card H3 ×7 · 2 lines · 4–7 words each · role: quantified outcome headline]` — *Rewritten set:*
  1. "A national carrier, now run by agents"
  2. "Debt recovery for [FIGURE] account holders"
  3. "Why models alone never ship results" *(essay card)*
  4. "IT support automated across a whole station network"
  5. "[FIGURE]% of queries resolved without a human"
  6. "Open architecture as a competitive edge" *(essay card)*
  7. "Energy billing issues closed start to finish"
- Media: 7 square photos 583×583 (cover, radius 10px), 5 with white client logo overlay; 2 essay cards use abstract/graphic artwork (dark code-texture, illustration).

**S4 · Pinned manifesto** — 800px section, sticky 100vh stage, one centred paragraph 62px (max 940px) filled word-by-word on scroll.
- `[Statement · 5 lines · ~17 words · role: positioning — three assets combined into one offer]` — *Rewritten:* "One partner for the software, the people on the ground and the roadmap — so your organization actually changes how it works."
- Media: none (white).

**S5 · Platform (dark)** — 1,654px dark block with grainy cloud photo background, animated dot grid, centred product lockup + H2 + button; then two tall pillar cards side by side.
- `[Product lockup · wordmark + product name]` → "[BRAND] [PRODUCT]"
- `[Floating tags · 10 × 1 word · role: hint at platform modules]` — *Rewritten set:* "Sources · Triggers · Access · Playbooks · Router · Console · Tests · Policies · Spaces · Memory"
- `[H2 · 2 lines · ~8 words · role: product definition]` — *Rewritten:* "A single AI layer the whole company runs on"
- `[Primary button · 3 words · role: product page]` — *Rewritten:* "Meet [PRODUCT]"
- `[Pillar 1 H3 · 2 lines · ~5 words · role: service — local delivery teams]` — *Rewritten:* "Engineers beside you, in every country."
- `[Pillar 1 body · 2 lines · ~17 words · role: how the engagement works]` — *Rewritten:* "A local crew builds alongside your staff, hands over the keys, then tackles the next problem."
- `[Pillar 1 button · 3 words]` — *Rewritten:* "How we deploy"
- `[Pillar 2 H3 · 2 lines · ~5 words · role: service — strategy]` — *Rewritten:* "A plan that makes AI stick."
- `[Pillar 2 body · 2 lines · ~12 words · role: what strategy decides]` — *Rewritten:* "Which problems first, in what sequence, and how your teams must evolve."
- `[Pillar 2 button · 3 words]` — *Rewritten:* "See our method"
- Media: background photo 1444×1405 (16:9 natural, grain), 2 photos 592×699 (people at whiteboard; motion-blurred landscape), radius 8px.

**S6 · Industries tabs** — white, padding 120px 60px; centred H2 (2 lines), segmented tabs, 1200×600 photo panel.
- `[H2 · 2 lines · ~5 words · role: specialisation in high-stakes sectors]` — *Rewritten:* "Made for sectors where errors are expensive"
- `[Tab labels · 7 × 1 word]` → your [INDUSTRY] names.
- `[Panel title · 1 word · role: industry name]` → "[INDUSTRY]"
- `[Panel tagline · triad "A, B and C" · 3–5 words · role: the industry's core values]` — *Rewritten set:* Banking "Precision · Oversight · Confidence"; Telecom "Uptime · Volume · Pace"; Healthcare "Protection · Discretion · Wellbeing"; Retail "Relevance · Reach · Loyalty"; Utilities "Continuity · Capacity · Care"; Insurance "Rigor · Auditability · Assurance"; Airlines "Recovery · Yield · Experience".
- `[Panel button · 2 words]` — *Rewritten:* "Learn more"
- Media: 7 photos 1200×600 (cover, radius 12px) — motion-blurred people in sector settings.

**S7 · Closer / company** — full-bleed dark photo (1444×716) with H2 left, paragraph right, then two cards.
- `[H2 · 2 lines · ~7 words · role: mission + team pride]` — *Rewritten:* "We're assembling the people who'll define applied AI."
- `[Paragraph · 4 lines · ~30 words · role: vision + hiring hook]` — *Rewritten:* "Picture one system that makes every employee, process and product smarter and faster. It's early days — and we're looking for the people who will build it with us."
- `[Card label 1 · 2 words]` — *Rewritten:* "Our story"; `[Card label 2 · 1 word]` — *Rewritten:* "Join us"
- Media: background photo; 2 cards with arrow icons.

**S8 · Footer (dark)** — see 3.13.

**Tone & devices:** confident, executive register; short declaratives; verbs of acceleration and execution (accelerate, drive, unlock, transform, solve). Heavy use of **triads** (platform/teams/strategy; "A, B, and C" taglines). Numbers only inside proof cards (percentages, client counts). Repetition of "enterprise" and "transform" as brand keywords. Sentences 6–17 words; no questions, no exclamation marks.

**Message hierarchy:** (1) Big promise: AI transformation at enterprise scale → (2) Proof: logos → (3) Proof in outcomes: case cards → (4) Thesis: we combine software + people + strategy → (5) The three pillars explained (platform, deployment teams, strategy) → (6) Credibility in regulated industries → (7) Company/hiring → close with CTA in footer.

---

### 6.2 AI OS — `/ai-os`  (6,424px)

**S1 · Hero** — 675px; grainy dark cloud photo + dot-grid animation with floating monospace chips; centred lockup (193×31) + H1 2 lines (64px).
- `[H1 · 2 lines · ~10 words · role: product category definition, naming the three users]` — *Rewritten:* "Where your people, agents and software finally share one system."
- Media: background image 1444×675 (PNG, grain); animated dots.

**S2 · Infrastructure diagram (dark)** — padding 140px 60px; left: H2 + active-layer caption; right: 758×566 image card with glass stack diagram (7 rows).
- `[H2 · 2 lines · ~6 words · role: completeness claim]` — *Rewritten:* "Everything enterprise AI needs to run."
- `[Layer names · 7 × 1–3 words · role: architecture vocabulary]` — *Rewritten set:* "Access & Policy · Monitoring · Automations · Builder Tools · Memory · Model Hub · Connectors"
- `[Active caption title · 3 words]` — *Rewritten:* "Access & Policy"
- `[Active caption body · 3 lines · ~25 words · role: what the layer does]` — *Rewritten:* "Decides which people and agents may reach which records and actions — and applies those rules everywhere AI runs in the company."
- Media: blurred blue landscape photo 758×566 radius 8px + HTML diagram overlay.

**S3 · Unified platform cards (dark)** — H2 left (2 lines) + 3 product cards 431×618.
- `[H2 · 2 lines · ~8 words · role: invite to explore the suite]` — *Rewritten:* "Three ways to change how work gets done"
- `[Card desc ×3 · 2 lines · ~7 words each]` — *Rewritten:* (1) "Agents that serve customers, help staff and finish tasks." (2) "Core business software, rebuilt natively for AI." (3) "One control point for every model you use."
- `[Card button ×3 · 1 word]` — *Rewritten:* "Discover"
- Media: 3 abstract blurred-gradient images (sky blue / red-orange flower / olive), product wordmarks.

**S4 · Advantages grid (dark)** — padding 120px 60px; H2 1 line + intro paragraph (max ~620px) + 3×2 feature cells with icons.
- `[H2 · 1 line · ~7 words · role: thesis]` — *Rewritten:* "Why one open layer beats a stack of tools"
- `[Intro · 3 lines · ~30 words · role: explain the single-environment idea]` — *Rewritten:* "When goals, context, models, workflows, controls and interfaces all live on the same foundation, execution stops being a relay between tools and becomes one continuous flow."
- `[Feature ×6 · title 2–3 words + body ~30 words]` — *Rewritten set:*
  1. "Any model, any time" — "Nothing you build is tied to one model provider. Each task goes to the best fit, and newcomers slot in without rewiring your work."
  2. "Faster every launch" — "Access rules, connectors and audit trails are set up once and reused, so use case number ten ships quicker than use case number one."
  3. "One source of context" — "Every agent and app reads the same data under the same permissions, so nobody re-keys information between systems."
  4. "Governance in one place" — "As agents multiply, a single control point keeps access, quality and spend growing in step rather than out of control."
  5. "Learning that compounds" — "Every decision routed through the platform becomes a record of how your business really runs — an asset competitors can't copy."
- Grid: 5 cells laid out 3 + 2 (second row left-aligned, third slot empty).
- Media: 5 line icons 24px.

**S5 · Built for the enterprise (light)** — padding 120px 0; big multi-line statement (first sentence dark, rest grey) + 4 hover rows (title | 310×196 image | description).
- `[Statement · 4 lines · ~25 words · role: enterprise-grade reassurance]` — *Rewritten:* "Ready for the enterprise. Hosting, data protection and compliance are each engineered to the standard large organizations demand."
- `[Row ×4 · title 2–3 words + desc ~15–20 words]` — *Rewritten set:*
  1. "Deploy your way" — "Shared cloud, dedicated tenant or your own account on [CLOUD A], [CLOUD B] or [CLOUD C]."
  2. "Security built in" — "Injection defence, agent guardrails, governed tool gateways and independent penetration tests [FIGURE] times a year."
  3. "Your data stays yours" — "No retention by model providers, automatic masking of personal data and [ENCRYPTION STANDARD] encryption."
  4. "Certified and audited" — "[CERTIFICATION], [CERTIFICATION] and [REGULATION]-aligned, re-verified by third parties every year."
- Media: 4 small product/abstract images 310×196 (revealed on hover).

**S6 · CTA band** (global).

**Tone:** technical-architectural, still executive; nouns of infrastructure (layer, governance, routing, context). Benefit-led feature titles in 2–3 words. **Hierarchy:** define → show architecture → products → why unified → enterprise trust → CTA.

---

### 6.3 Agents — `/agents`  (5,947px)

**S1 · Hero** — 675px, soft blue sky gradient photo (light, airy), centred lockup (181×29) + H1 + sub.
- `[H1 · 2 lines · ~5 words · role: ubiquity promise]` — *Rewritten:* "Agents that work wherever you do"
- `[Sub · 2 lines · ~11 words · role: three jobs agents do]` — *Rewritten:* "[BRAND] agents talk to customers, back up employees and complete the work itself."

**S2 · Use cases (white)** — H2 + 3 cards 431×529 with UI-mockup or photo backgrounds, text at bottom.
- `[H2 · 1 line · ~5 words]` — *Rewritten:* "Change how work gets done"
- `[Card ×3 · title 3–4 words + body ~25 words]` — *Rewritten:*
  1. "Run whole processes" — "Agents take a request the moment it lands and carry it through every step until it's closed — not just the first reply."
  2. "Delight and grow customers" — "Every channel answered faster and better, with each conversation a chance to sell more."
  3. "Give every employee a co-pilot" — "Agents pull from company knowledge to answer, advise and finish tasks next to your people."
- Media: card 1 = workflow-builder UI mock on pastel gradient; card 2 = office photo; card 3 = chat UI mock on blue gradient. Radius 8px.

**S3 · Capabilities accordion (dark)** — H2 left 2 lines; 5 items (first open); right media 758×626 (animated "tool calls" floating around a glossy orb).
- `[H2 · 2 lines · ~4 words]` — *Rewritten:* "Made for messy, real work"
- `[Items ×5 · title 3–4 words; open body ~18 words]` — *Rewritten:* "Every channel, every format" — "Phone, chat, email, files and whatever comes next; agents handle all of them." / "Copes with complexity" / "Plugged into your systems" / "Grounded in your knowledge" / "Tested before launch"
- Media: animated illustration 758×626.

**S4 · Case carousel** — same component as Home (5 cards, square 583).

**S5 · Team features (light grey `#fafafa`)** — H2 + 2-line intro + 4×2 white feature cards (icon + title + 2-line body).
- `[H2 · 1 line · ~6 words]` — *Rewritten:* "Made for teams shipping at scale"
- `[Intro · 2 lines · ~22 words]` — *Rewritten:* "All the tooling a team needs across an agent's life — first draft, testing, release and tuning in production."
- `[Feature ×8 · 1–2-word title + ~10-word body]` — *Rewritten set:* "Spaces — Separate areas per team, project or unit." / "History — Every edit logged; restore any version." / "Library — Build once, reuse agents, skills and tools everywhere." / "Roles — Control who builds, edits and publishes, per resource." / "Skill packs — Package a procedure once, plug it into any agent." / "Agent handoff — Pass work between agents on different platforms via [PROTOCOL]." / "Auto-labels — Tag every conversation so insights are searchable." / "Split tests — Route traffic to two variants and keep the winner."
- Media: 8 filled glyph icons 24px.

**S6 · Platform cards** (same 3-card component; this page shows the other three offerings). **S7 · CTA band.**

**Tone:** practical, verb-heavy ("engage, assist, execute"); feature names as nouns. **Hierarchy:** promise → 3 jobs → capabilities → proof → team tooling → cross-sell → CTA.

---

### 6.4 Systems — `/systems`  (6,102px)

**S1 · Hero** — 675px, red/orange blurred floral photo, lockup (210×31) + H1 2 lines + sub.
- `[H1 · 2 lines · ~11 words · role: replacement promise]` — *Rewritten:* "Retire legacy tools for software shaped around your business."
- `[Sub · 2 lines · ~15 words]` — *Rewritten:* "AI-native applications we design, build and operate for you — fitted to how your teams actually work."

**S2 · Split (white)** — left: H2 2 lines, intro, 3 list items with dividers; right: photo 784×719 (person at laptop with app UI).
- `[H2 · 2 lines · ~4 words]` — *Rewritten:* "Finally, software that bends to you."
- `[Intro · 2 lines · ~14 words · role: historical contrast]` — *Rewritten:* "For years companies reshaped themselves to suit their tools. That era is over."
- `[Item ×3 · title 4–6 words + body ~30 words]` — *Rewritten:*
  1. "Your requirements come first" — "Off-the-shelf suites force your business into their data model. [PRODUCT] starts from your real processes on day one instead of being bent into shape later."
  2. "Evolves as you do" — "Your organization keeps moving, so the software moves with it — no waiting for someone else's roadmap."
  3. "A screen for every role" — "Old systems show everyone the same interface. [PRODUCT] tailors each view to the person and the task."

**S3 · Outcomes (dark)** — H2 + sub + 3 feature columns.
- `[H2 · 1 line · ~5 words]` — *Rewritten:* "What changes with [BRAND]"
- `[Sub · 1 line · ~11 words · triad]` — *Rewritten:* "Cheaper to run, quicker to change, fewer systems to hold together."
- `[Feature ×3]` — "Modernise in weeks" — "Replacing core systems is usually slow and risky; this takes weeks, not years." / "Lower lifetime cost" — "Most software spend goes on customisation and services; AI-driven building keeps that minimal." / "Fewer, simpler systems" — "Work spread across many tools can finally live in one tailored application."

**S4 · Core systems grid (dark)** — H2 + 2×2 cards 650×455 with dark app-UI screenshots; title bottom-left 26px.
- `[H2 · 1 line · ~6 words]` — *Rewritten:* "Build or replace your core systems"
- `[Card titles ×4 · 2–3 words]` → "[SYSTEM TYPE]" (e.g., customer records, customer value, knowledge base, people management).
- Media: 4 product UI screenshots (dark dashboards).

**S5 · Delivery (white)** — H2 2 lines + expandable duo (photo card "rollout" / grey card "any infrastructure").
- `[H2 · 2 lines · ~7 words]` — *Rewritten:* "Rolled out where you operate, by local experts"
- `[Card 1 title · 2 words + body ~25 words]` — *Rewritten:* "Engineer-led rollout" — "Our engineers map how the function really runs, build the system around it and move your data and processes off the old tool."
- `[Card 2 title · 2 lines · ~5 words]` — *Rewritten:* "Any cloud or on-site, fully governed"
- Media: photo 720×542 (person at desk, motion blur).

**S6 · Platform cards**, **S7 · CTA band.**

**Tone:** contrarian ("software finally adapts to you"), before/after framing. **Hierarchy:** replace legacy → why custom wins → business outcomes → which systems → how it's delivered → CTA.

---

### 6.5 AI Gateway — `/ai-gateway`  (7,005px)

**S1 · Hero (1,252px)** — warm blurred gradient photo; lockup (255×32) + H1 2 lines + sub; below, an **interactive HTML dashboard mock** (dark, 1324px wide, rounded 12px) with sidebar nav, KPI tiles, cumulative-spend chart, spend-by-model bars, router savings, failover funnel.
- `[H1 · 2 lines · ~6 words · role: control promise]` — *Rewritten:* "One cockpit for all your company's AI"
- `[Sub · 2 lines · ~14 words · triad of verbs]` — *Rewritten:* "Send every AI request through a single point to see it, steer it and trim its cost."
- `[Dashboard microcopy · dozens of 1–4-word labels + figures]` — replace with your own product labels and [FIGURE] placeholders; keep the structure: section label → KPI ×4 → chart with budget line → share-of-spend list → savings card → reliability funnel.
- Media: background photo 1444×1252; live HTML/SVG charts.

**S2 · Video showcase (1,704px, dark)** — pinned video expanding from 818×461 to full width; behind the lockup a vertical scrolling list of model names with provider icons.
- Slots: product lockup only. *Rewritten:* "[BRAND] [PRODUCT]"
- Media: product video (UI notifications, team icons), play affordance; model list (text + logos) — replace with your own integrations.

**S3 · Feature grid (dark)** — 2 columns × 3 cards 650×455; each card = UI illustration top + title 26px + body 17px 70% white.
- `[Card ×6 · title 3–5 words + body ~20 words]` — *Rewritten:*
  1. "Connect anything" — "Popular tools plug in as ready-made providers, the rest via our SDK, and our own products connect natively."
  2. "Usage and budget control" — "See tokens and spend per team, then set caps and restrict pricey models."
  3. "Who-gets-what policies" — "Give premium models to the teams that need them and lighter ones to everyone else."
  4. "Smart routing" — "Simple prompts go to small models, hard ones to heavyweight models — automatically."
  5. "Privacy shield" — "Outbound requests are scanned and personal data masked before any vendor sees them."
  6. "Session analytics" — "Complete logs of who did what, to explain cost spikes and spot misuse."

**S4 · Problem statement (dark)** — H2 2 lines (second line grey) + 2 short paragraphs.
- `[H2 · 2 lines · ~16 words · role: problem → solution in two beats]` — *Rewritten:* "AI adoption is running ahead of oversight. This is where you regain it."
- `[Para ×2 · ~15 words each · role: cause, consequence]` — *Rewritten:* "As usage grows, each department picks its own tools." / "With no single checkpoint, costs balloon and security holes appear."

**S5 · Business value (dark)** — H2 + 4-column feature cells.
- `[H2 · 1 line · ~5 words]` — *Rewritten:* "What it changes for you"
- `[Cell ×4 · title 3–4 words + body ~15 words]` — *Rewritten:* "Every request, one place" — "Stop stitching together usage reports from scattered tools." / "Full visibility" — "Know what's used, by whom and at what cost, without chasing anyone." / "Lower spend" — "Quit paying premium rates for simple jobs." / "Access, centrally" — "Decide who reaches which models once, not team by team."

**S6 · Platform cards**, **S7 · CTA band.**

**Tone:** CFO/CISO-oriented; control, visibility, cost; numbers shown inside the product mock. **Hierarchy:** promise + product shown immediately → video → capabilities → problem framing (late, as justification) → value → CTA.

---

### 6.6 Deployment — `/deployment`  (4,256px)

**S1 · Hero** — 604px full-bleed photo (people around whiteboard, motion blur); centred H1 2 lines + sub.
- `[H1 · 2 lines · ~8 words · role: provocative thesis]` — *Rewritten:* "Rollout decides whether enterprise AI pays off."
- `[Sub · 2 lines · ~20 words · role: offer — on-site teams, speed, handover]` — *Rewritten:* "We send engineers on site to put AI into production, show results quickly and leave your team in charge."

**S2 · Embedded teams (white)** — H2 + intro left; stat block right (big number + caption, with left divider); expandable duo (FDE photo card / DS card).
- `[H2 · 2 lines · ~4 words]` — *Rewritten:* "Teams that sit with yours"
- `[Intro · 3 lines · ~35 words]` — *Rewritten:* "Engineers and strategists work inside your environment to deliver fast and leave lasting skills behind. Think of it as a dedicated pod at your office, not a distant supplier."
- `[Stat · number "[FIGURE]+" + caption ~8 words]` — *Rewritten caption:* "local teams shipping AI in demanding settings worldwide"
- `[Card A title · ~4 words + body ~25 words]` — *Rewritten:* "Engineers | they make it run." — "They wire agents, integrations and workflows into your stack and solve data, governance and performance issues on site."
- `[Card B title · ~4 words + body ~28 words]` — *Rewritten:* "Strategists | they make it count." — "They set the use cases, KPIs and business case with you, drive adoption and draw the roadmap from the first win onward."
- Media: 2 photos (≈794×542 / 470×542, radius 8px).

**S3 · Phases (dark)** — H2 2 lines + 3 phase tabs + panel (title, progress %, body, 3 chips).
- `[H2 · 2 lines · ~8 words · role: ownership journey]` — *Rewritten:* "From our hands to yours, step by step."
- `[Phase 1 · title ~7 words · % · body ~20 words · 3 chips]` — *Rewritten:* "Ship the right first use case quickly." · 75% · "We start from your data, pick what's worth building and get it live so value is proven before scaling." · chips "Scoping · Workshops · Pilots"
- `[Phase 2]` — "Build together, then build alone." · 50% · "We co-develop with your staff and train them along the way so the skills stay when we leave." · "Co-building · Training · Enablement"
- `[Phase 3]` — "Keep it running, then take the wheel." · 25% · "We operate your use cases, hand over cleanly and size support to the risk involved." · "Support · Handover · Operations"
- *(The % = share of work led by [BRAND]; it decreases phase by phase.)*

**S4 · Deployment models (light grey)** — H2 + sub + 4 cells.
- `[H2 · 1 line · 2 words]` — *Rewritten:* "Run it anywhere"
- `[Sub · 2 lines · ~15 words]` — *Rewritten:* "Every hosting model covered, matched to your infrastructure and compliance rules."
- `[Cell ×4 · title 2–4 words + ~15 words]` — *Rewritten:* "Shared cloud" — "Always up to date, monitored by us, logically isolated and auto-scaling." / "Dedicated tenant" — "Your own isolated infrastructure with automatic updates and custom settings." / "Your cloud" — "Data never leaves your company; you own security, governance and upgrade timing." / "On-premises" — "Fully air-gapped, no outside dependencies, maintained on site by our engineers."

**S5 · CTA band.**

**Tone:** bold thesis-led; role names with "|" punchlines (rhythmic parallelism). **Hierarchy:** why deployment matters → who does it → how ownership transfers → where it runs → CTA.

---

### 6.7 Strategy — `/ai-transformation`  (4,188px)

**S1 · Hero** — 604px, abstract motion-blur photo (blue/black); centred 2-line statement H1 (64px).
- `[H1 · 2 lines · ~16 words · role: reframe AI as operating-model change (antithesis)]` — *Rewritten:* "AI isn't a tool you install. It reshapes the way your whole organization runs."

**S2 · Essay + principles (white, 2,440px)** — sticky-feeling left H2; right column of 4 paragraphs (17px, max 540px); divider; numbered accordion 01–05; divider; H2 + expandable duo.
- `[H2 · 2 lines · ~4 words]` — *Rewritten:* "Tomorrow's enterprise"
- `[Para 1 · ~95 words · role: history of tech adoption cycles]` — *Rewritten:* "For decades, enterprise software arrived as a project with an end date: buy, configure, launch, done. Each package handled one bounded job inside one department, and it sat comfortably within the org chart because its role was to store records and help people coordinate. Leaders learned to treat technology as a sequence of purchases, each closing a single gap. *(expand to length with your own example from [INDUSTRY])*"
- `[Para 2 · ~75 words · role: why AI breaks the pattern]` — *Rewritten:* "With AI there is no launch day to aim for. Because it carries out work rather than routing it between people, it cuts straight across departmental lines. The value shows up in what the organization turns into — which makes it a change of operating model rather than of software."
- `[Para 3 · ~45 words · role: diagnosis of the common mistake]` — *Rewritten:* "Plenty of companies are running adoption initiatives when the real task is transformation. Adoption bolts new tools onto old structures; transformation produces a company that thinks, acts and scales differently."
- `[Para 4 · ~15 words · role: bridge to principles]` — *Rewritten:* "Technology is only part of it. Five things have to go right."
- `[Accordion label · 3 words]` — *Rewritten:* "Our five principles"
- `[Principles ×5 · title 5–8 words; open body ~50 words]` — *Rewritten:* "01 Pick the right problem, then the next one" — "Sequencing is a strategic call. Choose the use case that lays foundations for the rest; speed comes from starting well, with the target operating model in view." / "02 Automate across workflows, not departments" / "03 Grow the capability in-house" / "04 Keep control and keep options open" / "05 Judge AI on output, not only savings"
- `[H2 · 2 lines · ~5 words]` — *Rewritten:* "Speeding up AI in critical organizations"
- `[Duo cards]` — "[PRODUCT]" + "One AI foundation for the whole company" / "Deployment"
- Media: photo 720×542 (dark water texture) in duo.

**S3 · CTA band.**

**Tone:** essayistic, thought-leadership; long paragraphs; antithesis ("not X, but Y") and contrasts (adoption vs transformation). **Hierarchy:** reframe → history → diagnosis → principles → offer → CTA.

---

### 6.8 Industry template — `/industries/{banking|telecommunication|healthcare|retail|utilities|insurance|airlines}`

All seven pages share one template (≈5,670px @1440; Utilities ≈ +700px for an extra case block). Section order and measurements below; per-industry rewrites follow.

**S1 · Hero** — 100vh (710px) full-bleed photo (sector scene, motion blur). Giant H1 (200px, the industry name) bottom-left at x=60; a 1px vertical white rule; sub-headline 20px to its right (≈260px wide, 4 lines).
- `[H1 · 1 line · 1 word · role: industry name as monument]`
- `[Sub · 4 lines · ~14 words · role: "where complex workflows become compliant production"]`
- Media: photo 1444×710 cover.

**S2 · Social proof** — H2 small centred + 4×2 logo tiles (210×80). Padding ~120px.
- `[H2 small · ~6 words]` — *Rewritten (shared):* "Relied on by leaders across sectors"

**S3 · Benefits (dark, gradient image top)** — full-bleed 1444×692 dark gradient photo with H2 1 line at top-left, 3 benefit columns (icon 24px, title 22px, body 14px) with vertical dividers.
- `[H2 · 1 line · ~6 words · role: "transform your [INDUSTRY] operations"]`
- `[Benefit ×3 · title 2–4 words + body ~15 words]`

**S3b · Utilities only — Case story** — full-bleed photo (glass building + sky) with H2 2 lines (~12 words) + "Watch now" white pill; bottom row: paragraph (~20 words) left + 3 count-up stats (≈56px white numbers, 14px captions) separated by 1px rules.
- *Rewritten:* H2 "See how teams like yours put AI to work." · button "Watch the story" · paragraph "How [CLIENT] runs accurate, policy-aware agents across service, staff workflows and operations." · stats "[FIGURE]% shorter calls · [FIGURE]% positive ratings · [FIGURE]% handled end to end"

**S4 · Workflows accordion (dark)** — H2 2 lines left; 4 workflow items (title 16px semibold-look + body 17px grey, dividers); image 758×700 right (radius 4px) that swaps per item.
- `[H2 · 2 lines · ~5 words]` — *Rewritten (shared):* "Automate the workflows that matter most"
- `[Item ×4 · title 2–4 words + body ~20–30 words]`

**S5 · Why us (light)** — H2 1 line (32–48px) + lead statement (3 lines, 36px grey, ~30 words) + 4 hover rows (title | 310×196 reveal image | description ~25 words).
- `[H2 · ~5 words · role: "why [INDUSTRY] chooses [BRAND]"]`
- `[Lead · 3 lines · ~30 words · role: differentiation by negation — "we don't do the shallow thing, we do end-to-end"]`
- `[Row ×4 · title 3–6 words + desc ~25 words]` — row titles follow a fixed pattern across all industries: (1) frontier AI in production, (2) one platform across the whole organization, (3) enterprise-grade & [industry-specific]-ready, (4) deployment partner, not a vendor.

**S6 · CTA band.**

**Tone (all industries):** domain vocabulary dropped in precisely (sector acronyms, core systems, regulations); every sub-headline uses the same formula; triads in benefits; "end to end" repeated as a motif. **Hierarchy:** industry identity → proof → outcomes → concrete workflows → differentiation → CTA.

#### Per-industry rewrites

**Banking**
- Sub: "Turning a bank's hardest processes into audit-proof production, from first step to last."
- H2 benefits: "Rethink banking operations with AI"
- Benefits: "Faster operations — Processes that took weeks now close in minutes." / "Growth without hiring — Back office, service and advisers all handle more, with the same headcount." / "Happier customers — Requests resolved fully, with answers in minutes instead of days."
- Workflows: "Lending & credit — Cover the whole credit journey for SME, mortgage and private loans: intake, assessment, approval and servicing, with quicker decisions and tighter control." / "Risk & compliance — Run identity checks, due diligence and transaction monitoring against policy, escalating to humans and logging everything." / "Customer service — A request verified and executed across every system involved, with people only for judgement calls." / "Payments & operations — Automate payments, reconciliation and case handling at volume, accurately and on schedule."
- Why H2: "Why banks pick [BRAND]" · Lead: "We don't bolt a chatbot onto your bank. We put complete workflows live — across every team and system involved — on one platform reused by every business line."
- Rows: "Cutting-edge AI, live today — The newest models in production before the market catches up: accurate, constantly evaluated, governed and deployed your way." / "One platform, every business line — Retail, SME, corporate and wealth plus the shared operations beneath them." / "Built for regulators — Scale, security and stability with guardrails that track policy changes and a full audit trail." / "A partner, not a supplier — Local engineers take it live, then equip your teams to build on it themselves."

**Telecom**
- Sub: "Turning an operator's toughest processes into always-on production, from first step to last."
- Benefits: "More value per subscriber — Every contact resolved in full; more customers kept and grown." / "Leaner operations — Lower cost across care, field, back office and collections on your current stack." / "Elastic capacity — Handle any peak without growing headcount."
- Workflows: "Fault resolution — Verifies, diagnoses and fixes remotely; when a visit is needed the ticket is already complete." / "Churn prevention — Risk signals become tailored retention offers on voice, chat and digital." / "Collections — Prioritises overdue accounts and agrees payment plans over voice and messaging." / "Outage alerts — Warns subscribers before they call and sends crews out with tickets pre-filled."
- Why H2: "Why operators pick [BRAND]" · Rows: frontier AI live / one platform for consumer, business and wholesale / "Carrier-grade by design" / partner not supplier.

**Healthcare**
- Sub: "Turning a provider's most complex processes into compliant production, end to end."
- Benefits: "Better patient journeys — Quicker access and requests closed, not passed around." / "Efficient operations — Lower cost to serve across scheduling, claims and admin on existing systems." / "More revenue — Fewer missed appointments, fuller calendars, the right service offered at the right time."
- Workflows: "Clinical support — Summarise records, draft notes and coordinate care, always with a clinician in control." / "Scheduling & access — Book visits, handle referrals, verify coverage and run preventive outreach." / "Quality & compliance — Monitor adherence, run QA and keep a complete audit trail." / "Corporate functions — Claims, invoice checks, procurement reviews and IT/admin requests."
- Rows: frontier AI live / "One platform across clinical, revenue and admin, connected to your [HIS] and claims systems" / "Privacy-grade and [REGULATION]-ready" / partner not supplier.

**Retail**
- Sub: "Turning a retailer's most complex processes into production across every channel and store."
- Benefits: "One joined-up operation — Online, in-store, loyalty and workforce connected with nothing lost in between." / "Revenue growth — Anonymous visitors become known, higher-spend repeat customers." / "Protected margins — Cut cost across service, returns, staffing and back office at once."
- Workflows: "Promotions & loyalty — Campaigns checked, approved and published across channels, end to end." / "Staffing & onboarding — Shifts planned and new associates trained so every store is covered." / "Orders & returns — Status, tracking, refunds and click-and-collect resolved in every channel." / "Suppliers & invoices — Invoice validation, supplier coordination and procurement checks with full traceability."
- Rows: frontier AI live / one platform across stores, e-commerce, supply and workforce / "Peak-ready, connected to [ERP], [COMMERCE PLATFORM], [CRM]" / partner not supplier.

**Utilities**
- Sub: "Turning a utility's most complex processes into dependable production, end to end."
- Benefits: "Better customer experience — From a billing question to an outage, handled fully and around the clock." / "Efficient operations — Lower cost across billing, field and contact centre." / "Ready for any surge — Outages, emergencies and seasonal peaks absorbed without extra staff."
- Workflows: "Field & emergencies — Dispatch technicians, triage leaks and incidents, monitor assets across electricity, gas and water." / "Grid & connections — Process capacity requests and new connections; flag outages in real time." / "Scheduling & access — Book visits, onboard sites, check tariff eligibility." / "Billing & collections — Invoice, collect and reconcile across cash, card and direct debit."
- Rows: frontier AI live / one platform across grid, field, billing and customers / "Always-on, [CERTIFICATION]-certified" / partner not supplier.

**Insurance**
- Sub: "Turning an insurer's most complex processes into audit-ready production, end to end."
- Benefits: "Capacity on demand — Absorb volume spikes without adding staff." / "Revenue growth — Tailored products and sharper underwriting that win and grow your book." / "Efficient operations — Lower cost and loss ratio across claims, underwriting and servicing."
- Workflows: "Sales & underwriting — Assess risk, verify identity, recommend cover and quote instantly." / "Service & retention — Answer coverage questions, update policies and renew across channels." / "Claims — Intake, triage, validation and settlement from first notice to payout." / "Risk & compliance — Spot fraud, assess liability and keep every decision audit-ready."
- Rows: frontier AI live / "One platform across [LINES OF BUSINESS], over your [CORE SYSTEM]" / "Made for regulated environments — [CERTIFICATION]s and immutable logs" / partner who knows your core systems.

**Airlines**
- Sub: "Turning an airline's most complex processes into disruption-proof production, end to end."
- Benefits: "More revenue per passenger — The right offer in every interaction; small uplifts worth [FIGURE] a year." / "Lower cost per seat — Cheaper disruption, claims and service handling, [FIGURE]% shorter handling time." / "Disruption absorbed — Irregular-operations surges handled 24/7 with no queue."
- Workflows: "Disruption & rebooking — Triage, rebook, refund and issue vouchers directly in the [PSS] as demand spikes." / "Passenger service — Authenticate by booking reference and resolve questions in [FIGURE]+ languages." / "Claims & compensation — Process complaints and [REGULATION] claims with regulator-ready records." / "Revenue & commercial — Personalised add-ons, recovered abandoned bookings, live fare monitoring."
- Rows: "Model-agnostic and open" / one platform connected to [GDS A], [GDS B] / "Built for 24/7 operations, aligned to [REGULATION]" / "Live in weeks, usage-based pricing, no lock-in".

**Media (per industry page):** hero photo 1444×710; 8 client logos; dark gradient photo 1444×692; 4 workflow photos 758×700; 4 hover images 310×196 (UI/abstract); CTA image 1444×700.

---

### 6.9 About — `/about-us`  (4,709px)

**S1 · Split hero (white)** — H1 2 lines (62px) left; sub 3 lines (14px grey) top-right; large photo 1324×800 (radius 8px) below.
- `[H1 · 2 lines · ~6 words · role: identity metaphor]` — *Rewritten:* "The force powering AI change in big companies."
- `[Sub · 3 lines · ~16 words · role: speed promise]` — *Rewritten:* "We move your most important workflows into production, company-wide, in a matter of weeks."
- Media: photo 1324×800 (silhouette against blue glass).

**S2 · Thesis (white)** — H2 + 2 paragraphs left; photo 570×561 right.
- `[H2 · 1–2 lines · ~6 words]` — *Rewritten:* "From AI promise to everyday operations"
- `[Para 1 · ~20 words]` — *Rewritten:* "AI will change how companies run — but only once it's woven into the operating model itself."
- `[Para 2 · ~35 words · role: what the company combines (triad)]` — *Rewritten:* "[BRAND] works with ambitious enterprises to speed up adoption, pairing a multi-model platform, local delivery teams and seasoned advisers to transform customer, employee and back-office work."
- Media: photo 570×561 radius 8px (engineer, hardware, motion blur).

**S3 · Culture (white)** — H2 + long paragraph (~120 words) + "See open positions" button.
- `[H2 · ~5 words]` — *Rewritten:* "Here to close the gap"
- `[Para · ~120 words · role: mission + values list]` — *Rewritten:* "We exist to help the organizations society depends on reach their full potential. That takes pace, precision and staying power. We act quickly, own outcomes and fix problems early. We bring calm expertise to every client, because our customers can't afford errors. We trust people to decide and move without waiting for sign-off, and we compete hard as one team — winning matters to us."
- `[Button · 3 words]` — *Rewritten:* "View open roles"

**S4 · Investors** — H2 + sub left; 3×2 investor logo tiles (150×80) right.
- *Rewritten:* H2 "Backed by top investors" · sub "Leading venture firms and some of the most accomplished founders and operators support us."

**S5 · Stories** — H2 + 4 article cards (image 282×238 radius 4px + 2-line title).
- *Rewritten:* H2 "News from us and about us" · cards → [ARTICLE TITLE] ×4.

**S6 · CTA band.**

**Tone:** values-driven, first person plural, short value statements. **Hierarchy:** identity → why we exist → how we work → who backs us → what we publish → CTA.

---

### 6.10 Careers — `/careers`  (6,194px)

**S1 · Split hero** — H1 1 line (64px) left; sub right (~30 words); photo 1324×800 below (radius 0).
- `[H1 · ~3 words]` — *Rewritten:* "Work at [BRAND]"
- `[Sub · 3 lines · ~30 words]` — *Rewritten:* "We take enterprises from AI intentions to measurable production results in weeks, using a repeatable delivery model designed for real-world constraints."

**S2 · Pinned statement** — 1,050px, padding 180px 60px, centred 5-line paragraph (≈48px) filled on scroll.
- `[Statement · ~40 words · role: who we hire]` — *Rewritten:* "We look for owners and builders who care more about shipping results in production than about theory, titles or comfort — people who love working on site with customers and solving hard problems all the way through."

**S3 · Global presence (black)** — centred H2 2 lines + sub + "Submit your role" button; below, a 2D canvas dotted globe (1324×910) with ~30 city/region labels.
- `[H2 · 2 lines · ~6 words · antithesis]` — *Rewritten:* "Global in reach. Local in delivery."
- `[Sub · 3 lines · ~17 words]` — *Rewritten:* "We're in key markets today and adding more, with teams based wherever we deploy."
- `[Button · 3 words]` — *Rewritten:* "Pitch your role"
- `[Labels · ~30 × city + region]` → "[CITY] / [REGION]"

**S4 · Roles** — H2 + 4 hover rows (title left, description right, image on hover).
- `[H2 · 2 words]` — *Rewritten:* "Key roles"
- `[Row ×4 · title 2–4 words + ~40 words]` — *Rewritten:* "Delivery Strategist — Hands-on problem-solvers with technical fluency: ex-operators, consultants, founders or early start-up staff, often with engineering degrees. They own deployments and are measured on client P&L." / "Field Engineer — Generalists across integrations, agents and data, or specialists such as voice architects, who design and ship agents for real business problems." / "Enterprise Sales — Consultative sellers fluent in buying processes and stakeholder dynamics; technical enough to explain the product and lead a delivery pod." / "Other roles — We're also hiring in operations and leadership as we grow worldwide."

**S5 · Apply** — "Apply here" link + email + privacy note.
- *Rewritten:* "Send your application" · "Write to [EMAIL]" · "We handle your data as described in our Candidate Privacy Notice."

**S6 · CTA band.**

**Tone:** demanding, mission-driven, slightly elitist ("high-ownership", "theory, titles or comfort" triad). **Hierarchy:** what we do → who we want → where we are → roles → how to apply.

---

### 6.11 Press — `/press`  (6,643px, dark page `#080808`)

**S1 · Title** — H1 72px white, left-aligned at x≈20 (this page uses a 20px gutter), ~200px top padding.
- `[H1 · 1 line · ~4 words · role: media coverage]` — *Rewritten:* "[BRAND] in the headlines"

**S2 · Bento grid** — 25 cards, all linking to external outlets (new tab). Rows alternate: 2 large squares (696×696) / 4 small squares (342×342), 12px gaps, radius 8px.
- Per card slots: `[Tag · 1 word · "• Article / Video / Podcast"]`, `[Outlet logo · top-right]`, `[Outlet name · 14px 70% white]`, `[Headline · 1–2 lines · ~8–14 words, often in the outlet's language]`.
- *Rewritten pattern:* tag "• Feature" · headline "[OUTLET]: how [BRAND] is changing AI in [INDUSTRY]".
- Media: 25 images (editorial photos of founders, abstract renders, outlet-branded graphics), outlet wordmarks (SVG/PNG).

**Tone:** no copy beyond the title — the outlets do the talking (borrowed authority). **Hierarchy:** biggest/most prestigious stories first in the large tiles.

---

### 6.12 Blog listing — `/blog`  (8,258px)

**S1 · Featured post** — image 823×463 (radius 8px) left at x=62; right column (x≈925): date 14px grey, H3 32px title (3 lines), excerpt 17px grey (2 lines).
- `[Date]` → "[DATE]"
- `[Featured title · 3 lines · ~14 words · role: launch announcement with promise]` — *Rewritten:* "Introducing [PRODUCT]: see every AI dollar, by team and by task"
- `[Excerpt · 2 lines · ~14 words]` — *Rewritten:* "Find out where your AI budget goes and what it delivers — then stretch it further."

**S2 · All posts** — H1 32px "All posts" + 17px sub; filter pills (6: All + 5 categories) in a `#f5f5f5` pill style (active = filled, padding 4px 12px, radius 1000px, 14px); hairline under; 3-column grid of cards (420×236 images, 30px column gap, ≈404px row pitch). ~50 posts render in one long list (no pagination observed).
- `[H1 · 2 words]` — *Rewritten:* "Latest writing"
- `[Sub · ~5 words]` — *Rewritten:* "News, launches, ideas and customer results."
- `[Filters · 6 × 1–2 words]` — *Rewritten:* "All · Product · Live deployments · Company news · Opinion · Case studies"
- `[Card title · 2 lines clamp · 4–20 words]` + `[Date]`
- Media: 16:9 cover images (abstract 3D renders, office photos, partner lockups, big-number graphics).

**Tone:** neutral index. **Hierarchy:** newest launch featured → filterable archive.

---

### 6.13 Blog article (essay) — sample `/blog-articles/the-execution-gap-no-model-can-close`  (5,023px)

**Layout:** centred single column.
1. Meta row centred: author 14px `rgba(31,31,31,.8)` · thin "|" divider 10% black · date 14px 60% grey (y≈181).
2. H1 48px centred, max 800px.
3. Dek 17px centred, max 600px.
4. Hero image 1064×598 (16:9) radius 8px (abstract illustration — overlapping circles on gradient).
5. Body: 600px column (x=422 at 1440), paragraphs Inter 17/21.76 `#393939`, **30px between paragraphs**, section subheads H4 26px display (no extra top margin beyond 30px rhythm). Sample has 22 blocks: 20 paragraphs (6–110 words) + 2 subheads.
6. "More posts": H3 32px + 3 cards (380×214 images, H4 26px, date 14px).
7. Footer.

Slots + rewrites:
- `[Author · 2 words]` → "[AUTHOR NAME]"; `[Date]` → "[DATE]"
- `[H1 · 1–2 lines · ~7 words · role: essay thesis]` — *Rewritten:* "Why better models won't close the delivery gap"
- `[Dek · 1 line · ~9 words]` — *Rewritten:* "The reason we organised [BRAND] around execution, not only software."
- `[Body paragraphs · 20 × 20–110 words]` → your essay; keep 2 H4 subheads at ~1/3 and ~4/5 of the length.

**Tone:** first-person-plural founder essay, argumentative, short one-line paragraphs used as punches between longer ones.

### 6.14 Press / news article — sample `/blog-articles/wonderful-raises-550m-series-c`  (4,617px)

Same template with: H1 3 lines (≈14 words), dek 3 lines (~25 words), **hero video** 1064×599 (poster image + `<video>`), body, then boilerplate blocks with H3 32px ("About [BRAND]", "About [INVESTOR]", "Media contact"), then "More posts".
- *Rewritten H1:* "[BRAND] secures [FIGURE] in new funding to expand its enterprise AI platform"
- *Rewritten dek:* "The investment will speed up product work and global rollout as companies move from scattered pilots to company-wide AI."
- *Boilerplate H3s:* "About [BRAND]" · "About [PARTNER]" · "Press contact"

---

### 6.15 Contact — `/contact`

**Layout:** 50/50 split, full viewport height. Left (722px): full-height dark photo (office scene, heavy blur) with header overlaid; H1 64px white 2 lines, sub 17px, contact lines 12px 70% white, privacy note pinned bottom 12px. Right (722px): white, form block from x≈843 to 1323.

- `[H1 · 2 lines · ~4 words · role: category claim]` — *Rewritten:* "AI that works for big business"
- `[Sub · 2 lines · ~13 words]` — *Rewritten:* "[BRAND] helps large organizations speed up AI adoption and reach their full potential."
- `[Contact lines ×4 · ~4 words each]` — *Rewritten:* "General: [EMAIL]" · "Press: [EMAIL]" · "Security issues: [EMAIL]" · "Bug bounty terms"
- `[Privacy note · 2 lines · ~25 words]` — *Rewritten:* "We keep and use what you submit only to answer you. See our Privacy Policy for details."
- `[Form title · 1 line · ~5 words]` — *Rewritten:* "Book time with our team"
- `[Form intro · 1 line · ~16 words]` — *Rewritten:* "Fill in the form and we'll get back to you shortly to arrange a call."
- `[Labels ×9]` — work email · first name · last name · job title · phone · company · industry (select, ~40 options) · company size (select, 4 ranges) · country (select, ~245) — keep as generic labels.
- `[Submit · 1 word]` — *Rewritten:* "Submit"

**Tone:** minimal, functional. **Hierarchy:** reassurance left, action right.

---

### 6.16 AI Safety — `/safety`  (2,573px; light footer variant)

**S1 · Hero (dark)** — 600px, black with blue binary-digit "rain" texture top; centred H1 64px + 3-line sub 17px.
- `[H1 · 2 words]` — *Rewritten:* "Responsible AI"
- `[Sub · 3 lines · ~30 words · triad of adjectives + triad of "every"]` — *Rewritten:* "Companies running on AI need to trust it. [BRAND] builds AI that is secure, answerable and open about how it works — in each market, each language and each deployment."

**S2 · Two text rows (white)** — H3 32px left (570px) / paragraph 17px right (≈516px), separated by hairlines.
- `[H3 · ~4 words]` — *Rewritten:* "Our mission and principles" · `[Para · ~70 words]` — *Rewritten:* "We think AI should widen what's possible without adding new risks. Safety is designed into how agents are built and how they're rolled out. Every interaction is recorded and traceable, every customer can see how their AI behaves, and when something goes wrong our engineers are already inside your environment to fix it."
- `[H3 · 2 words]` — *Rewritten:* "How we protect you" · `[Para · ~75 words]` — *Rewritten:* "Protections are in place before an agent goes live: injection defence, guardrails and optional automatic masking of personal data. Governed tool gateways limit what agents may do, providers keep none of your data, and an immutable log shows your team everything happening across the AI estate."

**S3 · Resources + report form (light grey)** — left: H3 + two H4 resource blocks (title + ~35-word text + arrow link 14px bold); right: white form card (radius 12px, shadow) with 4 inputs, textarea, black full-width "Send", 10px legal note.
- *Rewritten:* H3 "Useful links" · "Trust Center — Certifications, audit reports, data-residency options and how we keep up with [REGULATION]. → [TRUST URL]" · "Privacy Policy — How we collect, use and safeguard personal data and the rights you have under [REGULATION]. → [PRIVACY URL]" · form title "Report a concern" · button "Send report" · note "We use what you send only to handle your report. Submitting it creates no contract and waives no rights."

**Tone:** reassuring, compliance-forward. **Hierarchy:** principle → safeguards → resources → report channel.

---

### 6.17 Legal index — `/legal`  (1,877px)

Light page; header in dark-text mode with no language pill. H1 72px ("[BRAND] legal") at x=232 (≈980px measure), 1px divider (≈`#d9d9d9`), H2 48px "Legal policies", then 9 links (12px, `#3286f5`, 50px pitch), then CTA band and footer.
- *Rewritten:* H1 "Legal centre" · H2 "Policies and agreements" · links → your document names.

### 6.18 Legal document template — analysed on `/legal/privacy`  (14,605px)

- H2 48px title at x=232 (measure 980px) — *Rewritten:* "[BRAND] Privacy Notice"
- "Updated date:" label 16px black + date 17px grey (inline).
- 1px divider, ~110px space.
- Body: Inter 17/21.76, letter-spacing −0.51px, `#393939`, **justified**; bold inline terms (700); links `#3286f5` underlined; bulleted lists with 21px indent; no H3s — clause headings are bold paragraphs.
- Header nav text renders white-on-white at the top of legal pages (nav visually disappears until scrolled) — a bug, don't copy.

Other pages using this template (not separately analysed): `/legal/websiteterms`, `/legal/bug-bounty-terms`, `/careers/candidate_notice`, `/legal/msa`, `/legal/sla`, `/legal/dpa`, `/legal/aup`, `/legal/data-act`, `/legal/dora`.

---

## 7. Tech stack

| Layer | Finding | Evidence |
|---|---|---|
| Site builder / framework | **Framer** (React-based, SSR/static export, client hydration) | `<meta name="generator" content="Framer 0918601">`; modules from `framerusercontent.com/sites/<siteId>/script_main…`; ~40 `modulepreload` chunks; `data-framer-name` / `data-framer-appear-id` attributes; `framer/appear` inline scripts; Framer search index meta (`framer-search-index`) |
| Animation | Framer Motion (bundled), Framer "appear" effects, Framer text/word effects, scroll-linked transforms; one 2D canvas component (globe) | no GSAP/Lenis/Lottie globals; `transition: all` on 1,200 elements |
| Routing | Framer client-side page transitions; query params used for state (`?selected-industry=banking`) | URL changes on tab click |
| Localisation | **Smartcat** translation proxy (10 locales) — adds `?scLang=xx`, class `wf-lang-slot` on `<html>`, `alternate` hreflang links | scripts from `cdn.smartcat-proxy.com/…/script-v1/__translator…` |
| Fonts | **ABC Favorit Light** (custom upload, variable display face, only 300 used) · **Inter** 300/400/500 (+ Inter Display, Inter var registered) · **Fragment Mono** (diagram tags) · Ubuntu Mono, Google Sans, "Super Sans VF" registered but not loaded on Home | `document.fonts`; preconnect `fonts.gstatic.com` |
| Images | Served from `framerusercontent.com/images/<hash>.{jpg,png,svg}` with responsive `srcset` (`?scale-down-to=512 / 1024 …` widths), `sizes` per breakpoint, `loading="lazy"`, `decoding="auto"`, wrapped in `data-framer-background-image-wrapper` divs; logos mostly SVG, some PNG | DOM |
| Video | Self-hosted MP4 on **cdn.wonderful.ai** (e.g. a 16:9 hero montage); `autoplay muted loop playsinline preload="auto"`, no poster on hero; product/news videos with posters inside articles and menus | `<video>` |
| Analytics / marketing | Google Tag Manager + gtag, LinkedIn Insight (`snap.licdn.com`), Framer Events (`events.framer.com`) | scripts |
| Careers | **Comeet** careers API (`comeet.co/careers-api/api.js`) | script |
| Consent | Framer cookie-banner component (top-right card; "Cookie Settings" reopens it) | footer button |
| SEO | per-page `<title>`, meta description, Open Graph + Twitter card (image on framerusercontent), canonical, hreflang alternates, JSON-LD (`schema.org` inline block) | meta tags |
| External | Trust Center on a sub-domain (third-party trust portal) | footer link |

**Build-your-own equivalents:** Framer (fastest to replicate 1:1) · or Next.js / Astro + Tailwind + Motion + a headless CMS (Sanity/Contentful) for blog, press and case studies; Mux or Cloudflare Stream for looping MP4/HLS; next/image or Cloudinary for responsive images; a translation layer (Smartcat, Weglot, or i18n routing).

---

## 8. Decisions made autonomously

1. **Viewport sizes.** The Chrome side panel reduces the viewport by ~386px and the screen limited the window, so "1440" was measured at **1444px**, height **710px** (hero heights that use 100vh therefore read 710px — on a real 1440×900 screen they'd be 900px). Phone was measured at **407px** (narrowest possible) instead of 390px, plus 768px. Tablet at exactly 1024px.
2. **Reloaded for phone header.** Framer chooses the header variant at load; a live resize left the desktop nav overflowing, so phone checks were done after reloading the page.
3. **Copy is never quoted.** Every text slot is described by role/length and given an original rewrite with placeholders. Generic UI labels (e.g. form field names, sector names like "Lending") are kept as generic vocabulary because they are not distinctive copy. Long body paragraphs on Strategy, About and the blog essay are rewritten at the idea level and may need lengthening to fill the same slot.
4. **Depth per page type.** Full section-by-section analysis on Home, all 4 product pages, both service pages, Banking (as the industry template), About, Careers, Press, Blog, one essay article, one news article, Contact, AI Safety, Legal index and the Privacy policy (legal template). The other six industry pages were checked for structure and fully rewritten, but measured only where they differ (Utilities' extra case block). The remaining 9 legal URLs are listed as the same template without individual visits.
5. **Responsive verification scope.** Home was measured at all four widths; Banking and the mobile menu were verified on phone. Responsive notes for other pages (5.3–5.6) are inferred from the shared components and breakpoints and are flagged as such — verify the specific pages you plan to clone.
6. **Approximate values.** Values from computed styles are exact. Items marked "≈" (some icon sizes, mega-menu card widths, language-list styling, the hero appear timing ≈0.6s, ticker slide ≈0.4s, count-up duration, dot-grid cadence, hover transition lengths) were estimated from screenshots/sampling because Framer drives them in JavaScript. The word-reveal timing (0.30s/word, 0.045s stagger, 6px blur, 16px rise) and the statement fill colours were sampled frame-by-frame and are reliable.
7. **Gradients** in the CSS block are reconstructions (≈) — the site uses photographs with baked-in blur/grain rather than CSS gradients.
8. **Cookie banner.** It appeared after clicking "Cookie Settings"; I chose **Reject** (privacy-preserving) to dismiss it. No other forms were submitted; the contact form was only focused to capture its focus state.
9. **Press "sample article".** Every press card links off-site, so the press-type sample analysed is the company's own news article (funding announcement) in the blog template.
10. **Trust Center** (separate sub-domain) and external social/press links were not analysed.
11. **Display font.** ABC Favorit is commercially licensed; the CSS variables point to a placeholder `"Your Display"` with Inter Display as fallback. Licence your own display face.
12. **Bugs observed and excluded from the recommendations:** white nav text on white legal pages; right-edge text clipping in the industry accordion at ~400px; desktop header overflow if the viewport changes without reload.
