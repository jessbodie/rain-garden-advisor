"""Rain garden sizing calculations.

Pure, dependency-free port of the sizing math from the Hex notebook
``notebooks/DIY Rain Garden Calculator_20260624.yaml``. Every function here is a
pure function over its arguments: no global state, no notebook/Hex/pandas/numpy
dependencies, and no I/O. Values the notebook derives from out-of-scope
precipitation data (the one-hour extreme precipitation rate and the annual
precipitation total) are passed in as explicit parameters.

Lookup tables below are transcribed from the notebook. The soil sizing factors
for the "Less than 30 ft" distance are derived in the notebook from
``data/RainGarden-SizeFactors.csv`` as ``round((d_6_7 + d_8) / 2, 2)`` per soil
type; those results are precomputed and inlined here so this module reads no CSV
at runtime.
"""

from __future__ import annotations

import math

# --- Constants and lookup tables (transcribed from the notebook) -------------

#: Soil-type sizing factors keyed by distance from the foundation.
#: "More than 30 ft" column: Washington, D.C. DOEE rain garden size factors.
#: "Less than 30 ft" column: precomputed from data/RainGarden-SizeFactors.csv as
#: round((6-7" deep + 8" deep) / 2, 2) per soil type.
SOIL_SIZING_FACTORS: dict[str, dict[str, float]] = {
    "Sandy": {"More than 30 ft": 0.03, "Less than 30 ft": 0.11},
    "Silty": {"More than 30 ft": 0.06, "Less than 30 ft": 0.21},
    "Clayey": {"More than 30 ft": 0.10, "Less than 30 ft": 0.26},
}

#: Sizing factors based on measured infiltration (percolation) rate.
#: Each row is (min_rate, max_rate, sizing_factor); a rate matches when
#: min_rate <= rate <= max_rate. Source: 5 Counties rain garden guide, p.5.
RATE_SIZING_TABLE: tuple[tuple[float, float, float], ...] = (
    (0.5, 0.9, 0.09),
    (1.0, 1.4, 0.05),
    (1.5, 1.9, 0.04),
    (2.0, 5.9, 0.03),
    (6.0, 11.9, 0.02),
    (12.0, 18.0, 0.01),
)

#: Minimum rain garden geometry: ponding depth (inches) -> minimum area (sq ft).
#: Source: 5 Counties rain garden guide, p.5.
GEOMETRY_TABLE: dict[int, float] = {
    6: 9.0,
    7: 12.3,
    8: 16.0,
    9: 20.3,
    10: 25.0,
    11: 30.3,
    12: 36.0,
}

#: Gallons of water in a 1-inch-deep layer over 1 square inch of area.
GALLONS_PER_CUBIC_INCH = 0.004329

#: Assumed footprint (feet) allotted to each plant, square.
PLANT_WIDTH_FT = 1.33

#: Percolation rates above this are treated as data-entry errors and capped.
MAX_PERC_RATE = 18.0

#: Input soil-type labels mapped to the key used for soil-factor lookup.
#: Loamy / Silty / unknown have no dedicated factor, so they use Silty (mid-range).
_SOIL_LOOKUP = {
    "Sandy": "Sandy",
    "Clayey": "Clayey",
    "Silty": "Silty",
    "Loamy": "Silty",
    "I'm not sure": "Silty",
}


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


def soil_sizing_factor(soil_type: str, distance: str) -> float:
    """Return the sizing factor for a soil type and distance from the foundation.

    ``distance == "More than 30 ft"`` uses the more-than-30 column; any other
    distance ("10-30 ft", "Less than 10 ft") uses the less-than-30 column.
    Ported from the notebook's ``getSoilSizingFactor``.
    """
    column = "More than 30 ft" if distance == "More than 30 ft" else "Less than 30 ft"
    return SOIL_SIZING_FACTORS[soil_type][column]


def rate_sizing_factor(rate: float) -> float | None:
    """Return the sizing factor for a measured percolation rate, or ``None``.

    Returns the first table band where ``min <= rate <= max``; ``None`` if the
    rate falls in no band. Ported from the notebook's ``getRateSizingFactor``.
    """
    for min_rate, max_rate, factor in RATE_SIZING_TABLE:
        if min_rate <= rate <= max_rate:
            return factor
    return None


def resolve_sizing_factor(
    soil_type: str, distance: str, perc_rate: float | None
) -> float:
    """Choose the sizing factor from a measured rate when available, else soil.

    Mirrors the notebook's selection logic:

    * No usable rate -> soil-type factor (unknown/Loamy/Silty fall back to Silty).
    * Rate below 0.5 in/hr -> a rain garden isn't recommended; fall back to the
      Silty soil factor so a number is still produced.
    * Rate >= 0.5 in/hr -> rate-table factor, falling back to the Silty soil
      factor when the rate matches no band.
    """
    lookup = _SOIL_LOOKUP.get(soil_type, "Silty")

    if perc_rate is None:
        return soil_sizing_factor(lookup, distance)

    if 0 < perc_rate < 0.5:
        return soil_sizing_factor("Silty", distance)

    factor = rate_sizing_factor(perc_rate)
    if factor is None:
        return soil_sizing_factor("Silty", distance)
    return factor


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


def recommended_depth(area: float) -> int:
    """Ponding depth (inches) whose table minimum-area is closest to ``area``.

    Closest by absolute difference; ties resolve to the first (shallowest)
    matching row, matching the notebook's pandas ``idxmin`` behavior. Ported
    from the notebook's ``getDepth``.
    """
    return min(GEOMETRY_TABLE, key=lambda depth: abs(GEOMETRY_TABLE[depth] - area))


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
