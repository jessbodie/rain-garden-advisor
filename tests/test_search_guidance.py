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
from tools import SEARCH_GUIDANCE, dispatch  # noqa: E402


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


# --- results assembly: token-injected summary + guidance dropped -------------
# Numbers are constructed test inputs, NOT oracle values — assertions check the
# substitution/guard machinery, never that a particular area is "correct".

# Canonical size_garden design. drainage/gallons default null (the common
# no-perc-rate / soil-unknown run); individual tests override as needed.
_DESIGN = {
    "sizing_factor": 0.10,
    "area_sqft": 70,
    "elongated_width_ft": 6,
    "elongated_length_ft": 12,
    "balanced_side_ft": 8,
    "depth_inches": 12,
    "interior_plant_count": 11,
    "perimeter_plant_count": 9,
    "drainage_time_hours": None,
    "gallons_per_year": None,
}


def _sizing_entry(design=None, catchment=700, advisories=None):
    d = dict(_DESIGN)
    if design:
        d.update(design)
    return {
        "name": "size_garden",
        "input": {"catchment_sa": catchment},
        "output": {
            "recommended": True,
            "design": d,
            "advisories": advisories if advisories is not None else [
                {"type": "utilities", "severity": "informational", "message": "m"},
            ],
        },
    }


def _present(summary):
    return {"name": "present_results", "input": {"summary": summary}, "output": None}


def test_assemble_populates_fields_and_resolves_summary():
    call_log = [
        _sizing_entry(advisories=[
            {"type": "clay_drainage", "severity": "corrective", "message": "m"}]),
        {"name": "filter_plants", "input": {}, "output": {
            "interior": [{"common_name": "Blue Flag"}], "perimeter": [],
        }},
        {"name": "search_guidance", "input": {"query": "clay"},
         "output": {"passages": [{"citation_label": "Oregon"}]}},
        _present("A {area_sqft} sq ft garden with {interior_plant_count} center plants."),
    ]
    res = app._assemble_results(call_log)
    assert res["summary"] == "A 70 sq ft garden with 11 center plants."
    assert res["sizing"]["design"]["area_sqft"] == 70
    assert res["advisories"][0]["type"] == "clay_drainage"
    assert res["plants"]["interior"][0]["common_name"] == "Blue Flag"
    assert "guidance" not in res  # guidance is no longer a results field


def test_summary_has_no_bare_dimension_digits():
    """Every digit in the rendered summary arrived as a resolved token; a raw
    summary that is digit-free stays digit-free only via substitution."""
    subs = app._substitutions(_sizing_entry())
    raw = ("{area_sqft} sq ft, {depth_inches} in deep, "
           "{interior_plant_count}/{perimeter_plant_count} plants.")
    assert not any(ch.isdigit() for ch in raw)  # model wrote zero bare digits
    resolved = app._resolve_summary(raw, subs)
    assert resolved == "70 sq ft, 12 in deep, 11/9 plants."


def test_referenced_tokens_all_resolve_non_null():
    subs = app._substitutions(_sizing_entry(
        design={"drainage_time_hours": 30, "gallons_per_year": 12000}))
    raw = ("{area_sqft} sq ft; captures {gallons_per_year} gal/yr from "
           "{catchment_sqft} sq ft; drains in {drainage_time_hours} h.")
    resolved = app._resolve_summary(raw, subs)
    # No fallback: all referenced tokens were present and non-null.
    assert resolved == "70 sq ft; captures 12000 gal/yr from 700 sq ft; drains in 30 h."


def test_substitution_dict_is_curated_allowlist_not_design_splat():
    subs = app._substitutions(_sizing_entry(catchment=850))
    # catchment comes from the INPUT, under the token name catchment_sqft.
    assert subs["catchment_sqft"] == 850
    # A design-only key that is NOT an authored token must not be substitutable.
    assert "sizing_factor" not in subs
    # Referencing it therefore fails the allow-list check -> deterministic fallback.
    resolved = app._resolve_summary("factor {sizing_factor}", subs)
    assert resolved == app._fallback_summary(subs)


def test_advisories_byte_identical_to_tool_output():
    advisories = [{"type": "slope", "severity": "blocking", "message": "x"}]
    entry = _sizing_entry(advisories=advisories)
    res = app._assemble_results([entry, _present("ok")])
    assert res["advisories"] == advisories                    # unchanged value
    assert res["advisories"] is entry["output"]["advisories"]  # same object, no copy/edit


def test_incidental_and_untokenized_digits_pass_through():
    """No digit guard: bare digits the model writes are left as-is. Only unknown or
    null tokens route to the fallback."""
    subs = app._substitutions(_sizing_entry())
    # An un-tokenized dimension digit is no longer policed -> passes through.
    assert app._resolve_summary("Your garden is 70 sq ft.", subs) == "Your garden is 70 sq ft."
    # Valid tokens resolve while incidental non-dimension digits (zone, 811) survive.
    resolved = app._resolve_summary("A {area_sqft} sq ft garden, Zone 7b, call 811.", subs)
    assert resolved == "A 70 sq ft garden, Zone 7b, call 811."


def test_null_token_routes_to_fallback_and_omits_clause():
    subs = app._substitutions(_sizing_entry())  # drainage_time_hours is None
    resolved = app._resolve_summary("It drains in {drainage_time_hours} hours.", subs)
    fallback = app._fallback_summary(subs)
    assert resolved == fallback
    # The fallback omits the drainage clause entirely when the value is null.
    assert "drains in about" not in fallback
    # ...but includes optional clauses whose values ARE present.
    subs2 = app._substitutions(_sizing_entry(design={"drainage_time_hours": 30}))
    assert "drains in about 30 hours" in app._fallback_summary(subs2)


def test_prompt_slip_without_sizing_passes_summary_through():
    """present_results but no size_garden this turn: no design to substitute against,
    so the raw summary passes through rather than raising."""
    res = app._assemble_results([_present("done")])
    assert res["summary"] == "done"
    assert "sizing" not in res and "guidance" not in res


# --- guidance retrieval failure is non-fatal (guarantee had no other coverage) --

def test_guidance_retrieval_error_is_non_fatal(monkeypatch):
    """A raising retrieval degrades to a recoverable {is_error}, never propagating —
    the 'retrieval failure never breaks the deterministic recommendation' invariant."""
    def boom(query, **kwargs):
        raise RuntimeError("onnx runtime exploded")
    monkeypatch.setattr("rain_garden.retrieval.search", boom)
    out = dispatch(SEARCH_GUIDANCE, {"query": "clay"})
    assert out["is_error"] is True
    assert "onnx runtime exploded" in out["message"]


def test_assemble_tolerates_errored_guidance_entry():
    """An errored search_guidance entry in the log doesn't break assembly: the
    deterministic fields still populate and there is no guidance field to poison."""
    call_log = [
        _sizing_entry(),
        {"name": "search_guidance", "input": {"query": "x"},
         "output": {"is_error": True, "message": "boom"}},
        _present("Set at {area_sqft} sq ft."),
    ]
    res = app._assemble_results(call_log)
    assert "guidance" not in res
    assert res["sizing"]["design"]["area_sqft"] == 70
    assert res["summary"] == "Set at 70 sq ft."
