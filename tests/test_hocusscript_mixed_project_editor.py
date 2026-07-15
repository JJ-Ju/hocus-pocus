from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from hocuspocus.hocusscript import update_project_mixed_module_lock, verify_project_lock
from hocuspocus.hocusscript.mixed_project_editor import (
    complete_mixed_path,
    complete_mixed_project_source,
    definition_mixed_path,
    definition_mixed_project_source,
)
from hocuspocus.hocusscript.project import ProjectError
from hocuspocus.hocusscript.project_editor import complete_project_source
from test_hocusscript_module_lock_plan import _fixture, _write_source


def _roots(alpha: Path, beta: Path) -> dict[str, Path]:
    return {"beta": beta, "alpha": alpha}


def _rich_fixture(base: Path) -> tuple[Path, Path, Path, str]:
    project, alpha, beta = _fixture(base)
    _write_source(
        alpha / "modules/main.hocus",
        b'hocus 0.2; import { Helper } from "./helper.hocus"; '
        b'import { Beta } from "@beta/main.hocus"; '
        b'module Alpha(scale: float = 1.0) exports (result: node_output) { '
        b'node n: "sop::null" {} export result = n.output[0]; }',
    )
    entry = (
        'hocus 0.2; import { Alpha as Terrain } from "@alpha/modules/main.hocus"; '
        'graph Main { target "/obj/main"; use terrain @id("terrain") = Terrain(); '
        'node out: "sop::null" { input[0] = terrain.result; } }'
    )
    _write_source(project / "src/main.hocus", entry.encode("utf-8"))
    update_project_mixed_module_lock(
        project,
        ["src/main.hocus"],
        _roots(alpha, beta),
        expected_lock_digest=verify_project_lock(project).lock_digest,
        allow_write=True,
    )
    return project, alpha, beta, entry


class MixedProjectEditorTests(unittest.TestCase):
    def test_saved_import_path_completion_is_portable_and_entry_gated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta, entry = _rich_fixture(Path(temporary))
            offset = entry.index("@alpha") + len("@a")
            first = complete_mixed_path(
                project, "src/main.hocus", offset,
                module_roots=_roots(alpha, beta),
            ).to_dict()
            second = complete_mixed_path(
                project, "src/main.hocus", offset,
                module_roots=_roots(alpha, beta),
            ).to_dict()
            self.assertEqual(first, second)
            self.assertEqual(first["context"], "import_path")
            labels = [item["label"] for item in first["items"]]
            self.assertIn("@alpha/modules/main.hocus", labels)
            self.assertNotIn("@alpha/modules/helper.hocus", labels)
            encoded = json.dumps(first)
            self.assertNotIn(str(project), encoded)
            self.assertNotIn(str(alpha), encoded)
            self.assertNotIn(str(beta), encoded)
            self.assertIn("resolverPolicyDigest", first["pins"])

    def test_dirty_external_interface_completions_use_exact_published_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta, entry = _rich_fixture(Path(temporary))
            roots = _roots(alpha, beta)
            imported = complete_mixed_project_source(
                project, "src/main.hocus", entry,
                entry.index("Alpha as") + 2,
                module_roots=roots,
            )
            self.assertEqual(imported.context, "imported_module_name")
            self.assertEqual([item.label for item in imported.items], ["Alpha"])

            argument_offset = entry.index("Terrain()") + len("Terrain(")
            arguments = complete_mixed_project_source(
                project, "src/main.hocus", entry, argument_offset,
                module_roots=roots,
            )
            self.assertEqual(arguments.context, "named_argument")
            self.assertEqual([item.label for item in arguments.items], ["scale"])
            self.assertFalse(arguments.items[0].required)
            self.assertEqual(arguments.items[0].default, 1.0)

            export_offset = entry.index("terrain.result") + len("terrain.")
            exports = complete_mixed_project_source(
                project, "src/main.hocus", entry, export_offset,
                module_roots=roots,
            )
            self.assertEqual(exports.context, "instance_export")
            self.assertEqual([item.label for item in exports.items], ["result"])

    def test_saved_and_dirty_definitions_return_external_portable_uris(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta, entry = _rich_fixture(Path(temporary))
            roots = _roots(alpha, beta)
            imported = definition_mixed_path(
                project, "src/main.hocus", entry.index("@alpha") + 2,
                module_roots=roots,
            )
            self.assertEqual(imported.items[0].kind, "module")
            self.assertEqual(imported.items[0].name, "Alpha")
            self.assertEqual(
                imported.items[0].source_uri,
                "hocus-module://alpha-library/modules/main.hocus",
            )

            parameter_source = entry.replace("Terrain()", "Terrain(scale = 2.0)")
            parameter = definition_mixed_project_source(
                project, "src/main.hocus", parameter_source,
                parameter_source.index("scale =") + 2,
                module_roots=roots,
            )
            self.assertEqual(parameter.items[0].kind, "parameter")
            self.assertEqual(parameter.items[0].name, "scale")
            self.assertEqual(parameter.items[0].source_uri, imported.items[0].source_uri)

            exported = definition_mixed_project_source(
                project, "src/main.hocus", entry,
                entry.index("terrain.result") + len("terrain."),
                module_roots=roots,
            )
            self.assertEqual(exported.items[0].kind, "export")
            self.assertEqual(exported.items[0].name, "result")
            self.assertEqual(exported.items[0].source_uri, imported.items[0].source_uri)

    def test_roots_are_mandatory_exact_and_subjects_remain_project_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta, entry = _rich_fixture(Path(temporary))
            offset = entry.index("Alpha as") + 2
            with self.assertRaises(TypeError):
                complete_mixed_project_source(project, "src/main.hocus", entry, offset)
            with self.assertRaises(ProjectError):
                complete_mixed_project_source(
                    project, "src/main.hocus", entry, offset, module_roots={},
                )
            with self.assertRaises(ProjectError):
                complete_mixed_project_source(
                    project, "../alpha/modules/main.hocus", entry, offset,
                    module_roots=_roots(alpha, beta),
                )
            with self.assertRaises(ProjectError):
                complete_project_source(project, "src/main.hocus", entry, offset)

    def test_wrong_or_stale_roots_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta, entry = _rich_fixture(Path(temporary))
            offset = entry.index("Alpha as") + 2
            with self.assertRaises(ProjectError):
                complete_mixed_project_source(
                    project, "src/main.hocus", entry, offset,
                    module_roots={"alpha": beta, "beta": alpha},
                )
            manifest = alpha / "hocus.module.toml"
            manifest.write_bytes(manifest.read_bytes() + b"\n")
            with self.assertRaises(ProjectError):
                complete_mixed_project_source(
                    project, "src/main.hocus", entry, offset,
                    module_roots=_roots(alpha, beta),
                )

    def test_saved_cancellation_precedes_subject_read(self) -> None:
        with patch(
            "hocuspocus.hocusscript.mixed_project_editor._read_saved_subject",
            side_effect=AssertionError("saved subject was read"),
        ):
            for operation in (complete_mixed_path, definition_mixed_path):
                with self.subTest(operation=operation.__name__), self.assertRaises(ProjectError) as cancelled:
                    operation(
                        "not-a-project", "src/main.hocus", 0,
                        module_roots={}, cancelled=lambda: True,
                    )
                self.assertEqual(cancelled.exception.code, "HOCUS465")

    def test_external_source_change_is_detected_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta, entry = _rich_fixture(Path(temporary))
            from hocuspocus.hocusscript import mixed_project_editor as editor

            real_read = editor._read_target
            calls = 0

            def mutate_after_initial_read(*args, **kwargs):
                nonlocal calls
                result = real_read(*args, **kwargs)
                calls += 1
                if calls == 1:
                    path = alpha / "modules/main.hocus"
                    path.write_bytes(path.read_bytes() + b" ")
                return result

            with patch.object(editor, "_read_target", side_effect=mutate_after_initial_read):
                with self.assertRaises(ProjectError) as changed:
                    complete_mixed_project_source(
                        project, "src/main.hocus", entry,
                        entry.index("Alpha as") + 2,
                        module_roots=_roots(alpha, beta),
                    )
            self.assertEqual(changed.exception.code, "HOCUS428")


if __name__ == "__main__":
    unittest.main()
