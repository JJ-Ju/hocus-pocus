from __future__ import annotations

import copy
import json

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.hocusscript.document_runtime_contract import (
    DocumentRuntimeContractError,
    attach_runtime_contract,
    validate_runtime_contract,
)
from hocuspocus.live.ops.document_runtime_contract import (
    execute_animation_clears,
    execute_animation_updates,
    execute_spare_changes,
    plan_runtime_changes,
    snapshot_runtime_contract,
)
from hocuspocus.live.ops.document_snapshot import (
    _prune_runtime_binding_observations,
)


def assert_runtime_semantic_trust(testcase, graph, semantic) -> None:
    from hocuspocus.hocusscript.document_bundle_semantics import (
        _FreshDocumentSemanticError, _validate_semantic_equivalence,
    )
    from hocuspocus.hocusscript.runtime_semantic import validate_runtime_evidence

    forged = copy.deepcopy(semantic)
    spare = next(item for item in forged["runtimeSelections"] if item["kind"] == "spare")
    spare["jsonPointer"] = "/forged"
    with testcase.assertRaises(ValueError):
        validate_runtime_evidence(
            graph, forged["runtimeSelections"], forged["parameterSelections"],
        )
    with testcase.assertRaises(_FreshDocumentSemanticError):
        _validate_semantic_equivalence(semantic, forged)


class _Enum:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def __eq__(self, other):
        return isinstance(other, _Enum) and self._name == other._name


class _Template:
    def __init__(
        self, name, label, components, default, type_name, *,
        menu_items=(), menu_labels=(),
    ):
        self._name = name
        self._label = label
        self._components = components
        self._default = default
        self._type_name = type_name
        self._menu_items = tuple(menu_items)
        self._menu_labels = tuple(menu_labels)
        self._tags = {}

    def name(self):
        return self._name

    def label(self):
        return self._label

    def numComponents(self):
        return self._components

    def defaultValue(self):
        return self._default

    def type(self):
        return _Enum(self._type_name)

    def tags(self):
        return dict(self._tags)

    def setTags(self, tags):
        self._tags = dict(tags)

    def menuItems(self):
        return self._menu_items

    def menuLabels(self):
        return self._menu_labels

    def setMenuUseToken(self, _enabled):
        return None

    def isMultiParmInstance(self):
        return False


class _Keyframe:
    def __init__(self):
        self._time = 0.0
        self._value = 0.0
        self._expression = "bezier()"
        self._language = None

    def setTime(self, value):
        self._time = value

    def time(self):
        return self._time

    def setValue(self, value):
        self._value = value

    def value(self):
        return self._value

    def setExpression(self, expression, language):
        self._expression = expression
        self._language = language

    def expression(self):
        return self._expression

    def expressionLanguage(self):
        return self._language


class _Parm:
    def __init__(self, node, template, *, spare=False):
        self.node = node
        self.template = template
        self.spare = spare
        self.keys = []
        self.extrapolation = {True: _Enum("Constant"), False: _Enum("Constant")}

    def path(self):
        return f"{self.node.path()}/{self.template.name()}"

    def parmTemplate(self):
        return self.template

    def isSpare(self):
        return self.spare

    def deleteAllKeyframes(self):
        self.keys = []

    def keyframes(self):
        return tuple(self.keys)

    def setKeyframe(self, key):
        self.keys.append(copy.deepcopy(key))

    def setKeyframeExtrapolation(self, before, value):
        self.extrapolation[before] = value

    def keyframeExtrapolation(self, before):
        return self.extrapolation[before]


class _Group:
    def __init__(self, templates):
        self.templates = dict(templates)

    def append(self, template):
        self.templates[template.name()] = template

    def replace(self, old_name, template):
        self.templates.pop(old_name)
        self.templates[template.name()] = template

    def remove(self, name):
        self.templates.pop(name)


class _Node:
    def __init__(self, path):
        self._path = path
        self._locked = False
        self._data = {}
        self.templates = {}
        self.parms_by_name = {}

    def path(self):
        return self._path

    def parm(self, name):
        return self.parms_by_name.get(name)

    def spareParms(self):
        return tuple(
            parm for parm in self.parms_by_name.values() if parm.spare
        )

    def parmTemplateGroup(self):
        return _Group(self.templates)

    def setParmTemplateGroup(self, group, *, rename_conflicting_parms):
        assert rename_conflicting_parms is False
        self.templates = dict(group.templates)
        prior = self.parms_by_name
        self.parms_by_name = {
            name: prior.get(name, _Parm(self, template, spare=True))
            for name, template in self.templates.items()
        }

    def isInsideLockedHDA(self):
        return self._locked

    def userData(self, key):
        return self._data.get(key)

    def setUserData(self, key, value):
        self._data[key] = value


class _Hou:
    exprLanguage = type("Expr", (), {"Hscript": _Enum("Hscript")})
    parmExtrapolate = type(
        "Extrapolate",
        (),
        {
            name: _Enum(name)
            for name in ("Hold", "Slope", "Cycle", "CycleOffset", "Oscillate")
        },
    )
    Keyframe = _Keyframe

    def __init__(self, node):
        self._node = node

    def node(self, path):
        return self._node if path == self._node.path() else None

    @staticmethod
    def FloatParmTemplate(name, label, components, default_value):
        return _Template(name, label, components, default_value, "Float")

    @staticmethod
    def IntParmTemplate(name, label, components, default_value):
        return _Template(name, label, components, default_value, "Int")

    @staticmethod
    def StringParmTemplate(name, label, components, default_value):
        return _Template(name, label, components, default_value, "String")

    @staticmethod
    def ToggleParmTemplate(name, label, default_value):
        return _Template(name, label, 1, default_value, "Toggle")

    @staticmethod
    def MenuParmTemplate(
        name, label, tokens, *, menu_labels, default_value,
    ):
        return _Template(
            name, label, 1, default_value, "Menu",
            menu_items=tokens, menu_labels=menu_labels,
        )


class _Operations:
    def __init__(self, node):
        self.hou = _Hou(node)

    def _require_hou(self):
        return self.hou

    @staticmethod
    def _safe_value(callback, default):
        try:
            return callback()
        except Exception:
            return default

    @staticmethod
    def _document_apply_state_current_path(state, uid, fallback):
        return state["uidToPath"].get(uid, fallback)


def _base_document():
    return {
        "$schema": "hocuspocus://schemas/network-document/v2",
        "kind": "network_document",
        "documentId": "network:/obj/geo1",
        "documentRevision": 1,
        "rootPath": "/obj/geo1",
        "category": "Sop",
        "nodes": [{
            "uid": "node:geo1",
            "name": "geo1",
            "typeName": "geo",
            "category": "Object",
            "path": "/obj/geo1",
            "parentPath": "/obj",
            "isNetwork": True,
            "flags": {},
            "metadata": {},
        }],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
        "metadata": {"hocusPreview": {"ownership": "team-a"}},
    }


def _spare():
    return {
        "uid": "spare:gain",
        "nodeUid": "node:geo1",
        "name": "gain",
        "label": "Gain",
        "type": "float",
        "tupleSize": 1,
        "default": [1.0],
        "menuItems": [],
        "metadata": {
            "source": "test",
            "hocus": {"ownership": "team-a"},
        },
    }


def _animation():
    return {
        "uid": "animation:gain",
        "nodeUid": "node:geo1",
        "parmName": "gain",
        "valueType": "float",
        "value": 1.0,
        "authoredFps": 24.0,
        "displayFps": 30.0,
        "extrapolation": {"before": "constant", "after": "cycle"},
        "keys": [
            {
                "timeSeconds": 0.0,
                "value": 1.0,
                "interpolation": "linear",
            },
            {
                "timeSeconds": 1.0,
                "value": 2.0,
                "interpolation": "bezier",
            },
        ],
        "metadata": {
            "source": "test",
            "hocus": {"ownership": "team-a"},
        },
    }


def _assert_runtime_binding_observations_pruned(
    testcase, target, binding_targets,
) -> None:
    testcase.assertEqual(
        binding_targets, {("node:geo1", "gain")}
    )
    observed = copy.deepcopy(target)
    observed["parameterBindings"] = [{
        "uid": "binding:runtime",
        "nodeUid": "node:geo1",
        "parmName": "gain",
        "valueMode": "code_reference",
        "codeBlobUid": "code:runtime",
        "metadata": {},
    }, {
        "uid": "binding:artist",
        "nodeUid": "node:geo1",
        "parmName": "artist_note",
        "valueMode": "code_reference",
        "codeBlobUid": "code:artist",
        "metadata": {},
    }]
    observed["codeBlobs"] = [
        {"uid": "code:runtime"},
        {"uid": "code:artist"},
    ]
    _prune_runtime_binding_observations(observed, binding_targets)
    testcase.assertEqual(
        [item["uid"] for item in observed["parameterBindings"]],
        ["binding:artist"],
    )
    testcase.assertEqual(
        [item["uid"] for item in observed["codeBlobs"]],
        ["code:artist"],
    )


def assert_managed_spare_and_animation_contract(testcase) -> None:
    baseline = _base_document()
    target = attach_runtime_contract(
        baseline,
        spare_parameters=[_spare()],
        animations=[_animation()],
    )
    validate_runtime_contract(target)
    forged = copy.deepcopy(target)
    forged["timeSamples"] = [{"usdPath": "/World"}]
    with testcase.assertRaises(DocumentRuntimeContractError):
        validate_runtime_contract(forged)
    forged = copy.deepcopy(target)
    forged["animations"][0]["keys"][1]["timeSeconds"] = 0.0
    with testcase.assertRaises(DocumentRuntimeContractError):
        validate_runtime_contract(forged)
    forged = copy.deepcopy(target)
    forged["animations"][0]["keys"][0]["slope"] = 1.0
    forged["animations"][0]["keys"][0]["accel"] = 0.0
    with testcase.assertRaises(DocumentRuntimeContractError):
        validate_runtime_contract(forged)
    forged = copy.deepcopy(target)
    forged["animations"][0]["keys"][1]["slope"] = 1.0
    with testcase.assertRaises(DocumentRuntimeContractError):
        validate_runtime_contract(forged)
    forged["animations"][0]["keys"][1]["accel"] = 0.0
    validate_runtime_contract(forged)
    forged = copy.deepcopy(target)
    nested = {}
    cursor = nested
    for _ in range(40):
        cursor["next"] = {}
        cursor = cursor["next"]
    forged["animations"][0]["metadata"] = nested
    with testcase.assertRaises(DocumentRuntimeContractError):
        validate_runtime_contract(forged)
    forged = copy.deepcopy(target)
    forged["parameterBindings"] = [{
        "uid": "binding",
        "nodeUid": "node:geo1",
        "parmName": "gain",
        "valueMode": "literal",
        "value": "constant()",
        "metadata": {},
    }]
    validate_runtime_contract(forged)
    forged["parameterBindings"][0]["valueMode"] = "expression"
    forged["parameterBindings"][0]["expression"] = "ch('../x')"
    forged["parameterBindings"][0]["expressionLanguage"] = "hscript"
    forged["parameterBindings"][0]["metadata"] = {
        "hocus": {"entityKind": "parameter_binding"},
    }
    with testcase.assertRaises(DocumentRuntimeContractError):
        validate_runtime_contract(forged)

    node = _Node("/obj/geo1")
    artist_template = _Template(
        "artist_note", "Artist Note", 1, ("keep",), "String"
    )
    node.templates["artist_note"] = artist_template
    node.parms_by_name["artist_note"] = _Parm(
        node, artist_template, spare=True
    )
    operations = _Operations(node)
    state = {"uidToPath": {"node:geo1": "/obj/geo1"}}
    nodes = {"node:geo1": target["nodes"][0]}
    plan = plan_runtime_changes(
        baseline, target, mode="reconcile",
        target_nodes=nodes, create_uids=set(),
    )
    executed = []
    checkpoint = lambda: None
    execute_spare_changes(
        operations, plan["spareParameterChanges"], state, executed, checkpoint
    )
    execute_animation_updates(
        operations, plan["animationUpdates"], state, executed, checkpoint
    )
    testcase.assertIn("artist_note", node.parms_by_name)
    spares, animations, diagnostics, binding_targets = snapshot_runtime_contract(
        operations, baseline
    )
    testcase.assertEqual(diagnostics, [])
    testcase.assertEqual(spares, target["spareParameters"])
    testcase.assertEqual(animations, target["animations"])
    _assert_runtime_binding_observations_pruned(
        testcase, target, binding_targets,
    )
    testcase.assertEqual(
        json.loads(node.userData("hpmcp.runtime_contract"))["version"], 1
    )
    authenticated = node.userData("hpmcp.runtime_contract")
    node._data["hpmcp.runtime_contract"] = authenticated + " "
    with testcase.assertRaises(JsonRpcError):
        snapshot_runtime_contract(operations, baseline)
    node._data["hpmcp.runtime_contract"] = authenticated

    removal = plan_runtime_changes(
        target, baseline, mode="reconcile",
        target_nodes=nodes, create_uids=set(),
    )
    execute_animation_clears(
        operations, removal["animationClears"], state, executed, checkpoint
    )
    execute_spare_changes(
        operations, removal["spareParameterChanges"],
        state, executed, checkpoint,
    )
    testcase.assertNotIn("gain", node.parms_by_name)
    testcase.assertIn("artist_note", node.parms_by_name)
    testcase.assertEqual(
        plan_runtime_changes(
            target, baseline, mode="merge",
            target_nodes=nodes, create_uids=set(),
        )["spareParameterChanges"],
        [],
    )
    foreign_target = copy.deepcopy(baseline)
    foreign_target["metadata"] = {
        "hocusPreview": {"ownership": "team-b"}
    }
    foreign_plan = plan_runtime_changes(
        target,
        foreign_target,
        mode="reconcile",
        target_nodes=nodes,
        create_uids=set(),
    )
    testcase.assertEqual(foreign_plan["spareParameterChanges"], [])
    testcase.assertEqual(foreign_plan["animationClears"], [])
    foreign_baseline = copy.deepcopy(target)
    foreign_animation = foreign_baseline["animations"][0]
    foreign_animation["uid"] = "animation:foreign"
    foreign_animation["metadata"]["hocus"]["ownership"] = "team-b"
    with testcase.assertRaises(JsonRpcError):
        plan_runtime_changes(
            foreign_baseline,
            target,
            mode="merge",
            target_nodes=nodes,
            create_uids=set(),
        )
    retarget_baseline = copy.deepcopy(target)
    foreign_animation = copy.deepcopy(retarget_baseline["animations"][0])
    foreign_animation.update({
        "uid": "animation:foreign-target",
        "parmName": "foreign_target",
    })
    foreign_animation["metadata"]["hocus"]["ownership"] = "team-b"
    retarget_baseline["animations"].append(foreign_animation)
    retarget_target = copy.deepcopy(target)
    retarget_target["animations"][0]["parmName"] = "foreign_target"
    with testcase.assertRaises(JsonRpcError):
        plan_runtime_changes(
            retarget_baseline,
            retarget_target,
            mode="merge",
            target_nodes=nodes,
            create_uids=set(),
        )

    forged_node = _Node("/obj/geo1")
    forged_template = _Template(
        "gain", "Artist Forgery", 1, (9.0,), "Float"
    )
    forged_template.setTags({
        "hocuspocus.managed_spare_uid": "spare:gain"
    })
    forged_node.templates["gain"] = forged_template
    forged_node.parms_by_name["gain"] = _Parm(
        forged_node, forged_template, spare=True
    )
    with testcase.assertRaises(JsonRpcError):
        execute_spare_changes(
            _Operations(forged_node), plan["spareParameterChanges"],
            state, [], checkpoint,
        )

    node._locked = True
    with testcase.assertRaises(JsonRpcError):
        execute_spare_changes(
            operations, plan["spareParameterChanges"],
            state, [], checkpoint,
        )
