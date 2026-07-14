"""Agent-callable tool layer over the deterministic rain-garden modules.

Deterministic only — no Anthropic SDK, no agent loop (that's ``agent.py``).
This module exposes:

* ``LOWER_48`` and ``geocode_and_gate`` — a pre-step that resolves an address and
  refuses anything outside the contiguous lower-48 states.
* ``TOOLS`` — the Anthropic-style tool schemas the model can call (the compute
  tools, ``check_viability``, ``search_guidance``, and the two terminal signals
  ``present_results`` / ``conclude_without_plan``).
* ``dispatch`` — routes a compute tool call to the underlying module and returns a
  strictly JSON-safe result (no numpy types, no NaN). The terminal signals are
  intercepted by ``agent.py`` and never reach ``dispatch``.

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
    a structured refusal ``{"ok": False, "reason": ..., "message": ...}``. Never
    raises for a bad address — a not-found result is a refusal, not an exception.
    ``reason`` distinguishes the two refusal kinds so the HTTP layer can map each to
    a distinct terminal status (``address_not_found`` vs ``out_of_region``) rather
    than string-matching the human message.
    """
    try:
        result = geocode_address(address)
    except AddressNotFoundError:
        return {
            "ok": False,
            "reason": "address_not_found",
            "message": "I couldn't find that address — please give a fuller US street address.",
        }
    if result.get("state") not in LOWER_48:
        return {"ok": False, "reason": "out_of_region", "message": _OUT_OF_AREA}
    return {"ok": True, **result}


# Opens the seeded first user turn. The HTTP layer scans incoming messages for this
# marker to tell a seed request (absent -> geocode + gate) from a continuation
# (present -> geocode already ran), so geocoding happens exactly once per conversation.
LOCATION_PREAMBLE_MARKER = "[Resolved location:"

# The seed also records whether a satellite roof-area estimate resolved — as
# *availability only*, never the digit. The model reads this to decide whether to
# offer the estimate (via the {roof_sqft} token) or the no-estimate fallback copy;
# the HTTP layer reads it to decide whether to attach the results-card advisory. The
# exact number is redacted from the transcript and carried out of band (see app.py).
ROOF_ESTIMATE_MARKER = "[Roof estimate:"
ROOF_ESTIMATE_AVAILABLE = f"{ROOF_ESTIMATE_MARKER} available]"
ROOF_ESTIMATE_UNAVAILABLE = f"{ROOF_ESTIMATE_MARKER} unavailable]"


def build_seed(
    location: dict, roof_estimate: dict | None = None, slots: str | None = None
) -> str:
    """Build the seeded first user turn: location + roof-estimate availability (+ slots).

    ``location`` is a successful :func:`geocode_and_gate` result. The preamble opens
    with :data:`LOCATION_PREAMBLE_MARKER` (the geocode-once discriminator) and carries
    the resolved state/zip/lat/lon so the model never asks for them.

    ``roof_estimate`` is the :func:`rain_garden.roofarea.estimate_roof_area` result
    (or ``None``). Only its *availability* is written here — never the digit. The exact
    number is redacted from the model's context and reaches the user solely through
    deterministic ``{roof_sqft}`` substitution in the HTTP layer, so the model can
    never author or mis-transcribe a value the user may adopt as their catchment area.

    ``slots`` (optional) is free-text embedding the site details, INCLUDING the
    catchment area (now a conversational detail, no longer pre-filled in the seed).
    The oracle passes all details so its run stays a one-shot ``complete``; the HTTP
    seed path omits it and lets the model slot-fill across turns. Sole builder of the
    preamble so the marker strings live in exactly one place.
    """
    preamble = (
        f"{LOCATION_PREAMBLE_MARKER} {location['address']}, "
        f"state {location['state']}, zip {location['zip_code']}, "
        f"lat {location['lat']}, lon {location['lon']}]"
    )
    roof_line = ROOF_ESTIMATE_AVAILABLE if roof_estimate else ROOF_ESTIMATE_UNAVAILABLE
    seed = f"{preamble}\n\n{roof_line}"
    if slots:
        seed = f"{seed}\n\n{slots}"
    return seed


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
            "Compute the rain garden design from the catchment area and site conditions. "
            "Returns three depth options (about 4, 6, and 8 inches), each with its own "
            "area and plant counts, plus site advisories. Pass total_precip_yr from "
            "get_precipitation_stats to also get the annual gallons diverted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "catchment_sa": {
                    "type": "number",
                    "description": (
                        "Drainage (catchment) area in square feet, as stated by the user. "
                        "Provide this OR set adopt_roof_estimate=true when the user chooses "
                        "to use the satellite roof estimate — never both, and never a value "
                        "you invented."
                    ),
                },
                "adopt_roof_estimate": {
                    "type": "boolean",
                    "description": (
                        "Set true ONLY when the user asks to use the satellite roof-area "
                        "estimate as their catchment area. The server fills catchment_sa with "
                        "the exact estimate; do not pass a number yourself. Requires a roof "
                        "estimate to have resolved this session (see the seed's roof-estimate "
                        "marker); otherwise you'll get an error to ask for the area directly."
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
                "distance": {
                    "type": "string",
                    "enum": ["More than 30 ft", "10-30 ft", "Less than 10 ft"],
                    "description": (
                        "Distance of the planned garden from the house foundation. Used "
                        "only for the setback advisory (does not change the garden size)."
                    ),
                },
                "slope_ok": {
                    "type": "boolean",
                    "description": "True if the site slope is flat or under 12%.",
                },
                "slopes_away_from_house": {
                    "type": "boolean",
                    "description": (
                        "Whether the ground slopes away from the house or is flat (true) "
                        "vs. slopes toward the house (false). Separate from slope_ok, which "
                        "is the grade/steepness check."
                    ),
                },
                "perc_rate": {
                    "type": "string",
                    "description": "Measured drainage/percolation rate (inches/hour), if known.",
                },
                "threshold_precip_rate": {
                    "type": "number",
                    "description": (
                        "From get_precipitation_stats. Accepted for forward compatibility "
                        "(per-depth drain-down timing); not currently reflected in output."
                    ),
                },
                "total_precip_yr": {
                    "type": "number",
                    "description": "From get_precipitation_stats; enables gallons-diverted output.",
                },
            },
            # Neither is unconditionally required: the caller supplies catchment_sa OR
            # sets adopt_roof_estimate. The agent loop validates that exactly one path is
            # taken (and resolves the adoption) before dispatch, so the compute layer
            # always receives a concrete numeric catchment_sa.
            "required": [],
        },
    },
    {
        "name": "check_viability",
        "description": (
            "Check whether the site clears the three viability blockers BEFORE you size "
            "the garden: foundation setback (garden under 10 ft from the house), slope "
            "over 12%, and measured drainage below 0.5 in/hr. Also flags clayey soil "
            "that hasn't been drainage-tested. Call this the moment a viability slot "
            "(distance, slope steepness, measured drainage rate, or soil) is first "
            "collected OR corrected — pass every value you know so far; omit the ones you "
            "don't. It computes nothing about size. If it returns a 'blocking' advisory, "
            "raise it with the user THIS turn (offer the correction, then confirm whether "
            "they want to proceed anyway) before moving on — do not call size_garden while "
            "an un-overridden blocker stands. Re-call it after any correction to confirm "
            "the blocker cleared."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "distance": {
                    "type": "string",
                    "enum": ["More than 30 ft", "10-30 ft", "Less than 10 ft"],
                    "description": (
                        "Distance of the planned garden from the house foundation. If the "
                        "user gives a number, bucket it: under 10 ft -> 'Less than 10 ft'; "
                        "10 to 30 ft (inclusive) -> '10-30 ft'; over 30 ft -> 'More than "
                        "30 ft'. Omit if not yet known."
                    ),
                },
                "slope_ok": {
                    "type": "boolean",
                    "description": "True if the site slope is flat or under 12%; false if steeper. Omit if unknown.",
                },
                "perc_rate": {
                    "type": "string",
                    "description": (
                        "The user's MEASURED drainage/percolation rate (inches/hour), if they "
                        "have actually measured it. Omit if unmeasured — do not guess."
                    ),
                },
                "soil_type": {
                    "type": "string",
                    "enum": ["Sandy", "Silty", "Loamy", "Clayey"],
                    "description": (
                        "Classify the user's free-text soil description into one of these four. "
                        "Omit if it cannot be determined. Do not pass raw text."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_guidance",
        "description": (
            "Retrieve short, cited passages of external how/why rain-garden guidance "
            "(digging, berms, mulching, soil amendment, regrading, overflow outlets, "
            "maintenance) from a curated library of government and university guides. "
            "This is the ONLY tool that returns outside prose; it computes nothing. "
            "Call it once, on the final turn, AFTER size_garden and filter_plants have "
            "returned. Form the 'query' from this site's fired advisories and conditions "
            "(e.g. clayey soil, slope too steep, close to the foundation, slopes toward "
            "the house) — never from plot size or an urban/suburban label. The passages "
            "are shown to the user as cited external guidance; do not restate them as "
            "your own computed advice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A condition-derived search query built from the advisories that "
                        "fired for this site (soil, slope, foundation distance, drainage)."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "present_results",
        "description": (
            "Signal that the rain-garden design is complete and deliver a brief "
            "prose wrap-up. Call this only after size_garden and filter_plants have "
            "returned and all advisories are determined. Write `summary` per the "
            "SIGNALING COMPLETION rules in the system prompt: express every computed "
            "garden value as a named {token} (e.g. {area_sqft}), never a literal "
            "digit. This is a control signal that ends the turn; it runs no calculation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Short prose recap of the recommendation for the user.",
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "conclude_without_plan",
        "description": (
            "End the conversation WITHOUT a rain garden plan. Call this only when a "
            "blocking site condition (too close to the foundation, slope over 12%, or "
            "measured drainage below 0.5 in/hr) cannot be corrected AND the user, after "
            "you offered the correction and confirmed, has chosen NOT to proceed. This is "
            "the decline path: do NOT call size_garden or present_results. In the same "
            "turn, deliver a brief, kind closing message to the user as normal text. Like "
            "present_results this is a terminal control signal that runs no calculation; "
            "the server ends the conversation with no plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "One short line naming the unresolved blocker that ended the plan "
                        "(e.g. 'garden must stay under 10 ft from the foundation'). For the "
                        "record; your closing message to the user is normal assistant text."
                    ),
                },
            },
            "required": ["reason"],
        },
    },
]

# The two terminal-signal tools. The agent loop intercepts BOTH before dispatch; they
# appear in TOOLS but are never routed to a backend module. present_results ends the
# conversation WITH a plan; conclude_without_plan ends it on the decline path with no
# plan (spec §7.5 State B). Both are recorded in call_log so the HTTP layer derives the
# terminal outcome from the log (call-log-keyed, like search_guidance — never a
# transcript scan), which is the whole reason conclude_without_plan is a tool (§10-D).
PRESENT_RESULTS = "present_results"
CONCLUDE_WITHOUT_PLAN = "conclude_without_plan"

# The pre-sizing viability tool. Dispatched (it computes the blocker set), but unlike
# the other compute tools it takes no sizing inputs, so the model can call it the moment
# a viability slot fills. size_garden also calls the same underlying check internally.
CHECK_VIABILITY = "check_viability"

# The RAG retrieval tool. Unlike present_results it IS dispatched, but only on the
# terminal turn: the agent loop gates it on these deterministic tools already
# appearing in the current invocation's call_log (spec section 4, firmed to
# call_log co-occurrence). Forming the query needs the advisories those tools
# produced, so this ordering is also what the model naturally does.
SEARCH_GUIDANCE = "search_guidance"
# The sizing tool. The agent loop special-cases it to resolve an adopt_roof_estimate
# call into a concrete catchment_sa before dispatch (see agent._resolve_catchment).
SIZE_GARDEN = "size_garden"
GUIDANCE_PREREQS = frozenset({"size_garden", "filter_plants"})
GUIDANCE_GATE_MSG = (
    "search_guidance is only available on the final turn, after size_garden and "
    "filter_plants have returned in this exchange. Call those first, then form the "
    "guidance query from the advisories they produced."
)


# --- Viability checks --------------------------------------------------------

# The three viability blockers plus the soft clayey advisory. Each entry is
# (code, severity, corrective_action, message). The list order is the stable
# advisory order (spec §4.1): foundation_setback, slope, low_drainage, then the
# soft clayey advisory. `code` is carried on the `type` field to stay uniform with
# the other site advisories (spec §11 — align, don't fork); `corrective_action` is
# an additive field present only on these viability advisories. clayey_unverified's
# severity is "corrective" (the existing non-blocking vocabulary), not blocking.
_VIABILITY_SPECS = {
    "foundation_setback": (
        "blocking", "relocate_min_10ft",
        "Site the rain garden at least 10 ft from the foundation.",
    ),
    "slope": (
        "blocking", "regrade_site",
        "Slope exceeds 12% — regrade or choose a flatter location.",
    ),
    "low_drainage": (
        "blocking", "amend_soil",
        "Drainage below 0.5 in/hr — not recommended unless you improve it.",
    ),
    "clayey_unverified": (
        "corrective", "test_and_amend",
        "Clayey soil: verify drainage is at least 0.5 in/hr; amend until it is.",
    ),
}

# The three known distance buckets (spec §4.6). check_viability raises on any other
# non-None value so a model mislabel fails loudly rather than silently mis-deciding.
_VALID_DISTANCES = {"Less than 10 ft", "10-30 ft", "More than 30 ft"}


def _viability_advisory(code: str) -> dict:
    """Build one viability advisory object from :data:`_VIABILITY_SPECS`."""
    severity, corrective_action, message = _VIABILITY_SPECS[code]
    return {
        "type": code,
        "severity": severity,
        "corrective_action": corrective_action,
        "message": message,
    }


def check_viability(distance=None, slope_ok=None, perc_rate=None, soil_type=None) -> dict:
    """Evaluate the three viability blockers (+ soft clayey advisory) from inputs.

    Stateless and None-tolerant (spec §4.2): each dimension is evaluated
    independently, and a ``None`` input produces no advisory for its dimension —
    so this can be called incrementally as slots fill, not only at the end. It
    depends on none of the sizing inputs (catchment, precipitation, factor table).

    * ``distance`` — enum ``"Less than 10 ft"`` | ``"10-30 ft"`` | ``"More than
      30 ft"`` | ``None``. Blocks only on ``"Less than 10 ft"``; 10 ft belongs to
      ``"10-30 ft"``. Any other non-None value raises ``ValueError`` (§4.6).
    * ``slope_ok`` — ``bool | None``. Blocks when explicitly ``False`` (§4.3);
      ``None`` does not block.
    * ``perc_rate`` — ``float | None``, the MEASURED percolation rate (in/hr),
      already numeric (callers parse free text upstream). Blocks only on the open
      interval ``0 < rate < 0.5``: ``0.5`` and ``0.0`` both pass (§4.3, §10-A).
    * ``soil_type`` — ``str | None``. Fires the soft ``clayey_unverified``
      advisory only when soil is Clayey AND no rate was measured; once a rate is
      measured the rate governs and the advisory is suppressed (§4.4).

    Returns ``{"recommended": bool, "advisories": [ViabilityAdvisory, ...]}``.
    ``recommended`` is ``not any(severity == "blocking")`` over the advisories
    produced from the inputs provided — only *final* once all inputs are present
    (i.e. inside :func:`_size_garden`); mid-flow the caller reads individual
    advisories, not this flag.
    """
    if distance is not None and distance not in _VALID_DISTANCES:
        raise ValueError(f"Unknown distance value: {distance!r}")

    advisories = []
    if distance == "Less than 10 ft":
        advisories.append(_viability_advisory("foundation_setback"))
    if slope_ok is False:
        advisories.append(_viability_advisory("slope"))
    if perc_rate is not None and 0 < perc_rate < 0.5:
        advisories.append(_viability_advisory("low_drainage"))
    if soil_type == "Clayey" and perc_rate is None:
        advisories.append(_viability_advisory("clayey_unverified"))

    recommended = not any(a["severity"] == "blocking" for a in advisories)
    return {"recommended": recommended, "advisories": advisories}


# --- size_garden composition -------------------------------------------------

def _advisories(determined_soil, slopes_away_from_house, perc_input, parsed_rate):
    """Non-viability site advisories as {type, severity, message} objects.

    The viability blockers (foundation_setback, slope, low_drainage) and the soft
    clayey advisory now live in :func:`check_viability`; this covers only the
    remaining depth-invariant site notes.
    """
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
    # Direction (distinct from steepness): only when explicitly toward the house.
    # True or omitted (None) -> no advisory; don't nag when direction wasn't assessed.
    if slopes_away_from_house is False:
        out.append({
            "type": "slope_toward_house", "severity": "corrective",
            "message": (
                "This spot slopes toward the house. A rain garden here is workable, but it "
                "is essential to build a robust overflow outlet that channels excess water "
                "away from the foundation. Without one, overflow during heavy storms can pool "
                "against the house. Plan the outlet before you dig."
            ),
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
    slopes_away_from_house=None,
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

    # Three depth options, always computed. Distance no longer selects a factor
    # (advisory-only now); depth is the user tradeoff — deeper = smaller footprint.
    options = []
    for depth_in in sizing.DEPTH_OPTIONS:
        band = sizing.depth_band(depth_in)
        factor = sizing.size_factor(sizing_soil, band)
        area = sizing.rain_garden_area(catchment_sa, factor)
        dims = sizing.garden_dimensions(area)
        counts = sizing.plant_counts(dims["length"], dims["width"], area)
        # Gate the two-zone floor on the RAW interior count, then round for display:
        # a raw 0.5-0.99 must still fire the floor even though it displays as "1".
        interior_raw = counts["interior_count"]
        interior_plants = round(interior_raw)
        perimeter_plants = round(counts["outer_count"])
        area_sqft = round(area)

        opt_adv = []
        if area_sqft > 300:
            opt_adv.append({
                "type": "split_ceiling", "severity": "informational",
                "message": (
                    "At over 300 sq ft this is large for a single basin — consider "
                    "dividing it into two or more smaller rain gardens."
                ),
            })
        if interior_raw < 1:
            opt_adv.append({
                "type": "two_zone_floor", "severity": "corrective",
                "message": (
                    "Too small for a separate wetter center: plant this as a single "
                    "zone using the perimeter (medium-moisture) plant list only."
                ),
            })
        options.append({
            "depth_in": depth_in,
            "band": band,
            "area_sqft": area_sqft,
            "interior_plants": interior_plants,
            "perimeter_plants": perimeter_plants,
            "advisories": opt_adv,
        })

    gallons = None
    if total_precip_yr is not None:
        gallons = sizing.gallons_diverted(catchment_sa, total_precip_yr)

    # Viability (blocking) checks live in one deterministic place (§6, DRY): the
    # full input set is passed with the PARSED numeric rate, and the returned
    # blockers + soft clayey advisory lead the merged list. No blocking advisory is
    # produced outside check_viability, so recommended is its flag verbatim.
    viability = check_viability(
        distance=distance,
        slope_ok=slope_ok,
        perc_rate=parsed_rate,
        soil_type=determined_soil,
    )
    site_advisories = _advisories(
        determined_soil, slopes_away_from_house, perc_rate, parsed_rate
    )
    advisories = viability["advisories"] + site_advisories
    recommended = viability["recommended"]

    # 30%-smaller allowance: a pressure-release valve for users whose recommended
    # garden won't fit. Only meaningful when an option is actually too big (ceiling
    # fired) and never against an already-too-small garden (floor fired).
    any_ceiling = any(a["type"] == "split_ceiling" for o in options for a in o["advisories"])
    any_floor = any(a["type"] == "two_zone_floor" for o in options for a in o["advisories"])
    sizing_advisories = []
    if any_ceiling and not any_floor:
        sizing_advisories.append({
            "type": "reduction_allowance", "severity": "informational",
            "message": (
                "Any of these can be shrunk by up to 30% and still control about 90% "
                "of the yearly runoff — handy if the full size won't fit your yard."
            ),
        })

    return {
        "recommended": recommended,
        "sizing": {"options": options, "advisories": sizing_advisories},
        "advisories": advisories,
        "gallons_per_year": gallons,
    }


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
        local_min_temp = tool_input.get("local_min_temp")
        if local_min_temp is None:
            # Without a winter survival floor we cannot screen plants for cold
            # hardiness; returning an unfiltered list would silently recommend
            # plants that may not survive the local winter. Return empty + reason.
            return {
                "interior": [],
                "perimeter": [],
                "reason": (
                    "No plants selected: the hardiness lookup did not supply a "
                    "minimum-temperature floor ('local_min_temp'), so plants "
                    "cannot be screened for cold hardiness. Run get_hardiness_zone "
                    "and pass its 'min_temp_floor' as 'local_min_temp'."
                ),
            }
        df = filter_plants(
            tool_input["state"],
            local_min_temp=local_min_temp,
            soil_type=tool_input.get("soil_type"),
            sun=tool_input.get("sun"),
        )
        interior, perimeter = split_by_zone(df)
        return {"interior": _shape_plants(interior), "perimeter": _shape_plants(perimeter)}

    if tool_name == "search_guidance":
        # Import here so the ONNX runtime is pulled only when retrieval is actually
        # used, not on every tools import. Guidance is strictly additive (spec
        # section 0): a retrieval failure must never break the deterministic
        # recommendation, so any error degrades to a recoverable empty result.
        from rain_garden import retrieval
        try:
            passages = retrieval.search(tool_input["query"])
        except Exception as exc:  # noqa: BLE001 — additive channel, never fatal
            return {"is_error": True, "message": f"guidance retrieval unavailable: {exc}"}
        return {"passages": passages}

    if tool_name == "check_viability":
        # Parse the free-text rate to a float here (as size_garden does), so the
        # function always sees a numeric perc_rate. An invalid distance raises
        # ValueError inside check_viability; dispatch converts it to a recoverable
        # error so the model re-labels rather than crashing the loop.
        try:
            return check_viability(
                distance=tool_input.get("distance"),
                slope_ok=tool_input.get("slope_ok"),
                perc_rate=sizing.parse_perc_rate(tool_input.get("perc_rate")),
                soil_type=tool_input.get("soil_type"),
            )
        except ValueError as exc:
            return {"is_error": True, "message": str(exc)}

    if tool_name == "size_garden":
        return _size_garden(
            tool_input["catchment_sa"],
            soil_type=tool_input.get("soil_type"),
            distance=tool_input.get("distance", "More than 30 ft"),
            slope_ok=tool_input.get("slope_ok", True),
            slopes_away_from_house=tool_input.get("slopes_away_from_house"),
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
