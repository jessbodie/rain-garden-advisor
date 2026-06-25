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
Correct for NYC scope, but needs to be a parameter when expanding to broader
Northeast or other regions. Refactor before any non-NYC deployment.
Added: 2026-06-25

**Region scope: NYC only for v1**
Plant data, hardiness zones, and precipitation defaults are scoped to
New York City. Northeast expansion is v2 and requires a region-filtered
plant dataset.
Added: 2026-06-25


**Plant hardiness filter uses apparent (wind-chill) temperature, not actual**
precipitation.py returns min_apparent_temp, which the notebook then uses to
filter plants by USDA Temperature, Minimum (°F). USDA hardiness ratings are
based on actual air temperature, not perceived/wind-chill. When hardiness.py
is built, switch the plant filter to use the USDA hardiness zone (from the
RapidAPI lookup) as the authoritative cold-tolerance filter, and either drop
min_apparent_temp or repurpose it as an informational value only.
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

**Plant CSV has no regional native-status data**
`usda-plants_8-1-2023.csv` is a national dataset with an empty NativeStatuses
column. The current plant filter (moisture + drought tolerance + shade + soil)
does not filter by region or native status. A region-filtered re-pull from USDA
PLANTS is needed before `plants.py` is production-ready.
`nyc_rain_garden_native_plants.csv` exists as a hand-curated fallback for v1.
Added: 2026-06-25

**RapidAPI hardiness zone key was previously hardcoded in the Hex notebook**
The exposed key (in the YAML export) should be revoked if not already done.
The new key must live only in `.env`.
Added: 2026-06-25

**USDA PLANTS ScientificName has embedded HTML tags**
Values contain literal `<i>` and `</i>` tags (e.g. `<i>Abelia ×grandiflora</i>`).
Strip on ingest in `plants.py`.
Added: 2026-06-25

---

## Open Questions

**Less-than-10-ft distance path**
The notebook warns against siting a rain garden within 10 ft of the foundation
but still runs the calculation using the less-30ft sizing factor. Decide whether
the advisor should hard-block or warn-and-continue for this case.
Added: 2026-06-25

**Plant spacing assumption**
The notebook allocates 1.33 sq ft per plant (1.33 × 1.33 = 1.77 sq ft each).
This is a rough estimate. Verify against any regional extension-service guidance
for the plant types actually in the NYC native list.
Added: 2026-06-25

**RAG corpus sources**
The guidance RAG layer (construction, maintenance, troubleshooting) needs a
curated source list. Candidates identified so far:
- DC DOEE rain garden guide (already cited in notebook)
- Five Counties Salmonid Conservation Program guide (already cited)
- EPA "Soak Up the Rain" guidance
- Oregon Rain Garden Guide (cited in notebook)
- NYC-specific extension service material (not yet identified)
Added: 2026-06-25
