# Rain Garden Advisor — Design Spec

**Purpose.** A starting-point design brief for Claude Design (or any designer)
building the Rain Garden Advisor frontend. It ports the visual identity of Jess
Bodie Richards' portfolio site (`jessbodie.com`, Next.js) so the advisor reads as
part of the same brand — while extending that identity to the *application* UI
the portfolio never needed.

**Where it lives.** The advisor is a sub-route of the portfolio:
**`jessbodie.com/raingarden`**. Treat it as *inside* the existing Next.js site,
same domain — but per the **wireframes** it has its **own lightweight chrome**
(an app title header + a slim footer), not the portfolio's nav header and tall
footer. So:
- Assume Next.js App Router with the route at `app/raingarden/…` (or a `basePath`/
  rewrite if hosted separately and mounted at that path).
- **Header** (§6.6): an app title bar reading **"Rain Garden Advisor"** — not the
  portfolio's square-logo nav. **Footer** (§6.6): a **slim, single-row** social +
  copyright strip — not the portfolio's 27rem dark gradient footer, and **no bag
  SVG**. The wireframes govern this layout; the portfolio only supplies the brand
  tokens (color/type/motion) these are styled with.
- **Wireframe governs layout/structure; this spec governs color, type, and brand.**
  Where the wireframe shows neutral greys/placeholder styling, apply the palette in
  §2; where it shows structure (columns, order, controls), follow it.

**Styling stack: SCSS Modules (decided).** Match the portfolio — the advisor is a
route inside the same Next.js app, so it reuses `_variables.scss`, `_mixins.scss`
(`dropshadow`, `respond()`, the hover lift), and the existing `Header`. Tailwind is
**not** used here: a second styling system in one app isn't worth the marginal
authoring speed. Deliver tokens as SCSS variables **plus** CSS custom properties
(so a future dark theme is a token re-map — see §9).

**How to read the provenance tags:**
- 🟢 **Extracted** — a real value pulled verbatim from the live site's source
  (`app/styles/_variables.scss`, `_mixins.scss`, `globals.scss`, component modules).
  Treat as canonical brand. Don't change without asking Jess.
- 🟡 **Derived / extended** — proposed by me to cover app components (forms, chat,
  cards, stepper, results) that don't exist on the portfolio. Sensible defaults
  built *from* the extracted tokens; open to redesign.

---

## 1. Brand character

The portfolio's personality, distilled so the app inherits the same feel:

- **Calm, considered, a little editorial.** Deep jewel-tone purples and slate
  blues, generous whitespace, restrained type. Not a bright "eco-green" SaaS look —
  deliberately more grown-up and personal.
- **Soft depth, never flat-harsh.** Everything lifts on interaction (a 2px rise),
  casts a soft violet-tinted shadow, and transitions over 300ms. Nothing snaps.
- **Geometric accents.** Square bullets (▪), clipped diagonal shapes, growing
  bottom-border underlines on hover. Angular, not rounded-bubbly.
- **Motion is a signature, used sparingly.** The home hero animates once; body
  content fades/slides in on load. Respect `prefers-reduced-motion`.

**Applied to the advisor:** trustworthy and unhurried. A homeowner is making a
real decision about their yard. Favor clarity and reassurance over playfulness.
The accent that carries positive/primary actions and the "you're done" moment is
a **muted sage green** (§2.2) — it ties the purples to the garden subject without
tipping into a bright eco-SaaS look. **Coral is reserved for warnings and errors
only** (§2.1) — never a positive or decorative accent.

---

## 2. Color palette 🟢 (extracted)

| Token | Hex | Role on portfolio | Suggested app role |
|---|---|---|---|
| `--color-primary-dark` | `#372248` | Aubergine. Logo bg, headings, deepest text. Doubles as "black". | Headings, primary text, dark surfaces, footer |
| `--color-primary` | `#414770` | Indigo/slate. Links, heading-secondary bg, shadows. **The browser theme-color.** | Links, focus rings, primary brand fills, shadow tint |
| `--color-secondary` | `#5B85AA` | Muted steel blue. Button background, nav link text. | **Primary button / interactive fill** |
| `--color-secondary-light` | `#a9bfd3` | Pale blue. | Borders, disabled states, subtle fills, chart low-values |
| `--color-tertiary` | `#F56E48` | Coral. Accent (used sparingly). | **Reassigned: warning/error signal ONLY** (see §2.1) — not an accent |
| `--color-white` | `#eeeff5` | Lavender-tinted off-white. Text on dark, light surfaces. | App background, cards on dark, inverted text |
| `--color-white-true` | `#ffffff` | Pure white. Section backgrounds. | Card surfaces, input fields |
| `--color-black` | `#372248` | *Alias of primary-dark* — the site has no true black for text. | Body text |
| `--color-blacker` | `#0b070e` | Near-black. Deep shadows only. | Heavy shadow tint, overlays |

**Notes for the designer:**
- `#372248` is used as *both* the heading color and "black" — text is warm-dark
  purple, never `#000`.
- Selection styling 🟢: `::selection` = primary bg (`#414770`), white text.
- **Coral (`#F56E48`) is no longer an accent** — it is now reserved exclusively
  for warning/error states (§2.1). The accent/positive color is sage green (§2.2).

### 2.1 Semantic tokens 🟡 (decided)

The portfolio has no state colors. These are the app's status palette. Note the
deliberate split: **coral = something is wrong; sage = something is good.**

| Semantic | Hex | Basis | Use |
|---|---|---|---|
| Success / complete | `--color-accent-deep` `#5C7554` | deep sage (§2.2) | finished stages, "plan ready", confirmations |
| Accent / primary action | `--color-accent` `#7E9B76` | sage (§2.2) | primary CTAs, selected states, highlights |
| Warning / corrective advisory | `#F56E48` (coral) | tertiary | corrective advisories (coexist with a plan) |
| Error / blocking | `#8F3A2E` (deepened coral) | darkened tertiary, AA on white | viability blockers, not-recommended, form errors |
| Info | `#5B85AA` | secondary | neutral informational notes |
| Neutral border | `#a9bfd3` | secondary-light | dividers, input borders, disabled |

> The advisor distinguishes **corrective advisories** (coexist with a
> recommendation) from **blocking viability issues** (no plan / not recommended).
> Corrective → coral. Blocking → the deepened-coral error tone. Keep the two
> visually distinct from each other, and both clearly distinct from sage success.

### 2.2 Sage accent ramp 🟡 (new — replaces coral as the accent)

A muted, slightly grey-green that harmonizes with the cool purples/blues — not a
saturated leaf-green. Three stops so the designer can build states from one hue.
Tune the exact hex if needed, but keep it desaturated and a touch cool.

| Token | Hex | Role |
|---|---|---|
| `--color-accent-light` | `#C2D1B6` | subtle fills, selected-row background, chart low value, hover wash |
| `--color-accent` | `#7E9B76` | **the accent** — primary CTA fill, active/selected borders, links-as-action |
| `--color-accent-deep` | `#5C7554` | **complete / success** — finished stepper stages, checks, "plan ready", text on light |

**Rules:**
- **"Complete" / done states are always `--color-accent-deep`** (the selected deep
  sage), not the mid sage and never coral. This applies to the progress stepper's
  completed stages, confirmation checks, and the plan-ready moment.
- The **primary CTA** uses `--color-accent` fill with white (`#eeeff5`) text.
- Verify contrast: `#7E9B76` needs white text for AA on the button; `#5C7554`
  passes AA as small text on white — use it for success *text/icons*.

---

## 3. Typography

- **Family** 🟢: **Montserrat** (Google Fonts), loaded via `next/font`, `latin`
  subset, exposed as CSS var `--font-montserrat`. `sans-serif` fallback. This is
  the *only* typeface on the site — keep the app single-family.
- **Weights in use** 🟢: **400** (body), **500** (secondary/tertiary headings),
  **600** (primary headings), **700** (footer links, via `bolder`). `800`/`bold`
  appear only in commented-out source and are not active. Load exactly
  `weight: ['400','500','600','700']` rather than the full variable axis — smaller
  payload, identical appearance.

### 3.1 Fluid root sizing 🟢
```css
html { font-size: calc(6.5px + 0.66vw); }  /* base for rem scale */
```
Everything is `rem`-based off this fluid root, so the whole UI scales with viewport
width. Keep this behavior. (Note: this makes `1rem` ≈ 10–16px depending on width;
size components in `rem`, not `px`.)

### 3.2 Type scale 🟢 (from source)

| Role | Size | Weight | Line-height | Color |
|---|---|---|---|---|
| Heading primary | 3rem → 4rem (responsive) | 600 | 5.6–7rem | white (on dark) |
| Heading secondary | 2rem | 500 | — | white on `--color-primary` fill |
| Heading tertiary | 1.8rem (`$h3-default`) | 500 | — | `--color-primary` |
| Body | 1.25rem (`$body-default`) | 400 | normal, `word-spacing: .35rem` | `--color-primary-dark` |
| Fine print / copyright | 1rem | 400 | — | white @ 60% opacity |

**Extracted quirk:** body copy uses slightly **increased `word-spacing`**
(`.35rem`, up to `1.05rem` in the haiku block). It gives the prose an airy,
literary rhythm. Carry a gentle `word-spacing` into the advisor's explanatory
prose (the plan summary), but keep it subtle in dense UI.

### 3.3 App type roles to define 🟡
The portfolio has no small-UI type. Extend the scale downward for app chrome:
labels (~1.1rem, 500), input text (~1.25rem, 400), helper/caption (~1rem),
badge/chip (~0.9rem, 500, possibly uppercase with letter-spacing to echo the
geometric feel).

---

## 4. Spacing, layout & breakpoints 🟢

**Spacing anchors** (from `_variables.scss`):
- `$left-margin: 4rem` — the dominant gutter; the site's rhythm is built on it
  and multiples of it. Use as the base spacing unit.
- `$gutter-sm: 2rem`, `$margin-scroll: 1.5rem`.
- Utility steps present: `2rem` (sm), `3–4rem` (med). 🟡 Formalize an 8-step
  scale (`0.5, 1, 1.5, 2, 3, 4, 6, 8 rem`) so app components have finer control
  than the portfolio needed.

**Widths:**
- `$grid-width: 112.5em` (max content), `$desktop-width: 75em`, big-desktop rows
  cap at 80% width, centered.
- 🟡 For the advisor, a **single-column reading/chat measure** of ~`64rem` max is
  more appropriate than the portfolio's full-bleed sections — this is a focused
  task flow, not a showcase.

**Breakpoints** 🟢 (em-based — intentionally, for accessibility/zoom):

| Name | Query | px |
|---|---|---|
| mobile | `max-width: 37.5em` | ≤600 |
| tab-port | `min-width: 37.5em` | 600+ |
| tab-land | `min-width: 56.25em` | 900+ |
| desktop | `min-width: 75em` | 1200+ |
| big-desktop | `min-width: 112.5em` | 1800+ |

**Z-index tiers** 🟢: header `4000`, text-over `2000`, screens `1000`. Keep app
overlays/toasts above header; modals in the `4000+` band.

### 4.1 Responsive strategy 🟡 (contemporary best practice — required)

The app **must look good on mobile, tablet, and desktop.** The portfolio's brand
tokens transfer, but build the *layout* with current responsive practice rather
than copying the portfolio's older float/`clip-path` techniques:

- **Mobile-first.** Author base styles for small screens; layer enhancements up
  with `min-width` queries. (The extracted breakpoints in §4 are the ladder.)
- **Fluid type with `clamp()`, zoom-safe.** Prefer `clamp(min, preferred, max)`
  where the preferred term mixes `rem` + `vw` (e.g. `clamp(1.1rem, 1rem + 0.5vw,
  1.5rem)`). ⚠️ The source's `font-size: calc(6.5px + .66vw)` is *pure* viewport-
  driven and can defeat browser zoom — **improve on it** by always including a
  `rem` component so text still responds to user font-size settings (WCAG 1.4.4).
- **Intrinsic layout with CSS Grid + Flexbox.** Use Grid for page/card scaffolding
  and `auto-fit`/`minmax()` for the 3-up depth-option cards so they reflow to
  1-up on mobile without hand-written breakpoints. Flexbox for one-dimensional
  rows (stepper, message meta).
- **Container queries** where a component (e.g. a plan card, the stepper) can
  appear at different widths — size it to its container, not the viewport.
- **Fluid spacing & measure.** `min()`/`max()`/`clamp()` for gutters and max
  widths; cap reading measure (~`64rem`) so prose never runs edge-to-edge on wide
  screens. Respect safe-area insets on mobile.
- **Touch targets** ≥ 44×44px; inputs ≥ 16px effective font to avoid iOS zoom-on-
  focus; comfortable tap spacing in the chat/stepper.
- **Test matrix:** 360px (small phone), 768px (tablet portrait), 1024px (tablet
  land/small laptop), 1440px (desktop). The stepper goes vertical/compact on phone;
  depth-option cards stack; chat stays single-column throughout.
- Images/media: `max-width:100%`, responsive `srcset`, lazy-load below the fold.

---

## 5. Interaction & motion signature 🟢

This is the most transferable part of the brand — reproduce it exactly.

**Hover / active on anything interactive:**
```scss
transition: transform 300ms, text-shadow 300ms; /* or `all 300ms` */
&:hover, &:focus { transform: translateY(-2px); text-shadow: 0 1px 4px rgba(#372248, .3); }
&:active { transform: translateY(1px); }
```

**Soft drop-shadow (the `dropshadow` mixin):**
```scss
box-shadow: .2rem .5rem .5rem rgba(#414770, .6);   /* violet-tinted, offset down-right */
```
A vertical variant offsets left. Shadows are **always tinted with `--color-primary`
or `--color-blacker`**, never neutral gray.

**Growing underline accent** (nav/link hover): a `border-bottom` that expands to a
thick (`2rem`) solid band of `--color-primary-dark` / `--color-white` on hover,
paired with a shadow. 🟡 For app buttons/tabs, adapt this into a subtler animated
underline or left-border accent so it doesn't overwhelm dense UI.

**Motion on load** 🟢: body content fades in (`fadeIn`), slides down (`moveDown`),
staggered by `nth-child` delays (~0.75s apart). The home hero has a one-time
emoji-sweep + name reveal.
- 🟡 In the advisor, reserve entrance motion for: new chat messages (gentle fade+rise),
  stage transitions on the progress stepper, and the final plan reveal.
- **Always** guard with `@media (prefers-reduced-motion: reduce) { animation: none; opacity: 1; }`
  — the source already does this.

---

## 6. Component specs

### 6.1 Buttons 🟢 base / 🟡 extended
Source `<button>`:
```scss
background: #5B85AA; color: #eeeff5; font-family: inherit; font-size: 1.1em;
padding: .5em; border: none; outline: none;
&:hover,&:focus,&:active { cursor: pointer; @include dropshadow; }
```
Extend 🟡:
- **Primary CTA** ("Get my plan", "Adopt this estimate"): sage `--color-accent`
  (`#7E9B76`) fill, white text — sage is the app's positive signal.
- **Secondary/default**: steel-blue `#5B85AA` (the source default).
- **Tertiary/ghost**: transparent, `--color-primary` text + border.
- **Destructive/error-adjacent** (rare): deepened coral `#8F3A2E`.
- Keep sharp or very slightly rounded corners (`≤4px`) — the brand is geometric,
  **not pill-shaped**. Add a visible `:focus-visible` ring in `--color-primary`
  (source relies on `translateY` alone, which is insufficient for a11y — improve this).

### 6.2 Chat transcript 🟡 (per **chat wireframe**)
Layout per wireframe; color per brand:
- **Advisor messages**: **left-aligned, plain text with a small leading avatar/logo
  icon — no bubble/card.** `--color-primary-dark` text on the page background. This
  is the wireframe's structure; do not wrap advisor turns in a filled bubble.
- **User messages**: **right-aligned in a rounded bubble.** The wireframe shows a
  neutral grey fill — apply a subtle brand tint instead: `--color-secondary-light`
  (`#a9bfd3`) or a faint `--color-accent-light` wash, `--color-primary-dark` text.
  (Keep it quiet; the advisor is the primary voice.)
- **Input**: a single rounded, full-width field, placeholder "Write your response",
  with a **circular send button (up-arrow) at the bottom-right inside the field.**
  Send button fill = sage `--color-accent` on hover/active (primary action).
- Transcript scrolls; the input is pinned below it. Stepper sits above (§6.3).
- Message entrance: fade + `translateY` rise, 300ms. Generous line-height and the
  brand's gentle `word-spacing` in advisor prose.
- Corners here are the one **intentional exception** to the geometric "sharp
  corners" rule — the wireframe shows rounded chat bubbles and a rounded input;
  keep them softly rounded (not full pills), consistent with the wireframe.

### 6.3 Progress stepper 🟡 (maps to `ChatResponse.stages`)
The backend emits five ordered stages, each `state ∈ not_started | in_progress |
complete`: **Address → Localized data → Site conditions → Growing conditions → Plan.**
- Per wireframe: a **horizontal top bar** spanning the content width, sitting
  directly under the header on both the chat and results screens (not on the
  landing page). Each stage = an **icon + label** in a row. Collapse to a compact/
  scrollable or vertical form on mobile (`max-width: 37.5em`).
- Icons per wireframe: `complete` = **circle with a checkmark**, filled **deep sage
  `--color-accent-deep` (`#5C7554`)**; `in_progress` = an **open/partial ring**
  (the wireframe's spinner circle) in `--color-primary` with a subtle pulse;
  `not_started` = a plain open circle in `--color-secondary-light` (`#a9bfd3`).
- **Decline path**: when `outcome: declined`, the cursor freezes on the incomplete
  site stage and Plan never fills — design a distinct "halted" treatment (muted,
  not error-red-loud) for the frozen stage.
- **Expected non-linearity — don't treat as a bug**: *Site conditions* completes on
  distance + slope alone, so it can check off while the advisor is still asking about
  soil or sun (soil isn't a completion gate). Stages are also not strictly left-to-right —
  a later stage can read `complete` while an earlier one is the `in_progress` cursor.
  Render each stage's `state` as given; don't force monotonic left-to-right fill.
- Connectors between steps: thin lines that fill in the completed color as you advance.

### 6.4 Results / plan screen 🟡 (per **results wireframe**)
The terminal screen (`status: complete`, `outcome: "plan"`). Layout, top to bottom:

**(a) Top row — two cards side by side** (stack on mobile):
- **Left: depth-option selector card**, titled *"Evaluate the options for your rain
  garden dimensions:"*. The three depth options are **radio rows** (not 3 separate
  cards), one selected at a time. Each row lays out inline: **`{depth_in}` inches ·
  `{area_sqft}` square feet · `{interior_plants}` interior plants ·
  `{perimeter_plants}` perimeter plants**, with the number emphasized (larger/
  bolder) and the unit small beside it. Selected row = sage `--color-accent`
  radio + subtle `--color-accent-light` row wash. A **"Confirm the Plan"** button
  (primary, sage) sits below the rows.
  - Selecting a depth updates the plan card's `summary` and any per-option
    advisories (each option carries its own `summary` and `advisories[]`).
- **Right: annual-gallons hero card** — *"Your rain garden will divert and filter
  this many gallons of storm water annually:"* then the big number
  **`{gallons_per_year}`** with a small "gallons/year" unit. This value is
  **depth-invariant** (same for all three options) — that's why it sits apart from
  the selector. Give the number the largest type on the screen.

**(b) "Your Rain Garden Plan" card** — the narrative + advisories:
- Header "Your Rain Garden Plan" with two icon affordances top-right: an **edit**
  icon and a **copy** icon (copy the plan to clipboard).
- A short **"First things first:"** intro, then a **bulleted advisories list** —
  square bullets (▪, `\25A0` in `--color-primary`). Render all three advisory
  sources here: top-level `results.advisories`, `results.sizing.advisories`, and
  the selected option's `options[i].advisories`. Color each by `severity`
  (§2.1): `blocking` → error tone, `corrective` → coral, `informational` →
  neutral. (See the advisory catalogue in `API_SAMPLES_FOR_DESIGN.md` §3.)
- Then the **AI-generated summary paragraph** (`options[i].summary`) — editorial
  type, airy `word-spacing`, comfortable measure. Updates with the selected depth.

**(c) "Plant Options" section**:
- Heading "Plant Options" with an **(i) info icon** (tooltip: what interior vs.
  perimeter means).
- **Tabs**: *Interior Plants* / *Perimeter Plants* (maps to `results.plants.interior`
  / `.perimeter`). Active tab = sage/`--color-accent-light`.
- A **sortable table** (per-column sort arrows) with a **copy** icon and a vertical
  scroll when long (≤15 rows/zone). See the ⚠️ column-mapping note below.

**Terminal variants** (same scaffolding):
- **`outcome: "plan_not_recommended"`** (`recommended: false`) — muted plan-card
  header; the `blocking` advisory surfaced prominently but not alarmingly. Still
  shows the depth selector + gallons.
- **`outcome: "declined"`** — **no results screen at all**; the flow stays on the
  chat screen showing the advisor's closing message, and the stepper freezes with
  Site Conditions as the in-progress cursor (§6.3 decline path).
- **Roof-estimate footnote** — when present, the `roof_estimate` advisory renders
  in the advisories list like any other `informational` note.

> #### ⚠️ Plant-table column mismatch — needs a data decision
> The wireframe's table columns are **Common Name ~ *Scientific Name*, Height,
> Color, Bloom Period, Drought Tolerance**. The API (`results.plants[*]`) currently
> returns: `common_name`, `height_ft`, `flower_color`, `bloom_period`,
> `moisture_use` — **no scientific name, and `moisture_use` is not the same as
> "drought tolerance."** So two wireframe columns have no backing data:
> - **Scientific Name** — not exposed by `filter_plants`. Either add it to the API
>   (`tools.py` `_PLANT_COLUMNS`) or drop the column.
> - **Drought Tolerance** — the API has `moisture_use` (a plant's moisture *need*,
>   used to sort interior vs. perimeter). Either relabel the column **"Moisture
>   Use"** (recommended — it's the real field) or add a true drought-tolerance
>   field to the data. Straight mappings: Height→`height_ft`, Color→`flower_color`,
>   Bloom Period→`bloom_period`.
> **This is a backend/spec reconciliation for Jess, not a Design call.** Flagged in
> `API_SAMPLES_FOR_DESIGN.md` too.

### 6.5 Forms / inputs 🟡
White (`--color-white-true`) fields, `--color-secondary-light` border, focus
border → `--color-primary` + soft glow. Labels in 500 weight above the field.
Sharp/near-sharp corners. Address input is the first thing a user sees — make it
prominent and inviting.

### 6.6 Header / footer 🟡 (per **wireframes** — app-specific, not the portfolio's)
- **Header**: a **title bar reading "Rain Garden Advisor"** — large, bold, left-
  aligned, on a light bar spanning full width, persistent across app screens. The
  wireframe shows near-black on light grey; apply brand color: `--color-primary-dark`
  title on `--color-white` (`#eeeff5`), with the source's soft bottom shadow. This
  **replaces** the portfolio's square-logo nav for the advisor. (If the global site
  nav must also appear above it, that's Jess's call — default is this title bar only.)
- **Footer**: a **slim, single-row strip**, left-aligned: social icons (GitHub,
  LinkedIn, Instagram) then **"© 2026 Jess Bodie Richards. All rights reserved."**
  On the page background (light), not the portfolio's tall dark gradient footer, and
  **no bag SVG**. Icons get the brand hover lift (§5); copyright in fine-print type.
  Consistent across all three screens.

### 6.7 Landing page 🟡 (per **landing wireframe** — new)
The marketing/intro screen at `/raingarden`, before the chat flow. No stepper here.
Top to bottom:
- **Hero**: a **three-line haiku-style tagline** over a background image (the
  wireframe's grey block = a photo, styled like the portfolio's hero):
  *"A flood is made from millions of drops adding up / Flood mitigation is built one
  garden at a time. / Give the rain somewhere to go."* This directly echoes the
  portfolio's **haiku aesthetic** (staggered lines, the `moveDown`/`fadeIn` reveal,
  reduced-motion guard). A primary **"Plan my rain garden"** CTA (sage) sits within
  the hero and routes into the chat flow.
- **"What is a rain garden" explainer** — a soft-surfaced card: a short intro line
  then a bulleted list ("Soak, don't flood", "Filter the bad stuff", "Habitat, too")
  and a closing "small effort, real math" line. Square bullets per brand.
- **"How it works"** — a numbered 1‑2‑3 list (Enter your address → Answer a few
  questions → Get your plan), a "About ten minutes, start to finish." line, and an
  audience/encouragement paragraph.
- **Second "Plan my rain garden" CTA** (sage) — repeat entry point after the pitch.
- **"About Me"** — a portrait image (grey placeholder in the wireframe) beside a
  short bio with an Instagram link (`@sustainable.urban.gardening`). Bio copy is
  placeholder; treat the layout as canonical.
- **"> Credits & Sources"** — a **collapsible/disclosure** section (the "›" is a
  twisty). This is the home for the RAG guidance citations + data-source
  attributions (the `search_guidance` sources are retained server-side for exactly
  this; see the project's RAG notes). Collapsed by default.
- **Footer** (§6.6) closes the page.

Layout is a single centered column (respect §7's no-checkerboard rule). Hero and
About-Me imagery use the brand's soft `dropshadow`/overlay treatment.

---

## 7. Anti-patterns — do NOT do these

Explicit exclusions from Jess, and brand guardrails:

- **No checkerboard / alternating zig-zag layout.** The portfolio's Projects page
  ("Professional Highlights") alternates image-left / image-right in a checkerboard
  rhythm. **Do not reproduce that pattern anywhere in the advisor.** Keep the
  advisor's content in a clean, predominantly single-column, top-to-bottom flow.
- **No decorative bag SVG** (or any of the portfolio's decorative background
  illustrations) in the footer or elsewhere. The advisor's surfaces stay clean.
- **No coral as accent/positive.** Coral is warning/error only (§2.1). Positive =
  sage (§2.2).
- **No bright/saturated eco-green.** The garden nod is a *muted* sage, kept cool
  to sit with the purples.
- **No pill-shaped buttons / heavily rounded cards.** The brand is geometric;
  corners are sharp to ≤4px. *Exception:* the chat bubbles + response input are
  softly rounded per the wireframe (§6.2) — softly, not full pills.
- **Don't copy the portfolio's float + `clip-path` layout mechanics** — use modern
  Grid/Flexbox per §4.1.
- **Don't let hover-only affordances stand in for focus states** — always add
  `:focus-visible` (§8).

---

## 8. Accessibility notes

- 🟢 Em-based breakpoints and `rem` sizing already support zoom well — preserve.
- 🟢 `prefers-reduced-motion` is already honored — keep for every animation.
- 🟡 **Improve on the source**: hover states rely on `translateY` + text-shadow,
  which don't help keyboard or low-vision users. Add explicit `:focus-visible`
  rings (`--color-primary`, ≥2px) on all interactive elements.
- 🟡 **Verify contrast**: coral `#F56E48` on white is ~AA for large text only —
  use the deepened `#8f3a2e` for small error text. `#a9bfd3` is decorative, not a
  text color on white.

---

## 9. Theming (dark mode) — deferred 🟡

**Build light theme only for now. Do not spend time on dark mode.** The site's
default is light and that is the shippable target.

*Just* keep the architecture theme-able so a dark theme is a later drop-in, at no
extra cost now: express all colors as **CSS custom properties / semantic tokens**
(never hard-coded hex in components), so a future `:root[data-theme="dark"]` /
`prefers-color-scheme` layer only needs to re-map token values. If dark mode is
ever built, invert onto the `--color-primary-dark` aubergine surface, not neutral
gray. No dark-theme deliverables are expected in this pass.

---

## 10. Deliverable checklist for Claude Design

Please produce, staying inside the tokens above and following the **three
wireframes** (landing, chat, results) for layout — spec for color/type/brand:
1. A **token file** — SCSS variables **+** CSS custom properties (see stack
   decision + §9) seeding the 🟢 palette, the 🟡 sage ramp (§2.2) and semantic
   tokens (§2.1), Montserrat (400/500/600/700), spacing scale, breakpoints, shadow
   + motion primitives. **All colors as tokens.**
2. **Three full screens** at mobile / tablet / desktop (§4.1):
   - **Landing** (§6.7) — hero + haiku tagline, explainer, how-it-works, About Me,
     Credits & Sources, CTAs.
   - **Chat flow** (§6.2 + §6.3) — title header, stepper, transcript, response input.
   - **Results** (§6.4) — depth radio-selector + Confirm, gallons hero, plan card
     (edit/copy + advisories + AI summary), tabbed sortable plant table.
3. **Component + state coverage**: progress stepper (all states incl. `declined`
   freeze), advisory list by `severity`, buttons, forms/inputs, the terminal
   variants (`plan` / `plan_not_recommended` / `declined`), plus `out_of_region`
   and `error` states (see `API_SAMPLES_FOR_DESIGN.md`).
4. **App chrome** per §6.6 — the "Rain Garden Advisor" title header + slim footer.
5. Light theme only (§9).
6. Flag anywhere you invented outside the tokens/wireframes. **Do not resolve the
   plant-table column mismatch (§6.4 ⚠️) in design — it's a backend decision.**

---

### Source of truth
Extracted from `~/projects/PersonalWebsiteNext/jbr-website-next`:
`app/styles/_variables.scss`, `app/styles/_mixins.scss`, `app/globals.scss`,
`app/layout.tsx`, and the `Header`/`Footer`/`page` `.module.scss` files.
Tags: 🟢 extracted verbatim · 🟡 derived extension for app UI.
