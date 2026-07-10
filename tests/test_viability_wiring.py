"""Wiring tests for the viability terminal flow (no network).

Covers what the deterministic oracle (test_viability.py) does not: the
conclude_without_plan terminal intercept in the agent loop, and the /chat
`outcome` discriminator (plan / plan_not_recommended / declined). The load-bearing
invariant under test: the terminal outcome is derived from call_log, never from a
transcript scan (spec §10-D), and the decline path returns NO results (§7.5 State B).
"""

import os

# app.py builds an Anthropic client at import; give it a dummy key for offline import.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")

import agent  # noqa: E402
import app  # noqa: E402
from app import _is_declined  # noqa: E402

LOCATION = {
    "address": "97 80th St, Brooklyn, NY",
    "state": "NY",
    "zip_code": "11209",
    "lat": 40.6236,
    "lon": -74.0299,
}


# --- fake Anthropic response scaffolding (mirrors test_roof_estimate) ----------

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


# --- _is_declined: call-log-keyed, not transcript-scanned ---------------------

def test_is_declined_reads_call_log():
    assert _is_declined([{"name": "conclude_without_plan", "input": {}, "output": None}])
    assert not _is_declined([{"name": "present_results", "input": {}, "output": None}])
    assert not _is_declined([])


# --- run_agent: conclude_without_plan is a terminal signal, never dispatched ---

def test_conclude_without_plan_is_terminal_and_logged():
    client = FakeClient([
        FakeResp([
            FakeBlock("text", text="Given the foundation risk, I won't design one here."),
            _tu("conclude_without_plan", {"reason": "under 10 ft from the foundation"}, "c1"),
        ], "tool_use"),
    ])
    messages, status, call_log = agent.run_agent(
        [{"role": "user", "content": "hi"}], client=client
    )
    assert status == "complete"
    decline = [c for c in call_log if c["name"] == "conclude_without_plan"]
    assert len(decline) == 1
    assert decline[0]["output"] is None          # terminal signal, not dispatched
    assert decline[0]["input"]["reason"]
    # The decline path never sizes a garden.
    assert not any(c["name"] == "size_garden" for c in call_log)


def test_conclude_without_plan_not_routed_to_dispatch():
    # A bare terminal turn: no compute tools, just the decline signal + closing text.
    client = FakeClient([
        FakeResp([
            FakeBlock("text", text="Understood — take care."),
            _tu("conclude_without_plan", {"reason": "slope too steep"}, "c1"),
        ], "tool_use"),
    ])
    _, status, call_log = agent.run_agent([{"role": "user", "content": "hi"}], client=client)
    assert status == "complete"
    assert [c["name"] for c in call_log] == ["conclude_without_plan"]


# --- /chat outcome discriminator (offline: geocode/roof/client all stubbed) ----

def _seed_chat(monkeypatch, responses, roof=None):
    """Drive a fresh /chat seed request with a stubbed client + geocode + roof."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(app, "geocode_and_gate", lambda addr: {"ok": True, **LOCATION})
    monkeypatch.setattr(app, "estimate_roof_area", lambda lat, lon: roof)
    monkeypatch.setattr(app, "_client", FakeClient(responses))
    return TestClient(app.app).post("/chat", json={"address": "97 80th St, Brooklyn NY"}).json()


def test_chat_outcome_declined_has_no_results(monkeypatch):
    r = _seed_chat(monkeypatch, [
        FakeResp([
            FakeBlock("text", text="I won't design one this close to the house."),
            _tu("conclude_without_plan", {"reason": "under 10 ft from the foundation"}, "c1"),
        ], "tool_use"),
    ])
    assert r["status"] == "complete"
    assert r["outcome"] == "declined"
    assert r["results"] is None                  # §7.5 State B: no plan object
    assert "design" in r["assistant_message"].lower()


def test_chat_outcome_plan_recommended(monkeypatch):
    r = _seed_chat(monkeypatch, [
        FakeResp([
            _tu("size_garden", {
                "catchment_sa": 700, "soil_type": "Silty",
                "distance": "More than 30 ft", "slope_ok": True}, "s1"),
            _tu("filter_plants", {"state": "NY", "local_min_temp": 5}, "f1"),
        ], "tool_use"),
        FakeResp([
            FakeBlock("text", text="Your rain garden plan is ready."),
            _tu("present_results", {"summary": "Your plan is ready."}, "p1"),
        ], "tool_use"),
    ])
    assert r["status"] == "complete"
    assert r["outcome"] == "plan"
    assert r["results"]["recommended"] is True


def test_chat_outcome_plan_not_recommended_on_override(monkeypatch):
    # State A: the user overrode a foundation-setback blocker. A plan comes back, but
    # marked not recommended, and the outcome routes to the not-recommended layout.
    r = _seed_chat(monkeypatch, [
        FakeResp([
            _tu("size_garden", {
                "catchment_sa": 700, "soil_type": "Silty",
                "distance": "Less than 10 ft", "slope_ok": True}, "s1"),
            _tu("filter_plants", {"state": "NY", "local_min_temp": 5}, "f1"),
        ], "tool_use"),
        FakeResp([
            FakeBlock("text", text="Here's the plan, though I don't recommend this spot."),
            _tu("present_results", {"summary": "Plan ready; not recommended."}, "p1"),
        ], "tool_use"),
    ])
    assert r["status"] == "complete"
    assert r["outcome"] == "plan_not_recommended"
    assert r["results"]["recommended"] is False
    # The blocker is carried into the results for the not-recommended render.
    assert any(a["type"] == "foundation_setback" for a in r["results"]["advisories"])
