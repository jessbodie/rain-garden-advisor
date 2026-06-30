"""Tests for the tool layer (tools.py). No network.

Network-backed module functions are monkeypatched on the ``tools`` module;
``filter_plants`` and ``size_garden`` run for real against packaged data.
"""

import json

import pandas as pd
import pytest

import tools
from tools import FatalToolError, dispatch, geocode_and_gate
from rain_garden.geocode import AddressNotFoundError
from rain_garden.hardiness import HardinessZoneNotFoundError, MissingAPIKeyError
from rain_garden import plants
from rain_garden.plants import TEMP_COL, filter_plants


def _dumpable(obj):
    """True if strictly JSON-serializable (no numpy types, no NaN/Inf)."""
    json.dumps(obj, allow_nan=False)
    return True


# --- JSON safety across all tools --------------------------------------------

def test_filter_plants_dispatch_is_json_safe():
    # Floor supplied so the populated branch (numpy-typed plant records) is exercised.
    result = dispatch("filter_plants", {"state": "NY", "local_min_temp": 5})
    assert _dumpable(result)


def test_size_garden_dispatch_is_json_safe():
    result = dispatch("size_garden", {"catchment_sa": 700, "soil_type": "Silty"})
    assert _dumpable(result)


def test_precipitation_dispatch_is_json_safe(monkeypatch):
    monkeypatch.setattr(tools, "get_precipitation_stats", lambda lat, lon: {
        "threshold_precip_rate": 0.323,
        "total_precip_yr": 43,
        "min_apparent_temp": -11.8,
    })
    result = dispatch("get_precipitation_stats", {"lat": 40.65, "lon": -73.95})
    assert _dumpable(result)
    assert "min_apparent_temp" not in result  # stripped — never seen by the model
    assert result == {"threshold_precip_rate": 0.323, "total_precip_yr": 43}


def test_hardiness_dispatch_includes_numeric_floor(monkeypatch):
    monkeypatch.setattr(tools, "get_hardiness_zone", lambda zip_code: {
        "zone": "7b", "min_temp_range": "5 to 10", "zip_code": zip_code,
    })
    result = dispatch("get_hardiness_zone", {"zip_code": "11209"})
    assert _dumpable(result)
    assert result["min_temp_floor"] == 5
    assert result["zone"] == "7b"


# --- filter_plants shaping ----------------------------------------------------

def test_filter_plants_shape_and_trim():
    result = dispatch("filter_plants", {"state": "NY", "local_min_temp": 5})
    assert set(result) == {"interior", "perimeter"}
    expected_keys = {"common_name", "bloom_period", "flower_color", "height_ft", "moisture_use"}
    for zone in ("interior", "perimeter"):
        assert len(result[zone]) <= 15
        assert result[zone], f"{zone} should be non-empty for NY"
        for record in result[zone]:
            assert set(record) == expected_keys


# --- filter_plants hardiness-floor guard (both branches) ----------------------

def test_filter_plants_present_floor_returns_hardy_plants_no_reason():
    floor = 5
    result = dispatch("filter_plants", {"state": "NY", "local_min_temp": floor})
    # normal-branch shape: exactly interior + perimeter, never a reason key —
    # locks the two output shapes so they can't drift.
    assert set(result) == {"interior", "perimeter"}
    assert result["interior"] and result["perimeter"]
    # Regression guard for the inverted-comparison bug. The temp column is stripped
    # from both the tool output and filter_plants' returned frame, so cross-reference
    # each kept plant's Symbol against the source data and assert it is rated hardy
    # enough (min_temp <= floor) with no null-temp rows surviving.
    kept = filter_plants("NY", local_min_temp=floor)
    source = plants._load_plants()
    matched = source[source["Symbol"].isin(kept["Symbol"])]
    # Symbol is not globally unique in the source; assert the kept set maps 1:1 so the
    # temp lookup below can't silently pass on a mismatched duplicate row.
    assert len(matched) == len(kept)
    temps = pd.to_numeric(matched[TEMP_COL], errors="coerce")
    assert temps.notna().all()
    assert (temps <= floor).all()


def test_filter_plants_absent_floor_returns_empty_with_reason():
    result = dispatch("filter_plants", {"state": "NY"})
    assert result["interior"] == []
    assert result["perimeter"] == []
    assert isinstance(result["reason"], str) and result["reason"]
    # exactly these three keys — no leakage, no drift
    assert set(result) == {"interior", "perimeter", "reason"}
    assert _dumpable(result)


# --- Two-tier error handling --------------------------------------------------

def test_missing_api_key_is_fatal(monkeypatch):
    def boom(zip_code):
        raise MissingAPIKeyError("no key")
    monkeypatch.setattr(tools, "get_hardiness_zone", boom)
    with pytest.raises(FatalToolError):
        dispatch("get_hardiness_zone", {"zip_code": "11209"})


def test_recoverable_lookup_failure_returns_error(monkeypatch):
    def boom(zip_code):
        raise HardinessZoneNotFoundError("no data")
    monkeypatch.setattr(tools, "get_hardiness_zone", boom)
    result = dispatch("get_hardiness_zone", {"zip_code": "00000"})
    assert result == {"is_error": True, "message": "no data"}


def test_invalid_state_is_recoverable():
    # Floor supplied so the call reaches state validation (the no-floor guard
    # short-circuits before filter_plants would raise InvalidStateError).
    result = dispatch("filter_plants", {"state": "ZZ", "local_min_temp": 5})
    assert result["is_error"] is True


# --- geocode_and_gate ---------------------------------------------------------

def test_gate_allows_lower_48(monkeypatch):
    monkeypatch.setattr(tools, "geocode_address", lambda addr: {
        "address": "Brooklyn, NY", "lat": 40.65, "lon": -73.95,
        "zip_code": "11209", "state": "NY",
    })
    result = geocode_and_gate("97 80th St, Brooklyn NY")
    assert result["ok"] is True
    assert result["state"] == "NY"


def test_gate_refuses_non_lower_48(monkeypatch):
    monkeypatch.setattr(tools, "geocode_address", lambda addr: {
        "address": "Juneau, AK", "lat": 58.3, "lon": -134.4,
        "zip_code": "99801", "state": "AK",
    })
    result = geocode_and_gate("Juneau, AK")
    assert result["ok"] is False
    assert "lower-48" in result["message"]


def test_gate_refuses_unfindable_address(monkeypatch):
    def boom(addr):
        raise AddressNotFoundError("nope")
    monkeypatch.setattr(tools, "geocode_address", boom)
    result = geocode_and_gate("asdfghjkl12345")
    assert result["ok"] is False


# --- size_garden advisories ---------------------------------------------------

def test_advisory_happy_path_recommended():
    result = dispatch("size_garden", {
        "catchment_sa": 700, "soil_type": "Silty",
        "distance": "More than 30 ft", "slope_ok": True,
    })
    assert result["recommended"] is True
    types = {a["type"] for a in result["advisories"]}
    assert types == {"utilities"}  # only the always-on informational note
    for a in result["advisories"]:
        assert set(a) == {"type", "severity", "message"}


def test_advisory_clay_is_corrective():
    result = dispatch("size_garden", {"catchment_sa": 700, "soil_type": "Clayey"})
    clay = [a for a in result["advisories"] if a["type"] == "clay_drainage"]
    assert clay and clay[0]["severity"] == "corrective"
    assert result["recommended"] is True  # corrective is not blocking


def test_advisory_blocking_conditions():
    result = dispatch("size_garden", {
        "catchment_sa": 700, "soil_type": "Silty",
        "distance": "Less than 10 ft", "slope_ok": False,
    })
    severities = {a["type"]: a["severity"] for a in result["advisories"]}
    assert severities["foundation_setback"] == "blocking"
    assert severities["slope"] == "blocking"
    assert result["recommended"] is False
    # "Less than 10 ft" is deliberate: it still resolves the <30 ft factor (0.21
    # for Silty) and sizes a footprint — the blocking advisory does not suppress
    # the calculation, and it is never a KeyError or a silent default.
    assert result["design"]["sizing_factor"] == 0.21
    assert result["design"]["area_sqft"] == 147


def test_low_drainage_is_blocking_and_contingent():
    result = dispatch("size_garden", {
        "catchment_sa": 700, "soil_type": "Silty", "perc_rate": "0.3",
    })
    assert result["recommended"] is False
    assert any(a["type"] == "low_drainage" and a["severity"] == "blocking"
               for a in result["advisories"])
    assert result["design"]["contingent"] is True


def test_unknown_soil_uses_clay_factor_and_notes_it():
    # Omitted soil -> sized with Clayey factor (0.10) but flagged as unknown, not clay.
    result = dispatch("size_garden", {"catchment_sa": 700, "distance": "More than 30 ft"})
    assert result["design"]["sizing_factor"] == 0.10
    types = {a["type"] for a in result["advisories"]}
    assert "unknown_soil" in types
    assert "clay_drainage" not in types  # Unknown never gets the clay advisory


# --- slope-toward-house corrective advisory -----------------------------------

# Non-blocking base inputs; only slopes_away_from_house varies.
_SLOPE_BASE = {
    "catchment_sa": 700, "soil_type": "Silty",
    "distance": "More than 30 ft", "slope_ok": True,
}


def test_slope_toward_house_is_corrective_not_blocking():
    result = dispatch("size_garden", {**_SLOPE_BASE, "slopes_away_from_house": False})
    toward = [a for a in result["advisories"] if a["type"] == "slope_toward_house"]
    assert len(toward) == 1
    assert toward[0]["severity"] == "corrective"
    assert result["recommended"] is True  # corrective must not flip recommended


def test_slope_away_from_house_no_advisory():
    result = dispatch("size_garden", {**_SLOPE_BASE, "slopes_away_from_house": True})
    assert not any(a["type"] == "slope_toward_house" for a in result["advisories"])


def test_slope_direction_omitted_no_advisory():
    result = dispatch("size_garden", dict(_SLOPE_BASE))
    assert not any(a["type"] == "slope_toward_house" for a in result["advisories"])
