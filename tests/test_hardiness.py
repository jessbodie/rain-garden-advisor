"""Tests for rain_garden.hardiness.

No network: assertions run against saved real RapidAPI responses
(tests/fixtures/hardiness_*.json). The live path's missing-key behavior is
tested by monkeypatching the environment.
"""

import json
from pathlib import Path

import pytest

from rain_garden import hardiness
from rain_garden.hardiness import (
    HardinessZoneNotFoundError,
    InvalidZipCodeError,
    MissingAPIKeyError,
    get_hardiness_zone,
    min_temp_floor,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- Valid zips (fixtures) ----------------------------------------------------

def test_brooklyn_zone():
    result = get_hardiness_zone("11209", fixture=_load("hardiness_11209.json"))
    assert result == {"zone": "7b", "min_temp_range": "5 to 10", "zip_code": "11209"}


def test_fargo_zone_is_colder():
    # 58102 (Fargo, ND) — a colder zone, proving the lookup isn't NYC-specific.
    result = get_hardiness_zone("58102", fixture=_load("hardiness_58102.json"))
    assert result == {"zone": "4a", "min_temp_range": "-30 to -25", "zip_code": "58102"}


def test_fixture_accepts_path():
    result = get_hardiness_zone("11209", fixture=FIXTURES / "hardiness_11209.json")
    assert result["zone"] == "7b"


# --- Not found ----------------------------------------------------------------

def test_no_data_raises_not_found():
    # The real 404 body for a format-valid but nonexistent zip has no 'zone'.
    with pytest.raises(HardinessZoneNotFoundError):
        get_hardiness_zone("00000", fixture=_load("hardiness_00000.json"))


# --- Invalid zip format -------------------------------------------------------

@pytest.mark.parametrize("bad", [None, "1234", "123456", "abcde", "1234a", ""])
def test_invalid_zip_raises(bad):
    with pytest.raises(InvalidZipCodeError):
        get_hardiness_zone(bad)


def test_invalid_zip_checked_before_fixture():
    # Validation precedes data handling even when a fixture is supplied.
    with pytest.raises(InvalidZipCodeError):
        get_hardiness_zone("abc", fixture=_load("hardiness_11209.json"))


# --- Missing API key ----------------------------------------------------------

def test_missing_api_key_raises(monkeypatch):
    import dotenv

    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    # Prevent .env from repopulating the key during the test.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    with pytest.raises(MissingAPIKeyError):
        get_hardiness_zone("11209")  # live path, no fixture


# --- min_temp_floor -----------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [("5 to 10", 5), ("-30 to -25", -30), ("0 to 5", 0), ("10 to 15 (F)", 10)],
)
def test_min_temp_floor_parses_lower_bound(raw, expected):
    assert min_temp_floor(raw) == expected


@pytest.mark.parametrize("raw", ["", "n/a", None])
def test_min_temp_floor_unparseable_returns_none(raw):
    assert min_temp_floor(raw) is None


def test_min_temp_floor_from_hardiness_result():
    # Integration: the Brooklyn fixture's range "5 to 10" -> floor 5.
    result = get_hardiness_zone("11209", fixture=_load("hardiness_11209.json"))
    assert min_temp_floor(result["min_temp_range"]) == 5
