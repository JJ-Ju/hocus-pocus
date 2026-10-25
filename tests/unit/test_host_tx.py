"""The transaction engine (``host/tx.py``, spec-2.0 §2.4) on plain CPython: ``$id``
resolution, ``edit`` plan parsing, compensation, the execute loop's error and rollback
reporting, and plan validation against a fake ``hou`` scene."""

from __future__ import annotations

import types
from typing import Any

import pytest

from hocuspocus.host import tx
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit


# -- $id references -------------------------------------------------------------------


def test_ref_resolves_ids_and_children():
    ids = {"geo": "/obj/geo1", "box": "/obj/geo1/box1"}
    assert tx.resolve_ref("$geo", ids, ids, "parent", strict=True) == "/obj/geo1"
    assert tx.resolve_ref("$box/sizex", ids, ids, "path", strict=True) == "/obj/geo1/box1/sizex"
    assert tx.resolve_ref("/obj/geo1", ids, ids, "parent", strict=True) == "/obj/geo1"
    assert tx.resolve_ref(None, ids, ids, "from", strict=True) is None


def test_ref_to_an_unknown_name():
    # 1.4 tools pass path text through; edit refuses a name no op declares.
    assert tx.resolve_ref("$HIP/x", {}, (), "path", strict=False) == "$HIP/x"
    with pytest.raises(ToolError) as info:
        tx.resolve_ref("$nope", {}, {"geo"}, "parent", strict=True)
    assert info.value.code == "invalid_argument" and "$geo" in info.value.message


def test_ref_to_an_op_that_made_no_node():
    with pytest.raises(ToolError) as info:
        tx.resolve_ref("$later", {}, {"later"}, "from", strict=False)
    assert "has not produced a node" in info.value.message


def test_resolve_args_touches_only_path_fields():
    ids = {"a": "/obj/g/a", "b": "/obj/g/b"}
    args = {
        "parent": "/obj/g",
        "type": "xform",
        "inputs": [{"index": 0, "from": "$a"}],
        "parms": {"ty": {"expression": "$F"}, "label": "$a"},
    }
    out = tx.resolve_args("create", args, ids, ids, strict=True)
    assert out["inputs"] == [{"index": 0, "from": "/obj/g/a"}]
    assert out["parms"] == args["parms"]  # parm values are never rewritten
    assert args["inputs"][0]["from"] == "$a"  # the plan itself is not changed
    connect = tx.resolve_args("connect", {"from": "$a", "to": "$b"}, ids, ids)
    assert connect == {"from": "/obj/g/a", "to": "/obj/g/b"}
    paths = tx.resolve_args("delete", {"paths": ["$a", "/obj/x"]}, ids, ids)
    assert paths["paths"] == ["/obj/g/a", "/obj/x"]
    assert tx.resolve_args("set", "not a dict", ids, ids) == "not a dict"


def test_path_of_names_what_a_batch_error_names():
    assert tx.path_of("create", {"parent": "/obj/g", "name": "b"}) == "/obj/g/b"
    assert tx.path_of("create", {"parent": "/obj/g"}) == "/obj/g"
    assert tx.path_of("connect", {"to": "/obj/g/x"}) == "/obj/g/x"
    assert tx.path_of("set", {"node": "/obj/g/x", "parms": {}}) == "/obj/g/x"
    assert tx.path_of("delete", {"paths": ["/obj/a"]}) == "/obj/a"
    assert tx.path_of("select", {"paths": []}) is None
    assert tx.path_of("node", ["not", "a", "dict"]) is None


# -- parsing ------------------------------------------------------------------------------


def test_parse_ops_splits_options_and_normalises_delete():
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "b", "parent": "/obj", "type": "geo", "cook": False},
            {"op": "delete", "path": "/obj/x"},
            {"op": "set", "path": "/obj/b/tx", "value": 1, "frame": 12},
        ]
    )
    assert plan.strict_refs and plan.defer_rollback and not plan.partial
    create, delete, set_op = plan.ops
    assert create.id == "b" and create.opts == {"cook": False} and "cook" not in create.args
    assert delete.args == {"paths": ["/obj/x"]}
    assert set_op.opts == {"frame": 12.0} and "frame" not in set_op.args
    assert plan.declared == {"b"}


@pytest.mark.parametrize(
    ("ops", "needle"),
    [
        ([], "non-empty"),
        ([{"op": "make"}], "Unknown op"),
        ([{"op": "select", "paths": [], "id": "1x"}], "not an identifier"),
        ([{"op": "select", "paths": [], "id": "a"}, {"op": "select", "id": "a"}], "used twice"),
        ([{"op": "connect", "to": "/a", "from": "/b", "value": 1}], "takes no value"),
        ([{"op": "delete", "path": "/a", "paths": ["/b"]}], "not both"),
        (["create"], "must be an object"),
    ],
)
def test_parse_ops_refuses_malformed_plans(ops, needle):
    with pytest.raises(ToolError) as info:
        tx.parse_ops(ops)
    assert info.value.code == "invalid_argument" and needle in info.value.message
    if ops:
        assert info.value.message.startswith("ops[")  # review 25 papercut 3: not items[
        assert info.value.detail["rolled_back"] is True


def test_unknown_op_suggests_the_nearest():
    with pytest.raises(ToolError) as info:
        tx.parse_ops([{"op": "conect"}])
    assert info.value.candidates[0] == "connect"


# -- rollback ---------------------------------------------------------------------------


def test_rollback_runs_newest_first_and_reports_failures():
    done: list[int] = []
    rollback = tx.Rollback()
    rollback.add(lambda: done.append(1))
    mark = rollback.mark()
    rollback.add(lambda: done.append(2))
    rollback.add(lambda: done.append(3))
    assert rollback.run(mark) is True and done == [3, 2]
    rollback.add(lambda: 1 / 0)
    assert rollback.run() is False and done == [3, 2, 1]
    assert rollback.run() is True  # nothing left: vacuously true


def test_a_delete_cannot_be_compensated():
    rollback = tx.Rollback()
    rollback.cannot_undo()
    assert rollback.irreversible and rollback.run() is False


def test_checked_turns_a_false_restore_into_a_failure():
    rollback = tx.Rollback()
    rollback.add(tx._checked(lambda: False))
    assert rollback.run() is False


# -- execute with stand-in handlers ------------------------------------------------------


class _Node:
    def __init__(self, path: str) -> None:
        self._path = path

    def path(self) -> str:
        return self._path

    def sessionId(self) -> int:  # noqa: N802 - hou API
        return hash(self._path) & 0xFFFF


@pytest.fixture
def handlers(monkeypatch):
    """Stand-in ops: ``create`` makes ``parent/name`` (rolled back by dropping it from
    ``scene``), ``set`` fails when its value is ``"bad"``, ``delete`` cannot be undone."""
    scene: dict[str, Any] = {"log": [], "nodes": set()}

    def create(args, opts, index, st):
        path = f"{args['parent']}/{args['name']}"
        scene["nodes"].add(path)
        st.rollback.add(lambda: scene["nodes"].discard(path))
        scene["log"].append(("create", path))
        node = _Node(path)
        return tx.OpResult(index, tx.Op("create", args), node=node, path=path, nodes=[node])

    def set_(args, opts, index, st):
        if args.get("value") == "bad":
            raise ToolError("invalid_value", f"{args['path']}: bad value.")
        scene["log"].append(("set", args["path"]))
        return tx.OpResult(index, tx.Op("set", args), data={"path": args["path"]})

    def delete(args, opts, index, st):
        st.rollback.cannot_undo()
        scene["log"].append(("delete", args["paths"][0]))
        return tx.OpResult(index, tx.Op("delete", args), data={"deleted": args["paths"]})

    monkeypatch.setitem(tx.HANDLERS, "create", create)
    monkeypatch.setitem(tx.HANDLERS, "set", set_)
    monkeypatch.setitem(tx.HANDLERS, "delete", delete)
    return scene


def test_ids_resolve_to_what_earlier_ops_produced(handlers):
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "g", "parent": "/obj", "name": "geo1"},
            {"op": "create", "id": "b", "parent": "$g", "name": "box1"},
            {"op": "set", "path": "$b/sizex", "value": 2},
        ]
    )
    result = tx.execute(plan, ctx=None)
    assert handlers["log"] == [
        ("create", "/obj/geo1"),
        ("create", "/obj/geo1/box1"),
        ("set", "/obj/geo1/box1/sizex"),
    ]
    assert result.state.ids == {"g": "/obj/geo1", "b": "/obj/geo1/box1"}
    assert result.results[2].args["path"] == "/obj/geo1/box1/sizex"
    assert [n.path() for n, _cook in result.touched()] == ["/obj/geo1", "/obj/geo1/box1"]
    assert result.failures == {}


def test_a_failing_op_rolls_the_plan_back(handlers):
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "g", "parent": "/obj", "name": "geo1"},
            {"op": "set", "path": "$g/x", "value": "bad"},
        ]
    )
    with pytest.raises(ToolError) as info:
        tx.execute(plan, ctx=None)
    # Review 25 papercut 3: an edit error names the op field, not items[i] (path).
    assert info.value.message == "ops[1].value: bad value."
    assert info.value.detail == {
        "item": 1,
        "field": "value",
        "path": "/obj/geo1/x",
        "rolled_back": True,
    }
    assert handlers["nodes"] == set()


def test_after_a_delete_the_dispatcher_decides_rolled_back(handlers):
    plan = tx.parse_ops(
        [
            {"op": "delete", "path": "/obj/old"},
            {"op": "set", "path": "/obj/x", "value": "bad"},
        ]
    )
    with pytest.raises(ToolError) as info:
        tx.execute(plan, ctx=None)
    assert info.value.detail["rolled_back"] is None  # filled in by the dispatcher
    # A 1.4 tool's plan reports its compensation as is.
    plan.defer_rollback = False
    with pytest.raises(ToolError) as info:
        tx.execute(plan, ctx=None)
    assert info.value.detail["rolled_back"] is False


def test_partial_reverts_only_the_failing_op(handlers):
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "a", "parent": "/obj", "name": "a"},
            {"op": "set", "path": "$a/x", "value": "bad"},
            {"op": "set", "path": "$a/y", "value": 1},
        ],
        partial=True,
    )
    result = tx.execute(plan, ctx=None)
    assert handlers["nodes"] == {"/obj/a"}
    assert list(result.failures) == [1]
    assert result.failures[1]["detail"] == {
        "item": 1,
        "field": "value",
        "path": "/obj/a/x",
        "rolled_back": True,
    }
    assert [r.index for r in result.done()] == [0, 2]


def test_raw_errors_raise_the_op_error_unchanged(handlers):
    plan = tx.Plan([tx.Op("set", {"path": "/obj/x", "value": "bad"})], raw_errors=True)
    with pytest.raises(ToolError) as info:
        tx.execute(plan, ctx=None)
    assert info.value.message == "/obj/x: bad value." and info.value.detail is None


def test_a_reference_to_a_failed_op_fails_that_op_too(handlers):
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "a", "parent": "/obj", "name": "a"},
            {"op": "set", "id": "s", "path": "$a/x", "value": "bad"},
            {"op": "create", "parent": "$s", "name": "c"},
        ],
        partial=True,
    )
    result = tx.execute(plan, ctx=None)
    assert sorted(result.failures) == [1, 2]
    assert "has not produced a node" in result.failures[2]["message"]


def test_edit_checks_the_ops_after_a_failure_and_raises_every_problem(handlers):
    """BIBLE D56: the run is the validation. A failing op is reverted, the ops after it
    run in check mode against what the others leave, one that names the failed op is
    skipped (its root cause is reported once), and the plan is compensated before every
    problem is raised together."""
    seen: list[bool] = []
    original = tx.HANDLERS["set"]

    def set_(args, opts, index, st):
        seen.append(tx.checking())
        return original(args, opts, index, st)

    tx.HANDLERS["set"] = set_
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "a", "parent": "/obj", "name": "a"},
            {"op": "set", "id": "s", "path": "$a/x", "value": "bad"},
            {"op": "create", "parent": "$s", "name": "skipped"},
            {"op": "set", "path": "$a/y", "value": 1},
            {"op": "set", "path": "$a/z", "value": "bad"},
        ]
    )
    with pytest.raises(ToolError) as info:
        tx.execute(plan, ctx=None)
    error = info.value
    assert error.message == "ops[1].value: bad value. (+1 more problem(s))"
    assert [p["item"] for p in error.detail["problems"]] == [1, 4]
    assert error.detail["rolled_back"] is True
    assert seen == [False, True, True]  # check mode after the first failure
    assert handlers["nodes"] == set()
    assert ("create", "/obj/a/skipped") not in handlers["log"] and not tx.checking()


def test_partial_stop_keeps_the_ops_before_the_first_failure(handlers):
    plan = tx.parse_ops(
        [
            {"op": "create", "id": "a", "parent": "/obj", "name": "a"},
            {"op": "set", "path": "$a/x", "value": "bad"},
            {"op": "create", "parent": "/obj", "name": "b"},
        ],
        partial="stop",
    )
    result = tx.execute(plan, ctx=None)
    assert handlers["nodes"] == {"/obj/a"}
    assert result.state.stopped == 1 and list(result.failures) == [1]
    assert [r.index for r in result.done()] == [0]


@pytest.mark.parametrize(
    ("value", "mode"), [(None, False), (False, False), (True, True), ("stop", "stop")]
)
def test_partial_takes_true_false_or_stop(value, mode):
    assert tx.partial_mode({"partial": value}) == mode


@pytest.mark.parametrize("value", [1, 0, "yes", []])
def test_partial_refuses_anything_else(value):
    with pytest.raises(ToolError, match="partial"):
        tx.partial_mode({"partial": value})


# -- the fake hou scene the hint tests use --------------------------------------------------


class FakeTemplate:
    def __init__(self, name: str, size: int = 1, scheme: str = "XYZW") -> None:
        self._name, self._size, self._scheme = name, size, scheme

    def name(self) -> str:
        return self._name

    def numComponents(self) -> int:  # noqa: N802 - hou API
        return self._size

    def namingScheme(self) -> str:  # noqa: N802 - hou API
        return f"parmNamingScheme.{self._scheme}"

    def parmTemplates(self) -> tuple:  # noqa: N802 - hou API
        return ()


class FakeGroup:
    def __init__(self, templates: list[FakeTemplate]) -> None:
        self._templates = templates

    def entries(self) -> tuple:
        return tuple(self._templates)


class FakeCategory:
    def __init__(self, name: str, child: str | None = None) -> None:
        self._name = name
        self.types: dict[str, FakeType] = {}

    def name(self) -> str:
        return self._name

    def nodeTypes(self) -> dict:  # noqa: N802 - hou API
        return self.types


class FakeType:
    def __init__(
        self,
        name: str,
        category: FakeCategory,
        *,
        child: FakeCategory | None = None,
        inputs: int = 1,
        parms: list[FakeTemplate] | None = None,
    ) -> None:
        self._name, self._category, self._child, self._inputs = name, category, child, inputs
        self._parms = parms or []
        category.types[name] = self

    def name(self) -> str:
        return self._name

    def nameComponents(self) -> tuple:  # noqa: N802 - hou API
        return ("", "", self._name, "")

    def category(self) -> FakeCategory:
        return self._category

    def childTypeCategory(self) -> FakeCategory | None:  # noqa: N802 - hou API
        return self._child

    def maxNumInputs(self) -> int:  # noqa: N802 - hou API
        return self._inputs

    def maxNumOutputs(self) -> int:  # noqa: N802 - hou API
        return 1

    def parmTemplateGroup(self) -> FakeGroup:  # noqa: N802 - hou API
        return FakeGroup(self._parms)

    def hidden(self) -> bool:
        return False

    def description(self) -> str:
        return self._name.title()


class FakeHouNode:
    def __init__(self, scene: FakeScene, path: str, node_type: FakeType) -> None:
        self.scene, self._path, self._type = scene, path, node_type

    def path(self) -> str:
        return self._path

    def name(self) -> str:
        return self._path.rpartition("/")[2]

    def type(self) -> FakeType:
        return self._type

    def parent(self) -> FakeHouNode | None:
        head = self._path.rpartition("/")[0] or "/"
        return None if self._path == "/" else self.scene.nodes.get(head)

    def children(self) -> tuple:
        base = self._path.rstrip("/")
        return tuple(
            n for p, n in self.scene.nodes.items() if p != "/" and p.rpartition("/")[0] == base
        )

    def node(self, name: str) -> FakeHouNode | None:
        return self.scene.nodes.get(f"{self._path.rstrip('/')}/{name}")

    def childTypeCategory(self) -> FakeCategory | None:  # noqa: N802 - hou API
        return self._type.childTypeCategory()

    def isInsideLockedHDA(self) -> bool:  # noqa: N802 - hou API
        return False

    def isLockedHDA(self) -> bool:  # noqa: N802 - hou API
        return False

    def inputNames(self) -> tuple:  # noqa: N802 - hou API
        return tuple(f"input{i + 1}" for i in range(self._type.maxNumInputs()))

    def inputLabels(self) -> tuple:  # noqa: N802 - hou API
        return tuple(f"Input {i + 1}" for i in range(self._type.maxNumInputs()))

    def outputNames(self) -> tuple:  # noqa: N802 - hou API
        return ("output1",)

    def parm(self, name: str) -> Any:
        return name if name in {t.name() for t in self._type._parms} else None

    def parmTuple(self, name: str) -> Any:  # noqa: N802 - hou API
        return None

    def parmTuples(self) -> tuple:  # noqa: N802 - hou API
        return ()


class FakeScene:
    def __init__(self) -> None:
        self.manager = FakeCategory("Manager")
        self.obj = FakeCategory("Object")
        self.sop = FakeCategory("Sop")
        root_type = FakeType("root", self.manager, child=self.manager)
        objnet = FakeType("obj", self.manager, child=self.obj)
        self.geo = FakeType("geo", self.obj, child=self.sop, inputs=1)
        FakeType("box", self.sop, inputs=0, parms=[FakeTemplate("size", 3), FakeTemplate("t", 3)])
        FakeType("xform", self.sop, parms=[FakeTemplate("t", 3), FakeTemplate("scale")])
        FakeType("merge", self.sop, inputs=9999)
        self.nodes: dict[str, FakeHouNode] = {}
        self.add("/", root_type)
        self.add("/obj", objnet)
        self.add("/obj/geo1", self.geo)
        self.add("/obj/geo1/box1", self.sop.types["box"])

    def add(self, path: str, node_type: FakeType) -> FakeHouNode:
        self.nodes[path] = FakeHouNode(self, path, node_type)
        return self.nodes[path]

    def module(self) -> Any:
        categories = {c.name(): c for c in (self.manager, self.obj, self.sop)}

        def node_type(category: Any, name: str) -> Any:
            return category.types.get(name) if isinstance(category, FakeCategory) else None

        def preferred(spec: str, parent: Any = None) -> Any:
            category, _, name = spec.partition("/")
            return categories[category].types.get(name) if category in categories else None

        return types.SimpleNamespace(
            node=self.nodes.get,
            nodeType=node_type,
            preferredNodeType=preferred,
            nodeTypeCategories=lambda: categories,
            lopNodeTypeCategory=lambda: None,
            text=types.SimpleNamespace(alphaNumeric=lambda s: "".join(c for c in s if c.isalnum())),
        )
