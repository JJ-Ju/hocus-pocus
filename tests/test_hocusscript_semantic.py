from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import CompiledBundle, compile_source, decode_compiled_bundle
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    MenuItem,
    OperatorDefinition,
    ParameterDefinition,
    ParmRange,
)
from hocuspocus.hocusscript.semantic import CatalogConstraint, ExternalNodeBinding, resolve_graph


def _parm(
    token: str, value_type: str, default, *, tuple_size: int = 1, tuple_names=(), menu=(),
    code_surface: str = "none", assignable: bool = True, range=None,
) -> ParameterDefinition:
    return ParameterDefinition(
        token, token.title(), value_type, tuple_size, tuple(tuple_names), default, range,
        tuple(menu), {}, code_surface, assignable,
    )


def _operator(
    qualified_name: str, *, name: str, version: str | None = None, aliases=(), parameters=(),
    inputs=(), outputs=(), category: str = "Sop",
) -> OperatorDefinition:
    return OperatorDefinition(
        qualified_name, name, "acme" if "::" in qualified_name else None, version, category,
        tuple(aliases), DefinitionSource("builtin"), tuple(parameters), tuple(inputs), tuple(outputs),
    )


OUT0 = ConnectorDefinition(0, "geometry", "Geometry", data_types=("geometry",))
OUT1 = ConnectorDefinition(1, "points", "Points", data_types=("geometry",))
IN0 = ConnectorDefinition(0, "source", "Source", data_types=("geometry",))


def _provider(*operators: OperatorDefinition):
    return FakeCatalogProvider.create(
        categories=[CategoryDefinition("Sop", "SOP", "sop")], operators=operators,
    )


def _compile(body: str):
    result = compile_source(f'hocus 0.1; graph demo {{ target "/obj/geo1"; category Sop; {body} }}', "semantic.hocus")
    assert result.valid, [item.to_dict() for item in result.diagnostics]
    assert result.graph_spec is not None
    return result.graph_spec


class HocusScriptSemanticTests(unittest.TestCase):
    def test_exact_alias_and_unqualified_resolution_are_deterministic(self) -> None:
        provider = _provider(
            _operator("acme::source::1.0", name="source", version="1.0", aliases=("stable_source",), outputs=(OUT0,)),
            _operator("sink", name="sink", inputs=(IN0,), outputs=(OUT0,)),
        )
        graph = _compile('node a: "acme::source::1.0" {} node b: stable_source {} node c: sink {}')
        result = resolve_graph(graph, provider)
        self.assertTrue(result.valid, [item.to_dict() for item in result.diagnostics])
        self.assertEqual(
            [item.qualified_name for item in result.operator_selections],
            ["acme::source::1.0", "acme::source::1.0", "sink"],
        )
        self.assertEqual(result.to_dict(), resolve_graph(graph, provider).to_dict())

    def test_no_silent_version_upgrade_and_ambiguity_fixes_use_type_span(self) -> None:
        provider = _provider(
            _operator("acme::source::1.0", name="source", version="1.0"),
            _operator("acme::source::2.0", name="source", version="2.0"),
        )
        missing_source = 'hocus 0.1; graph demo { target "/obj/geo1"; category Sop; node a: "acme::source::1.5" {} }'
        compiled = compile_source(missing_source, "semantic.hocus")
        assert compiled.graph_spec is not None
        missing = resolve_graph(compiled.graph_spec, provider)
        self.assertEqual([item.code for item in missing.diagnostics], ["HOCUS624"])
        diagnostic = missing.diagnostics[0]
        self.assertEqual(diagnostic.span.start.offset, missing_source.index('"acme::source::1.5"'))
        self.assertEqual(diagnostic.json_pointer, "/nodes/0/typeName")
        self.assertEqual(diagnostic.to_dict()["jsonPointer"], "/nodes/0/typeName")
        self.assertEqual(diagnostic.fixes[0]["edits"][0]["newText"], '"acme::source::1.0"')

        ambiguous = resolve_graph(_compile("node a: source {}"), provider)
        self.assertEqual([item.code for item in ambiguous.diagnostics], ["HOCUS623"])
        self.assertEqual(ambiguous.diagnostics[0].details["candidates"],
                         ["acme::source::1.0", "acme::source::2.0"])

    def test_exact_houdini_type_name_is_disambiguated_by_category(self) -> None:
        provider = FakeCatalogProvider.create(
            categories=(CategoryDefinition("Sop", "SOP", "sop"), CategoryDefinition("Object", "OBJ", "object")),
            operators=(
                _operator("null", name="null", category="Sop"),
                _operator("null", name="null", category="Object"),
            ),
        )
        constrained = resolve_graph(_compile("node n: null {}"), provider)
        self.assertTrue(constrained.valid)
        self.assertEqual(constrained.operator_selections[0].category, "Sop")

        unconstrained_source = 'hocus 0.1; graph demo { target "/obj"; node n: null {} }'
        compiled = compile_source(unconstrained_source, "semantic.hocus")
        assert compiled.graph_spec is not None
        ambiguous = resolve_graph(compiled.graph_spec, provider)
        self.assertEqual([item.code for item in ambiguous.diagnostics], ["HOCUS623"])
        self.assertEqual(ambiguous.diagnostics[0].details["candidates"], ["Object/null", "Sop/null"])
        selected_source = 'hocus 0.1; graph demo { target "/obj"; node n: "Object/null" {} }'
        selected_compile = compile_source(selected_source, "semantic.hocus")
        assert selected_compile.graph_spec is not None
        selected = resolve_graph(selected_compile.graph_spec, provider)
        self.assertTrue(selected.valid)
        self.assertEqual(selected.operator_selections[0].category, "Object")
        self.assertEqual(selected.operator_selections[0].qualified_name, "null")

    def test_scalar_tuple_component_menu_code_and_capabilities(self) -> None:
        parameters = (
            _parm("enabled", "bool", False),
            _parm("count", "int", 1, range=ParmRange(0, 10)),
            _parm("scale", "float", (1.0, 1.0, 1.0), tuple_size=3, tuple_names=("sx", "sy", "sz")),
            _parm("mode", "menu", "fast", menu=(MenuItem("fast", "Fast Mode"), MenuItem("safe", "Safe Mode"))),
            _parm("snippet", "code", "", code_surface="vex"),
        )
        provider = _provider(_operator("processor", name="processor", parameters=parameters, outputs=(OUT0,)))
        graph = _compile('''node work: processor {
          enabled = true;
          count = 4;
          scale = [1, 2.0, 3];
          mode = "fast";
          snippet = vex`@P *= 2;`;
        }''')
        result = resolve_graph(graph, provider)
        self.assertTrue(result.valid, [item.to_dict() for item in result.diagnostics])
        self.assertEqual(result.required_capabilities, ("edit_scene", "run_code"))
        by_token = {item.authored_token: item for item in result.parameter_selections}
        self.assertEqual(by_token["scale"].conversion, "int_to_float")
        self.assertEqual(by_token["mode"].menu_token, "fast")
        self.assertEqual(by_token["snippet"].code_surface, "vex")

        components = resolve_graph(_compile("node work: processor { sx = 2; sy = 3; }"), provider)
        self.assertTrue(components.valid)
        self.assertEqual([item.component_index for item in components.parameter_selections], [0, 1])

    def test_parameter_rejections_are_precise_and_never_coerce(self) -> None:
        parameters = (
            _parm("count", "int", 1, range=ParmRange(0, 10)),
            _parm("scale", "float", (1.0, 1.0, 1.0), tuple_size=3, tuple_names=("sx", "sy", "sz")),
            _parm("mode", "menu", "fast", menu=(MenuItem("fast", "Fast Mode"),)),
            _parm("snippet", "code", "", code_surface="vex"),
            _parm("press", "button", None, assignable=False),
        )
        provider = _provider(_operator("processor", name="processor", parameters=parameters))
        cases = (
            ('node n: processor { count = 1.5; }', "HOCUS633"),
            ('node n: processor { count = 11; }', "HOCUS637"),
            ('node n: processor { scale = 1; }', "HOCUS634"),
            ('node n: processor { scale = [1, 2]; }', "HOCUS634"),
            ('node n: processor { mode = "Fast Mode"; }', "HOCUS636"),
            ('node n: processor { snippet = "text"; }', "HOCUS638"),
            ('node n: processor { snippet = python`print(1)`; }', "HOCUS639"),
            ('node n: processor { press = true; }', "HOCUS632"),
            ('node n: processor { scale = [1, 2, 3]; sx = 4; }', "HOCUS631"),
        )
        for source, code in cases:
            with self.subTest(code=code, source=source):
                result = resolve_graph(_compile(source), provider)
                self.assertIn(code, {item.code for item in result.diagnostics})
                self.assertFalse(result.valid)
        label = resolve_graph(_compile('node n: processor { mode = "Fast Mode"; }'), provider).diagnostics[0]
        self.assertEqual(label.fixes[0]["edits"][0]["newText"], '"fast"')

    def test_indexed_named_multi_output_ports_and_external_defer(self) -> None:
        source = _operator("source", name="source", outputs=(OUT0, OUT1))
        sink = _operator("sink", name="sink", inputs=(IN0,), outputs=(OUT0,))
        provider = _provider(source, sink)
        graph = _compile("node a: source {} node b: sink { input[0] = a.output[1]; }")
        resolved = resolve_graph(graph, provider)
        self.assertTrue(resolved.valid)
        self.assertEqual(resolved.connection_selections[0].input_name, "source")
        self.assertEqual(resolved.connection_selections[0].output_name, "points")
        self.assertEqual(resolved.connection_selections[0].output_index, 1)

        invalid = resolve_graph(_compile("node a: source {} node b: sink { input[2] = a.output[9]; }"), provider)
        self.assertEqual([item.code for item in invalid.diagnostics], ["HOCUS640", "HOCUS641"])

        external_graph = _compile('existing live = "/obj/geo1/live"; node b: sink { input[0] = live.output[1]; }')
        deferred = resolve_graph(external_graph, provider)
        self.assertTrue(deferred.valid)
        self.assertFalse(deferred.ready_for_document_lowering)
        self.assertEqual([item.code for item in deferred.diagnostics], ["HOCUS643"])
        bound = resolve_graph(external_graph, provider, external_bindings={
            "live": ExternalNodeBinding("source", provider.catalog.fingerprint),
        })
        self.assertTrue(bound.ready_for_document_lowering)
        self.assertEqual(bound.connection_selections[0].output_name, "points")

        variadic_sink = _operator(
            "merge", name="merge",
            inputs=(ConnectorDefinition(None, "variadic", "Inputs", "many", ("geometry",)),),
            outputs=(OUT0,),
        )
        variadic_provider = _provider(source, variadic_sink)
        variadic_graph = _compile("node a: source {} node b: merge { input[37] = a; }")
        variadic = resolve_graph(variadic_graph, variadic_provider)
        self.assertTrue(variadic.valid, [item.to_dict() for item in variadic.diagnostics])
        self.assertEqual(variadic.connection_selections[0].input_index, 37)

    def test_port_type_incompatibility_and_catalog_drift_are_fatal(self) -> None:
        output = ConnectorDefinition(0, "text", "Text", data_types=("string",))
        provider = _provider(_operator("source", name="source", outputs=(output,)),
                             _operator("sink", name="sink", inputs=(IN0,)))
        graph = _compile("node a: source {} node b: sink { input[0] = a; }")
        incompatible = resolve_graph(graph, provider)
        self.assertEqual([item.code for item in incompatible.diagnostics], ["HOCUS642"])
        drift = resolve_graph(graph, provider, constraint=CatalogConstraint("sha256:" + "0" * 64))
        self.assertIn("HOCUS605", {item.code for item in drift.diagnostics})
        self.assertFalse(drift.valid)

    def test_nested_token_spans_round_trip_through_graphspec_and_schema(self) -> None:
        source = 'hocus 0.1; graph demo { target "/obj/geo1"; existing live = "/obj/geo1/live"; node src: "source" {} node out: "sink" { input[2] = src.output[1]; value = 3; } }'
        compiled = compile_source(source, "spans.hocus")
        assert compiled.graph_spec is not None
        payload = compiled.graph_spec.to_dict()
        node = payload["nodes"][1]
        external = payload["externalNodes"][0]
        self.assertEqual(external["fieldSpans"]["path"]["start"]["offset"], source.index('"/obj/geo1/live"'))
        self.assertEqual(node["fieldSpans"]["typeName"]["start"]["offset"], source.index('"sink"'))
        self.assertEqual(node["parms"][0]["fieldSpans"]["name"]["start"]["offset"], source.index("value"))
        self.assertEqual(node["inputs"][0]["fieldSpans"]["index"]["start"]["offset"], source.index("2"))
        self.assertEqual(node["inputs"][0]["source"]["fieldSpans"]["outputIndex"]["start"]["offset"],
                         source.index("1", source.index("output")))
        schema = json.loads((ROOT / "docs" / "schemas" / "graph-spec-v0.2.schema.json").read_text(encoding="utf-8"))
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return
        Draft202012Validator(schema).validate(payload)

    def test_bundle_decoder_accepts_legacy_nested_records_without_field_spans(self) -> None:
        compiled = compile_source('hocus 0.1; graph demo { target "/obj/geo1"; node src: "source" { value = 1; } }', "legacy.hocus")
        payload = CompiledBundle.from_result(compiled).to_dict()

        def remove_nested(value, *, root=False):
            if isinstance(value, dict):
                if not root:
                    value.pop("fieldSpans", None)
                for item in value.values():
                    remove_nested(item)
            elif isinstance(value, list):
                for item in value:
                    remove_nested(item)

        remove_nested(payload["graphSpec"], root=True)
        unsigned = dict(payload)
        unsigned.pop("bundleDigest")
        canonical = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        payload["bundleDigest"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        decoded = decode_compiled_bundle(payload)
        self.assertEqual(decoded.digest, payload["bundleDigest"])


if __name__ == "__main__":
    unittest.main()
