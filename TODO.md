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


**Plant hardiness filter uses apparent (wind-chill) temperature, not actual**
precipitation.py returns min_apparent_temp, which the notebook then uses to
filter plants by USDA Temperature, Minimum (°F). USDA hardiness ratings are
based on actual air temperature, not perceived/wind-chill. When hardiness.py
is built, switch the plant filter to use the USDA hardiness zone (from the
RapidAPI lookup) as the authoritative cold-tolerance filter, and either drop
min_apparent_temp or repurpose it as an informational value only.
Added: 2026-06-25
RESOLVED 2026-06-28: plants.filter_plants now takes `local_min_temp`, sourced
from the hardiness zone's lower bound via hardiness.min_temp_floor() (not
min_apparent_temp). The comparison direction was also inverted in the notebook
(it kept cold-tender plants); fixed to keep plants whose rated minimum is at or
below the local floor. STILL OPEN: precipitation.py still computes
min_apparent_temp — decide at the agent layer whether to drop it or keep it as
informational only.

**min_temp direction bug (notebook kept cold-tender plants)**
Added: 2026-06-25
RESOLVED 2026-06-28: corrected to `plant_min_temp <= local_min_temp`. On current
data the null-temp exclusion is latent (every NY/NJ candidate has a non-null min
temp, so the filter only ever drops by value) — fine, just noted for the agent
layer.

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
The new key must live only in `.env`.
Added: 2026-06-25

**Nominatim rate limiting and caching not implemented**
Nominatim's usage policy is max 1 request/second and asks that results be
cached. geocode.py currently makes a live call every invocation. Before the
agent layer goes live, add request-rate limiting (e.g., a simple sleep or a
token bucket) and a small in-memory or disk cache keyed on the input address.
Added: 2026-06-25

**RapidAPI hardiness zone is on the BASIC plan (1 req/sec)**
The current RapidAPI subscription rate-limits to 1 request/second; hardiness.py
makes no attempt to throttle. At the agent layer, add a rate limiter or short
sleep between calls, or upgrade the plan if call volume warrants. Caching by
zip is also worth considering — hardiness zones don't change.
Added: 2026-06-25

**Note the data/RainGarden-sizeFactors.csv updated descrip and added category for Loamy**

---

## Open Questions

**Less-than-10-ft distance path**
The notebook warns against siting a rain garden within 10 ft of the foundation
but still runs the calculation using the less-30ft sizing factor. The advisor should warn-and-continue for this case.
Added: 2026-06-25

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