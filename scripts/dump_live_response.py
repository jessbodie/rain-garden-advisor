"""Live end-to-end run to inspect whether the REAL model tokenizes the summary.

Unlike ``dump_complete_response.py`` (which stubs the Anthropic client and
hardcodes the summary), this drives the actual agent loop against the live
Anthropic model and the live geocode / precipitation / hardiness / retrieval
services, then shows what the model *actually wrote* for
``present_results.summary`` BEFORE substitution — so you can verify it emitted
``{tokens}`` and no bare digits.

It makes real, billed API calls and hits the network. Requires ANTHROPIC_API_KEY
and RAPIDAPI_KEY in .env.

The site is fully seeded (address + every site detail, incl. a measured perc
rate) so the model needs no follow-up questions and runs straight to a
``present_results`` completion — and so that drainage time AND gallons are both
non-null, exercising every dimension token.

Usage (from repo root, with the project venv):
    python scripts/dump_live_response.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))  # real keys, before the client is built

import app  # noqa: E402  — constructs the real Anthropic client at import
from agent import last_assistant_text, run_agent  # noqa: E402
from tools import build_seed, geocode_and_gate  # noqa: E402

ADDRESS = "97 80th St. Brooklyn NY"
CATCHMENT_SA = 700
SLOTS = (
    "I'd like to plan a rain garden. It's more than 30 feet from the house, on "
    "flat ground well under a 12% grade, and the ground slopes away from the "
    "house. It gets partial sun. The soil is loamy — crumbly and drains well. I "
    "measured the percolation rate at about 1 inch per hour. Please size the "
    "garden and recommend plants."
)

_TOKEN_RE = re.compile(r"\{(\w+)\}")


def main() -> None:
    location = geocode_and_gate(ADDRESS)
    if not location.get("ok"):
        print(f"Geocode/gate failed: {location.get('message')}")
        sys.exit(1)

    messages = [{"role": "user", "content": build_seed(location, CATCHMENT_SA, slots=SLOTS)}]
    messages, status, call_log = run_agent(messages, client=app._client)

    print(f"=== status: {status} ===\n")
    if status != "complete":
        print("Did not reach completion (the model likely asked a follow-up):\n")
        print(last_assistant_text(messages))
        sys.exit(0)

    present = next((c for c in call_log if c["name"] == "present_results"), None)
    raw = present["input"].get("summary") if present else None

    print("--- RAW summary AS AUTHORED BY THE MODEL (pre-substitution) ---")
    print(raw)
    print()

    tokens = _TOKEN_RE.findall(raw or "")
    stripped = _TOKEN_RE.sub("", raw or "")
    bare_digits = [ch for ch in stripped if ch.isdigit()]
    print(f"tokens the model emitted   : {tokens or '(none)'}")
    print(f"incidental digits in prose : {''.join(bare_digits) or '(none)'} "
          f"(left as written — there is no digit guard)")
    if tokens:
        print("VERDICT: model tokenized its garden values.\n")
    else:
        print("VERDICT: model wrote NO garden-value tokens.\n")

    # What the user actually receives, after deterministic substitution.
    results = app._assemble_results(call_log)
    print("--- FINAL results.summary (after substitution) ---")
    print(results["summary"])
    print()

    # Did substitution keep the model's prose, or discard it for the template?
    sizing = next((c for c in call_log if c["name"] == "size_garden"), None)
    if sizing:
        fallback = app._fallback_summary(app._substitutions(sizing))
        used = "fallback template" if results["summary"] == fallback else "model's summary"
        print(f"rendered via: {used}")

    print("\n--- assistant presentation text (user-facing) ---")
    print(last_assistant_text(messages))


if __name__ == "__main__":
    main()
