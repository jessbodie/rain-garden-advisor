SUMMARY
 - Update timezone to not be hardcoded to ET
 - Check/update the plant CSV to account for regional sourcing


IN DETAIL

# Rain Garden Advisor — TODO

Items deliberately deferred, known issues, and open questions.
Add entries here rather than as inline code comments.
Reference this file in CLAUDE.md so Claude Code keeps it in context.

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

**Negative interior area on tiny gardens**
The notebook's plant-count formula produces a negative interior area when the
rain garden is very small (roughly < 5 sq ft). `sizing.py` now guards against
this (clamps to 0), but the upstream cause — no minimum viable garden size
check — is unaddressed. A garden below ~9 sq ft (the geometry table minimum)
should probably return a warning rather than silently produce edge-case counts.
Added: 2026-06-25

**getDepth saturates for real-world catchments**
`recommended_depth` looks up the closest row in the geometry table, which tops
out at 36 sq ft min-area → 12" depth. Any garden >= ~36 sq ft clamps to 12",
so depth is effectively constant for essentially all real catchments. Faithful
to the notebook, but the depth output carries no information above that size.
Revisit whether depth should scale (or be dropped) for larger gardens.
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

## [v2] Depth selection and depth/footprint coupling

Current behavior:
- Ponding depth is a *dependent output*, not an input. getDepth(area) returns
  the geometry-table depth whose Min Area is closest to the computed area.
- It saturates at 12" above 36 sq ft, so for essentially all real catchments
  depth pins at 12" and is effectively constant.
- Footprint (length / width / balanced side) is computed directly from area
  (sqrt(area/2), etc.), independent of depth. Depth and footprint are parallel
  outputs of area, not coupled — choosing a depth cannot currently change the
  footprint. (NOTE: this contradicts the intuition that "depth impacts
  dimensions"; it currently does not.)
- The single sizing_factor bakes in an implicit depth assumption (notebook
  averaged the 6-7" and 8" bands), which may disagree with the depth_inches the
  geometry table reports for the same garden.

Requirement gap:
- Depth should be selectable, and should trade against footprint (deeper basin
  -> smaller footprint for the same storage). Offer dimension options by depth.

v2 implementation notes:
- The depth-banded factors already exist in data/RainGarden-SizeFactors.csv
  (3-5", 6-7", 8" columns). Each soil -> three (depth, factor) pairs ->
  three (depth, area, footprint) options. Feed these instead of one factor.
- Caveats:
  * Depth bands exist only for the <30 ft distance regime. The >30 ft factors
    are single values, not depth-banded — no data backing for depth-as-input on
    far gardens. Resolve before exposing the feature there.
  * Confirm which column/aggregation the committed sizing_factor uses, to know
    what depth today's single number implies and whether it matches the reported
    depth_inches.
  * Reconcile getDepth (geometry table) against the factor's implied depth so
    the reported depth and the footprint describe the same basin.
- Prompt impact: when size_garden returns depth options, the system prompt's
  results section must present them.


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