"""Print the raw JSON of one full complete-path ``POST /chat`` response.

A frontend-design aid, NOT part of the request path. Drives the real FastAPI
endpoint through a full happy-path run and prints the exact ``ChatResponse``
JSON a browser would receive on ``status: "complete"`` — so you can see the
response shape without babysitting uvicorn + /docs.

Fully offline and deterministic. Everything that would touch the network or the
LLM is stubbed:
  * the Anthropic client is a scripted ``FakeClient`` (no API key, no tokens);
  * geocode / precipitation / hardiness / retrieval are monkeypatched;
  * ``size_garden`` and ``filter_plants`` run FOR REAL against packaged data,
    so the ``results`` payload is faithful to a live complete run.

Because it never calls out, it also never spends money and can't flake.

Usage (from repo root, with the project venv):
    python scripts/dump_complete_response.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# The app modules (app.py, agent.py, tools.py) live at the repo root. When this
# script is run as ``python scripts/dump_complete_response.py`` only the scripts/
# dir lands on sys.path, so add the repo root. (rain_garden itself resolves via
# the editable install's .pth — no need to add src/.)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# app.py builds an Anthropic client at import; a dummy key lets the import
# succeed offline (it's never used — the client is replaced below).
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")

# Windows cp1252 consoles raise UnicodeEncodeError on the em-dashes in the
# advisory/guidance text; make stdout tolerant rather than lose output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import app  # noqa: E402
import tools  # noqa: E402
import rain_garden.retrieval as retrieval  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from tools import SEARCH_GUIDANCE  # noqa: E402


# --- fake Anthropic scaffolding (mirrors tests/test_search_guidance.py) -------

class FakeBlock:
    def __init__(self, type, name=None, input=None, id=None, text=None):
        self.type = type
        self.name = name
        self.input = input or {}
        self.id = id or "tid"
        self.text = text

    def model_dump(self, exclude_none=False):
        d = {"type": self.type}
        if self.type == "tool_use":
            d.update(name=self.name, input=self.input, id=self.id)
        if self.type == "text":
            d["text"] = self.text
        return d


class FakeResp:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class FakeClient:
    """Pops scripted responses in order; stands in for client.messages.create."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs):
        return self._responses.pop(0)


def tu(name, inp, id):
    return FakeBlock("tool_use", name=name, input=inp, id=id)


# --- offline stubs for the network-backed seams -------------------------------

tools.geocode_address = lambda addr: {
    "address": "Brooklyn, NY, USA", "lat": 40.6236, "lon": -74.0299,
    "zip_code": "11209", "state": "NY",
}
tools.get_precipitation_stats = lambda lat, lon: {
    "threshold_precip_rate": 0.29, "total_precip_yr": 39.4,
    "min_apparent_temp": -11.8,
}
tools.get_hardiness_zone = lambda zip_code: {
    "zone": "7b", "min_temp_range": "5 to 10", "zip_code": zip_code,
}
retrieval.search = lambda q, **k: [
    {
        "text": "Amend clayey soils with several inches of compost before "
                "planting so the basin can drain within 24 to 48 hours.",
        "source_doc": "epa_soak_up_the_rain",
        "source_url": "https://www.epa.gov/soakuptherain",
        "citation_label": "EPA — Soak Up the Rain",
        "page": 4, "score": 0.83,
    },
    {
        "text": "Build a shallow overflow outlet at the low edge so heavy storms "
                "spill away from the house foundation.",
        "source_doc": "epa_soak_up_the_rain",
        "source_url": "https://www.epa.gov/soakuptherain",
        "citation_label": "EPA — Soak Up the Rain",
        "page": 6, "score": 0.79,
    },
]

# Scripted model run: precip+hardiness -> size+plants -> guidance -> present.
app._client = FakeClient([
    FakeResp([
        tu("get_precipitation_stats", {"lat": 40.6236, "lon": -74.0299}, "t1"),
        tu("get_hardiness_zone", {"zip_code": "11209"}, "t2"),
    ], "tool_use"),
    FakeResp([
        tu("size_garden",
           {"catchment_sa": 700, "distance": "More than 30 ft", "slope_ok": True},
           "t3"),
        tu("filter_plants", {"state": "NY", "local_min_temp": 5}, "t4"),
    ], "tool_use"),
    FakeResp([
        tu(SEARCH_GUIDANCE, {"query": "amend clay soil drainage overflow outlet"}, "t5"),
    ], "tool_use"),
    FakeResp([
        FakeBlock("text", text=(
            "Here's your rain garden plan for Brooklyn (zone 7b). Based on ~700 sq "
            "ft of drainage and unknown soil, I've sized a 70 sq ft basin and "
            "picked NY-hardy plants for the wet interior and drier perimeter.")),
        # Summary is authored with tokens (no bare digits): _assemble_results
        # injects the deterministic values, exercising the happy token path rather
        # than the digit-guard fallback.
        tu("present_results", {"summary": (
            "A {area_sqft} sq ft rain garden, {depth_inches} in deep, for your "
            "{catchment_sqft} sq ft catchment. The interior and perimeter plant "
            "lists are matched to your hardiness zone. Amend the clay-leaning soil "
            "with compost and add an overflow outlet that directs water away from "
            "the house.")}, "t6"),
    ], "tool_use"),
])


def main() -> None:
    client = TestClient(app.app)
    # catchment_sa is no longer a seed field (it's gathered conversationally); the
    # scripted FakeClient drives size_garden directly, so the seed needs only the address.
    resp = client.post("/chat", json={"address": "97 80th St, Brooklyn NY"})
    print(f"HTTP {resp.status_code}\n")
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
