"""Roof-footprint area estimate from the Google Solar API.

Given a lat/lon (already resolved by the geocoding step), fetch the building's
whole-roof *footprint* from the Solar API ``buildingInsights.findClosest``
endpoint and convert it to square feet. This is offered to the user as reference
context when we ask for their catchment area — it is additive, never required.

Two deliberate design choices distinguish this module from the other API modules
(``hardiness.py``, ``precipitation.py``):

* **Footprint, not surface area.** We read ``wholeRoofStats.groundAreaMeters2``
  (the horizontal footprint), NOT ``areaMeters2`` (the sloped surface area). Rain
  falls vertically, so the volume a roof intercepts is a function of its footprint;
  using the larger sloped area would overestimate catchment and oversize the garden.

* **Every failure degrades to ``None`` — never raises.** No building found, no
  coverage in the region, an HTTP/timeout error, a malformed response, or even a
  missing ``GOOGLE_SOLAR_API_KEY`` all collapse to ``None``. Because the estimate is
  reference context and not a required input, a gap here must never halt the
  conversation (unlike ``hardiness.py``, where a missing key is fatal).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# buildingInsights.findClosest — nearest building to a lat/lon (US/Europe/Oceania
# coverage, not universal). See error handling: no-coverage is a normal None.
API_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"

# m² -> sq ft. Independently derivable oracle (the constant itself); do not treat
# as tunable. Estimates are rounded to the nearest 10 sq ft before use — the source
# resolution doesn't justify more precision, and it reads as an estimate, not a spec.
SQFT_PER_SQM = 10.7639
ROUND_TO = 10


class MissingAPIKeyError(RuntimeError):
    """Raised internally when GOOGLE_SOLAR_API_KEY is unset.

    Never propagates to callers of :func:`estimate_roof_area` — it is caught and
    logged there, then collapsed to ``None`` like every other failure mode.
    """


def _fetch(lat: float, lon: float, timeout_s: float) -> dict:
    """Call the Solar API and return its parsed JSON, or raise."""
    import requests  # lazy: only needed for live calls, not for fixture/tests
    from dotenv import find_dotenv, load_dotenv

    # usecwd=True mirrors the other API modules — robust to how the entrypoint is
    # launched (repo-root script, pytest, etc.).
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.getenv("GOOGLE_SOLAR_API_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "GOOGLE_SOLAR_API_KEY is not set. Add it to your .env file "
            "(see .env.example) to enable satellite roof-area estimates."
        )

    params = {
        "location.latitude": lat,
        "location.longitude": lon,
        "key": api_key,
    }
    response = requests.get(API_URL, params=params, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def _imagery_date(data: dict) -> str | None:
    """Format the Solar API's ``imageryDate`` (a {year,month,day} object) as text.

    Returns ``"YYYY-MM-DD"`` when full, the year alone if only that is present, or
    ``None``. For disclosure only — never feeds a computed value.
    """
    parts = (data or {}).get("imageryDate") or {}
    year = parts.get("year")
    if not year:
        return None
    month, day = parts.get("month"), parts.get("day")
    if month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    return str(year)


def _parse(data: dict) -> dict | None:
    """Extract the roof footprint (sq ft, rounded to nearest 10) from a response.

    Returns ``None`` when the response carries no whole-roof footprint (e.g. a
    no-building result), so the caller's normal no-estimate path fires.
    """
    stats = ((data or {}).get("solarPotential") or {}).get("wholeRoofStats") or {}
    ground_m2 = stats.get("groundAreaMeters2")
    if ground_m2 is None:
        return None
    raw_sqft = float(ground_m2) * SQFT_PER_SQM
    sq_ft = int(round(raw_sqft / ROUND_TO) * ROUND_TO)
    return {"roof_sqft": sq_ft, "imagery_date": _imagery_date(data)}


def estimate_roof_area(
    lat: float,
    lon: float,
    timeout_s: float = 5.0,
    fixture: dict | Path | None = None,
) -> dict | None:
    """Estimate a building's roof footprint at ``lat``/``lon``.

    Returns ``{"roof_sqft": <int, rounded to nearest 10>, "imagery_date": str|None}``
    or ``None``. By default this calls the live Google Solar API, reading
    ``GOOGLE_SOLAR_API_KEY`` from the environment; for tests, pass ``fixture`` as a
    parsed-JSON ``dict`` or a path to a saved response and no network call is made.

    Never raises: no building, no regional coverage, an HTTP error, a timeout, a
    malformed response, or a missing API key all return ``None`` (a warning is
    logged). Callers treat ``None`` as "no estimate available."
    """
    try:
        if fixture is not None:
            data = fixture if isinstance(fixture, dict) else json.loads(
                Path(fixture).read_text(encoding="utf-8")
            )
        else:
            data = _fetch(lat, lon, timeout_s)
        return _parse(data)
    except MissingAPIKeyError as exc:
        logger.warning("Roof-area estimate skipped: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — any failure degrades to no-estimate
        logger.warning("Roof-area estimate failed (%s): %s", type(exc).__name__, exc)
        return None
