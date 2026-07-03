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

import re

from dotenv import find_dotenv, load_dotenv

# Entry point owns env loading (§7): load .env before the Anthropic client reads
# the key. Must run before constructing the client below.
load_dotenv(find_dotenv(usecwd=True))

import anthropic  # noqa: E402  — after load_dotenv
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import last_assistant_text, run_agent  # noqa: E402
from rain_garden.roofarea import estimate_roof_area  # noqa: E402
from tools import (  # noqa: E402
    LOCATION_PREAMBLE_MARKER,
    ROOF_ESTIMATE_AVAILABLE,
    FatalToolError,
    build_seed,
    geocode_and_gate,
)

app = FastAPI(title="Rain Garden Advisor")

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
    status: str  # awaiting_user | complete | out_of_region | error
    messages: list = []
    assistant_message: str | None = None
    results: dict | None = None  # sizing/plants/advisories + token-injected summary
    detail: str | None = None
    # Echoed back so the client can resend it next turn (see ChatRequest.roof_sqft).
    roof_sqft: float | None = None


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


# Curated allow-list of summary tokens sourced 1:1 from the size_garden design.
# catchment_sqft is handled separately (it comes from the tool INPUT, not the
# design output). Enumerated explicitly — never a **design splat — so an unknown
# token in the model summary is a detectable error, not a silent pass-through.
_SUMMARY_DESIGN_KEYS = (
    "area_sqft", "depth_inches", "elongated_width_ft", "elongated_length_ft",
    "balanced_side_ft", "interior_plant_count", "perimeter_plant_count",
    "drainage_time_hours", "gallons_per_year",
)
_TOKEN_RE = re.compile(r"\{(\w+)\}")


def _substitutions(sizing_entry: dict) -> dict:
    """Curated token -> deterministic value map for summary substitution.

    Values may be None (e.g. drainage_time_hours without a measured perc rate);
    :func:`_resolve_summary` treats a *referenced* null as an error and falls back.
    catchment_sqft is read from the size_garden INPUT (it is not a design output).
    """
    design = sizing_entry["output"]["design"]
    subs = {k: design.get(k) for k in _SUMMARY_DESIGN_KEYS}
    subs["catchment_sqft"] = sizing_entry["input"].get("catchment_sa")
    return subs


def _fallback_summary(subs: dict) -> str:
    """Fully code-authored summary. Tokens filled from ``subs``; any clause whose
    value is null is omitted. Its only digits are substituted deterministic values
    (no narrative digits), so it is returned as-is with no digit guard."""
    parts = [
        f"Your rain garden should cover about {subs['area_sqft']} sq ft and sit "
        f"{subs['depth_inches']} inches deep. Shape it either elongated "
        f"({subs['elongated_width_ft']} ft by {subs['elongated_length_ft']} ft, long "
        f"side across the water's path) or squarer ({subs['balanced_side_ft']} ft per "
        f"side).",
        f"Plan for {subs['interior_plant_count']} plants in the wetter center and "
        f"{subs['perimeter_plant_count']} around the drier edge.",
    ]
    if subs.get("gallons_per_year") is not None:
        parts.append(
            f"It captures roughly {subs['gallons_per_year']} gallons of runoff a year "
            f"from about {subs['catchment_sqft']} sq ft of catchment."
        )
    if subs.get("drainage_time_hours") is not None:
        parts.append(
            f"After a storm it drains in about {subs['drainage_time_hours']} hours."
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

    The summary is rendered by token substitution (:func:`_resolve_summary`): the
    model authors it with named {tokens}, and the exact deterministic values are
    injected here, so no computed number ever originates in model prose. Retrieved
    guidance is narrative fuel for that prose upstream — it is NOT a results field.

    Guards against a prompt slip (present_results without the sizing call in this
    request's log): with no design to substitute against, the raw summary passes
    through rather than raising KeyError.
    """
    latest = {c["name"]: c for c in call_log}
    present = latest.get("present_results")
    raw_summary = present["input"].get("summary") if present else None

    results: dict = {}
    # Numeric/structured fields — sourced ONLY from the deterministic compute-tool
    # entries. Advisories pass through byte-identical to the size_garden output.
    sizing = latest.get("size_garden")
    if sizing:
        results["summary"] = _resolve_summary(raw_summary, _substitutions(sizing))
        results["sizing"] = sizing["output"]
        results["advisories"] = sizing["output"].get("advisories", [])
    else:
        results["summary"] = raw_summary
    plants = latest.get("filter_plants")
    if plants:
        results["plants"] = plants["output"]
    return results


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
        # Seed: geocode + gate before any model call. Out-of-region is a terminal
        # business outcome (HTTP 200), not an error, and never reaches the model.
        location = geocode_and_gate(req.address or "")
        if not location.get("ok"):
            return ChatResponse(status="out_of_region", detail=location["message"])
        # Resolve the roof estimate once, up front (reusing the geocoded lat/lon), so it
        # is available before the catchment question. Bounded by a ~5s timeout; None on
        # any failure. Only *availability* rides in the seed; the digit stays out of band.
        estimate = estimate_roof_area(location["lat"], location["lon"])
        roof_sqft = estimate["roof_sqft"] if estimate else None
        messages = [{"role": "user", "content": build_seed(location, estimate)}]

    try:
        messages, status, call_log = run_agent(messages, client=_client, roof_sqft=roof_sqft)
    except FatalToolError as exc:  # specific catch (§7) — e.g. missing API key
        return JSONResponse(
            status_code=500,
            content=ChatResponse(status="error", detail=str(exc)).model_dump(),
        )

    if status == "error":
        # Truncation or an unhandled stop reason — deliberate 500, not a crash.
        return JSONResponse(
            status_code=500,
            content=ChatResponse(
                status="error",
                messages=messages,
                detail="The model run did not complete (truncated or unhandled stop).",
            ).model_dump(),
        )

    results = _assemble_results(call_log) if status == "complete" else None
    if results is not None and _roof_estimate_available(messages):
        # Independent of size_garden's own advisories: the persistent whole-roof caveat,
        # shown whenever an estimate was offered — regardless of the user's final value.
        results.setdefault("advisories", []).append(_ROOF_ADVISORY)

    assistant = last_assistant_text(messages)
    if not assistant and results:
        assistant = results.get("summary")
    # Deterministic {roof_sqft} injection for the question turn (no-op on other turns).
    assistant = _resolve_roof(assistant, roof_sqft)

    return ChatResponse(
        status=status,
        messages=messages,
        assistant_message=assistant or None,
        results=results,
        roof_sqft=roof_sqft,
    )
