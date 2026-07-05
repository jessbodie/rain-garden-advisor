"""Oracle fixtures for check_viability (spec §8). No network.

Expected outputs are transcribed directly from the Chat-authored oracle table
(§8) — NOT derived from the implementation. Each row asserts the exact advisory
set (code + severity), the corrective_action mapping (§4.5), stable order, and
`recommended`.

Reconciliation note (spec §11, "align, don't fork"): the oracle labels advisory
codes on a `code` field and gives clayey_unverified severity "advisory". The
implementation carries the code on the existing `type` field and uses the
existing non-blocking severity "corrective" for clayey_unverified, so these
advisories stay uniform with the other site advisories in tools.py. The
SEMANTICS the oracle pins (which advisories fire, blocking-or-not, recommended)
are asserted exactly; only those two label spellings are aligned to the codebase.
"""

import pytest

from tools import check_viability

# §4.5 corrective_action codes, keyed by advisory type.
_CORRECTIVE = {
    "foundation_setback": "relocate_min_10ft",
    "slope": "regrade_site",
    "low_drainage": "amend_soil",
    "clayey_unverified": "test_and_amend",
}

# (id, kwargs, expected [(type, severity), ...] in stable order, recommended).
# Severity "corrective" for clayey_unverified is the §11-aligned spelling of the
# oracle's "advisory" (see module docstring).
_ORACLE = [
    ("1_setback", dict(distance="Less than 10 ft", slope_ok=True),
     [("foundation_setback", "blocking")], False),
    ("2_10to30_ok", dict(distance="10-30 ft", slope_ok=True), [], True),
    ("3_far_ok", dict(distance="More than 30 ft", slope_ok=True), [], True),
    ("4_distance_none", dict(distance=None, slope_ok=True), [], True),
    ("5_slope", dict(distance="More than 30 ft", slope_ok=False),
     [("slope", "blocking")], False),
    ("6_slope_none", dict(distance="More than 30 ft", slope_ok=None), [], True),
    ("7_perc_049", dict(distance="More than 30 ft", slope_ok=True, perc_rate=0.49),
     [("low_drainage", "blocking")], False),
    ("8_perc_05_boundary", dict(distance="More than 30 ft", slope_ok=True, perc_rate=0.5),
     [], True),
    ("9_perc_04_clayey", dict(distance="More than 30 ft", slope_ok=True,
                              perc_rate=0.4, soil_type="Clayey"),
     [("low_drainage", "blocking")], False),
    ("10_clayey_unmeasured", dict(distance="More than 30 ft", slope_ok=True,
                                  perc_rate=None, soil_type="Clayey"),
     [("clayey_unverified", "corrective")], True),
    ("11_clayey_measured_ok", dict(distance="More than 30 ft", slope_ok=True,
                                   perc_rate=0.8, soil_type="Clayey"),
     [], True),
    ("12_sandy_unmeasured", dict(distance="More than 30 ft", slope_ok=True,
                                 perc_rate=None, soil_type="Sandy"),
     [], True),
    ("13_all_three", dict(distance="Less than 10 ft", slope_ok=False, perc_rate=0.3),
     [("foundation_setback", "blocking"), ("slope", "blocking"),
      ("low_drainage", "blocking")], False),
    ("14_perc_00_boundary", dict(distance="More than 30 ft", slope_ok=True, perc_rate=0.0),
     [], True),
]


@pytest.mark.parametrize("kwargs,expected,recommended",
                         [(k, e, r) for _, k, e, r in _ORACLE],
                         ids=[i for i, _, _, _ in _ORACLE])
def test_viability_oracle(kwargs, expected, recommended):
    result = check_viability(**kwargs)
    got = [(a["type"], a["severity"]) for a in result["advisories"]]
    # Exact set AND stable order (§4.1: order stable, §8: exact advisory set).
    assert got == expected, f"advisories {got!r} != expected {expected!r}"
    assert result["recommended"] is recommended
    # Structural: exactly one advisory per triggering input, each carrying its
    # §4.5 corrective_action, and no stray fields.
    for adv in result["advisories"]:
        assert set(adv) == {"type", "severity", "corrective_action", "message"}
        assert adv["corrective_action"] == _CORRECTIVE[adv["type"]]
        assert adv["message"]


def test_viability_row15_invalid_distance_raises():
    # §4.6: an unknown non-None distance fails loudly, never silently mis-decides.
    with pytest.raises(ValueError):
        check_viability(distance="banana", slope_ok=True)


def test_viability_none_distance_does_not_raise():
    # None is the "not yet collected" sentinel — valid, produces no advisory.
    assert check_viability(distance=None) == {"recommended": True, "advisories": []}


def test_viability_incremental_all_none():
    # Fully empty call (§4.2 incremental use): no inputs, no advisories, recommended.
    assert check_viability() == {"recommended": True, "advisories": []}


def test_clayey_suppressed_once_rate_measured():
    # §4.4: the "go test it" advisory is moot once a rate exists; the measured rate
    # governs (block below 0.5, clear at/above). Neither path emits clayey_unverified.
    low = check_viability(soil_type="Clayey", perc_rate=0.3)
    assert [a["type"] for a in low["advisories"]] == ["low_drainage"]
    assert low["recommended"] is False
    fine = check_viability(soil_type="Clayey", perc_rate=0.6)
    assert fine["advisories"] == []
    assert fine["recommended"] is True
