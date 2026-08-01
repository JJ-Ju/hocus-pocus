from __future__ import annotations

import copy
from contextlib import contextmanager
from types import SimpleNamespace

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.live.houdini_undo import perform_stack_action
from hocuspocus.live.ops.scene import SceneOperationsMixin


class _Named:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Template:
    def __init__(self, kind, menu=()):
        self.kind, self.menu = kind, menu

    def type(self):
        return _Named(self.kind)

    def menuItems(self):
        return self.menu


class _Parm:
    def __init__(self, template, *, fail=False):
        self.template, self.fail, self.value = template, fail, None

    def parmTemplate(self):
        return self.template

    def set(self, value):
        if self.fail:
            raise TypeError("rejected value")
        self.value = value


class _Node:
    def __init__(self, parms):
        self.parms = parms

    def parm(self, name):
        return self.parms.get(name)


class _NodeType:
    def __init__(self, templates):
        self.templates = templates

    def parmTemplateGroup(self):
        return SimpleNamespace(find=lambda name: self.templates.get(name))


class _Category:
    name = lambda self: "Sop"
    nodeTypes = lambda self: {}


class _Undos:
    def __init__(self):
        self.undo, self.redo = ["HocusPocus: apply"], ["artist edit"]

    def undoLabels(self):
        return tuple(self.undo)

    def redoLabels(self):
        return tuple(self.redo)

    def performUndo(self):
        self.undo.pop(0)
        return True

    def performRedo(self):
        self.redo.pop(0)
        return True

    @contextmanager
    def group(self, label):
        self.undo.insert(0, label)
        yield


def _assert_output_contract(test, tools, network_document):
    numeric = {
        "name": "mode", "path": "/obj/geo1/node/mode", "label": "Mode",
        "templateType": "Int", "rawValue": "poly", "value": 1,
        "isAtDefault": False,
    }
    test.assertEqual(
        tools._document_binding_for_parm(numeric, "node", None)["value"], 1
    )
    baseline, target = network_document(), network_document()
    child = {
        "uid": "display", "path": "/obj/geo1/display", "name": "display",
        "parentPath": "/obj/geo1", "typeName": "null", "category": "Sop",
        "isNetwork": False, "position": [0.0, -1.0],
        "flags": {"display": True, "render": True, "bypass": False, "template": False},
        "metadata": {},
    }
    target["nodes"].append(child)
    stale = {
        "uid": "edge:output:stale", "kind": "output_flag",
        "from": {"nodeUid": "root"}, "to": {"nodeUid": "root"},
        "metadata": {},
    }
    target["edges"] = [stale]
    context = {
        "after": {item["uid"]: item for item in target["nodes"]},
        "rootUid": "root", "rootPath": "/obj/geo1",
    }
    guard, change = tools._document_plan_output(baseline, target, context, "sop")
    test.assertEqual((guard["sourceUid"], guard["authority"]), ("display", "node_flags"))
    test.assertIsNone(change)
    observed = copy.deepcopy(target)
    observed["edges"] = [{**stale, "uid": "edge:output:display", "from": {"nodeUid": "display"}}]
    test.assertTrue(tools._document_diff_is_clean(
        tools._document_verification_diff_payload(target, observed)
    ))
    other = {**copy.deepcopy(child), "uid": "other", "name": "other", "path": "/obj/geo1/other"}
    target["nodes"].append(other)
    diagnostics = tools._document_validate_network_document(target)
    test.assertIn("node.display.multiple", {item["code"] for item in diagnostics})


def _assert_preflight_contract(test, tools, network_document):
    baseline = network_document()
    parms = {
        "mode": _Parm(_Template("Int", ("points", "poly"))),
        "note": _Parm(_Template("Label")),
    }
    tools._require_hou = lambda: SimpleNamespace(
        node=lambda path: _Node(parms) if path == "/obj/geo1" else None,
        undos=_Undos(),
    )
    menu_plan = {
        "networkFamily": "sop", "parameterAssignments": [{
            "bindingUid": "binding:root:mode", "nodeUid": "root",
            "nodePath": "/obj/geo1", "parmName": "mode", "value": "poly",
            "metadata": {"templateType": "Int"},
        }],
    }
    frozen = copy.deepcopy(menu_plan)
    prepared, _ = tools._document_preflight_apply_plan(menu_plan, baseline)
    test.assertEqual(prepared["parameterAssignments"][0]["value"], 1)
    test.assertEqual(menu_plan, frozen)
    invalid = copy.deepcopy(menu_plan)
    invalid["parameterAssignments"][0].update(
        bindingUid="binding:root:note", parmName="note", value="x"
    )
    with test.assertRaises(JsonRpcError) as captured:
        tools._document_preflight_apply_plan(invalid, baseline)
    test.assertEqual(
        (captured.exception.data["bindingUid"], captured.exception.data["expectedType"]),
        ("binding:root:note", "label"),
    )
    _assert_preferred_types(test, tools, baseline)


def _assert_preferred_types(test, tools, baseline):
    calls = []
    preferred = _NodeType({"operation": _Template("Int", ("union", "subtract"))})
    old_node = _Node({"operation": _Parm(_Template("Label"))})
    tools._require_hou = lambda: SimpleNamespace(
        sopNodeTypeCategory=lambda: _Category(),
        node=lambda path: old_node if path == "/obj/geo1/old" else None,
        nodeType=lambda *_args: None,
        preferredNodeType=lambda name, parent: calls.append((name, parent)) or preferred,
    )
    assignment = {
        "bindingUid": "binding:node:operation", "nodeUid": "node",
        "nodePath": "/obj/geo1/old", "parmName": "operation",
        "value": "subtract", "metadata": {"templateType": "Int"},
    }
    created = {
        "networkFamily": "sop",
        "createNodes": [{"uid": "node", "path": "/obj/geo1/old", "parentPath": "/obj/geo1", "typeName": "boolean"}],
        "parameterAssignments": [assignment],
    }
    prepared, _ = tools._document_preflight_apply_plan(created, baseline)
    test.assertEqual(prepared["parameterAssignments"][0]["value"], 1)
    replacement_baseline = copy.deepcopy(baseline)
    replacement_baseline["nodes"].append({"uid": "node", "path": "/obj/geo1/old", "parentPath": "/obj/geo1"})
    replacement = {
        "networkFamily": "sop",
        "replaceNodes": [{"uid": "node", "currentPath": "/obj/geo1/old", "target": created["createNodes"][0]}],
        "parameterAssignments": [assignment],
    }
    prepared, _ = tools._document_preflight_apply_plan(replacement, replacement_baseline)
    test.assertEqual(prepared["parameterAssignments"][0]["value"], 1)
    test.assertEqual([item[0] for item in calls], ["Sop/boolean", "Sop/boolean"])


def _assert_inverse_path_preflight(test, tools, network_document):
    current = network_document()
    current["nodes"].append({
        "uid": "node", "path": "/obj/geo1/old", "parentPath": "/obj/geo1",
        "name": "old", "typeName": "box", "category": "Sop",
        "isNetwork": False, "position": [0.0, 0.0], "flags": {}, "metadata": {},
    })
    parm = _Parm(_Template("Int"))
    tools._require_hou = lambda: SimpleNamespace(
        node=lambda path: _Node({"mode": parm}) if path == "/obj/geo1/old" else None,
    )
    tools._hocus_canonical_digest = lambda value: repr(value)
    for move_field, future_path in (
        ("renameNodes", "/obj/geo1/new"),
        ("reparentNodes", "/obj/geo1/subnet/old"),
    ):
        target = copy.deepcopy(current)
        target["nodes"][-1].update(path=future_path, name=future_path.rsplit("/", 1)[-1])
        forward = _path_change_plan(move_field, "/obj/geo1/old", future_path, 2)
        inverse = _path_change_plan(move_field, future_path, "/obj/geo1/old", 0)
        frozen_forward = copy.deepcopy(forward)
        frozen_inverse = copy.deepcopy(inverse)
        prepared_forward, prepared_inverse = tools._document_prepare_hash_bound_apply(
            forward, forward, inverse, current, target
        )
        test.assertEqual(prepared_forward["parameterAssignments"][0]["value"], 2)
        test.assertEqual(prepared_inverse["parameterAssignments"][0]["value"], 0)
        test.assertEqual((forward, inverse), (frozen_forward, frozen_inverse))

        build = tools._document_build_apply_plan
        tools._document_build_apply_plan = lambda *_args, **_kwargs: copy.deepcopy(inverse)
        try:
            direct_inverse = tools._document_prepare_direct_inverse(
                forward, target, current
            )
        finally:
            tools._document_build_apply_plan = build
        test.assertEqual(direct_inverse["parameterAssignments"][0]["value"], 0)


def _path_change_plan(move_field, current_path, target_path, parm_value):
    operation = {
        "uid": "node", "currentPath": current_path, "path": target_path,
    }
    if move_field == "reparentNodes":
        operation["targetParentPath"] = target_path.rpartition("/")[0]
    return {
        "networkFamily": "sop", "summary": {}, move_field: [operation],
        "parameterAssignments": [{
            "bindingUid": "binding:node:mode", "nodeUid": "node",
            "nodePath": target_path, "parmName": "mode", "value": parm_value,
            "metadata": {"templateType": "Int"},
        }],
    }


def _assert_stack_contract(test):
    hou_module = SimpleNamespace(undos=_Undos())
    test.assertEqual(
        perform_stack_action(hou_module, "undo", expected_label="HocusPocus: apply")["label"],
        "HocusPocus: apply",
    )
    rejected = _Undos()
    rejected.performUndo = lambda: False
    with test.assertRaises(JsonRpcError) as captured:
        perform_stack_action(SimpleNamespace(undos=rejected), "undo", expected_label="HocusPocus: apply")
    test.assertFalse(captured.exception.to_payload()["data"]["retryable"])
    scene_hou = SimpleNamespace(undos=_Undos())
    scene = SimpleNamespace(
        _require_hou=lambda: scene_hou,
        _scene_summary_impl=lambda: {"sceneRevision": 4},
    )
    result = SceneOperationsMixin._scene_undo_impl(
        scene, {"expected_label": "HocusPocus: apply"}
    )
    test.assertEqual(result["stackAction"]["before"]["undoLabels"], ["HocusPocus: apply"])
    test.assertEqual(result["stackAction"]["after"]["undoLabels"], [])
    with test.assertRaises(JsonRpcError):
        SceneOperationsMixin._scene_redo_impl(scene, {"expected_label": "wrong"})
    with test.assertRaises(JsonRpcError):
        SceneOperationsMixin._scene_redo_impl(scene, {"expected_label": " "})
    test.assertEqual(
        SceneOperationsMixin._scene_redo_impl(scene)["stackAction"]["label"],
        "artist edit",
    )


def _direct_fixture(tools, network_document, *, clean_rollback, undo_fails=False):
    direct = type(tools)()
    parms = {"first": _Parm(_Template("Int")), "second": _Parm(_Template("Int"), fail=True)}
    undos = _Undos()
    if undo_fails:
        undos.performUndo = lambda: False
    hou_module = SimpleNamespace(
        node=lambda path: _Node(parms) if path == "/obj/geo1" else None,
        undos=undos,
    )
    baseline = network_document()
    forward = {
        "networkFamily": "sop", "summary": {},
        "parameterAssignments": [
            {"bindingUid": "binding:first", "nodeUid": "root", "nodePath": "/obj/geo1", "parmName": "first", "value": 1, "metadata": {"templateType": "Int"}},
            {"bindingUid": "binding:second", "nodeUid": "root", "nodePath": "/obj/geo1", "parmName": "second", "value": 2, "metadata": {"templateType": "Int"}},
        ],
    }
    inverse = {
        "networkFamily": "sop", "summary": {},
        "parameterAssignments": [{"bindingUid": "binding:first", "nodeUid": "root", "nodePath": "/obj/geo1", "parmName": "first", "value": 0, "metadata": {"templateType": "Int"}}],
    }
    plans = [copy.deepcopy(forward), copy.deepcopy(inverse)]
    direct._require_hou = lambda: hou_module
    direct._require_parm_by_path = lambda path: parms[path.rsplit("/", 1)[-1]]
    direct._document_validate_network_document = lambda _document: []
    direct._document_current_network_payload = lambda *_args, **_kwargs: copy.deepcopy(baseline)
    direct._document_diff_payload = lambda *_args: {"summary": {"changedNodeCount": 1}}
    direct._document_verification_diff_payload = lambda *_args: {"summary": {"changedNodeCount": 0 if clean_rollback else 1}}
    direct._document_build_apply_plan = lambda *_args, **_kwargs: plans.pop(0)
    direct._monitor = SimpleNamespace(mark_dirty=lambda *_args, **_kwargs: 1)
    direct._graph_store = SimpleNamespace()
    quarantine = {}
    direct._hocus_quarantine_map = lambda: quarantine
    return direct, baseline, quarantine


def _assert_direct_rollback_contract(test, tools, network_document):
    for clean, expected in ((True, "HOCUS755"), (False, "HOCUS756")):
        direct, target, quarantine = _direct_fixture(
            tools, network_document, clean_rollback=clean
        )
        with test.assertRaises(JsonRpcError) as captured:
            direct._document_apply_impl({"document": target, "mode": "merge"})
        test.assertEqual(captured.exception.data["diagnosticCode"], expected)
        test.assertEqual(bool(quarantine), not clean)
        test.assertEqual(
            [item["bindingUid"] for item in captured.exception.data["failure"]["executedOperations"]],
            ["binding:first"],
        )
    direct, target, quarantine = _direct_fixture(
        tools, network_document, clean_rollback=True, undo_fails=True
    )
    with test.assertRaises(JsonRpcError) as captured:
        direct._document_apply_impl({"document": target, "mode": "merge"})
    failure = captured.exception.data["failure"]
    test.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS755")
    test.assertEqual(failure["rollbackExecutedOperations"][0]["bindingUid"], "binding:first")
    test.assertEqual(quarantine, {})


def assert_mutation_integrity_contract(test, tools, network_document):
    _assert_output_contract(test, tools, network_document)
    _assert_preflight_contract(test, tools, network_document)
    _assert_inverse_path_preflight(test, tools, network_document)
    _assert_stack_contract(test)
    _assert_direct_rollback_contract(test, tools, network_document)
