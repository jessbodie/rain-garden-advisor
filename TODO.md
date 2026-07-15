SUMMARY
 - Update timezone to not be hardcoded to ET
 - Check/update the plant CSV to account for regional sourcing


IN DETAIL

# Rain Garden Advisor — TODO

Items deliberately deferred, known issues, and open questions.
Add entries here rather than as inline code comments.
Reference this file in CLAUDE.md so Claude Code keeps it in context.

(Completed/implemented work is removed from this file once shipped — git history and
CLAUDE.md hold the record. Keep only open, deferred, or undecided items here.)

---

## Frontend build — IN PROGRESS (2026-07-14)
The Next.js frontend (built in the sibling `raingarden-frontend` repo) is the active
workstream. Handoff package is complete in `docs/`: `DESIGN_SPEC.md`,
`API_SAMPLES_FOR_DESIGN.md`, `FRONTEND_INTEGRATION.md`, `CLAUDE_DESIGN_BRIEF.md`, plus the
Claude Design export under `design/`. Decided: SCSS Modules (not Tailwind); hybrid routing
(landing = real indexable route at `/raingarden`, flow = client state); light theme only
for v1.

**Pending during/after the frontend build:**
- **Placeholder copy** — the landing page's **About Me bio** and **Credits & Sources**
  list are PLACEHOLDER in the design; supply real copy AFTER the frontend is coded
  (Credits & Sources is the home for the RAG guidance source citations). Consolidates the
  scattered "About page" / "Credits/Sources page" notes below.
- **Canonical `check_viability` advisory copy** is still placeholder (spec §4.5) —
  finalize during frontend work.
- **Outcome/decline gating (frontend):** gate the plan / not-recommended / decline screens
  on `outcome` + `recommended`, never on "severity ≠ informational". Handle a `complete`
  turn with no `results` (`outcome: "declined"`) and render the restart / "start over"
  affordance (§9, §10-C).

---

## Deferrals (cut from v1, planned for v2)

**Precipitation dashboard charts**
The hourly and daily precipitation visualizations (bar charts, percentile curves)
from the Hex notebook are not being ported. V2 "show your work" details view.
Added: 2026-06-25

**Timezone hardcoded to America/New_York**
`precipitation.py` currently passes `timezone=America%2FNew_York` to Open-Meteo.
Needs to be a parameter when expanding to broader Northeast or other regions.
Added: 2026-06-25

**Drain-down time (per depth)**
Compute `depth ÷ infiltration_rate` per depth option (a function of selected depth, not
area); surface whenever an infiltration rate is available. `sizing.drainage_time` is kept
for this. Open question: ship a soil→default infiltration-rate table (the CSV already
carries typical perc ranges) so drain-down can display without a user-entered rate? The
clayey drainage advisory (0.5 in/hr threshold) ships live but is bundled here for later
reevaluation.
Added: 2026-07-04

**Elongated vs. balanced shape**
Ask the user whether the garden is elongated (2:1) or balanced; compute perimeter and
interior/perimeter counts accordingly. Until then counts assume the elongated 2:1 shape,
and length/width are not surfaced.
Added: 2026-07-04

**Roof-estimate `imagery_date` not surfaced**
`roofarea.py` parses and returns `imagery_date` but it is logged/unused — decide if it
needs display alongside the roof estimate.

**~1,700 sq ft fallback constant sourced from a single blog**
The no-estimate fallback figure comes from a single roofing blog (likely a sloped
surface-area figure, not footprint). Fine for a portfolio project; revisit if an
authoritative footprint average (Census/NAHB) is wanted. It is offered only as loose
reference context, never as a computed or adoptable value.

---

## Known Issues

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
A rain garden design arguably could still be useful without the plant list. Make the app
more resilient, make the hardiness lookup degrade gracefully (like precipitation).

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
