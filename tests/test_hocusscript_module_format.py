from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    ModuleProjectFormatError,
    ProjectError,
    format_project_module_path,
)
import hocuspocus.hocusscript.project as project_module


GRAPH_SOURCE = 'hocus 0.2; graph Main { target "/obj/main"; category Sop; mode merge; }'
MODULE_SOURCE = (
    'hocus 0.2; module Leaf() exports (result: node_output) {'
    ' node leaf @id("leaf-node"): "box" {} export result = leaf.output[0]; }'
)


def _project(root: Path, *, uid: str = "format-project") -> None:
    for directory in ("src", "modules", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "hocus.project.toml").write_text(
        f'''schema_version = 3
[project]
uid = "{uid}"
source_directories = ["src"]
module_directories = ["modules"]
[language]
version = "0.2"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
''',
        encoding="utf-8",
    )


class HocusScriptModuleFormatTests(unittest.TestCase):
    def test_requires_explicit_language_02_v3_project(self) -> None:
        with self.assertRaises(ProjectError) as missing:
            format_project_module_path("", "src/main.hocus")
        self.assertEqual(missing.exception.code, "HOCUS460")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "src" / "main.hocus").write_text(GRAPH_SOURCE, encoding="utf-8")
            (root / "hocus.project.toml").write_text(
                'schema_version = 1\n[project]\nuid = "legacy-project"\n'
                'source_directories = ["src"]\n',
                encoding="utf-8",
            )
            with self.assertRaises(ProjectError) as legacy:
                format_project_module_path(root, "src/main.hocus")
            self.assertEqual(legacy.exception.code, "HOCUS452")

    def test_formats_graph_and_module_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            graph_path = root / "src" / "main.hocus"
            module_path = root / "modules" / "leaf.hocus"
            graph_path.write_text(GRAPH_SOURCE, encoding="utf-8")
            module_path.write_text(MODULE_SOURCE, encoding="utf-8")

            graph = format_project_module_path(root, "src/main.hocus")
            module = format_project_module_path(root, Path("modules/leaf.hocus"))
            self.assertTrue(graph.valid)
            self.assertEqual(graph.root_kind, "graph")
            self.assertTrue(graph.changed)
            self.assertEqual(module.root_kind, "module")
            self.assertTrue(module.changed)
            self.assertEqual(graph_path.read_text(encoding="utf-8"), GRAPH_SOURCE)
            self.assertNotIn("native_source_path", graph.to_dict())

            graph_path.write_text(graph.formatted_source or "", encoding="utf-8", newline="\n")
            repeated = format_project_module_path(root, "src/main.hocus")
            self.assertFalse(repeated.changed)
            self.assertEqual(repeated.formatted_source, graph.formatted_source)

    def test_missing_stale_or_malformed_lock_does_not_block_repair_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            source = root / "src" / "main.hocus"
            source.write_text(GRAPH_SOURCE, encoding="utf-8")
            self.assertTrue(format_project_module_path(root, "src/main.hocus").valid)

            lock = root / "pins" / "hocus.lock.json"
            lock.write_text('{"stale":', encoding="utf-8")
            before = lock.read_bytes()
            self.assertTrue(format_project_module_path(root, "src/main.hocus").valid)
            self.assertEqual(lock.read_bytes(), before)

    def test_invalid_source_returns_portable_diagnostic_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            source = root / "src" / "broken.hocus"
            source.write_text("hocus 0.2; graph Broken { target ; }", encoding="utf-8")
            before = source.read_bytes()
            result = format_project_module_path(root, "src/broken.hocus")
            self.assertFalse(result.valid)
            self.assertIsNone(result.formatted_source)
            self.assertFalse(result.changed)
            self.assertEqual(len(result.diagnostics), 1)
            payload = result.to_dict()
            self.assertEqual(payload["sourceUri"], "hocus-project://format-project/src/broken.hocus")
            self.assertEqual(payload["diagnostics"][0]["sourceUri"], payload["sourceUri"])
            self.assertNotIn(str(root), str(payload))
            self.assertEqual(source.read_bytes(), before)

    def test_relocation_preserves_public_result_and_omits_host_path(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            roots = (Path(first), Path(second))
            results = []
            for root in roots:
                _project(root, uid="relocatable-project")
                (root / "src" / "main.hocus").write_text(GRAPH_SOURCE, encoding="utf-8")
                results.append(format_project_module_path(root, "src/main.hocus"))
            self.assertEqual(results[0].to_dict(), results[1].to_dict())
            self.assertNotEqual(results[0].native_source_path, results[1].native_source_path)
            for root, result in zip(roots, results):
                self.assertNotIn(str(root), str(result.to_dict()))

    def test_rejects_nonportable_uncontained_and_reparse_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            (root / "src" / "main.hocus").write_text(GRAPH_SOURCE, encoding="utf-8")
            (root / "outside.hocus").write_text(GRAPH_SOURCE, encoding="utf-8")
            hostile = (
                "../outside.hocus",
                "src/../outside.hocus",
                "src\\main.hocus",
                "C:/escape.hocus",
                "/escape.hocus",
                "src/CON.hocus",
                "src/main.txt",
                "outside.hocus",
            )
            for value in hostile:
                with self.subTest(value=value), self.assertRaises(ProjectError) as rejected:
                    format_project_module_path(root, value)
                self.assertIn(rejected.exception.code, {"HOCUS460"})

            with tempfile.TemporaryDirectory() as outside:
                link = root / "src" / "linked.hocus"
                target = Path(outside) / "linked.hocus"
                target.write_text(GRAPH_SOURCE, encoding="utf-8")
                try:
                    link.symlink_to(target)
                except OSError:
                    return
                with self.assertRaises(ProjectError) as reparse:
                    format_project_module_path(root, "src/linked.hocus")
                self.assertEqual(reparse.exception.code, "HOCUS460")

    def test_stable_read_race_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            source = root / "src" / "main.hocus"
            source.write_text(GRAPH_SOURCE, encoding="utf-8")
            original = project_module._read_bounded

            def mutate_after_read(path, limit, code, label):
                raw = original(path, limit, code, label)
                Path(path).write_bytes(raw + b" ")
                return raw

            with patch(
                "hocuspocus.hocusscript.project._read_bounded",
                side_effect=mutate_after_read,
            ):
                with self.assertRaises(ProjectError) as raced:
                    format_project_module_path(root, "src/main.hocus")
            self.assertEqual(raced.exception.code, "HOCUS428")

    def test_cancellation_is_typed_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            (root / "src" / "main.hocus").write_text(GRAPH_SOURCE, encoding="utf-8")
            for callback in (
                lambda: True,
                lambda: None,
                lambda: (_ for _ in ()).throw(RuntimeError("stop")),
            ):
                with self.subTest(callback=callback), self.assertRaises(ModuleProjectFormatError) as cancelled:
                    format_project_module_path(root, "src/main.hocus", cancelled=callback)
                self.assertEqual(cancelled.exception.code, "HOCUS465")

            checkpoints = 0

            def cancel_after_read() -> bool:
                nonlocal checkpoints
                checkpoints += 1
                return checkpoints >= 4

            with self.assertRaises(ModuleProjectFormatError) as later:
                format_project_module_path(root, "src/main.hocus", cancelled=cancel_after_read)
            self.assertEqual(later.exception.code, "HOCUS465")
            self.assertLessEqual(checkpoints, 4)


if __name__ == "__main__":
    unittest.main()
