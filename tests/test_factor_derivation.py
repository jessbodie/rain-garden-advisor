"""Verify sizing.SIZE_FACTORS_BY_DEPTH matches the source CSV cell-for-cell,
keyed by soil-type (not row position), so a reordered CSV cannot mis-assign.

The three depth bands in the CSV ('3-5" deep', '6-7" deep', '8" deep') map to the
table keys '3-5', '6-7', '8'.
"""

import csv
from pathlib import Path

import pytest

from rain_garden import sizing

# Path resolved relative to the repo root (tests/ -> repo root -> data/),
# so the test confirms the correct file is read regardless of CWD.
CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "RainGarden-SizeFactors.csv"

# CSV column header -> table band key.
_BAND_COLUMNS = {'3-5" deep': "3-5", '6-7" deep': "6-7", '8" deep': "8"}

SOILS = ("Sandy", "Loamy", "Silty", "Clayey")


def _read_rows() -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _factors_from_csv(rows) -> dict[str, dict[str, float]]:
    """Build {soil: {band: factor}} keyed by the 'Type of Soil' column."""
    out = {}
    for row in rows:
        soil = row["Type of Soil"].strip()
        out[soil] = {band: float(row[col]) for col, band in _BAND_COLUMNS.items()}
    return out


def test_csv_file_exists():
    assert CSV_PATH.is_file(), f"expected CSV at {CSV_PATH}"


def test_table_matches_csv_cell_for_cell():
    assert _factors_from_csv(_read_rows()) == sizing.SIZE_FACTORS_BY_DEPTH


@pytest.mark.parametrize("soil", SOILS)
def test_every_modeled_soil_present(soil):
    assert soil in sizing.SIZE_FACTORS_BY_DEPTH
    assert set(sizing.SIZE_FACTORS_BY_DEPTH[soil]) == {"3-5", "6-7", "8"}


def test_key_join_is_order_independent():
    rows = _read_rows()
    assert _factors_from_csv(rows) == _factors_from_csv(list(reversed(rows)))
