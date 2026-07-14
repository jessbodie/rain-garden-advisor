"""Unit tests for the UI progress stepper (_stages) — no network.

_stages derives five ordered stages (Address, Localized Data, Site Conditions,
Growing Conditions, Rain Garden Plan) from the transcript's tool calls plus this
turn's status/outcome. The load-bearing invariants under test:
  * completion flags are independent and order-free (a later stage can be complete
    while an earlier one is the in-progress cursor);
  * Site Conditions clears early from check_viability inputs, but ONLY when no blocker
    stands — a corrective (clayey-unverified) note does not block completion;
  * a decline freezes the cursor at the incomplete site stage; Plan never completes;
  * a produced plan (recommended OR overridden) fills the whole bar.
"""

import os

# app.py builds an Anthropic client at import; give it a dummy key for offline import.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-not-used")

from app import _stages  # noqa: E402
from tools import LOCATION_PREAMBLE_MARKER, check_viability  # noqa: E402


# --- transcript builders ------------------------------------------------------

def _seed():
    """The seed user turn carries the location preamble marker (address resolved)."""
    return {"role": "user", "content": f"{LOCATION_PREAMBLE_MARKER} site is in NY 11209."}


def _assistant(*calls):
    """An assistant turn of tool_use blocks: each call is (name, input_dict)."""
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "name": name, "input": inp, "id": f"t{i}"}
            for i, (name, inp) in enumerate(calls)
        ],
    }


def _states(stages):
    """{stage_id: state} for concise assertions."""
    return {s["id"]: s["state"] for s in stages}


# --- ordering / labels --------------------------------------------------------

def test_stage_order_and_labels():
    stages = _stages([_seed()], "awaiting_user", None)
    assert [s["id"] for s in stages] == [
        "address", "localized_data", "site_conditions",
        "growing_conditions", "plan",
    ]
    assert [s["label"] for s in stages] == [
        "Address", "Localized Data", "Site Conditions",
        "Growing Conditions", "Rain Garden Plan",
    ]


# --- Address / out_of_region --------------------------------------------------

def test_out_of_region_marks_address_in_progress():
    st = _states(_stages([], "out_of_region", None))
    assert st == {
        "address": "in_progress",
        "localized_data": "not_started",
        "site_conditions": "not_started",
        "growing_conditions": "not_started",
        "plan": "not_started",
    }


def test_address_not_found_marks_address_in_progress():
    # The geocode-miss rejection shares the out_of_region stepper shape (address is the
    # cursor, nothing else started); only the terminal status differs.
    st = _states(_stages([], "address_not_found", None))
    assert st == {
        "address": "in_progress",
        "localized_data": "not_started",
        "site_conditions": "not_started",
        "growing_conditions": "not_started",
        "plan": "not_started",
    }


# --- Localized Data -----------------------------------------------------------

def test_localized_data_completes_on_precip_and_hardiness():
    msgs = [
        _seed(),
        _assistant(
            ("get_precipitation_stats", {"lat": 40.6, "lon": -74.0}),
            ("get_hardiness_zone", {"zip_code": "11209"}),
        ),
    ]
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["address"] == "complete"
    assert st["localized_data"] == "complete"
    # Cursor moves to the next incomplete stage.
    assert st["site_conditions"] == "in_progress"
    assert st["growing_conditions"] == "not_started"
    assert st["plan"] == "not_started"


def test_localized_data_in_progress_when_only_one_of_two_fired():
    msgs = [_seed(), _assistant(("get_precipitation_stats", {"lat": 40.6, "lon": -74.0}))]
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["localized_data"] == "in_progress"
    assert st["site_conditions"] == "not_started"


# --- Site Conditions: early clear from check_viability ------------------------

def _localized(*extra):
    """Seed + both localized fetches, plus any extra assistant turns."""
    return [
        _seed(),
        _assistant(
            ("get_precipitation_stats", {"lat": 40.6, "lon": -74.0}),
            ("get_hardiness_zone", {"zip_code": "11209"}),
        ),
        *extra,
    ]


def test_site_completes_when_core_slots_filled_no_blocker():
    msgs = _localized(_assistant((
        "check_viability",
        {"distance": "More than 30 ft", "slope_ok": True, "soil_type": "Silty"},
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "complete"
    assert st["growing_conditions"] == "in_progress"  # cursor advances past Site


def test_site_incomplete_when_slope_blocker_stands():
    msgs = _localized(_assistant((
        "check_viability",
        {"distance": "More than 30 ft", "slope_ok": False, "soil_type": "Silty"},
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    # slope_ok False keeps recommended False → Site does not complete; cursor freezes here.
    assert st["site_conditions"] == "in_progress"
    assert st["growing_conditions"] == "not_started"


def test_site_incomplete_when_core_slot_missing():
    # Only distance known — slope not yet answered — so the site can't clear yet.
    msgs = _localized(_assistant((
        "check_viability", {"distance": "More than 30 ft"},
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "in_progress"


def test_site_completes_on_distance_and_slope_without_soil():
    # Chosen semantics (live-verified 2026-07-09): the model reliably screens the two
    # blocker slots (distance, slope) via check_viability but NOT benign soil, so Site
    # Conditions clears on those two alone — soil is not required. This is what makes the
    # cursor actually walk Site -> Growing mid-chat.
    msgs = _localized(_assistant((
        "check_viability", {"distance": "More than 30 ft", "slope_ok": True},  # no soil
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "complete"
    assert st["growing_conditions"] == "in_progress"


def test_clayey_untested_is_advisory_not_blocker_site_completes():
    # The user-requested case: Clayey + unmeasured percolation is a corrective note,
    # NOT a blocker. With the core slots filled, Site Conditions completes and the bar
    # advances. Prove the underlying tool call is recommended=True first.
    assert check_viability(soil_type="Clayey", perc_rate=None)["recommended"] is True
    msgs = _localized(_assistant((
        "check_viability",
        {"distance": "More than 30 ft", "slope_ok": True, "soil_type": "Clayey"},
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "complete"
    assert st["growing_conditions"] == "in_progress"


def test_measured_low_drainage_blocks_site():
    # Contrast: a MEASURED slow rate (string, as the model passes it) does block.
    msgs = _localized(_assistant((
        "check_viability",
        {"distance": "More than 30 ft", "slope_ok": True,
         "soil_type": "Clayey", "perc_rate": "0.3"},
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "in_progress"


def test_size_garden_alone_completes_site():
    msgs = _localized(_assistant((
        "size_garden", {"catchment_sa": 700, "soil_type": "Silty"},
    )))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "complete"


# --- order independence: Growing complete while Site is the cursor ------------

def test_growing_complete_while_site_is_cursor():
    # filter_plants fired, but the site never cleared (no check_viability/size_garden):
    # Growing reads complete while Site remains the in-progress cursor — proves the
    # flags are order-free, not a left-to-right waterfall.
    msgs = _localized(_assistant(("filter_plants", {"state": "NY", "local_min_temp": 5})))
    st = _states(_stages(msgs, "awaiting_user", None))
    assert st["site_conditions"] == "in_progress"
    assert st["growing_conditions"] == "complete"
    assert st["plan"] == "not_started"


# --- terminal outcomes --------------------------------------------------------

def test_plan_recommended_fills_whole_bar():
    msgs = _localized(
        _assistant(
            ("size_garden", {"catchment_sa": 700, "soil_type": "Silty"}),
            ("filter_plants", {"state": "NY", "local_min_temp": 5}),
        ),
        _assistant(("present_results", {"summary": "ready"})),
    )
    st = _states(_stages(msgs, "complete", "plan"))
    assert set(st.values()) == {"complete"}


def test_plan_not_recommended_fills_whole_bar():
    # State A: a blocker was overridden — a plan still came back, so the bar fills.
    msgs = _localized(
        _assistant(
            ("size_garden", {"catchment_sa": 700, "distance": "Less than 10 ft"}),
            ("filter_plants", {"state": "NY", "local_min_temp": 5}),
        ),
        _assistant(("present_results", {"summary": "ready; not recommended"})),
    )
    st = _states(_stages(msgs, "complete", "plan_not_recommended"))
    assert set(st.values()) == {"complete"}


def test_declined_freezes_at_site_plan_never_completes():
    # The user declined a standing slope blocker → conclude_without_plan. The bar stops:
    # Site stays in_progress (frozen), downstream not_started, Plan never completes.
    msgs = _localized(
        _assistant((
            "check_viability",
            {"distance": "More than 30 ft", "slope_ok": False, "soil_type": "Silty"},
        )),
        _assistant(("conclude_without_plan", {"reason": "slope over 12%"})),
    )
    st = _states(_stages(msgs, "complete", "declined"))
    assert st["address"] == "complete"
    assert st["localized_data"] == "complete"
    assert st["site_conditions"] == "in_progress"
    assert st["growing_conditions"] == "not_started"
    assert st["plan"] == "not_started"
