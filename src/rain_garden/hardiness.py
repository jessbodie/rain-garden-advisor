"""USDA Plant Hardiness Zone lookup by zip code.

Ports the notebook's "USDA Hardiness Zone" cell: given a US zip code, look up the
USDA Plant Hardiness Zone (and its minimum temperature range) from the RapidAPI
service, to inform plant selection.

Two deliberate changes from the notebook:

* The API key is read from the ``RAPIDAPI_KEY`` environment variable at call
  time — never hardcoded. (The notebook embedded a real key, which should be
  rotated.)
* Typed exceptions let callers distinguish bad input from API problems from
  misconfiguration:
    - :class:`InvalidZipCodeError` — caller passed a non-5-digit zip.
    - :class:`HardinessZoneNotFoundError` — valid-format zip, but no data.
    - :class:`HardinessAPIError` — auth failure, rate limit, or other HTTP error.
    - :class:`MissingAPIKeyError` — ``RAPIDAPI_KEY`` is not configured.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

API_HOST = "usda-plant-hardiness-zones.p.rapidapi.com"
API_URL = "https://usda-plant-hardiness-zones.p.rapidapi.com/zone/{zip_code}"


class InvalidZipCodeError(ValueError):
    """Raised when the zip code is missing or not a 5-digit string."""


class HardinessZoneNotFoundError(ValueError):
    """Raised when a valid-format zip returns no hardiness data."""


class HardinessAPIError(RuntimeError):
    """Raised on API auth failures, rate limits, or other HTTP errors."""


class MissingAPIKeyError(RuntimeError):
    """Raised when the RAPIDAPI_KEY environment variable is not set."""


def _validate_zip(zip_code) -> str:
    """Return the zip as a string, or raise InvalidZipCodeError."""
    if zip_code is None or not isinstance(zip_code, str) or not (
        zip_code.isdigit() and len(zip_code) == 5
    ):
        raise InvalidZipCodeError(
            f"Zip code must be a 5-digit string; got {zip_code!r}."
        )
    return zip_code


def _fetch(zip_code: str) -> dict:
    """Call the RapidAPI hardiness-zone endpoint and return its JSON."""
    import requests  # lazy: only needed for live calls
    from dotenv import find_dotenv, load_dotenv

    # usecwd=True is robust to how the entrypoint is launched (repo-root script,
    # pytest, etc.) and avoids find_dotenv's frame-walking edge cases.
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "RAPIDAPI_KEY is not set. Add it to your .env file "
            "(see .env.example) to look up hardiness zones."
        )

    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": API_HOST}
    response = requests.get(API_URL.format(zip_code=zip_code), headers=headers, timeout=30)

    if response.status_code == 200:
        return response.json()
    if response.status_code == 404:
        raise HardinessZoneNotFoundError(
            f"No hardiness zone found for zip code {zip_code!r}."
        )
    raise HardinessAPIError(
        f"Hardiness zone API returned HTTP {response.status_code} for zip {zip_code!r}."
    )


def get_hardiness_zone(zip_code: str, fixture: dict | Path | None = None) -> dict:
    """Look up the USDA hardiness zone for ``zip_code``.

    Returns ``{"zone", "min_temp_range", "zip_code"}``. By default this calls the
    live RapidAPI service, reading ``RAPIDAPI_KEY`` from the environment. For
    tests, pass ``fixture`` as a parsed-JSON ``dict`` or a path to a saved
    response; the zip is still validated, but no network call is made.

    Raises :class:`InvalidZipCodeError`, :class:`HardinessZoneNotFoundError`,
    :class:`HardinessAPIError`, or :class:`MissingAPIKeyError`.
    """
    zip_code = _validate_zip(zip_code)

    if fixture is not None:
        data = fixture if isinstance(fixture, dict) else json.loads(
            Path(fixture).read_text(encoding="utf-8")
        )
    else:
        data = _fetch(zip_code)

    zone = data.get("zone") if isinstance(data, dict) else None
    min_temp_range = data.get("min_temp_range") if isinstance(data, dict) else None
    if not zone or not min_temp_range:
        raise HardinessZoneNotFoundError(
            f"No hardiness zone data returned for zip code {zip_code!r}."
        )

    return {"zone": zone, "min_temp_range": min_temp_range, "zip_code": zip_code}


def min_temp_floor(min_temp_range: str) -> int | None:
    """Return the lower bound (°F) of a hardiness zone's temperature range.

    e.g. ``"5 to 10"`` -> ``5``, ``"-30 to -25"`` -> ``-30``. This is the
    location's winter survival floor — the correct value to pass to
    ``plants.filter_plants(local_min_temp=...)``. Returns ``None`` for a
    ``None``/malformed range string (so callers, e.g. the tool layer, can never
    be crashed by an unparseable value).
    """
    match = re.search(r"-?\d+", min_temp_range or "")
    return int(match.group()) if match else None
