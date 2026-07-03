"""Wiring tests for the roof-estimate feature (no network).

Covers the pieces the module test (test_roofarea.py) does not: the redaction
guarantee in the seed, deterministic adoption resolution in the agent loop, the
question-turn ``{roof_sqft}`` substitution, and the results-card advisory. The
security-critical invariant under test throughout: the raw roof digit is never in
the model's context and is never model-authored.
"""

import os

# app.py constructs an Anthropic client at import; give it a dummy key so the
# import succeeds offline (load_dotenv won't override an already-set var).
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")

import agent  # noqa: E402
import app  # noqa: E402
from agent import _resolve_catchment  # noqa: E402
from tools import (  # noqa: E402
    ROOF_ESTIMATE_AVAILABLE,
    ROOF_ESTIMATE_UNAVAILABLE,
    build_seed,
)

LOCATION = {
    "address": "97 80th St, Brooklyn, NY",
    "state": "NY",
    "zip_code": "11209",
    "lat": 40.6236,
    "lon": -74.0299,
}


# --- fake Anthropic response scaffolding (mirrors test_search_guidance) --------

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
    def __init__(self, responses):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs):
        return self._responses.pop(0)


def _tu(name, inp, id):
    return FakeBlock("tool_use", name=name, input=inp, id=id)


# --- build_seed: availability only, digit redacted ----------------------------

def test_seed_marks_available_without_leaking_digit():
    seed = build_seed(LOCATION, {"roof_sqft": 1730, "imagery_date": "2022-08-15"})
    assert ROOF_ESTIMATE_AVAILABLE in seed
    # The redaction guarantee: the raw number never enters the model's context.
    assert "1730" not in seed
    assert "2022-08-15" not in seed


def test_seed_marks_unavailable_when_no_estimate():
    seed = build_seed(LOCATION, None)
    assert ROOF_ESTIMATE_UNAVAILABLE in seed


# --- _resolve_catchment: deterministic adoption -------------------------------

def test_adoption_injects_exact_value_and_strips_flag():
    inp = {"adopt_roof_estimate": True, "soil_type": "Clayey"}
    resolved, err = _resolve_catchment(inp, roof_sqft=1730)
    assert err is None
    assert resolved["catchment_sa"] == 1730          # exact value, server-injected
    assert "adopt_roof_estimate" not in resolved     # flag consumed before dispatch


def test_adoption_without_estimate_is_recoverable_error():
    inp = {"adopt_roof_estimate": True}
    resolved, err = _resolve_catchment(inp, roof_sqft=None)
    assert err is not None and err["is_error"] is True
    assert "catchment_sa" not in resolved            # nothing fabricated


def test_normal_number_passes_through_unchanged():
    inp = {"catchment_sa": 700, "soil_type": "Silty"}
    resolved, err = _resolve_catchment(inp, roof_sqft=1730)
    assert err is None
    assert resolved == inp                            # normal path untouched by roof value


def test_missing_catchment_and_no_flag_is_recoverable_error():
    resolved, err = _resolve_catchment({"soil_type": "Silty"}, roof_sqft=1730)
    assert err is not None and err["is_error"] is True


# --- run_agent: adoption end to end -------------------------------------------

def test_run_agent_sizes_on_injected_estimate():
    client = FakeClient([
        FakeResp([
            _tu("size_garden", {"adopt_roof_estimate": True, "soil_type": "Clayey"}, "a1"),
            _tu("filter_plants", {"state": "NY", "local_min_temp": 5}, "a2"),
        ], "tool_use"),
        FakeResp([
            FakeBlock("text", text="Here is your design."),
            _tu("present_results", {"summary": "All set."}, "a3"),
        ], "tool_use"),
    ])
    _, status, call_log = agent.run_agent(
        [{"role": "user", "content": "hi"}], client=client, roof_sqft=1730
    )
    assert status == "complete"
    sizing = next(c for c in call_log if c["name"] == "size_garden")
    # The logged input carries the deterministic value (so {catchment_sqft} resolves
    # to it too), and a real design was computed from it.
    assert sizing["input"]["catchment_sa"] == 1730
    assert "adopt_roof_estimate" not in sizing["input"]
    assert sizing["output"]["design"]["area_sqft"] > 0


def test_run_agent_adoption_without_estimate_does_not_crash():
    client = FakeClient([
        FakeResp([
            _tu("size_garden", {"adopt_roof_estimate": True}, "a1"),
        ], "tool_use"),
        FakeResp([FakeBlock("text", text="What's the catchment area?")], "end_turn"),
    ])
    _, status, call_log = agent.run_agent(
        [{"role": "user", "content": "hi"}], client=client, roof_sqft=None
    )
    assert status == "awaiting_user"                  # recoverable, never a hard failure
    sizing = next(c for c in call_log if c["name"] == "size_garden")
    assert sizing["output"]["is_error"] is True


# --- _resolve_roof: deterministic display substitution ------------------------

def test_resolve_roof_substitutes_exact_value():
    out = app._resolve_roof("Your roof is about {roof_sqft} sq ft.", 1730)
    assert out == "Your roof is about 1730 sq ft."
    assert "{roof_sqft}" not in out


def test_resolve_roof_noop_without_token():
    text = "Roughly how many square feet drain into this spot?"
    assert app._resolve_roof(text, 1730) == text


def test_resolve_roof_drops_orphan_token_never_shows_brace():
    # Defensive: token present but no value on record (e.g. client dropped the field).
    out = app._resolve_roof(
        "Great question. Your roof is about {roof_sqft} sq ft. What drains here?", None
    )
    assert "{roof_sqft}" not in out
    assert "1730" not in out
    assert "What drains here?" in out                 # surrounding sentences survive


# --- results-card advisory ----------------------------------------------------

def test_advisory_available_detection():
    seed_available = build_seed(LOCATION, {"roof_sqft": 1730})
    seed_none = build_seed(LOCATION, None)
    assert app._roof_estimate_available([{"role": "user", "content": seed_available}])
    assert not app._roof_estimate_available([{"role": "user", "content": seed_none}])
    assert not app._roof_estimate_available([])


# --- integrated /chat: available seed path (offline) --------------------------
# geocode + roof estimate + Anthropic client are all stubbed so no network is hit;
# this exercises the real handler: seed resolution -> question-turn substitution ->
# out-of-band roof_sqft echo.

def test_chat_seed_available_path(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(app, "geocode_and_gate", lambda addr: {"ok": True, **LOCATION})
    monkeypatch.setattr(
        app, "estimate_roof_area",
        lambda lat, lon: {"roof_sqft": 1730, "imagery_date": "2022-08-15"},
    )
    monkeypatch.setattr(app, "_client", FakeClient([
        FakeResp([FakeBlock("text", text=(
            "Roughly how many square feet drain into this spot? Satellite imagery puts "
            "your whole roof near {roof_sqft} sq ft."
        ))], "end_turn"),
    ]))

    r = TestClient(app.app).post("/chat", json={"address": "97 80th St, Brooklyn NY"}).json()
    assert r["status"] == "awaiting_user"
    assert r["roof_sqft"] == 1730                      # exact value echoed out of band
    assert "1730" in r["assistant_message"]            # deterministically substituted
    assert "{roof_sqft}" not in r["assistant_message"]  # token never shown raw
