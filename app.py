"""FastAPI HTTP layer over the rain-garden agent loop.

Single endpoint ``POST /chat``. **Client-stateless:** the ``messages`` transcript
*is* the conversation state — the browser holds it and resends it on every turn;
the server runs one agent-loop pass per request and returns the updated transcript.
There is no session store; the API key, tool definitions, and loop stay server-side.

Seed vs continue is discriminated by the location-preamble marker in ``messages``
(a seed request has none), so geocoding runs exactly once per conversation.

Trust note: the client holds the structured ``tool_result`` blocks and the server
re-drives from them rather than recomputing, so a client *can* edit them. Acceptable
only because a user can corrupt nothing but their own recommendation — no
multi-tenant, sensitive, or cost/privilege-amplifying data.
"""

from __future__ import annotations

import os
import re

from dotenv import find_dotenv, load_dotenv

# Entry point owns env loading (§7): load .env before the Anthropic client reads
# the key. Must run before constructing the client below.
load_dotenv(find_dotenv(usecwd=True))

import anthropic  # noqa: E402  — after load_dotenv
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import last_assistant_text, run_agent  # noqa: E402
from rain_garden import sizing  # noqa: E402  — parse_perc_rate for stage viability check
from rain_garden.retrieval import search  # noqa: E402
from rain_garden.roofarea import estimate_roof_area  # noqa: E402
from tools import (  # noqa: E402
    CHECK_VIABILITY,
    CONCLUDE_WITHOUT_PLAN,
    LOCATION_PREAMBLE_MARKER,
    PRESENT_RESULTS,
    ROOF_ESTIMATE_AVAILABLE,
    SIZE_GARDEN,
    FatalToolError,
    build_seed,
    check_viability,
    geocode_and_gate,
)

app = FastAPI(title="Rain Garden Advisor")

# The browser frontend (jessbodie.com, served from Vercel) calls this API cross-origin.
# Scoped tight: explicit origins only (no "*" — that breaks credentialed requests and isn't
# the pattern here), only the methods/headers /chat and /warmup actually use. The OPTIONS
# preflight is answered by the middleware itself, so allow_methods lists only POST.
# allow_credentials is left at its default (False): no cookies/auth are in play, which is
# what keeps the explicit-origin allowlist valid.
#
# Origins are env-driven (ALLOWED_ORIGINS, comma-separated) so local dev (localhost:3000)
# and Vercel preview subdomains can be allowed per-environment WITHOUT a code change, while
# production stays scoped to jessbodie.com by default. Set e.g.
#   ALLOWED_ORIGINS=http://localhost:3000,https://jessbodie.com
# in the relevant environment; unset falls back to production-only.
_DEFAULT_ORIGINS = "https://jessbodie.com"
_allowed_origins = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

# One client for the process — reuses the connection pool across requests. The
# sync handler runs in FastAPI's threadpool, so concurrent requests are fine.
_client = anthropic.Anthropic()


class ChatRequest(BaseModel):
    # Seed request: a fresh conversation. catchment_sa is NO LONGER pre-supplied — it
    # is gathered conversationally (the roof estimate is offered as reference context).
    address: str | None = None
    # Continue request: prior transcript returned last turn, plus the new answer.
    messages: list | None = None
    user_message: str | None = None
    # Out-of-band carrier for the exact satellite roof estimate. Resolved at seed time,
    # returned in ChatResponse, and echoed back by the client on every continue — it is
    # deliberately kept OUT of `messages` so the raw digit never enters the model's
    # context. Single source of truth for both the {roof_sqft} question substitution and
    # an adopt_roof_estimate size_garden call.
    roof_sqft: float | None = None


class ChatResponse(BaseModel):
    status: str  # awaiting_user | complete | address_not_found | out_of_region | error
    # Terminal discriminator for the frontend, set ONLY on a complete turn (else None).
    # Gates which screen renders — the frontend keys off this, never a transcript scan:
    #   "plan"                 — recommended design; normal plan render.
    #   "plan_not_recommended" — State A: results present, recommended False, blocker kept.
    #   "declined"             — State B: user declined; NO results, terminal message only.
    outcome: str | None = None
    messages: list = []
    assistant_message: str | None = None
    results: dict | None = None  # sizing/plants/advisories + token-injected summary
    detail: str | None = None
    # Echoed back so the client can resend it next turn (see ChatRequest.roof_sqft).
    roof_sqft: float | None = None
    # Progress-stepper state for the UI: five stages in canonical order, each
    # {id, label, state} with state in not_started|in_progress|complete. Derived
    # server-side from the transcript's tool calls + this turn's status/outcome (see
    # _stages) — the frontend just renders it. None only when no derivation ran.
    stages: list | None = None


def _has_preamble(messages: list | None) -> bool:
    """True if any turn carries the location preamble — i.e. a continuation.

    build_seed sets the seed turn's content to a string containing the marker;
    later user turns (tool_results) are lists and assistant turns are block dicts,
    so a plain string scan reliably isolates the seed preamble.
    """
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, str) and LOCATION_PREAMBLE_MARKER in content:
            return True
    return False


def _roof_estimate_available(messages: list | None) -> bool:
    """True if a satellite roof estimate resolved this session.

    Read from the seed preamble's availability marker (which persists across turns,
    like the location marker) — NOT from the raw digit, which never enters `messages`.
    Gates the results-card roof advisory.
    """
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, str) and ROOF_ESTIMATE_AVAILABLE in content:
            return True
    return False


# Persistent results-card advisory whenever a roof estimate was offered this session
# (regardless of the user's final catchment_SA): the estimate is whole-roof footprint,
# not this downspout's share. The chat question happens early and may be scrolled past.
_ROOF_ADVISORY = {
    "type": "roof_estimate",
    "severity": "informational",
    "message": (
        "The satellite roof estimate reflects your entire roof's footprint — not the "
        "catchment area for this specific downspout. Most homes have more than one "
        "gutter and downspout, each carrying only part of the total roof runoff."
    ),
}

_ROOF_TOKEN = "{roof_sqft}"


def _resolve_roof(text: str, roof_sqft) -> str:
    """Inject the exact roof value for the question turn's ``{roof_sqft}`` token.

    The roof digit is redacted from the model's context, so it enters the outgoing
    text ONLY here (mirrors ``_resolve_summary``, scoped to one token). The token stays
    in the transport ``messages`` transcript (the model keeps seeing a placeholder, not
    a number); the client renders its visible chat log from this returned string, so
    substitution lives in exactly one place. If the token appears with no value on
    record (should not happen — the prompt only writes it when the estimate is
    available), drop the sentence rather than emit a literal brace.
    """
    if not text or _ROOF_TOKEN not in text:
        return text
    if roof_sqft is None:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return " ".join(s for s in sentences if _ROOF_TOKEN not in s).strip()
    return text.replace(_ROOF_TOKEN, str(int(roof_sqft)))


# Curated allow-list of per-option summary tokens. The first four are scoped to a
# single depth option; catchment_sqft and gallons_per_year are depth-invariant and
# shared across all three. Enumerated explicitly — never a **splat — so an unknown
# token in the model summary is a detectable error, not a silent pass-through.
_OPTION_TOKEN_KEYS = ("depth_in", "area_sqft", "interior_plants", "perimeter_plants")
_TOKEN_RE = re.compile(r"\{(\w+)\}")


def _substitutions(sizing_entry: dict, option: dict) -> dict:
    """Per-option token -> deterministic value map for summary substitution.

    Partitioned by option: each dict pulls ONLY its own depth's area/plant counts,
    so a rendered summary can never show a mismatched depth (an 8" paragraph cannot
    substitute a 4" area). catchment_sqft is read from the size_garden INPUT and
    gallons_per_year from the output — both depth-invariant, shared across options.
    A None value (e.g. gallons without precip data) is treated by
    :func:`_resolve_summary` as a referenced-null error and routes to the fallback.
    """
    subs = {k: option.get(k) for k in _OPTION_TOKEN_KEYS}
    subs["catchment_sqft"] = sizing_entry["input"].get("catchment_sa")
    subs["gallons_per_year"] = sizing_entry["output"].get("gallons_per_year")
    return subs


def _fallback_summary(subs: dict) -> str:
    """Fully code-authored per-option summary. Tokens filled from ``subs``; any
    clause whose value is null is omitted. Its only digits are substituted
    deterministic values (no narrative digits), so it is returned as-is."""
    parts = [
        f"At about {subs['depth_in']} inches deep, your rain garden should cover "
        f"roughly {subs['area_sqft']} sq ft.",
        f"Plan for {subs['interior_plants']} plants in the wetter center and "
        f"{subs['perimeter_plants']} around the drier edge.",
    ]
    if subs.get("gallons_per_year") is not None:
        parts.append(
            f"It captures roughly {subs['gallons_per_year']} gallons of runoff a year "
            f"from about {subs['catchment_sqft']} sq ft of catchment."
        )
    parts.append("Review the advisories below before you dig.")
    return " ".join(parts)


def _resolve_summary(raw_summary, subs: dict) -> str:
    """Render the model's summary by injecting deterministic values for its tokens.

    Every garden dimension the model references is a token, and each token is
    replaced with its deterministic value here — so no *computed* garden value
    originates in model prose. Two conditions route to the code-authored fallback
    instead:
    * an unknown token (not in the allow-list); or
    * a referenced token whose value is null (null-is-error, never blank-fill —
      mirrors the prompt's reference-only-present-values rule).

    Incidental non-dimension digits the model writes as prose (a hardiness zone like
    "7b", the 811 dig line) are not computed garden values, so they need no
    substitution and are left exactly as written.
    """
    raw = raw_summary or ""
    referenced = _TOKEN_RE.findall(raw)
    if any(name not in subs or subs[name] is None for name in referenced):
        return _fallback_summary(subs)
    return _TOKEN_RE.sub(lambda m: str(subs[m.group(1)]), raw)


def _assemble_results(call_log: list) -> dict:
    """Build the structured results payload from the deterministic tool outputs.

    Reads call_log (not model text). Dict comprehension keeps the *last* entry per
    tool name, so a refine turn that re-runs size_garden surfaces the updated design.

    Summaries are rendered by token substitution (:func:`_resolve_summary`): the model
    authors ONE unified paragraph with named {tokens}, and it is substituted three
    times — once per depth option, against that option's own value set — so the depth
    tradeoff is conveyed by the numbers, not per-depth editorial prose, and no computed
    number ever originates in model prose. Retrieved guidance is narrative fuel for that
    prose upstream — it is NOT a results field.

    Guards against a prompt slip (present_results without the sizing call in this
    request's log): with no options to substitute against, no summaries are produced.
    """
    latest = {c["name"]: c for c in call_log}
    present = latest.get("present_results")
    raw_summary = present["input"].get("summary") if present else None

    results: dict = {}
    # Structured fields — sourced ONLY from the deterministic compute-tool entries.
    # Advisories pass through byte-identical to the size_garden output.
    sizing = latest.get("size_garden")
    if sizing:
        out = sizing["output"]
        for option in out["sizing"]["options"]:
            option["summary"] = _resolve_summary(
                raw_summary, _substitutions(sizing, option)
            )
        results["sizing"] = out["sizing"]              # {options (w/ summaries), advisories}
        results["advisories"] = out.get("advisories", [])
        results["gallons_per_year"] = out.get("gallons_per_year")
        results["recommended"] = out.get("recommended")
    plants = latest.get("filter_plants")
    if plants:
        results["plants"] = plants["output"]
    return results


def _is_declined(call_log: list) -> bool:
    """True if the model reached the decline terminal (spec §7.5 State B).

    Read from call_log, exactly like the search_guidance gate and the present_results
    completion — NOT by scanning the transcript. This call-log keying is the whole
    reason conclude_without_plan is a tool and not an inferred sentinel (§10-D).
    """
    return any(c["name"] == CONCLUDE_WITHOUT_PLAN for c in call_log)


# --- Progress stepper (spec: UI stages) --------------------------------------
# The five UI stages in canonical display order. Each stage's `complete` is derived
# independently from the transcript's tool calls (order-free — a later stage can read
# complete while an earlier one is still the in-progress cursor); a single cursor is then
# placed per this turn's status/outcome. See the plan doc + CLAUDE.md.
_STAGES = (
    ("address", "Address"),
    ("localized_data", "Localized Data"),
    ("site_conditions", "Site Conditions"),
    ("growing_conditions", "Growing Conditions"),
    ("plan", "Rain Garden Plan"),
)
# Site Conditions clears early (before size_garden fires) once these viability slots are
# known AND check_viability finds no standing blocker. Deliberately distance + slope only:
# those are the two blocker slots the model RELIABLY screens via check_viability (verified
# by live run). Soil is NOT required — it is not a blocker (only the soft clayey note), and
# the model won't re-call check_viability for benign soil, so requiring it would stall the
# stepper until the finale. Soil (and perc_rate) are still PASSED to check_viability below
# when known, so a measured low-drainage blocker still keeps the stage incomplete.
_SITE_CORE_SLOTS = ("distance", "slope_ok")


def _called_tools(messages: list) -> set[str]:
    """Cumulative set of tool_use block *names* across every assistant turn.

    A structured read (block type/name), same spirit as _has_preamble — not a prose
    scan. The transcript is the client-stateless conversation state and run_agent appends
    this turn's assistant blocks before returning, so this set is cumulative *and*
    current: it captures tools fired on earlier turns that this turn's call_log omits.
    """
    names: set[str] = set()
    for msg in messages or []:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("name"):
                    names.add(block["name"])
    return names


def _latest_viability_inputs(messages: list) -> dict:
    """The ``input`` dict of the most recent check_viability tool_use block ({} if none).

    check_viability is None-tolerant and called incrementally as site slots fill, so its
    latest call reflects the freshest known viability inputs — the signal that advances
    Site Conditions mid-chat, before size_garden runs at the finale.
    """
    latest: dict = {}
    for msg in messages or []:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == CHECK_VIABILITY
            ):
                latest = block.get("input") or {}
    return latest


def _site_conditions_done(messages: list, tools_called: set[str]) -> bool:
    """True once the site is established: size_garden ran, OR viability cleared early.

    Early-clear needs the core slots (distance, slope) known AND no standing blocker.
    The "no blocker" test reuses the real check_viability (DRY — one home for blocker
    logic): a blocker in the inputs (e.g. slope_ok False, or a measured rate under 0.5)
    keeps `recommended` False and the stage incomplete, while a corrective note
    (clayey-unverified) does not — completion keys on `recommended`, never severity. Soil
    is not a core slot (see _SITE_CORE_SLOTS) but is still passed through when known, so a
    clayey + measured-slow-rate combination is caught here just as size_garden would.
    """
    if SIZE_GARDEN in tools_called:
        return True
    vinputs = _latest_viability_inputs(messages)
    if not all(vinputs.get(slot) is not None for slot in _SITE_CORE_SLOTS):
        return False
    return check_viability(
        distance=vinputs.get("distance"),
        slope_ok=vinputs.get("slope_ok"),
        # Parse the same way size_garden does — check_viability expects a numeric rate.
        perc_rate=sizing.parse_perc_rate(vinputs.get("perc_rate")),
        soil_type=vinputs.get("soil_type"),
    )["recommended"]


def _stages(messages: list, status: str, outcome: str | None) -> list[dict]:
    """Derive the five-stage progress stepper for the UI.

    Independent, order-free `complete` flags (from cumulative tool calls) + a single
    in-progress cursor placed by this turn's status/outcome:
    * address_not_found / out_of_region — address in_progress, rest not_started (the
      seed was rejected pre-model, so no transcript exists yet). Both address-entry
      rejections share this stepper shape; only the terminal `status` differs.
    * complete + plan/plan_not_recommended — every stage complete (a plan was produced,
      even when a blocker was overridden or an advisory fired; the bar fills fully).
    * otherwise (awaiting_user / error / declined) — completed stages marked, the cursor
      on the earliest incomplete stage, the rest not_started. On a decline the site
      blocker keeps Site Conditions incomplete, so the cursor freezes there and Plan
      never completes; the frontend styles the halt from outcome == "declined".
    """
    tools_called = _called_tools(messages)
    complete = {
        "address": _has_preamble(messages),
        "localized_data": {"get_precipitation_stats", "get_hardiness_zone"} <= tools_called,
        "site_conditions": _site_conditions_done(messages, tools_called),
        "growing_conditions": "filter_plants" in tools_called,
        "plan": PRESENT_RESULTS in tools_called,
    }

    states: dict[str, str] = {}
    if status in ("address_not_found", "out_of_region"):
        states = {sid: "not_started" for sid, _ in _STAGES}
        states["address"] = "in_progress"
    elif status == "complete" and outcome in ("plan", "plan_not_recommended"):
        states = {sid: "complete" for sid, _ in _STAGES}
    else:
        cursor_placed = False
        for sid, _ in _STAGES:
            if complete[sid]:
                states[sid] = "complete"
            elif not cursor_placed:
                states[sid] = "in_progress"
                cursor_placed = True
            else:
                states[sid] = "not_started"

    return [{"id": sid, "label": label, "state": states[sid]} for sid, label in _STAGES]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Run one agent-loop pass. Sync handler → FastAPI runs it in a threadpool.

    ``run_agent`` is synchronous and makes blocking network calls (Nominatim,
    Open-Meteo, RapidAPI, the Anthropic SDK); declaring this ``def`` (not
    ``async def``) keeps those off the event loop so concurrent requests don't
    serialize.
    """
    messages = list(req.messages or [])

    if _has_preamble(messages):
        # Continue: geocode + roof estimate already ran on the seed turn. The roof value
        # rides out of band (req.roof_sqft), echoed by the client each turn — never in
        # `messages`. Append the user's answer and re-drive.
        messages.append({"role": "user", "content": req.user_message or ""})
        roof_sqft = req.roof_sqft
    else:
        # Seed: geocode + gate before any model call. A rejected address is a terminal
        # business outcome (HTTP 200), not an error, and never reaches the model. The two
        # rejection kinds carry distinct statuses (address_not_found — geocode miss;
        # out_of_region — resolved but outside the lower-48) so the frontend picks the
        # right error screen by a stable key, not by matching the human `detail` text.
        location = geocode_and_gate(req.address or "")
        if not location.get("ok"):
            # Address submitted but didn't resolve to a usable lower-48 location: bar shows
            # Address in_progress (no transcript exists yet to derive from).
            status = location.get("reason", "out_of_region")
            return ChatResponse(
                status=status,
                detail=location["message"],
                stages=_stages([], status, None),
            )
        # Resolve the roof estimate once, up front (reusing the geocoded lat/lon), so it
        # is available before the catchment question. Capped at 3s: this sits on the
        # address-submit critical path (geocode + roof + first model turn all block the
        # response), so a slow/no-coverage Solar call must not stall submit — a timeout
        # yields None, identical to any other miss. Only *availability* rides in the seed;
        # the digit stays out of band.
        estimate = estimate_roof_area(location["lat"], location["lon"], timeout_s=3.0)
        roof_sqft = estimate["roof_sqft"] if estimate else None
        messages = [{"role": "user", "content": build_seed(location, estimate)}]

    try:
        messages, status, call_log = run_agent(messages, client=_client, roof_sqft=roof_sqft)
    except FatalToolError as exc:  # specific catch (§7) — e.g. missing API key
        return JSONResponse(
            status_code=500,
            content=ChatResponse(
                status="error",
                detail=str(exc),
                stages=_stages(messages, "error", None),
            ).model_dump(),
        )

    if status == "error":
        # Truncation or an unhandled stop reason — deliberate 500, not a crash.
        return JSONResponse(
            status_code=500,
            content=ChatResponse(
                status="error",
                messages=messages,
                detail="The model run did not complete (truncated or unhandled stop).",
                stages=_stages(messages, "error", None),
            ).model_dump(),
        )

    # Terminal outcome discriminator (spec §9), keyed off call_log — never a transcript
    # scan. Only a complete turn carries an outcome; awaiting_user/error leave it None.
    outcome = None
    results = None
    if status == "complete":
        if _is_declined(call_log):
            # State B: the user declined an un-overridable blocker. No plan is produced —
            # results stays None even if some stray sizing entry sits in the log.
            outcome = "declined"
        else:
            results = _assemble_results(call_log)
            if _roof_estimate_available(messages):
                # Independent of size_garden's own advisories: the persistent whole-roof
                # caveat, shown whenever an estimate was offered — regardless of value.
                results.setdefault("advisories", []).append(_ROOF_ADVISORY)
            # State A vs normal: the not-recommended layout is gated on `recommended`
            # (a blocker was overridden), NOT on any advisory's corrective severity.
            outcome = "plan" if results.get("recommended") else "plan_not_recommended"

    assistant = last_assistant_text(messages)
    if not assistant and results:
        # No top-level summary anymore; fall back to the first depth option's summary.
        options = results.get("sizing", {}).get("options") if results else None
        if options:
            assistant = options[0].get("summary")
    # Deterministic {roof_sqft} injection for the question turn (no-op on other turns).
    assistant = _resolve_roof(assistant, roof_sqft)

    return ChatResponse(
        status=status,
        outcome=outcome,
        messages=messages,
        assistant_message=assistant or None,
        results=results,
        roof_sqft=roof_sqft,
        stages=_stages(messages, status, outcome),
    )


@app.post("/warmup")
def warmup():
    """Force the RAG lazy singletons to load on a cheap out-of-band request.

    The embedder and corpus index are independent lazy singletons that today only
    populate when ``search_guidance`` first dispatches (the terminal turn of a real
    conversation) — so that ONNX-model load latency would otherwise land on a user.

    This calls ``search()`` with a throwaway canary query so the warm path is, by
    construction, identical to what the first real ``search_guidance`` dispatch does —
    rather than reimplementing the load sequence (``_get_embedder()`` + ``load_index()``)
    and risking silent drift. One ``search()`` call populates both singletons:
      - ``load_index()``    -> ``_index_cache``     (embeddings .npy + chunks .jsonl)
      - ``_get_embedder()`` -> ``_shared_embedder`` (OnnxEmbedder / ONNX session)

    Idempotent: subsequent hits — from /warmup or any real search_guidance call in the
    same process — reuse the process-level globals (a cheap no-op). Exceptions are NOT
    swallowed: the warmup promise is atomic (container awake + embedder + index all
    loaded), so it must resolve iff ``search()`` completed once. A missing/corrupt
    artifact 500-ing here is the correct signal, not something to mask as success.
    """
    search("rain garden depth")  # result discarded; the call is the side effect
    return {"status": "warm"}
