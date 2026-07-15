from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.control_semantic import (
    ControlExpansionLimits,
    validate_control_program,
)
from hocuspocus.hocusscript.diagnostics import CodeOffsetMap, SourcePosition, SourceSpan
from hocuspocus.hocusscript.expander import ModuleExpansionError, ResolvedModuleUnit
from hocuspocus.hocusscript.parser import parse_syntax
from hocuspocus.hocusscript.syntax import (
    ArrayExpr, CodeExpr, ForDecl, IfDecl, NodeDecl, ParmStmt, RevisionStmt,
)


DIGEST = "sha256:" + "3" * 64
ENTRY_URI = "hocus-project://control/program.hocus"
MODULE_URI = "hocus-project://control/modules/control.hocus"


@dataclass(frozen=True)
class _Import:
    specifier: str
    imported_name: str
    local_name: str
    target_uri: str
    span: object


def _resolved(declaration, target_uri: str = MODULE_URI) -> _Import:
    return _Import(
        declaration.specifier,
        declaration.imported_name,
        declaration.local_name,
        target_uri,
        declaration.span,
    )


def _validate_graph(source: str, **kwargs) -> None:
    validate_control_program(parse_syntax(source, ENTRY_URI), {}, {}, **kwargs)


def _program(module_source: str, *, arguments: str = ""):
    entry_source = f'''hocus 0.3;
import {{ Control as C }} from "modules/control.hocus";
graph Program {{
  target "/obj/program";
  node source @id("source"): "box" {{}}
  use result @id("result") = C({arguments});
  node output @id("output"): "null" {{ input[0] = result.out; }}
}}
'''
    entry = parse_syntax(entry_source, ENTRY_URI)
    module = ResolvedModuleUnit(
        MODULE_URI, DIGEST, parse_syntax(module_source, MODULE_URI), {}
    )
    exact_import = _resolved(entry.imports[0])
    return entry, {"C": exact_import}, {MODULE_URI: module}


class HocusScriptV03SemanticTests(unittest.TestCase):
    def test_valid_nested_controls_use_exact_types_and_outer_fold_bindings(self) -> None:
        module_source = '''hocus 0.3;
module Control(source: node_output, flag: bool = true, count: int = 2) exports (
  out: node_output,
) {
  for outer @id("outer") (i in range(param.count)) carry (
    out: node_output = param.source,
  ) {
    if choice @id("choice") (param.flag) outputs (out: node_output) {
      for inner @id("inner") (j in range(1)) carry (out: node_output = carry.out) {
        node step @id("step"): "null" {
          input[0] = carry.out;
          outerIndex = iter.i;
          innerIndex = iter.j;
        }
        yield out = step.output[0];
      }
      yield out = inner.out;
    } else {
      yield out = carry.out;
    }
    yield out = choice.out;
  }
  export out = outer.out;
}
'''
        entry, imports, modules = _program(
            module_source,
            arguments="source = source.output[0], flag = true, count = 2",
        )
        self.assertIsNone(validate_control_program(entry, imports, modules))

    def test_hidden_if_branch_is_statically_resolved_and_typed(self) -> None:
        source = '''hocus 0.3; graph G {
          target "/obj/g";
          if selected @id("selected") (true) outputs (out: int) {
            yield out = 1;
          } else {
            node invalid: "null" { value = missing.value; }
            yield out = 2;
          }
        }'''
        with self.assertRaises(ModuleExpansionError) as captured:
            _validate_graph(source)
        self.assertEqual(captured.exception.code, "HOCUS471")

    def test_zero_count_fold_body_is_statically_resolved(self) -> None:
        source = '''hocus 0.3; graph G {
          target "/obj/g";
          for zero @id("zero") (i in range(0)) carry (out: int = 1) {
            node invalid: "null" { value = missing.value; }
            yield out = carry.out;
          }
        }'''
        with self.assertRaises(ModuleExpansionError) as captured:
            _validate_graph(source)
        self.assertEqual(captured.exception.code, "HOCUS471")

    def test_conditions_counts_initializers_and_yields_require_exact_types(self) -> None:
        invalid = (
            '''hocus 0.3; graph G { target "/obj/g";
              if c @id("c") (1) outputs (out: int) { yield out = 1; } else { yield out = 2; }
            }''',
            '''hocus 0.3; graph G { target "/obj/g";
              for f @id("f") (i in range(true)) carry (out: int = 1) { yield out = carry.out; }
            }''',
            '''hocus 0.3; graph G { target "/obj/g";
              for f @id("f") (i in range(1)) carry (out: int = false) { yield out = carry.out; }
            }''',
            '''hocus 0.3; graph G { target "/obj/g";
              if c @id("c") (true) outputs (out: int) { yield out = false; } else { yield out = 2; }
            }''',
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, "HOCUS475")

    def test_control_yields_are_exact_unique_and_trailing(self) -> None:
        invalid = (
            '''hocus 0.3; graph G { target "/obj/g";
              if c @id("c") (true) outputs (a: int, b: int) {
                yield a = 1;
              } else { yield a = 1; yield b = 2; }
            }''',
            '''hocus 0.3; graph G { target "/obj/g";
              if c @id("c") (true) outputs (a: int) {
                yield a = 1; yield a = 2;
              } else { yield a = 1; }
            }''',
            '''hocus 0.3; graph G { target "/obj/g";
              if c @id("c") (true) outputs (a: int) {
                yield a = 1; node late: "null" {}
              } else { yield a = 1; }
            }''',
        )
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, "HOCUS479")

    def test_control_results_are_visible_only_after_declaration(self) -> None:
        before = '''hocus 0.3; graph G { target "/obj/g";
          node early: "null" { value = later.out; }
          if later @id("later") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
        }'''
        with self.assertRaises(ModuleExpansionError) as captured:
            _validate_graph(before)
        self.assertEqual(captured.exception.code, "HOCUS471")
        after = '''hocus 0.3; graph G { target "/obj/g";
          if earlier @id("earlier") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
          node late: "null" { value = earlier.out; }
        }'''
        _validate_graph(after)

    def test_block_symbols_and_identity_seeds_are_unified(self) -> None:
        same_seed = '''hocus 0.3; graph G { target "/obj/g";
          node n @id("shared"): "null" {}
          if c @id("shared") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
        }'''
        same_symbol = '''hocus 0.3; graph G { target "/obj/g";
          node duplicate: "null" {}
          if duplicate @id("control") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
        }'''
        for source in (same_seed, same_symbol):
            with self.assertRaises(ModuleExpansionError) as captured:
                _validate_graph(source)
            self.assertEqual(captured.exception.code, "HOCUS473")

    def test_special_fold_references_are_lexical_and_nested_names_shadow(self) -> None:
        outside = '''hocus 0.3; graph G { target "/obj/g";
          node n: "null" { value = iter.i; }
        }'''
        with self.assertRaises(ModuleExpansionError) as captured:
            _validate_graph(outside)
        self.assertEqual(captured.exception.code, "HOCUS471")

        shadow = '''hocus 0.3; graph G { target "/obj/g";
          for outer @id("outer") (i in range(1)) carry (value: int = 0) {
            for inner @id("inner") (i in range(1)) carry (other: int = carry.value) {
              node n: "null" { index = iter.i; outerValue = carry.value; }
              yield other = carry.other;
            }
            yield value = inner.other;
          }
        }'''
        _validate_graph(shadow)

    def test_graph_requires_one_absolute_target(self) -> None:
        for source in (
            'hocus 0.3; graph G { node n: "null" {} }',
            'hocus 0.3; graph G { target "relative"; }',
        ):
            with self.assertRaises(ModuleExpansionError) as captured:
                _validate_graph(source)
            self.assertEqual(captured.exception.code, "HOCUS302")

    def test_graph_directives_match_frozen_graph_admission_semantics(self) -> None:
        cases = (
            ('hocus 0.3; graph G { target "/obj//g"; }', "HOCUS302"),
            ('hocus 0.3; graph G { target "/obj/./g"; }', "HOCUS302"),
            ('hocus 0.3; graph G { target "/obj/g/"; }', "HOCUS302"),
            (
                'hocus 0.3; graph G { target "/obj/g"; existing e = "/obj/other/e"; }',
                "HOCUS311",
            ),
            (
                'hocus 0.3; graph G { target "/obj/g"; existing e = "/obj/g/e"; output = e; }',
                "HOCUS318",
            ),
            ('hocus 0.3; graph G { target "/obj/g"; output = missing; }', "HOCUS315"),
            ('hocus 0.3; graph G { target "/obj/g"; mode reconcile; }', "HOCUS305"),
            (
                'hocus 0.3; graph G { target "/obj/g"; mode reconcile; ownership ""; }',
                "HOCUS319",
            ),
            ('hocus 0.3; graph G { target "/obj/g"; mode invalid; }', "HOCUS303"),
            ('hocus 0.3; graph G { target "/obj/g"; layout = grid; }', "HOCUS316"),
            (
                'hocus 0.3; graph G { target "/obj/g"; existing e = "/obj/g//e"; }',
                "HOCUS310",
            ),
        )
        for source, code in cases:
            with self.subTest(code=code, source=source):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, code)
        _validate_graph('''hocus 0.3; graph G {
          target "/";
          mode reconcile;
          ownership "team";
          adopt e = "/obj/e";
          output = e;
          layout = auto;
        }''')

        revision_syntax = parse_syntax(
            'hocus 0.3; graph G { target "/obj/g"; expect revision 1; }', ENTRY_URI
        )
        assert revision_syntax.graph is not None
        revision = revision_syntax.graph.statements[1]
        assert isinstance(revision, RevisionStmt)
        forged_revision = replace(revision_syntax, graph=replace(
            revision_syntax.graph,
            statements=(revision_syntax.graph.statements[0], replace(revision, value=True)),
        ))
        with self.assertRaises(ModuleExpansionError) as invalid_revision:
            validate_control_program(forged_revision, {}, {})
        self.assertEqual(invalid_revision.exception.code, "HOCUS304")

    def test_malformed_module_mappings_and_import_targets_are_typed(self) -> None:
        module_source = '''hocus 0.3;
          module Control() exports (out: int) { export out = 1; }
        '''
        entry, imports, modules = _program(module_source)
        module = modules[MODULE_URI]
        with self.assertRaises(ModuleExpansionError) as bad_key:
            validate_control_program(entry, imports, {1: module})  # type: ignore[dict-item]
        self.assertEqual(bad_key.exception.code, "HOCUS460")
        malformed = replace(imports["C"], target_uri=1)  # type: ignore[arg-type]
        with self.assertRaises(ModuleExpansionError) as bad_target:
            validate_control_program(entry, {"C": malformed}, modules)
        self.assertEqual(bad_target.exception.code, "HOCUS463")

    def test_forged_empty_interface_is_a_typed_semantic_error(self) -> None:
        syntax = parse_syntax('''hocus 0.3; graph G { target "/obj/g";
          if c @id("c") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
        }''', ENTRY_URI)
        assert syntax.graph is not None
        control = syntax.graph.statements[1]
        assert isinstance(control, IfDecl)
        forged = replace(syntax, graph=replace(
            syntax.graph,
            statements=(syntax.graph.statements[0], replace(control, outputs=())),
        ))
        with self.assertRaises(ModuleExpansionError) as captured:
            validate_control_program(forged, {}, {})
        self.assertEqual(captured.exception.code, "HOCUS479")

    def test_hidden_embedded_code_is_structurally_checked_and_charged(self) -> None:
        syntax = parse_syntax('''hocus 0.3; graph G { target "/obj/g";
          if c @id("c") (true) outputs (out: int) {
            yield out = 1;
          } else {
            node hidden: "null" { value = 2; }
            yield out = 2;
          }
        }''', ENTRY_URI)
        assert syntax.graph is not None
        control = syntax.graph.statements[1]
        assert isinstance(control, IfDecl)
        hidden = control.else_body[0]
        assert isinstance(hidden, NodeDecl)
        parm = hidden.statements[0]
        assert isinstance(parm, ParmStmt)
        code_start = parm.value.span.start
        code_end = SourcePosition(code_start.offset + 2, code_start.line, code_start.column + 2)
        code_span = SourceSpan(parm.value.span.source_name, code_start, code_end)
        code = CodeExpr(
            "vex", "xx", code_span, code_span,
            CodeOffsetMap(2, ((0, code_start.offset), (2, code_end.offset))),
        )
        forged_hidden = replace(hidden, statements=(replace(parm, value=code),))
        forged_control = replace(control, else_body=(forged_hidden, control.else_body[1]))
        forged = replace(syntax, graph=replace(
            syntax.graph,
            statements=(syntax.graph.statements[0], forged_control),
        ))
        with self.assertRaises(ModuleExpansionError) as captured:
            validate_control_program(
                forged,
                {},
                {},
                limits=ControlExpansionLimits(aggregate_code_bytes=1),
            )
        self.assertEqual(captured.exception.code, "HOCUS464")

        surrogate = replace(code, body="\ud800", offset_map=CodeOffsetMap(
            1, ((0, code_start.offset), (1, code_end.offset)),
        ))
        surrogate_hidden = replace(hidden, statements=(replace(parm, value=surrogate),))
        surrogate_control = replace(
            control, else_body=(surrogate_hidden, control.else_body[1])
        )
        forged_surrogate = replace(syntax, graph=replace(
            syntax.graph,
            statements=(syntax.graph.statements[0], surrogate_control),
        ))
        with self.assertRaises(ModuleExpansionError) as invalid_unicode:
            validate_control_program(forged_surrogate, {}, {})
        self.assertEqual(invalid_unicode.exception.code, "HOCUS474")

    def test_cancellation_reaches_each_array_child_checkpoint(self) -> None:
        syntax = parse_syntax('''hocus 0.3; graph G { target "/obj/g";
          node n: "null" { value = 1; }
        }''', ENTRY_URI)
        assert syntax.graph is not None
        node = syntax.graph.statements[1]
        assert isinstance(node, NodeDecl)
        parm = node.statements[0]
        assert isinstance(parm, ParmStmt)
        array = ArrayExpr(tuple(parm.value for _ in range(32)), False, parm.value.span)
        forged = replace(syntax, graph=replace(
            syntax.graph,
            statements=(syntax.graph.statements[0], replace(
                node, statements=(replace(parm, value=array),),
            )),
        ))
        calls = 0

        def cancel() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 12

        with self.assertRaises(ModuleExpansionError) as captured:
            validate_control_program(forged, {}, {}, cancellation=cancel)
        self.assertEqual(captured.exception.code, "HOCUS499")
        self.assertEqual(calls, 12)

    def test_cancellation_is_checked_during_large_block_name_scan(self) -> None:
        nodes = " ".join(f'node n{index}: "null" {{}}' for index in range(32))
        syntax = parse_syntax(
            f'hocus 0.3; graph G {{ target "/obj/g"; {nodes} }}', ENTRY_URI
        )
        calls = 0

        def cancel() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 10

        with self.assertRaises(ModuleExpansionError) as captured:
            validate_control_program(syntax, {}, {}, cancellation=cancel)
        self.assertEqual(captured.exception.code, "HOCUS499")
        self.assertEqual(calls, 10)

    def test_cancellation_callback_is_checked_and_typed(self) -> None:
        source = 'hocus 0.3; graph G { target "/obj/g"; node n: "null" {} }'
        syntax = parse_syntax(source, ENTRY_URI)
        with self.assertRaises(ModuleExpansionError) as cancelled:
            validate_control_program(syntax, {}, {}, cancellation=lambda: True)
        self.assertEqual(cancelled.exception.code, "HOCUS499")
        with self.assertRaises(ModuleExpansionError) as malformed:
            validate_control_program(syntax, {}, {}, cancellation=lambda: 1)  # type: ignore[arg-type]
        self.assertEqual(malformed.exception.code, "HOCUS499")

    def test_limit_fields_are_exact_positive_bounded_integers(self) -> None:
        self.assertEqual(ControlExpansionLimits().per_fold_iterations, 4096)
        self.assertEqual(ControlExpansionLimits().aggregate_iterations, 100_000)
        for kwargs in (
            {"per_fold_iterations": True},
            {"per_fold_iterations": 4097},
            {"aggregate_iterations": 0},
        ):
            with self.assertRaises(ValueError):
                ControlExpansionLimits(**kwargs)


if __name__ == "__main__":
    unittest.main()
