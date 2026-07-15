from __future__ import annotations

import hashlib
import json
import sys
import unittest
from collections.abc import Iterator, Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.control_expander import (
    _Scope, _State, _emit_node, _node_bound, expand_control_graph,
)
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
    def test_if_evaluates_only_selected_branch_and_composes_scalar_result(self) -> None:
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
        self.assertEqual(graph["nodes"][0]["parms"][0]["value"]["value"], 7)
        self.assertEqual(graph["nodes"][1]["parms"][0]["value"]["value"], 7)
        mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/1/parms/0"
        )
        self.assertIsNotNone(mapping["controlStackId"])
        frame = graph["expansionMap"]["controlStacks"][0]["frames"][0]
        self.assertEqual(frame["branch"], "then")

    def test_hidden_branch_and_zero_count_body_are_statically_validated(self) -> None:
        invalid_if = '''
  if choice @id("choice") (true) outputs (value: int) {
    yield value = 1;
  } else {
    yield value = false;
  }
'''
        with self.assertRaises(ModuleExpansionError) as hidden:
            _expand(invalid_if)
        self.assertEqual(hidden.exception.code, "HOCUS475")

        invalid_zero = '''
  for series @id("series") (i in range(0)) carry (value: int = 1) {
    yield value = false;
  }
'''
        with self.assertRaises(ModuleExpansionError) as zero:
            _expand(invalid_zero)
        self.assertEqual(zero.exception.code, "HOCUS475")

    def test_fold_is_half_open_composable_and_domain_separates_each_index(self) -> None:
        graph = _expand('''
  for series @id("series") (i in range(3)) carry (value: int = 0) {
    node step @id("step"): "null" { index = iter.i; previous = carry.value; }
    yield value = iter.i;
  }
  node result @id("result"): "null" { final = series.value; }
''')
        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(
            [node["parms"][0]["value"]["value"] for node in graph["nodes"][:3]],
            [0, 1, 2],
        )
        self.assertEqual(graph["nodes"][-1]["parms"][0]["value"]["value"], 2)
        generated_ids = [node["explicitId"] for node in graph["nodes"][:3]]
        self.assertEqual(len(set(generated_ids)), 3)
        indexes = {
            frame["iterationIndex"]
            for stack in graph["expansionMap"]["controlStacks"]
            for frame in stack["frames"] if frame["kind"] == "for"
        }
        self.assertEqual(indexes, {0, 1, 2})

    def test_zero_count_returns_initializer_without_inventing_iteration_frame(self) -> None:
        graph = _expand('''
  for series @id("series") (i in range(0)) carry (value: int = 41) {
    node never @id("never"): "null" { index = iter.i; }
    yield value = iter.i;
  }
  node result @id("result"): "null" { final = series.value; }
''')
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["nodes"][0]["parms"][0]["value"]["value"], 41)
        self.assertEqual(graph["expansionMap"]["controlStacks"], [])
        mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        self.assertIsNone(mapping["controlStackId"])
        self.assertEqual(
            {item["role"] for item in mapping["relatedOrigins"]},
            {"control_declaration", "fold_count", "carry_initializer"},
        )

    def test_identity_ignores_control_symbol_iterator_and_body_local_names(self) -> None:
        first = _expand('''
  for series @id("durable-series") (i in range(2)) carry (value: int = 0) {
    node step @id("durable-step"): "null" { index = iter.i; }
    yield value = iter.i;
  }
  node result @id("result"): "null" { final = series.value; }
''')
        second = _expand('''
  for renamed @id("durable-series") (iteration in range(2)) carry (value: int = 0) {
    node renamedStep @id("durable-step"): "null" { index = iter.iteration; }
    yield value = iter.iteration;
  }
  node result @id("result"): "null" { final = renamed.value; }
''')
        self.assertEqual(
            [node["explicitId"] for node in first["nodes"]],
            [node["explicitId"] for node in second["nodes"]],
        )
        self.assertNotEqual(
            first["expansionMap"]["controlStacks"],
            second["expansionMap"]["controlStacks"],
        )

    def test_identity_path_preserves_module_control_structural_order(self) -> None:
        syntax = parse_syntax('''hocus 0.3;
graph G { target = "/obj"; node leaf @id("leaf"): "null" {} }
''', ENTRY_URI)
        assert syntax.graph is not None
        node = syntax.graph.statements[1]
        module_step = {
            "domain": "hocus-module-instance-v1",
            "durableSeed": "make",
            "moduleUri": "hocus-project://control-tests/make.hocus",
        }
        control_step = {
            "domain": "hocus-control-if-branch-v1",
            "durableSeed": "choice",
            "branch": "then",
        }
        use_inside_control = _node_bound(
            node, "hocus-project://control-tests/make.hocus", ("make",),
            (control_step, module_step), "sha256:" + "1" * 64,
        )
        control_inside_use = _node_bound(
            node, "hocus-project://control-tests/make.hocus", ("make",),
            (module_step, control_step), "sha256:" + "1" * 64,
        )
        self.assertNotEqual(use_inside_control.value, control_inside_use.value)

    def test_per_fold_aggregate_node_and_cancellation_limits_fail_typed(self) -> None:
        body = '''
  for series @id("series") (i in range(3)) carry (value: int = 0) {
    node step @id("step"): "null" { index = iter.i; }
    yield value = iter.i;
  }
'''
        with self.assertRaises(ModuleExpansionError) as per_fold:
            _expand(body, limits=ControlExpansionLimits(per_fold_iterations=2))
        self.assertEqual(per_fold.exception.code, "HOCUS464")
        with self.assertRaises(ModuleExpansionError) as aggregate:
            _expand(body, limits=ControlExpansionLimits(aggregate_iterations=2))
        self.assertEqual(aggregate.exception.code, "HOCUS464")
        with self.assertRaises(ModuleExpansionError) as nodes:
            _expand(body, limits=ControlExpansionLimits(expanded_nodes=2))
        self.assertEqual(nodes.exception.code, "HOCUS464")
        with self.assertRaises(ModuleExpansionError) as cancelled:
            _expand(body, cancellation=lambda: True)
        self.assertEqual(cancelled.exception.code, "HOCUS499")
        with self.assertRaises(ModuleExpansionError) as malformed:
            _expand(body, cancellation=lambda: 1)
        self.assertEqual(malformed.exception.code, "HOCUS499")

    def test_nested_fold_cannot_consume_budget_reserved_only_by_outer_admission(self) -> None:
        body = '''
  for outer @id("outer") (i in range(3)) carry (enabled: bool = true) {
    if choice @id("choice") (carry.enabled) outputs (enabled: bool) {
      for inner @id("inner") (j in range(2)) carry (value: int = 0) {
        yield value = iter.j;
      }
      yield enabled = false;
    } else {
      yield enabled = false;
    }
    yield enabled = choice.enabled;
  }
'''
        with self.assertRaises(ModuleExpansionError) as aggregate:
            _expand(body, limits=ControlExpansionLimits(aggregate_iterations=4))
        self.assertEqual(aggregate.exception.code, "HOCUS464")

    def test_nested_control_result_keeps_the_most_specific_producer_stack(self) -> None:
        graph = _expand('''
  if outer @id("outer") (true) outputs (value: int) {
    if inner @id("inner") (true) outputs (value: int) {
      yield value = 7;
    } else {
      yield value = 8;
    }
    yield value = inner.value;
  } else {
    yield value = 9;
  }
  node result @id("result"): "null" { level = outer.value; }
''')
        mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        stack = next(
            item for item in graph["expansionMap"]["controlStacks"]
            if item["controlStackId"] == mapping["controlStackId"]
        )
        self.assertEqual(
            [frame["durableSeed"] for frame in stack["frames"]],
            ["outer", "inner"],
        )

    def test_pass_through_carry_uses_the_current_selected_iteration_frames(self) -> None:
        graph = _expand('''
  for plain @id("plain") (i in range(2)) carry (value: int = 5) {
    yield value = carry.value;
  }
  for nested @id("nested") (i in range(2)) carry (value: int = plain.value) {
    if pass @id("pass") (true) outputs (value: int) {
      yield value = carry.value;
    } else {
      yield value = 0;
    }
    yield value = pass.value;
  }
  node result @id("result"): "null" {
    plainValue = plain.value;
    nestedValue = nested.value;
  }
''')
        mappings = {
            item["generatedPointer"]: item
            for item in graph["expansionMap"]["mappings"]
        }
        stacks = {
            item["controlStackId"]: item
            for item in graph["expansionMap"]["controlStacks"]
        }
        plain = stacks[mappings["/nodes/0/parms/0"]["controlStackId"]]["frames"]
        nested = stacks[mappings["/nodes/0/parms/1"]["controlStackId"]]["frames"]
        self.assertEqual([frame["iterationIndex"] for frame in plain], [1])
        self.assertEqual(
            [(frame["kind"], frame.get("iterationIndex")) for frame in nested],
            [("for", 1), ("if", None)],
        )

    def test_carry_value_used_by_each_node_maps_to_the_current_iteration(self) -> None:
        graph = _expand('''
  for series @id("series") (i in range(2)) carry (value: int = 5) {
    node step @id("step"): "null" { previous = carry.value; }
    yield value = carry.value;
  }
''')
        mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/1/parms/0"
        )
        stack = next(
            item for item in graph["expansionMap"]["controlStacks"]
            if item["controlStackId"] == mapping["controlStackId"]
        )
        self.assertEqual(stack["frames"][-1]["iterationIndex"], 1)

    def test_local_use_and_control_shadow_outer_nodes_at_runtime(self) -> None:
        module_uri = "hocus-project://control-tests/modules/value.hocus"
        unit = _module_unit('''hocus 0.3;
module Value() exports (out: int) { export out = 7; }
''', module_uri)
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
            declaration.specifier, declaration.imported_name,
            declaration.local_name, module_uri, declaration.span,
        )
        graph = expand_control_graph(
            source.encode(), ENTRY_URI,
            {declaration.local_name: imported}, {module_uri: unit},
        )
        result = graph["nodes"][-1]
        self.assertEqual(
            [item["value"]["value"] for item in result["parms"]], [7, 9],
        )

    def test_control_can_compose_through_a_module_use(self) -> None:
        module_uri = "hocus-project://control-tests/modules/make.hocus"
        module_source = '''hocus 0.3;
module Make(value: int) exports (out: int) {
  export out = param.value;
}
'''
        unit = _module_unit(module_source, module_uri)
        source = '''hocus 0.3;
import { Make } from "modules/make.hocus";
graph ControlGraph {
  target = "/obj";
  if choice @id("choice") (true) outputs (value: int) {
    use made @id("made") = Make(value = 7);
    yield value = made.out;
  } else {
    yield value = 9;
  }
  node result @id("result"): "null" { level = choice.value; }
}
'''
        syntax = parse_syntax(source, ENTRY_URI)
        declaration = syntax.imports[0]
        resolved = ResolvedImport(
            declaration.specifier, declaration.imported_name,
            declaration.local_name, module_uri, declaration.span,
        )
        unit = ResolvedModuleUnit(
            unit.uri, unit.source_digest, unit.syntax, {},
        )
        graph = expand_control_graph(
            source.encode("utf-8"), ENTRY_URI,
            {declaration.local_name: resolved}, {module_uri: unit},
        )
        self.assertEqual(graph["nodes"][0]["parms"][0]["value"]["value"], 7)
        self.assertTrue(graph["expansionMap"]["controlStacks"])
        parm_mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        self.assertIsNotNone(parm_mapping["stackId"])
        module_stack = next(
            item for item in graph["expansionMap"]["stacks"]
            if item["stackId"] == parm_mapping["stackId"]
        )
        self.assertEqual(module_stack["frames"][-1]["moduleUri"], module_uri)

    def test_forwarded_module_argument_uses_the_receiving_module_stack(self) -> None:
        a_uri = "hocus-project://control-tests/modules/a.hocus"
        b_uri = "hocus-project://control-tests/modules/b.hocus"
        a = _module_unit('''hocus 0.3;
module A() exports (out: int) { export out = 7; }
''', a_uri)
        b = _module_unit('''hocus 0.3;
module B(value: int) exports (out: node_output) {
  node made @id("made"): "null" { value = param.value; }
  export out = made.output[0];
}
''', b_uri)
        source = '''hocus 0.3;
import { A } from "modules/a.hocus";
import { B } from "modules/b.hocus";
graph ControlGraph {
  target = "/obj";
  use a @id("a") = A();
  use b @id("b") = B(value = a.out);
  node result @id("result"): "null" { input[0] = b.out; }
}
'''
        syntax = parse_syntax(source, ENTRY_URI)
        resolved = {}
        for declaration, uri in zip(syntax.imports, (a_uri, b_uri)):
            resolved[declaration.local_name] = ResolvedImport(
                declaration.specifier, declaration.imported_name,
                declaration.local_name, uri, declaration.span,
            )
        graph = expand_control_graph(
            source.encode("utf-8"), ENTRY_URI, resolved, {a_uri: a, b_uri: b},
        )
        parm_mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        stack = next(
            item for item in graph["expansionMap"]["stacks"]
            if item["stackId"] == parm_mapping["stackId"]
        )
        self.assertEqual(stack["frames"][-1]["moduleUri"], b_uri)
        self.assertEqual(parm_mapping["primarySpan"]["sourceUri"], b_uri)

    def test_module_argument_inside_later_control_uses_current_control_stack(self) -> None:
        module_uri = "hocus-project://control-tests/modules/make-node.hocus"
        unit = _module_unit('''hocus 0.3;
module MakeNode(value: int) exports (out: node_output) {
  node made @id("made"): "null" { value = param.value; }
  export out = made.output[0];
}
''', module_uri)
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
            declaration.specifier, declaration.imported_name,
            declaration.local_name, module_uri, declaration.span,
        )
        graph = expand_control_graph(
            source.encode(), ENTRY_URI,
            {declaration.local_name: imported}, {module_uri: unit},
        )
        mapping = next(
            item for item in graph["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        stack = next(
            item for item in graph["expansionMap"]["controlStacks"]
            if item["controlStackId"] == mapping["controlStackId"]
        )
        self.assertEqual(
            [frame["durableSeed"] for frame in stack["frames"]], ["current"],
        )

    def test_result_is_canonical_json_and_expansion_origins_are_authenticated(self) -> None:
        graph = _expand('''
  if choice @id("choice") (false) outputs (value: int) {
    yield value = 1;
  } else {
    yield value = 2;
  }
  node result @id("result"): "null" { level = choice.value; }
''')
        encoded = json.dumps(
            graph, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        )
        self.assertEqual(json.loads(encoded), graph)
        pointers = [
            item["generatedPointer"] for item in graph["expansionMap"]["mappings"]
        ]
        self.assertEqual(pointers, sorted(set(pointers)))
        self.assertEqual(
            len({item["originId"] for item in graph["expansionMap"]["mappings"]}),
            len(pointers),
        )

    def test_node_emission_preserves_array_and_code_value_carriers(self) -> None:
        source = '''hocus 0.1;
graph Values {
  target "/obj";
  node values: "null" {
    items = [1, 2.5, true, "x"];
    snippet = vex`@Cd = 1;`;
  }
}
'''
        syntax = parse_syntax(source, ENTRY_URI)
        assert syntax.graph is not None
        node = syntax.graph.statements[1]
        state = _State(ControlExpansionLimits(), None)
        _emit_node(
            node, ENTRY_URI, (), (), (), "sha256:" + "2" * 64,
            _Scope(), state,
        )
        emitted = state.nodes[0].to_dict()
        self.assertEqual(emitted["parms"][0]["value"]["kind"], "array")
        self.assertEqual(
            [item["value"] for item in emitted["parms"][0]["value"]["items"]],
            [1, 2.5, True, "x"],
        )
        self.assertEqual(emitted["parms"][1]["value"]["kind"], "code")
        self.assertEqual(emitted["parms"][1]["value"]["body"], "@Cd = 1;")
        bounded_state = _State(ControlExpansionLimits(aggregate_code_bytes=5), None)
        with self.assertRaises(ModuleExpansionError) as bounded:
            _emit_node(
                node, ENTRY_URI, (), (), (), "sha256:" + "2" * 64,
                _Scope(), bounded_state,
            )
        self.assertEqual(bounded.exception.code, "HOCUS464")

    def test_public_mapping_and_import_evidence_is_snapshotted_once(self) -> None:
        class OnceMapping(Mapping):
            def __init__(self, values):
                self.values = dict(values)
                self.item_reads = 0

            def __getitem__(self, key):
                return self.values[key]

            def __iter__(self) -> Iterator:
                return iter(self.values)

            def __len__(self) -> int:
                return len(self.values)

            def items(self):
                self.item_reads += 1
                if self.item_reads > 1:
                    raise RuntimeError("mapping was read twice")
                return tuple(self.values.items())

        class OnceImport:
            def __init__(self, declaration, target_uri):
                self.specifier = declaration.specifier
                self.imported_name = declaration.imported_name
                self.local_name = declaration.local_name
                self.span = declaration.span
                self._target_uri = target_uri
                self.target_reads = 0

            @property
            def target_uri(self):
                self.target_reads += 1
                if self.target_reads > 1:
                    return "hocus-project://control-tests/modules/swapped.hocus"
                return self._target_uri

        module_uri = "hocus-project://control-tests/modules/value.hocus"
        unit = _module_unit('''hocus 0.3;
module Value() exports (out: int) { export out = 7; }
''', module_uri)
        source = '''hocus 0.3;
import { Value } from "modules/value.hocus";
graph ControlGraph {
  target = "/obj";
  use value @id("value") = Value();
  node result @id("result"): "null" { value = value.out; }
}
'''
        syntax = parse_syntax(source, ENTRY_URI)
        evidence = OnceImport(syntax.imports[0], module_uri)
        imports = OnceMapping({"Value": evidence})
        modules = OnceMapping({module_uri: unit})
        graph = expand_control_graph(source.encode(), ENTRY_URI, imports, modules)
        self.assertEqual(graph["nodes"][0]["parms"][0]["value"]["value"], 7)
        self.assertEqual(imports.item_reads, 1)
        self.assertEqual(modules.item_reads, 1)
        self.assertEqual(evidence.target_reads, 1)

        class BrokenMapping(OnceMapping):
            def items(self):
                raise RuntimeError("hostile")

        with self.assertRaises(ModuleExpansionError) as broken:
            expand_control_graph(
                source.encode(), ENTRY_URI, BrokenMapping({}),
                OnceMapping({module_uri: unit}),
            )
        self.assertEqual(broken.exception.code, "HOCUS460")

        untouched_imports = OnceMapping({"Value": evidence})
        untouched_modules = OnceMapping({module_uri: unit})
        with self.assertRaises(ModuleExpansionError) as cancelled:
            expand_control_graph(
                source.encode(), ENTRY_URI, untouched_imports, untouched_modules,
                cancellation=lambda: True,
            )
        self.assertEqual(cancelled.exception.code, "HOCUS499")
        self.assertEqual(untouched_imports.item_reads, 0)
        self.assertEqual(untouched_modules.item_reads, 0)


if __name__ == "__main__":
    unittest.main()
