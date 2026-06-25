"""Tests for rain_garden.precipitation.

No network: the three scalars are asserted against a saved real Open-Meteo
response for Brooklyn (lat 40.6501, lon -73.9496). The expected literals were
computed from that fixture and cross-checked against the notebook's pandas logic
(Series.quantile(0.999) / .sum() / .min()).
"""

import json
from pathlib import Path

import pytest

from rain_garden import precipitation

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "open_meteo_brooklyn.json"
BROOKLYN = (40.6501, -73.9496)

# Expected values computed from the saved Brooklyn fixture.
EXPECTED_THRESHOLD = 0.323
EXPECTED_TOTAL_PRECIP_YR = 43
EXPECTED_MIN_APPARENT_TEMP = -11.8


@pytest.fixture
def brooklyn_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_stats_from_dict_fixture(brooklyn_data):
    stats = precipitation.get_precipitation_stats(*BROOKLYN, fixture=brooklyn_data)
    assert stats["threshold_precip_rate"] == pytest.approx(EXPECTED_THRESHOLD)
    assert stats["total_precip_yr"] == EXPECTED_TOTAL_PRECIP_YR
    assert stats["min_apparent_temp"] == pytest.approx(EXPECTED_MIN_APPARENT_TEMP)


def test_stats_from_path_fixture():
    # fixture may also be a path to a JSON file
    stats = precipitation.get_precipitation_stats(*BROOKLYN, fixture=FIXTURE_PATH)
    assert stats == {
        "threshold_precip_rate": pytest.approx(EXPECTED_THRESHOLD),
        "total_precip_yr": EXPECTED_TOTAL_PRECIP_YR,
        "min_apparent_temp": pytest.approx(EXPECTED_MIN_APPARENT_TEMP),
    }


def test_returns_expected_keys(brooklyn_data):
    stats = precipitation.get_precipitation_stats(*BROOKLYN, fixture=brooklyn_data)
    assert set(stats) == {"threshold_precip_rate", "total_precip_yr", "min_apparent_temp"}


def test_none_values_are_skipped():
    # A None in any series must be ignored, matching pandas' NaN-skipping.
    base = {
        "hourly": {"precipitation": [0.0, 0.1, 0.2, 0.3, 0.4]},
        "daily": {
            "precipitation_sum": [1.0, 2.0, 3.0],
            "apparent_temperature_min": [40.0, 30.0, 20.0],
        },
    }
    with_none = {
        "hourly": {"precipitation": [0.0, 0.1, 0.2, 0.3, 0.4, None]},
        "daily": {
            "precipitation_sum": [1.0, 2.0, 3.0, None],
            "apparent_temperature_min": [40.0, 30.0, 20.0, None],
        },
    }
    assert precipitation._compute_stats(with_none) == precipitation._compute_stats(base)
