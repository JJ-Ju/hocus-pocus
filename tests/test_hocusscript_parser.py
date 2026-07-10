from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import compile_source
from hocuspocus.hocusscript.diagnostics import HocusSourceError
from hocuspocus.hocusscript.lexer import Lexer
from hocuspocus.hocusscript.parser import Parser


VALID_SOURCE = '''hocus 0.1;

graph rocks {
  target "/obj/geo1";
  category Sop;
  mode merge;
  expect revision 42;
  ownership "studio.environment.rocks";
  existing ground = "/obj/geo1/OUT_GROUND";
  node scatter: "scatter" {
    input[0] = ground.output[0];
    npts = 2500;
    values = [1, 2.5, true, null, "x"];
  }
  node tint: "attribwrangle" {
    input[0] = scatter.output[1];
    snippet = vex`@Cd = rand(@ptnum);`;
  }
  display = tint;
  render = tint;
  output = tint;
  layout = auto;
}
'''


class HocusScriptParserTests(unittest.TestCase):
    def test_complete_preview_grammar(self) -> None:
        result = compile_source(VALID_SOURCE, "rocks.hocus")
        self.assertTrue(result.valid, [item.to_dict() for item in result.diagnostics])
        graph = result.graph_spec
        assert graph is not None
        self.assertEqual(graph.target, "/obj/geo1")
        self.assertEqual(graph.expected_revision, 42)
        self.assertEqual(graph.external_nodes[0].symbol, "ground")
        self.assertEqual(graph.nodes[1].inputs[0].source.output_index, 1)
        values = graph.nodes[0].parms[1].value
        self.assertEqual([item.value for item in values.items], [1, 2.5, True, None, "x"])
        self.assertEqual(values.span.start.line, 13)
        self.assertEqual(graph.span.start.line, 3)

    def test_missing_semicolon_is_parse_error(self) -> None:
        source = 'hocus 0.1; graph demo { target "/obj/geo1" }'
        result = compile_source(source, "bad.hocus")
        self.assertFalse(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS245")

    def test_typescript_call_syntax_is_rejected(self) -> None:
        source = 'hocus 0.1; graph demo { target "/obj/geo1"; node box: sop.box({}); }'
        result = compile_source(source, "unsafe.hocus")
        self.assertFalse(result.valid)
        self.assertIn(result.diagnostics[0].code, {"HOCUS004", "HOCUS225"})

    def test_missing_header_is_warning_but_valid(self) -> None:
        source = 'graph demo { target "/obj/geo1"; }'
        result = compile_source(source, "preview.hocus", strict=False)
        self.assertTrue(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS101")
        self.assertEqual(result.diagnostics[0].severity, "warning")

    def test_missing_header_is_an_error_in_strict_mode(self) -> None:
        result = compile_source('graph demo { target "/obj/geo1"; }', "strict.hocus")
        self.assertFalse(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS101")
        self.assertEqual(result.diagnostics[0].severity, "error")

    def test_quoted_category_is_rejected(self) -> None:
        result = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; category "Sop Network"; }',
            "category.hocus",
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS208")

    def test_node_limit_stops_parsing_before_graph_serialization(self) -> None:
        source = 'hocus 0.1; graph demo { target "/obj/geo1"; node a: "null" {} node b: "null" {} }'
        tokens = Lexer(source, "nodes.hocus").tokenize()
        with self.assertRaises(HocusSourceError) as captured:
            Parser(tokens, max_nodes=1).parse()
        self.assertEqual(captured.exception.diagnostic.code, "HOCUS314")

    def test_nested_values_hit_a_structured_depth_limit(self) -> None:
        nested = "[" * 130 + "1" + "]" * 130
        source = f'hocus 0.1; graph demo {{ target "/obj/geo1"; node box: "box" {{ value = {nested}; }} }}'
        result = compile_source(source, "deep.hocus")
        self.assertFalse(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS246")


if __name__ == "__main__":
    unittest.main()
