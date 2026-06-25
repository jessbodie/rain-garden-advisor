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

**Deterministic core — five clean modules, each independently testable:**
- `src/rain_garden/sizing.py` — garden area, dimensions, depth, plant counts ✅
- `src/rain_garden/precipitation.py` — three weather scalars from Open-Meteo (in progress)
- `src/rain_garden/geocode.py` — address → lat/lon via Nominatim (not started)
- `src/rain_garden/hardiness.py` — USDA hardiness zone via RapidAPI (not started)
- `src/rain_garden/plants.py` — structured plant filter from CSV (not started)

**LLM layer comes after all five modules are complete and tested.**
The agent loop, function calling, and Anthropic SDK are not touched until then.

**RAG is scoped to unstructured prose only.**
Construction, maintenance, and troubleshooting guidance = RAG.
Plant selection = deterministic filter in plants.py. Do not apply RAG to
structured data.

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
- `ANTHROPIC_API_KEY` — added later, for the app's LLM calls (not the same
  as a Claude.ai subscription; billed per token via console.anthropic.com)
- Open-Meteo (precipitation) and Nominatim (geocoding) require no keys.
  Nominatim requires a descriptive User-Agent string.

---

## Data files

- `data/RainGarden-SizeFactors.csv` — sizing factor lookup table (source of truth
  for under-30ft soil factors)
- `data/usda-plants_8-1-2023.csv` — national USDA PLANTS dataset; NativeStatuses
  column is empty; region filtering is a known open issue (see TODO.md)
- `data/nyc_rain_garden_native_plants.csv` — hand-curated NYC native plant list;
  fallback for v1 plants module

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

- Any LLM / Anthropic SDK code
- FastAPI endpoints (added after all five modules pass)
- Next.js or any frontend code
- Precipitation charts and dashboard visualizations (V2 — see TODO.md)
- Porting any logic to JavaScript

---

## Deferrals and known issues

See TODO.md. Check it before starting any new module.