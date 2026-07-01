"""Tests for the search_guidance tool: dispatch, terminal-turn gate, and the
disjoint guidance channel in results assembly. No network.

Retrieval is monkeypatched to a canned result so these exercise the wiring (gate
+ dispatch + assembly), not the ONNX model — that is covered in test_retrieval.py.
"""

import os

# app.py constructs an Anthropic client at import; give it a dummy key so the
# import succeeds offline (load_dotenv won't override an already-set var).
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")

import agent  # noqa: E402
import app  # noqa: E402
from tools import SEARCH_GUIDANCE  # noqa: E402


# --- fake Anthropic response scaffolding -------------------------------------

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


def _tool_use(name, inp, id):
    return FakeBlock("tool_use", name=name, input=inp, id=id)


# --- terminal-turn gate -------------------------------------------------------

def test_search_guidance_gated_before_compute(monkeypatch):
    """Called before size_garden+filter_plants -> recoverable error, never dispatched."""
    calls = {"n": 0}
    monkeypatch.setattr(
        "rain_garden.retrieval.search",
        lambda q, **k: calls.__setitem__("n", calls["n"] + 1) or [],
    )
    client = FakeClient([
        FakeResp([_tool_use(SEARCH_GUIDANCE, {"query": "clay"}, "s1")], "tool_use"),
        FakeResp([FakeBlock("text", text="I still need a couple details.")], "end_turn"),
    ])
    _, status, call_log = agent.run_agent(
        [{"role": "user", "content": "hi"}], client=client
    )
    entry = next(c for c in call_log if c["name"] == SEARCH_GUIDANCE)
    assert entry["output"]["is_error"] is True
    assert calls["n"] == 0            # retrieval was never reached
    assert status == "awaiting_user"


def test_search_guidance_dispatched_after_compute(monkeypatch):
    """Proper order -> gate passes, retrieval runs, run completes."""
    passages = [{
        "text": "Amend clayey soil with compost before planting.",
        "source_doc": "oregon_guide", "source_url": "u",
        "citation_label": "Oregon Rain Garden Guide", "page": 11, "score": 0.82,
    }]
    monkeypatch.setattr("rain_garden.retrieval.search", lambda q, **k: passages)
    client = FakeClient([
        FakeResp([
            _tool_use("size_garden", {"catchment_sa": 700, "soil_type": "Clayey"}, "a1"),
            _tool_use("filter_plants", {"state": "NY", "local_min_temp": 5}, "a2"),
        ], "tool_use"),
        FakeResp([_tool_use(SEARCH_GUIDANCE, {"query": "clay amend"}, "a3")], "tool_use"),
        FakeResp([
            FakeBlock("text", text="Here is your rain garden design."),
            _tool_use("present_results", {"summary": "All set."}, "a4"),
        ], "tool_use"),
    ])
    _, status, call_log = agent.run_agent(
        [{"role": "user", "content": "hi"}], client=client
    )
    assert status == "complete"
    entry = next(c for c in call_log if c["name"] == SEARCH_GUIDANCE)
    assert entry["output"] == {"passages": passages}   # dispatched, not gated


# --- disjoint guidance channel in assembly (spec section 0) ------------------

def test_assemble_results_populates_disjoint_channels():
    call_log = [
        {"name": "size_garden", "input": {}, "output": {
            "design": {"area_sqft": 70}, "recommended": True,
            "advisories": [{"type": "clay_drainage", "severity": "corrective", "message": "m"}],
        }},
        {"name": "filter_plants", "input": {}, "output": {
            "interior": [{"common_name": "Blue Flag"}], "perimeter": [],
        }},
        {"name": "search_guidance", "input": {"query": "clay"}, "output": {"passages": [
            {"text": "Amend clay with compost.", "citation_label": "Oregon",
             "source_url": "u", "page": 11, "score": 0.82},
        ]}},
        {"name": "present_results", "input": {"summary": "done"}, "output": None},
    ]
    res = app._assemble_results(call_log)
    assert res["summary"] == "done"
    assert res["sizing"]["design"]["area_sqft"] == 70
    assert res["advisories"][0]["type"] == "clay_drainage"
    assert res["plants"]["interior"][0]["common_name"] == "Blue Flag"
    assert res["guidance"][0]["citation_label"] == "Oregon"


def test_guidance_entry_never_reaches_numeric_fields():
    """A search_guidance entry whose payload mimics numeric fields cannot populate
    them: numeric fields are read ONLY from their own compute-tool entries."""
    call_log = [{
        "name": "search_guidance", "input": {"query": "x"},
        "output": {"passages": [], "sizing": {"area_sqft": 999},
                   "advisories": [{"type": "spoofed"}]},
    }]
    res = app._assemble_results(call_log)
    assert "sizing" not in res       # no size_garden entry -> no sizing field
    assert "plants" not in res
    assert "advisories" not in res   # advisories come only from size_garden
    assert res["guidance"] == []     # only the (empty) passages are read


def test_errored_guidance_yields_empty_channel():
    call_log = [{
        "name": "search_guidance", "input": {"query": "x"},
        "output": {"is_error": True, "message": "boom"},
    }]
    assert app._assemble_results(call_log)["guidance"] == []
