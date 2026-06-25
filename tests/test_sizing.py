"""Parity tests for rain_garden.sizing against the source Hex notebook.

The primary example uses the notebook's default inputs: a 700 sq ft catchment,
Silty soil, more than 30 ft from the foundation, with no measured percolation
rate. Expected outputs were verified against the notebook's formulas.
"""

import math

import pytest

from rain_garden import sizing

# Notebook default example inputs.
CATCHMENT = 700
SOIL = "Silty"
DISTANCE = "More than 30 ft"


# --- Primary example (notebook defaults) -------------------------------------

def test_example_sizing_factor():
    assert sizing.soil_sizing_factor(SOIL, DISTANCE) == 0.06


def test_example_resolve_sizing_factor_no_perc_rate():
    # With no percolation rate, the factor comes from soil + distance.
    assert sizing.resolve_sizing_factor(SOIL, DISTANCE, perc_rate=None) == 0.06


def test_example_area():
    assert sizing.rain_garden_area(CATCHMENT, 0.06) == 42.0


def test_example_dimensions():
    dims = sizing.garden_dimensions(42.0)
    assert round(dims["length"]) == 5
    assert round(dims["width"]) == 9
    assert round(dims["side"]) == 6
    # Sanity-check the raw geometry the rounding comes from.
    assert dims["length"] == pytest.approx(math.sqrt(21))
    assert dims["width"] == pytest.approx(2 * math.sqrt(21))


def test_example_depth():
    assert sizing.recommended_depth(42.0) == 12


def test_example_plant_counts():
    dims = sizing.garden_dimensions(42.0)
    counts = sizing.plant_counts(dims["length"], dims["width"], 42.0)
    assert counts["interior_area"] == pytest.approx(25.5, abs=0.1)
    assert round(counts["interior_count"]) == 14
    assert counts["outer_area"] == pytest.approx(16.5, abs=0.1)
    assert round(counts["outer_count"]) == 9


def test_example_gallons_diverted():
    # round(700 * 144 * 40 * 0.004329) == 17455
    assert sizing.gallons_diverted(CATCHMENT, total_precip_yr=40) == 17455


def test_example_drainage_time():
    # round(((700 / 42) * 1.0) / 1.0, 1) == 16.7
    assert sizing.drainage_time(CATCHMENT, 42.0, threshold_precip_rate=1.0, perc_rate=1.0) == 16.7


# --- Soil sizing factor table (all soil x distance combos) -------------------

@pytest.mark.parametrize(
    "soil, distance, expected",
    [
        ("Sandy", "More than 30 ft", 0.03),
        ("Silty", "More than 30 ft", 0.06),
        ("Clayey", "More than 30 ft", 0.10),
        ("Sandy", "10-30 ft", 0.11),
        ("Silty", "10-30 ft", 0.21),
        ("Clayey", "10-30 ft", 0.26),
        ("Sandy", "Less than 10 ft", 0.11),
        ("Silty", "Less than 10 ft", 0.21),
        ("Clayey", "Less than 10 ft", 0.26),
    ],
)
def test_soil_sizing_factor_table(soil, distance, expected):
    assert sizing.soil_sizing_factor(soil, distance) == expected


# --- Rate sizing factor bands ------------------------------------------------

@pytest.mark.parametrize(
    "rate, expected",
    [
        (0.5, 0.09),
        (0.9, 0.09),
        (1.0, 0.05),
        (1.4, 0.05),
        (1.5, 0.04),
        (2.0, 0.03),
        (6.0, 0.02),
        (12.0, 0.01),
        (18.0, 0.01),
        (0.4, None),  # below the lowest band
        (0.95, None),  # gap between bands
    ],
)
def test_rate_sizing_factor(rate, expected):
    assert sizing.rate_sizing_factor(rate) == expected


# --- parse_perc_rate ---------------------------------------------------------

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


# --- resolve_sizing_factor branches ------------------------------------------

def test_resolve_unknown_and_loamy_map_to_silty():
    assert sizing.resolve_sizing_factor("I'm not sure", DISTANCE, None) == 0.06
    assert sizing.resolve_sizing_factor("Loamy", DISTANCE, None) == 0.06


def test_resolve_perc_rate_overrides_soil():
    # A measured rate of 1.0 in/hr -> rate table factor 0.05, regardless of soil.
    assert sizing.resolve_sizing_factor("Clayey", DISTANCE, perc_rate=1.0) == 0.05


def test_resolve_low_perc_rate_falls_back_to_silty():
    # Rate below 0.5 -> not recommended; falls back to Silty soil factor.
    assert sizing.resolve_sizing_factor("Sandy", DISTANCE, perc_rate=0.3) == 0.06


def test_resolve_unmatched_rate_band_falls_back_to_silty():
    # 0.95 sits in a gap between bands -> fall back to Silty soil factor.
    assert sizing.resolve_sizing_factor("Sandy", DISTANCE, perc_rate=0.95) == 0.06
