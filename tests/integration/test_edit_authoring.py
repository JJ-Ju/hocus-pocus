"""``edit`` for tool authoring (review 26 P1 friction 2, 6, 7; BIBLE §4.5, D48-D50)
against real Houdini: patching a long string parm and setting one from a file, ``path``
as every op's node key, a dry run that refuses what the run would, and the spare parm
interface fields (conditions, folder types, layout, change, placement)."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")

SNIPPET = "\n".join(
    [
        "// facade",
        "float h = chf('height');",
        "int floors = chi('floors');",
        *[f"// filler line {i}" for i in range(400)],
        "for (int i = 0; i < floors; i++) {",
        "    addpoint(0, set(0, i * h, 0));",
        "}",
    ]
)


def _wrangle():
    geo = hou.node("/obj").createNode("geo", "g")
    node = geo.createNode("attribwrangle", "facade")
    node.parm("snippet").set(SNIPPET)
    return node


def _snippet(path: str) -> str:
    return hou.node(path).parm("snippet").unexpandedString()


# -- patch -------------------------------------------------------------------------------


def test_patch_changes_one_line_of_a_long_snippet(client):
    node = _wrangle()
    path = f"{node.path()}/snippet"
    result = client.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "set",
                    "path": path,
                    "patch": {"find": "i * h", "replace": "i * h * 1.05"},
                }
            ],
            "return": "ops",
        },
    )
    assert _snippet(node.path()) == SNIPPET.replace("i * h", "i * h * 1.05")
    row = result["results"][0]
    assert row["patched_lines"] == [
        SNIPPET.split("\n").index("    addpoint(0, set(0, i * h, 0));") + 1
    ]
    # Several edits in order, in the node form, and all: true.
    client.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "set",
                    "node": node.path(),
                    "parms": {
                        "snippet": {
                            "patch": [
                                {"find": "// filler line", "replace": "// line", "all": True},
                                {"find": "chf('height')", "replace": "chf('floor_h')"},
                            ]
                        }
                    },
                }
            ]
        },
    )
    text = _snippet(node.path())
    assert "// filler" not in text and text.count("// line ") == 400
    assert "chf('floor_h')" in text


def test_patch_that_does_not_match_once_changes_nothing(client):
    node = _wrangle()
    path = f"{node.path()}/snippet"
    for dry_run in (True, False):
        error = client.error(
            "edit",
            {
                "ops": [{"op": "set", "path": path, "patch": {"find": "float h = chf('hieght');"}}],
                "dry_run": dry_run,
            },
        )
        assert error["code"] == "invalid_value", error
        assert error["message"].startswith("ops[0].patch: ")
        assert error["candidates"][0] == "line 2: float h = chf('height');"
    error = client.error(
        "edit",
        {"ops": [{"op": "set", "path": path, "patch": {"find": "// filler", "replace": "x"}}]},
    )
    assert error["code"] == "invalid_value" and "occurs 400 times" in error["message"]
    assert "all: true" in error["hint"]
    spaced = client.error(
        "edit",
        {"ops": [{"op": "set", "path": path, "patch": {"find": "float  h =  chf('height');"}}]},
    )
    assert "whitespace" in spaced["hint"]
    assert _snippet(node.path()) == SNIPPET
    number = client.error(
        "edit",
        {"ops": [{"op": "set", "path": f"{node.path()}/class", "patch": {"find": "a"}}]},
    )
    assert number["code"] in ("invalid_value", "invalid_argument")


# -- value_file ----------------------------------------------------------------------------


def test_value_file_sets_a_string_parm(client, host, tmp_path):
    node = _wrangle()
    source = tmp_path / "vex" / "facade.vfl"
    source.parent.mkdir()
    source.write_text("// from a file\nf@x = 1;\n", encoding="utf-8")
    result = client.ok(
        "edit",
        {
            "ops": [
                {"op": "set", "path": f"{node.path()}/snippet", "value_file": source.as_posix()}
            ],
            "return": "ops",
        },
    )
    assert _snippet(node.path()) == "// from a file\nf@x = 1;\n"
    assert result["results"][0]["value_file"] == source.as_posix()
    missing = client.error(
        "edit",
        {
            "ops": [{"op": "set", "path": f"{node.path()}/snippet", "value_file": "C:/nope/x.vfl"}],
            "dry_run": True,
        },
    )
    assert missing["code"] == "file_not_found"
    host.config.approved_roots = [str(tmp_path / "elsewhere")]
    refused = client.error(
        "edit",
        {
            "ops": [
                {"op": "set", "path": f"{node.path()}/snippet", "value_file": source.as_posix()}
            ],
            "dry_run": True,
        },
    )
    assert refused["code"] == "path_not_allowed"
    host.config.approved_roots = []
    wrong = client.error(
        "edit",
        {"ops": [{"op": "set", "path": f"{node.path()}/class", "value_file": source.as_posix()}]},
    )
    assert wrong["code"] == "invalid_value" and "string parms" in wrong["message"]


# -- path as every op's node key -----------------------------------------------------------


def test_path_names_the_node_of_every_op(client):
    result = client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "g", "path": "/obj/towers", "type": "geo"},
                {"op": "create", "id": "b", "path": "$g/base", "type": "box"},
                {"op": "create", "id": "x", "path": "$g/lift", "type": "xform"},
                {"op": "connect", "from": "$b", "path": "$x"},
                {"op": "set", "path": "$x", "parms": {"ty": 2}},
                {"op": "node", "node": "$x", "comment": "lifted"},
                {"op": "layout", "path": "$g"},
                {"op": "select", "path": "$x"},
            ]
        },
    )
    assert result["ids"]["b"] == "/obj/towers/base"
    lift = hou.node("/obj/towers/lift")
    assert lift.inputs()[0].path() == "/obj/towers/base"
    assert lift.parm("ty").eval() == 2 and lift.comment() == "lifted"
    error = client.error(
        "edit",
        {"ops": [{"op": "node", "path": "/obj/towers/lift", "node": "/obj/towers/base"}]},
    )
    assert error["code"] == "invalid_argument" and "not both" in error["message"]
    bad = client.error("edit", {"ops": [{"op": "create", "path": "box1", "type": "box"}]})
    assert bad["code"] == "invalid_argument" and "ops[0].path" in bad["message"]


def test_errors_name_the_key_the_caller_sent(client):
    """An op's path is read as its 1.4 field; an error about it names path (or node), not
    parent, to, paths[0]."""
    geo = hou.node("/obj").createNode("geo", "g")
    geo.createNode("box", "box1")
    cases = [
        ({"op": "create", "path": "/obj/nope/box1", "type": "box"}, "path"),
        ({"op": "create", "path": "/obj/g/box1", "type": "box"}, "path"),  # name collision
        ({"op": "connect", "from": "/obj/g/box1", "path": "/obj/g/nope"}, "path"),
        ({"op": "delete", "path": "/obj/g/nope"}, "path"),
        ({"op": "set", "path": "/obj/g/nope", "parms": {"sizex": 1}}, "path"),
        ({"op": "node", "node": "/obj/g/nope", "comment": "x"}, "node"),
        ({"op": "layout", "path": "/obj/nope"}, "path"),
        # the 1.4 spelling is named as it was sent
        ({"op": "create", "parent": "/obj/nope", "type": "box"}, "parent"),
        ({"op": "connect", "from": "/obj/g/box1", "to": "/obj/g/nope"}, "to"),
    ]
    for op, field in cases:
        error = client.error("edit", {"ops": [op]})
        assert error["detail"]["field"] == field, (op, error)
        assert error["message"].startswith(f"ops[0].{field}: "), (op, error["message"])


# -- dry_run refuses what the run would ------------------------------------------------------


def _locked_asset(tmp_path):
    geo = hou.node("/obj").createNode("geo", "a")
    sub = geo.createNode("subnet", "asset")
    sub.createNode("box", "inner")
    library = (tmp_path / f"dry{hou.hda.defaultFileExtension()}").as_posix()
    asset = sub.createDigitalAsset(name="hptest::dry::1.0", hda_file_name=library)
    asset.matchCurrentDefinition()
    assert asset.isLockedHDA()
    return asset


def test_dry_run_refuses_a_set_inside_a_locked_asset(client, tmp_path):
    asset = _locked_asset(tmp_path)
    for op in (
        {"op": "set", "path": f"{asset.path()}/inner/sizex", "value": 2},
        {"op": "set", "node": f"{asset.path()}/inner", "parms": {"sizex": 2}},
    ):
        error = client.error("edit", {"ops": [op], "dry_run": True})
        assert error["code"] == "locked", error
        assert "lock: false" in error["hint"] and "allowEditingOfContents" in error["hint"]


def test_dry_run_checks_value_types_and_ranges(client):
    geo = hou.node("/obj").createNode("geo", "v")
    box = geo.createNode("box", "b")
    cases = [
        ({"op": "set", "path": f"{box.path()}/sizex", "value": "big"}, "invalid_value"),
        ({"op": "set", "path": f"{box.path()}/size", "value": [1, 2]}, "invalid_value"),
        ({"op": "set", "node": box.path(), "parms": {"divrate": "x"}}, "invalid_value"),
        ({"op": "set", "path": f"{box.path()}/type", "value": "nope"}, "invalid_value"),
    ]
    for op, code in cases:
        error = client.error("edit", {"ops": [op], "dry_run": True})
        assert error["code"] == code, (op, error)
    assert box.parm("sizex").eval() == 1


def test_dry_run_checks_spare_parms_on_a_node_it_creates(client):
    for spare in (
        {"seed": {"type": "int"}},  # the {name: {...}} shape of review 26 error 4
        {"add": [{"name": "w", "type": "float", "disable_when": "{ intreior == 0 }"}]},
        {"add": [{"name": "m", "type": "menu"}]},
        {"add": [{"name": "t", "type": "toggle", "default": 1}]},
    ):
        error = client.error(
            "edit",
            {
                "ops": [
                    {"op": "create", "id": "n", "parent": "/obj", "type": "null"},
                    {"op": "node", "path": "$n", "spare_parms": spare},
                ],
                "dry_run": True,
            },
        )
        assert error["code"] in ("invalid_argument", "invalid_value"), (spare, error)
        assert error["message"].startswith("ops[1].spare_parms"), error["message"]
    ok = client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "n", "parent": "/obj", "type": "null"},
                {
                    "op": "node",
                    "path": "$n",
                    "spare_parms": {"add": [{"name": "seedy", "type": "int"}]},
                },
                {"op": "set", "node": "$n", "parms": {"seedy": 3}},
            ],
            "dry_run": True,
        },
    )
    assert ok["dry_run"] is True


# -- spare parm interface fields -------------------------------------------------------------


def test_spare_parms_conditions_folders_layout_and_change(client):
    null = hou.node("/obj").createNode("null", "controls")
    spare = {
        "add": [
            {"type": "folder", "label": "Main", "folder_type": "collapsible"},
            {"name": "enable", "type": "toggle", "default": True, "folder": "Main",
             "join_next": True},
            {"name": "amount", "type": "float", "default": 0.5, "min": 0, "max": 1,
             "min_strict": True, "max_strict": True, "folder": "Main",
             "disable_when": "{ enable == 0 }", "hide_when": "{ mode == hidden }"},
            {"name": "mode", "type": "string", "default": "shown", "folder": ["Main", "More"],
             "menu_items": [{"token": "shown"}, {"token": "hidden"}]},
            {"name": "out", "type": "file", "default": "$HIP/out.fbx", "tags": {"hp": "1"}},
            {"type": "separator", "name": "sep1", "before": "out"},
            {"name": "go", "type": "button", "callback": "print('go')", "help": "Run."},
        ]
    }  # fmt: skip
    client.ok("edit", {"ops": [{"op": "node", "path": null.path(), "spare_parms": spare}]})
    group = null.parmTemplateGroup()
    main = group.findFolder("Main")
    assert main.folderType() == hou.folderType.Collapsible
    amount = group.find("amount")
    assert amount.minIsStrict() and amount.maxIsStrict()
    assert amount.conditionals()[hou.parmCondType.DisableWhen] == "{ enable == 0 }"
    assert amount.conditionals()[hou.parmCondType.HideWhen] == "{ mode == hidden }"
    assert group.find("enable").joinsWithNext()
    assert group.findFolder(("Main", "More")) is not None
    assert group.find("mode").menuType() == hou.menuType.StringReplace
    assert group.find("out").stringType() == hou.stringParmType.FileReference
    assert group.find("out").tags()["hp"] == "1"
    names = [t.name() for t in group.entries()]
    assert names.index("sep1") == names.index("out") - 1
    assert group.find("go").scriptCallback() == "print('go')"
    null.parm("amount").set(0.75)
    client.ok(
        "edit",
        {
            "ops": [
                {
                    "op": "node",
                    "path": null.path(),
                    "spare_parms": {
                        "change": [
                            {"name": "amount", "default": 0.25, "label": "Amount",
                             "disable_when": ""},
                            {"name": "Main", "folder_type": "simple"},
                            {"name": "go", "after": "out"},
                        ]
                    },
                }
            ]
        },
    )  # fmt: skip
    group = null.parmTemplateGroup()
    assert group.find("amount").defaultValue() == (0.25,)
    assert group.find("amount").label() == "Amount"
    assert hou.parmCondType.DisableWhen not in group.find("amount").conditionals() or (
        group.find("amount").conditionals()[hou.parmCondType.DisableWhen] == ""
    )
    assert group.findFolder("Main").folderType() == hou.folderType.Simple
    assert null.parm("amount").eval() == 0.75  # change keeps the value
    names = [t.name() for t in group.entries()]
    assert names.index("go") == names.index("out") + 1


def test_spare_parms_refuse_bad_conditions_and_type_parms(client):
    null = hou.node("/obj").createNode("null", "c2")
    error = client.error(
        "edit",
        {
            "ops": [
                {
                    "op": "node",
                    "path": null.path(),
                    "spare_parms": {
                        "add": [{"name": "w", "type": "float", "disable_when": "{ scal == 0 }"}]
                    },
                }
            ]
        },
    )
    assert error["code"] == "invalid_value" and "scal" in error["message"]
    assert "scale" in error["candidates"]
    error = client.error(
        "edit",
        {"ops": [{"op": "node", "path": null.path(), "spare_parms": {"change": [{"name": "tx"}]}}]},
    )
    assert error["code"] == "invalid_argument" and "only spare parms" in error["message"]
    error = client.error(
        "edit",
        {
            "ops": [
                {
                    "op": "node",
                    "path": null.path(),
                    "spare_parms": {"add": [{"name": "w", "type": "float", "before": "nope"}]},
                }
            ]
        },
    )
    assert error["code"] == "parm_not_found"
    assert null.spareParms() == ()


def test_spare_parms_min_alone_moves_the_soft_range(client):
    null = hou.node("/obj").createNode("null", "c3")
    spare = {"add": [{"name": "h", "type": "float", "default": 3.6, "min": 2, "min_strict": True}]}
    client.ok("edit", {"ops": [{"op": "node", "path": null.path(), "spare_parms": spare}]})
    template = null.parmTemplateGroup().find("h")
    assert (template.minValue(), template.maxValue()) == (2.0, 3.0)
    error = client.error(
        "edit",
        {
            "ops": [
                {
                    "op": "node",
                    "path": null.path(),
                    "spare_parms": {"add": [{"name": "k", "type": "int", "min": 5, "max": 1}]},
                }
            ]
        },
    )
    assert error["code"] == "invalid_argument" and "above max" in error["message"]
