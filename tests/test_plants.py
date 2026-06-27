"""Tests for rain_garden.plants.

No network. Runs against the packaged NWPL+USDA dataset. Expected counts are the
oracle independently reproduced from the source data:
  NY -> 74 rows (42 interior, 32 perimeter)   [single region]
  NJ -> 121 rows (62 interior, 59 perimeter)  [multi-region union + min-rank]
"""

from importlib.resources import files

import pandas as pd
import pytest

from rain_garden import plants
from rain_garden.plants import (
    InvalidStateError,
    filter_plants,
    regions_for_state,
    split_by_zone,
)

RAW_CODES = {"OBL", "FACW", "FAC", "FACU", "UPL"}


# --- Region resolution --------------------------------------------------------

def test_regions_for_state_single_region():
    assert regions_for_state("NY") == ["NCNE"]


def test_regions_for_state_multi_region_order():
    assert regions_for_state("NJ") == ["AGCP", "EMP", "NCNE"]


def test_regions_for_state_excluded_region_raises():
    # HI's only region is excluded (non-Lower-48) -> no qualifying region.
    with pytest.raises(InvalidStateError):
        regions_for_state("HI")


def test_regions_for_state_unknown_raises():
    with pytest.raises(InvalidStateError):
        regions_for_state("XX")


# --- Oracle counts ------------------------------------------------------------

def test_ny_counts():
    df = filter_plants("NY")
    assert len(df) == 74
    interior, perimeter = split_by_zone(df)
    assert len(interior) == 42
    assert len(perimeter) == 32


def test_nj_counts():
    df = filter_plants("NJ")
    assert len(df) == 121
    interior, perimeter = split_by_zone(df)
    assert len(interior) == 62
    assert len(perimeter) == 59


def test_split_partitions_all_rows():
    df = filter_plants("NJ")
    interior, perimeter = split_by_zone(df)
    assert len(interior) + len(perimeter) == len(df)


# --- Output shape / no leaked codes ------------------------------------------

def test_output_has_no_raw_wetland_codes():
    df = filter_plants("NY")
    for col in df.columns:
        assert not df[col].isin(RAW_CODES).any(), f"raw code leaked in column {col!r}"


def test_url_built_from_symbol():
    df = filter_plants("NY")
    row = df.iloc[0]
    assert row["URL"] == f"https://plants.usda.gov/plant-profile/{row['Symbol']}"


# --- Cache-mutation safety (where mistakes hide) -----------------------------

def test_repeated_calls_are_stable_and_cache_unmutated():
    first = filter_plants("NY")
    second = filter_plants("NY")
    assert second.equals(first)
    # The cached source frame must never gain the derived "zone" column.
    assert "zone" not in plants._load_plants().columns


# --- data= injection (mirrors geocode fixture injection) ---------------------

def test_data_override_accepts_path():
    path = str(files("rain_garden.data") / "nwpl_usda_merged.csv")
    df = filter_plants("NY", data=path)
    assert len(df) == 74


# --- min_temp smoke (filter fires + excludes nulls; not validating direction) -

def _synthetic_ny_frame():
    """Minimal NY-region frame: one warm, one cold, one null-temp plant."""
    return pd.DataFrame(
        {
            "NCNE": ["OBL", "OBL", "OBL"],
            "Moisture Use": ["High", "High", "High"],
            "Drought Tolerance": ["High", "High", "High"],
            plants.TEMP_COL: [10.0, -20.0, None],
            "Common Name": ["Warm", "Cold", "Unknown"],
            "Scientific Name": ["a", "b", "c"],
            "Symbol": ["WARM", "COLD", "NULL"],
            plants.HEIGHT_COL: [3, 3, 3],
            "Bloom Period": ["Spring", "Spring", "Spring"],
            "Flower Color": ["Blue", "Blue", "Blue"],
        }
    )


def test_min_temp_filter_fires_and_excludes_nulls():
    df = _synthetic_ny_frame()
    # Without the filter, all three qualify.
    assert len(filter_plants("NY", data=df)) == 3
    # With min_temp active, the filter fires (drops the cold plant) AND excludes
    # the null-temp plant — leaving only the warm one.
    kept = filter_plants("NY", min_temp=0, data=df)
    assert list(kept["Symbol"]) == ["WARM"]
