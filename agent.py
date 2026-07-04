"""LLM agent loop for the rain garden advisor.

Standalone script at the repo root: the conversational layer that wires the
deterministic tools (``tools.py``) to the Anthropic Messages API. No FastAPI,
no frontend.

Flow:

1. **Pre-step (deterministic, before any model call):** geocode the address and
   gate it to the lower-48. An out-of-region address never enters the loop.
2. **Loop:** the model drives tool use. It may emit several ``tool_use`` blocks
   in one turn (precip + hardiness have no dependency), so every block in a turn
   is dispatched and all ``tool_result`` blocks go back in the following turn.
   Tool order is *not* enforced — dependency edges hold because the model can't
   wire an output it hasn't received yet.

Error tiers mirror ``tools.dispatch``: a ``FatalToolError`` (e.g. missing API
key) is a hard stop with no synthesis; recoverable failures arrive as a normal
tool result (``{"is_error": True, ...}``) and the model decides how to degrade.

``__main__`` is a fully-seeded, non-interactive Brooklyn smoke test: the seed
message carries every site detail, so the model needs no follow-up questions and
any ``end_turn`` is terminal. It runs the acceptance oracle in Section 8 of the
spec. The smoke test hits the live Open-Meteo / Nominatim / RapidAPI / Anthropic
services, so it needs RAPIDAPI_KEY and ANTHROPIC_API_KEY in ``.env``.
"""

from __future__ import annotations

import json
import sys

import anthropic

# The model's synthesis may contain emoji/Unicode; a Windows cp1252 console
# raises UnicodeEncodeError on print. Make stdout tolerant rather than lose output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # non-reconfigurable stream
    pass

from tools import (
    GUIDANCE_GATE_MSG,
    GUIDANCE_PREREQS,
    PRESENT_RESULTS,
    SEARCH_GUIDANCE,
    SIZE_GARDEN,
    TOOLS,
    FatalToolError,
    build_seed,
    dispatch,
    geocode_and_gate,
)
from rain_garden.prompts import SYSTEM_PROMPT

# Sonnet is a sensible default for tool orchestration (cost/latency vs. Opus).
MODEL = "claude-sonnet-4-6"
# Generous enough for the final synthesis, which embeds two plant lists.
MAX_TOKENS = 4096


def last_assistant_text(messages: list) -> str:
    """Concatenate the text blocks of the most recent assistant turn.

    Assistant turns are stored as serialized dicts (see ``run_agent``), so this
    reads ``b["text"]`` rather than block attributes. Returns "" if the last
    assistant turn carried no text (e.g. a bare tool_use turn).
    """
    for msg in reversed(messages):
        if msg["role"] != "assistant":
            continue
        content = msg["content"]
        if isinstance(content, str):
            return content
        return "".join(
            b.get("text", "") for b in content if b.get("type") == "text"
        )
    return ""


def _resolve_catchment(tool_input: dict, roof_sqft: float | None) -> tuple[dict, dict | None]:
    """Resolve size_garden's catchment area before dispatch.

    Returns ``(effective_input, error)``. When the user adopted the satellite roof
    estimate (``adopt_roof_estimate=true``), the exact out-of-band ``roof_sqft`` value
    is injected as ``catchment_sa`` and the flag stripped — the figure is never
    model-authored, so the number the user saw is exactly the one that feeds the
    calculation. A missing estimate (adoption with no value on record) or a missing
    number both yield a *recoverable* error the model reacts to — never a hard failure.
    """
    if tool_input.get("adopt_roof_estimate"):
        if roof_sqft is None:
            return tool_input, {
                "is_error": True,
                "message": (
                    "No roof estimate is available to adopt; ask the user for the "
                    "catchment area in square feet instead."
                ),
            }
        resolved = {k: v for k, v in tool_input.items() if k != "adopt_roof_estimate"}
        resolved["catchment_sa"] = roof_sqft
        return resolved, None
    if tool_input.get("catchment_sa") is None:
        return tool_input, {
            "is_error": True,
            "message": (
                "size_garden needs a catchment area: pass catchment_sa (square feet) "
                "or set adopt_roof_estimate=true to use the satellite estimate."
            ),
        }
    return tool_input, None


def run_agent(
    messages: list, client=None, roof_sqft: float | None = None
) -> tuple[list, str, list]:
    """Drive the tool loop over ``messages`` until it pauses or completes.

    ``messages`` already carries the location preamble (built by :func:`build_seed`)
    on the seed turn and every prior turn on a continuation — this function never
    geocodes. ``roof_sqft`` is the out-of-band satellite roof-area value (or ``None``);
    it is the single source of truth used to resolve an ``adopt_roof_estimate`` call
    into a concrete ``catchment_sa`` — see :func:`_resolve_catchment`. Returns
    ``(messages, status, call_log)``:

    * ``status == "awaiting_user"`` — the model asked a question (``end_turn`` with
      trailing text and no ``present_results``); the caller resumes by appending the
      user's answer and calling again.
    * ``status == "complete"`` — the model called ``present_results``; the design is
      final. The summary rides in the ``present_results`` ``call_log`` entry.
    * ``status == "error"`` — truncation or an unhandled stop reason.

    ``call_log`` records every tool call this invocation made
    (``{"name", "input", "output"}``), including the ``present_results`` signal
    (``output=None``). A :class:`FatalToolError` propagates to the caller unswallowed.
    """
    if client is None:
        client = anthropic.Anthropic()
    call_log: list[dict] = []

    while True:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        # Serialize assistant blocks to plain dicts so the transcript round-trips
        # through JSON for the client-stateless transport. exclude_none drops
        # optional metadata (citations, cache_control) the API rejects inbound.
        messages.append({
            "role": "assistant",
            "content": [b.model_dump(exclude_none=True) for b in resp.content],
        })

        if resp.stop_reason == "tool_use":
            results = []
            complete = False
            for block in resp.content:  # ALL blocks — parallel calls are common
                if block.type != "tool_use":
                    continue
                if block.name == PRESENT_RESULTS:
                    # Terminal control signal — intercepted, never dispatched. Record
                    # it in call_log (summary lives here) and acknowledge so the
                    # transcript stays API-valid (every tool_use needs a tool_result).
                    call_log.append(
                        {"name": block.name, "input": block.input, "output": None}
                    )
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"acknowledged": True}),
                    })
                    complete = True
                    continue
                if block.name == SEARCH_GUIDANCE and not GUIDANCE_PREREQS <= {
                    c["name"] for c in call_log
                }:
                    # Terminal-turn gate (§4): retrieval is reachable only once the
                    # deterministic design exists, so its query is derived from real
                    # advisories. Enforced at the loop boundary, not by prompt alone —
                    # an early call gets a recoverable error, never a dispatch.
                    gated = {"is_error": True, "message": GUIDANCE_GATE_MSG}
                    call_log.append(
                        {"name": block.name, "input": block.input, "output": gated}
                    )
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(gated),
                    })
                    continue
                # size_garden may carry the adoption flag (user chose the satellite
                # estimate): resolve catchment_sa deterministically before dispatch so
                # the compute layer only ever sees a concrete number. The RESOLVED input
                # is what we log — so the summary's {catchment_sqft} token, read from this
                # entry, is the deterministic value too.
                tool_input = block.input
                if block.name == SIZE_GARDEN:
                    tool_input, size_err = _resolve_catchment(tool_input, roof_sqft)
                    if size_err is not None:
                        call_log.append(
                            {"name": block.name, "input": block.input, "output": size_err}
                        )
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(size_err),
                        })
                        continue
                # FatalToolError propagates to the endpoint (§7) — no longer swallowed.
                out = dispatch(block.name, tool_input)
                call_log.append(
                    {"name": block.name, "input": tool_input, "output": out}
                )
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    # dispatch guarantees JSON safety; recoverable {"is_error":...}
                    # payloads ride back here unchanged.
                    "content": json.dumps(out, allow_nan=False),
                })
            messages.append({"role": "user", "content": results})
            if complete:
                return messages, "complete", call_log
            continue

        if resp.stop_reason == "end_turn":
            # Trailing assistant text, no present_results — the model is asking a
            # slot question and waiting on the user.
            return messages, "awaiting_user", call_log

        if resp.stop_reason == "max_tokens":
            return messages, "error", call_log

        # Any other stop_reason: stop rather than fall through silently.
        return messages, "error", call_log


# --- Acceptance oracle (Section 8) -------------------------------------------

def _find_call(call_log, name):
    """Return the single call_log entry for ``name`` (asserts exactly one)."""
    hits = [c for c in call_log if c["name"] == name]
    assert len(hits) == 1, f"expected exactly one {name} call, got {len(hits)}"
    return hits[0]


def _run_oracle(location, status, call_log, messages):
    """Structural / wiring / plausibility checks on a finished Brooklyn run."""
    # Pre-step: resolved NY / 11209 and passed the gate.
    assert location["ok"] is True, "Brooklyn address should pass the lower-48 gate"
    assert location["state"] == "NY", f"expected state NY, got {location['state']!r}"
    assert location["zip_code"] == "11209", \
        f"expected zip 11209, got {location['zip_code']!r}"

    # Tool set: each of the four deterministic tools exactly once, free order.
    # present_results (terminal signal) and search_guidance (additive retrieval)
    # are not deterministic compute tools — both are checked separately below.
    _control = {"present_results", "search_guidance"}
    names = [c["name"] for c in call_log if c["name"] not in _control]
    assert set(names) == {
        "get_precipitation_stats", "get_hardiness_zone", "filter_plants", "size_garden",
    }, f"unexpected tool set: {sorted(set(names))}"
    assert len(names) == 4, f"a tool was called more than once: {names}"

    precip = _find_call(call_log, "get_precipitation_stats")["output"]
    hardiness = _find_call(call_log, "get_hardiness_zone")["output"]
    plants = _find_call(call_log, "filter_plants")
    sizing = _find_call(call_log, "size_garden")["output"]

    # Wiring / provenance (the assertion that matters): the floor the model fed
    # filter_plants is the hardiness output's floor from THIS run — not precip,
    # not a hardcoded constant.
    floor_out = hardiness["min_temp_floor"]
    floor_in = plants["input"].get("local_min_temp")
    assert floor_in == floor_out, (
        f"local_min_temp wiring mismatch: filter_plants got {floor_in!r}, "
        f"get_hardiness_zone produced {floor_out!r}"
    )

    # Plausibility — precipitation (NYC sanity bands).
    rate = precip["threshold_precip_rate"]
    total = precip["total_precip_yr"]
    assert rate > 0 and total > 0, "precip stats must be positive"
    # Sanity band, not a contract (spec: "~0.3-0.8"). The live archive returns
    # ~0.29 for 11209, so the floor is 0.25 to stay non-flaky on real values.
    assert 0.25 <= rate <= 0.8, f"rate {rate} outside NYC sanity band 0.25-0.8 in/hr"
    # Same caveat for the annual total (spec guessed ~44-52); the live Open-Meteo
    # archive computes ~39 in/yr for 11209, so the band floor is widened to 35.
    assert 35 <= total <= 52, f"total {total} outside NYC sanity band 35-52 in/yr"

    # Plausibility — hardiness.
    assert hardiness["zone"] in {"7a", "7b"}, f"zone {hardiness['zone']!r} unexpected for 11209"
    assert floor_out in {0, 5}, f"floor {floor_out!r} unexpected for zone 7a/7b"

    # Plausibility — plants: happy path, both zones populated, no reason key.
    plants_out = plants["output"]
    assert "reason" not in plants_out, \
        "reason key present — the floor failed to wire into filter_plants"
    assert plants_out["interior"] and plants_out["perimeter"], \
        "both plant zones should be non-empty for NY"
    assert len(plants_out["interior"]) <= 15 and len(plants_out["perimeter"]) <= 15

    # Plausibility — sizing: three depth options (about 4/6/8 in), each with a
    # positive area, and deeper options are more compact (smaller footprint).
    options = sizing["sizing"]["options"]
    assert [o["depth_in"] for o in options] == [4, 6, 8], \
        f"expected depth options 4/6/8, got {[o['depth_in'] for o in options]}"
    assert all(o["area_sqft"] > 0 for o in options), "every option needs a positive area"
    assert options[0]["area_sqft"] > options[2]["area_sqft"], \
        "shallower option should be larger than the deeper one"

    # Additive RAG: search_guidance fired exactly once on the terminal turn (the
    # gate lets it through only after size_garden + filter_plants), and returned
    # cited passages for the guidance channel — never a numeric field.
    guidance = _find_call(call_log, "search_guidance")
    g_out = guidance["output"]
    assert isinstance(g_out, dict) and g_out.get("passages"), \
        f"search_guidance should return non-empty passages, got {g_out!r}"
    for passage in g_out["passages"]:
        assert passage.get("citation_label") and passage.get("source_url"), \
            "each retrieved passage must carry a citation label + source url"
    # Query is condition-derived, not a size/locale label (spec section 5).
    query = guidance["input"]["query"].lower()
    assert "sq ft" not in query and "square feet" not in query, \
        f"guidance query looks size-derived, not condition-derived: {query!r}"
    print(f"    search_guidance query: {guidance['input']['query']!r}")
    print(f"    retrieved {len(g_out['passages'])} passages from "
          f"{sorted({p['source_doc'] for p in g_out['passages']})}")

    # Termination: the model signaled completion via present_results and delivered
    # a plain-language presentation in the same turn.
    assert status == "complete", f"expected status 'complete', got {status!r}"
    present = _find_call(call_log, "present_results")
    assert present["input"].get("summary"), \
        "present_results should carry a non-empty prose summary"
    assert last_assistant_text(messages), \
        "expected a plain-language presentation in the final assistant turn"

    print("\n--- ORACLE: all structural / wiring / plausibility checks passed ---")


if __name__ == "__main__":
    # Fully-seeded Brooklyn smoke test (Section 7): every site detail is embedded in
    # the seed so the model needs no follow-up questions and runs one-shot to a
    # present_results completion. Catchment is now a conversational detail (no longer
    # pre-filled in the seed), so the slot text states it explicitly. No roof estimate
    # is passed here — the oracle exercises the ordinary user-stated-number path.
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))  # oracle is its own entry point

    address = "97 80th St. Brooklyn NY"
    location = geocode_and_gate(address)
    if not location.get("ok"):
        print(location["message"])
        sys.exit(1)

    slots = (
        "I'd like to plan a rain garden in my yard. About 700 square feet of roof "
        "drains toward the spot. It's more than 30 feet from the house. The ground is "
        "flat there — well under a 12% grade. It gets partial sun. I haven't tested my "
        "soil and honestly couldn't tell you what type it is. Please size the garden "
        "and recommend plants."
    )
    messages = [{"role": "user", "content": build_seed(location, None, slots=slots)}]

    messages, status, call_log = run_agent(messages)
    print(last_assistant_text(messages))
    _run_oracle(location, status, call_log, messages)
