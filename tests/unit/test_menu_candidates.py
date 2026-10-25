"""Menu candidates ranked by similarity to the value given (BIBLE D72, review 26 P3 #11:
``subnetconnector parmtype: volume`` listed the first 20 of 44 items, not ``atmosphere``,
whose label is ``Volume (shader)``)."""

from __future__ import annotations

import pytest

from hocuspocus.host.tools.parms import (
    MENU_ALL_ITEMS,
    MENU_CANDIDATES,
    menu_choices,
    rank_menu,
)

pytestmark = pytest.mark.unit

# subnetconnector's parmtype menu on 22.0.466 (tokens and labels).
PARMTYPE = [
    ("float", "Float (float)"), ("int", "Integer (int)"), ("toggle", "Toggle (int)"),
    ("angle", "Angle (float)"), ("logfloat", "Logarithmic (float)"),
    ("float2", "2 Floats (vector2)"), ("float3", "3 Floats (vector)"),
    ("vector", "Vector (vector)"), ("normal", "Normal (normal)"), ("point", "Point (point)"),
    ("direction", "Direction (vector)"), ("float4", "4 Floats (vector4)"),
    ("floatm2", "4 Floats (matrix2)"), ("float9", "9 Floats (matrix3)"),
    ("float16", "16 Floats (matrix)"), ("string", "String (string)"), ("file", "File (string)"),
    ("image", "Image (string)"), ("geometry", "Geometry (string)"), ("color", "Color (color)"),
    ("coloralpha", "Color with Alpha (vector4)"), ("bsdf", "BSDF (F)"),
    ("dict", "Dictionary (dict)"), ("coshader", "Co-Shader (shader)"),
    ("surface", "Surface (shader)"), ("displacement", "Displacement (shader)"),
    ("atmosphere", "Volume (shader)"), ("light", "Light (shader)"),
    ("lightfilter", "Light Filter (shader)"), ("floata", "Float Array (float[])"),
    ("inta", "Integer Array (int[])"), ("vector2a", "2 Float Array (vector2[])"),
    ("vectora", "Vector Array (vector[])"), ("pointa", "Point Array (point[])"),
    ("normala", "Normal Array (normal[])"), ("colora", "Color Array (color[])"),
    ("float4a", "4 Float Array (vector4[])"), ("floatm2a", "4 Float Array (matrix2[])"),
    ("float9a", "9 Float Array (matrix3[])"), ("float16a", "16 Float Array (matrix4[])"),
    ("stringa", "String Array (string[])"), ("dicta", "Dictionary Array (dict[])"),
    ("coshadera", "Co-Shader Array (shader[])"), ("struct", "Custom (struct)"),
]  # fmt: skip
TOKENS = [t for t, _ in PARMTYPE]
LABELS = [label for _, label in PARMTYPE]


def test_a_label_word_ranks_its_item_first():
    order = rank_menu("volume", TOKENS, LABELS)
    assert TOKENS[order[0]] == "atmosphere"


def test_a_menu_of_44_items_lists_them_all_nearest_first():
    assert len(TOKENS) <= MENU_ALL_ITEMS
    candidates, shown = menu_choices("volume", TOKENS, LABELS)
    assert sorted(candidates) == sorted(TOKENS) and candidates[0] == "atmosphere"
    assert shown.startswith("atmosphere (Volume (shader))")
    assert "44 items, candidates lists all" in shown


def test_a_typo_ranks_the_token_it_misspells():
    candidates, _ = menu_choices("surfce", TOKENS, LABELS)
    assert candidates[0] == "surface"
    candidates, _ = menu_choices("colour", TOKENS, LABELS)
    assert candidates[0] in ("color", "colora", "coloralpha")


def test_a_large_menu_gives_the_nearest_items():
    tokens = [f"item{i:03d}" for i in range(120)] + ["atmosphere"]
    labels = [f"Item {i}" for i in range(120)] + ["Volume (shader)"]
    candidates, shown = menu_choices("volume", tokens, labels)
    assert len(candidates) == MENU_CANDIDATES and candidates[0] == "atmosphere"
    assert f"121 items, candidates lists the {MENU_CANDIDATES} nearest" in shown


def test_an_index_out_of_range_keeps_menu_order():
    candidates, shown = menu_choices(99, TOKENS, LABELS)
    assert candidates == TOKENS and "in menu order" in shown


def test_a_small_menu_needs_no_count():
    candidates, shown = menu_choices("b", ["a", "b2"], ["Alpha", "Beta"])
    assert candidates == ["b2", "a"] and shown == "b2 (Beta), a (Alpha)"
