from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    ProjectError,
    complete_path,
    complete_project_source,
    definition_project_source,
    update_project_module_lock,
    verify_project_lock,
)
from test_hocusscript_resolver import _valid_project
from hocuspocus.hocusscript.resolved_modules import ResolvedModuleLimits


def _rich_project(root: Path) -> tuple[str, str]:
    _valid_project(root)
    previous = verify_project_lock(root).lock_digest
    module = (
        'hocus 0.2; module Root(source: node_output, scale: float = 1.0) '
        'exports (result: node_output, effectiveScale: float) { '
        'node n: "sop::null" {} export result = n.output[0]; '
        'export effectiveScale = param.scale; }'
    )
    entry = (
        'hocus 0.2; import { Root as Terrain } from "root.hocus"; graph Main { '
        'target "/obj/geo1"; category Sop; node base: "sop::null" {} '
        'use terrain @id("terrain") = Terrain(source = base.output[0]); '
        'node out: "sop::null" { input[0] = terrain.result; } }'
    )
    (root / "modules-b/root.hocus").write_text(module, encoding="utf-8")
    (root / "src/main.hocus").write_text(entry, encoding="utf-8")
    update_project_module_lock(
        root, ["src/main.hocus"], allow_write=True, expected_lock_digest=previous,
    )
    return entry, module


class ProjectEditorTests(unittest.TestCase):
    def test_saved_and_dirty_completion_are_pinned_portable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as relocated:
            root, second_root = Path(temporary), Path(relocated)
            _valid_project(root)
            _valid_project(second_root)
            source = (root / "src/main.hocus").read_text("utf-8")

            version = complete_project_source(root, "src/main.hocus", source, source.index("0.2") + 1)
            self.assertEqual(version.context, "language_version")
            self.assertEqual([item.label for item in version.items], ["0.2"])
            self.assertEqual(version.subject_lock_state, "unlocked")

            path_offset = source.index("root.hocus") + 2
            first = complete_path(root, "src/main.hocus", path_offset).to_dict()
            second = complete_path(root, "src/main.hocus", path_offset).to_dict()
            self.assertEqual(first, second)
            self.assertEqual(first, complete_path(second_root, "src/main.hocus", path_offset).to_dict())
            self.assertEqual(first["context"], "import_path")
            self.assertIn("root.hocus", [item["label"] for item in first["items"]])
            encoded = json.dumps(first)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn(str(second_root), encoded)
            self.assertIn("resolverPolicyDigest", first["pins"])

    def test_import_module_and_use_completion_read_only_locked_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (
                'hocus 0.2; import { Root as LocalRoot } from "root.hocus"; '
                'graph Main { use r @id("r") = LocalRoot(); }'
            )
            imported_offset = source.index("Root as") + 2
            imported = complete_project_source(root, "src/main.hocus", source, imported_offset)
            self.assertEqual(imported.context, "imported_module_name")
            self.assertEqual([item.label for item in imported.items], ["Root"])

            use_offset = source.rindex("LocalRoot") + 3
            used = complete_project_source(root, "src/main.hocus", source, use_offset)
            self.assertEqual(used.context, "use_module")
            self.assertEqual([item.label for item in used.items], ["LocalRoot"])

    def test_definitions_cover_import_specifier_name_and_use_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (
                'hocus 0.2; import { Root as LocalRoot } from "root.hocus"; '
                'graph Main { use r @id("r") = LocalRoot(); }'
            )
            module_definition = definition_project_source(
                root, "src/main.hocus", source, source.index("root.hocus") + 2,
            )
            self.assertEqual(module_definition.items[0].name, "Root")
            self.assertEqual(module_definition.items[0].kind, "module")
            self.assertTrue(module_definition.items[0].source_uri.endswith("/modules-b/root.hocus"))

            alias_definition = definition_project_source(
                root, "src/main.hocus", source, source.rindex("LocalRoot") + 2,
            )
            self.assertEqual(alias_definition.items[0].kind, "import_alias")
            self.assertEqual(alias_definition.items[0].source_uri, alias_definition.source_uri)

    def test_modified_locked_subject_is_explicit_and_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            disk = (root / "modules-b/root.hocus").read_bytes()
            dirty = disk.decode("utf-8").replace("module Root", "module Changed")
            result = complete_project_source(
                root, "modules-b/root.hocus", dirty, dirty.index("0.2") + 1,
            )
            self.assertEqual(result.subject_lock_state, "modified")
            self.assertEqual((root / "modules-b/root.hocus").read_bytes(), disk)

    def test_interface_completions_and_definitions_cover_parameters_exports_and_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry, module = _rich_project(root)

            call_offset = entry.index("Terrain(") + len("Terrain(")
            arguments = complete_project_source(root, "src/main.hocus", entry, call_offset)
            self.assertEqual(arguments.context, "named_argument")
            by_name = {item.label: item for item in arguments.items}
            self.assertTrue(by_name["source"].required)
            self.assertEqual(by_name["source"].type_name, "node_output")
            self.assertFalse(by_name["scale"].required)
            self.assertEqual(by_name["scale"].default, 1.0)

            export_offset = entry.index("terrain.result") + len("terrain.")
            exports = complete_project_source(root, "src/main.hocus", entry, export_offset)
            self.assertEqual(exports.context, "instance_export")
            self.assertEqual([item.label for item in exports.items], ["effectiveScale", "result"])

            parameter_offset = module.index("param.scale") + len("param.")
            parameters = complete_project_source(
                root, "modules-b/root.hocus", module, parameter_offset,
            )
            self.assertEqual(parameters.subject_lock_state, "matching")
            self.assertEqual(parameters.context, "parameter_name")
            self.assertEqual([item.label for item in parameters.items], ["scale", "source"])

            named_definition = definition_project_source(
                root, "src/main.hocus", entry, entry.index("source =") + 2,
            )
            self.assertEqual(named_definition.items[0].kind, "parameter")
            self.assertTrue(named_definition.items[0].source_uri.endswith("/modules-b/root.hocus"))

            argument_symbol = definition_project_source(
                root, "src/main.hocus", entry, entry.index("base.output") + 2,
            )
            self.assertEqual(argument_symbol.items[0].kind, "symbol")
            self.assertEqual(argument_symbol.items[0].name, "base")
            self.assertEqual(argument_symbol.items[0].source_uri, argument_symbol.source_uri)

            export_definition = definition_project_source(
                root, "src/main.hocus", entry, entry.index("terrain.result") + len("terrain."),
            )
            self.assertEqual(export_definition.items[0].kind, "export")
            self.assertEqual(export_definition.items[0].name, "result")

            local_definition = definition_project_source(
                root, "modules-b/root.hocus", module, module.index("n.output") + 1,
            )
            self.assertEqual(local_definition.items[0].kind, "symbol")
            self.assertEqual(local_definition.items[0].name, "n")

    def test_fake_imports_in_comments_and_strings_do_not_trigger_module_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            cases = (
                'hocus 0.2; // import { Missing } from "missing.hocus"\ngraph Main {}',
                'hocus 0.2; graph Main { node n: "import { Missing } from \\"missing.hocus\\"" {} }',
                'hocus 0.2; graph Main { node n: "sop::null" { code = `import { Missing } from "missing.hocus"`; } }',
                'hocus 0.2; graph Main { node n: "sop::null" { from "missing.hocus',
            )
            for source in cases:
                with self.subTest(source=source):
                    result = complete_project_source(root, "src/main.hocus", source, len(source))
                    self.assertEqual(result.context, "none")

    def test_invalid_inputs_and_cancellation_fail_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (root / "src/main.hocus").read_text("utf-8")
            for current in ("../main.hocus", str(root / "src/main.hocus"), "src\\main.hocus"):
                with self.subTest(current=current), self.assertRaises(ProjectError):
                    complete_project_source(root, current, source, 0)
            with self.assertRaises(ProjectError) as cancelled:
                complete_project_source(root, "src/main.hocus", source, 0, cancelled=lambda: True)
            self.assertEqual(cancelled.exception.code, "HOCUS465")

            constrained = replace(ResolvedModuleLimits(), aggregate_source_bytes=1)
            with patch(
                "hocuspocus.hocusscript.project_editor.ResolvedModuleLimits",
                return_value=constrained,
            ), self.assertRaises(ProjectError) as bounded:
                complete_project_source(root, "src/main.hocus", source, 0)
            self.assertEqual(bounded.exception.code, "HOCUS464")
            (root / "src/occupied.hocus").mkdir()
            with self.assertRaises(ProjectError):
                complete_project_source(root, "src/occupied.hocus", source, 0)

    def test_saved_cancellation_precedes_project_and_subject_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            with patch(
                "hocuspocus.hocusscript.project_editor.ProjectContext.load",
                side_effect=AssertionError("project read must not run"),
            ), self.assertRaises(ProjectError) as cancelled:
                complete_path(root, "src/main.hocus", 0, cancelled=lambda: True)
            self.assertEqual(cancelled.exception.code, "HOCUS465")

    def test_module_aggregate_budget_and_uri_alias_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            module_bytes = (root / "modules-b/root.hocus").read_bytes()
            source = (
                'hocus 0.2; import { Root as A } from "root.hocus"; '
                'import { Root as B } from "../modules-b/root.hocus"; '
                'graph Main { use r @id("r") = A(); use s @id("s") = B(); }'
            )
            exact_once = len(source.encode("utf-8")) + len(module_bytes)
            deduped_limits = replace(
                ResolvedModuleLimits(), aggregate_source_bytes=exact_once,
            )
            with patch(
                "hocuspocus.hocusscript.project_editor.ResolvedModuleLimits",
                return_value=deduped_limits,
            ):
                result = complete_project_source(
                    root, "src/main.hocus", source, source.index("A();") + 1,
                )
            self.assertEqual([item.label for item in result.items], ["A"])

            too_small = replace(
                ResolvedModuleLimits(), aggregate_source_bytes=exact_once - 1,
            )
            with patch(
                "hocuspocus.hocusscript.project_editor.ResolvedModuleLimits",
                return_value=too_small,
            ), self.assertRaises(ProjectError) as bounded:
                complete_project_source(
                    root, "src/main.hocus", source, source.index("A();") + 1,
                )
            self.assertEqual(bounded.exception.code, "HOCUS464")

    def test_duplicate_dirty_imports_do_not_duplicate_completion_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (
                'hocus 0.2; import { Root as A } from "root.hocus"; '
                'import { Root as A } from "root.hocus"; '
                'graph Main { use r @id("r") = A(); }'
            )
            offset = source.rindex("A()") + 1
            result = complete_project_source(root, "src/main.hocus", source, offset)
            self.assertEqual(result.context, "use_module")
            self.assertEqual([item.label for item in result.items], ["A"])

    def test_use_module_completion_rejects_nonportable_and_unlocked_imports_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            absolute = (root / "private/secret.hocus").as_posix()
            hostile = (
                absolute,
                "@studio/secret.hocus",
                "../../../private/secret.hocus",
            )
            for specifier in hostile:
                source = (
                    f'hocus 0.2; import {{ Leak }} from "{specifier}"; '
                    'graph Main { use x @id("x") = Le }'
                )
                with self.subTest(specifier=specifier), self.assertRaises(ProjectError) as rejected:
                    complete_project_source(
                        root, "src/main.hocus", source, source.rindex("Le") + 2,
                    )
                self.assertIn(rejected.exception.code, {"HOCUS460", "HOCUS462"})
                self.assertNotIn(str(root), json.dumps(rejected.exception.to_dict()))

            (root / "modules-a/unlocked.hocus").write_text(
                "hocus 0.2; module Unlocked() exports () {}", encoding="utf-8",
            )
            unlocked = (
                'hocus 0.2; import { Unlocked } from "unlocked.hocus"; '
                'graph Main { use x @id("x") = Un }'
            )
            with self.assertRaises(ProjectError) as rejected:
                complete_project_source(
                    root, "src/main.hocus", unlocked, unlocked.rindex("Un") + 2,
                )
            self.assertEqual(rejected.exception.code, "HOCUS462")

    def test_stale_import_content_or_lock_authority_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (root / "src/main.hocus").read_text("utf-8")
            (root / "modules-b/root.hocus").write_text(
                "hocus 0.2; module Root() exports () { } // changed", encoding="utf-8",
            )
            with self.assertRaises(ProjectError) as stale:
                complete_project_source(root, "src/main.hocus", source, source.index("Root") + 2)
            self.assertEqual(stale.exception.code, "HOCUS461")

    def test_earlier_occupied_winner_and_final_winner_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (root / "src/main.hocus").read_text("utf-8")
            (root / "modules-a/root.hocus").write_text(
                "hocus 0.2; module Shadow() exports () {}", encoding="utf-8",
            )
            with self.assertRaises(ProjectError) as shadowed:
                complete_project_source(root, "src/main.hocus", source, source.index("Root") + 2)
            self.assertEqual(shadowed.exception.code, "HOCUS462")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            source = (root / "src/main.hocus").read_text("utf-8")
            from hocuspocus.hocusscript import project_editor as editor_module

            real_select = editor_module._select_project_module_target
            calls = 0

            def drifting(context, importer, specifier, *, cancelled=None):
                nonlocal calls
                calls += 1
                selected = real_select(context, importer, specifier, cancelled=cancelled)
                if calls == 3:
                    return context.root / "modules-a/changed-winner.hocus"
                return selected

            with patch(
                "hocuspocus.hocusscript.project_editor._select_project_module_target",
                side_effect=drifting,
            ):
                with self.assertRaises(ProjectError) as drifted:
                    complete_project_source(root, "src/main.hocus", source, source.index("Root") + 2)
            self.assertEqual(drifted.exception.code, "HOCUS428")


if __name__ == "__main__":
    unittest.main()
