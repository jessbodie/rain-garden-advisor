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

from dotenv import find_dotenv, load_dotenv

# Entry point owns env loading (§7): load .env before the Anthropic client reads
# the key. Must run before constructing the client below.
load_dotenv(find_dotenv(usecwd=True))

import anthropic  # noqa: E402  — after load_dotenv
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent import last_assistant_text, run_agent  # noqa: E402
from tools import (  # noqa: E402
    LOCATION_PREAMBLE_MARKER,
    FatalToolError,
    build_seed,
    geocode_and_gate,
)

app = FastAPI(title="Rain Garden Advisor")

# One client for the process — reuses the connection pool across requests. The
# sync handler runs in FastAPI's threadpool, so concurrent requests are fine.
_client = anthropic.Anthropic()


class ChatRequest(BaseModel):
    # Seed request: a fresh conversation.
    address: str | None = None
    catchment_sa: float | None = None
    # Continue request: prior transcript returned last turn, plus the new answer.
    messages: list | None = None
    user_message: str | None = None


class ChatResponse(BaseModel):
    status: str  # awaiting_user | complete | out_of_region | error
    messages: list = []
    assistant_message: str | None = None
    results: dict | None = None
    detail: str | None = None


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


def _assemble_results(call_log: list) -> dict:
    """Build the structured results payload from the deterministic tool outputs.

    Reads call_log (not model text). Dict comprehension keeps the *last* entry per
    tool name, so a refine turn that re-runs size_garden surfaces the updated design.
    Guards against a prompt slip (present_results without the sizing/plant calls in
    this request's log): returns whatever is present rather than raising KeyError.
    """
    latest = {c["name"]: c for c in call_log}
    present = latest.get("present_results")
    results: dict = {
        "summary": present["input"].get("summary") if present else None,
    }
    sizing = latest.get("size_garden")
    if sizing:
        results["sizing"] = sizing["output"]
        results["advisories"] = sizing["output"].get("advisories", [])
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
        # Continue: geocode already ran (its output rides in the preamble and the
        # precip/hardiness tool_results). Append the user's answer and re-drive.
        messages.append({"role": "user", "content": req.user_message or ""})
    else:
        # Seed: geocode + gate before any model call. Out-of-region is a terminal
        # business outcome (HTTP 200), not an error, and never reaches the model.
        location = geocode_and_gate(req.address or "")
        if not location.get("ok"):
            return ChatResponse(status="out_of_region", detail=location["message"])
        messages = [{"role": "user", "content": build_seed(location, req.catchment_sa)}]

    try:
        messages, status, call_log = run_agent(messages, client=_client)
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
    assistant = last_assistant_text(messages)
    if not assistant and results:
        assistant = results.get("summary")

    return ChatResponse(
        status=status,
        messages=messages,
        assistant_message=assistant or None,
        results=results,
    )
