from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.control_semantic import validate_control_program
from hocuspocus.hocusscript.expander import ModuleExpansionError, ResolvedModuleUnit
from hocuspocus.hocusscript.parser import parse_syntax
from hocuspocus.hocusscript.resolved_modules import ResolvedImport


DIGEST = "sha256:" + "3" * 64
ENTRY_URI = "hocus-project://control/program.hocus"
MODULE_URI = "hocus-project://control/modules/control.hocus"


def _validate_graph(source: str) -> None:
    validate_control_program(parse_syntax(source, ENTRY_URI), {}, {})


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
    declaration = entry.imports[0]
    resolved = ResolvedImport(
        declaration.specifier,
        declaration.imported_name,
        declaration.local_name,
        MODULE_URI,
        declaration.span,
    )
    module = ResolvedModuleUnit(
        MODULE_URI,
        DIGEST,
        parse_syntax(module_source, MODULE_URI),
        {},
    )
    return entry, {"C": resolved}, {MODULE_URI: module}


class HocusScriptV03SemanticTests(unittest.TestCase):
    def test_nested_controls_compose_through_a_module(self) -> None:
        module_source = '''hocus 0.3;
module Control(source: node_output, flag: bool = true, count: int = 2) exports (
  out: node_output,
) {
  for outer @id("outer") (i in range(param.count)) carry (
    out: node_output = param.source,
  ) {
    if choice @id("choice") (param.flag) outputs (out: node_output) {
      for inner @id("inner") (j in range(1)) carry (
        out: node_output = carry.out,
      ) {
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

    def test_unselected_and_zero_iteration_bodies_are_validated(self) -> None:
        invalid_programs = (
            '''hocus 0.3; graph G {
              target "/obj/g";
              if selected @id("selected") (true) outputs (out: int) {
                yield out = 1;
              } else {
                node invalid: "null" { value = missing.value; }
                yield out = 2;
              }
            }''',
            '''hocus 0.3; graph G {
              target "/obj/g";
              for zero @id("zero") (i in range(0)) carry (out: int = 1) {
                node invalid: "null" { value = missing.value; }
                yield out = carry.out;
              }
            }''',
        )
        for source in invalid_programs:
            with self.subTest(source=source):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, "HOCUS471")

    def test_control_types_and_yield_contracts_are_exact(self) -> None:
        invalid_programs = (
            (
                '''hocus 0.3; graph G { target "/obj/g";
                  if c @id("c") (1) outputs (out: int) {
                    yield out = 1;
                  } else { yield out = 2; }
                }''',
                "HOCUS475",
            ),
            (
                '''hocus 0.3; graph G { target "/obj/g";
                  for f @id("f") (i in range(true)) carry (out: int = 1) {
                    yield out = carry.out;
                  }
                }''',
                "HOCUS475",
            ),
            (
                '''hocus 0.3; graph G { target "/obj/g";
                  for f @id("f") (i in range(1)) carry (out: int = false) {
                    yield out = carry.out;
                  }
                }''',
                "HOCUS475",
            ),
            (
                '''hocus 0.3; graph G { target "/obj/g";
                  if c @id("c") (true) outputs (out: int) {
                    yield out = false;
                  } else { yield out = 2; }
                }''',
                "HOCUS475",
            ),
            (
                '''hocus 0.3; graph G { target "/obj/g";
                  if c @id("c") (true) outputs (a: int, b: int) {
                    yield a = 1;
                  } else { yield a = 1; yield b = 2; }
                }''',
                "HOCUS479",
            ),
            (
                '''hocus 0.3; graph G { target "/obj/g";
                  if c @id("c") (true) outputs (out: int) {
                    yield out = 1;
                    node late: "null" {}
                  } else { yield out = 2; }
                }''',
                "HOCUS479",
            ),
        )
        for source, code in invalid_programs:
            with self.subTest(code=code):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, code)

    def test_control_results_and_fold_bindings_obey_lexical_order(self) -> None:
        before_declaration = '''hocus 0.3; graph G { target "/obj/g";
          node early: "null" { value = later.out; }
          if later @id("later") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
        }'''
        with self.assertRaises(ModuleExpansionError) as before:
            _validate_graph(before_declaration)
        self.assertEqual(before.exception.code, "HOCUS471")

        outside_fold = '''hocus 0.3; graph G { target "/obj/g";
          node invalid: "null" { value = iter.i; }
        }'''
        with self.assertRaises(ModuleExpansionError) as outside:
            _validate_graph(outside_fold)
        self.assertEqual(outside.exception.code, "HOCUS471")

        valid_nested_scope = '''hocus 0.3; graph G { target "/obj/g";
          if earlier @id("earlier") (true) outputs (out: int) {
            yield out = 1;
          } else { yield out = 2; }
          for outer @id("outer") (i in range(1)) carry (value: int = earlier.out) {
            for inner @id("inner") (i in range(1)) carry (
              other: int = carry.value,
            ) {
              node n: "null" { index = iter.i; outerValue = carry.value; }
              yield other = carry.other;
            }
            yield value = inner.other;
          }
          node result: "null" { value = outer.value; }
        }'''
        self.assertIsNone(_validate_graph(valid_nested_scope))

    def test_block_symbols_and_durable_seeds_share_a_namespace(self) -> None:
        invalid_programs = (
            '''hocus 0.3; graph G { target "/obj/g";
              node n @id("shared"): "null" {}
              if c @id("shared") (true) outputs (out: int) {
                yield out = 1;
              } else { yield out = 2; }
            }''',
            '''hocus 0.3; graph G { target "/obj/g";
              node duplicate: "null" {}
              if duplicate @id("control") (true) outputs (out: int) {
                yield out = 1;
              } else { yield out = 2; }
            }''',
        )
        for source in invalid_programs:
            with self.subTest(source=source):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, "HOCUS473")

    def test_graph_target_is_required_absolute_and_canonical(self) -> None:
        self.assertIsNone(
            _validate_graph('hocus 0.3; graph G { target "/obj/g"; }')
        )
        invalid_programs = (
            'hocus 0.3; graph G { node n: "null" {} }',
            'hocus 0.3; graph G { target "relative"; }',
            'hocus 0.3; graph G { target "/obj//g"; }',
        )
        for source in invalid_programs:
            with self.subTest(source=source):
                with self.assertRaises(ModuleExpansionError) as captured:
                    _validate_graph(source)
                self.assertEqual(captured.exception.code, "HOCUS302")


if __name__ == "__main__":
    unittest.main()
