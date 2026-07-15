# Rain Garden Advisor — Backend

An AI-powered advisor that helps DIY gardeners design a rain garden. A conversational
agent gathers site details in plain language — address, roof catchment, soil, slope,
sun, moisture — calls a deterministic calculation engine, and explains the result:
how big to dig, how deep, how many plants, and what to watch out for.

The important design constraint: **the AI never does the math.** The LLM orchestrates
tools and narrates; the tools — a clean, independently testable Python core ported from
an existing engineering notebook — do every calculation. Numbers reach the user only
through deterministic token substitution, never from the model's own text.

This repository is the **Python backend and HTTP API**. The browser UI is a separate
Next.js app (see [Frontend](#frontend)).

Live at [jessbodie.com](https://jessbodie.com) · API on Render.

---

## What it does

1. Takes an address and geocodes it, then pulls localized data: precipitation scalars,
   USDA hardiness zone, and a satellite roof-footprint estimate the user can adopt as
   their catchment area.
2. Runs early **viability checks** — foundation setback, slope, drainage rate — that can
   block or correct a design before any sizing happens.
3. Sizes the garden across **three depth options** (~4"/6"/8"), each with its own area,
   plant counts, and advisories, from a soil × depth-band factor table.
4. Filters a plant list by hardiness zone, sun, and moisture from a structured dataset.
5. Retrieves short, cited construction/maintenance guidance (RAG) as narrative fuel for
   the final summary.
6. Returns a structured plan the frontend renders, or declines with a clear reason when
   the site isn't viable.

---

## Architecture

The system is layered so the deterministic core can be tested in isolation and the AI
sits strictly on top of it.

**Deterministic core** (`src/rain_garden/`) — six pure modules, each with its own test file:

| Module | Responsibility |
| --- | --- |
| `sizing.py` | Garden area (soil × depth-band factor), dimensions, plant counts |
| `precipitation.py` | Three weather scalars from Open-Meteo |
| `geocode.py` | Address → lat/lon via Nominatim |
| `hardiness.py` | USDA hardiness zone via RapidAPI |
| `plants.py` | Structured plant filter from CSV (NWPL + USDA data) |
| `roofarea.py` | Roof footprint (sq ft) via Google Solar API |
| `retrieval.py` | Local ONNX embedder + brute-force cosine search over a shipped index (RAG) |

**Tool layer** (`tools.py`) wraps the modules as agent-callable tools and owns the
deterministic site advisories — the AI never authors an advisory or a number. It also
holds `check_viability` (the single home for the blocking checks) and the sizing shape
that returns three depth options.

**Agent loop** (`agent.py`) — a messages-based loop over the Anthropic Messages API.
`run_agent(messages, client=None) -> (messages, status, call_log)` runs one pass and
records every tool call. Two terminal signals end a conversation: `present_results`
(finishes with a plan) and `conclude_without_plan` (declines, carrying the unresolved
blocker as the reason).

**API** (`app.py`) — FastAPI, **client-stateless**. The `messages` transcript *is* the
conversation state: the browser holds it and resends it each turn, and the server runs
one agent pass per request. No session store.

**System prompt** (`prompts.py` / `src/rain_garden/prompts.py`) — passed verbatim as the
API `system` parameter.

### Key design choices

- **Numbers are token-injected, deterministically.** The model writes one summary
  paragraph with named `{tokens}`; the server substitutes computed values three times
  (once per depth option) against a per-option allow-list. The model authors no digits.
- **The roof estimate is redacted from the model's context.** Only its *availability*
  rides in the transcript; the exact number travels out-of-band on the request/response
  and is injected server-side for both display and calculation.
- **RAG is additive and prose-only.** It supplies why/how guidance for the narrative;
  it never feeds a calculation or a displayed field. Plant selection stays a
  deterministic filter.

The full rationale for each decision lives in [CLAUDE.md](CLAUDE.md); the ported logic's
source of truth is the notebook export in `notebooks/`.

---

## Getting started

Requires **Python 3.10+**.

```bash
# from the repo root
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash);  .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"            # installs the package + dev tools (pytest)
```

### Environment

Copy `.env.example` to `.env` and fill in the keys:

```
RAPIDAPI_KEY=          # USDA hardiness zone API (RapidAPI)
ANTHROPIC_API_KEY=     # the app's LLM calls (billed per token via console.anthropic.com)
GOOGLE_SOLAR_API_KEY=  # Google Solar API, roof-area estimate (Solar API must be enabled)
```

Open-Meteo (precipitation) and Nominatim (geocoding) need no keys. `.env` is gitignored —
never commit keys.

`ALLOWED_ORIGINS` (comma-separated) controls CORS; it defaults to `https://jessbodie.com`
when unset. Add `http://localhost:3000` (or a Vercel preview origin) to develop against
the frontend locally.

### Run the API

```bash
uvicorn app:app --reload
```

- `POST /chat` — the single conversational endpoint (client-stateless; send back the
  full `messages` transcript each turn).
- `POST /warmup` — forces the RAG singletons (ONNX embedder + corpus index) to load
  early so the first real request doesn't eat the model-load latency. Idempotent.

### Tests

```bash
pytest
```

Tests never hit the network — external APIs are covered by saved fixtures in
`tests/fixtures/`. The notebook is the oracle: expected outputs are verified against the
notebook logic before being written as assertions.

### RAG index

The corpus chunks, embeddings, and the vendored bge-small ONNX model all ship as package
data — there is **no runtime index build**. To rebuild after changing the corpus:

```bash
python scripts/build_rag_index.py
```

The `.onnx` model is tracked with git-lfs (see `.gitattributes`).

---

## Frontend

This repo is the Python backend only. The browser UI is a separate **Next.js** app
(`raingarden-frontend`, a sibling repository), served from Vercel and mounted under
`/raingarden`. It holds and resends the `messages` transcript, round-trips the roof
estimate, and renders the returned plan — it never recomputes anything. The complete
handoff set (design spec, API samples, integration guide) lives in [`docs/`](docs/).

---

## How AI was used

This project was built with AI as an active collaborator across the whole lifecycle, not
as an afterthought. Being deliberate about *which* tool did *what* was part of the work.

**Claude Chat — thinking, planning, and porting.** The original calculation logic lived
in a Hex/Python notebook. Claude Chat was used to reason through the port, pin down edge
cases against the notebook oracle, shape the depth-options sizing model, and work out the
harder architectural calls (the viability-blocker model, the client-stateless transport,
how to keep the LLM out of the math). Much of what became `CLAUDE.md` and `TODO.md`
started as these design conversations.

**Claude Code — implementation and iteration.** The backend itself — the deterministic
modules, the tool layer, the agent loop, the FastAPI service, the RAG pipeline, and the
test suites — was written and refactored in Claude Code, working directly against the
repository. That includes the fiddly, correctness-critical seams: the per-depth token
substitution that keeps model-authored digits out of the output, the roof-estimate
redaction, and the progress-stepper derivation. Tests were written alongside each module
with the notebook as the source of truth.

**Claude Design — the visual system and UI.** The brand system (color, type, the sage
accent with coral reserved for warnings), the component specs, and a high-fidelity HTML
prototype came from Claude Design, exported into `design/` and handed off to the frontend
build via the docs in `docs/`.

The throughline: AI accelerated the parts that benefit from speed and breadth — porting,
scaffolding, iteration, design exploration — while the engineering constraints that make
the tool trustworthy (deterministic math, tested edge cases, the AI never emitting a
number) were designed in on purpose and verified, not assumed.

---

## Repository layout

```
app.py                 FastAPI service (POST /chat, POST /warmup)
agent.py               Anthropic Messages API agent loop
tools.py               Agent-callable tools, advisories, viability checks
prompts.py             System prompt
src/rain_garden/       Deterministic core (six modules) + data + RAG
scripts/               Offline RAG index build + response dumps
tests/                 Per-module tests + fixtures (no network)
notebooks/             Source-of-truth notebook export
data/                  Sizing factors CSV + RAG corpus build inputs
docs/                  Frontend + design handoff
design/                Claude Design export (prototype, tokens, assets)
CLAUDE.md              Full architecture rationale and decisions
TODO.md                Deferrals and known issues
```
