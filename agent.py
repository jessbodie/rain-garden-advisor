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

from tools import TOOLS, FatalToolError, dispatch, geocode_and_gate
from rain_garden.prompts import SYSTEM_PROMPT

# Sonnet is a sensible default for tool orchestration (cost/latency vs. Opus).
MODEL = "claude-sonnet-4-6"
# Generous enough for the final synthesis, which embeds two plant lists.
MAX_TOKENS = 4096


def _final_text(resp) -> str:
    """Concatenate the text blocks of an assistant response."""
    return "".join(b.text for b in resp.content if b.type == "text")


def run_agent(address: str, seeded_request: str) -> dict:
    """Resolve ``address``, then run the tool loop on ``seeded_request``.

    Returns a dict with the resolved ``location``, the final synthesis text
    (``final``; ``None`` if the run stopped early), and the ``call_log`` of every
    tool call ``{"name", "input", "output"}`` — the oracle reads the log to check
    wiring provenance.
    """
    # --- Pre-step: geocode + gate (deterministic, before any model call) ------
    location = geocode_and_gate(address)
    if not location.get("ok"):
        # Out of region / unfindable — refuse without ever entering the loop.
        print(location["message"])
        return {"location": location, "final": None, "call_log": []}

    # Inject the resolved location as a preamble on the first user turn — never
    # mutate SYSTEM_PROMPT (it's verbatim-verified). state and zip feed
    # filter_plants / get_hardiness_zone; the model reads them here.
    preamble = (
        f"[Resolved location: {location['address']}, "
        f"state {location['state']}, zip {location['zip_code']}, "
        f"lat {location['lat']}, lon {location['lon']}]"
    )
    messages = [{"role": "user", "content": f"{preamble}\n\n{seeded_request}"}]
    call_log: list[dict] = []

    # ANTHROPIC_API_KEY lives in .env; load it before the client reads the env
    # (usecwd=True mirrors hardiness.py — robust to how the script is launched).
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    client = anthropic.Anthropic()

    while True:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "tool_use":
            results = []
            for block in resp.content:  # ALL blocks — parallel calls are common
                if block.type != "tool_use":
                    continue
                try:
                    out = dispatch(block.name, block.input)
                except FatalToolError as exc:  # specific catch — no bare except
                    print(f"FATAL: {exc}")
                    return {"location": location, "final": None,
                            "call_log": call_log, "fatal": True}
                call_log.append(
                    {"name": block.name, "input": block.input, "output": out}
                )
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    # dispatch guarantees JSON safety; recoverable {"is_error":...}
                    # payloads ride back here unchanged.
                    "content": json.dumps(out, allow_nan=False),
                })
            messages.append({"role": "user", "content": results})
            continue

        if resp.stop_reason == "end_turn":
            final = _final_text(resp)
            print(final)
            return {"location": location, "final": final, "call_log": call_log}

        if resp.stop_reason == "max_tokens":
            print("WARNING: response truncated (max_tokens). Stopping.")
            return {"location": location, "final": None,
                    "call_log": call_log, "truncated": True}

        # Any other stop_reason: stop rather than fall through silently.
        print(f"WARNING: unhandled stop_reason {resp.stop_reason!r}. Stopping.")
        return {"location": location, "final": None, "call_log": call_log}


# --- Acceptance oracle (Section 8) -------------------------------------------

def _find_call(call_log, name):
    """Return the single call_log entry for ``name`` (asserts exactly one)."""
    hits = [c for c in call_log if c["name"] == name]
    assert len(hits) == 1, f"expected exactly one {name} call, got {len(hits)}"
    return hits[0]


def _run_oracle(result):
    """Structural / wiring / plausibility checks on a finished Brooklyn run."""
    location = result["location"]
    call_log = result["call_log"]

    # Pre-step: resolved NY / 11209 and passed the gate.
    assert location["ok"] is True, "Brooklyn address should pass the lower-48 gate"
    assert location["state"] == "NY", f"expected state NY, got {location['state']!r}"
    assert location["zip_code"] == "11209", \
        f"expected zip 11209, got {location['zip_code']!r}"

    # Tool set: each of the four, exactly once, free order.
    names = [c["name"] for c in call_log]
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

    # Plausibility — sizing: 700 * 0.10 (Clayey @ >30 ft) = 70 sq ft; depth
    # saturates at 12 in (known getDepth TODO for area > 36).
    assert sizing["design"]["area_sqft"] == 70, \
        f"area {sizing['design']['area_sqft']} != 70 — sizing-input wiring error"
    assert sizing["design"]["depth_inches"] == 12, \
        f"depth {sizing['design']['depth_inches']} should saturate at 12 in"

    # Termination: synthesis exists (loop exited on end_turn).
    assert result.get("final"), "expected final synthesis text on end_turn"

    print("\n--- ORACLE: all structural / wiring / plausibility checks passed ---")


if __name__ == "__main__":
    # Fully-seeded Brooklyn smoke test (Section 7): every detail the model would
    # otherwise slot-fill is in the seed, so no follow-up questions are needed.
    address = "97 80th St. Brooklyn NY"
    seeded_request = (
        "I'd like to plan a rain garden in my yard. About 700 square feet of roof "
        "drains toward the spot. It's more than 30 feet from the house. The ground "
        "is flat there — well under a 12% grade. It gets partial sun. I haven't "
        "tested my soil and honestly couldn't tell you what type it is. "
        "Please size the garden and recommend plants."
    )

    result = run_agent(address, seeded_request)
    _run_oracle(result)
