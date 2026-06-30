"""Agent-callable tool layer over the deterministic rain-garden modules.

Deterministic only — no Anthropic SDK, no agent loop (that's ``agent.py``).
This module exposes:

* ``LOWER_48`` and ``geocode_and_gate`` — a pre-step that resolves an address and
  refuses anything outside the contiguous lower-48 states.
* ``TOOLS`` — four Anthropic-style tool schemas the model can call.
* ``dispatch`` — routes a tool call to the underlying module and returns a
  strictly JSON-safe result (no numpy types, no NaN).

Error tiers: recoverable lookup failures are returned as ``{"is_error": True,
...}`` for the model to react to; a missing API key is fatal and raised as
``FatalToolError`` for ``agent.py`` to halt on.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from rain_garden import sizing
from rain_garden.geocode import AddressNotFoundError, geocode_address
from rain_garden.hardiness import (
    HardinessAPIError,
    HardinessZoneNotFoundError,
    InvalidZipCodeError,
    MissingAPIKeyError,
    get_hardiness_zone,
    min_temp_floor,
)
from rain_garden.plants import InvalidStateError, filter_plants, split_by_zone
from rain_garden.precipitation import get_precipitation_stats

# Contiguous lower-48 (excludes AK, HI; DC not included).
LOWER_48 = {
    "AL", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
}

_CANONICAL_SOILS = {"Sandy", "Silty", "Loamy", "Clayey"}
_OUT_OF_AREA = "This tool currently supports the contiguous lower-48 US states only."

# Curated plant columns -> snake_case keys exposed to the model.
_PLANT_COLUMNS = {
    "Common Name": "common_name",
    "Bloom Period": "bloom_period",
    "Flower Color": "flower_color",
    "Height at 20 Years, Maximum (feet)": "height_ft",
    "Moisture Use": "moisture_use",
}
_MAX_ROWS_PER_ZONE = 15


class FatalToolError(RuntimeError):
    """Unrecoverable tool failure (e.g. missing API key). agent.py halts on it."""


# --- JSON safety -------------------------------------------------------------

def _jsonify(obj):
    """Return a strictly JSON-serializable copy: numpy -> python, NaN/NA -> None."""
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if pd.isna(obj):  # pd.NA, np.nan, None, NaT — scalar leaves only
        return None
    if isinstance(obj, np.floating):
        return float(obj)
    return obj


# --- Geocode pre-step (plain function, not a tool) ---------------------------

def geocode_and_gate(address: str) -> dict:
    """Geocode an address and gate it to the lower-48 states.

    Returns ``{"ok": True, ...geocode fields...}`` for an in-area address, else
    a structured refusal ``{"ok": False, "message": ...}``. Never raises for a
    bad address — a not-found result is a refusal, not an exception.
    """
    try:
        result = geocode_address(address)
    except AddressNotFoundError:
        return {
            "ok": False,
            "message": "I couldn't find that address — please give a fuller US street address.",
        }
    if result.get("state") not in LOWER_48:
        return {"ok": False, "message": _OUT_OF_AREA}
    return {"ok": True, **result}


# --- Tool schemas ------------------------------------------------------------

TOOLS = [
    {
        "name": "get_precipitation_stats",
        "description": (
            "Fetch local precipitation statistics for a location from the Open-Meteo "
            "historical archive: the extreme one-hour rainfall rate and the average "
            "annual rainfall total. Use the lat/lon from the geocoding step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude."},
                "lon": {"type": "number", "description": "Longitude."},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_hardiness_zone",
        "description": (
            "Look up the USDA plant hardiness zone for a 5-digit US zip code. Returns "
            "the zone, its temperature range, and 'min_temp_floor' (the numeric lower "
            "bound in °F). Pass 'min_temp_floor' to filter_plants as 'local_min_temp'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zip_code": {"type": "string", "description": "5-digit US zip code."},
            },
            "required": ["zip_code"],
        },
    },
    {
        "name": "filter_plants",
        "description": (
            "Return rain-garden-appropriate native plants for a US state, split into "
            "interior (wettest) and perimeter zones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "Two-letter US state code (e.g. 'NY').",
                },
                "local_min_temp": {
                    "type": "number",
                    "description": (
                        "The location's winter low (°F). Use get_hardiness_zone's "
                        "'min_temp_floor'. Do NOT use any precipitation temperature value."
                    ),
                },
                "soil_type": {
                    "type": "string",
                    "enum": ["Sandy", "Silty", "Loamy", "Clayey"],
                    "description": (
                        "Classify the user's free-text soil description into one of these "
                        "four. Omit this field if it cannot be determined. Do not pass raw text."
                    ),
                },
                "sun": {
                    "type": "string",
                    "enum": ["Full sun", "Partial sun", "Mostly shady"],
                    "description": "Sun exposure at the site.",
                },
            },
            "required": ["state"],
        },
    },
    {
        "name": "size_garden",
        "description": (
            "Compute the recommended rain garden size, dimensions, depth, plant counts, "
            "and site advisories from the catchment area and site conditions. Pass "
            "threshold_precip_rate and total_precip_yr from get_precipitation_stats to "
            "also get drainage time and annual gallons diverted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "catchment_sa": {
                    "type": "number",
                    "description": "Drainage (catchment) area in square feet.",
                },
                "soil_type": {
                    "type": "string",
                    "enum": ["Sandy", "Silty", "Loamy", "Clayey"],
                    "description": (
                        "Classify the user's free-text soil description into one of these "
                        "four. Omit this field if it cannot be determined. Do not pass raw text."
                    ),
                },
                "distance": {
                    "type": "string",
                    "enum": ["More than 30 ft", "10-30 ft", "Less than 10 ft"],
                    "description": "Distance of the planned garden from the house foundation.",
                },
                "slope_ok": {
                    "type": "boolean",
                    "description": "True if the site slope is flat or under 12%.",
                },
                "perc_rate": {
                    "type": "string",
                    "description": "Measured drainage/percolation rate (inches/hour), if known.",
                },
                "threshold_precip_rate": {
                    "type": "number",
                    "description": "From get_precipitation_stats; enables drainage-time output.",
                },
                "total_precip_yr": {
                    "type": "number",
                    "description": "From get_precipitation_stats; enables gallons-diverted output.",
                },
            },
            "required": ["catchment_sa"],
        },
    },
]


# --- size_garden composition -------------------------------------------------

def _advisories(determined_soil, distance, slope_ok, perc_input, parsed_rate):
    """Deterministic site advisories as {type, severity, message} objects."""
    out = [{
        "type": "utilities", "severity": "informational",
        "message": "Check for underground utilities before digging.",
    }]
    if determined_soil == "Unknown":
        out.append({
            "type": "unknown_soil", "severity": "informational",
            "message": (
                "Soil type wasn't determined, so the garden was sized conservatively "
                "assuming slow, clay-like drainage. Confirming your soil type will likely "
                "refine — usually shrink — this estimate."
            ),
        })
    if determined_soil == "Clayey" and parsed_rate is None:
        out.append({
            "type": "clay_drainage", "severity": "corrective",
            "message": "Clayey soil: verify drainage is at least 0.5 in/hr; amend until it is.",
        })
    if parsed_rate is not None and 0 < parsed_rate < 0.5:
        out.append({
            "type": "low_drainage", "severity": "blocking",
            "message": "Drainage below 0.5 in/hr — not recommended unless you improve it.",
        })
    if distance == "Less than 10 ft":
        out.append({
            "type": "foundation_setback", "severity": "blocking",
            "message": "Site the rain garden at least 10 ft from the foundation.",
        })
    if not slope_ok:
        out.append({
            "type": "slope", "severity": "blocking",
            "message": "Slope exceeds 12% — regrade or choose a flatter location.",
        })
    if perc_input and parsed_rate is None:
        out.append({
            "type": "rate_unparsed", "severity": "informational",
            "message": "Couldn't read the drainage rate; sized from your soil type instead.",
        })
    return out


def _size_garden(
    catchment_sa,
    soil_type=None,
    distance="More than 30 ft",
    slope_ok=True,
    perc_rate=None,
    threshold_precip_rate=None,
    total_precip_yr=None,
):
    # Decouple the determined soil from the sizing-only substitution: an
    # undetermined/unexpected soil is sized conservatively with Clayey's factor,
    # but advisories and plant filtering still see "Unknown" (not "Clayey").
    determined_soil = soil_type if soil_type in _CANONICAL_SOILS else "Unknown"
    sizing_soil = "Clayey" if determined_soil == "Unknown" else determined_soil

    parsed_rate = sizing.parse_perc_rate(perc_rate)
    factor = sizing.resolve_sizing_factor(sizing_soil, distance, parsed_rate)
    area = sizing.rain_garden_area(catchment_sa, factor)
    dims = sizing.garden_dimensions(area)
    counts = sizing.plant_counts(dims["length"], dims["width"], area)

    drainage_time = None
    if parsed_rate is not None and threshold_precip_rate is not None:
        drainage_time = sizing.drainage_time(
            catchment_sa, area, threshold_precip_rate, parsed_rate
        )
    gallons = None
    if total_precip_yr is not None:
        gallons = sizing.gallons_diverted(catchment_sa, total_precip_yr)

    design = {
        "sizing_factor": factor,
        "area_sqft": round(area),
        "elongated_width_ft": round(dims["width"]),
        "elongated_length_ft": round(dims["length"]),
        "balanced_side_ft": round(dims["side"]),
        "depth_inches": sizing.recommended_depth(area),
        "interior_plant_count": round(counts["interior_count"]),
        "perimeter_plant_count": round(counts["outer_count"]),
        "drainage_time_hours": drainage_time,
        "gallons_per_year": gallons,
    }

    advisories = _advisories(determined_soil, distance, slope_ok, perc_rate, parsed_rate)
    recommended = not any(a["severity"] == "blocking" for a in advisories)

    # Sub-0.5 drainage: the footprint is provisional, never a confident
    # recommendation. (Pinned — the notebook ran area on a stale factor here.)
    if parsed_rate is not None and 0 < parsed_rate < 0.5:
        design["contingent"] = True
        design["contingent_on"] = "drainage improved to >= 0.5 in/hr"

    return {"recommended": recommended, "design": design, "advisories": advisories}


# --- Dispatch ----------------------------------------------------------------

def _run(tool_name: str, tool_input: dict):
    if tool_name == "get_precipitation_stats":
        stats = get_precipitation_stats(tool_input["lat"], tool_input["lon"])
        # Strip min_apparent_temp: it must never be wired into plant filtering.
        return {
            "threshold_precip_rate": stats["threshold_precip_rate"],
            "total_precip_yr": stats["total_precip_yr"],
        }

    if tool_name == "get_hardiness_zone":
        result = get_hardiness_zone(tool_input["zip_code"])
        return {
            "zone": result["zone"],
            "min_temp_range": result["min_temp_range"],
            "min_temp_floor": min_temp_floor(result["min_temp_range"]),
            "zip_code": result["zip_code"],
        }

    if tool_name == "filter_plants":
        df = filter_plants(
            tool_input["state"],
            local_min_temp=tool_input.get("local_min_temp"),
            soil_type=tool_input.get("soil_type"),
            sun=tool_input.get("sun"),
        )
        interior, perimeter = split_by_zone(df)
        return {"interior": _shape_plants(interior), "perimeter": _shape_plants(perimeter)}

    if tool_name == "size_garden":
        return _size_garden(
            tool_input["catchment_sa"],
            soil_type=tool_input.get("soil_type"),
            distance=tool_input.get("distance", "More than 30 ft"),
            slope_ok=tool_input.get("slope_ok", True),
            perc_rate=tool_input.get("perc_rate"),
            threshold_precip_rate=tool_input.get("threshold_precip_rate"),
            total_precip_yr=tool_input.get("total_precip_yr"),
        )

    raise ValueError(f"Unknown tool: {tool_name!r}")


def _shape_plants(zone_df):
    """Trim a zone's plants to the 5 exposed columns, capped at 15 rows."""
    trimmed = zone_df.head(_MAX_ROWS_PER_ZONE)[list(_PLANT_COLUMNS)]
    return trimmed.rename(columns=_PLANT_COLUMNS).to_dict("records")


def dispatch(tool_name: str, tool_input: dict) -> dict:
    """Route a tool call to its module and return a JSON-safe result.

    Recoverable lookup failures return ``{"is_error": True, "message": ...}``.
    A missing API key raises :class:`FatalToolError` for the caller to halt on.
    """
    try:
        result = _run(tool_name, tool_input)
    except MissingAPIKeyError as exc:  # fatal — caught before HardinessAPIError
        raise FatalToolError(str(exc)) from exc
    except (
        InvalidStateError,
        InvalidZipCodeError,
        HardinessZoneNotFoundError,
        HardinessAPIError,
    ) as exc:
        return {"is_error": True, "message": str(exc)}
    return _jsonify(result)
