"""Tests for rain_garden.roofarea.

No network: the happy path runs against a saved Solar API response
(tests/fixtures/solar_*.json). Live-path failure modes (timeout, HTTP error,
missing key) are exercised by monkeypatching, and every one must collapse to
``None`` rather than raising — the estimate is reference context, never required.
"""

import json
from pathlib import Path

import pytest

from rain_garden import roofarea
from rain_garden.roofarea import SQFT_PER_SQM, estimate_roof_area

FIXTURES = Path(__file__).parent / "fixtures"

BROOKLYN = (40.6501, -73.9496)
# Oracle: the Brooklyn fixture's groundAreaMeters2 (160.0) converted and rounded
# to the nearest 10 sq ft. Derived directly from the constant, independently of the
# module. 160.0 * 10.7639 = 1722.224 -> 1720.
EXPECTED_BROOKLYN_SQFT = int(round(160.0 * SQFT_PER_SQM / 10) * 10)


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- Happy path (fixture) -----------------------------------------------------

def test_footprint_from_fixture():
    result = estimate_roof_area(*BROOKLYN, fixture=_load("solar_brooklyn.json"))
    assert result == {"roof_sqft": EXPECTED_BROOKLYN_SQFT, "imagery_date": "2022-08-15"}
    assert result["roof_sqft"] == 1720  # pins the oracle explicitly


def test_uses_footprint_not_sloped_surface():
    # The fixture also carries the larger sloped areaMeters2 (210.5). Using it would
    # overestimate catchment; confirm we read groundAreaMeters2 instead.
    surface_sqft = int(round(210.5 * SQFT_PER_SQM / 10) * 10)
    result = estimate_roof_area(*BROOKLYN, fixture=_load("solar_brooklyn.json"))
    assert result["roof_sqft"] != surface_sqft
    assert result["roof_sqft"] == EXPECTED_BROOKLYN_SQFT


def test_fixture_accepts_path():
    result = estimate_roof_area(*BROOKLYN, fixture=FIXTURES / "solar_brooklyn.json")
    assert result["roof_sqft"] == EXPECTED_BROOKLYN_SQFT


@pytest.mark.parametrize(
    "ground_m2, expected",
    [
        (160.0, 1720),   # 1722.2 -> 1720
        (100.0, 1080),   # 1076.4 -> 1080
        (0.0, 0),        # degenerate but structurally valid
        (200.05, 2150),  # 2153.8 -> 2150
    ],
)
def test_rounds_to_nearest_ten(ground_m2, expected):
    data = {"solarPotential": {"wholeRoofStats": {"groundAreaMeters2": ground_m2}}}
    result = estimate_roof_area(*BROOKLYN, fixture=data)
    assert result["roof_sqft"] == expected


def test_imagery_date_optional():
    data = {"solarPotential": {"wholeRoofStats": {"groundAreaMeters2": 160.0}}}
    result = estimate_roof_area(*BROOKLYN, fixture=data)
    assert result["imagery_date"] is None


# --- No estimate available -> None (never raises) -----------------------------

def test_no_building_returns_none():
    assert estimate_roof_area(*BROOKLYN, fixture=_load("solar_no_building.json")) is None


def test_missing_roof_stats_returns_none():
    # A response present but without groundAreaMeters2.
    data = {"solarPotential": {"wholeRoofStats": {"areaMeters2": 210.5}}}
    assert estimate_roof_area(*BROOKLYN, fixture=data) is None


def test_missing_api_key_returns_none(monkeypatch):
    import dotenv

    monkeypatch.delenv("GOOGLE_SOLAR_API_KEY", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    # Live path (no fixture), no key -> graceful None, NOT a raised exception.
    assert estimate_roof_area(*BROOKLYN) is None


def test_timeout_returns_none(monkeypatch):
    import dotenv
    import requests

    monkeypatch.setenv("GOOGLE_SOLAR_API_KEY", "test-key")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    def _raise_timeout(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(requests, "get", _raise_timeout)
    assert estimate_roof_area(*BROOKLYN, timeout_s=0.001) is None


def test_http_error_returns_none(monkeypatch):
    import dotenv
    import requests

    monkeypatch.setenv("GOOGLE_SOLAR_API_KEY", "test-key")
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)

    class _FakeResponse:
        def raise_for_status(self):
            raise requests.HTTPError("404 Not Found")

        def json(self):  # pragma: no cover - should never be reached
            return {}

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse())
    assert estimate_roof_area(*BROOKLYN) is None


def test_no_soil_dependency():
    # Regression guard (per the feature spec): the roof path is purely geometric —
    # it takes no soil input and touches no soil logic, so it can't trip the known
    # gallons_per_year-nulls-on-unknown-soil bug in the sizing path.
    import inspect

    sig = inspect.signature(estimate_roof_area)
    assert "soil" not in " ".join(sig.parameters).lower()
