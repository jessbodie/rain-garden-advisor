"""Tests for rain_garden.sizing.

Sizing now uses a single soil x depth-band factor table (UW-Extension Table 1,
transcribed from data/RainGarden-SizeFactors.csv). Distance no longer selects a
factor, and depth is a fixed set of user options rather than an area-derived value.
The area and plant-count formulas are unchanged from the notebook port.
"""

import math

import pytest

from rain_garden import sizing


# --- Depth-band mapping ------------------------------------------------------

def test_depth_options_and_bands():
    assert sizing.DEPTH_OPTIONS == (4, 6, 8)
    assert sizing.depth_band(4) == "3-5"
    assert sizing.depth_band(6) == "6-7"
    assert sizing.depth_band(8) == "8"


# --- Soil x depth-band factor table ------------------------------------------

@pytest.mark.parametrize(
    "soil, band, expected",
    [
        ("Sandy", "3-5", 0.19), ("Sandy", "6-7", 0.15), ("Sandy", "8", 0.08),
        ("Loamy", "3-5", 0.32), ("Loamy", "6-7", 0.24), ("Loamy", "8", 0.15),
        ("Silty", "3-5", 0.34), ("Silty", "6-7", 0.25), ("Silty", "8", 0.16),
        ("Clayey", "3-5", 0.43), ("Clayey", "6-7", 0.32), ("Clayey", "8", 0.20),
    ],
)
def test_size_factor_table(soil, band, expected):
    assert sizing.size_factor(soil, band) == expected


def test_deeper_band_has_smaller_factor():
    for soil in ("Sandy", "Loamy", "Silty", "Clayey"):
        f = [sizing.size_factor(soil, b) for b in ("3-5", "6-7", "8")]
        assert f[0] > f[1] > f[2]


# --- Area = catchment * factor -----------------------------------------------

def test_rain_garden_area():
    assert sizing.rain_garden_area(700, 0.34) == pytest.approx(238.0)
    assert sizing.rain_garden_area(700, 0.25) == pytest.approx(175.0)
    assert sizing.rain_garden_area(700, 0.16) == pytest.approx(112.0)


# --- Dimensions (elongated 2:1 shape, unchanged) -----------------------------

def test_garden_dimensions():
    dims = sizing.garden_dimensions(42.0)
    assert round(dims["length"]) == 5
    assert round(dims["width"]) == 9
    assert round(dims["side"]) == 6
    assert dims["length"] == pytest.approx(math.sqrt(21))
    assert dims["width"] == pytest.approx(2 * math.sqrt(21))


# --- Plant counts (unchanged formula; notebook-verified oracles) -------------

def test_plant_counts_example():
    dims = sizing.garden_dimensions(42.0)
    counts = sizing.plant_counts(dims["length"], dims["width"], 42.0)
    assert counts["interior_area"] == pytest.approx(25.5, abs=0.1)
    assert round(counts["interior_count"]) == 14
    assert counts["outer_area"] == pytest.approx(16.5, abs=0.1)
    assert round(counts["outer_count"]) == 9


def test_plant_counts_small_garden_is_guarded():
    # A ~3 sq ft garden would inset to a negative interior; the guard clamps to 0.
    dims = sizing.garden_dimensions(3.0)
    counts = sizing.plant_counts(dims["length"], dims["width"], 3.0)
    assert counts["interior_area"] == 0.0
    assert counts["interior_count"] >= 0
    assert counts["outer_count"] >= 0


# --- parse_perc_rate (unchanged) ---------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", None),
        (None, None),
        ("   ", None),
        ("abc", None),
        ("1.5", 1.5),
        ("1.5 in/hr", 1.5),
        ("0.5", 0.5),
        ("99", 18.0),  # capped at MAX_PERC_RATE
        ("20", 18.0),
    ],
)
def test_parse_perc_rate(raw, expected):
    assert sizing.parse_perc_rate(raw) == expected


# --- Performance estimates (unchanged) ---------------------------------------

def test_gallons_diverted():
    # round(700 * 144 * 40 * 0.004329) == 17455
    assert sizing.gallons_diverted(700, total_precip_yr=40) == 17455
    # round(700 * 144 * 45.0 * 0.004329) == 19636
    assert sizing.gallons_diverted(700, total_precip_yr=45.0) == 19636


def test_drainage_time_helper_still_available():
    # Kept for the deferred per-depth drain-down work, though not called by the tool.
    assert sizing.drainage_time(700, 35, threshold_precip_rate=0.80, perc_rate=1.0) == 16.0
