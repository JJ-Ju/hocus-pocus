from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import check_source, complete_source, format_source
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    MenuItem,
    OperatorDefinition,
    ParameterDefinition,
)


def _provider():
    parameters = (
        ParameterDefinition("size", "Size", "float", 1, (), 1.0),
        ParameterDefinition(
            "operation",
            "Operation",
            "menu",
            1,
            (),
            "union",
            menu=(MenuItem("union", "Union"), MenuItem("subtract", "Subtract")),
        ),
        ParameterDefinition("execute", "Execute", "button", 1, (), None, assignable=False),
    )
    return FakeCatalogProvider.create(
        categories=(
            CategoryDefinition("Sop", "SOP", "sop"),
            CategoryDefinition("Object", "OBJ", "obj"),
        ),
        operators=(
            OperatorDefinition(
                "acme::box::1.0",
                "box",
                "acme",
                "1.0",
                "Sop",
                ("studio_box",),
                DefinitionSource("builtin"),
                parameters,
                (),
                (),
            ),
            OperatorDefinition(
                "geo",
                "geo",
                None,
                None,
                "Object",
                (),
                DefinitionSource("builtin"),
                (),
                (),
                (),
            ),
        ),
    )


VALID = '''hocus 0.1;
graph demo {
  target "/obj/geo1";
  category Sop;
  mode merge;
  node box1: "acme::box::1.0" {
    size = 2;
    operation = "union";
  }
  display = box1;
  output = box1;
  layout = auto;
}
'''


class HocusScriptEditorTests(unittest.TestCase):
    def test_format_source_is_canonical_and_idempotent(self) -> None:
        compact = VALID.replace("\n", " ")
        first = format_source(compact, "asset file.hocus")
        self.assertTrue(first.valid)
        self.assertTrue(first.changed)
        self.assertEqual(first.source_uri, "hocus-memory:///asset%20file.hocus")
        self.assertIsNotNone(first.formatted_source)

        second = format_source(first.formatted_source, "asset file.hocus")
        self.assertTrue(second.valid)
        self.assertFalse(second.changed)
        self.assertEqual(second.formatted_source, first.formatted_source)

    def test_invalid_format_does_not_rewrite_and_preserves_diagnostic_span(self) -> None:
        source = 'hocus 0.1; graph demo { target "/obj/geo1"; node broken: }'
        result = format_source(source, source_uri="hocus-project://demo/broken.hocus")
        self.assertFalse(result.valid)
        self.assertIsNone(result.formatted_source)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.span.source_name, "hocus-project://demo/broken.hocus")
        self.assertEqual(
            source[diagnostic.span.start.offset : diagnostic.span.end.offset],
            "}",
        )

    def test_check_combines_structural_and_catalog_diagnostics_at_exact_spans(self) -> None:
        source = VALID.replace('"acme::box::1.0"', '"missing::box"')
        result = check_source(
            source,
            "missing.hocus",
            source_uri="hocus-project://demo/missing.hocus",
            catalog=_provider(),
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.catalog_fingerprint, _provider().get_catalog().fingerprint)
        unknown = next(item for item in result.diagnostics if item.code == "HOCUS624")
        self.assertEqual(unknown.span.source_name, "hocus-project://demo/missing.hocus")
        self.assertEqual(
            source[unknown.span.start.offset : unknown.span.end.offset],
            '"missing::box"',
        )
        self.assertEqual(result.to_dict()["diagnostics"][0]["span"]["start"]["offset"], unknown.span.start.offset)

        many = check_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; category Sop; '
            + " ".join(f'node n{index}: "missing{index}" {{}}' for index in range(6))
            + " }",
            catalog=_provider(),
            max_diagnostics=3,
        )
        self.assertEqual(len(many.diagnostics), 3)
        self.assertEqual(many.diagnostics[-1].code, "HOCUS019")
        self.assertEqual(many.diagnostics[-1].details["omittedCount"], 4)

    def test_catalog_completion_covers_category_operator_parameter_and_menu(self) -> None:
        provider = _provider()
        category_source = "hocus 0.1; graph demo { category S"
        category = complete_source(category_source, len(category_source), provider)
        self.assertEqual(category.context, "category")
        self.assertEqual([item.label for item in category.items], ["Sop"])
        self.assertEqual(category.items[0].replacement_span.start.offset, len(category_source) - 1)

        type_source = 'hocus 0.1; graph demo { category Sop; node box1: "ac'
        node_type = complete_source(type_source, len(type_source), provider)
        self.assertEqual(node_type.context, "node_type")
        self.assertEqual([item.label for item in node_type.items], ["acme::box::1.0"])
        self.assertEqual(node_type.items[0].insert_text, 'acme::box::1.0"')

        identified_type_source = (
            'hocus 0.1; graph demo { category Sop; node box1 '
            '@id("asset.box-01"): "ac'
        )
        identified_type = complete_source(
            identified_type_source, len(identified_type_source), provider
        )
        self.assertEqual(identified_type.context, "node_type")
        self.assertEqual([item.label for item in identified_type.items], ["acme::box::1.0"])

        parm_source = 'hocus 0.1; graph demo { category Sop; node box1: "acme::box::1.0" { si'
        parameter = complete_source(parm_source, len(parm_source), provider)
        self.assertEqual(parameter.context, "parameter")
        self.assertEqual([item.label for item in parameter.items], ["size"])
        self.assertEqual(parameter.items[0].insert_text, "size = ")

        identified_parm_source = (
            'hocus 0.1; graph demo { category Sop; node box1 '
            '@id("asset.box-01"): "acme::box::1.0" { si'
        )
        identified_parameter = complete_source(
            identified_parm_source, len(identified_parm_source), provider
        )
        self.assertEqual(identified_parameter.context, "parameter")
        self.assertEqual([item.label for item in identified_parameter.items], ["size"])

        menu_source = (
            'hocus 0.1; graph demo { category Sop; node box1: "acme::box::1.0" '
            '{ operation = "sub'
        )
        menu = complete_source(menu_source, len(menu_source), provider)
        self.assertEqual(menu.context, "menu_value")
        self.assertEqual([item.label for item in menu.items], ["subtract"])
        self.assertEqual(menu.items[0].insert_text, 'subtract"')

        reference_source = (
            'hocus 0.1; graph demo { category Sop; node source1: "acme::box::1.0" {} '
            'node output1: "acme::box::1.0" { input[0] = sou'
        )
        reference = complete_source(reference_source, len(reference_source), provider)
        self.assertEqual(reference.context, "node_reference")
        self.assertEqual([item.label for item in reference.items], ["source1"])

    def test_completion_is_deterministic_bounded_and_serializable(self) -> None:
        source = "hocus 0.1; graph demo { "
        first = complete_source(source, len(source), _provider(), limit=3)
        second = complete_source(source, len(source), _provider(), limit=3)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(len(first.items), 3)
        self.assertTrue(first.is_incomplete)
        json.dumps(first.to_dict(), allow_nan=False)
        with self.assertRaises(ValueError):
            complete_source(source, len(source) + 1, _provider())

    def test_textmate_grammar_is_valid_and_registers_hocus_files(self) -> None:
        grammar = json.loads(
            (ROOT / "editors" / "hocusscript.tmLanguage.json").read_text(encoding="utf-8")
        )
        self.assertEqual(grammar["scopeName"], "source.hocusscript")
        self.assertIn("hocus", grammar["fileTypes"])
        self.assertIn("comments", grammar["repository"])
        self.assertTrue(any("python" in item.get("name", "") for item in grammar["patterns"]))
        fixture_root = ROOT / "tests" / "fixtures" / "hocusscript" / "editor"
        source = (fixture_root / "highlighting.hocus").read_text(encoding="utf-8")
        expectations = json.loads(
            (fixture_root / "highlighting.expectations.json").read_text(encoding="utf-8")
        )
        scopes = {
            item.get("name")
            for item in [*grammar["patterns"], *grammar["repository"]["comments"]["patterns"]]
        }
        for pattern in grammar["patterns"]:
            scopes.update(item.get("name") for item in pattern.get("patterns", []))
            scopes.update(capture.get("name") for capture in pattern.get("captures", {}).values())
        for expectation in expectations["snippets"]:
            self.assertIn(expectation["text"], source)
            self.assertIn(expectation["scope"], scopes)

        vex = next(item for item in grammar["patterns"] if item.get("name") == "meta.embedded.block.vex.hocusscript")
        import re
        self.assertIsNone(re.search(vex["end"], r"\`"))
        self.assertIsNotNone(re.search(vex["end"], "`"))


if __name__ == "__main__":
    unittest.main()
