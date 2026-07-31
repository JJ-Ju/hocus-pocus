from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.hocusscript import (
    compile_source,
    format_syntax,
    parse_syntax,
    validate_control_catalog_program,
)
from hocuspocus.hocusscript.catalog import CategoryDefinition, FakeCatalogProvider
from hocuspocus.hocusscript.control_semantic import ControlExpansionLimits, validate_control_program
from hocuspocus.hocusscript.expander import ModuleExpansionError, ResolvedModuleUnit
from hocuspocus.live.context import OperationCancelledError, RequestContext
from hocuspocus.live.operations import LiveOperations
from tests.test_hocusscript_authoring_scenarios import (
    _control_bundle as _h5_control_bundle,
    _module_bundle as _h5_module_bundle,
    _provider as _h5_provider,
    _tampered_control_bundle as _tampered_h5_bundle,
)
from tests.hocusscript_hs7_helpers import assert_heuristic_tuple_evidence_rejected, assert_tagged_value_pipeline, assert_value_plan_apply, assert_value_preview_bindings, value_bundle
from tests.hocusscript_control_runtime_helpers import (
    _EditorOperations,
    _PlanOperations,
    _PreviewOperations,
    _apply_arguments,
    _bundle,
    _catalog_provider,
    _expand,
    _h5_plan_bundle,
    _identity_symbols,
)


class HocusScriptControlScenarios(unittest.TestCase):
    def test_mcp_editor_surface_compiles_and_formats_without_scene_access(self) -> None:
        operations = _EditorOperations()
        compiled = operations.document_compile_source(
            {
                "source_name": "demo.hocus",
                "source": 'hocus 0.1; graph demo { target "/obj/geo1"; }',
            },
            RequestContext(),
        )["structuredContent"]
        formatted = operations.document_format_source(
            {"source": 'hocus 0.1; graph demo { target "/obj/geo1"; }'},
            RequestContext(),
        )["structuredContent"]

        self.assertTrue(compiled["valid"])
        self.assertFalse(compiled["readyForApply"])
        self.assertTrue(formatted["valid"])
        self.assertIn("graph demo {\n", formatted["formattedSource"])

        tools, resources = ToolRegistry(), ResourceRegistry()
        LiveOperations.__new__(LiveOperations).register(tools, resources)
        expected_metadata = {
            "document.compile_source": (
                ("source.project.build", "document.apply_plan", "never rereads this source"),
                ("observe",),
                True,
            ),
            "document.format_source": ((), ("observe",), True),
            "document.export_source": (
                (
                    "flat direct-child",
                    "structurally recompiled",
                    "exact-catalog semantic and connector validation",
                    "neither proves network reconstruction nor publishes",
                ),
                ("observe",),
                True,
            ),
            "document.preview_bundle": (
                (
                    "authenticated carrier semantics and provenance pins", "flat Bundle 0.2", "module Bundle 0.3",
                    "control Bundle 0.4", "value Bundle 0.5", "catalog/HDA selections",
                    "candidate document", "destructive summary", "without mutating Houdini or reading DSL project files",
                ),
                ("observe",),
                True,
            ),
            "document.plan_bundle": (
                (
                    "Rerun the exact-version live validation", "flat Bundle 0.2", "module Bundle 0.3",
                    "control Bundle 0.4", "value Bundle 0.5", "carrier semantics and provenance pins",
                    "immutable apply plan",
                ),
                ("observe",),
                True,
            ),
            "document.apply_plan": (
                (
                    "immutable plan identity",
                    "drift gates",
                    "without rereading or recompiling HocusScript source",
                ),
                ("edit_scene",),
                False,
            ),
        }
        for name, (fragments, capabilities, read_only) in expected_metadata.items():
            definition = tools.get(name)
            self.assertIsNotNone(definition)
            self.assertEqual(definition.required_capabilities, capabilities)
            self.assertEqual(
                bool(definition.annotations.get("readOnlyHint", False)),
                read_only,
            )
            self.assertTrue(
                all(fragment in definition.description for fragment in fragments)
            )

    def test_preview_produces_a_read_only_plan_and_rejects_catalog_drift(self) -> None:
        operations = _PreviewOperations()
        payload = operations.document_preview_bundle(
            {"bundle": _bundle().to_dict()}, RequestContext()
        )["structuredContent"]

        self.assertTrue(payload["valid"])
        self.assertTrue(payload["readyForPlan"])
        self.assertFalse(payload["readyForApply"])
        self.assertEqual(operations.asserted_root_path, "/obj/geo1")
        self.assertTrue(payload["preview"]["candidatePlan"]["operations"])

        empty_catalog = FakeCatalogProvider.create(
            categories=(CategoryDefinition("Sop", "SOP", "sop"),),
            operators=(),
        ).catalog
        blocked = _PreviewOperations(catalog=empty_catalog).document_preview_bundle(
            {"bundle": _bundle().to_dict()}, RequestContext()
        )["structuredContent"]
        self.assertFalse(blocked["valid"])
        self.assertFalse(blocked["readyForPlan"])
        self.assertEqual(blocked["diagnostics"][0]["code"], "HOCUS720")
        for malformed_value in ([], "hocus-compiled-bundle-v9.9"):
            malformed_version = _bundle().to_dict()
            malformed_version["bundleVersion"] = malformed_value
            with self.assertRaises(JsonRpcError) as malformed:
                operations.document_preview_bundle(
                    {"bundle": malformed_version},
                    RequestContext(),
                )
            self.assertEqual(
                malformed.exception.data["diagnosticCode"], "HOCUS700"
            )

        control = _tampered_h5_bundle(
            _tampered_h5_bundle(
                _h5_control_bundle(),
                ("semanticResolution", "requiredCapabilities"),
                ["edit_scene", "run_code"],
            ),
            ("requiredCapabilities",),
            ["edit_scene", "run_code"],
        )
        value, value_provider = value_bundle(_h5_provider())
        for carrier, provider in ((_h5_module_bundle(), _h5_provider()), (control, _h5_provider()), (value, value_provider)):
            with self.subTest(live_bundle=carrier["bundleVersion"]):
                operations = _PreviewOperations(catalog=provider.catalog)
                target = carrier["graphSpec"]["target"]
                operations.baseline["documentId"] = f"network:{target}"
                operations.baseline["rootPath"] = target
                operations.baseline["nodes"][0].update({
                    "name": target.rsplit("/", 1)[-1],
                    "path": target,
                    "parentPath": target.rsplit("/", 1)[0],
                })
                preview = operations.document_preview_bundle(
                    {"bundle": carrier},
                    RequestContext(),
                )["structuredContent"]
                self.assertTrue(preview["valid"], preview["diagnostics"])
                candidate = preview["preview"]["candidatePlan"]
                self.assertEqual(candidate["bundleVersion"], carrier["bundleVersion"])
                self.assertEqual(candidate["languageVersion"], carrier["languageVersion"])
                self.assertEqual(candidate["resolverPolicyDigest"], carrier["resolvedModuleSet"]["resolverPolicyDigest"])
                self.assertEqual(operations.catalog_request, carrier["graphSpecVersion"])
                self.assertEqual(
                    candidate["expansionMapDigest"],
                    carrier["sourceMaps"]["expansionMapDigest"],
                )
                self.assertEqual(
                    candidate["requiredCapabilities"],
                    carrier["requiredCapabilities"],
                )
                if carrier["bundleVersion"] == "0.5":
                    assert_value_preview_bindings(self, preview)
                if carrier["bundleVersion"] == "0.4":
                    lowered = [
                        node
                        for node in preview["preview"]["document"]["nodes"]
                        if (
                            (node.get("metadata") or {}).get("hocus") or {}
                        ).get("symbol", "").startswith("__hocus_")
                    ]
                    self.assertTrue(
                        all(node["name"].startswith("hocus_generated_") for node in lowered)
                    )
                    self.assertTrue(
                        all(
                            node["metadata"]["hocus"]["symbol"].startswith("__hocus_")
                            for node in lowered
                        )
                    )
                    self.assertEqual(len(lowered), len(carrier["graphSpec"]["nodes"]))
    def test_plan_apply_is_guarded_durable_and_idempotent(self) -> None:
        assert_tagged_value_pipeline(self, _PreviewOperations, RequestContext, _h5_provider())
        assert_value_plan_apply(self, _PlanOperations, RequestContext, _apply_arguments, _h5_provider())
        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "graph.sqlite3")
            context = RequestContext(permissions=("edit_scene", "run_code"))
            operations.global_revision += 1
            plan = operations.document_plan_bundle(
                {"bundle": _bundle().to_dict()}, context
            )["structuredContent"]
            self.assertEqual(operations.sync_calls, 2)

            before = copy.deepcopy(operations.baseline)
            invalid = _apply_arguments(plan, "invalid-token")
            invalid["planHash"] = "sha256:" + "0" * 64
            with self.assertRaises(JsonRpcError):
                operations.document_apply_plan(invalid, context)
            self.assertEqual(operations.baseline, before)

            arguments = _apply_arguments(plan, "apply-rocks")
            first = operations.document_apply_plan(arguments, context)["structuredContent"]
            replay = operations.document_apply_plan(arguments, context)["structuredContent"]
            self.assertTrue(first["applied"])
            self.assertTrue(first["verified"])
            self.assertFalse(first["idempotentReplay"])
            self.assertTrue(replay["idempotentReplay"])

        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "drift.sqlite3")
            operations.mutate_on_sync_call = 2
            with self.assertRaises(JsonRpcError) as drift:
                operations.document_plan_bundle(
                    {"bundle": _bundle().to_dict()},
                    RequestContext(permissions=("edit_scene", "run_code")),
                )
            self.assertEqual(drift.exception.data["diagnosticCode"], "HOCUS745")

        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "cancel.sqlite3")
            context = RequestContext(permissions=("edit_scene", "run_code"))
            operations.cancel_context = context
            operations.cancel_on_sync_call = 2
            with self.assertRaises(OperationCancelledError):
                operations.document_plan_bundle(
                    {"bundle": _bundle().to_dict()}, context
                )
            self.assertEqual(operations._documents.apply_plan_stats()["count"], 0)
            self.assertEqual(
                operations._graph_store.stats()["immutablePlanCount"], 0
            )

            operations.cancel_context = RequestContext(
                permissions=("edit_scene", "run_code")
            )
            operations.cancel_on_sync_call = None
            operations.cancel_on_plan_build = 1
            with self.assertRaises(OperationCancelledError):
                operations.document_plan_bundle(
                    {"bundle": _bundle().to_dict()},
                    operations.cancel_context,
                )
            self.assertEqual(operations._documents.apply_plan_stats()["count"], 0)
            self.assertEqual(
                operations._graph_store.stats()["immutablePlanCount"], 0
            )

        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(
                Path(temporary) / "cancel-after-store.sqlite3"
            )
            context = RequestContext(permissions=("edit_scene", "run_code"))
            original_store = operations._graph_store.store_immutable_plan

            def store_then_cancel(*arguments, **keywords):
                result = original_store(*arguments, **keywords)
                context.cancel()
                return result

            operations._graph_store.store_immutable_plan = store_then_cancel
            with self.assertRaises(OperationCancelledError):
                operations.document_plan_bundle(
                    {"bundle": _bundle().to_dict()}, context
                )
            self.assertEqual(operations._documents.apply_plan_stats()["count"], 0)
            self.assertEqual(
                operations._graph_store.stats()["immutablePlanCount"], 0
            )

        carrier = _h5_plan_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "h5-graph.sqlite3")
            operations.catalog = _h5_provider().catalog
            target = carrier["graphSpec"]["target"]
            operations.baseline["documentId"] = f"network:{target}"
            operations.baseline["rootPath"] = target
            operations.baseline["nodes"][0].update({
                "name": target.rsplit("/", 1)[-1],
                "path": target,
                "parentPath": target.rsplit("/", 1)[0],
            })
            _PlanOperations.decode_calls = 0
            context = RequestContext(permissions=("edit_scene", "run_code"))
            plan = operations.document_plan_bundle(
                {"bundle": carrier},
                context,
            )["structuredContent"]
            self.assertEqual(_PlanOperations.decode_calls, 1)
            stored = operations._documents.apply_plan(
                plan["planId"],
                expected_hash=plan["planHash"],
            )
            expected_pins = {
                "bundleVersion": carrier["bundleVersion"],
                "languageVersion": carrier["languageVersion"],
                "resolverPolicyDigest": carrier["resolvedModuleSet"]["resolverPolicyDigest"],
                "expansionMapDigest": carrier["sourceMaps"]["expansionMapDigest"],
            }
            for key, expected in expected_pins.items():
                self.assertEqual(stored[key], expected)
            self.assertEqual(stored["requiredCapabilities"], ["edit_scene", "run_code"])

    def test_failed_apply_rolls_back_the_scene_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            operations = _PlanOperations(Path(temporary) / "graph.sqlite3")
            context = RequestContext(permissions=("edit_scene", "run_code"))
            plan = operations.document_plan_bundle(
                {"bundle": _bundle().to_dict()}, context
            )["structuredContent"]
            before = copy.deepcopy(operations.baseline)
            operations.fail_execution = True

            with self.assertRaises(JsonRpcError) as captured:
                operations.document_apply_plan(_apply_arguments(plan, "failed-apply"), context)

            self.assertEqual(captured.exception.data["diagnosticCode"], "HOCUS755")
            self.assertTrue(captured.exception.data["failure"]["rolledBack"])
            self.assertEqual(operations.baseline, before)

    def test_controls_parse_and_format_as_stable_source(self) -> None:
        source = '''hocus 0.3;
module Repeat(flag: bool = true, count: int = 2) exports (out: int) {
  for series @id("series") (i in range(param.count)) carry (out: int = 0) {
    if choice @id("choice") (param.flag) outputs (out: int) {
      yield out = iter.i;
    } else {
      yield out = carry.out;
    }
    yield out = choice.out;
  }
  export out = series.out;
}
'''
        formatted = format_syntax(parse_syntax(source, "repeat.hocus"))
        self.assertEqual(format_syntax(parse_syntax(formatted, "repeat.hocus")), formatted)
        self.assertIn('for series @id("series")', formatted)
        self.assertIn('if choice @id("choice")', formatted)

        legacy = compile_source(source, "repeat.hocus")
        self.assertFalse(legacy.valid)
        self.assertEqual(legacy.diagnostics[0].code, "HOCUS102")

        with self.assertRaises(ModuleExpansionError) as malformed:
            _expand(
                '''
  if broken @id("broken") (true) outputs (value: int) {
    yield value = 1;
  }
'''
            )
        self.assertEqual(malformed.exception.code, "HOCUS460")

    def test_semantics_validate_the_whole_control_program(self) -> None:
        assert_heuristic_tuple_evidence_rejected(self, _catalog_provider())
        valid = '''hocus 0.3;
graph G {
  target "/obj/g";
  if choice @id("choice") (true) outputs (out: int) {
    yield out = 1;
  } else {
    yield out = 2;
  }
  node result: "null" { value = choice.out; }
}
'''
        self.assertIsNone(validate_control_program(parse_syntax(valid, "valid.hocus"), {}, {}))

        invalid = valid.replace("yield out = 2;", 'node broken: "null" { value = missing.value; } yield out = 2;')
        with self.assertRaises(ModuleExpansionError) as captured:
            validate_control_program(parse_syntax(invalid, "invalid.hocus"), {}, {})
        self.assertEqual(captured.exception.code, "HOCUS471")

        for count, code in ((-1, "HOCUS475"), (4097, "HOCUS464")):
            hidden_count = valid.replace(
                "yield out = 2;",
                f'''for hidden @id("hidden") (i in range({count})) carry (value: int = 0) {{
      yield value = iter.i;
    }}
    yield out = hidden.value;''',
            )
            with self.assertRaises(ModuleExpansionError) as hidden:
                validate_control_program(
                    parse_syntax(hidden_count, "hidden-count.hocus"), {}, {}
                )
            self.assertEqual(hidden.exception.code, code)

        nested = valid.replace(
            "yield out = 1;",
            '''if nested @id("nested") (true) outputs (value: int) {
      yield value = 1;
    } else {
      yield value = 2;
    }
    yield out = nested.value;''',
        )
        with self.assertRaises(ModuleExpansionError) as depth:
            validate_control_program(
                parse_syntax(nested, "nested.hocus"),
                {},
                {},
                limits=ControlExpansionLimits(instance_depth=1),
            )
        self.assertEqual(depth.exception.code, "HOCUS464")

        graph_ast = parse_syntax(
            'hocus 0.3; graph G { target = "/obj"; category = Sop; }',
            "forged.hocus",
        )
        module_ast = parse_syntax(
            "hocus 0.3; module M() exports (value: int) { export value = 1; }",
            "module.hocus",
        )
        forged = replace(
            graph_ast,
            graph=replace(
                graph_ast.graph,
                statements=(
                    *graph_ast.graph.statements,
                    module_ast.module.statements[-1],
                ),
            ),
        )
        with self.assertRaises(ModuleExpansionError) as malformed:
            validate_control_program(forged, {}, {})
        self.assertEqual(malformed.exception.code, "HOCUS479")

        category = graph_ast.graph.statements[1]
        duplicated = replace(
            graph_ast,
            graph=replace(
                graph_ast.graph,
                statements=(*graph_ast.graph.statements, category),
            ),
        )
        with self.assertRaises(ModuleExpansionError) as duplicate:
            validate_control_program(duplicated, {}, {})
        self.assertEqual(duplicate.exception.code, "HOCUS473")

        valid_ast = parse_syntax(valid, "forged-node.hocus")
        node = valid_ast.graph.statements[-1]
        for symbol in (7, "not valid!"):
            hostile_ast = replace(
                valid_ast,
                graph=replace(
                    valid_ast.graph,
                    statements=(
                        *valid_ast.graph.statements[:-1],
                        replace(node, symbol=symbol),
                    ),
                ),
            )
            with self.assertRaises(ModuleExpansionError) as hostile:
                validate_control_program(hostile_ast, {}, {})
            self.assertEqual(hostile.exception.code, "HOCUS473")

        invalid_category = replace(
            graph_ast,
            graph=replace(
                graph_ast.graph,
                statements=(
                    graph_ast.graph.statements[0],
                    replace(category, value="not valid!"),
                ),
            ),
        )
        with self.assertRaises(ModuleExpansionError) as hostile_category:
            validate_control_program(invalid_category, {}, {})
        self.assertEqual(hostile_category.exception.code, "HOCUS479")

        malformed_root = replace(valid_ast, span=7)
        with self.assertRaises(ModuleExpansionError) as malformed_span:
            validate_control_program(malformed_root, {}, {})
        self.assertEqual(malformed_span.exception.code, "HOCUS479")
        self.assertEqual(malformed_span.exception.span.source_name, "<control-ast>")

        unsupported = replace(
            valid_ast,
            version=replace(valid_ast.version, value="0.2"),
        )
        with self.assertRaises(ModuleExpansionError) as wrong_lane:
            validate_control_program(unsupported, {}, {})
        self.assertEqual(wrong_lane.exception.code, "HOCUS460")

        parm = node.statements[0]
        value = parm.value
        malformed_fields = (
            replace(valid_ast, version=7),
            replace(
                valid_ast,
                graph=replace(valid_ast.graph, statements=list(valid_ast.graph.statements)),
            ),
            replace(
                valid_ast,
                graph=replace(
                    valid_ast.graph,
                    statements=(
                        *valid_ast.graph.statements[:-1],
                        replace(node, statements=(replace(parm, span=7),)),
                    ),
                ),
            ),
            replace(
                valid_ast,
                graph=replace(
                    valid_ast.graph,
                    statements=(
                        *valid_ast.graph.statements[:-1],
                        replace(
                            node,
                            statements=(
                                replace(
                                    parm,
                                    value=replace(
                                        value,
                                        output_index=True,
                                        output_index_span=value.member_span,
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
        for malformed_ast in malformed_fields:
            with self.subTest(malformed_field=malformed_ast):
                with self.assertRaises(ModuleExpansionError) as malformed:
                    validate_control_program(malformed_ast, {}, {})
                self.assertEqual(malformed.exception.code, "HOCUS479")

        invalid_parm_name = replace(
            valid_ast,
            graph=replace(
                valid_ast.graph,
                statements=(
                    *valid_ast.graph.statements[:-1],
                    replace(node, statements=(replace(parm, name=7),)),
                ),
            ),
        )
        with self.assertRaises(ModuleExpansionError) as invalid_name:
            validate_control_program(invalid_parm_name, {}, {})
        self.assertEqual(invalid_name.exception.code, "HOCUS473")

        fold_ast = parse_syntax(
            '''hocus 0.3;
graph G {
  target "/obj/g";
  for series @id("series") (i in range(1)) carry (out: int = 0) {
    yield out = iter.i;
  }
}
''',
            "forged-fold.hocus",
        )
        fold = fold_ast.graph.statements[-1]
        folded_yield = fold.body[-1]
        invalid_control_names = (
            replace(fold, iterator=7),
            replace(
                fold,
                body=(
                    replace(
                        folded_yield,
                        value=replace(folded_yield.value, member=7),
                    ),
                ),
            ),
        )
        for invalid_control in invalid_control_names:
            hostile_fold = replace(
                fold_ast,
                graph=replace(
                    fold_ast.graph,
                    statements=(
                        *fold_ast.graph.statements[:-1],
                        invalid_control,
                    ),
                ),
            )
            with self.assertRaises(ModuleExpansionError) as invalid_identifier:
                validate_control_program(hostile_fold, {}, {})
            self.assertEqual(invalid_identifier.exception.code, "HOCUS473")

        code_ast_v01 = parse_syntax(
            'hocus 0.1; graph G { target "/obj/g"; node n: "null" { script = vex`@P = 0;`; } }',
            "forged-code.hocus",
        )
        code_ast = replace(
            code_ast_v01,
            version=replace(code_ast_v01.version, value="0.3"),
        )
        array_ast_v04 = parse_syntax(
            'hocus 0.4; graph G { target "/obj/g"; node n: "null" { scale = [1, 2, 3]; } }',
            "forged-array.hocus",
        )
        for rich_ast in (
            code_ast,
            replace(array_ast_v04, version=replace(array_ast_v04.version, value="0.3")),
        ):
            with self.assertRaises(ModuleExpansionError) as frozen_lane:
                validate_control_program(rich_ast, {}, {})
            self.assertEqual(frozen_lane.exception.code, "HOCUS479")
        code_node = code_ast.graph.statements[-1]
        code_parm = code_node.statements[0]
        code_value = code_parm.value
        malformed_map = replace(
            code_value.offset_map,
            checkpoints=((0, code_value.body_span.start.offset), ("bad", 0)),
        )
        hostile_code = replace(
            code_ast,
            graph=replace(
                code_ast.graph,
                statements=(
                    *code_ast.graph.statements[:-1],
                    replace(
                        code_node,
                        statements=(
                            replace(code_parm, value=replace(code_value, offset_map=malformed_map)),
                        ),
                    ),
                ),
            ),
        )
        with self.assertRaises(ModuleExpansionError) as invalid_offset_map:
            validate_control_program(hostile_code, {}, {})
        self.assertEqual(invalid_offset_map.exception.code, "HOCUS479")

        payload = "x" * (1024 * 1024)
        literal = valid_ast.graph.statements[1].then_body[0].value
        amplified_node = replace(
            node,
            statements=tuple(
                replace(
                    parm,
                    name=f"payload{index}",
                    value=replace(literal, value=payload, span=parm.value.span),
                )
                for index in range(9)
            ),
        )
        amplified_ast = replace(
            valid_ast,
            graph=replace(
                valid_ast.graph,
                statements=(*valid_ast.graph.statements[:-1], amplified_node),
            ),
        )
        with self.assertRaises(ModuleExpansionError) as amplified_text:
            validate_control_program(amplified_ast, {}, {})
        self.assertEqual(amplified_text.exception.code, "HOCUS479")

        module_ast = parse_syntax(
            "hocus 0.3; module M(value: int) exports (out: int) { export out = param.value; }",
            "forged-module.hocus",
        )
        parameter = module_ast.module.parameters[0]
        malformed_module = replace(
            module_ast,
            module=replace(
                module_ast.module,
                parameters=(replace(parameter, name=7),),
            ),
        )
        unit = ResolvedModuleUnit(
            "hocus-project://project/forged-module.hocus",
            "sha256:" + "0" * 64,
            malformed_module,
            {},
        )
        with self.assertRaises(ModuleExpansionError) as invalid_module_name:
            validate_control_program(valid_ast, {}, {unit.uri: unit})
        self.assertEqual(invalid_module_name.exception.code, "HOCUS473")

    def test_expansion_executes_if_and_for_into_a_canonical_graph(self) -> None:
        graph = _expand(
            '''
  if choice @id("choice") (true) outputs (value: int) {
    yield value = 7;
  } else {
    yield value = 9;
  }
  for series @id("series") (i in range(3)) carry (value: int = choice.value) {
    node step @id("step"): "null" { index = iter.i; previous = carry.value; }
    yield value = iter.i;
  }
  node result @id("result"): "null" { final = series.value; }
'''
        )

        self.assertEqual(len(graph["nodes"]), 4)
        self.assertEqual(
            [node["parms"][0]["value"]["value"] for node in graph["nodes"][:3]],
            [0, 1, 2],
        )
        self.assertEqual(graph["nodes"][-1]["parms"][0]["value"]["value"], 2)
        self.assertTrue(graph["expansionMap"]["mappings"])
        self.assertTrue(graph["expansionMap"]["controlStacks"])

        zero = _expand(
            '''
  for series @id("zero") (i in range(0)) carry (value: int = 7) {
    node hidden @id("hidden"): "null" { index = iter.i; }
    yield value = iter.i;
  }
  node result @id("zero-result"): "null" { final = series.value; }
'''
        )
        self.assertEqual(len(zero["nodes"]), 1)
        self.assertEqual(zero["nodes"][0]["parms"][0]["value"]["value"], 7)
        self.assertFalse(zero["expansionMap"]["controlStacks"])
        zero_mapping = next(
            item
            for item in zero["expansionMap"]["mappings"]
            if item["generatedPointer"] == "/nodes/0/parms/0"
        )
        self.assertEqual(
            [item["role"] for item in zero_mapping["relatedOrigins"]],
            ["control_declaration", "fold_count", "carry_initializer"],
        )

        shadowed = _expand(
            '''
  for outer @id("outer") (i in range(2)) carry (value: int = 5) {
    for inner @id("inner") (i in range(1)) carry (value: int = carry.value) {
      node step @id("step"): "null" { inner_index = iter.i; previous = carry.value; }
      yield value = iter.i;
    }
    node after @id("after"): "null" {
      outer_index = iter.i;
      previous = carry.value;
      nested = inner.value;
    }
    yield value = iter.i;
  }
'''
        )
        values = [
            [parm["value"]["value"] for parm in node["parms"]]
            for node in shadowed["nodes"]
        ]
        self.assertEqual(values, [[0, 5], [0, 5, 0], [0, 0], [1, 0, 0]])
        self.assertEqual(
            sorted({
                len(item["frames"])
                for item in shadowed["expansionMap"]["controlStacks"]
            }),
            [1, 2],
        )

        base_ids = _identity_symbols()
        self.assertEqual(
            base_ids,
            _identity_symbols(
                control_symbol="renamed",
                iterator="j",
                node_symbol="renamed_node",
            ),
        )
        self.assertNotEqual(base_ids, _identity_symbols(branch="false"))
        self.assertEqual(base_ids, _identity_symbols(count=3)[:2])

    def test_expansion_stops_at_public_limits_or_cancellation(self) -> None:
        body = '''
  for series @id("series") (i in range(3)) carry (value: int = 0) {
    node step @id("step"): "null" { index = iter.i; }
    yield value = iter.i;
  }
'''
        with self.assertRaises(ModuleExpansionError) as limited:
            _expand(body, limits=ControlExpansionLimits(aggregate_iterations=2))
        self.assertEqual(limited.exception.code, "HOCUS464")

        boundary = _expand(
            body,
            limits=ControlExpansionLimits(
                per_fold_iterations=3,
                aggregate_iterations=3,
            ),
        )
        self.assertEqual(len(boundary["nodes"]), 3)

        exhausted = body + body.replace("series", "again").replace('"step"', '"again-step"')
        with self.assertRaises(ModuleExpansionError) as aggregate:
            _expand(
                exhausted,
                limits=ControlExpansionLimits(
                    per_fold_iterations=3,
                    aggregate_iterations=5,
                ),
            )
        self.assertEqual(aggregate.exception.code, "HOCUS464")

        with self.assertRaises(ModuleExpansionError) as cancelled:
            _expand(body, cancellation=lambda: True)
        self.assertEqual(cancelled.exception.code, "HOCUS499")

        catalog_source = parse_syntax(
            'hocus 0.3; graph G { target "/obj/g"; category Sop; node n: "missing" {} }',
            "catalog-cancel.hocus",
        )
        base_catalog = _catalog_provider().catalog
        operators = tuple(
            replace(
                base_catalog.operators[0],
                qualified_name=f"operator{i}",
                name=f"operator{i}",
                aliases=("shared",),
            )
            for i in range(256)
        )
        large_catalog = FakeCatalogProvider.create(
            categories=base_catalog.categories,
            operators=operators,
        ).catalog
        checkpoints = [0]

        def cancel_during_operator_scan() -> bool:
            checkpoints[0] += 1
            return checkpoints[0] >= 24

        with self.assertRaises(ModuleExpansionError) as catalog_cancelled:
            validate_control_catalog_program(
                catalog_source,
                {},
                {},
                large_catalog,
                expected_catalog_fingerprint=large_catalog.fingerprint,
                cancellation=cancel_during_operator_scan,
            )
        self.assertEqual(catalog_cancelled.exception.code, "HOCUS499")

        checkpoints[0] = 0
        ambiguous_source = parse_syntax(
            'hocus 0.3; graph G { target "/obj/g"; category Sop; node n: shared {} }',
            "catalog-ambiguous-cancel.hocus",
        )
        with self.assertRaises(ModuleExpansionError) as ambiguity_cancelled:
            validate_control_catalog_program(
                ambiguous_source,
                {},
                {},
                large_catalog,
                expected_catalog_fingerprint=large_catalog.fingerprint,
                cancellation=cancel_during_operator_scan,
            )
        self.assertEqual(ambiguity_cancelled.exception.code, "HOCUS499")

        checks = [0]

        def cancel_during_expansion() -> bool:
            checks[0] += 1
            return checks[0] >= 30

        with self.assertRaises(ModuleExpansionError) as cancelled_late:
            _expand(body, cancellation=cancel_during_expansion)
        self.assertEqual(cancelled_late.exception.code, "HOCUS499")
        self.assertGreater(checks[0], 1)


if __name__ == "__main__":
    unittest.main()
