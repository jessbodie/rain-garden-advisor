"""Print rain garden sizing outputs for a set of inputs, for comparison with the
original Hex notebook.

Edit the INPUT_* values below to mirror a run of the Hex notebook, then run this
script and compare the "Comparable to notebook" group against the notebook's
output. Entering a drainage rate (INPUT_PERC_RATE) switches the sizing factor
from the soil/distance table to the infiltration-rate table, just like the
notebook.

Run:
    ./.venv/Scripts/python.exe examples/compare_notebook.py
"""

from rain_garden import sizing

# --- Inputs (mirror the notebook's input cells) ------------------------------
INPUT_CATCHMENT_SA = 700          # Drainage area (sq ft)
INPUT_SOIL_TYPE = "Silty"         # Sandy / Silty / Loamy / Clayey / "I'm not sure"
INPUT_DISTANCE = "More than 30 ft"  # More than 30 ft / 10-30 ft / Less than 10 ft
INPUT_PERC_RATE = "1.0"           # Free text, e.g. "1.0"; "" = none -> soil-based path

# --- Placeholder precipitation values ----------------------------------------
# NOTE: the notebook derives these from the location's weather data. These are
# placeholders, so the drainage-time and gallons-diverted outputs below are NOT
# directly comparable to the notebook unless you paste in the notebook's own
# per-location values here.
PLACEHOLDER_THRESHOLD_PRECIP_RATE = 1.0  # one-hour extreme precip rate (in/hr)
PLACEHOLDER_TOTAL_PRECIP_YR = 40         # annual precipitation total (inches)


def main() -> None:
    perc_rate = sizing.parse_perc_rate(INPUT_PERC_RATE)
    sizing_factor = sizing.resolve_sizing_factor(
        INPUT_SOIL_TYPE, INPUT_DISTANCE, perc_rate
    )
    path = "rate table" if perc_rate is not None and perc_rate >= 0.5 else "soil + distance"

    area = sizing.rain_garden_area(INPUT_CATCHMENT_SA, sizing_factor)
    dims = sizing.garden_dimensions(area)
    depth = sizing.recommended_depth(area)
    plants = sizing.plant_counts(dims["length"], dims["width"], area)

    print("=" * 60)
    print("INPUTS")
    print("=" * 60)
    print(f"  Catchment area      : {INPUT_CATCHMENT_SA} sq ft")
    print(f"  Soil type           : {INPUT_SOIL_TYPE}")
    print(f"  Distance            : {INPUT_DISTANCE}")
    print(f"  Drainage rate input : {INPUT_PERC_RATE!r}")
    print(f"  Drainage rate (used): {perc_rate if perc_rate is not None else 'none'}")
    print(f"  Sizing path         : {path}")

    print()
    print("=" * 60)
    print("COMPARABLE TO NOTEBOOK")
    print("=" * 60)
    print(f"  Sizing factor       : {sizing_factor}")
    print(f"  Area                : {round(area)} sq ft")
    print(f"  Elongated (W x L)   : {round(dims['width'])} x {round(dims['length'])} ft")
    print(f"  Balanced (side)     : {round(dims['side'])} x {round(dims['side'])} ft")
    print(f"  Depth               : {depth} in")
    print(
        f"  Interior plants     : {round(plants['interior_count'])}"
        f" (~{plants['interior_area']:.1f} sq ft)"
    )
    print(
        f"  Perimeter plants    : {round(plants['outer_count'])}"
        f" (~{plants['outer_area']:.0f} sq ft)"
    )

    print()
    print("=" * 60)
    print("PRECIP-DEPENDENT (placeholder values -- verify separately)")
    print("=" * 60)
    if perc_rate is not None:
        drain = sizing.drainage_time(
            INPUT_CATCHMENT_SA, area, PLACEHOLDER_THRESHOLD_PRECIP_RATE, perc_rate
        )
        print(f"  Drainage time       : {drain} hr")
    else:
        print("  Drainage time       : N/A -- no drainage rate entered")
    gallons = sizing.gallons_diverted(INPUT_CATCHMENT_SA, PLACEHOLDER_TOTAL_PRECIP_YR)
    print(f"  Gallons / year      : {gallons:,}")
    print(
        "  NOTE: drainage time and gallons depend on the notebook's per-location\n"
        "        precipitation values; replace the PLACEHOLDER_* constants with the\n"
        "        notebook's own values to compare these two outputs."
    )


if __name__ == "__main__":
    main()
