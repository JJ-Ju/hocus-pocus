from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.control_expander import expand_control_graph
from hocuspocus.hocusscript.control_semantic import ControlExpansionLimits
from hocuspocus.hocusscript.expander import ModuleExpansionError, ResolvedModuleUnit
from hocuspocus.hocusscript.parser import parse_syntax
from hocuspocus.hocusscript.resolved_modules import ResolvedImport


ENTRY_URI = "hocus-project://control-tests/main.hocus"


def _expand(body: str, *, limits: ControlExpansionLimits | None = None, cancellation=None):
    source = f'''hocus 0.3;
graph ControlGraph {{
  target = "/obj";
{body}
}}
'''.encode("utf-8")
    kwargs = {}
    if limits is not None:
        kwargs["limits"] = limits
    if cancellation is not None:
        kwargs["cancellation"] = cancellation
    return expand_control_graph(source, ENTRY_URI, {}, {}, **kwargs)


def _module_unit(source: str, uri: str) -> ResolvedModuleUnit:
    encoded = source.encode("utf-8")
    return ResolvedModuleUnit(
        uri,
        "sha256:" + hashlib.sha256(encoded).hexdigest(),
        parse_syntax(source, uri),
        {},
    )


class HocusScriptV03ExpanderTests(unittest.TestCase):
    def test_selected_if_emits_only_the_chosen_branch_and_composes_its_result(self) -> None:
        graph = _expand('''
  if choice @id("lod-choice") (true) outputs (value: int) {
    node selected @id("selected"): "null" { level = 7; }
    yield value = 7;
  } else {
    node hidden @id("hidden"): "null" { level = 9; }
    yield value = 9;
  }
  node result @id("result"): "null" { level = choice.value; }
''')

        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(
            [node["parms"][0]["value"]["value"] for node in graph["nodes"]],
            [7, 7],
        )
        mapping = next(
            item
            for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/1/parms/0"
        )
        stack = next(
            item
            for item in graph["expansionMap"]["controlStacks"]
            if item["controlStackId"] == mapping["controlStackId"]
        )
        self.assertEqual(stack["frames"][-1]["branch"], "then")

    def test_fold_is_half_open_and_zero_count_passes_through_its_initializer(self) -> None:
        graph = _expand('''
  for series @id("series") (i in range(3)) carry (value: int = 0) {
    node step @id("step"): "null" { index = iter.i; previous = carry.value; }
    yield value = iter.i;
  }
  for empty @id("empty") (i in range(0)) carry (value: int = 41) {
    node never @id("never"): "null" { index = iter.i; }
    yield value = iter.i;
  }
  node result @id("result"): "null" {
    final = series.value;
    empty = empty.value;
  }
''')

        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(
            [node["parms"][0]["value"]["value"] for node in graph["nodes"][:3]],
            [0, 1, 2],
        )
        result_parms = {
            parm["name"]: parm["value"]["value"]
            for parm in graph["nodes"][-1]["parms"]
        }
        self.assertEqual(result_parms, {"empty": 41, "final": 2})
        indexes = {
            frame["iterationIndex"]
            for stack in graph["expansionMap"]["controlStacks"]
            for frame in stack["frames"]
            if frame["kind"] == "for"
        }
        self.assertEqual(indexes, {0, 1, 2})

    def test_durable_identity_survives_symbol_renames_and_separates_iterations(self) -> None:
        first = _expand('''
  for series @id("durable-series") (i in range(2)) carry (value: int = 0) {
    node step @id("durable-step"): "null" { index = iter.i; }
    yield value = iter.i;
  }
  node result @id("result"): "null" { final = series.value; }
''')
        renamed = _expand('''
  for renamed @id("durable-series") (iteration in range(2)) carry (value: int = 0) {
    node renamedStep @id("durable-step"): "null" { index = iter.iteration; }
    yield value = iter.iteration;
  }
  node result @id("result"): "null" { final = renamed.value; }
''')

        first_ids = [node["explicitId"] for node in first["nodes"]]
        self.assertEqual(
            first_ids,
            [node["explicitId"] for node in renamed["nodes"]],
        )
        self.assertEqual(len(first_ids), len(set(first_ids)))

    def test_nested_provenance_tracks_the_current_iteration_and_inner_producer(self) -> None:
        graph = _expand('''
  for series @id("series") (i in range(2)) carry (value: int = 5) {
    if chosen @id("chosen") (true) outputs (value: int) {
      yield value = carry.value;
    } else {
      yield value = 0;
    }
    node step @id("step"): "null" { previous = chosen.value; }
    yield value = chosen.value;
  }
  node result @id("result"): "null" { final = series.value; }
''')

        mappings = {
            item["generatedPointer"]: item
            for item in graph["expansionMap"]["mappings"]
        }
        stacks = {
            item["controlStackId"]: item["frames"]
            for item in graph["expansionMap"]["controlStacks"]
        }
        second_step = stacks[mappings["/nodes/1/parms/0"]["controlStackId"]]
        result = stacks[mappings["/nodes/2/parms/0"]["controlStackId"]]
        expected = [("for", 1), ("if", None)]
        self.assertEqual(
            [(frame["kind"], frame.get("iterationIndex")) for frame in second_step],
            expected,
        )
        self.assertEqual(
            [(frame["kind"], frame.get("iterationIndex")) for frame in result],
            expected,
        )

    def test_runtime_scope_allows_local_use_and_control_to_shadow_outer_nodes(self) -> None:
        module_uri = "hocus-project://control-tests/modules/value.hocus"
        unit = _module_unit(
            '''hocus 0.3;
module Value() exports (out: int) { export out = 7; }
''',
            module_uri,
        )
        source = '''hocus 0.3;
import { Value } from "modules/value.hocus";
graph ControlGraph {
  target = "/obj";
  node shadow @id("outer-shadow"): "null" {}
  node choice @id("outer-choice"): "null" {}
  if outer @id("outer") (true) outputs (a: int, b: int) {
    use shadow @id("local-use") = Value();
    if choice @id("local-control") (true) outputs (value: int) {
      yield value = 9;
    } else {
      yield value = 10;
    }
    yield a = shadow.out;
    yield b = choice.value;
  } else {
    yield a = 0;
    yield b = 0;
  }
  node result @id("result"): "null" { a = outer.a; b = outer.b; }
}
'''
        syntax = parse_syntax(source, ENTRY_URI)
        declaration = syntax.imports[0]
        imported = ResolvedImport(
            declaration.specifier,
            declaration.imported_name,
            declaration.local_name,
            module_uri,
            declaration.span,
        )

        graph = expand_control_graph(
            source.encode("utf-8"),
            ENTRY_URI,
            {declaration.local_name: imported},
            {module_uri: unit},
        )

        self.assertEqual(
            [item["value"]["value"] for item in graph["nodes"][-1]["parms"]],
            [7, 9],
        )

    def test_module_and_control_composition_attributes_the_emitted_node_correctly(self) -> None:
        module_uri = "hocus-project://control-tests/modules/make-node.hocus"
        unit = _module_unit(
            '''hocus 0.3;
module MakeNode(value: int) exports (out: node_output) {
  node made @id("made"): "null" { value = param.value; }
  export out = made.output[0];
}
''',
            module_uri,
        )
        source = '''hocus 0.3;
import { MakeNode } from "modules/make-node.hocus";
graph ControlGraph {
  target = "/obj";
  if prior @id("prior") (true) outputs (value: int) {
    yield value = 7;
  } else {
    yield value = 8;
  }
  if current @id("current") (true) outputs (out: node_output) {
    use made @id("made") = MakeNode(value = prior.value);
    yield out = made.out;
  } else {
    node fallback @id("fallback"): "null" {}
    yield out = fallback.output[0];
  }
  node result @id("result"): "null" { input[0] = current.out; }
}
'''
        syntax = parse_syntax(source, ENTRY_URI)
        declaration = syntax.imports[0]
        imported = ResolvedImport(
            declaration.specifier,
            declaration.imported_name,
            declaration.local_name,
            module_uri,
            declaration.span,
        )

        graph = expand_control_graph(
            source.encode("utf-8"),
            ENTRY_URI,
            {declaration.local_name: imported},
            {module_uri: unit},
        )

        mapping = next(
            item
            for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        module_stack = next(
            item
            for item in graph["expansionMap"]["stacks"]
            if item["stackId"] == mapping["stackId"]
        )
        control_stack = next(
            item
            for item in graph["expansionMap"]["controlStacks"]
            if item["controlStackId"] == mapping["controlStackId"]
        )
        self.assertEqual(module_stack["frames"][-1]["moduleUri"], module_uri)
        self.assertEqual(mapping["primarySpan"]["sourceUri"], module_uri)
        self.assertEqual(
            [frame["durableSeed"] for frame in control_stack["frames"]],
            ["current"],
        )

    def test_public_budgets_and_cancellation_fail_with_typed_errors(self) -> None:
        body = '''
  for series @id("series") (i in range(3)) carry (value: int = 0) {
    node step @id("step"): "null" { index = iter.i; }
    yield value = iter.i;
  }
'''

        with self.assertRaises(ModuleExpansionError) as budget:
            _expand(
                body,
                limits=ControlExpansionLimits(aggregate_iterations=2),
            )
        self.assertEqual(budget.exception.code, "HOCUS464")
        with self.assertRaises(ModuleExpansionError) as cancelled:
            _expand(body, cancellation=lambda: True)
        self.assertEqual(cancelled.exception.code, "HOCUS499")

    def test_output_is_a_canonical_graphspec_with_an_authenticated_expansion_map(self) -> None:
        graph = _expand('''
  if choice @id("choice") (false) outputs (value: int) {
    yield value = 1;
  } else {
    yield value = 2;
  }
  node result @id("result"): "null" { level = choice.value; }
''')

        encoded = json.dumps(
            graph,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.assertEqual(json.loads(encoded), graph)
        self.assertEqual(graph["graphSpecVersion"], "0.4")
        self.assertEqual(graph["target"], "/obj")
        mappings = graph["expansionMap"]["mappings"]
        pointers = [item["generatedPointer"] for item in mappings]
        self.assertEqual(pointers, sorted(set(pointers)))
        self.assertEqual(
            len({item["originId"] for item in mappings}),
            len(mappings),
        )
        self.assertTrue(graph["expansionMap"]["controlStacks"])


if __name__ == "__main__":
    unittest.main()
