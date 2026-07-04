SUMMARY
 - Update timezone to not be hardcoded to ET
 - Check/update the plant CSV to account for regional sourcing


IN DETAIL

# Rain Garden Advisor — TODO

Items deliberately deferred, known issues, and open questions.
Add entries here rather than as inline code comments.
Reference this file in CLAUDE.md so Claude Code keeps it in context.

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

**Agent-layer and FastAPI tests missing**
The agent/HTTP layers are built but untested: `app.py` (FastAPI `POST /chat`)
has no `test_app.py`, and `agent.py` has no `test_agent.py` — only the built-in
Brooklyn oracle smoke test in `__main__`, which hits live Open-Meteo / Nominatim
/ RapidAPI / Anthropic services. Per CLAUDE.md, tests must not hit the network:
add fixture-backed tests for `run_agent` (the tool loop, the present_results
completion contract, awaiting_user/complete/error statuses) and for the `/chat`
endpoint (seed vs. continue via the location preamble, out-of-region, error tiers).
Added: 2026-06-30

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


---

## v3 and Beyond

**Precise NWPL Region Lookup via Shapefile**
Currently, states that span two NWPL regions (e.g. Virginia spans EMP and AGCP) are handled by querying both regional columns and returning a plant if it qualifies in either. This is a reasonable approximation for v1.
A more accurate approach: the Army Corps of Engineers publishes NWPL regional boundaries as shapefiles, using the same boundaries as the Regional Supplements to the Corps Wetland Delineation Manual. Given the user's lat/lon (already available from geocode.py), do a spatial point-in-polygon lookup against those shapefiles to determine the exact NWPL region, then query only that column. This eliminates the edge case where a plant is wetland-adapted in one part of a split state but not another.
Libraries: geopandas, shapely. Shapefiles available at: https://wetland-plants.usace.army.mil


**tightening the prompt (spell out "days" etc.)**
TODO -- for the cases when numbers trip the auto-template of the AI summary response