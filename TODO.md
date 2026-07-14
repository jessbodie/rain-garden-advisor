SUMMARY
 - Update timezone to not be hardcoded to ET
 - Check/update the plant CSV to account for regional sourcing


IN DETAIL

# Rain Garden Advisor — TODO

Items deliberately deferred, known issues, and open questions.
Add entries here rather than as inline code comments.
Reference this file in CLAUDE.md so Claude Code keeps it in context.

---

## Frontend build — STARTING (2026-07-14)
The Next.js frontend (previously deferred as "last") is now the active workstream.
Handoff package is complete in `docs/`: `DESIGN_SPEC.md`, `API_SAMPLES_FOR_DESIGN.md`,
`FRONTEND_INTEGRATION.md`, `CLAUDE_DESIGN_BRIEF.md`, plus the Claude Design export under
`design/`. Decided: SCSS Modules (not Tailwind); hybrid routing (landing = real indexable
route at `/raingarden`, flow = client state); light theme only for v1.

**Pending during/after the frontend build:**
- **Placeholder copy** — the landing page's **About Me bio** and **Credits & Sources**
  list are PLACEHOLDER in the design; supply real copy AFTER the frontend is coded
  (Credits & Sources is the home for the RAG guidance source citations). Consolidates
  the earlier scattered "About page" / "Credits/Sources page" notes below.
- **Canonical `check_viability` advisory copy** is still placeholder (spec §4.5) —
  finalize during frontend work.

## Implemented: Frontend-readiness backend tweaks (2026-07-14)
Two small API-contract changes so the frontend builds against a stable surface. Full
suite green (213 passed).
- **CORS is now env-driven** (`app.py`): `ALLOWED_ORIGINS` (comma-separated) replaces the
  hardcoded `["https://jessbodie.com"]`, defaulting to that origin when unset. Lets local
  dev (`localhost:3000`) and Vercel previews be allowed per-environment without a code
  change. **Action for deploy:** set `ALLOWED_ORIGINS` in each environment (Render prod,
  local `.env`, any preview) — unset = production-only.
- **Distinct address-error status** (`app.py` + `tools.py`): a geocode miss now returns
  `status: "address_not_found"` (was `out_of_region` for both cases). `geocode_and_gate`
  carries a `reason` field; `_stages` treats both rejections the same (Address =
  in_progress). The frontend keys its two Address error screens off `status`, not brittle
  `detail` string-matching. Tests: `test_gate_refuses_*` assert `reason`;
  `test_address_not_found_marks_address_in_progress` added.

---

## Implemented: Roof Catchment Area Estimation (Google Solar API)
Implemented 2026-07-03 (branch `estimate-roofSA`). Verified live against the Solar
API and offline via fixtures (191+ tests). The original feature spec is superseded by
the shipped design; the resolved decisions are captured here.

**What shipped**
- `src/rain_garden/roofarea.py` — `estimate_roof_area(lat, lon, timeout_s=5.0)` calls
  Solar `buildingInsights.findClosest`, reads `wholeRoofStats.groundAreaMeters2`
  (footprint, not sloped `areaMeters2`), converts ×10.7639, rounds to nearest 10.
  Every failure — no building, no coverage, HTTP error, 5s timeout, **missing key** —
  degrades to `None` (never raises; diverges from hardiness's fatal-key policy because
  the estimate is additive reference context).
- Resolved **at seed time** in `app.py` (reusing the geocoded lat/lon), not as a
  dispatched agent tool — so it's ready before the catchment question and its value is
  turn-independent.
- **Redaction:** only *availability* rides in the seed preamble
  (`[Roof estimate: available|unavailable]`); the raw digit is carried **out of band**
  on `ChatRequest`/`ChatResponse.roof_sqft` (echoed by the client, never in
  `messages`). It reaches the user only via deterministic `{roof_sqft}` substitution
  (`_resolve_roof`) and the calculation only via server injection — model-authored
  nowhere.
- **Adoption ("I don't know" path):** the user may adopt the estimate as their
  catchment area. `size_garden` gained an optional `adopt_roof_estimate` flag;
  `run_agent` injects the exact out-of-band value as `catchment_sa` before dispatch
  (recoverable error if no estimate exists — never a hard failure). Compute layer
  (`_size_garden`, `sizing.py`) untouched.
- `catchment_sa` moved out of the pre-chat `ChatRequest` into conversational
  slot-filling (address stays pre-chat).
- Persistent results-card advisory whenever an estimate was offered (whole-roof
  footprint ≠ this downspout's share).

**Fallback copy — RESOLVED (softened, reference-only)**
The "~1,700 sq ft" figure is a soft, unverified reference number (single roofing blog,
likely a *sloped surface-area* figure, not footprint). It is offered only on the
no-estimate path as loose context, never as a computed value or an adoptable answer.
Decided wording (in `prompts.py`):
- With estimate: *"Roughly how many square feet drain into this spot? For reference,
  satellite imagery puts your whole roof at about {roof_sqft} sq ft — but most homes
  drain through more than one downspout, so the area feeding this one is usually
  smaller."*
- No estimate (fallback): *"Roughly how many square feet of roof or pavement drain
  into this spot? We couldn't pull a satellite estimate here, but for rough context a
  typical US home roof is very roughly 1,700 sq ft — a ballpark, not your answer."*
Only `{roof_sqft}` is adoptable; the ~1,700 figure never is.

**Still open / deferred here**
- `imagery_date` is parsed and returned by the module but not surfaced to the user
  (logged/unused) — decide if it needs display.
- The ~1,700 constant remains sourced from a single blog; fine for a portfolio
  project, revisit if an authoritative footprint average (Census/NAHB) is wanted.
- Driveway/patio (non-roof impervious) estimation stays **out of scope** — no
  deterministic data source; would need CV/segmentation.
- `GOOGLE_SOLAR_API_KEY` must have the Solar API enabled and (if restricted) allow the
  dev/deploy caller — a misconfigured key returns 403, which the code treats as `None`.

---

## Implemented: Early Viability Check (`check_viability`) + decline path
Implemented 2026-07-05 (branch `blocking-advisories`). Deterministic core verified
against the Chat-authored oracle (spec §8, `tests/test_viability.py`); wiring verified
offline (full suite green). Moves the three viability blockers earlier in the flow so a
site is flagged as inputs are collected, not only at the terminal sizing turn.

**What shipped**
- `tools.check_viability(distance, slope_ok, perc_rate, soil_type)` — stateless,
  None-tolerant; the single home for `foundation_setback`, `slope`, `low_drainage`
  (measured rate on the open interval `0 < rate < 0.5`; `0.0`/`0.5` pass) + soft
  `clayey_unverified`. Invalid `distance` enum raises `ValueError` (tool path → recoverable
  error). Exposed as the `check_viability` tool; `size_garden` also calls it internally
  (DRY — one place derives `recommended`). The old inline blocking logic in `_advisories`
  is deleted.
- **Behavior change:** the old `clay_drainage` advisory (fired on any Clayey soil) is
  replaced by `clayey_unverified` (fires only when Clayey AND no measured rate; a measured
  rate governs and suppresses it). The CLAUDE.md "byte-identical advisories" note was
  updated accordingly.
- `conclude_without_plan` terminal tool (decline path, §7.5 State B) — intercepted in
  `agent.py` like `present_results`, recorded in `call_log`, returns `status="complete"`.
- `ChatResponse.outcome` discriminator (`app.py`, §9): `"plan"` / `"plan_not_recommended"`
  (override, State A) / `"declined"` (no `results`), keyed off `call_log` — never a
  transcript scan (§10-D).
- Prompt (`prompts.py`): the `check_viability` wiring, the raise-on-knowability rule, and
  the **explicit two-step** offer-correction → confirm-override → decline flow (§7.2, kept
  distinct — not collapsed into one "proceed anyway?").

**Reconciliation decisions (spec §11, "align, don't fork" — confirmed with user)**
- Advisory code rides the existing `type` field (not a new `code` field); `corrective_action`
  is an additive field on viability advisories only.
- `clayey_unverified` uses the existing non-blocking severity `"corrective"` (not the spec's
  proposed new `"advisory"` value). Only `severity == "blocking"` gates not-recommended;
  verified by grep that nothing keys blocking-UI treatment off corrective (precedent:
  `slope_toward_house` already ships corrective + `recommended: true`).

**Still open / deferred**
- **§10-E tracker step mapping** — RESOLVED 2026-07-09, see "Implemented: Progress Stepper
  (`ChatResponse.stages`)" below. The mapping was reconciled against the wireframe with the
  user and differs from this item's earlier guess: **all four `check_viability` inputs
  (distance, slope, drainage, soil) are Site Conditions**; Growing Conditions is sun +
  moisture (`filter_plants` inputs only). Soil/drainage are NOT Growing Conditions.
- **§10-F** — skipped per spec.
- **Frontend (Vercel, out of this repo):** must gate the plan/not-recommended/decline
  screens on `outcome` + `recommended`, never on "severity ≠ informational"; must handle a
  `complete` turn with no `results` (`outcome: "declined"`) and render the restart/"start
  over" affordance (§9, §10-C). Copy for the canonical `check_viability` messages is
  placeholder (§4.5) — finalize during frontend work.

## Implemented: Progress Stepper (`ChatResponse.stages`)
Implemented 2026-07-09 (branch `blocking-advisories`). Backend-authoritative UI progress
tracker. Verified offline (`tests/test_progress.py`, 14 cases; full suite green) and
end-to-end through the HTTP layer with a stubbed client. Resolves §10-E.

**What shipped**
- `ChatResponse.stages` — five ordered stages (`address`, `localized_data`,
  `site_conditions`, `growing_conditions`, `plan`), each `{id, label, state}` with
  `state ∈ not_started|in_progress|complete`, returned on every `/chat` path. The frontend
  renders it; no stage logic in JS (CLAUDE.md).
- `_stages` / `_called_tools` / `_latest_viability_inputs` / `_site_conditions_done` in
  `app.py`. Derived from a structured `tool_use`-name scan of the transcript (cumulative,
  since the transcript *is* the client-stateless state), NOT `call_log` (per-turn). Two
  layers: order-free per-stage `complete` flags + a single in-progress cursor placed by
  status/outcome.
- **Refined Site-Conditions granularity:** Site clears mid-chat (before `size_garden`) once
  the latest `check_viability` inputs carry **distance + slope** AND `check_viability` finds
  no blocker — reuses the real tool (DRY). A corrective note (clayey-unverified) does not
  block completion; a blocker (slope, setback, measured low-drainage) does. Soil is NOT a
  completion gate (see live-run finding below) but is still passed through when known.
- **End states (tri-state):** an advisory fills the bar to Plan; a produced plan
  (recommended or overridden → `plan`/`plan_not_recommended`) fills the whole bar; a
  decline (`conclude_without_plan` → `outcome: declined`) freezes the cursor at Site
  Conditions and Plan never completes. Stages are NOT strictly left-to-right (a later stage
  can be complete while an earlier one is the cursor).

**Live-run tuning (2026-07-09, done)**
Drove a real Brooklyn conversation against uvicorn and watched `stages` per turn. Two
findings, both resolved:
- The model calls `check_viability` incrementally for the **blocker** slots (distance,
  slope) but will NOT re-call it for benign soil (e.g. sandy) — so a distance+slope+soil
  gate never cleared mid-chat and the cursor stalled at Site until the finale (Coarse, not
  Refined). Strengthening the prompt to re-call on every slot got slope included but not
  soil. **Resolution:** the Site gate is distance + slope only (`_SITE_CORE_SLOTS`); soil
  stays a passed-through input and a categorical Site Condition, just not a completion gate.
  Verified: the cursor now walks Address → Localized → Site → Growing → Plan as slots fill.
- Applied the prompt nudge anyway (`prompts.py`, CHECKING VIABILITY EARLY): re-call
  `check_viability` on each viability slot, passing all known values, even absent a
  suspected blocker. Behavioral only, no schema change.
- **Frontend rendering** of the stepper lands with the (out-of-repo) Vercel UI, alongside
  the results screen and its depth toggle. The depth toggle is downstream of the terminal
  turn and stays decoupled from `stages`.

## Implemented: Depth-Options Sizing Redesign
Implemented 2026-07-04. Verified offline (full suite green). Supersedes the
"[v2] Depth selection and depth/footprint coupling" deferral below.

**What shipped**
- Single soil × depth-band factor table (`sizing.SIZE_FACTORS_BY_DEPTH`, transcribed
  cell-for-cell from `data/RainGarden-SizeFactors.csv`, verified by
  `test_factor_derivation.py`), applied universally. `area = catchment × factor(soil, band)`.
- **Distance no longer feeds area** — it is advisory-only (setback). The `>30 ft`
  table, the rate-table override, and `recommended_depth`/`GEOMETRY_TABLE` are removed
  from `sizing.py` (`soil_sizing_factor`, `rate_sizing_factor`, `resolve_sizing_factor`
  all gone).
- **Three depth options always computed** — about 4"/6"/8" (bands 3-5"/6-7"/8"). Each
  option carries its own `area_sqft`, `interior_plants`, `perimeter_plants`, `advisories`,
  and a `summary`. Deeper = smaller factor = more compact. Unknown soil → Clayey column.
- **Contract:** `size_garden` now returns `{recommended, sizing:{options[], advisories[]},
  advisories[], gallons_per_year}`. `results.summary` (top-level) is retired; the depth
  toggle is pure frontend view state (all three ship in one `/chat` response).
- **Advisory buckets:** existing site/viability advisories stay top-level, byte-identical
  (clayey now fires whenever soil is Clayey, rate or not). `sizing.advisories` holds only
  the new 30%-reduction allowance (fires only when a split-ceiling fires and no floor does).
  Per-option `options[i].advisories` hold the 300 sq ft split-ceiling and the two-zone
  floor (gated on the **unrounded** interior count).
- **Summaries:** the model authors ONE tokenized paragraph; `_assemble_results`
  substitutes it three times, once per option, against a per-option-scoped allow-list
  (`{depth_in} {area_sqft} {interior_plants} {perimeter_plants}` per-depth;
  `{catchment_sqft} {gallons_per_year}` shared). No cross-depth leakage by construction.
- Dropped the `contingent`/`contingent_on` design flag (its container was removed; the
  sub-0.5 in/hr case is fully carried by the `low_drainage` blocking advisory +
  `recommended=False`; no live consumer).

**Deferred from this redesign**
- **Drain-down time (per depth):** compute `depth ÷ infiltration_rate` per option (a
  function of selected depth, not area); surface whenever an infiltration rate is
  available. `sizing.drainage_time` is kept for this. Open question: ship a soil→default
  infiltration-rate table (CSV already carries typical perc ranges) so drain-down can
  display without a user-entered rate? The clayey drainage advisory (0.5 in/hr threshold)
  ships live but is bundled here for later reevaluation.
- **Elongated vs. balanced shape:** ask the user whether the garden is elongated (2:1) or
  balanced; compute perimeter and interior/perimeter counts accordingly. Until then counts
  assume the elongated 2:1 shape, and length/width are not surfaced.
Added: 2026-07-04

---

## Deferrals (cut from v1, planned for v2)

**Precipitation dashboard charts**
The hourly and daily precipitation visualizations (bar charts, percentile curves)
from the Hex notebook are not being ported. V2 "show your work" details view.
Added: 2026-06-25

**Timezone hardcoded to America/New_York**
`precipitation.py` currently passes `timezone=America%2FNew_York` to Open-Meteo.
Needs to be a parameter when expanding to broader
Northeast or other regions. 
Added: 2026-06-25


---

## Known Issues


**gallons_per_year — soil/perc decoupling already holds; null only without precip**
Corrected 2026-07-04. Re-verified against `_size_garden`: `gallons_per_year` is
`gallons_diverted(catchment_sa, total_precip_yr)` gated ONLY on `total_precip_yr`, with
no soil or perc-rate dependency. It is NOT null when soil is unknown, and NOT null on the
low-perc branch (confirmed by dispatch: unknown-soil + precip -> a number). The earlier
"null when soil is unknown / decouple from the perc-rate branch" framing no longer
matches the code. The only residual: `gallons_per_year` is null when precipitation stats
weren't supplied to `size_garden` (the model is prompted to always pass them from
get_precipitation_stats; a null therefore means those stats were missing/failed, a
model-reliability concern, not a compute bug). On a null run the summary's
{gallons_per_year} clause is simply omitted, per the reference-only-present-values rule.

**Negative interior area on tiny gardens**
The notebook's plant-count formula produces a negative interior area when the
rain garden is very small (roughly < 5 sq ft). `sizing.py` now guards against
this (clamps to 0), but the upstream cause — no minimum viable garden size
check — is unaddressed. A garden below ~9 sq ft (the geometry table minimum)
should probably return a warning rather than silently produce edge-case counts.
Partly addressed 2026-07-04: an option whose interior can't hold one plant now fires
the per-option `two_zone_floor` advisory (single-zone perimeter planting). A hard
minimum-viable-size check on the whole garden is still unaddressed.
Added: 2026-06-25

**getDepth saturates for real-world catchments** — RESOLVED 2026-07-04
Obsolete: depth is no longer an area-derived output. `recommended_depth` and the
geometry table were removed; depth is now a user tradeoff across three fixed options
(about 4"/6"/8"). See "Implemented: Depth-Options Sizing Redesign" above.
Added: 2026-06-29

**Agent-layer and FastAPI tests — partial gaps remain**
Largely addressed. `tests/test_viability_wiring.py` and `tests/test_roof_estimate.py`
are both fully offline (fake Anthropic client + `TestClient` + monkeypatched
`geocode_and_gate`) and now cover: the `run_agent` tool loop and dispatch, both
terminal contracts (`present_results` via the `outcome` tiers and
`conclude_without_plan` — terminal, logged, not routed to dispatch), and the `/chat`
seed path end-to-end plus the three `outcome` tiers (plan / plan_not_recommended /
declined).
Still uncovered: the `status="error"` tier in `run_agent`; the out-of-region gate
rejection in `/chat`; and a continue-turn `/chat` test (every current `/chat` test
mocks `geocode_and_gate` to `ok: True`, so only the seed path is exercised). The
built-in Brooklyn oracle smoke test in `__main__` still hits live services and is
not part of the offline suite.
Added: 2026-06-30
Updated: 2026-07-08

## [DONE 2026-07-04] Depth selection and depth/footprint coupling

Implemented — see "Implemented: Depth-Options Sizing Redesign" above. Depth is now a
user-selectable tradeoff: `size_garden` returns three (depth, area, plant-count) options
from the CSV's 3-5"/6-7"/8" bands, and the system prompt presents them. The distance
caveat that blocked this ("depth bands exist only for the <30 ft regime") is moot now
that Table 1 (<30 ft) is applied universally and distance no longer feeds area.


**Plant-count geometry doesn't sanity-check small gardens**
The plant-count math allots 1.33 sq ft/plant by area but ignores whether the
plants physically fit the footprint. E.g. a 0.05-factor garden (Loamy/700 sq ft,
area 35) has a ~4 ft length → ~2.67 ft plantable interior width, yet the model
places 11 interior plants, which can't physically fit in that strip. Faithful to
the notebook; needs a geometry-aware feasibility check (or a per-row spacing
cap) so counts don't exceed what the dimensions support.
Added: 2026-06-29


**RapidAPI hardiness zone key was previously hardcoded in the Hex notebook**
The exposed key (in the YAML export) should be revoked if not already done.
The new key lives in `.env`.
Added: 2026-06-25

**Nominatim rate limiting and caching not implemented**
Nominatim's usage policy is max 1 request/second and asks that results be
cached. geocode.py currently makes a live call every invocation. Add
request-rate limiting (e.g., a simple sleep or a token bucket) and a small
in-memory or disk cache keyed on the input address.
Added: 2026-06-25
ESCALATED 2026-07-01: the "before the agent layer goes live" precondition has
passed — agent.py and app.py are built and call geocode_and_gate — yet no
throttle/cache exists. Now an outstanding gap, not future work.

**RapidAPI hardiness zone is on the BASIC plan (1 req/sec)**
The current RapidAPI subscription rate-limits to 1 request/second; hardiness.py
makes no attempt to throttle. Add a rate limiter or short sleep between calls,
or upgrade the plan if call volume warrants. Caching by zip is also worth
considering — hardiness zones don't change.
Added: 2026-06-25
ESCALATED 2026-07-01: the agent layer is now live (dispatch → get_hardiness_zone)
and still no throttle exists. Now an outstanding gap, not future work.

**RAPIDAPI_KEY is currently a hard dependency (a missing key crashes the run)** 
A rain garden design arguably could still be useful without the plant list. Make the app more resilient, make the hardiness lookup degrade gracefully (like precipitation) 

**Plant lists are capped at 15 each. Paginate?**

**Ability to sort plant list by height, color, bloom_period**

**Ability to filter plant list by height, color, bloom_period**

**About page**

**Credits/Sources page**

**Education piece about value of rain garden**


---

## Open Questions

**Plant spacing assumption**
The notebook allocates 1.33 sq ft per plant (1.33 × 1.33 = 1.77 sq ft each).
This is a rough estimate. Verify against any regional extension-service guidance
for the plant types.
Added: 2026-06-25

**RAG corpus sources**
The guidance RAG layer (construction, maintenance, troubleshooting) needs a
curated source list. Candidates identified so far:
- DC DOEE rain garden guide (already cited in notebook)
- Five Counties Salmonid Conservation Program guide (already cited)
- EPA "Soak Up the Rain" guidance
- Oregon Rain Garden Guide (cited in notebook)
Added: 2026-06-25

**Evaluate if/when the 3:1 basin slope about the garden's internal side wall should surface as an advisory**

**For list of plants, can we get and then include the dropped Scientific Name?**
Design/frontend context (2026-07-14): the Claude Design plant table **dropped** the
Scientific Name column (the API doesn't expose it). Restoring it means adding
`scientific_name` to `tools.py` `_PLANT_COLUMNS` (confirm it exists in the plant CSV).
Still open — a deliberate future decision, not pre-build work.

**For list of plants, examine the "mosture use" detail and if we can translate to "Drought Tolerance" or something more intuitive**
Design/frontend context (2026-07-14): the design + `FRONTEND_INTEGRATION.md` kept the
column labeled **"Moisture Use"** (the real `moisture_use` field). Do NOT simply relabel
it "Drought Tolerance" — that's a different (arguably inverse) quantity and would mislead.
A true drought-tolerance column would need a new data field. Still open.

---

## Feature Requests

**Print full plan to PDF**

---

## v3 and Beyond

**Precise NWPL Region Lookup via Shapefile**
Currently, states that span two NWPL regions (e.g. Virginia spans EMP and AGCP) are handled by querying both regional columns and returning a plant if it qualifies in either. This is a reasonable approximation for v1.
A more accurate approach: the Army Corps of Engineers publishes NWPL regional boundaries as shapefiles, using the same boundaries as the Regional Supplements to the Corps Wetland Delineation Manual. Given the user's lat/lon (already available from geocode.py), do a spatial point-in-polygon lookup against those shapefiles to determine the exact NWPL region, then query only that column. This eliminates the edge case where a plant is wetland-adapted in one part of a split state but not another.
Libraries: geopandas, shapely. Shapefiles available at: https://wetland-plants.usace.army.mil


**tightening the prompt (spell out "days" etc.)**
TODO -- for the cases when numbers trip the auto-template of the AI summary response