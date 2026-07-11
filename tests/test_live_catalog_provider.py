from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.catalog import CatalogProvider
from hocuspocus.live.catalog_provider import (
    LiveCatalogExtractionError,
    LiveHoudiniCatalogProvider,
    _parameter,
)


class _Enum:
    def __init__(self, name: str):
        self._name = name

    def name(self) -> str:
        return self._name


class _ParmTemplate:
    def __init__(
        self,
        name: str,
        label: str,
        kind: str,
        *,
        size: int = 1,
        default=None,
        naming: str = "Base1",
        minimum=None,
        maximum=None,
        menu: tuple[tuple[str, str], ...] = (),
        tags: dict[str, str] | None = None,
    ):
        self._name = name
        self._label = label
        self._kind = kind
        self._size = size
        self._default = default
        self._naming = naming
        self._minimum = minimum
        self._maximum = maximum
        self._menu = menu
        self._tags = tags or {}

    def name(self):
        return self._name

    def label(self):
        return self._label

    def type(self):
        return _Enum(self._kind)

    def numComponents(self):
        return self._size

    def defaultValue(self):
        return self._default

    def namingScheme(self):
        return _Enum(self._naming)

    def minValue(self):
        return self._minimum

    def maxValue(self):
        return self._maximum

    def minIsStrict(self):
        return self._minimum is not None

    def maxIsStrict(self):
        return self._maximum is not None

    def menuItems(self):
        return tuple(item[0] for item in self._menu)

    def menuLabels(self):
        return tuple(item[1] for item in self._menu)

    def tags(self):
        return self._tags


class _Folder:
    def __init__(self, children):
        self._children = tuple(children)

    def parmTemplates(self):
        return self._children


class _Multiparm(_Folder):
    def name(self):
        return "layers"

    def label(self):
        return "Layers"

    def type(self):
        return _Enum("Folder")

    def folderType(self):
        return _Enum("MultiparmBlock")

    def numComponents(self):
        return 1

    def defaultValue(self):
        return (0,)

    def tags(self):
        return {}


class _ParmGroup:
    def __init__(self, entries):
        self._entries = tuple(entries)

    def entries(self):
        return self._entries


class _Definition:
    def __init__(self, path: Path):
        self._path = path

    def libraryFilePath(self):
        return str(self._path)

    def version(self):
        return "2.0"


class _NodeType:
    def __init__(self, raw_name: str, *, definition=None, parameters=()):
        self._raw_name = raw_name
        self._definition = definition
        self._parameters = tuple(parameters)

    def name(self):
        return self._raw_name

    def nameComponents(self):
        if self._raw_name == "labs::axis_align::2.0":
            return ("Sop", "labs", "axis_align", "2.0")
        return ("Sop", "", self._raw_name, "")

    def aliases(self):
        return ("labs_axis_align",) if self._raw_name.startswith("labs::") else ()

    def definition(self):
        return self._definition

    def parmTemplateGroup(self):
        return _ParmGroup(self._parameters)

    def minNumInputs(self):
        return 1

    def maxNumInputs(self):
        return 2

    def inputNames(self):
        return ("geometry", "reference")

    def inputLabels(self):
        return ("Geometry", "Reference")

    def inputDataTypes(self):
        return (("geometry",), ("geometry",))

    def minNumOutputs(self):
        return 1

    def maxNumOutputs(self):
        return 1

    def outputNames(self):
        return ("result",)

    def outputLabels(self):
        return ("Result",)


class _Category:
    def __init__(self, name: str, node_types: list[_NodeType], *, reverse: bool = False):
        self._name = name
        values = list(reversed(node_types)) if reverse else node_types
        self._node_types = {node_type.name(): node_type for node_type in values}

    def name(self):
        return self._name

    def label(self):
        return "Geometry" if self._name == "Sop" else self._name

    def nodeTypes(self):
        return self._node_types


class _Hou:
    def __init__(self, categories: list[_Category], *, reverse: bool = False):
        values = list(reversed(categories)) if reverse else categories
        self._categories = {category.name(): category for category in values}

    def nodeTypeCategories(self):
        return self._categories

    def applicationName(self):
        return "Houdini FX"

    def applicationVersion(self):
        return (21, 0, 321)

    def applicationPlatformInfo(self):
        return "windows-x86_64"

    def licenseCategory(self):
        return _Enum("Commercial")


def _fake_hou(hda_path: Path, *, reverse: bool = False) -> _Hou:
    parameters = (
        _Folder(
            (
                _ParmTemplate(
                    "size",
                    "Size",
                    "Float",
                    size=3,
                    default=(1.0, 1.0, 1.0),
                    naming="XYZW",
                    minimum=0.0,
                    maximum=10.0,
                ),
                _ParmTemplate(
                    "method",
                    "Method",
                    "String",
                    default=("axis",),
                    menu=(("axis", "Axis"), ("normal", "Normal")),
                ),
                _ParmTemplate(
                    "snippet",
                    "VEXpression",
                    "String",
                    default=("",),
                    tags={"editorlang": "vex", "script_callback": "python should not classify this"},
                ),
                _ParmTemplate("execute", "Execute", "Button"),
                _ParmTemplate(
                    "bounds",
                    "Bounds",
                    "Float",
                    size=2,
                    default=(0.0, 1.0),
                    naming="MinMax",
                ),
                _ParmTemplate("heading", "Heading", "Label"),
                _Multiparm((_ParmTemplate("layer#", "Layer", "Float", default=(1.0,)),)),
            )
        ),
    )
    node_types = [
        _NodeType("labs::axis_align::2.0", definition=_Definition(hda_path), parameters=parameters),
        _NodeType("null"),
    ]
    return _Hou([_Category("Sop", node_types, reverse=reverse)], reverse=reverse)


class LiveCatalogProviderTests(unittest.TestCase):
    def _package_fixture(self, directory: Path) -> None:
        (directory / "SideFX Labs.json").write_text(
            json.dumps({"name": "SideFX Labs", "version": "21.0.321"}, separators=(",", ":")),
            encoding="utf-8",
        )

    def test_extracts_portable_full_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hda = root / "otls" / "labs.hda"
            hda.parent.mkdir()
            hda.write_bytes(b"stable hda content")
            packages = root / "packages"
            packages.mkdir()
            self._package_fixture(packages)

            provider = LiveHoudiniCatalogProvider(
                _fake_hou(hda), package_directories=(packages,)
            )
            snapshot = provider.get_catalog()
            self.assertIsInstance(provider, CatalogProvider)

            operator = next(
                item
                for item in snapshot.operators
                if item.category == "Sop" and item.qualified_name == "labs::axis_align::2.0"
            )
            self.assertEqual(operator.source.package_id, "sidefx-labs")
            self.assertTrue(operator.source.hda_library.content_digest.startswith("sha256:"))
            self.assertEqual(operator.inputs[1].name, "reference")
            self.assertEqual(operator.outputs[0].name, "result")
            size = next(item for item in operator.parameters if item.token == "size")
            self.assertEqual(size.tuple_names, ("sizex", "sizey", "sizez"))
            self.assertEqual((size.range.minimum, size.range.maximum), (0.0, 10.0))
            method = next(item for item in operator.parameters if item.token == "method")
            self.assertEqual([item.token for item in method.menu], ["axis", "normal"])
            snippet = next(item for item in operator.parameters if item.token == "snippet")
            self.assertEqual((snippet.value_type, snippet.code_surface), ("code", "vex"))
            bounds = next(item for item in operator.parameters if item.token == "bounds")
            self.assertEqual(bounds.tuple_names, ("boundsmin", "boundsmax"))
            self.assertNotIn("heading", {item.token for item in operator.parameters})
            layers = next(item for item in operator.parameters if item.token == "layers")
            self.assertEqual(layers.value_type, "multiparm")
            self.assertNotIn("layer#", {item.token for item in operator.parameters})
            execute = next(item for item in operator.parameters if item.token == "execute")
            self.assertFalse(execute.assignable)
            self.assertEqual(snapshot.packages[0].kind, "labs")
            self.assertNotIn(str(root), snapshot.to_json())

    def test_order_and_physical_location_do_not_change_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            roots = (Path(first_dir), Path(second_dir))
            snapshots = []
            for index, root in enumerate(roots):
                hda = root / "different" / "labs.hda"
                hda.parent.mkdir()
                hda.write_bytes(b"stable hda content")
                packages = root / "packages"
                packages.mkdir()
                self._package_fixture(packages)
                snapshots.append(
                    LiveHoudiniCatalogProvider(
                        _fake_hou(hda, reverse=bool(index)),
                        package_directories=(packages,),
                    ).get_catalog()
                )
            self.assertEqual(snapshots[0].fingerprint, snapshots[1].fingerprint)
            self.assertEqual(snapshots[0].to_json(), snapshots[1].to_json())

    def test_meaningful_hda_change_changes_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hda = root / "labs.hda"
            hda.write_bytes(b"first definition")
            first = LiveHoudiniCatalogProvider(_fake_hou(hda), package_directories=()).get_catalog()
            hda.write_bytes(b"second definition")
            second = LiveHoudiniCatalogProvider(_fake_hou(hda), package_directories=()).get_catalog()
            self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_callback_tags_do_not_create_code_capabilities(self) -> None:
        parameter = _parameter(
            _ParmTemplate(
                "callback_mode",
                "Callback Mode",
                "String",
                default=("deferred",),
                tags={"script_callback": "python -c unsafe"},
            ),
            "test_operator",
        )
        self.assertEqual((parameter.value_type, parameter.code_surface), ("string", "none"))

    def test_unknown_code_surface_is_not_silently_downgraded(self) -> None:
        parameter = _parameter(
            _ParmTemplate(
                "snippet",
                "Code Snippet",
                "String",
                default=("",),
                tags={"editorlang": "javascript"},
            ),
            "test_operator",
        )
        self.assertEqual((parameter.value_type, parameter.code_surface), ("code", "unsupported"))
        self.assertEqual(parameter.assignable, True)
        self.assertEqual(parameter.tags["hocus.codeSurfaceStatus"], "unsupported-or-unknown-language")

    def test_conflicting_normalized_package_ids_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hda = root / "labs.hda"
            hda.write_bytes(b"definition")
            packages = root / "packages"
            packages.mkdir()
            (packages / "first.json").write_text(
                json.dumps({"name": "Studio Tools", "version": "1.0"}), encoding="utf-8"
            )
            (packages / "second.json").write_text(
                json.dumps({"name": "Studio-Tools", "version": "2.0"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(LiveCatalogExtractionError, "conflicting ID"):
                LiveHoudiniCatalogProvider(
                    _fake_hou(hda), package_directories=(packages,)
                ).get_catalog()


if __name__ == "__main__":
    unittest.main()
