# Rain Garden Advisor — Project Context

Read this file at the start of every session. Also read TODO.md before
starting any new module.

---

## What this project is

An AI-powered advisor that helps DIY gardeners design a rain garden. It wraps
a deterministic calculation engine (ported from an existing Python/Hex notebook)
in a conversational AI layer. The AI gathers site details in natural language,
calls calculation tools, and explains results.

**The AI does not perform the math itself.** The LLM orchestrates tools;
the tools do the calculation.

---

## Architecture decisions (do not relitigate without asking)

**Python backend, API-first.**
All calculation logic stays in Python. It was written in Python; keep it there.
Do NOT port any calculation logic to JavaScript.

**Deterministic core — six clean modules, each independently testable:**
- `src/rain_garden/sizing.py` — garden area (soil × depth-band factor), dimensions,
  plant counts ✅ (depth is a user tradeoff across three options, not area-derived —
  see the depth-options note below)
- `src/rain_garden/precipitation.py` — three weather scalars from Open-Meteo ✅
- `src/rain_garden/geocode.py` — address → lat/lon via Nominatim ✅
- `src/rain_garden/hardiness.py` — USDA hardiness zone via RapidAPI ✅
- `src/rain_garden/plants.py` — structured plant filter from CSV ✅
- `src/rain_garden/roofarea.py` — roof footprint (sq ft) via Google Solar API ✅
  (resolved at seed time, NOT a dispatched tool — see the roof-estimate note below)

**Tool layer (`tools.py`) wraps the five modules as agent-callable tools.** It owns the
deterministic site advisories (not the LLM). `size_garden` takes two *separate* slope inputs:
`slope_ok` (grade/steepness, ≤12%; false → blocking advisory) and `slopes_away_from_house`
(direction; false → a *corrective* advisory to build an overflow outlet away from the foundation —
does not block, `recommended` stays true). Omitting a slope input fires no advisory. ✅

**Depth-options sizing (`size_garden` output shape).** ✅ `area = catchment ×
factor(soil, depth_band)` from the single soil×depth-band table
(`sizing.SIZE_FACTORS_BY_DEPTH`, transcribed from `data/RainGarden-SizeFactors.csv`),
applied universally. Distance no longer feeds area (advisory-only setback). `size_garden`
returns `{recommended, sizing:{options[], advisories[]}, advisories[], gallons_per_year}`:
- `sizing.options[]` — **exactly three**, about 4"/6"/8" (bands 3-5"/6-7"/8"). Each:
  `depth_in, band, area_sqft, interior_plants, perimeter_plants, summary` (per-option,
  token-injected — see below), and `advisories[]` (depth-*dependent*: the 300 sq ft
  split-ceiling; the two-zone floor, gated on the **unrounded** interior count → single-zone
  perimeter planting). Deeper = smaller factor = more compact. Unknown soil → Clayey column.
- `sizing.advisories[]` — depth-*invariant* sizing advisory: only the 30%-reduction
  allowance, and only when a ceiling fired and no floor did.
- top-level `advisories[]` — the merged site advisories. The three **viability blockers**
  (`foundation_setback`, `slope`, `low_drainage`) plus the soft `clayey_unverified` note now
  come from `check_viability` (see below); the depth-invariant site notes (`utilities`,
  `unknown_soil`, `slope_toward_house`, `rate_unparsed`) come from `_advisories`.
  `gallons_per_year` is depth-invariant.
- The old single-`design` shape, the distance/rate factor tables, `recommended_depth`, and
  the `contingent` flag are retired.

**Early viability checks (`check_viability`) — the producer of the three blockers.** ✅
`check_viability(distance, slope_ok, perc_rate, soil_type)` is the single deterministic
home for the three input-level blockers — `foundation_setback` (distance `"Less than 10 ft"`),
`slope` (`slope_ok is False`), `low_drainage` (a *measured* rate on the open interval
`0 < rate < 0.5`; `0.0` and `0.5` both pass) — plus the soft, non-blocking `clayey_unverified`
note (Clayey soil AND no measured rate; a measured rate governs and suppresses it). It is
stateless and None-tolerant so the model can call it incrementally as slots fill (the
`check_viability` **tool**), well before sizing; `size_garden` also calls it internally with
the full input set (DRY — one place derives `recommended = not any severity == "blocking"`).
It takes NO sizing inputs and computes nothing about size. An invalid `distance` enum raises
`ValueError` (the tool path converts that to a recoverable error). Reconciliation with the
existing advisory schema (spec §11, "align, don't fork"): the code rides the existing `type`
field (not `code`), `corrective_action` is an additive field on viability advisories only, and
`clayey_unverified` uses the existing non-blocking severity `"corrective"` (not a new
`"advisory"` value). Only `severity == "blocking"` gates not-recommended — a corrective
advisory (clayey, or `slope_toward_house`) coexists with `recommended: true`.

**LLM layer sits on top of the completed deterministic core.**
- `agent.py` — the agent loop over the Anthropic Messages API. ✅
  `run_agent(messages, client=None) -> (messages, status, call_log)` is a
  messages-based loop: `status` ∈ `awaiting_user` | `complete` | `error`, and
  `call_log` records every tool call `{name, input, output}`. Assistant turns
  are serialized to plain dicts (`model_dump(exclude_none=True)`) so the
  transcript round-trips through JSON — a hard dependency of the client-stateless
  transport, not a convenience (`exclude_none` drops citations/cache_control the
  API rejects inbound). `last_assistant_text` therefore reads `b["text"]` on
  dicts, not block attributes.
- **Completion contract:** there are TWO terminal control signals, both intercepted
  before dispatch, recorded in `call_log` (`output=None`; the payload rides in the
  input), returning `status="complete"`, and never routed through `dispatch`:
  `present_results` (ends WITH a plan; summary in its input) and `conclude_without_plan`
  (the decline path — ends with NO plan; the unresolved blocker rides as `reason`, spec
  §7.5 State B). The HTTP layer reads `call_log` to tell the two terminals apart.
- **Terminal `outcome` discriminator (`app.py`, spec §9).** `ChatResponse.outcome` is set
  only on a `complete` turn, keyed off `call_log` (never a transcript scan — the whole
  reason `conclude_without_plan` is a tool, §10-D): `"declined"` when the decline signal
  fired (`results` is `None` — a completion turn with no plan object); otherwise `"plan"` if
  `recommended`, else `"plan_not_recommended"` (State A: the user overrode a blocker; the
  plan returns with `recommended: false` and the blocker kept in `advisories`). The
  not-recommended layout is gated on `recommended`, NOT on any corrective severity.
- **Progress stepper (`ChatResponse.stages`, `app.py`).** ✅ Five ordered UI stages —
  `address`, `localized_data`, `site_conditions`, `growing_conditions`, `plan` — each
  `{id, label, state}` with `state ∈ not_started|in_progress|complete`, returned on
  **every** `/chat` path (`_stages`). Derived from the transcript's tool calls
  (`_called_tools` — a structured `tool_use`-name scan, not prose; cumulative because the
  transcript *is* the state), NOT from `call_log` (which is per-turn). Two layers:
  order-free per-stage `complete` flags + a single in-progress cursor placed by
  status/outcome. Stage→signal: address = geocode preamble present; localized_data =
  `get_precipitation_stats` + `get_hardiness_zone` (the seed-resolved roof estimate is
  reference-only, not gating); site_conditions = `size_garden` fired OR viability cleared
  early (latest `check_viability` inputs have distance+slope AND
  `check_viability(**inputs).recommended` — reuses the real tool, DRY; a **blocker** keeps
  it incomplete, a **corrective** note like clayey-unverified does not); growing_conditions
  = `filter_plants`; plan = `present_results`. A produced plan (recommended OR overridden)
  fills the whole bar; a **decline** (`conclude_without_plan` → `outcome: declined`) freezes
  the cursor at the incomplete site stage and Plan never completes. The site gate is
  **distance + slope only** (not soil): a live run showed the model reliably re-calls
  `check_viability` for the two blocker slots but skips it for benign soil, so requiring
  soil stalls the cursor until the finale. Soil is still *passed* to `check_viability` when
  known (so a measured low-drainage blocker still counts) and still categorized under Site
  Conditions for the user — it just isn't a completion gate. Growing Conditions' slots
  (sun/moisture) reach only `filter_plants`, so that stage has no incremental signal
  (binary). This resolves the §10-E tracker mapping (see TODO.md). Stages are decoupled from the frontend's
  results-screen depth toggle, which is downstream of the terminal turn.
- `app.py` — FastAPI `POST /chat`, **client-stateless**. ✅ The `messages`
  transcript *is* the conversation state: the browser holds it and resends it
  each turn; the server runs one `run_agent` pass per request. No session store.
  Seed vs. continue is discriminated by `LOCATION_PREAMBLE_MARKER` in `messages`,
  so geocoding runs exactly once per conversation.
- `prompts.py` — `SYSTEM_PROMPT`, passed verbatim as the API `system` parameter.

**Deployment: Render + CORS + `/warmup`.** ✅ The API is deployed on Render at
`https://rain-garden-advisor-api.onrender.com`; the browser frontend (`jessbodie.com`,
served from Vercel) calls it cross-origin. `app.py` adds `CORSMiddleware` scoped to the
`https://jessbodie.com` origin only (no `"*"`, no credentials — production-only; Vercel
preview subdomains are deliberately excluded for now). `POST /warmup` forces the RAG lazy
singletons (embedder + corpus index) to load early via one throwaway `search()` call, so
the first real `search_guidance` dispatch doesn't eat the ONNX-model load latency; it's
idempotent and its atomic success means container-awake + embedder + index all loaded.
- **Known accepted tradeoff — first-`/chat` cold-start race.** The frontend's address
  submit does NOT wait for `/warmup` to resolve before firing the first `/chat`. This is
  intentional: any request to the Render service wakes the container regardless of which
  endpoint receives it, so gating submit on `/warmup` adds a wait state without changing
  the outcome (the container ends up warm either way). The per-message, time-based loading
  state absorbs whatever cold-start delay remains. Do not add a "wait for `/warmup`" gate
  without discussing first — it will look like a missing feature but isn't one.

**Roof catchment estimate (Google Solar API) — a deterministic reference number
folded into the catchment question.** ✅ `catchment_sa` is collected conversationally
(it was removed from the pre-chat `ChatRequest`; address stays pre-chat). When the
user is asked for it, a satellite whole-roof footprint estimate is offered as context
they can confirm, adjust, ignore, or **knowingly adopt** as their answer.
- `roofarea.estimate_roof_area` is resolved **at seed time in `app.py`** (reusing the
  geocoded lat/lon), not dispatched through `tools.py` — so it's ready before the
  catchment question and its value is turn-independent. All failures (no building, no
  coverage, HTTP error, 5s timeout, missing key) return `None`, never raising.
- **The raw digit is redacted from the model's context.** Only *availability* rides in
  the seed preamble (`ROOF_ESTIMATE_MARKER`: `[Roof estimate: available|unavailable]`).
  The exact number is carried **out of band** on `ChatRequest`/`ChatResponse.roof_sqft`
  (the client echoes it alongside `messages`, but it is NEVER placed inside `messages`).
  This one out-of-band value is the single source of truth for both display and
  calculation — no second recovery path.
- The number reaches the **user** only via deterministic substitution: the model
  authors `{roof_sqft}` in its question; `app._resolve_roof` injects the exact value on
  `awaiting_user` turns (same technique as the summary token seam, scoped to one
  token). The token stays in the transport transcript; the client renders its visible
  log from the returned `assistant_message`, so substitution lives in exactly one place.
- The number reaches the **calculation** only via server injection: `size_garden` has
  an optional `adopt_roof_estimate` flag; when the user adopts the estimate, `run_agent`
  (`_resolve_catchment`) fills `catchment_sa` with the out-of-band value and strips the
  flag **before dispatch** (recoverable error if no estimate is on record — never a hard
  failure). `_size_garden`/`sizing.py` are untouched; the compute layer only ever sees a
  concrete numeric `catchment_sa`. So the roof digit is model-authored nowhere.
- A persistent results-card advisory (whole-roof footprint ≠ this downspout's share) is
  appended whenever an estimate was offered this session, read from the availability
  marker. The `~1,700 sq ft` fallback (no-estimate path) is soft, reference-only copy —
  never a computed value and never adoptable. See TODO.md for the resolved wording.

**RAG is scoped to unstructured prose only — and it is strictly additive.** ✅
Construction, maintenance, and troubleshooting guidance = RAG. Plant selection =
deterministic filter in plants.py. Do not apply RAG to structured data.
- `search_guidance` (`tools.py`) is the sixth tool: it retrieves short, cited
  why/how passages and computes nothing. It IS dispatched (unlike
  `present_results`), but only on the terminal turn — `agent.py` gates it on
  `size_garden` + `filter_plants` already appearing in the current `call_log`, so
  its query is derived from the fired advisories, never plot size.
- `src/rain_garden/retrieval.py` — the `Embedder` seam, a local ONNX embedder
  (`OnnxEmbedder`, bge-small, shipped as package data — no key, no runtime
  download), and brute-force cosine `search()` over a shipped `.npy` index. The
  SAME `OnnxEmbedder` builds the index and embeds queries, so there is one
  embedding space by construction.
- Retrieved guidance is **narrative fuel, not a displayed channel.** The model
  paraphrases the passages into its `present_results.summary` prose; guidance is
  **dropped from the `/chat` response** — `_assemble_results` no longer reads it.
  The `search_guidance` `call_log` entry is retained server-side (traceability,
  About-section sourcing), but retrieved prose never feeds a tool input or a
  computed value, and never surfaces as its own results field.
- Numbers in the summary are **token-injected deterministically, per depth option**,
  under a strict taxonomy. The model authors ONE unified summary paragraph; on
  completion `_assemble_results` substitutes it **three times**, once per depth option,
  against a **per-option-scoped allow-list**, writing `options[i].summary` — so the same
  paragraph becomes three numerically distinct summaries (no cross-depth leakage by
  construction). There is no top-level `results.summary`.
  - **Computed deterministic values** are always injected as named `{tokens}` — never
    digits, never qualitative words. Per-depth tokens: `{depth_in}`, `{area_sqft}`,
    `{interior_plants}`, `{perimeter_plants}`. Shared (depth-invariant): `{catchment_sqft}`,
    `{gallons_per_year}`. Length/width are **not** surfaced; drain-down timing is deferred
    (see TODO). A null value drops its whole clause (the model omits the token). A summary
    referencing an unknown or null-valued token falls back to a fully code-authored,
    per-option template.
  - **Guidance-derived numbers** are always qualitative ("drains within a day or
    two"), never digits — those are the only numbers expressed in words.
  - Incidental non-dimension digits (a hardiness zone like "7b", the 811 dig line)
    are left as written — there is no digit scan.
  Advisories pass through byte-identical from the `size_garden` output — the AI
  never modifies them.
- Corpus + index are built offline by `scripts/build_rag_index.py` and shipped;
  there is no runtime index build (mirrors the CSV pattern).

**Frontend (Next.js) is last.**
A thin chat UI layer, added only after the backend and agent loop work.

---

## Source of truth

The notebook export at `notebooks/DIY Rain Garden Calculator_20260624.yaml`
is the authoritative reference for all ported logic. When in doubt, match
the notebook's behavior exactly (including edge cases), then note any defects
in TODO.md.

---

## Secrets and keys

- `.env` is gitignored. Never commit keys.
- `.env.example` lists variable names with no values.
- `RAPIDAPI_KEY` — USDA hardiness zone API (RapidAPI)
- `ANTHROPIC_API_KEY` — for the app's LLM calls (not the same
  as a Claude.ai subscription; billed per token via console.anthropic.com)
- `GOOGLE_SOLAR_API_KEY` — Google Maps Platform Solar API (roof-area estimate).
  The key must have the **Solar API enabled** and, if restricted, allow the caller —
  a misconfigured key returns HTTP 403, which the code treats as a `None` estimate
  (graceful fallback, never fatal). Free tier covers portfolio-scale usage.
- Open-Meteo (precipitation) and Nominatim (geocoding) require no keys.
  Nominatim requires a descriptive User-Agent string.

---

## Data files

- `data/RainGarden-SizeFactors.csv` — sizing factor lookup table (source of truth
  for under-30ft soil factors)
- `src/rain_garden/data/nwpl_usda_merged.csv` — National Wetlands Plant List (NWPL) merged and enriched with USDA PLANTS dataset
- `src/rain_garden/data/NWPL_RegionStateMapping.csv` — Maps NWPL regions to U.S. States

RAG artifacts (all shipped as package data, built offline — never at runtime):
- `src/rain_garden/data/guidance_chunks.jsonl` — 160 row-aligned why/how prose
  chunks (`source_doc`, `source_url`, `citation_label`, `page`)
- `src/rain_garden/data/guidance_embeddings.npy` — L2-normalized chunk embeddings
  (160 × 384), row-aligned to the sidecar; the brute-force cosine index
- `src/rain_garden/data/embedding_model/` — vendored bge-small ONNX model +
  tokenizer; the `.onnx` is tracked with **git-lfs** (see `.gitattributes`)
- `data/corpus/` — offline build inputs: `manifest.json` (sources + per-PDF page
  exclusions) and the EPA / Missouri Botanical text snippets. Source guidance
  PDFs live in the gitignored `data/raw/`.

---

## Testing conventions

- Tests must not hit the network. Use fixtures (saved API responses) for
  any module that calls an external API.
- Fixture files live in `tests/fixtures/`.
- The notebook is the oracle: expected outputs are independently verified
  against the notebook logic before being written as test assertions.
- Each module gets its own test file: `tests/test_sizing.py`, etc.

---

## What is explicitly out of scope right now

- Next.js or any frontend code
- Precipitation charts and dashboard visualizations (V2 — see TODO.md)
- Porting any logic to JavaScript

(The LLM agent loop, the FastAPI `POST /chat` endpoint, and the search_guidance
RAG layer are now built — see the Architecture section. The frontend is still the
last piece.)

---

## Deferrals and known issues

See TODO.md. Check it before starting any new module.