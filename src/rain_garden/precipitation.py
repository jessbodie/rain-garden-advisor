"""Precipitation statistics from the Open-Meteo historical archive.

Ports only the three scalar values the sizing/plants logic consumes, from the
notebook's PRECIPITATION cells:

* ``threshold_precip_rate`` — 99.9th-percentile hourly precipitation (inches),
  used to estimate drainage time.
* ``total_precip_yr`` — average annual precipitation total (inches), used to
  estimate gallons of stormwater diverted per year.
* ``min_apparent_temp`` — minimum apparent temperature over the period (°F),
  used (in V2) to filter plants by cold tolerance.

Charts, percentile curves, daily/hourly averages, and the ``MIN_PRECIP``
filtering from the notebook are presentation/analysis and are intentionally
excluded (V2).
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# Constants from the notebook's "Set Constant Variables" cell.
NUM_YEARS = 2
PERCENTILE_THRESHOLD_EXTREME = 0.999

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "America/New_York"
# Open-Meteo's archive lags ~5 days behind today.
ARCHIVE_LAG_DAYS = 5


def _date_range(today: date | None = None) -> tuple[str, str]:
    """Return (start_date, end_date) strings for the 2-year archive window.

    Mirrors the notebook: the window ends 5 days before today and spans
    ``NUM_YEARS`` years (365 days each).
    """
    today = today or date.today()
    end = today - timedelta(days=ARCHIVE_LAG_DAYS)
    start = end - timedelta(days=365 * NUM_YEARS)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _clean(values: list) -> list[float]:
    """Drop ``None``/NaN, matching pandas' NaN-skipping reductions."""
    return [v for v in values if v is not None and not math.isnan(v)]


def _compute_stats(data: dict) -> dict:
    """Compute the three scalar values from a raw Open-Meteo response dict."""
    hourly_precip = _clean(data["hourly"]["precipitation"])
    daily_precip = _clean(data["daily"]["precipitation_sum"])
    daily_min_temp = _clean(data["daily"]["apparent_temperature_min"])

    # numpy's default method="linear" is what pandas.Series.quantile delegates to.
    threshold_precip_rate = float(np.quantile(hourly_precip, PERCENTILE_THRESHOLD_EXTREME))
    total_precip_yr = round(sum(daily_precip) / NUM_YEARS)
    min_apparent_temp = min(daily_min_temp)

    return {
        "threshold_precip_rate": threshold_precip_rate,
        "total_precip_yr": total_precip_yr,
        "min_apparent_temp": min_apparent_temp,
    }


def _fetch(lat: float, lon: float) -> dict:
    """Fetch a raw archive response for a location over the 2-year window."""
    import requests  # lazy: only needed for live calls, not for fixture/tests

    start_date, end_date = _date_range()
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "precipitation",
        "daily": "apparent_temperature_min,precipitation_sum",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": TIMEZONE,
    }
    response = requests.get(ARCHIVE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def get_precipitation_stats(lat: float, lon: float, fixture=None) -> dict:
    """Return ``{threshold_precip_rate, total_precip_yr, min_apparent_temp}``.

    By default this fetches live data from the Open-Meteo archive (no API key).
    For tests, pass ``fixture`` as either a parsed-JSON ``dict`` or a path to a
    saved JSON response; when given, no network call is made.
    """
    if fixture is not None:
        if isinstance(fixture, dict):
            data = fixture
        else:
            data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    else:
        data = _fetch(lat, lon)
    return _compute_stats(data)
