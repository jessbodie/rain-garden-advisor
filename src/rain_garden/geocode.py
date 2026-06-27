"""Geocode an address to coordinates via Nominatim (OpenStreetMap).

Ports the notebook's "Convert address to latitude and longitude" cell: geocode
an address and return its canonical form, latitude, longitude, and US zip code.
The notebook's Hex-specific ``address.json`` save/load fallback is intentionally
omitted — this function just geocodes and returns.

Zip and state are read from Nominatim's structured ``address`` fields, gated on
a US ``country_code``: ``address.postcode`` (sliced to 5 digits to handle ZIP+4)
and ``address.ISO3166-2-lvl4`` (e.g. ``"US-NY"`` -> ``"NY"``). International
results return ``None`` for both, even when their canonical address contains a
5-digit token (e.g. a French ``75007`` postcode).
"""

from __future__ import annotations

import json
from pathlib import Path

# Nominatim's usage policy requires a descriptive, non-personal User-Agent.
USER_AGENT = "rain-garden-advisor/0.1"


class AddressNotFoundError(ValueError):
    """Raised when Nominatim returns no match for an address."""


def _parse_zip(raw: dict) -> str | None:
    """Return the 5-digit US zip from a Nominatim result, else ``None``.

    Reads the structured ``address.postcode`` field, gated on a US
    ``country_code``. The first five characters are taken so a ZIP+4 value
    (e.g. ``"11209-1234"``) is normalized to ``"11209"``.
    """
    address = raw.get("address", {})
    if address.get("country_code") != "us":
        return None
    postcode = address.get("postcode")
    return postcode[:5] if postcode else None


def _parse_state(raw: dict) -> str | None:
    """Return the two-letter US state abbreviation, else ``None``.

    Extracted from the structured ``address.ISO3166-2-lvl4`` field
    (e.g. ``"US-NY"`` -> ``"NY"``). Returns ``None`` for non-US results or when
    the field is absent.
    """
    address = raw.get("address", {})
    if address.get("country_code") != "us":
        return None
    iso = address.get("ISO3166-2-lvl4")
    if not iso or not iso.startswith("US-"):
        return None
    return iso[3:]


def _build_result(raw: dict) -> dict:
    """Build the public result dict from a raw Nominatim result."""
    address = raw["display_name"]
    return {
        "address": address,
        "lat": float(raw["lat"]),
        "lon": float(raw["lon"]),
        "zip_code": _parse_zip(raw),
        "state": _parse_state(raw),
    }


def _geocode_live(address: str) -> dict | None:
    """Geocode via Nominatim, returning the raw result dict or ``None``."""
    from geopy.geocoders import Nominatim  # lazy: only needed for live calls

    geolocator = Nominatim(user_agent=USER_AGENT)
    location = geolocator.geocode(address, addressdetails=True)
    return location.raw if location is not None else None


def geocode_address(address: str, fixture: dict | Path | None = None) -> dict:
    """Geocode ``address`` to ``{address, lat, lon, zip_code, state}``.

    By default this calls Nominatim live (no API key). For tests, pass
    ``fixture`` as a parsed-JSON ``dict`` or a path to a saved Nominatim
    response; when given, no network call is made.

    Raises :class:`AddressNotFoundError` when no match is found (never returns
    ``None`` — a silent ``None`` gets swallowed downstream).
    """
    if fixture is not None:
        raw = fixture if isinstance(fixture, (dict, list)) else json.loads(
            Path(fixture).read_text(encoding="utf-8")
        )
    else:
        raw = _geocode_live(address)

    if not raw:
        raise AddressNotFoundError(f"No match found for address: {address!r}")
    if isinstance(raw, list):
        raw = raw[0]
    return _build_result(raw)
