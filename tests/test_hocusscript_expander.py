from __future__ import annotations

import json
import sys
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    ModuleLockRecord, ModuleSourceEnvelope, ResolvedModuleLimits, graph_spec_from_dict,
    module_interface_digest, module_transitive_digest,
)
from hocuspocus.hocusscript.bundle import _validate_graph_spec
from hocuspocus.hocusscript.expander import (
    ExpansionLimits, ModuleExpansionError, ResolvedModuleUnit,
    expand_module_graph, expand_resolved_module_dag, resolved_import_map, resolved_units_from_dag,
    validate_module_interfaces,
)
from hocuspocus.hocusscript.resolved_modules import ResolvedImport, module_source_digest
from hocuspocus.hocusscript.parser import parse_syntax
from test_hocusscript_resolved_modules import (
    ENTRY as RESOLVED_ENTRY_URI,
    Fixture,
    _module as _resolved_envelope,
    _validate as _resolved_dag,
)


DIGEST = "sha256:" + "1" * 64
ENTRY_URI = "hocus-project://city/asset.hocus"
NOISE_URI = "hocus-project://city/noise.hocus"


@dataclass(frozen=True)
class _Import:
    specifier: str
    imported_name: str
    local_name: str
    target_uri: str
    span: object


def _resolved(declaration, target_uri: str) -> _Import:
    return _Import(
        declaration.specifier, declaration.imported_name, declaration.local_name,
        target_uri, declaration.span,
    )


def _module(source: str, uri: str, imports=None) -> ResolvedModuleUnit:
    return ResolvedModuleUnit(uri, DIGEST, parse_syntax(source, uri), imports or {})


def _shape_fixture(relative: str, type_name: str) -> Fixture:
    uri = f"hocus-project://city/modules/{relative}.hocus"
    source = f'''hocus 0.2; module Shape() exports (result: node_output) {{
      node n: "{type_name}" {{}}
      export result = n.output[0];
    }}'''.encode("utf-8")
    source_digest = module_source_digest(source)
    interface_digest = module_interface_digest({
        "schemaVersion": 1, "moduleName": "Shape", "parameters": [],
        "exports": [{"name": "result", "type": "node_output"}],
    })
    transitive = module_transitive_digest(
        uri=uri, source_digest=source_digest, interface_digest=interface_digest,
        dependencies=(),
    )
    lock = ModuleLockRecord(
        uri, "city", None, None, None, "0.2", f"modules/{relative}.hocus",
        source_digest, interface_digest, transitive, (), None,
    )
    return Fixture("Shape", ModuleSourceEnvelope(uri, source, ()), lock)


NOISE = '''hocus 0.2;
module Noise(source: node_output, scale: float = 1.0) exports (
  result: node_output,
  effectiveScale: float,
) {
  node noise @id("noise-node"): "mountain" {
    input[0] = param.source;
    height = param.scale;
  }
  export result = noise.output[0];
  export effectiveScale = param.scale;
}
'''


def _graph(use_symbol: str = "noise", scale: str = "2.0") -> str:
    return f'''hocus 0.2;
import {{ Noise as StudioNoise }} from "./noise.hocus";
graph asset {{
  target "/obj/asset";
  category Sop;
  mode merge;
  node source: "box" {{}}
  use {use_symbol} @id("asset-noise") = StudioNoise(source = source.output[0], scale = {scale});
  node result: "null" {{ input[0] = {use_symbol}.result; }}
  output = result;
}}
'''


def _expand(source: str = _graph()):
    entry = parse_syntax(source, ENTRY_URI)
    resolved = _resolved(entry.imports[0], NOISE_URI)
    module = _module(NOISE, NOISE_URI)
    spec = expand_module_graph(
        entry_source=source.encode("utf-8"), entry_uri=ENTRY_URI,
        entry_imports={"StudioNoise": resolved}, modules={NOISE_URI: module},
    )
    return entry, module, spec


class HocusScriptExpanderTests(unittest.TestCase):
    def test_validated_dag_adapters_compose_end_to_end_without_io(self) -> None:
        envelope = _resolved_envelope("Empty")
        entry_source = '''hocus 0.2; import { Empty } from "./empty.hocus";
          graph g { target "/obj/g"; use empty @id("empty") = Empty(); node n: "box" {} output = n; }'''
        entry = parse_syntax(entry_source, RESOLVED_ENTRY_URI)
        declaration = entry.imports[0]
        exact_imports = (ResolvedImport(
            declaration.specifier, declaration.imported_name, declaration.local_name,
            envelope.envelope.uri, declaration.span,
        ),)
        dag = _resolved_dag(
            [envelope], roots=(envelope,), entry=entry_source.encode("utf-8"),
            entry_imports=exact_imports, entry_uri=RESOLVED_ENTRY_URI,
        )
        self.assertEqual(dag.entry_source, entry_source.encode("utf-8"))
        self.assertEqual(dag.entry_source_digest, module_source_digest(dag.entry_source))
        self.assertEqual(dag.entry_syntax, entry)
        self.assertEqual(dag.entry_imports, exact_imports)
        spec = expand_resolved_module_dag(dag)
        self.assertEqual(graph_spec_from_dict(spec.to_dict()).to_dict(), spec.to_dict())
        different = parse_syntax('hocus 0.2; graph Other { target "/obj/other"; }', RESOLVED_ENTRY_URI)
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(dag, entry_syntax=different))
        self.assertEqual(captured.exception.code, "HOCUS460")
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(
                dag, entry_source=b'hocus 0.2; graph Other { target "/obj/other"; }',
            ))
        self.assertEqual(captured.exception.code, "HOCUS460")
        with self.assertRaises(TypeError):
            expand_module_graph(
                entry_source=entry_source.encode("utf-8"), entry_uri=RESOLVED_ENTRY_URI,
                entry_imports=resolved_import_map(exact_imports),
                modules=resolved_units_from_dag(dag), entry_source_digest=DIGEST,
            )

    def test_handoff_seal_rejects_entry_and_nested_target_swaps(self) -> None:
        box = _shape_fixture("boxshape", "box")
        sphere = _shape_fixture("sphereshape", "sphere")
        entry_source = '''hocus 0.2;
          import { Shape as A } from "modules/boxshape.hocus";
          import { Shape as B } from "modules/sphereshape.hocus";
          graph g {
            target "/obj/g";
            use a @id("a") = A();
            use b @id("b") = B();
            node out: "null" { input[0] = a.result; }
            output = out;
          }'''
        syntax = parse_syntax(entry_source, RESOLVED_ENTRY_URI)
        imports = (
            ResolvedImport(
                syntax.imports[0].specifier, syntax.imports[0].imported_name,
                syntax.imports[0].local_name, box.lock.module_uri, syntax.imports[0].span,
            ),
            ResolvedImport(
                syntax.imports[1].specifier, syntax.imports[1].imported_name,
                syntax.imports[1].local_name, sphere.lock.module_uri, syntax.imports[1].span,
            ),
        )
        dag = _resolved_dag(
            (box, sphere), roots=(box, sphere), entry=entry_source.encode("utf-8"),
            entry_imports=imports, entry_uri=RESOLVED_ENTRY_URI,
        )
        original = expand_resolved_module_dag(dag)
        self.assertEqual([node.type_name for node in original.nodes[:2]], ["box", "sphere"])

        swapped_entry_imports = (
            replace(imports[0], target_uri=sphere.lock.module_uri), imports[1],
        )
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(dag, entry_imports=swapped_entry_imports))
        self.assertEqual(captured.exception.code, "HOCUS460")
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(dag, handoff_digest=DIGEST))
        self.assertEqual(captured.exception.code, "HOCUS460")

        alpha, zulu = _resolved_envelope("Alpha"), _resolved_envelope("Zulu")
        root = _resolved_envelope("Root", (alpha, zulu))
        nested_dag = _resolved_dag((root, zulu, alpha), roots=(root,))
        root_index = next(
            index for index, record in enumerate(nested_dag.ordered_modules)
            if record.dependency.uri == root.lock.module_uri
        )
        root_record = nested_dag.ordered_modules[root_index]
        nested_imports = (
            replace(root_record.imports[0], target_uri=root_record.imports[1].target_uri),
            *root_record.imports[1:],
        )
        records = list(nested_dag.ordered_modules)
        records[root_index] = replace(root_record, imports=nested_imports)
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(nested_dag, ordered_modules=tuple(records)))
        self.assertEqual(captured.exception.code, "HOCUS460")

    def test_handoff_seal_binds_resolved_limits_and_module_projection(self) -> None:
        two_node_source = b'''hocus 0.2; graph Main {
          target "/obj/g";
          node a: "box" {}
          node b: "null" { input[0] = a.output[0]; }
        }'''
        limited = _resolved_dag(
            (), roots=(), entry=two_node_source, entry_imports=(),
            limits=ResolvedModuleLimits(expanded_nodes=1),
        )
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(limited)
        self.assertEqual(captured.exception.code, "HOCUS464")

        widened = limited.resolved_module_set
        widened["limits"]["expandedNodes"] = 10_000
        widened_json = json.dumps(widened, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(limited, resolved_module_set_json=widened_json))
        self.assertEqual(captured.exception.code, "HOCUS460")

        module = _resolved_envelope("Empty")
        projected = _resolved_dag((module,), roots=(module,))
        substituted = projected.resolved_module_set
        substituted["modules"][0]["sourceDigest"] = DIGEST
        substituted_json = json.dumps(
            substituted, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        )
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_resolved_module_dag(replace(projected, resolved_module_set_json=substituted_json))
        self.assertEqual(captured.exception.code, "HOCUS460")
    def test_expands_to_strict_round_trippable_graphspec_03(self) -> None:
        _, module, spec = _expand()
        encoded = spec.to_dict()
        self.assertEqual(encoded["graphSpecVersion"], "0.3")
        self.assertEqual(len(encoded["nodes"]), 3)
        self.assertEqual(graph_spec_from_dict(encoded).to_dict(), encoded)
        _validate_graph_spec(
            encoded, graph_spec_version="0.3",
            module_dependencies={NOISE_URI: {
                "uri": NOISE_URI, "moduleName": "Noise", "sourceDigest": DIGEST,
            }},
            entry_source_uri=ENTRY_URI,
            module_limits={
                "expandedNodes": 10_000, "sourceMapEntries": 100_000,
                "instances": 4096, "instanceDepth": 64, "aggregateCodeBytes": 4_194_304,
            },
        )
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            return
        schemas = [
            json.loads((ROOT / "docs" / "schemas" / name).read_text("utf-8"))
            for name in ("expansion-map-v1.schema.json", "graph-spec-v0.3.schema.json")
        ]
        registry = Registry().with_resources((item["$id"], Resource.from_contents(item)) for item in schemas)
        Draft202012Validator(schemas[1], registry=registry).validate(encoded)

    def test_exact_types_do_not_convert_int_to_float(self) -> None:
        with self.assertRaises(ModuleExpansionError) as captured:
            _expand(_graph(scale="2"))
        self.assertEqual(captured.exception.code, "HOCUS475")
        self.assertEqual(captured.exception.details, {"expected": "float", "actual": "int"})

    def test_provenance_and_limit_caps_fail_before_expansion(self) -> None:
        entry = parse_syntax(_graph(), ENTRY_URI)
        resolved = _resolved(entry.imports[0], NOISE_URI)
        forged = ResolvedModuleUnit(NOISE_URI, "sha256:" + "A" * 64, parse_syntax(NOISE, NOISE_URI), {})
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_module_graph(
                entry_source=_graph().encode("utf-8"), entry_uri=ENTRY_URI,
                entry_imports={"StudioNoise": resolved}, modules={NOISE_URI: forged},
            )
        self.assertEqual(captured.exception.code, "HOCUS460")
        module = _module(NOISE, NOISE_URI)
        forged_import = _resolved(entry.imports[0], NOISE_URI)
        forged_import = _Import(
            "./forged.hocus", forged_import.imported_name, forged_import.local_name,
            forged_import.target_uri, forged_import.span,
        )
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_module_graph(
                entry_source=_graph().encode("utf-8"), entry_uri=ENTRY_URI,
                entry_imports={"StudioNoise": forged_import}, modules={NOISE_URI: module},
            )
        self.assertEqual(captured.exception.code, "HOCUS463")
        for bad_uri in (
            "hocus-project://city/../asset.hocus",
            "hocus-project://city/asset",
        ):
            with self.subTest(bad_uri=bad_uri), self.assertRaises(ModuleExpansionError) as captured:
                expand_module_graph(
                    entry_source=_graph().encode("utf-8"), entry_uri=bad_uri,
                    entry_imports={"StudioNoise": resolved}, modules={NOISE_URI: module},
                )
            self.assertEqual(captured.exception.code, "HOCUS460")
        bad_module_uri = "hocus-project://city/../noise.hocus"
        bad_unit = ResolvedModuleUnit(
            bad_module_uri, DIGEST, parse_syntax(NOISE, bad_module_uri), {},
        )
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_module_graph(
                entry_source=_graph().encode("utf-8"), entry_uri=ENTRY_URI,
                entry_imports={"StudioNoise": _resolved(entry.imports[0], bad_module_uri)},
                modules={bad_module_uri: bad_unit},
            )
        self.assertEqual(captured.exception.code, "HOCUS460")
        with self.assertRaises(ValueError):
            ExpansionLimits(expanded_nodes=10_001)
        with self.assertRaises(ValueError):
            ExpansionLimits(instances=True)

    def test_use_symbol_rename_does_not_change_expanded_identity(self) -> None:
        first = _expand(_graph("noise"))[2]
        second = _expand(_graph("renamed"))[2]
        self.assertEqual(
            [node.explicit_id for node in first.nodes],
            [node.explicit_id for node in second.nodes],
        )
        self.assertEqual([node.symbol for node in first.nodes], [node.symbol for node in second.nodes])

    def test_duplicate_effective_node_seed_fails_closed(self) -> None:
        source = '''hocus 0.2; graph asset {
          target "/obj/asset";
          node first @id("same"): "box" {}
          node same: "null" {}
        }'''
        entry = parse_syntax(source, ENTRY_URI)
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_module_graph(
                entry_source=source.encode("utf-8"), entry_uri=ENTRY_URI,
                entry_imports={}, modules={},
            )
        self.assertEqual(captured.exception.code, "HOCUS473")

    def test_graph_namespace_and_node_shape_are_validated_before_output(self) -> None:
        cases = (
            '''hocus 0.2; graph g { target "/obj/g"; existing same = "/obj/g/same"; node same: "box" {} }''',
            '''hocus 0.2; graph g { target "/obj/g"; node n: "box" { input[0] = n.output[0]; input[0] = n.output[0]; } }''',
            '''hocus 0.2; graph g { target "/obj/g"; node n: "box" { x = 1; x = 2; } }''',
            '''hocus 0.2; graph g { node n: "box" {} }''',
        )
        for source in cases:
            entry = parse_syntax(source, ENTRY_URI)
            with self.subTest(source=source), self.assertRaises(ModuleExpansionError):
                expand_module_graph(
                    entry_source=source.encode("utf-8"), entry_uri=ENTRY_URI,
                    entry_imports={}, modules={},
                )

    def test_import_cycles_limits_and_cancellation_fail_closed(self) -> None:
        a_uri = "hocus-project://city/a.hocus"
        b_uri = "hocus-project://city/b.hocus"
        a_syntax = parse_syntax('''hocus 0.2; import { B } from "./b.hocus";
          module A() exports () { use b @id("b") = B(); }''', a_uri)
        b_syntax = parse_syntax('''hocus 0.2; import { A } from "./a.hocus";
          module B() exports () { use a @id("a") = A(); }''', b_uri)
        modules = {
            a_uri: ResolvedModuleUnit(a_uri, DIGEST, a_syntax, {"B": _resolved(a_syntax.imports[0], b_uri)}),
            b_uri: ResolvedModuleUnit(b_uri, DIGEST, b_syntax, {"A": _resolved(b_syntax.imports[0], a_uri)}),
        }
        with self.assertRaises(ModuleExpansionError) as captured:
            validate_module_interfaces(modules)
        self.assertEqual(captured.exception.code, "HOCUS467")
        # Empty interface sets have no checkpoint; entry expansion always checks cancellation.
        entry_source = 'hocus 0.2; graph g { target "/obj/g"; }'
        entry = parse_syntax(entry_source, ENTRY_URI)
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_module_graph(
                entry_source=entry_source.encode("utf-8"), entry_uri=ENTRY_URI,
                entry_imports={}, modules={}, cancellation=lambda: True,
            )
        self.assertEqual(captured.exception.code, "HOCUS499")
        for callback in (lambda: 1, lambda: (_ for _ in ()).throw(RuntimeError("secret"))):
            with self.subTest(callback=callback), self.assertRaises(ModuleExpansionError) as captured:
                expand_module_graph(
                    entry_source=entry_source.encode("utf-8"), entry_uri=ENTRY_URI,
                    entry_imports={}, modules={}, cancellation=callback,
                )
            self.assertEqual(captured.exception.code, "HOCUS499")
            self.assertNotIn("secret", captured.exception.message)

    def test_nested_forwarded_argument_keeps_outer_callsite_origin(self) -> None:
        leaf_uri = "hocus-project://city/leaf.hocus"
        wrap_uri = "hocus-project://city/wrap.hocus"
        leaf = _module('''hocus 0.2; module Leaf(scale: float) exports (result: node_output) {
          node n: "mountain" { height = param.scale; }
          export result = n.output[0];
        }''', leaf_uri)
        wrap_syntax = parse_syntax('''hocus 0.2; import { Leaf } from "./leaf.hocus";
          module Wrap(scale: float) exports (result: node_output) {
            use inner @id("inner") = Leaf(scale = param.scale);
            export result = inner.result;
          }''', wrap_uri)
        wrap = ResolvedModuleUnit(
            wrap_uri, DIGEST, wrap_syntax,
            {"Leaf": _resolved(wrap_syntax.imports[0], leaf_uri)},
        )
        entry_source = '''hocus 0.2; import { Wrap } from "./wrap.hocus";
          graph g { target "/obj/g"; use w @id("w") = Wrap(scale = 2.0); }'''
        entry = parse_syntax(entry_source, ENTRY_URI)
        spec = expand_module_graph(
            entry_source=entry_source.encode("utf-8"), entry_uri=ENTRY_URI,
            entry_imports={"Wrap": _resolved(entry.imports[0], wrap_uri)},
            modules={leaf_uri: leaf, wrap_uri: wrap},
        )
        mapping = next(item for item in spec.expansion_map.mappings if item.generated_pointer.endswith("/parms/0"))
        outer_argument = entry.graph.statements[1].arguments[0].value.span
        self.assertEqual(mapping.primary_span, outer_argument)
        self.assertEqual(len(mapping.related_origins), 2)
        self.assertEqual(len(next(stack for stack in spec.expansion_map.stacks if stack.stack_id == mapping.stack_id).frames), 2)

    def test_forwarded_provenance_over_schema_bound_fails_closed(self) -> None:
        modules = {}
        previous_uri = None
        for index in range(17):
            uri = f"hocus-project://city/m{index}.hocus"
            if index == 0:
                source = '''hocus 0.2; module M0(p: float) exports (result: node_output) {
                  node n: "mountain" { height = param.p; }
                  export result = n.output[0];
                }'''
                unit = _module(source, uri)
            else:
                source = f'''hocus 0.2; import {{ M{index - 1} }} from "./m{index - 1}.hocus";
                  module M{index}(p: float) exports (result: node_output) {{
                    use inner @id("inner-{index}") = M{index - 1}(p = param.p);
                    export result = inner.result;
                  }}'''
                syntax = parse_syntax(source, uri)
                unit = ResolvedModuleUnit(
                    uri, DIGEST, syntax,
                    {f"M{index - 1}": _resolved(syntax.imports[0], previous_uri)},
                )
            modules[uri] = unit
            previous_uri = uri
        entry_source = '''hocus 0.2; import { M16 } from "./m16.hocus";
          graph g { target "/obj/g"; use root @id("root") = M16(p = 1.0); }'''
        entry = parse_syntax(entry_source, ENTRY_URI)
        with self.assertRaises(ModuleExpansionError) as captured:
            expand_module_graph(
                entry_source=entry_source.encode("utf-8"), entry_uri=ENTRY_URI,
                entry_imports={"M16": _resolved(entry.imports[0], previous_uri)},
                modules=modules,
            )
        self.assertEqual(captured.exception.code, "HOCUS464")


if __name__ == "__main__":
    unittest.main()
