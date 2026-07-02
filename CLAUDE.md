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
- `src/rain_garden/precipitation.py` — three weather scalars from Open-Meteo ✅
- `src/rain_garden/geocode.py` — address → lat/lon via Nominatim ✅
- `src/rain_garden/hardiness.py` — USDA hardiness zone via RapidAPI ✅
- `src/rain_garden/plants.py` — structured plant filter from CSV ✅

**Tool layer (`tools.py`) wraps the five modules as agent-callable tools.** It owns the
deterministic site advisories (not the LLM). `size_garden` takes two *separate* slope inputs:
`slope_ok` (grade/steepness, ≤12%; false → blocking advisory) and `slopes_away_from_house`
(direction; false → a *corrective* advisory to build an overflow outlet away from the foundation —
does not block, `recommended` stays true). Omitting a slope input fires no advisory. ✅

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
- **Completion contract:** `present_results` is a terminal control signal, not a
  calculation. The loop intercepts it before dispatch, records it in `call_log`
  (with `output=None`; the summary rides in its input), and returns
  `status="complete"`. It appears in `TOOLS` but is never routed through `dispatch`.
- `app.py` — FastAPI `POST /chat`, **client-stateless**. ✅ The `messages`
  transcript *is* the conversation state: the browser holds it and resends it
  each turn; the server runs one `run_agent` pass per request. No session store.
  Seed vs. continue is discriminated by `LOCATION_PREAMBLE_MARKER` in `messages`,
  so geocoding runs exactly once per conversation.
- `prompts.py` — `SYSTEM_PROMPT`, passed verbatim as the API `system` parameter.

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
- Numbers in the summary are **token-injected deterministically.** The model
  authors the summary with named `{tokens}` (`{area_sqft}`, `{gallons_per_year}`,
  `{drainage_time_hours}`, …); `_assemble_results` substitutes the exact
  compute-tool values, so no *computed* garden value originates in model prose. A
  summary that references an unknown or null-valued token falls back to a fully
  code-authored template. Incidental non-dimension digits (a hardiness zone like
  "7b", the 811 dig line) are left as written — there is no digit scan. Advisories
  pass through byte-identical from the `size_garden` output — the AI never modifies them.
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