from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import update_project_module_lock, verify_project_lock
from hocuspocus.hocusscript.module_semantic import (
    ModuleSemanticCompileError,
    ModuleSemanticCompileResult,
    compile_project_module_bundle,
    compile_project_module_semantic,
)
from hocuspocus.hocusscript.project import ProjectError
from test_hocusscript_module_compiler import _native_project


def _valid_semantic_project(root: Path) -> None:
    _native_project(root)
    leaf = root / "modules/leaf.hocus"
    leaf.write_bytes(leaf.read_bytes().replace(b'"box"', b'"null"'))
    expected = verify_project_lock(root).lock_digest
    update_project_module_lock(
        root, ["src/main.hocus"], allow_write=True, expected_lock_digest=expected,
    )


class ModuleSemanticCompileTests(unittest.TestCase):
    def test_deterministic_valid_result_is_pinned_and_host_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_semantic_project(root)
            first = compile_project_module_semantic(root, "src/main.hocus")
            second = compile_project_module_semantic(root, "src/main.hocus")
            self.assertTrue(first.valid)
            self.assertTrue(first.ready_for_document_lowering)
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertEqual(first.semantic_digest, second.semantic_digest)
            self.assertEqual(first.semantic_result.catalog_fingerprint, first.compile_result.catalog_fingerprint)
            self.assertEqual(first.semantic, json.loads(first.semantic_json))
            self.assertNotIn(str(root), first.to_json(pretty=True))

    def test_semantic_error_is_retained_with_longest_expansion_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)  # The fixture catalog deliberately does not define `box`.
            result = compile_project_module_semantic(root, "src/main.hocus")
            self.assertFalse(result.valid)
            self.assertFalse(result.to_dict()["readyForBundle"])
            diagnostics = result.semantic["diagnostics"]
            unknown = next(item for item in diagnostics if item["code"] == "HOCUS622")
            self.assertEqual(unknown["jsonPointer"], "/nodes/0/typeName")
            mappings = result.compile_result.graph_spec.expansion_map.mappings
            expected = max(
                (
                    item for item in mappings
                    if unknown["jsonPointer"] == item.generated_pointer
                    or item.generated_pointer == ""
                    or unknown["jsonPointer"].startswith(item.generated_pointer + "/")
                ),
                key=lambda item: len(item.generated_pointer),
            )
            self.assertEqual(unknown["originId"], expected.origin_id)
            self.assertEqual(unknown["stackId"], expected.stack_id)
            self.assertEqual(unknown["expansionStack"], [])
            self.assertIsNone(unknown["entityUid"])
            self.assertIsNone(unknown["houdiniPath"])
            self.assertNotIn('"frames"', result.semantic_json)
            self.assertEqual(len(result.semantic_result.operator_selections), 1)

    def test_pin_drift_and_catalog_wrapper_mismatch_fail_closed(self) -> None:
        from hocuspocus.hocusscript import module_semantic as semantic_module

        for mode in ("runtime_drift", "wrapped_pin"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _valid_semantic_project(root)
                real_compile = semantic_module.compile_project_module_graph

                if mode == "runtime_drift":
                    def compile_then_drift(*args, **kwargs):
                        compiled = real_compile(*args, **kwargs)
                        catalog = root / "catalog/catalog.json"
                        catalog.write_bytes(catalog.read_bytes() + b" ")
                        return compiled

                    replacement = compile_then_drift
                    expected_error = ProjectError
                else:
                    compiled = real_compile(root, "src/main.hocus")
                    replacement = lambda *args, **kwargs: replace(
                        compiled, catalog_fingerprint="sha256:" + "0" * 64,
                    )
                    expected_error = ModuleSemanticCompileError

                with patch(
                    "hocuspocus.hocusscript.module_semantic.compile_project_module_graph",
                    new=replacement,
                ):
                    with self.assertRaises(expected_error):
                        compile_project_module_semantic(root, "src/main.hocus")

    def test_wrong_graph_version_wrapper_is_rejected(self) -> None:
        from hocuspocus.hocusscript import module_semantic as semantic_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_semantic_project(root)
            compiled = semantic_module.compile_project_module_graph(root, "src/main.hocus")
            payload = json.loads(compiled.graph_spec_json)
            payload["graphSpecVersion"] = "0.1"
            wrapped_json = semantic_module._canonical_json(payload)
            wrapped = replace(
                compiled,
                graph_spec_json=wrapped_json,
                graph_spec_digest=semantic_module._digest_text(wrapped_json),
            )
            with patch(
                "hocuspocus.hocusscript.module_semantic.compile_project_module_graph",
                return_value=wrapped,
            ):
                with self.assertRaises(ModuleSemanticCompileError) as captured:
                    compile_project_module_semantic(root, "src/main.hocus")
            self.assertEqual(captured.exception.code, "HOCUS481")

    def test_cancellation_and_selection_injection_are_rejected(self) -> None:
        signature = inspect.signature(compile_project_module_semantic)
        self.assertEqual(
            tuple(signature.parameters),
            ("project_directory", "entry_source_path", "limits", "cancelled"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_semantic_project(root)
            with self.assertRaises(ModuleSemanticCompileError) as cancelled:
                compile_project_module_semantic(
                    root, "src/main.hocus", cancelled=lambda: True,
                )
            self.assertEqual(cancelled.exception.code, "HOCUS499")
            with self.assertRaises(TypeError):
                compile_project_module_semantic(  # type: ignore[call-arg]
                    root, "src/main.hocus", catalog_snapshot=object(),
                )

    def test_one_shot_bundle_signature_has_no_semantic_injection_surface(self) -> None:
        signature = inspect.signature(compile_project_module_bundle)
        self.assertEqual(
            tuple(signature.parameters),
            ("project_directory", "entry_source_path", "limits", "cancelled"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_semantic_project(root)
            with self.assertRaises(TypeError):
                compile_project_module_bundle(  # type: ignore[call-arg]
                    root, "src/main.hocus", semantic_result=object(),
                )

    def test_one_shot_bundle_is_deterministic_and_host_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_semantic_project(root)
            first = compile_project_module_bundle(root, "src/main.hocus")
            second = compile_project_module_bundle(root, "src/main.hocus")
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertEqual(first.digest, second.digest)
            self.assertEqual(first.to_dict()["bundleVersion"], "0.3")
            self.assertNotIn(str(root), first.to_json(pretty=True))

    def test_one_shot_bundle_blocks_invalid_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)  # `box` is intentionally absent from the pinned catalog.
            with self.assertRaises(ValueError):
                compile_project_module_bundle(root, "src/main.hocus")

    def test_direct_construction_and_replace_forgery_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_semantic_project(root)
            trusted = compile_project_module_semantic(root, "src/main.hocus")
            with self.assertRaises(ModuleSemanticCompileError):
                ModuleSemanticCompileResult(
                    trusted.compile_result,
                    trusted.semantic_result,
                    trusted.semantic_json,
                    trusted.semantic_digest,
                    object(),
                    object(),  # type: ignore[arg-type]
                )
            forged_payload = trusted.semantic
            forged_payload["operatorSelections"] = []
            forged_json = json.dumps(
                forged_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
            )
            with self.assertRaises(ModuleSemanticCompileError):
                replace(
                    trusted,
                    semantic_json=forged_json,
                    semantic_digest="sha256:" + hashlib.sha256(
                        forged_json.encode("utf-8")
                    ).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
