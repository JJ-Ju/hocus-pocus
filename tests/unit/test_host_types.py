"""node_type_search and node_type_info verbosity helpers (review 23 papercuts 6, 7)."""

from __future__ import annotations

import pytest

from hocuspocus.host.tools.types import filter_parms, shared_fields

pytestmark = pytest.mark.unit


def test_shared_network_fields_are_hoisted_once():
    rows = [
        {"name": f"vellum{i}", "child_category": "Sop", "typical_parents": ["a geo object"]}
        for i in range(3)
    ]
    assert shared_fields(rows, ("child_category", "typical_parents")) == {
        "child_category": "Sop",
        "typical_parents": ["a geo object"],
    }
    assert all(set(row) == {"name"} for row in rows)


@pytest.mark.parametrize(
    "rows",
    [
        [{"name": "a", "child_category": "Sop", "typical_parents": []}],  # one row
        [{"name": "a", "child_category": "Sop", "typical_parents": []}, {"name": "b"}],
        [
            {"name": "a", "child_category": "Sop", "typical_parents": []},
            {"name": "b", "child_category": "Cop", "typical_parents": ["/img"]},
        ],
    ],
)
def test_fields_stay_on_rows_unless_every_row_shares_them(rows):
    before = [dict(row) for row in rows]
    assert shared_fields(rows, ("child_category", "typical_parents")) == {}
    assert rows == before


PARMS = [
    {"name": "stretchdampingratio", "label": "Stretch Damping Ratio"},
    {"name": "pintype", "label": "Pin Type"},
    {"name": "benddampingscale", "label": "Bend Damping Scale"},
    {"name": "pin_group", "label": "Pin Points"},
    {"name": "substeps", "label": "Substeps"},
]


def test_word_start_matches_come_first_and_substrings_are_marked():
    rows = filter_parms(PARMS, "*pin*")
    assert [r["name"] for r in rows] == [
        "pintype",
        "pin_group",
        "stretchdampingratio",
        "benddampingscale",
    ]
    assert [r.get("matched_by") for r in rows] == [None, None, "substring", "substring"]


def test_exact_and_inner_wildcard_patterns_are_not_marked():
    assert [r["name"] for r in filter_parms(PARMS, "substeps")] == ["substeps"]
    assert all("matched_by" not in r for r in filter_parms(PARMS, "p*n*"))


def test_an_exact_alternative_is_never_a_substring_match():
    """Review 24 N2: *pin*|grouptype|constrainttype|group reported the three exact names
    as substring matches."""
    rows = PARMS + [
        {"name": "group", "label": "Group"},
        {"name": "grouptype", "label": "Group Type"},
        {"name": "constrainttype", "label": "Constraint Type"},
    ]
    found = filter_parms(rows, "*pin*|grouptype|constrainttype|group")
    marked = [r["name"] for r in found if r.get("matched_by") == "substring"]
    assert marked == ["stretchdampingratio", "benddampingscale"]
    assert [r["name"] for r in found if "matched_by" not in r] == [
        "pintype",
        "pin_group",
        "group",
        "grouptype",
        "constrainttype",
    ]
    # The note counts only the wildcard alternatives' inside-word hits.
    alone = filter_parms(rows, "*ype|group")
    assert [r["name"] for r in alone] == ["group", "pintype", "grouptype", "constrainttype"]
    assert [r.get("matched_by") for r in alone] == [None, "substring", "substring", "substring"]
    trange = [{"name": "trange", "label": "Valid Frame Range"}, {"name": "f", "label": "Start"}]
    assert all("matched_by" not in r for r in filter_parms(trange, "trange|f|*output*"))
