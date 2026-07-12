from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import compile_source, format_syntax, parse_syntax
from hocuspocus.hocusscript.diagnostics import HocusSourceError
from hocuspocus.hocusscript.lexer import Lexer
from hocuspocus.hocusscript.parser import Parser
from hocuspocus.hocusscript.syntax import (
    ExportStmt,
    ModuleDecl,
    ParamRefExpr,
    SymbolRefExpr,
    UseDecl,
)


FIXTURES = ROOT / "tests" / "fixtures" / "hocusscript" / "v0.2"


class HocusScriptParserV02Tests(unittest.TestCase):
    def test_module_ast_has_exact_interfaces_expressions_and_spans(self) -> None:
        source = (FIXTURES / "module-input.hocus").read_text(encoding="utf-8")
        syntax = parse_syntax(source, "module-input.hocus")
        self.assertIsInstance(syntax.root, ModuleDecl)
        assert syntax.module is not None
        self.assertIsNone(syntax.graph)
        self.assertEqual(syntax.version.value, "0.2")
        self.assertEqual(
            [(item.imported_name, item.local_name, item.specifier) for item in syntax.imports],
            [("Noise", "StudioNoise", "@studio/noise.hocus")],
        )
        imported = syntax.imports[0]
        self.assertEqual(source[imported.span.start.offset:imported.span.end.offset],
                         'import{Noise as StudioNoise}from "@studio/noise.hocus";')
        self.assertEqual(source[imported.specifier_span.start.offset:imported.specifier_span.end.offset],
                         '"@studio/noise.hocus"')
        self.assertEqual(
            [(item.name, item.type_name, None if item.default is None else item.default.value)
             for item in syntax.module.parameters],
            [("source", "node_output", None), ("enabled", "bool", True),
             ("count", "int", 2), ("label", "string", "asset")],
        )
        use = next(item for item in syntax.module.statements if isinstance(item, UseDecl))
        self.assertEqual(use.explicit_id, "detail-use")
        self.assertEqual(source[use.explicit_id_span.start.offset:use.explicit_id_span.end.offset],
                         '"detail-use"')
        self.assertIsInstance(use.arguments[0].value, SymbolRefExpr)
        self.assertEqual(use.arguments[0].value.output_index, 0)
        exports = [item for item in syntax.module.statements if isinstance(item, ExportStmt)]
        self.assertIsInstance(exports[0].value, SymbolRefExpr)

    def test_graph_root_accepts_use_and_nested_instance_export(self) -> None:
        source = '''hocus 0.2;
import { Noise } from "noise.hocus";
graph asset {
  target "/obj/asset";
  node source: "box" {}
  use noise @id("asset-noise") = Noise(source = source.output[0]);
  node result: "null" { input[0] = noise.result; }
  output = result;
}
'''
        syntax = parse_syntax(source, "asset.hocus")
        self.assertIsNotNone(syntax.graph)
        use = next(item for item in syntax.graph.statements if isinstance(item, UseDecl))
        self.assertEqual(use.module_name, "Noise")
        result = next(item for item in syntax.graph.statements if getattr(item, "symbol", None) == "result")
        self.assertIsInstance(result.statements[0].source, SymbolRefExpr)
        self.assertEqual(result.statements[0].source.member, "result")

    def test_canonical_formatter_matches_golden_and_is_idempotent(self) -> None:
        source = (FIXTURES / "module-input.hocus").read_text(encoding="utf-8")
        expected = (FIXTURES / "module.golden.hocus").read_text(encoding="utf-8")
        formatted = format_syntax(parse_syntax(source, "module-input.hocus"))
        self.assertEqual(formatted, expected)
        self.assertEqual(format_syntax(parse_syntax(formatted, "module.golden.hocus")), expected)

    def test_compile_lane_remains_disabled_after_successful_v02_parse(self) -> None:
        source = (FIXTURES / "module-input.hocus").read_text(encoding="utf-8")
        result = compile_source(source, "module-input.hocus")
        self.assertFalse(result.valid)
        self.assertEqual([item.code for item in result.diagnostics], ["HOCUS102"])
        self.assertIsNone(result.graph_spec)

    def test_imports_are_literal_exact_hocus_paths_and_precede_root(self) -> None:
        invalid = (
            ('hocus 0.2; import { A } from path; module M() exports () {}', "HOCUS262"),
            ('hocus 0.2; import("a.hocus"); module M() exports () {}', "HOCUS261"),
            ('hocus 0.2; import { A } from "/abs/a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "a.txt"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "a.hocus?x"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "@Upper/a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "@bad!/a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "@alias/%2e%2e/a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "modules/a%2Ehocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "modules/a%25.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "con/a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "dir./a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; import { A } from "e\u0301/a.hocus"; module M() exports () {}', "HOCUS263"),
            ('hocus 0.2; module M() exports () {} import { A } from "a.hocus";', "HOCUS260"),
        )
        for source, code in invalid:
            with self.subTest(source=source), self.assertRaises(HocusSourceError) as rejected:
                parse_syntax(source, "invalid-import.hocus")
            self.assertEqual(rejected.exception.diagnostic.code, code)

    def test_use_id_named_arguments_types_and_literal_defaults_are_strict(self) -> None:
        invalid = (
            ('hocus 0.2; module M() exports () { use x = A(); }', "HOCUS279"),
            ('hocus 0.2; module M() exports () { use x @id("bad seed") = A(); }', "HOCUS281"),
            ('hocus 0.2; module M() exports () { use x @id("x") = A(1); }', "HOCUS285"),
            ('hocus 0.2; module M(x: number) exports () {}', "HOCUS275"),
            ('hocus 0.2; module M(x: node_output = true) exports () {}', "HOCUS276"),
            ('hocus 0.2; module M(x: int = param.y) exports () {}', "HOCUS291"),
            ('hocus 0.2; module M() exports (x: int = 1) {}', "HOCUS276"),
            ('hocus 0.2; module M(x: string = null) exports () {}', "HOCUS291"),
            ('hocus 0.2; module M(x: float = 1) exports () {}', "HOCUS276"),
            ('hocus 0.2; module M(x: int = 1.0) exports () {}', "HOCUS276"),
            ('hocus 0.2; module M(x: bool = 1) exports () {}', "HOCUS276"),
        )
        for source, code in invalid:
            with self.subTest(source=source), self.assertRaises(HocusSourceError) as rejected:
                parse_syntax(source, "invalid-types.hocus")
            self.assertEqual(rejected.exception.diagnostic.code, code)

    def test_reserved_names_and_multiple_roots_fail_deterministically(self) -> None:
        invalid = (
            'hocus 0.2; import { A as __hocus_A } from "a.hocus"; module M() exports () {}',
            'hocus 0.2; module __hocus_M() exports () {}',
            'hocus 0.2; module M(__hocus_x: int) exports () {}',
            'hocus 0.2; module M() exports (__hocus_x: int) {}',
            'hocus 0.2; graph G { node __hocus_n: "null" {} }',
            'hocus 0.2; graph A {} graph B {}',
            'hocus 0.2; module A() exports () {} module B() exports () {}',
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(HocusSourceError) as rejected:
                parse_syntax(source, "reserved.hocus")
            expected = "HOCUS260" if "} graph" in source or "} module" in source else "HOCUS300"
            self.assertEqual(rejected.exception.diagnostic.code, expected)

    def test_module_statement_recovery_preserves_later_valid_statements(self) -> None:
        source = '''hocus 0.2;
module M(source: node_output) exports (result: node_output) {
  unknown stuff;
  node n: "null" { input[0] = param.source; }
  export broken = ;
  export result = n.output[0];
}
'''
        parser = Parser(Lexer(source, "recovery.hocus").tokenize())
        syntax = parser.parse()
        self.assertEqual([item.code for item in parser.diagnostics], ["HOCUS269", "HOCUS292"])
        assert syntax.module is not None
        self.assertEqual(len(syntax.module.statements), 2)
        self.assertEqual(syntax.module.statements[-1].name, "result")
        self.assertIsInstance(syntax.module.statements[-1].value, SymbolRefExpr)

    def test_param_reference_span_is_exact(self) -> None:
        source = 'hocus 0.2; module M(x: float) exports (y: float) { export y = param.x; }'
        syntax = parse_syntax(source, "span.hocus")
        value = syntax.module.statements[0].value
        self.assertIsInstance(value, ParamRefExpr)
        self.assertEqual(source[value.span.start.offset:value.span.end.offset], "param.x")
        self.assertEqual(source[value.name_span.start.offset:value.name_span.end.offset], "x")

    def test_explicit_syntax_formatter_preserves_v01_canonical_output_exactly(self) -> None:
        source = 'hocus 0.1; graph demo { target "/obj/geo1"; node n: "null" {} output = n; }'
        compiled = compile_source(source, "legacy.hocus")
        self.assertTrue(compiled.valid)
        syntax = Parser(Lexer(source, "legacy.hocus").tokenize()).parse()
        self.assertEqual(format_syntax(syntax), compiled.formatted_source)


if __name__ == "__main__":
    unittest.main()
