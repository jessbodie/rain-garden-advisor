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


# --- results assembly: per-option token-injected summaries, guidance dropped --
# Numbers are constructed test inputs, NOT oracle values — assertions check the
# substitution/guard machinery, never that a particular area is "correct".

# Three depth options with deliberately distinct values so cross-depth leakage is
# visible. gallons defaults null (the common no-precip run); tests override it.
def _options():
    return [
        {"depth_in": 4, "band": "3-5", "area_sqft": 238,
         "interior_plants": 111, "perimeter_plants": 24, "advisories": []},
        {"depth_in": 6, "band": "6-7", "area_sqft": 175,
         "interior_plants": 79, "perimeter_plants": 20, "advisories": []},
        {"depth_in": 8, "band": "8", "area_sqft": 112,
         "interior_plants": 47, "perimeter_plants": 16, "advisories": []},
    ]


def _sizing_entry(catchment=700, advisories=None, gallons=None,
                  sizing_advisories=None, options=None):
    return {
        "name": "size_garden",
        "input": {"catchment_sa": catchment},
        "output": {
            "recommended": True,
            "sizing": {
                "options": options if options is not None else _options(),
                "advisories": sizing_advisories if sizing_advisories is not None else [],
            },
            "advisories": advisories if advisories is not None else [
                {"type": "utilities", "severity": "informational", "message": "m"},
            ],
            "gallons_per_year": gallons,
        },
    }


def _present(summary):
    return {"name": "present_results", "input": {"summary": summary}, "output": None}


def test_assemble_populates_fields_and_resolves_per_option_summaries():
    call_log = [
        _sizing_entry(advisories=[
            {"type": "clayey_unverified", "severity": "corrective", "message": "m"}]),
        {"name": "filter_plants", "input": {}, "output": {
            "interior": [{"common_name": "Blue Flag"}], "perimeter": [],
        }},
        {"name": "search_guidance", "input": {"query": "clay"},
         "output": {"passages": [{"citation_label": "Oregon"}]}},
        _present("A {area_sqft} sq ft garden with {interior_plants} center plants."),
    ]
    res = app._assemble_results(call_log)
    opts = res["sizing"]["options"]
    assert opts[0]["summary"] == "A 238 sq ft garden with 111 center plants."
    assert opts[2]["summary"] == "A 112 sq ft garden with 47 center plants."
    assert res["advisories"][0]["type"] == "clayey_unverified"
    assert res["plants"]["interior"][0]["common_name"] == "Blue Flag"
    assert "summary" not in res            # no top-level summary any more
    assert "guidance" not in res           # guidance is not a results field


def test_one_template_renders_three_distinct_summaries():
    template = "About {depth_in} in deep, {area_sqft} sq ft, {interior_plants} plants."
    res = app._assemble_results([_sizing_entry(), _present(template)])
    summaries = [o["summary"] for o in res["sizing"]["options"]]
    assert summaries == [
        "About 4 in deep, 238 sq ft, 111 plants.",
        "About 6 in deep, 175 sq ft, 79 plants.",
        "About 8 in deep, 112 sq ft, 47 plants.",
    ]
    assert len(set(summaries)) == 3        # numerically distinct


def test_per_option_allowlist_scopes_to_own_depth():
    # Each option substitutes ONLY its own values: the 8" summary can never show a
    # 4" area. Build subs per option and confirm the area tracks the option.
    entry = _sizing_entry()
    for opt in entry["output"]["sizing"]["options"]:
        subs = app._substitutions(entry, opt)
        assert subs["area_sqft"] == opt["area_sqft"]
        assert subs["depth_in"] == opt["depth_in"]
        resolved = app._resolve_summary("{area_sqft} sq ft", subs)
        assert resolved == f"{opt['area_sqft']} sq ft"


def test_referenced_tokens_all_resolve_non_null():
    entry = _sizing_entry(gallons=12000)
    subs = app._substitutions(entry, entry["output"]["sizing"]["options"][0])
    raw = ("{area_sqft} sq ft; captures {gallons_per_year} gal/yr from "
           "{catchment_sqft} sq ft.")
    resolved = app._resolve_summary(raw, subs)
    # No fallback: all referenced tokens were present and non-null.
    assert resolved == "238 sq ft; captures 12000 gal/yr from 700 sq ft."


def test_substitution_dict_is_curated_allowlist():
    entry = _sizing_entry(catchment=850)
    subs = app._substitutions(entry, entry["output"]["sizing"]["options"][0])
    # catchment comes from the INPUT, under the token name catchment_sqft.
    assert subs["catchment_sqft"] == 850
    # An option key that is NOT an authored token must not be substitutable.
    assert "band" not in subs
    # Referencing it therefore fails the allow-list check -> deterministic fallback.
    resolved = app._resolve_summary("band {band}", subs)
    assert resolved == app._fallback_summary(subs)


def test_advisories_byte_identical_to_tool_output():
    advisories = [{"type": "slope", "severity": "blocking", "message": "x"}]
    entry = _sizing_entry(advisories=advisories)
    res = app._assemble_results([entry, _present("ok")])
    assert res["advisories"] == advisories                    # unchanged value
    assert res["advisories"] is entry["output"]["advisories"]  # same object, no copy/edit


def test_gallons_and_recommended_sit_outside_options():
    res = app._assemble_results([_sizing_entry(gallons=9000), _present("ok")])
    assert res["gallons_per_year"] == 9000
    assert res["recommended"] is True
    for o in res["sizing"]["options"]:
        assert "gallons_per_year" not in o


def test_incidental_and_untokenized_digits_pass_through():
    """No digit guard: bare digits the model writes are left as-is. Only unknown or
    null tokens route to the fallback."""
    entry = _sizing_entry()
    subs = app._substitutions(entry, entry["output"]["sizing"]["options"][0])
    assert app._resolve_summary("Your garden is 238 sq ft.", subs) == "Your garden is 238 sq ft."
    resolved = app._resolve_summary("A {area_sqft} sq ft garden, Zone 7b, call 811.", subs)
    assert resolved == "A 238 sq ft garden, Zone 7b, call 811."


def test_null_token_routes_to_fallback_and_omits_clause():
    entry = _sizing_entry()  # gallons_per_year is None
    opt = entry["output"]["sizing"]["options"][0]
    subs = app._substitutions(entry, opt)
    resolved = app._resolve_summary("It captures {gallons_per_year} gallons.", subs)
    fallback = app._fallback_summary(subs)
    assert resolved == fallback
    # The fallback omits the gallons clause entirely when the value is null.
    assert "captures roughly" not in fallback
    # ...but includes it when the value IS present.
    entry2 = _sizing_entry(gallons=9000)
    subs2 = app._substitutions(entry2, entry2["output"]["sizing"]["options"][0])
    assert "captures roughly 9000 gallons" in app._fallback_summary(subs2)


def test_prompt_slip_without_sizing_produces_no_options():
    """present_results but no size_garden this turn: no options to substitute
    against, so no summaries are produced rather than raising."""
    res = app._assemble_results([_present("done")])
    assert "sizing" not in res and "summary" not in res and "guidance" not in res


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
    opts = res["sizing"]["options"]
    assert opts[0]["area_sqft"] == 238
    assert opts[0]["summary"] == "Set at 238 sq ft."
