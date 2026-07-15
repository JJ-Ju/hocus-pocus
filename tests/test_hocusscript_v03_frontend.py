from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import compile_source, format_syntax, parse_syntax
from hocuspocus.hocusscript.diagnostics import HocusSourceError
from hocuspocus.hocusscript.lexer import Lexer
from hocuspocus.hocusscript.parser import Parser
from hocuspocus.hocusscript.syntax import ForDecl, IfDecl, ParamRefExpr, SymbolRefExpr, YieldStmt


IF_SOURCE = '''hocus 0.3;
module Pick(enabled: bool = true) exports (out: node_output) {
  if choice @id("choice") (param.enabled) outputs (out: node_output) {
    node yes @id("yes"): "null" {}
    yield out = yes.output[0];
  } else {
    node no @id("no"): "null" {}
    yield out = no.output[0];
  }
  export out = choice.out;
}
'''


FOR_SOURCE = '''hocus 0.3;
module Repeat(count: int = 2, source: node_output) exports (out: node_output) {
  for series @id("series") (i in range(param.count)) carry (out: node_output = param.source) {
    use copy @id("copy") = Copy(source = carry.out, index = iter.i);
    yield out = copy.out;
  }
  export out = series.out;
}
'''


class HocusScriptV03FrontendTests(unittest.TestCase):
    def test_if_control_has_recursive_frozen_ast_and_exact_spans(self) -> None:
        syntax = parse_syntax(IF_SOURCE, "if.hocus")
        assert syntax.module is not None
        control = syntax.module.statements[0]
        self.assertIsInstance(control, IfDecl)
        assert isinstance(control, IfDecl)
        self.assertEqual(control.explicit_id, "choice")
        self.assertEqual(IF_SOURCE[control.span.start.offset:control.span.end.offset].split()[0], "if")
        self.assertEqual(
            IF_SOURCE[control.explicit_id_span.start.offset:control.explicit_id_span.end.offset],
            '"choice"',
        )
        self.assertEqual(
            IF_SOURCE[control.condition_span.start.offset:control.condition_span.end.offset],
            "param.enabled",
        )
        self.assertIsInstance(control.then_body[-1], YieldStmt)
        with self.assertRaises(Exception):
            control.symbol = "changed"  # type: ignore[misc]

    def test_for_control_parses_iterator_carry_and_control_references(self) -> None:
        syntax = parse_syntax(FOR_SOURCE, "for.hocus")
        assert syntax.module is not None
        control = syntax.module.statements[0]
        self.assertIsInstance(control, ForDecl)
        assert isinstance(control, ForDecl)
        self.assertEqual(control.iterator, "i")
        self.assertIsInstance(control.count, ParamRefExpr)
        self.assertEqual(control.carries[0].name, "out")
        use = control.body[0]
        self.assertIsInstance(use.arguments[0].value, SymbolRefExpr)  # type: ignore[union-attr]
        self.assertEqual(use.arguments[0].value.symbol, "carry")  # type: ignore[union-attr]
        self.assertEqual(use.arguments[0].value.member, "out")  # type: ignore[union-attr]
        self.assertEqual(use.arguments[1].value.symbol, "iter")  # type: ignore[union-attr]
        self.assertEqual(use.arguments[1].value.member, "i")  # type: ignore[union-attr]

    def test_nested_controls_parse_to_the_configured_depth(self) -> None:
        source = '''hocus 0.3;
module Nested(flag: bool = true, count: int = 1, seed: node_output) exports (out: node_output) {
  for outer @id("outer") (i in range(param.count)) carry (out: node_output = param.seed) {
    if inner @id("inner") (param.flag) outputs (out: node_output) {
      yield out = carry.out;
    } else {
      yield out = carry.out;
    }
    yield out = inner.out;
  }
  export out = outer.out;
}
'''
        syntax = parse_syntax(source, "nested.hocus")
        assert syntax.module is not None
        outer = syntax.module.statements[0]
        self.assertIsInstance(outer, ForDecl)
        self.assertIsInstance(outer.body[0], IfDecl)  # type: ignore[union-attr]

        with self.assertRaises(HocusSourceError) as rejected:
            Parser(Lexer(source, "nested.hocus").tokenize(), max_control_depth=1).parse()
        self.assertEqual(rejected.exception.diagnostic.code, "HOCUS323")

    def test_v03_formatter_is_two_space_canonical_and_idempotent(self) -> None:
        formatted = format_syntax(parse_syntax(IF_SOURCE, "if.hocus"))
        self.assertIn('  if choice @id("choice")', formatted)
        self.assertIn("    yield out = yes.output[0];", formatted)
        self.assertEqual(format_syntax(parse_syntax(formatted, "formatted.hocus")), formatted)

        formatted_for = format_syntax(parse_syntax(FOR_SOURCE, "for.hocus"))
        self.assertEqual(
            format_syntax(parse_syntax(formatted_for, "formatted-for.hocus")),
            formatted_for,
        )

    def test_control_identity_and_range_diagnostics_are_typed(self) -> None:
        invalid = (
            (
                "hocus 0.3; module M(x: bool = true) exports (y: bool) "
                "{ if c (param.x) outputs (y: bool) { yield y = true; } "
                "else { yield y = false; } export y = c.y; }",
                "HOCUS316",
            ),
            (
                "hocus 0.3; module M(n: int = 1, x: int = 0) exports (y: int) "
                "{ for f @id(\"f\") (i in repeat(param.n)) carry (y: int = param.x) "
                "{ yield y = y.value; } export y = f.y; }",
                "HOCUS321",
            ),
        )
        for source, code in invalid:
            with self.subTest(code=code), self.assertRaises(HocusSourceError) as rejected:
                parse_syntax(source, "invalid.hocus")
            self.assertEqual(rejected.exception.diagnostic.code, code)

    def test_outputs_and_carry_interfaces_must_not_be_empty(self) -> None:
        invalid = (
            (
                "hocus 0.3; module M(x: bool = true) exports () "
                "{ if c @id(\"c\") (param.x) outputs () {} else {} }",
                "HOCUS318",
            ),
            (
                "hocus 0.3; module M(n: int = 1) exports () "
                "{ for f @id(\"f\") (i in range(param.n)) carry () {} }",
                "HOCUS322",
            ),
        )
        for source, code in invalid:
            with self.subTest(code=code), self.assertRaises(HocusSourceError) as rejected:
                parse_syntax(source, "empty-interface.hocus")
            self.assertEqual(rejected.exception.diagnostic.code, code)

    def test_v02_rejects_controls_without_changing_legacy_diagnostics(self) -> None:
        sources = (
            (
                "hocus 0.2; module M() exports () "
                "{ if c @id(\"c\") (true) outputs (x: bool) "
                "{ yield x = true; } else { yield x = false; } }",
                "HOCUS269",
                "Modules support only node, use, and export statements.",
            ),
            (
                "hocus 0.2; graph G { for f @id(\"f\") (i in range(1)) "
                "carry (x: int = 0) { yield x = 1; } }",
                "HOCUS217",
                "Unknown graph statement. HocusScript 0.2 does not execute host-language constructs.",
            ),
        )
        for source, code, message in sources:
            with self.subTest(code=code), self.assertRaises(HocusSourceError) as rejected:
                parse_syntax(source, "v02.hocus")
            self.assertEqual(rejected.exception.diagnostic.code, code)
            self.assertEqual(rejected.exception.diagnostic.message, message)

    def test_v02_formatter_output_is_byte_for_byte_unchanged(self) -> None:
        source = '''hocus 0.2;

module M(
  x: bool = true,
) exports (
  y: bool,
) {
  export y = param.x;
}
'''
        self.assertEqual(format_syntax(parse_syntax(source, "v02.hocus")), source)

    def test_v03_node_limit_is_aggregate_across_nested_control_branches(self) -> None:
        source = '''hocus 0.3;
module M(flag: bool = true) exports (out: bool) {
  node top @id("top"): "null" {}
  if branch @id("branch") (param.flag) outputs (out: bool) {
    node yes @id("yes"): "null" {}
    yield out = true;
  } else {
    node no @id("no"): "null" {}
    yield out = false;
  }
  export out = branch.out;
}
'''
        Parser(Lexer(source, "node-limit.hocus").tokenize(), max_nodes=3).parse()
        with self.assertRaises(HocusSourceError) as rejected:
            Parser(Lexer(source, "node-limit.hocus").tokenize(), max_nodes=2).parse()
        self.assertEqual(rejected.exception.diagnostic.code, "HOCUS314")

    def test_v03_instance_limit_is_aggregate_across_nested_control_branches(self) -> None:
        source = '''hocus 0.3;
module M(flag: bool = true) exports (out: bool) {
  use top @id("top") = Unit();
  if branch @id("branch") (param.flag) outputs (out: bool) {
    use yes @id("yes") = Unit();
    yield out = true;
  } else {
    use no @id("no") = Unit();
    yield out = false;
  }
  export out = branch.out;
}
'''
        Parser(Lexer(source, "use-limit.hocus").tokenize(), max_instances=3).parse()
        with self.assertRaises(HocusSourceError) as rejected:
            Parser(Lexer(source, "use-limit.hocus").tokenize(), max_instances=2).parse()
        self.assertEqual(rejected.exception.diagnostic.code, "HOCUS271")

    def test_formatter_rejects_v03_controls_forged_under_v02_version(self) -> None:
        syntax = parse_syntax(IF_SOURCE, "if.hocus")
        assert syntax.version is not None
        forged = replace(syntax, version=replace(syntax.version, value="0.2"))
        with self.assertRaisesRegex(ValueError, "language 0.2 syntax"):
            format_syntax(forged)

    def test_malformed_control_header_recovers_to_later_root_statements(self) -> None:
        source = '''hocus 0.3;
module Recover(flag: bool = true) exports (out: bool) {
  if broken (param.flag) outputs (out: bool) {
    yield out = true;
  } else {
    yield out = false;
  }
  if valid @id("valid") (param.flag) outputs (out: bool) {
    yield out = true;
  } else {
    yield out = false;
  }
  export out = valid.out;
}
'''
        parser = Parser(Lexer(source, "recover-header.hocus").tokenize())
        syntax = parser.parse()
        self.assertEqual([item.code for item in parser.diagnostics], ["HOCUS316"])
        assert syntax.module is not None
        self.assertTrue(any(isinstance(item, IfDecl) and item.symbol == "valid" for item in syntax.module.statements))
        self.assertEqual(syntax.module.statements[-1].name, "out")  # type: ignore[union-attr]

    def test_malformed_branch_statement_recovers_without_swallowing_else(self) -> None:
        source = '''hocus 0.3;
module Recover(flag: bool = true) exports (out: bool) {
  if choice @id("choice") (param.flag) outputs (out: bool) {
    yield = true;
    yield out = true;
  } else {
    yield out = false;
  }
  export out = choice.out;
}
'''
        parser = Parser(Lexer(source, "recover-body.hocus").tokenize())
        syntax = parser.parse()
        self.assertEqual([item.code for item in parser.diagnostics], ["HOCUS323"])
        assert syntax.module is not None
        control = syntax.module.statements[0]
        self.assertIsInstance(control, IfDecl)
        assert isinstance(control, IfDecl)
        self.assertEqual(len(control.then_body), 1)
        self.assertEqual(len(control.else_body), 1)
        self.assertEqual(syntax.module.statements[-1].name, "out")  # type: ignore[union-attr]

    def test_graph_controls_parse_and_format_but_compilation_stays_closed(self) -> None:
        source = '''hocus 0.3;
graph G {
  if choice @id("choice") (true) outputs (out: node_output) {
    node yes @id("yes"): "null" {}
    yield out = yes.output[0];
  } else {
    node no @id("no"): "null" {}
    yield out = no.output[0];
  }
  node result @id("result"): "null" { input[0] = choice.out; }
}
'''
        syntax = parse_syntax(source, "graph-control.hocus")
        assert syntax.graph is not None
        self.assertIsInstance(syntax.graph.statements[0], IfDecl)
        formatted = format_syntax(syntax)
        self.assertEqual(format_syntax(parse_syntax(formatted, "formatted-graph.hocus")), formatted)
        result = compile_source(source, "graph-control.hocus")
        self.assertFalse(result.valid)
        self.assertEqual([item.code for item in result.diagnostics], ["HOCUS102"])

    def test_control_item_limit_counts_nested_controls(self) -> None:
        source = '''hocus 0.3;
module M(flag: bool = true) exports (out: bool) {
  if outer @id("outer") (param.flag) outputs (out: bool) {
    if inner @id("inner") (param.flag) outputs (out: bool) {
      yield out = true;
    } else {
      yield out = false;
    }
    yield out = inner.out;
  } else {
    yield out = false;
  }
  export out = outer.out;
}
'''
        Parser(Lexer(source, "control-limit.hocus").tokenize(), max_control_items=2).parse()
        with self.assertRaises(HocusSourceError) as rejected:
            Parser(Lexer(source, "control-limit.hocus").tokenize(), max_control_items=1).parse()
        self.assertEqual(rejected.exception.diagnostic.code, "HOCUS323")

    def test_missing_else_brace_preserves_later_root_sibling(self) -> None:
        source = '''hocus 0.3;
module Recover(flag: bool = true) exports (out: bool) {
  if broken @id("broken") (param.flag) outputs (out: bool) {
    yield out = true;
  } else
  node sibling @id("sibling"): "null" {}
  export out = true;
}
'''
        parser = Parser(Lexer(source, "recover-else-root.hocus").tokenize())
        syntax = parser.parse()
        self.assertEqual([item.code for item in parser.diagnostics], ["HOCUS319"])
        assert syntax.module is not None
        self.assertTrue(any(getattr(item, "symbol", None) == "sibling" for item in syntax.module.statements))
        self.assertEqual(syntax.module.statements[-1].name, "out")  # type: ignore[union-attr]

    def test_missing_nested_else_brace_preserves_outer_body_sibling(self) -> None:
        source = '''hocus 0.3;
module Recover(flag: bool = true) exports (out: bool) {
  for outer @id("outer") (i in range(1)) carry (out: bool = false) {
    if broken @id("broken") (param.flag) outputs (out: bool) {
      yield out = true;
    } else
    node sibling @id("sibling"): "null" {}
    yield out = true;
  }
  export out = outer.out;
}
'''
        parser = Parser(Lexer(source, "recover-else-nested.hocus").tokenize())
        syntax = parser.parse()
        self.assertEqual([item.code for item in parser.diagnostics], ["HOCUS319"])
        assert syntax.module is not None
        outer = syntax.module.statements[0]
        self.assertIsInstance(outer, ForDecl)
        assert isinstance(outer, ForDecl)
        self.assertTrue(any(getattr(item, "symbol", None) == "sibling" for item in outer.body))
        self.assertIsInstance(outer.body[-1], YieldStmt)


if __name__ == "__main__":
    unittest.main()
