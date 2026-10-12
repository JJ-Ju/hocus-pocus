"""node_type_search and node_type_info against real Houdini (bible §4.7, §5.4, §5.15)."""

from __future__ import annotations

import json
import time

import pytest

hou = pytest.importorskip("hou")


def _names(result: dict) -> list[str]:
    return [f"{row['category']}/{row['name']}" for row in result["results"]]


# -- search -----------------------------------------------------------------------


def test_search_index_is_cached(client):
    from hocuspocus.host.tools import types

    started = time.perf_counter()
    client.ok("node_type_search", {"query": "box"})
    first = time.perf_counter() - started
    builds = types._INDEX.builds
    started = time.perf_counter()
    client.ok("node_type_search", {"query": "sphere"})
    second = time.perf_counter() - started
    assert types._INDEX.builds == builds
    assert len(types._INDEX.rows) > 4000
    assert second < 1.0, (first, second)


@pytest.mark.parametrize(
    ("query", "category", "expected"),
    [
        ("scatter", None, "Sop/scatter::2.0"),
        ("scatter", "Sop", "Sop/scatter::2.0"),
        ("copy to points", None, "Sop/copytopoints::2.0"),
        ("copy to points", "Sop", "Sop/copytopoints::2.0"),
        ("polyreduce", None, "Sop/polyreduce::2.0"),
        ("Box", "Sop", "Sop/box"),
    ],
)
def test_search_ranks_exact_current_version_first(client, query, category, expected):
    args = {"query": query, "limit": 5}
    if category:
        args["category"] = category
    result = client.ok("node_type_search", args)
    assert _names(result)[0] == expected, _names(result)
    top = result["results"][0]
    assert top["is_current_version"] is True
    assert top["deprecated"] is False
    assert result["total"] >= len(result["results"])


@pytest.mark.parametrize(
    ("query", "top"),
    [
        ("scatter points on a surface", 1),
        ("noise on a surface", 4),
        ("smooth geometry", 1),
        ("extrude faces", 1),
    ],
)
def test_search_plain_language(client, query, top):
    """Review 07 papercut 5: a word that names the type or a word of its label outranks
    description-only matches; stop words do not count."""
    expected = {
        "scatter points on a surface": {"Sop/scatter::2.0"},
        "noise on a surface": {"Sop/attribnoise::2.0", "Sop/mountain"},
        "smooth geometry": {"Sop/smooth::2.0"},
        "extrude faces": {"Sop/polyextrude::2.0"},
    }[query]
    names = _names(client.ok("node_type_search", {"query": query, "category": "Sop", "limit": 10}))
    assert expected & set(names[:top]), names
    if query == "scatter points on a surface":
        assert _names(client.ok("node_type_search", {"query": query, "limit": 5}))[0] == (
            "Sop/scatter::2.0"
        )


def test_search_rows_and_older_versions(client):
    result = client.ok(
        "node_type_search",
        {"query": "scatter", "category": "Sop", "limit": 3, "current_only": False},
    )
    first, second = result["results"][:2]
    assert first["name"] == "scatter::2.0"
    assert first["label"] == "Scatter"
    assert first["version"] == "2.0"
    assert first["inputs"] == {"min": 1, "max": 1}
    assert "points" in first["description"].lower()
    assert set(first) >= {"name", "label", "category", "version", "is_current_version",
                          "description", "inputs", "deprecated"}  # fmt: skip
    assert second["name"] == "scatter"
    assert second["is_current_version"] is False
    assert second["current"] == "scatter::2.0"


def test_search_current_only_folds_older_versions(client):
    """Review 11 B6: current versions only by default, older ones named on the row."""
    result = client.ok("node_type_search", {"query": "scatter", "category": "Sop", "limit": 10})
    names = [r["name"] for r in result["results"]]
    assert names[0] == "scatter::2.0"
    assert "scatter" not in names
    assert result["results"][0]["other_versions"] == ["scatter"]
    assert all(r["is_current_version"] for r in result["results"])
    every = client.ok(
        "node_type_search",
        {"query": "scatter", "category": "Sop", "limit": 10, "current_only": False},
    )
    assert "scatter" in [r["name"] for r in every["results"]]
    assert every["total"] > result["total"]
    assert "other_versions" not in every["results"][0]


def test_search_descriptions_are_capped(client):
    result = client.ok("node_type_search", {"query": "noise", "limit": 50})
    assert result["results"]
    assert all(len(r["description"]) <= 120 for r in result["results"])
    assert any(r["description"].endswith("…") for r in result["results"])


def test_type_not_found_candidates_use_synonyms(client):
    """Review 11 B10: distantlight is hlight in /obj."""
    error = client.error("node_type_info", {"type": "distantlight", "category": "Object"})
    assert error["code"] == "node_type_not_found"
    assert error["candidates"][0] == "hlight", error
    spot = client.error("node_type_info", {"type": "spot_light", "category": "Object"})
    assert "hlight" in spot["candidates"][:3], spot


def test_search_by_label_words_and_category_filter(client):
    result = client.ok("node_type_search", {"query": "noise", "category": "Vop", "limit": 5})
    assert result["results"] and all(r["category"] == "Vop" for r in result["results"])
    lop = client.ok("node_type_search", {"query": "sublayer", "category": "Lop"})
    assert lop["results"][0]["name"] == "sublayer"


def test_search_hidden(client):
    hidden = [
        t
        for t in hou.sopNodeTypeCategory().nodeTypes().values()
        if t.hidden() and not t.nameComponents()[0]
    ]
    target = hidden[0].name()
    default = client.ok("node_type_search", {"query": target, "category": "Sop"})
    assert target not in [r["name"] for r in default["results"]]
    shown = client.ok(
        "node_type_search",
        {"query": target, "category": "Sop", "include_hidden": True, "current_only": False},
    )
    row = next(r for r in shown["results"] if r["name"] == target)
    assert row["hidden"] is True


def test_search_errors_and_empty(client):
    assert client.error("node_type_search", {"query": " "})["code"] == "invalid_argument"
    error = client.error("node_type_search", {"query": "box", "category": "Sops"})
    assert error["code"] == "invalid_argument" and "Sop" in error["candidates"]
    empty = client.ok("node_type_search", {"query": "zzqqxxnothing"})
    assert empty["results"] == [] and empty["total"] == 0 and empty["hint"]


# -- info -------------------------------------------------------------------------


def _assert_no_side_effects(before_children: int, before_undo: tuple) -> None:
    assert len(hou.node("/obj").children()) == before_children
    assert len(hou.node("/img").children()) == 0
    assert hou.undos.undoLabels() == before_undo


def test_info_box(client):
    before = (len(hou.node("/obj").children()), hou.undos.undoLabels())
    info = client.ok("node_type_info", {"type": "Sop/box", "detail": "full"})
    _assert_no_side_effects(*before)
    assert info["name"] == "box" and info["category"] == "Sop" and info["label"] == "Box"
    assert info["help_url"] == "operator:Sop/box"
    assert info["description"].startswith("Creates a cube")
    assert info["inputs"] == [{"index": 0, "name": "input1", "label": "Bounding Source"}]
    assert info["outputs"][0]["name"] == "output1"
    assert info["min_inputs"] == 0 and info["max_inputs"] == 1
    parms = {p["name"]: p for p in info["parms"]}
    assert parms["size"]["components"] == ["sizex", "sizey", "sizez"]
    assert parms["size"]["default"] == [1.0, 1.0, 1.0]
    assert parms["t"]["components"] == ["tx", "ty", "tz"]
    assert parms["type"]["menu"]["items"][0] == ["poly", "Polygon"]
    assert parms["type"]["default_token"] == "poly"
    assert parms["scale"]["type"] == "float" and parms["scale"]["max"] == 10.0
    assert "help_text" not in info
    size = len(json.dumps(info, separators=(",", ":")))
    assert size < 5000, size


def test_info_component_names_match_real_parms(client):
    geo = hou.node("/obj").createNode("geo")
    for type_name in ("box", "scatter", "xform", "copytopoints"):
        node = geo.createNode(type_name)
        info = client.ok("node_type_info", {"type": type_name, "category": "Sop", "detail": "full"})
        assert info["name"] == node.type().name()
        for parm in info["parms"]:
            if "#" in parm["name"] or parm["type"] == "multiparm":
                continue
            for component in parm.get("components", [parm["name"]]):
                assert node.parm(component) is not None or node.parmTuple(component), (
                    type_name,
                    component,
                )


def test_info_bare_name_resolves_like_create_node(client):
    info = client.ok("node_type_info", {"type": "scatter", "category": "Sop", "detail": "full"})
    assert info["name"] == "scatter::2.0"
    assert info["is_current_version"] is True
    assert info["versions"] == ["scatter::2.0", "scatter"]
    assert info["inputs"][0]["label"] == "Geometry to scatter points onto"
    assert "Options" in info["folders"]
    npts = next(p for p in info["parms"] if p["name"] == "npts")
    assert npts["folder"] == "Options" and npts["label"] == "Force Total Count"
    # Unique in one category: no category needed.
    assert client.ok("node_type_info", {"type": "scatter"})["name"] == "scatter::2.0"
    assert client.ok("node_type_info", {"type": "Sop/scatter"})["name"] == "scatter::2.0"
    old = client.ok("node_type_info", {"type": "Sop/scatter::2.0", "include_parms": False})
    assert old["name"] == "scatter::2.0" and "parms" not in old


def test_info_folder_filter(client):
    info = client.ok(
        "node_type_info", {"type": "Sop/scatter", "folder": "Output Attributes", "detail": "full"}
    )
    assert info["parms"] and all(p["folder"] == "Output Attributes" for p in info["parms"])
    compact = client.ok("node_type_info", {"type": "Sop/scatter", "folder": "Output Attributes"})
    assert list(compact["parms"]) == ["Output Attributes"]
    error = client.error("node_type_info", {"type": "Sop/scatter", "folder": "Nope"})
    assert error["code"] == "invalid_argument" and "Options" in error["candidates"]


def test_info_lop_type(client):
    info = client.ok("node_type_info", {"type": "Lop/sublayer"})
    assert info["category"] == "Lop"
    assert [i["label"] for i in info["inputs"]] == ["Input Stage", "Add As Sublayer"]
    assert len(hou.node("/stage").children()) == 0


def test_info_cop_types(client):
    cop = client.ok("node_type_info", {"type": "blur", "category": "Cop"})
    assert cop["category"] == "Cop"
    assert [i["name"] for i in cop["inputs"]] == ["source", "size"]
    cop2 = client.ok("node_type_info", {"type": "Cop2/blur"})
    assert cop2["inputs"][0]["label"] == "Image to Blur"
    assert len(hou.node("/obj").children()) == 0 and len(hou.node("/img").children()) == 0


def test_info_help_text(client):
    info = client.ok(
        "node_type_info", {"type": "Sop/scatter", "include_help": True, "detail": "full"}
    )
    assert info["help_source"] == "nodes.zip:sop/scatter.txt"
    text = info["help_text"]
    assert text.startswith("Scatter")
    assert "Scatters new points randomly" in text
    assert "#type:" not in text and "[Node:" not in text
    assert len(text) <= 2100
    assert info["help_truncated"] is True
    npts = next(p for p in info["parms"] if p["name"] == "npts")
    assert npts.get("help")
    box = client.ok("node_type_info", {"type": "Sop/box", "include_help": True})
    assert "Creates a cube" in box["help_text"]


def test_info_errors(client):
    error = client.error("node_type_info", {"type": "Sop/scater"})
    assert error["code"] == "node_type_not_found"
    assert "scatter::2.0" in error["candidates"]
    error = client.error("node_type_info", {"type": "copytopoints"})
    assert error["code"] == "invalid_argument"
    assert error["candidates"] == ["Sop/copytopoints::2.0", "Lop/copytopoints"]
    assert client.error("node_type_info", {"type": ""})["code"] == "invalid_argument"
    error = client.error("node_type_info", {"type": "Sop/box", "detail": "brief"})
    assert error["code"] == "invalid_argument"


def test_info_compact_is_the_default(client):
    """Review 07 papercut 5/6: 12.6 KB of scatter to find npts was too much."""
    full = client.ok("node_type_info", {"type": "Sop/scatter", "detail": "full"})
    info = client.ok("node_type_info", {"type": "Sop/scatter"})
    size = len(json.dumps(info, separators=(",", ":")))
    full_size = len(json.dumps(full, separators=(",", ":")))
    print(f"node_type_info Sop/scatter: compact {size} B, full {full_size} B")
    assert size < full_size * 0.6 and size < 3200, (size, full_size)
    assert info["detail"] == "compact" and "full" in info["hint"]
    assert "folders" not in info
    assert info["parm_columns"] == ["name", "label", "type", "default", "components"]
    options = {row[0]: row for row in info["parms"]["Options"]}
    assert options["npts"] == ["npts", "Force Total Count", "int", 1000]
    rows = [row for group in info["parms"].values() for row in group]
    assert all(len(row) in (4, 5) for row in rows)
    box = client.ok("node_type_info", {"type": "Sop/box"})
    by_name = {row[0]: row for group in box["parms"].values() for row in group}
    assert by_name["size"][4] == ["sizex", "sizey", "sizez"]
    assert by_name["type"][3] == "poly"  # a menu's default is its token
    copy = client.ok("node_type_info", {"type": "Sop/copytopoints"})
    assert len(json.dumps(copy, separators=(",", ":"))) < 2000


# -- review 10 ----------------------------------------------------------------------


def test_info_multi_output_hda_lists_every_output(client):
    info = client.ok("node_type_info", {"type": "Sop/rbdmaterialfracture", "include_parms": False})
    assert [o["label"] for o in info["outputs"]] == [
        "Geometry",
        "Constraint Geometry",
        "Proxy Geometry",
    ]


def test_info_probe_never_shows_in_events(client):
    from hocuspocus.host.tools import events

    client.ok("events", {})  # installs the hooks
    since = events.LOG.last_seq
    # Uncached types in categories whose probe needs a temporary container.
    for type_name in ("Sop/polyextrude::2.0", "Dop/rbdsolver", "Chop/wave"):
        client.ok("node_type_info", {"type": type_name, "include_parms": False})
    recorded = client.ok("events", {"since": since})["events"]
    assert recorded == [], recorded
    assert not [n for n in hou.node("/").allSubChildren() if "type_probe" in n.name()]


def test_info_parms_glob_filters_by_name_or_label(client):
    info = client.ok("node_type_info", {"type": "Sop/scatter", "parms": "npts"})
    rows = [row for folder in info["parms"].values() for row in folder]
    assert [row[0] for row in rows] == ["npts"]
    by_label = client.ok(
        "node_type_info", {"type": "Sop/scatter", "parms": "*seed*", "detail": "full"}
    )
    assert by_label["parms"] and all(
        "seed" in p["name"].lower() or "seed" in p["label"].lower() for p in by_label["parms"]
    )
    none = client.ok("node_type_info", {"type": "Sop/box", "parms": "zzz*"})
    assert none["parms"] == {} and "zzz*" in none["hint"]


def test_info_folders_mode(client):
    info = client.ok("node_type_info", {"type": "Sop/scatter", "detail": "folders"})
    folders = {row["folder"]: row["parms"] for row in info["folders"]}
    assert "Options" in folders and folders["Options"] > 0
    assert "parms" not in info
    full = client.ok("node_type_info", {"type": "Sop/scatter", "detail": "full"})
    visible = [p for p in full["parms"] if not p.get("is_hidden")]
    assert sum(folders.values()) == len(visible)


def test_info_does_not_recount_types(client, monkeypatch):
    from hocuspocus.host.tools import types

    client.ok("node_type_search", {"query": "box"})

    def boom():
        raise AssertionError("_type_count called")

    monkeypatch.setattr(types, "_type_count", boom, raising=False)
    client.ok("node_type_search", {"query": "sphere"})
    client.ok("node_type_info", {"type": "Sop/box", "include_parms": False})


def test_info_top_level_folder_and_parm_alternatives(client):
    """Review 12 papercut 2: the (no folder) label is accepted, and parms takes a|b."""
    folders = client.ok("node_type_info", {"type": "Sop/polyextrude", "detail": "folders"})
    names = [row["folder"] for row in folders["folders"]]
    assert names[0] == "(no folder)"
    for label in ("(no folder)", "", "(No Folder)"):
        info = client.ok(
            "node_type_info", {"type": "Sop/polyextrude", "folder": label, "detail": "full"}
        )
        top = [p["name"] for p in info["parms"]]
        assert {"dist", "inset"} <= set(top), (label, top)
        assert all(not p.get("folder") for p in info["parms"])
    for name in names:  # detail: folders lists only names folder accepts
        assert client.ok("node_type_info", {"type": "Sop/polyextrude", "folder": name})["parms"]
    pair = client.ok("node_type_info", {"type": "Sop/polyextrude", "parms": "dist|inset"})
    rows = [row[0] for rows in pair["parms"].values() for row in rows]
    assert sorted(rows) == ["dist", "inset"]
    both = client.ok(
        "node_type_info", {"type": "Sop/polyextrude", "folder": "", "parms": "Dist | *inset*"}
    )
    assert {row[0] for row in both["parms"]["(no folder)"]} >= {"dist", "inset"}
    error = client.error("node_type_info", {"type": "Sop/polyextrude", "folder": "Nope"})
    assert error["code"] == "invalid_argument" and error["candidates"] == names
    assert client.error("node_type_info", {"type": "Sop/box", "parms": "|"})["code"] == (
        "invalid_argument"
    )
