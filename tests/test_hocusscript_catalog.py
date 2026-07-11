from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.catalog import (
    CatalogProvider,
    CatalogValidationError,
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    HdaLibrary,
    MenuItem,
    OperatorDefinition,
    PackageDefinition,
    ParameterDefinition,
    ParmRange,
    SnapshotCatalogProvider,
    decode_catalog_snapshot,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _provider(*, reverse: bool = False) -> FakeCatalogProvider:
    categories = [
        CategoryDefinition("Sop", "Geometry", "sop"),
        CategoryDefinition("Driver", "Render", "rop"),
    ]
    packages = [
        PackageDefinition("sidefx-labs", "SideFX Labs", "21.0.123", "labs", _digest("a"), {"vendor": "SideFX"}),
        PackageDefinition("studio-tools", "Studio Tools", "3.2.1", "package", _digest("b"), {"channel": "release"}),
    ]
    parameters = [
        ParameterDefinition("group", "Group", "string", 1, (), "", tags={"scope": "point"}),
        ParameterDefinition("size", "Size", "tuple", 3, ("sizex", "sizey", "sizez"), (1.0, 1.0, 1.0), ParmRange(0, 10)),
        ParameterDefinition("method", "Method", "menu", 1, (), "axis", menu=(MenuItem("axis", "Axis"), MenuItem("normal", "Normal"))),
        ParameterDefinition("snippet", "VEXpression", "code", 1, (), "", code_surface="vex"),
        ParameterDefinition("execute", "Execute", "button", 1, (), None, assignable=False),
    ]
    connectors = [
        ConnectorDefinition(1, "reference", "Reference", "optional", ("geometry",), ("Sop",)),
        ConnectorDefinition(0, "geometry", "Geometry", "one", ("geometry",), ("Sop",)),
        ConnectorDefinition(None, "mask", "Mask", "many", ("geometry",), ("Sop",)),
    ]
    operators = [
        OperatorDefinition(
            "labs::sop::axis_align::2.0", "axis_align", "labs", "2.0", "Sop", ("axisalign", "labs_axis_align"),
            DefinitionSource("hda", "sidefx-labs", HdaLibrary("SideFXLabs/axis_align.hda", _digest("c"), "labs::axis_align", "2.0")),
            tuple(parameters), tuple(connectors), (ConnectorDefinition(0, "output", "Output", data_types=("geometry",), categories=("Sop",)),),
            "declared_only", True, False, ("sop",),
        ),
        OperatorDefinition(
            "sop::null", "null", None, None, "Sop", (), DefinitionSource("builtin"), (),
            (ConnectorDefinition(0, "input", "Input", categories=("Sop",)),),
            (ConnectorDefinition(0, "output", "Output", categories=("Sop",)),), network_families=("sop",),
        ),
    ]
    if reverse:
        categories.reverse()
        packages.reverse()
        operators.reverse()
    return FakeCatalogProvider.create(
        operators=operators, categories=categories, packages=packages,
        version="21.0", build="21.0.123", platform="windows-x86_64",
        feature_flags=("apex", "karma_xpu") if not reverse else ("karma_xpu", "apex"),
    )


class HocusScriptCatalogTests(unittest.TestCase):
    def test_full_snapshot_round_trip_and_schema(self) -> None:
        provider = _provider()
        snapshot = provider.get_catalog()
        decoded = SnapshotCatalogProvider.decode(snapshot.to_json()).get_catalog()
        self.assertIsInstance(provider, CatalogProvider)
        self.assertEqual(decoded, snapshot)
        self.assertEqual(decoded.fingerprint, snapshot.fingerprint)
        self.assertEqual(decoded.operators[0].source.hda_library.asset_name, "labs::axis_align")
        size = next(item for item in decoded.operators[0].parameters if item.token == "size")
        self.assertEqual(size.tuple_names, ("sizex", "sizey", "sizez"))
        self.assertEqual(decoded.operators[0].inputs[2].name, "mask")
        self.assertEqual(decoded.packages[0].kind, "labs")

        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return
        schema = json.loads((ROOT / "docs" / "schemas" / "catalog-v1.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(snapshot.to_dict())

    def test_fingerprint_is_independent_of_provider_enumeration_order(self) -> None:
        first = _provider().get_catalog()
        second = _provider(reverse=True).get_catalog()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.to_json(), second.to_json())

    def test_exact_operator_name_is_scoped_by_category_not_rewritten(self) -> None:
        categories = (
            CategoryDefinition("Sop", "Geometry", "sop"),
            CategoryDefinition("Object", "Objects", "object"),
        )
        operators = (
            OperatorDefinition("null", "null", None, None, "Sop", (), DefinitionSource("builtin"), (), (), ()),
            OperatorDefinition("null", "null", None, None, "Object", (), DefinitionSource("builtin"), (), (), ()),
        )
        snapshot = FakeCatalogProvider.create(categories=categories, operators=operators).get_catalog()
        decoded = decode_catalog_snapshot(snapshot.to_json())
        self.assertEqual([(item.category, item.qualified_name) for item in decoded.operators], [("Object", "null"), ("Sop", "null")])

    def test_snapshot_fixture_decodes_and_is_canonical(self) -> None:
        fixture = ROOT / "tests" / "fixtures" / "hocusscript" / "catalog" / "catalog-v1.json"
        raw = fixture.read_text(encoding="utf-8")
        snapshot = decode_catalog_snapshot(raw)
        self.assertEqual(snapshot.to_json(), raw.strip())
        self.assertEqual(snapshot.houdini.build, "21.0.123")

    def test_tamper_unknown_fields_and_duplicate_keys_are_rejected(self) -> None:
        payload = _provider().get_catalog().to_dict()
        payload["houdini"]["build"] = "21.0.124"
        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot(payload)
        self.assertEqual(captured.exception.code, "catalog.fingerprint_mismatch")

        payload = _provider().get_catalog().to_dict()
        payload["surprise"] = True
        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot(payload)
        self.assertEqual(captured.exception.code, "catalog.unknown_field")

        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot('{"kind":"first","kind":"second"}')
        self.assertEqual(captured.exception.code, "catalog.duplicate_key")

        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot(b"\xff")
        self.assertEqual(captured.exception.code, "catalog.encoding")

        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot("[" * 2000 + "]" * 2000)
        self.assertEqual(captured.exception.code, "catalog.limit")

        payload = _provider().get_catalog().to_dict()
        payload["catalogVersion"] = True
        with self.assertRaises(CatalogValidationError) as captured:
            decode_catalog_snapshot(payload)
        self.assertEqual(captured.exception.code, "catalog.version")

    def test_relational_and_semantic_invariants_are_strict(self) -> None:
        cases = []
        unknown_category = _provider().get_catalog().to_dict()
        unknown_category["operators"][0]["category"] = "Missing"
        cases.append((unknown_category, "catalog.reference"))
        invalid_button = _provider().get_catalog().to_dict()
        group = next(item for item in invalid_button["operators"][0]["parameters"] if item["token"] == "group")
        group["type"] = "button"
        cases.append((invalid_button, "catalog.action"))
        invalid_code = _provider().get_catalog().to_dict()
        group = next(item for item in invalid_code["operators"][0]["parameters"] if item["token"] == "group")
        group["codeSurface"] = "python"
        cases.append((invalid_code, "catalog.code_surface"))
        invalid_scalar_tuple = _provider().get_catalog().to_dict()
        group = next(item for item in invalid_scalar_tuple["operators"][0]["parameters"] if item["token"] == "group")
        group["tupleSize"] = 7
        group["default"] = "wrong"
        cases.append((invalid_scalar_tuple, "catalog.tuple_shape"))
        invalid_default = _provider().get_catalog().to_dict()
        group = next(item for item in invalid_default["operators"][0]["parameters"] if item["token"] == "group")
        group["default"] = 42
        cases.append((invalid_default, "catalog.default"))
        missing_port_identity = _provider().get_catalog().to_dict()
        missing_port_identity["operators"][0]["inputs"][0]["index"] = None
        missing_port_identity["operators"][0]["inputs"][0]["name"] = None
        cases.append((missing_port_identity, "catalog.connector_identity"))
        duplicate_port_index = _provider().get_catalog().to_dict()
        duplicate_port_index["operators"][0]["inputs"][1]["index"] = 0
        cases.append((duplicate_port_index, "catalog.duplicate"))
        invalid_menu_default = _provider().get_catalog().to_dict()
        menu = next(item for item in invalid_menu_default["operators"][0]["parameters"] if item["token"] == "method")
        menu["default"] = "localized label"
        cases.append((invalid_menu_default, "catalog.menu"))
        invalid_tuple_default = _provider().get_catalog().to_dict()
        size = next(item for item in invalid_tuple_default["operators"][0]["parameters"] if item["token"] == "size")
        size["default"] = [1, 2]
        cases.append((invalid_tuple_default, "catalog.tuple_shape"))
        unknown_connector_category = _provider().get_catalog().to_dict()
        unknown_connector_category["operators"][0]["inputs"][0]["categories"] = ["Missing"]
        cases.append((unknown_connector_category, "catalog.reference"))
        wrong_package_kind = _provider().get_catalog().to_dict()
        wrong_package_kind["operators"][0]["source"]["kind"] = "package"
        cases.append((wrong_package_kind, "catalog.reference"))
        for payload, code in cases:
            # Recompute through a temporary valid-model decode is intentionally impossible;
            # semantic validation precedes fingerprint authentication at this boundary.
            with self.subTest(code=code):
                with self.assertRaises(CatalogValidationError) as captured:
                    decode_catalog_snapshot(payload)
                self.assertEqual(captured.exception.code, code)

    def test_default_values_are_deeply_immutable(self) -> None:
        snapshot = _provider().get_catalog()
        tuple_default = next(item for item in snapshot.operators[0].parameters if item.token == "size").default
        self.assertIsInstance(tuple_default, tuple)
        with self.assertRaises(TypeError):
            snapshot.operators[0].parameters[0].tags["new"] = "value"


if __name__ == "__main__":
    unittest.main()
