"""Rain garden sizing calculations.

Pure, dependency-free port of the sizing math from the Hex notebook
``notebooks/DIY Rain Garden Calculator_20260624.yaml``. Every function here is a
pure function over its arguments: no global state, no notebook/Hex/pandas/numpy
dependencies, and no I/O. Values the notebook derives from out-of-scope
precipitation data (the one-hour extreme precipitation rate and the annual
precipitation total) are passed in as explicit parameters.

The soil x depth-band factor table below is transcribed cell-for-cell from
``data/RainGarden-SizeFactors.csv`` (UW-Extension Table 1, rain gardens < 30 ft
from the downspout). It is applied universally: distance from the foundation no
longer selects a factor (it is advisory-only now), and depth is a user tradeoff
across three fixed options rather than a value derived from the area.
"""

from __future__ import annotations

import math

# --- Constants and lookup tables ---------------------------------------------

#: The three depth options always offered, in displayed inches (approximate: a
#: hand-dug basin isn't uniform, and 4" and 5" both fall in the 3-5" band).
DEPTH_OPTIONS: tuple[int, ...] = (4, 6, 8)

#: Displayed depth (inches) -> CSV depth-band key.
_DEPTH_BAND: dict[int, str] = {4: "3-5", 6: "6-7", 8: "8"}

#: Soil x depth-band sizing factors, transcribed from
#: data/RainGarden-SizeFactors.csv. area = catchment_area * factor(soil, band).
#: Deeper band -> smaller factor -> more compact footprint.
SIZE_FACTORS_BY_DEPTH: dict[str, dict[str, float]] = {
    "Sandy": {"3-5": 0.19, "6-7": 0.15, "8": 0.08},
    "Loamy": {"3-5": 0.32, "6-7": 0.24, "8": 0.15},
    "Silty": {"3-5": 0.34, "6-7": 0.25, "8": 0.16},
    "Clayey": {"3-5": 0.43, "6-7": 0.32, "8": 0.20},
}

#: Gallons of water in a 1-inch-deep layer over 1 square inch of area.
GALLONS_PER_CUBIC_INCH = 0.004329

#: Assumed footprint (feet) allotted to each plant, square.
PLANT_WIDTH_FT = 1.33

#: Percolation rates above this are treated as data-entry errors and capped.
MAX_PERC_RATE = 18.0


# --- Sizing factor -----------------------------------------------------------

def parse_perc_rate(perc_input: str | None) -> float | None:
    """Coerce a free-text percolation-rate input to a float (inches/hour).

    Keeps only digits and the decimal point (so "1.5 in/hr" -> 1.5), caps
    implausibly high values at :data:`MAX_PERC_RATE`, and returns ``None`` for
    empty/blank input. Ported from the notebook's ``getPercRate``.
    """
    if not perc_input:
        return None
    numeric_part = "".join(ch for ch in perc_input if ch.isdigit() or ch == ".")
    if not numeric_part:
        return None
    rate = float(numeric_part)
    if rate > MAX_PERC_RATE:
        rate = MAX_PERC_RATE
    return rate


def depth_band(depth_in: int) -> str:
    """CSV depth-band key for a displayed depth option (4/6/8 inches)."""
    return _DEPTH_BAND[depth_in]


def size_factor(soil_type: str, band: str) -> float:
    """Sizing factor for a soil type and depth band (see SIZE_FACTORS_BY_DEPTH).

    ``soil_type`` must be one of Sandy/Loamy/Silty/Clayey; the tool layer maps an
    undetermined soil to Clayey (the most conservative column) before calling.
    """
    return SIZE_FACTORS_BY_DEPTH[soil_type][band]


# --- Dimensions --------------------------------------------------------------

def rain_garden_area(catchment_sa: float, sizing_factor: float) -> float:
    """Recommended rain garden area (sq ft) = catchment area * sizing factor."""
    return catchment_sa * sizing_factor


def garden_dimensions(area: float) -> dict[str, float]:
    """Suggested footprint dimensions (feet) for a given area.

    Returns raw (unrounded) values; rounding is left to the caller/display.

    * ``length`` / ``width``: elongated garden where width is twice the length
      (DOEE recommendation), i.e. length = sqrt(area / 2), width = 2 * length.
    * ``side``: balanced (near-square) garden, side = sqrt(area) (5 Counties).
    """
    length = math.sqrt(area / 2)
    width = length * 2
    side = math.sqrt(area)
    return {"length": length, "width": width, "side": side}


# --- Plants ------------------------------------------------------------------

def plant_counts(length: float, width: float, area: float) -> dict[str, float]:
    """Suggested plant counts for the interior and perimeter of the garden.

    Each plant is allotted a ``PLANT_WIDTH_FT`` square. The interior is the area
    inset by one plant-width on each side; the perimeter is the remainder. Uses
    the unrounded ``length``/``width`` from :func:`garden_dimensions`. Counts are
    returned unrounded; round for display.

    For very small gardens the notebook's formula yields a *negative* interior
    area (e.g. a ~3 sq ft garden insets to below zero on each side); the notebook
    leaves this unguarded. We keep the same formula but clamp the interior and
    perimeter areas — and therefore the counts — at zero so neither can go
    negative.
    """
    plant_area = PLANT_WIDTH_FT * PLANT_WIDTH_FT
    interior_area = max(0.0, (length - PLANT_WIDTH_FT) * (width - PLANT_WIDTH_FT))
    outer_area = max(0.0, area - interior_area)
    return {
        "interior_area": interior_area,
        "interior_count": interior_area / plant_area,
        "outer_area": outer_area,
        "outer_count": outer_area / plant_area,
    }


# --- Performance estimates ---------------------------------------------------

def drainage_time(
    catchment_sa: float,
    area: float,
    threshold_precip_rate: float,
    perc_rate: float,
) -> float:
    """Hours for the garden to drain a one-hour extreme precipitation event.

    ``threshold_precip_rate`` is the one-hour extreme (e.g. 99.9th percentile)
    precipitation rate in inches/hour, supplied by the (out-of-scope)
    precipitation analysis. Rounded to one decimal place, as in the notebook.
    """
    return round(((catchment_sa / area) * threshold_precip_rate) / perc_rate, 1)


def gallons_diverted(catchment_sa: float, total_precip_yr: float) -> int:
    """Gallons of stormwater the catchment can divert/filter per year.

    ``total_precip_yr`` is the annual precipitation total (inches), supplied by
    the (out-of-scope) precipitation analysis. Rounded to a whole number of
    gallons, as in the notebook.
    """
    return round((catchment_sa * 144) * total_precip_yr * GALLONS_PER_CUBIC_INCH)
