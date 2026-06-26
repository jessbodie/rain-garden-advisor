"""Geocode an address to coordinates via Nominatim (OpenStreetMap).

Ports the notebook's "Convert address to latitude and longitude" cell: geocode
an address and return its canonical form, latitude, longitude, and US zip code.
The notebook's Hex-specific ``address.json`` save/load fallback is intentionally
omitted — this function just geocodes and returns.

Zip parsing is gated on Nominatim's structured ``country_code``: a zip is
returned only for US addresses (``country_code == "us"``); international
addresses return ``None`` even if their canonical address contains a 5-digit
token (e.g. a French ``75007`` postcode).
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

    Only US results (``address.country_code == "us"``) yield a zip; the token is
    found with the notebook's original logic (first 5-digit, all-digit part of
    the canonical address split on ``", "``).
    """
    if raw.get("address", {}).get("country_code") != "us":
        return None
    for part in raw["display_name"].split(", "):
        if part.isdigit() and len(part) == 5:
            return part
    return None


def _build_result(raw: dict) -> dict:
    """Build the public result dict from a raw Nominatim result."""
    address = raw["display_name"]
    return {
        "address": address,
        "lat": float(raw["lat"]),
        "lon": float(raw["lon"]),
        "zip_code": _parse_zip(raw),
    }


def _geocode_live(address: str) -> dict | None:
    """Geocode via Nominatim, returning the raw result dict or ``None``."""
    from geopy.geocoders import Nominatim  # lazy: only needed for live calls

    geolocator = Nominatim(user_agent=USER_AGENT)
    location = geolocator.geocode(address, addressdetails=True)
    return location.raw if location is not None else None


def geocode_address(address: str, fixture: dict | Path | None = None) -> dict:
    """Geocode ``address`` to ``{address, lat, lon, zip_code}``.

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
