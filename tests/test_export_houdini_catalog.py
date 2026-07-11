from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_houdini_catalog.py"
SPEC = importlib.util.spec_from_file_location("export_houdini_catalog", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class _Snapshot:
    operators = (object(), object())
    fingerprint = "sha256:" + "a" * 64

    def to_json(self) -> str:
        return '{"catalogFingerprint":"' + self.fingerprint + '"}'


class _Provider:
    def __init__(self, hou_module):
        self.hou_module = hou_module

    def get_catalog(self):
        return _Snapshot()


def _write_project(root: Path, *, version: int = 2) -> None:
    catalog = '\n[catalog]\npath = "artifacts/catalog-v1.json"\n' if version == 2 else ""
    (root / "hocus.project.toml").write_text(
        f'schema_version = {version}\n[project]\nuid = "export-test"\n'
        '[lock]\npolicy = "required"\npath = "hocus.lock.json"\n'
        + catalog,
        encoding="utf-8",
    )


class ExportHoudiniCatalogTests(unittest.TestCase):
    def _run(self, arguments: list[str]) -> int:
        fake_hou = types.ModuleType("hou")
        with (
            mock.patch.dict(sys.modules, {"hou": fake_hou}),
            mock.patch.object(exporter, "LiveHoudiniCatalogProvider", _Provider),
            redirect_stdout(StringIO()),
        ):
            return exporter.main(arguments)

    def test_writes_only_manifest_catalog_path_under_explicit_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_project(root)

            self.assertEqual(self._run(["--project", str(root)]), 0)

            output = root / "artifacts" / "catalog-v1.json"
            self.assertTrue(output.is_file())
            self.assertEqual(output.read_text(encoding="utf-8"), _Snapshot().to_json() + "\n")
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()),
                ["artifacts/catalog-v1.json", "hocus.project.toml"],
            )

    def test_environment_project_directory_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_project(root)
            with mock.patch.dict(os.environ, {"HOCUS_PROJECT_DIRECTORY": str(root)}):
                self.assertEqual(self._run([]), 0)
            self.assertTrue((root / "artifacts" / "catalog-v1.json").is_file())

    def test_manifest_without_catalog_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_project(root, version=1)
            with self.assertRaises(SystemExit):
                self._run(["--project", str(root)])
            self.assertFalse((root / "catalog-v1.json").exists())


if __name__ == "__main__":
    unittest.main()
