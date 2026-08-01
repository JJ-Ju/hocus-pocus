from __future__ import annotations

import copy
from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace

from hocuspocus.core.policy import EDIT_SCENE, RUN_CODE, capability_projection
from hocuspocus.core.settings import available_policy_profiles
from hocuspocus.live.context import RequestContext
from hocuspocus.live.ops.hda_ops import HdaOperationsMixin
from hocuspocus.live.ops.session import SessionOperationsMixin


class _Template:
    def __init__(self, name: str, default: tuple[object, ...], label: str = "Size"):
        self._name, self._default, self._label = name, default, label

    def clone(self):
        return copy.deepcopy(self)

    def name(self):
        return self._name

    def label(self):
        return self._label

    def setName(self, name):
        self._name = name

    def setLabel(self, label):
        self._label = label

    def setDefaultValue(self, value):
        self._default = tuple(value)

    def defaultValue(self):
        return self._default

    @staticmethod
    def type():
        return SimpleNamespace(name=lambda: "Float")


class _MenuTemplate(_Template):
    def __init__(self, name: str, default: int, items=("small", "large")):
        super().__init__(name, (default,), "Menu")
        self._default = default
        self._items = tuple(items)

    @staticmethod
    def type():
        return SimpleNamespace(name=lambda: "Menu")

    def menuItems(self):
        return self._items

    def setDefaultValue(self, value):
        assert isinstance(value, int) and not isinstance(value, bool)
        self._default = value

    def defaultValue(self):
        return self._default


class _Group:
    def __init__(self, templates=None):
        self.templates = dict(templates or {})

    def clone(self):
        return _Group({name: item.clone() for name, item in self.templates.items()})

    def find(self, name):
        return self.templates.get(name)

    @staticmethod
    def findFolder(_label):
        return None

    def append(self, template):
        self.templates[template.name()] = template


class _Parm:
    def __init__(self, name, path, node, template, value):
        self._name, self._path, self._node = name, path, node
        self._template, self._value = template, value
        self._reference = self._tuple = None

    def name(self):
        return self._name

    def path(self):
        return self._path

    def node(self):
        return self._node

    def parmTemplate(self):
        return self._template

    def tuple(self):
        return self._tuple

    def eval(self):
        return self._reference.eval() if self._reference is not None else self._value

    def set(self, value):
        if isinstance(value, _Parm):
            self._reference = value
        else:
            if self._template.type().name() == "Menu" and isinstance(value, str):
                value = self._template.menuItems().index(value)
            self._reference, self._value = None, value

    @staticmethod
    def keyframes():
        return ()

    def deleteAllKeyframes(self):
        self._reference = None

    @staticmethod
    def setKeyframes(_keyframes):
        raise AssertionError("The fixture has no keyed parameter state.")


class _ParmTuple:
    def __init__(self, parms, template):
        self.parms, self.template = list(parms), template
        for parm in self.parms:
            parm._tuple = self

    def __iter__(self):
        return iter(self.parms)

    def __len__(self):
        return len(self.parms)

    def __getitem__(self, index):
        return self.parms[index]

    def parmTemplate(self):
        return self.template

    def set(self, value):
        values = value.parms if isinstance(value, _ParmTuple) else value
        for target, source in zip(self.parms, values, strict=True):
            target.set(source)


class _Definition:
    def __init__(self, library_path="Embedded"):
        self.group, self.update_count = _Group(), 0
        self.library_path, self.version = library_path, "1.0"

    def parmTemplateGroup(self):
        return self.group.clone()

    def setParmTemplateGroup(self, group, **_kwargs):
        self.group = group.clone()

    def updateFromNode(self, _instance):
        self.update_count += 1

    def libraryFilePath(self):
        return self.library_path

    @staticmethod
    def nodeTypeName():
        return "hocus::brick::1.0"

    def setVersion(self, version):
        self.version = version


class _Instance:
    def __init__(self, registry, library_path="Embedded"):
        self.registry, self.definition = registry, _Definition(library_path)
        self.outer, self.locked, self.fail_cook = {}, True, False

    @staticmethod
    def path():
        return "/obj/brick"

    def type(self):
        return SimpleNamespace(definition=lambda: self.definition)

    def parmTemplateGroup(self):
        return self.definition.parmTemplateGroup()

    def matchCurrentDefinition(self):
        wanted = self.definition.group.templates
        for name in list(self.outer):
            if name not in wanted:
                for parm in self.outer.pop(name):
                    self.registry.pop(parm.path(), None)
        for name, template in wanted.items():
            if name not in self.outer:
                default = template.defaultValue()
                value = default[0] if isinstance(default, tuple) else default
                parm = _Parm(name, f"{self.path()}/{name}", self, template, value)
                self.outer[name] = _ParmTuple([parm], template)
                self.registry[parm.path()] = parm
        self.locked = True

    def allowEditingOfContents(self):
        self.locked = False

    def parmTuple(self, name):
        return self.outer.get(name)

    def parm(self, name):
        parm_tuple = self.outer.get(name)
        return parm_tuple.parms[0] if parm_tuple is not None else None

    def cook(self, force=False):
        assert force
        if self.fail_cook:
            raise RuntimeError("injected cook failure")

    def isLockedHDA(self):
        return self.locked

    def matchesCurrentDefinition(self):
        return self.locked

    @staticmethod
    def spareParms():
        return []


class _HdaHarness(HdaOperationsMixin):
    def __init__(self, *, template=None, source_value=4.0, library_path="Embedded"):
        self.registry, self.hou = {}, SimpleNamespace(
            undos=SimpleNamespace(group=lambda _label: nullcontext()),
        )
        self._settings = SimpleNamespace(
            allow_file_write=True, read_only=False, approved_roots=[],
        )
        self.instance = _Instance(self.registry, library_path)
        internal = SimpleNamespace(path=lambda: "/obj/brick/internal")
        template = template or _Template("size", (1.0,))
        self.source = _Parm(
            "size", "/obj/brick/internal/size", internal, template, source_value,
        )
        _ParmTuple([self.source], template)
        self.registry[self.source.path()] = self.source

    def _require_hou(self):
        return self.hou

    def _require_node_by_path(self, path, **_kwargs):
        assert path == self.instance.path()
        return self.instance

    def _require_parm_by_path(self, path):
        return self.registry[path]

    @staticmethod
    def _safe_value(callback, default):
        try:
            return callback() if callable(callback) else callback
        except Exception:
            return default

    @staticmethod
    def _hda_instance_summary(instance):
        return {"path": instance.path(), "locked": instance.isLockedHDA()}

    @staticmethod
    def _hda_definition_summary(definition, **_kwargs):
        return {
            "nodeTypeName": definition.nodeTypeName(),
            "libraryFilePath": definition.libraryFilePath(),
            "version": definition.version,
        }

    @staticmethod
    def _call_live(callback, _context):
        return callback()

    @staticmethod
    def _tool_response(_text, data):
        return {"structuredContent": data}


class _SessionHarness(SessionOperationsMixin):
    @staticmethod
    def _session_info_impl():
        return {"policy": {}}

    _call_live = staticmethod(lambda callback, _context: callback())
    _tool_response = staticmethod(lambda _text, data: {"structuredContent": data})


def _assert_menu_token_contract(test) -> None:
    menu = _HdaHarness(template=_MenuTemplate("size", 0), source_value=0)
    menu_result = menu._hda_promote_parm_impl({
        "instance_path": "/obj/brick",
        "source_parm_path": menu.source.path(),
        "promoted_name": "menu_size",
        "default_value": "large",
        "initial_value": "large",
    })
    test.assertEqual(menu_result["definitionDefaultValue"], [1])
    test.assertEqual(menu_result["instanceInitialValue"], [1])
    menu_update = menu._hda_set_instance_parms_impl({
        "instance_path": "/obj/brick",
        "assignments": [{"name": "menu_size", "value": "small"}],
    })
    test.assertEqual(menu_update["assignments"][0]["value"], [0])
    with test.assertRaises(Exception) as unknown_menu:
        menu._hda_set_instance_parms_impl({
            "instance_path": "/obj/brick",
            "assignments": [{"name": "menu_size", "value": "unknown"}],
        })
    test.assertEqual(
        unknown_menu.exception.data["diagnosticCode"],
        "hda.interface.menu_token",
    )
    test.assertEqual(menu.instance.parm("menu_size").eval(), 0)

    try:
        import hou  # type: ignore[import-not-found]
    except ImportError:
        return
    actual_menu = hou.MenuParmTemplate(
        "menu", "Menu", ("small", "large"), ("Small", "Large"),
        default_value=0,
    )
    payload, canonical = HdaOperationsMixin._hda_default_payload(
        actual_menu, "Menu", ("large",), "default_value",
    )
    test.assertIsInstance(payload, int)
    test.assertEqual((payload, canonical), (1, (1,)))
    probe = hou.node("/obj").createNode(
        "null", "hocus_menu_token_probe", run_init_scripts=False,
        force_valid_node_name=True,
    )
    try:
        probe.addSpareParmTuple(actual_menu)
        actual_parm = probe.parm("menu")
        actual_parm.set("large")
        test.assertEqual(actual_parm.eval(), 1)
        prepared = HdaOperationsMixin._hda_canonicalize_values(
            actual_menu, "Menu", ("large",), "value",
        )
        HdaOperationsMixin._hda_set_parm_values(actual_parm, None, prepared)
        test.assertEqual(actual_parm.eval(), prepared[0])
    finally:
        probe.destroy()


def assert_hda_and_capability_contract(test):
    projection = capability_projection((EDIT_SCENE,), (EDIT_SCENE, RUN_CODE))
    test.assertEqual(projection["missingCapabilities"], [RUN_CODE])
    test.assertFalse(projection["capabilityReady"])
    profiles = available_policy_profiles()
    test.assertFalse(profiles["local-dev"]["enable_exec_tools"])
    test.assertTrue(profiles["procedural-authoring"]["enable_exec_tools"])
    session = _SessionHarness().session_info(
        {}, RequestContext(permissions=(RUN_CODE, EDIT_SCENE)),
    )["structuredContent"]
    test.assertEqual(session["grantedCapabilities"], [EDIT_SCENE, RUN_CODE])

    harness = _HdaHarness()
    promoted = harness.hda_promote_parm({
        "instance_path": "/obj/brick",
        "source_parm_path": harness.source.path(),
        "promoted_name": "brick_size",
    }, RequestContext())["structuredContent"]
    test.assertEqual(promoted["capturedSourceValue"], [4.0])
    test.assertEqual(promoted["definitionDefaultValue"], [4.0])
    test.assertEqual(promoted["instanceInitialValue"], [4.0])
    test.assertTrue(promoted["verified"])
    test.assertEqual(promoted["libraryIdentity"]["kind"], "embedded")
    test.assertTrue(harness.instance.isLockedHDA())
    harness._resolve_definition = lambda **_kwargs: harness.instance.definition
    versioned = harness._hda_set_definition_version_impl({
        "node_path": "/obj/brick", "version": "2.0",
    })
    test.assertEqual(versioned["version"], "2.0")
    test.assertEqual(versioned["libraryIdentity"]["kind"], "embedded")

    updated = harness.hda_set_instance_parms({
        "instance_path": "/obj/brick",
        "assignments": [{"name": "brick_size", "value": 6.0}],
    }, RequestContext())["structuredContent"]
    test.assertTrue(updated["locked"])
    test.assertEqual(harness.source.eval(), 6.0)
    with test.assertRaises(Exception) as duplicate:
        harness._hda_set_instance_parms_impl({
            "instance_path": "/obj/brick",
            "assignments": [
                {"name": "brick_size", "value": 2.0},
                {"name": "brick_size", "value": 3.0},
            ],
        })
    test.assertEqual(duplicate.exception.data["diagnosticCode"], "hda.interface.duplicate")
    with test.assertRaises(Exception) as wrong_type:
        harness._hda_set_instance_parms_impl({
            "instance_path": "/obj/brick",
            "assignments": [{"name": "brick_size", "value": "large"}],
        })
    test.assertEqual(wrong_type.exception.data["diagnosticCode"], "hda.interface.value_type")
    public_parm = harness.instance.parm("brick_size")
    harness.instance.spareParms = lambda: [public_parm]
    with test.assertRaises(Exception) as spare:
        harness._hda_set_instance_parms_impl({
            "instance_path": "/obj/brick",
            "assignments": [{"name": "brick_size", "value": 2.0}],
        })
    test.assertEqual(spare.exception.data["diagnosticCode"], "hda.interface.spare")

    explicit = _HdaHarness()
    explicit_result = explicit._hda_promote_parm_impl({
        "instance_path": "/obj/brick",
        "source_parm_path": explicit.source.path(),
        "promoted_name": "explicit_size",
        "default_value": 2.0,
        "initial_value": 3.0,
    })
    test.assertEqual(explicit_result["definitionDefaultValue"], [2.0])
    test.assertEqual(explicit_result["instanceInitialValue"], [3.0])
    test.assertEqual(explicit.source.eval(), 3.0)

    _assert_menu_token_contract(test)

    unlocked = _HdaHarness()
    unlocked.instance.locked = False
    with test.assertRaises(Exception) as stale_instance:
        unlocked._hda_promote_parm_impl({
            "instance_path": "/obj/brick",
            "source_parm_path": unlocked.source.path(),
        })
    test.assertEqual(
        stale_instance.exception.data["diagnosticCode"],
        "hda.instance.not_current_locked",
    )
    stale = _HdaHarness()
    stale.instance.matchesCurrentDefinition = lambda: False
    with test.assertRaises(Exception) as stale_definition:
        stale._hda_promote_parm_impl({
            "instance_path": "/obj/brick",
            "source_parm_path": stale.source.path(),
        })
    test.assertEqual(
        stale_definition.exception.data["diagnosticCode"],
        "hda.instance.not_current_locked",
    )

    authored = _HdaHarness()
    authored.source.keyframes = lambda: (object(),)
    with test.assertRaises(Exception) as authored_channel:
        authored._hda_promote_parm_impl({
            "instance_path": "/obj/brick",
            "source_parm_path": authored.source.path(),
        })
    test.assertEqual(
        authored_channel.exception.data["diagnosticCode"],
        "hda.promotion.authored_channel",
    )
    expression = _HdaHarness()
    expression.source.expression = lambda: "ch('../controller')"
    with test.assertRaises(Exception) as expression_channel:
        expression._hda_promote_parm_impl({
            "instance_path": "/obj/brick",
            "source_parm_path": expression.source.path(),
        })
    test.assertEqual(
        expression_channel.exception.data["diagnosticCode"],
        "hda.promotion.authored_channel",
    )

    with tempfile.TemporaryDirectory() as temporary:
        approved = Path(temporary) / "approved"
        approved.mkdir()
        external = _HdaHarness(library_path=str(approved / "brick.hda"))
        external._settings.approved_roots = [str(approved)]
        identity = external._hda_definition_library_identity(external.instance.definition)
        test.assertEqual(identity["kind"], "external_library")
        external._settings.approved_roots = [str(Path(temporary) / "other")]
        with test.assertRaises(Exception):
            external._hda_definition_library_identity(external.instance.definition)

    failed = _HdaHarness()
    failed.instance.fail_cook = True
    with test.assertRaisesRegex(Exception, "rolled back"):
        failed._hda_promote_parm_impl({
            "instance_path": "/obj/brick",
            "source_parm_path": failed.source.path(),
            "promoted_name": "broken",
        })
    test.assertIsNone(failed.instance.parm("broken"))
    test.assertEqual(failed.source.eval(), 4.0)
