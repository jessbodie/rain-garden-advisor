"""Verify the "Less than 30 ft" soil sizing factors are derived from the source
CSV by SOIL-TYPE KEY (not row position), and match the values inlined in
rain_garden.sizing.

The notebook merges the more-than-30 and less-than-30 tables by row position,
which would mis-assign factors if the CSV rows were reordered. Here we join on
the soil-type key, so a reordered CSV cannot mis-assign.
"""

import csv
from pathlib import Path

import pytest

from rain_garden import sizing

# Path resolved relative to the repo root (tests/ -> repo root -> data/),
# so the test confirms the correct file is read regardless of CWD.
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "RainGarden-SizeFactors.csv"

# Exact expected values. These are float-rounding edge cases:
#   (0.15 + 0.08) / 2 -> 0.11 (rounds down)
#   (0.25 + 0.16) / 2 -> 0.21 (rounds up)
EXPECTED_LESS_THAN_30 = {"Sandy": 0.11, "Silty": 0.21, "Clayey": 0.26}


def _derive_by_key(rows) -> dict[str, float]:
    """Build {soil_type: less_than_30_factor} keyed by the 'Type of Soil' column."""
    derived = {}
    for row in rows:
        soil = row["Type of Soil"].strip()
        d_6_7 = float(row['6-7" deep'])
        d_8 = float(row['8" deep'])
        derived[soil] = round((d_6_7 + d_8) / 2, 2)
    return derived


def _read_rows() -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_csv_file_exists():
    assert CSV_PATH.is_file(), f"expected CSV at {CSV_PATH}"


def test_derived_factors_match_expected_exactly():
    derived = _derive_by_key(_read_rows())
    assert derived == EXPECTED_LESS_THAN_30


@pytest.mark.parametrize("soil, expected", EXPECTED_LESS_THAN_30.items())
def test_derived_factor_matches_inlined_constant(soil, expected):
    derived = _derive_by_key(_read_rows())
    assert derived[soil] == expected
    assert sizing.SOIL_SIZING_FACTORS[soil]["Less than 30 ft"] == expected


def test_key_join_is_order_independent():
    rows = _read_rows()
    forward = _derive_by_key(rows)
    reversed_map = _derive_by_key(list(reversed(rows)))
    assert forward == reversed_map == EXPECTED_LESS_THAN_30
