# Brief for Claude Design — Rain Garden Advisor frontend

I need designs for the **Rain Garden Advisor**, a conversational tool that helps a
homeowner design a DIY rain garden. It lives at **`jessbodie.com/raingarden`** — a
route inside my existing Next.js portfolio, styled to match my brand but with its
own lightweight header/footer.

## Read these first (source of truth)
- **`DESIGN_SPEC.md`** — the visual system: palette, typography, spacing, motion,
  and per-component specs. **This governs all color, type, and brand.**
- **`API_SAMPLES_FOR_DESIGN.md`** — real backend response shapes, 5 sample
  payloads, an advisory catalogue, and an example conversation. Design the
  data-bearing screens against these, not lorem.
- **The wireframes** — attached (see note below). **These govern layout and
  structure.** Where a wireframe shows neutral grey/placeholder styling, apply the
  palette from the spec.

**Rule when they conflict:** wireframe wins on layout/structure; spec wins on
color/type/brand.

## Wireframes — use ALL of them
Please work from **every wireframe I've provided**, not a subset — including any
error/edge states, the not-recommended and declined screens, and mobile variants.
More wireframes mean less guesswork and a more consistent result.

> Note: `DESIGN_SPEC.md` and `API_SAMPLES_FOR_DESIGN.md` were written against three
> reviewed wireframes — **landing, chat, and results**. If any *other* wireframe
> introduces structure not reflected in the spec, follow the wireframe for layout,
> keep the spec for brand, and **flag the new structure** so it can be reconciled.

## Build three core screens (responsive: mobile / tablet / desktop — spec §4.1)
1. **Landing** (spec §6.7) — hero + haiku tagline, explainer, how-it-works, About
   Me, collapsible Credits & Sources, CTAs.
2. **Chat flow** (§6.2–6.3) — title header, progress stepper, transcript, response
   input.
3. **Results** (§6.4) — depth radio-selector + "Confirm the Plan", gallons/year
   hero, plan card (edit/copy + advisories + AI summary), tabbed sortable plant
   table.

Plus **all states**: stepper states including the `declined` freeze; advisories
colored by severity; the terminal variants `plan` / `plan_not_recommended` /
`declined`; and `out_of_region` / `error`. All are illustrated in
`API_SAMPLES_FOR_DESIGN.md`.

## Deliverables
- A **token file** — SCSS variables **+** CSS custom properties (I'm staying on
  **SCSS Modules, not Tailwind**; all colors as tokens for a future dark theme).
- The three screens above, plus any additional screens your other wireframes cover.
- Component + state coverage as listed above.
- App chrome per spec §6.6 — the "Rain Garden Advisor" title header + slim footer.

## Hard constraints (spec §7)
- **Stack: SCSS Modules.** No Tailwind.
- **Coral is warning/error only.** The accent/positive color is **sage** (spec
  §2.2); "complete" states are deep sage.
- **No checkerboard / zig-zag layout**, **no decorative bag SVG**, no bright
  eco-green, no pill buttons (chat bubbles are the one softly-rounded exception).
- **Light theme only** for now — but keep colors token-based so dark mode is a
  later drop-in.
- Fonts: **Montserrat** 400 / 500 / 600 / 700 only.

## Leave alone
The plant-table column mismatch noted in spec §6.4 (Scientific Name / Drought
Tolerance vs. what the API returns) is an **open backend decision — do not resolve
it in design.** Design the table against the fields the API actually returns
(`common_name`, `height_ft`, `flower_color`, `bloom_period`, `moisture_use`).

Flag anywhere you had to invent outside the tokens or wireframes so I can approve.

---

### Handoff packet (attach all of these to the Claude Design session)
1. `DESIGN_SPEC.md`
2. `API_SAMPLES_FOR_DESIGN.md`
3. This brief (`CLAUDE_DESIGN_BRIEF.md`)
4. **All wireframes** (reviewed: landing, chat, results — plus any others you have)
