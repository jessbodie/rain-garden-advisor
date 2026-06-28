"""Filter rain-garden-appropriate plants for a location, zoned interior/perimeter.

Fifth deterministic module. Works off the merged NWPL + USDA PLANTS dataset
(``nwpl_usda_merged.csv``) and the NWPL region-to-state mapping
(``NWPL_RegionStateMapping.csv``), both packaged under ``rain_garden/data/``.

Pipeline (per state): resolve the NWPL region(s) the state belongs to, keep
plants that are wetland-adapted (OBL/FACW/FAC) in any of those regions, narrow by
moisture/drought tolerance (and optionally min temperature, soil, sun), then zone
each surviving plant interior vs. perimeter by its most-hydrophytic indicator.

No network, no LLM. Empty results are a valid outcome (the caller surfaces
"0 plants match"); only an unrecognized state raises.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

import pandas as pd

# Wetland indicator ranks (most -> least hydrophytic). Also the qualifying set.
WETLAND_RANK = {"OBL": 0, "FACW": 1, "FAC": 2}
# NWPL regions outside the Lower 48.
EXCLUDE_REGIONS = {"CB", "HI", "AK"}
# Indicators that place a plant in the wetter interior; FAC -> perimeter.
INTERIOR = {"OBL", "FACW"}

TEMP_COL = "Temperature, Minimum (°F)"
HEIGHT_COL = "Height at 20 Years, Maximum (feet)"
PLANT_URL_PREFIX = "https://plants.usda.gov/plant-profile/"

_OUTPUT_COLUMNS = [
    "Common Name",
    "Scientific Name",
    "Symbol",
    "URL",
    HEIGHT_COL,
    "Bloom Period",
    "Flower Color",
    "Moisture Use",
    "Drought Tolerance",
    "zone",
]

# Shade Tolerance value kept for each sun preference (null is always kept too).
_SUN_TO_SHADE = {
    "Full sun": "Intolerant",
    "Partial sun": "Intermediate",
    "Mostly shady": "Tolerant",
}


class InvalidStateError(ValueError):
    """Raised when a state resolves to no qualifying Lower-48 NWPL region."""


@lru_cache(maxsize=None)
def _load_plants(path: str | None = None) -> pd.DataFrame:
    """Load the merged NWPL+USDA plant dataset (cached). Read-only — copy to mutate."""
    source = path or files("rain_garden.data") / "nwpl_usda_merged.csv"
    return pd.read_csv(source)


@lru_cache(maxsize=None)
def _load_mapping(path: str | None = None) -> pd.DataFrame:
    """Load the NWPL region-to-state mapping (cached)."""
    source = path or files("rain_garden.data") / "NWPL_RegionStateMapping.csv"
    return pd.read_csv(source)


def regions_for_state(state: str) -> list[str]:
    """Return the Lower-48 NWPL regions a state belongs to, in mapping-file order.

    Excludes non-Lower-48 regions (``EXCLUDE_REGIONS``). Raises
    :class:`InvalidStateError` if the state matches no qualifying region.
    """
    key = state.strip().upper() if isinstance(state, str) else state
    mapping = _load_mapping()
    regions: list[str] = []
    for _, row in mapping.iterrows():
        region = row["Region Abbreviation"]
        if region in EXCLUDE_REGIONS:
            continue
        states = [s.strip() for s in str(row["States"]).split(",")]
        if key in states:
            regions.append(region)
    if not regions:
        raise InvalidStateError(
            f"{state!r} is not a recognized Lower-48 state abbreviation."
        )
    return regions


def _resolved_indicator(row, regions: list[str]) -> str | None:
    """Most-hydrophytic wetland code for a plant across the given regions, or None."""
    codes = [row[r] for r in regions if row[r] in WETLAND_RANK]
    if not codes:
        return None
    return min(codes, key=WETLAND_RANK.get)


def filter_plants(
    state: str,
    *,
    wetland_indicators: tuple[str, ...] = ("OBL", "FACW", "FAC"),
    moisture: tuple[str, ...] = ("High", "Medium"),
    drought: tuple[str, ...] = ("High", "Medium"),
    local_min_temp: float | None = None,
    soil_type: str | None = None,
    sun: str | None = None,
    data=None,
) -> pd.DataFrame:
    """Filter plants for ``state`` and zone them interior vs. perimeter.

    ``local_min_temp`` is the location's winter survival floor (°F) — the **lower
    bound of its USDA hardiness zone** (e.g. zone 7b → 5). When supplied, a plant
    qualifies if its rated minimum temperature is at or below that floor, i.e. it
    is hardy enough to survive the local winter. (The source notebook had this
    comparison inverted — and used wind-chill apparent temperature, a comfort
    metric — which kept the cold-tender plants and discarded the hardy ones.)

    ``data`` (optional) injects a plant DataFrame or a path to one, bypassing the
    packaged dataset (mirrors the fixture-injection pattern in other modules).
    Returns curated columns only; the raw OBL/FACW/FAC codes are never exposed.
    An empty result is valid (not an error).
    """
    regions = regions_for_state(state)

    if isinstance(data, pd.DataFrame):
        source = data
    elif data is not None:
        source = _load_plants(str(data))
    else:
        source = _load_plants()
    # The cached/injected frame is read-only; copy before adding any column.
    d = source.copy()

    # Wetland union: keep plants qualifying in ANY of the state's regions.
    d = d[d[regions].isin(wetland_indicators).any(axis=1)]
    # Moisture / drought tolerance (NaN-characteristic rows drop by design).
    d = d[d["Moisture Use"].isin(moisture)]
    d = d[d["Drought Tolerance"].isin(drought)]

    if local_min_temp is not None:
        # Keep plants hardy enough for the local winter floor: a plant survives
        # if its rated minimum temperature is at or below the floor. NaN <= x is
        # False, so plants with no min-temp data are excluded while filtering.
        temp = pd.to_numeric(d[TEMP_COL], errors="coerce")
        d = d[temp <= local_min_temp]

    if soil_type == "Clayey":
        d = d[d["Adapted to Fine Textured Soils"] == "Yes"]
    elif soil_type == "Sandy":
        d = d[d["Adapted to Coarse Textured Soils"] == "Yes"]

    if sun in _SUN_TO_SHADE:
        keep = _SUN_TO_SHADE[sun]
        d = d[d["Shade Tolerance"].isin([keep]) | d["Shade Tolerance"].isnull()]

    if d.empty:
        zone = pd.Series(dtype="object")
    else:
        zone = d.apply(
            lambda row: "interior" if _resolved_indicator(row, regions) in INTERIOR
            else "perimeter",
            axis=1,
        )

    out = pd.DataFrame(
        {
            "Common Name": d["Common Name"],
            "Scientific Name": d["Scientific Name"],
            "Symbol": d["Symbol"],
            "URL": PLANT_URL_PREFIX + d["Symbol"].astype(str),
            HEIGHT_COL: d[HEIGHT_COL],
            "Bloom Period": d["Bloom Period"],
            "Flower Color": d["Flower Color"],
            "Moisture Use": d["Moisture Use"],
            "Drought Tolerance": d["Drought Tolerance"],
            "zone": zone,
        }
    )
    return out[_OUTPUT_COLUMNS].reset_index(drop=True)


def split_by_zone(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a filtered plant frame into (interior, perimeter) by the ``zone`` column."""
    interior = df[df["zone"] == "interior"].reset_index(drop=True)
    perimeter = df[df["zone"] == "perimeter"].reset_index(drop=True)
    return interior, perimeter
