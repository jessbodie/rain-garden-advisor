"""Tests for rain_garden.geocode.

No network: assertions run against saved real Nominatim responses
(tests/fixtures/nominatim_*.json) captured via geopy with addressdetails=True.
"""

import json
from pathlib import Path

import pytest

from rain_garden import geocode
from rain_garden.geocode import AddressNotFoundError, geocode_address

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --- End-to-end against fixtures ---------------------------------------------

def test_us_address_has_zip_and_state():
    result = geocode_address("97 80th St. Brooklyn NY", fixture=_load("nominatim_brooklyn.json"))
    assert result["zip_code"] == "11209"
    assert result["state"] == "NY"
    assert result["lat"] == pytest.approx(40.629658)
    assert result["lon"] == pytest.approx(-74.035852)
    assert result["address"].endswith("United States")


def test_international_address_zip_and_state_are_none():
    # France has postcode '75007' / ISO3166-2-lvl4 'FR-IDF', but country_code 'fr' -> None.
    result = geocode_address("Eiffel Tower, Paris", fixture=_load("nominatim_eiffel.json"))
    assert result["zip_code"] is None
    assert result["state"] is None
    assert result["lat"] == pytest.approx(48.8582599)
    assert result["lon"] == pytest.approx(2.2945006)
    assert result["address"].endswith("France")


def test_not_found_raises():
    with pytest.raises(AddressNotFoundError):
        geocode_address("asdfghjkl12345", fixture=_load("nominatim_notfound.json"))


def test_fixture_accepts_path():
    result = geocode_address("97 80th St. Brooklyn NY", fixture=FIXTURES / "nominatim_brooklyn.json")
    assert result["zip_code"] == "11209"


# --- _parse_zip units (synthetic raw dicts) ----------------------------------

def test_parse_zip_us_with_postcode():
    raw = {"address": {"country_code": "us", "postcode": "12345"}}
    assert geocode._parse_zip(raw) == "12345"


def test_parse_zip_truncates_zip_plus_four():
    raw = {"address": {"country_code": "us", "postcode": "11209-1234"}}
    assert geocode._parse_zip(raw) == "11209"


def test_parse_zip_non_us_returns_none():
    # Has a postcode, but country_code is not 'us'.
    raw = {"address": {"country_code": "fr", "postcode": "75007"}}
    assert geocode._parse_zip(raw) is None


def test_parse_zip_us_without_postcode_returns_none():
    raw = {"address": {"country_code": "us"}}
    assert geocode._parse_zip(raw) is None


def test_parse_zip_missing_address_returns_none():
    raw = {"display_name": "1, Main Street, 12345"}
    assert geocode._parse_zip(raw) is None


# --- _parse_state units (synthetic raw dicts) --------------------------------

def test_parse_state_us():
    raw = {"address": {"country_code": "us", "ISO3166-2-lvl4": "US-NY"}}
    assert geocode._parse_state(raw) == "NY"


def test_parse_state_non_us_returns_none():
    raw = {"address": {"country_code": "fr", "ISO3166-2-lvl4": "FR-IDF"}}
    assert geocode._parse_state(raw) is None


def test_parse_state_us_without_iso_returns_none():
    raw = {"address": {"country_code": "us"}}
    assert geocode._parse_state(raw) is None


def test_parse_state_missing_address_returns_none():
    raw = {"display_name": "1, Main Street, 12345"}
    assert geocode._parse_state(raw) is None
