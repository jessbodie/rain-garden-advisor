# Rain Garden Advisor — Frontend Integration Guide

How to wire the Next.js frontend to the real backend. This is the **build-time
companion** to the design handoff and the other docs:

- **`DESIGN_SPEC.md`** — color/type/brand system + component specs.
- **`API_SAMPLES_FOR_DESIGN.md`** — the **response payloads** and field→purpose
  table. *This doc does not repeat those; it references them.*
- **Design export** (`design/…/design_handoff_rain_garden_advisor/`) — the visual
  prototype (`Rain Garden Advisor.dc.html`), `tokens.scss`, screenshots, assets.
- **This doc** — the request lifecycle, transport rules, types, and the
  design-state → API-condition mapping that the prototype fakes.

> ⚠️ **The prototype stubs the backend.** `Rain Garden Advisor.dc.html` hardcodes a
> `DATA` object and scripts the chat. The **results schema it uses is accurate**
> (built from `API_SAMPLES`), but the **chat transport is entirely faked** — that
> transport is the core of what you must build for real, and it's what this doc
> specifies.

---

## 1. Architecture at a glance

- **Backend**: FastAPI, one primary endpoint `POST /chat` + `POST /warmup`.
  Deployed at `https://rain-garden-advisor-api.onrender.com`.
- **Client-stateless transport**: there is **no session on the server**. The
  browser holds the entire `messages` transcript and **resends it every turn**;
  the server runs one agent pass per request and returns the updated transcript.
  This is the single most important thing to get right (§4).
- **Routing = hybrid** (decided):
  - **Landing** = a real, server-rendered route at **`/raingarden`** — indexable,
    shareable, good for SEO *and* AI-answer discoverability (§7).
  - **Address → Chat → Results** = **client state** within the app. The transcript
    lives only in browser memory (a refresh loses it — see §4.5), so per-screen
    URLs would be illusory there anyway.

---

## 2. Environment & configuration

- **API base URL** → env var, e.g. `NEXT_PUBLIC_API_BASE_URL`. Do **not** hardcode
  the Render URL in components (it will change for local/staging).
  - Local dev typically points at `http://localhost:8000`.
- **basePath**: the app is mounted at `/raingarden` under `jessbodie.com`. Set
  Next.js `basePath: '/raingarden'` (or a rewrite) so asset/link paths resolve.
- **CORS**: **env-driven** (`app.py`). The backend reads `ALLOWED_ORIGINS`
  (comma-separated), defaulting to `https://jessbodie.com` when unset; methods
  `POST`, header `Content-Type`, no credentials. **To develop locally / on previews:**
  set the origins in that environment, e.g.
  `ALLOWED_ORIGINS=http://localhost:3000,https://jessbodie.com` — no code change
  needed. (Unset = production-only.)
- **Fonts**: Montserrat via `next/font/google`, weights `['400','500','600','700']`
  only (see `tokens.scss`).
- **Tokens**: import `tokens.scss` (SCSS vars + `:root` custom properties) as-is.
  Components read `var(--…)`, never hardcoded hex (keeps a dark theme a drop-in).
- **Assets**: copy the export's `uploads/` (logo SVG, real photography, portrait)
  into `public/`. All photography is final, not placeholder.

---

## 3. Endpoints

### `POST /warmup`
Call **once on app load** (fire-and-forget). It preloads the backend's RAG
singletons so the first real plan doesn't eat model-load latency. Any request wakes
the Render container, so don't *gate* anything on it — just fire it early.
```
POST /warmup  →  { "status": "warm" }
```

### `POST /chat`
The whole conversation. Two request shapes, discriminated by whether you already
have a transcript:

**Seed (first turn)** — send only the address:
```json
{ "address": "1600 Grandview Ave, Columbus, OH 43212" }
```
**Continue (every later turn)** — send the transcript you got back last turn, the
user's new answer, and the echoed roof value:
```json
{
  "messages": [ /* the exact array from the previous response */ ],
  "user_message": "About 600 square feet.",
  "roof_sqft": 1740
}
```

The response shape (`ChatResponse`) and its field→purpose table live in
`API_SAMPLES_FOR_DESIGN.md` §1, with five full sample payloads in §2. Types in §5
below.

---

## 4. The client-stateless transport (read this twice)

### 4.1 The core loop
1. **On load**: fire `POST /warmup`. Show the **Address** screen.
2. **Address submit**: `POST /chat` with `{ address }` (seed). No `messages` yet.
3. **Every response** carries an updated `messages` array. **Store it verbatim.**
   Also store `roof_sqft` when present.
4. **Each user reply**: `POST /chat` with `{ messages, user_message, roof_sqft }`
   (continue) — `messages` = the array from step 3, unchanged.
5. Repeat until `status === "complete"`.

### 4.2 `messages` is opaque — hold, don't parse, don't render
`messages` is the raw Anthropic transcript (tool_use / tool_result blocks). It is
**transport state, not UI**. Rules:
- Store it exactly as received; send it back exactly as received.
- **Never render it.** Build the visible chat log from your own running list of
  user inputs + each response's **`assistant_message`** (the advisor's turn).
- Never edit it, reorder it, or construct it yourself.

### 4.3 The visible transcript vs. the wire transcript
Keep **two** things in state:
- `wireMessages` — the opaque `messages` array (for transport).
- `chatLog` — your rendered list of `{ role: 'advisor' | 'user', text }`, appended
  to locally: push the user's text when they send; push `assistant_message` when a
  response returns. (This is what the design's "chat transcript" state describes.)

### 4.4 The `roof_sqft` round-trip
- Returned on the **seed** response (the satellite roof estimate, or `null`).
- **Echo it back on every continue** request. It is deliberately kept **out of**
  `messages` (the raw number is redacted from the model's context).
- You don't display it directly — the server substitutes it into the advisor's
  catchment question, so it already appears inside `assistant_message`.
- **Adopting the estimate** is conversational: if the user says "use that
  estimate," the model handles it server-side. No special frontend field needed.

### 4.5 Refresh = conversation lost (by design)
Because state lives only in the browser, a refresh mid-flow loses the transcript.
That's acceptable (and the reason the flow screens are client-state, not routes).
**Optional hardening:** persist `wireMessages` + `chatLog` + `roof_sqft` to
`sessionStorage` to survive an accidental refresh. Not required for v1.

---

## 5. TypeScript types

```ts
// ---- Transport ----
type Stage = {
  id: 'address' | 'localized_data' | 'site_conditions' | 'growing_conditions' | 'plan';
  label: string;
  state: 'not_started' | 'in_progress' | 'complete';
};

type Severity = 'blocking' | 'corrective' | 'informational';

type Advisory = {
  type: string;                 // e.g. 'foundation_setback', 'utilities' (see API_SAMPLES §3)
  severity: Severity;           // drives color; see DESIGN_SPEC §2.1
  message: string;
  corrective_action?: string;   // present only on viability advisories; ignore for display
};

type Plant = {
  common_name: string;
  height_ft: number;
  flower_color: string;
  bloom_period: string;
  moisture_use: string;         // NOTE: this is "Moisture Use", not "Drought Tolerance"
};

type DepthOption = {
  depth_in: number;             // 4 | 6 | 8
  band: string;                 // '3-5' | '6-7' | '8' (not displayed)
  area_sqft: number;
  interior_plants: number;
  perimeter_plants: number;
  advisories: Advisory[];       // depth-DEPENDENT advisories for this option
  summary: string;              // per-option prose (already numerically injected)
};

type Results = {
  recommended: boolean;                                   // false → not-recommended layout
  sizing: { options: DepthOption[]; advisories: Advisory[] }; // sizing.advisories = depth-invariant
  advisories: Advisory[];                                 // site-wide advisories
  gallons_per_year: number | null;                        // depth-invariant; format with commas
  plants?: { interior: Plant[]; perimeter: Plant[]; reason?: string }; // may be empty → "no plants" state
};

type ChatStatus =
  | 'awaiting_user' | 'complete' | 'address_not_found' | 'out_of_region' | 'error';
type Outcome = 'plan' | 'plan_not_recommended' | 'declined' | null;

type ChatResponse = {
  status: ChatStatus;
  outcome: Outcome;             // set only when status === 'complete'
  messages: unknown[];          // OPAQUE — hold & resend, never render (§4.2)
  assistant_message: string | null;
  results: Results | null;
  detail: string | null;        // error / out-of-region text
  roof_sqft: number | null;     // echo back every continue (§4.4)
  stages: Stage[] | null;       // the 5-stage stepper
};

// ---- Request ----
type ChatRequest =
  | { address: string }                                                       // seed
  | { messages: unknown[]; user_message: string; roof_sqft: number | null };  // continue
```

---

## 6. What each response field drives

(Condensed; full table in `API_SAMPLES` §1.)

| Field | Drives |
|---|---|
| `stages` | The progress stepper (always render it) |
| `status` | `awaiting_user` → show chat input · `complete` → terminal screen · `out_of_region` → stay on Address w/ error · `error` → chat error state |
| `outcome` | Which terminal screen: `plan` → results · `plan_not_recommended` → results w/ "Not recommended" · `declined` → chat closing message, no results |
| `assistant_message` | The next advisor bubble |
| `results` | The whole results screen (§5 `Results`) |
| `roof_sqft` | Echo back each turn; already baked into `assistant_message` |
| `detail` | Error / out-of-region copy (but prefer design copy — §7) |

---

## 7. Design-state → API-condition mapping

Every UI state in the design README, and the API condition that produces it:

| Design state (screenshot) | API condition |
|---|---|
| Address — default (`02`) | Initial Address screen; no request yet |
| Address — **invalid** (`03`) | Seed response **`status: "address_not_found"`**, `detail` = *"I couldn't find that address…"* (geocode failed) |
| Address — **outside US** (`04`) | Seed response **`status: "out_of_region"`**, `detail` = *"…contiguous lower-48…"* (geocoded, state ∉ lower-48) |
| Chat — first message (`05`) | Seed response `status: "awaiting_user"`, first `assistant_message` |
| Chat — transcript (`06`) | Successive `awaiting_user` responses |
| Chat — pending (`07`) | **Frontend-only**: the in-flight `POST /chat` before it resolves. "percolating…" is UI copy, not from the API |
| Chat — error (`08`) | `status: "error"` (HTTP 500) — offer retry (re-send the same continue request) |
| Chat — declined (`09`) | `status: "complete"`, `outcome: "declined"`, `results: null` — show `assistant_message`, freeze stepper, offer restart |
| Results — pick depth (`10`) | `status: "complete"`, `outcome: "plan"`, `results.recommended: true` |
| Results — confirmed (`11`) | Same payload; **frontend** locks the selected `DepthOption` to read-only |
| Results — **no plants** (`12`) | `results.plants.interior` **and** `.perimeter` empty (a `reason` may be present) |
| Results — **not recommended** (`13`) | `status: "complete"`, `outcome: "plan_not_recommended"` (`results.recommended: false`); a `blocking` advisory in `results.advisories` |

**Invalid vs. outside-US (resolved 2026-07-14):** the two cases now carry **distinct
statuses** — `address_not_found` (geocode miss) vs `out_of_region` (resolved but
outside the lower-48). Key your two Address error screens off `status`; don't
string-match `detail`. Both share the same stepper shape (Address = in_progress). The
design has its own copy for each screen; use it, keyed off `status`.

---

## 8. Recommended backend changes (small)

1. ✅ **DONE (2026-07-14) — CORS env-driven.** `app.py` reads `ALLOWED_ORIGINS`
   (comma-separated), default `https://jessbodie.com`. *Action:* set it in each
   environment (local `.env`, Render prod, previews) — see §2.
2. ✅ **DONE (2026-07-14) — distinct address-error status.** Geocode miss →
   `status: "address_not_found"`; outside-48 → `status: "out_of_region"` (§7).
3. *(Optional, not done)* If you want **Scientific Name** in the plant table, add
   `scientific_name` to `tools.py` `_PLANT_COLUMNS` (the design dropped that column
   and kept `moisture_use`). Tracked in `TODO.md`.

---

## 9. Prototype `DATA` → real API mapping

The prototype's local field names differ from the real payload. Straight remaps:

| Prototype `DATA` | Real `ChatResponse` |
|---|---|
| `gallons` | `results.gallons_per_year` (format with thousands separators) |
| `options[]` | `results.sizing.options[]` |
| `siteAdvisories` | `results.advisories` |
| `sizingAdvisories` | `results.sizing.advisories` |
| `options[i].advisories` | same (per-option, depth-dependent) |
| `plants.interior/perimeter` | `results.plants.interior/perimeter` |

Notes:
- Prototype advisory objects are `{severity, message}`; **real ones also carry
  `type`** (and viability ones `corrective_action`). Use `severity` for color;
  `type` is available if you want per-type icons.
- Prototype omits `band` on options — fine, it isn't displayed.
- The roof caveat advisory is **appended server-side** into `results.advisories`
  when an estimate was offered — you don't add it; just render what's there.
- The two prototype datasets ("happy path" / "not recommended") correspond to
  `outcome: "plan"` vs `outcome: "plan_not_recommended"`.

The **results schema is otherwise faithful** — the meaningful build work is the
chat transport (§4), which the prototype does not model at all.

---

## 10. Discoverability (landing page)

The hybrid routing exists partly for this. For the landing route (`/raingarden`):
- **Server-render it** (SSG/SSR) so it's crawlable by Google *and* by AI answer
  engines' live search (ChatGPT-search, Perplexity, Claude-with-search).
- Add `generateMetadata` (title, description, Open Graph).
- Add **JSON-LD structured data** (e.g. `WebApplication` and/or `HowTo`) describing
  what the tool does and the 3-step flow.
- Don't block AI crawlers in `robots.txt` if you want to be cited: `GPTBot`,
  `ClaudeBot`, `PerplexityBot`, `Google-Extended`.
- Interior flow screens stay client-rendered — they're personalized and shouldn't
  be indexed.

---

## 11. Open items (not blockers)

- **Placeholder copy** — the **About Me bio** and **Credits & Sources** list are
  PLACEHOLDER in the design. Jess will supply final copy **after** the frontend is
  coded (Credits & Sources is the home for RAG source citations). Do not invent it.
- **Backend tweaks §8** (CORS, address discriminator) — coordinate with Jess.
- **Refresh persistence §4.5** — optional `sessionStorage` hardening.

### Source of truth
Backend: `app.py` (`ChatRequest`/`ChatResponse`, `/chat`, `/warmup`, `_stages`,
CORS), `tools.py` (`geocode_and_gate`, tool outputs), `agent.py`
(`run_agent(messages, client, roof_sqft) -> (messages, status, call_log)`).
Design: the export README + `Rain Garden Advisor.dc.html` `DATA` object.
