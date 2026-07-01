"""Gold eval for search_guidance retrieval (spec section 8). No network.

The (condition -> expected top-1 source_doc) oracle was settled by Chat against
the frozen corpus's ground truth; each query below is a faithful phrasing of the
fired condition. The clay and slopes-toward-house conditions are intentionally
omitted (their oracle was contaminated by earlier retriever inspection in the
build thread). Assertion: the expected source is the top-1 hit.
"""

import pytest

from rain_garden.retrieval import search

# (label, condition query, expected top-1 source_doc)
GOLD = [
    (
        "why/benefit",
        "what is the problem with polluted stormwater runoff and the benefits "
        "of soaking up the rain",
        "epa_soak_up_the_rain",
    ),
    (
        "foundation_setback",
        "how far from the house foundation should a rain garden be placed",
        "doee_howto",
    ),
    (
        "slope/berm",
        "building a berm and grading a rain garden on a sloped site",
        "oregon_guide",
    ),
    (
        "plants",
        "choosing and laying out native plants for the rain garden by height, "
        "bloom, and texture",
        "doee_howto",
    ),
    (
        "maintenance",
        "maintaining the rain garden over time — weeding, pruning, and mulching",
        "oregon_guide",
    ),
]


@pytest.mark.parametrize("label,query,expected", GOLD, ids=[g[0] for g in GOLD])
def test_top1_source_matches_oracle(label, query, expected):
    hits = search(query, k=1)
    assert hits, "retrieval returned no passages"
    top = hits[0]
    assert top["source_doc"] == expected, (
        f"[{label}] top-1 was {top['source_doc']} (score {top['score']}); "
        f"expected {expected}"
    )
