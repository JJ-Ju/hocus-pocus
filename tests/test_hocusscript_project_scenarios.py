from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    BundleValidationError,
    ModuleResolutionError,
    ProjectError,
    compile_project_mixed_module_bundle,
    compile_project_module_bundle,
    complete_mixed_project_source,
    complete_project_source,
    decode_compiled_bundle,
    definition_mixed_project_source,
    definition_project_source,
    format_project_module_path,
    inspect_external_module_roots,
    update_project_lock,
    update_project_mixed_module_lock,
    update_project_module_lock,
    verify_project_lock,
)
from hocuspocus.hocusscript.cli import main


CATALOG = ROOT / "tests/fixtures/hocusscript/catalog/catalog-v1.json"
NATIVE_UID = "scenario-native-project"
MIXED_UID = "scenario-mixed-project"

ROOT_MODULE = """hocus 0.2;
module Root(scale: float = 1.0) exports (result: node_output) {
  node source @id("source"): "sop::null" {}
  export result = source.output[0];
}
"""
NATIVE_ENTRY = """hocus 0.2;
import { Root as Terrain } from "root.hocus";
graph Main {
  target "/obj/geo1";
  category Sop;
  use terrain @id("terrain") = Terrain();
  node out @id("out"): "sop::null" { input[0] = terrain.result; }
  output = out;
}
"""
EXTERNAL_MODULE = """hocus 0.2;
import { Helper } from "./helper.hocus";
module Terrain(scale: float = 1.0) exports (result: node_output) {
  use helper @id("helper") = Helper();
  export result = helper.result;
}
"""
EXTERNAL_HELPER = """hocus 0.2;
module Helper() exports (result: node_output) {
  node source @id("source"): "sop::null" {}
  export result = source.output[0];
}
"""
MIXED_ENTRY = """hocus 0.2;
import { Terrain } from "@terrain/modules/main.hocus";
graph Main {
  target "/obj/geo1";
  category Sop;
  use terrain @id("terrain") = Terrain();
  node out @id("out"): "sop::null" { input[0] = terrain.result; }
  output = out;
}
"""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _write_base_project(root: Path, uid: str, external_table: str = "") -> None:
    for directory in ("src", "modules", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CATALOG, root / "catalog/catalog.json")
    (root / "hocus.project.toml").write_text(
        f"""schema_version = 3
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
{external_table}""",
        encoding="utf-8",
    )
    update_project_lock(root, [], allow_write=True)


def _native_project(root: Path) -> None:
    _write_base_project(root, NATIVE_UID)
    (root / "src/main.hocus").write_text(NATIVE_ENTRY, encoding="utf-8")
    (root / "modules/root.hocus").write_text(ROOT_MODULE, encoding="utf-8")
    update_project_module_lock(
        root,
        ["src/main.hocus"],
        expected_lock_digest=verify_project_lock(root).lock_digest,
        allow_write=True,
    )


def _mixed_project(base: Path) -> tuple[Path, Path]:
    project, library = base / "project", base / "terrain-library"
    manifest = b"""schema_version = 1
entry_modules = ["modules/main.hocus"]
[library]
uid = "terrain-library"
version = "1.0.0"
[language]
version = "0.2"
"""
    library.mkdir(parents=True)
    (library / "hocus.module.toml").write_bytes(manifest)
    (library / "modules").mkdir()
    (library / "modules/main.hocus").write_text(EXTERNAL_MODULE, encoding="utf-8")
    (library / "modules/helper.hocus").write_text(EXTERNAL_HELPER, encoding="utf-8")
    external = f"""[external_aliases.terrain]
library_uid = "terrain-library"
version = "1.0.0"
module_manifest_digest = "{_digest(manifest)}"
"""
    _write_base_project(project, MIXED_UID, external)
    (project / "src/main.hocus").write_text(MIXED_ENTRY, encoding="utf-8")
    update_project_mixed_module_lock(
        project,
        ["src/main.hocus"],
        {"terrain": library},
        expected_lock_digest=verify_project_lock(project).lock_digest,
        allow_write=True,
    )
    return project, library


def _run(*arguments: str) -> tuple[int, str, str]:
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = main(list(arguments))
    return code, output.getvalue(), errors.getvalue()


class HocusScriptProjectScenarios(unittest.TestCase):
    def test_native_cli_check_and_compile_produce_portable_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)

            checked, check_output, check_errors = _run(
                "check", "src/main.hocus", "--project", str(root), "--json",
            )
            compiled, bundle_output, bundle_errors = _run(
                "compile", "src/main.hocus", "--project", str(root),
            )

            self.assertEqual((checked, compiled), (0, 0), check_errors + bundle_errors)
            self.assertTrue(json.loads(check_output)["valid"])
            self.assertEqual(json.loads(bundle_output)["bundleVersion"], "0.3")
            self.assertNotIn(str(root), check_output + bundle_output)

    def test_native_bundle_is_deterministic_after_project_relocation(self) -> None:
        bundles = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for location in (first, second):
                root = Path(location)
                _native_project(root)
                bundles.append(
                    compile_project_module_bundle(root, "src/main.hocus").to_dict()
                )
                self.assertNotIn(str(root), json.dumps(bundles[-1]))
        self.assertEqual(bundles[0], bundles[1])

    def test_native_editor_completes_and_defines_locked_module_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)
            source = (root / "src/main.hocus").read_text("utf-8")

            arguments = complete_project_source(
                root, "src/main.hocus", source, source.index("Terrain()") + len("Terrain("),
            )
            exported = definition_project_source(
                root,
                "src/main.hocus",
                source,
                source.index("terrain.result") + len("terrain."),
            )

            self.assertEqual([item.label for item in arguments.items], ["scale"])
            self.assertEqual(arguments.items[0].default, 1.0)
            self.assertEqual(exported.items[0].name, "result")
            self.assertEqual(
                exported.items[0].source_uri,
                f"hocus-project://{NATIVE_UID}/modules/root.hocus",
            )

    def test_changed_native_module_is_rejected_until_lock_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)
            module = root / "modules/root.hocus"
            module.write_text(ROOT_MODULE + "\n", encoding="utf-8")

            with self.assertRaises(ModuleResolutionError):
                compile_project_module_bundle(root, "src/main.hocus")

            update_project_module_lock(
                root,
                ["src/main.hocus"],
                expected_lock_digest=verify_project_lock(root).lock_digest,
                allow_write=True,
            )
            self.assertEqual(
                compile_project_module_bundle(
                    root, "src/main.hocus",
                ).to_dict()["bundleVersion"],
                "0.3",
            )

    def test_mixed_cli_updates_lock_checks_and_compiles_external_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, library = _mixed_project(Path(temporary))
            digest = verify_project_lock(project).lock_digest
            roots = ("--module-root", f"terrain={library}")

            locked, receipt, lock_errors = _run(
                "lock",
                "src/main.hocus",
                "--update",
                "--project",
                str(project),
                "--expected-lock-digest",
                digest,
                *roots,
            )
            checked, check_output, check_errors = _run(
                "check",
                "src/main.hocus",
                "--project",
                str(project),
                "--json",
                *roots,
            )
            compiled, bundle_output, bundle_errors = _run(
                "compile", "src/main.hocus", "--project", str(project), *roots,
            )

            self.assertEqual((locked, checked, compiled), (0, 0, 0))
            self.assertEqual(json.loads(receipt)["previousLockDigest"], digest)
            self.assertTrue(json.loads(check_output)["valid"])
            bundle = json.loads(bundle_output)
            self.assertTrue(
                any(item["uri"].startswith("hocus-module://") for item in bundle["dependencies"])
            )
            rendered = receipt + check_output + bundle_output
            self.assertNotIn(str(project), rendered)
            self.assertNotIn(str(library), rendered)
            self.assertEqual(lock_errors + check_errors + bundle_errors, "")

    def test_mixed_editor_uses_published_external_interface(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, library = _mixed_project(Path(temporary))
            source = (project / "src/main.hocus").read_text("utf-8")
            roots = {"terrain": library}

            arguments = complete_mixed_project_source(
                project,
                "src/main.hocus",
                source,
                source.index("Terrain()") + len("Terrain("),
                module_roots=roots,
            )
            exported = definition_mixed_project_source(
                project,
                "src/main.hocus",
                source,
                source.index("terrain.result") + len("terrain."),
                module_roots=roots,
            )

            self.assertEqual([item.label for item in arguments.items], ["scale"])
            self.assertEqual(exported.items[0].name, "result")
            self.assertEqual(
                exported.items[0].source_uri,
                "hocus-module://terrain-library/modules/main.hocus",
            )

    def test_mixed_consumers_reject_missing_roots_and_stale_external_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, library = _mixed_project(Path(temporary))
            code, output, errors = _run(
                "compile", "src/main.hocus", "--project", str(project),
            )
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("HOCUS460", errors)

            helper = library / "modules/helper.hocus"
            helper.write_text(EXTERNAL_HELPER + "\n", encoding="utf-8")
            with self.assertRaises((ProjectError, ModuleResolutionError)):
                compile_project_mixed_module_bundle(
                    project, "src/main.hocus", {"terrain": library},
                )

    def test_stale_lock_digest_never_overwrites_mixed_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, library = _mixed_project(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            before = lock.read_bytes()
            with self.assertRaises(ProjectError):
                update_project_mixed_module_lock(
                    project,
                    ["src/main.hocus"],
                    {"terrain": library},
                    expected_lock_digest="sha256:" + "0" * 64,
                    allow_write=True,
                )
            self.assertEqual(lock.read_bytes(), before)

    def test_format_handles_graph_and_module_without_lock_or_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)
            graph = root / "src/main.hocus"
            module = root / "modules/root.hocus"
            graph.write_text(NATIVE_ENTRY.replace("\n", " "), encoding="utf-8")
            module.write_text(ROOT_MODULE.replace("\n", " "), encoding="utf-8")
            lock = root / "pins/hocus.lock.json"
            lock.write_text("not-json", encoding="utf-8")
            graph_before, module_before = graph.read_bytes(), module.read_bytes()

            graph_result = format_project_module_path(root, "src/main.hocus")
            module_result = format_project_module_path(root, "modules/root.hocus")

            self.assertTrue(graph_result.valid and module_result.valid)
            self.assertEqual((graph_result.root_kind, module_result.root_kind), ("graph", "module"))
            self.assertEqual((graph.read_bytes(), module.read_bytes()), (graph_before, module_before))
            self.assertNotIn(str(root), json.dumps(graph_result.to_dict()))

    def test_external_manifest_inspection_and_bundle_tampering_fail_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, library = _mixed_project(Path(temporary))
            inspection = inspect_external_module_roots(project, {"terrain": library})
            self.assertEqual(inspection.libraries[0].library_uid, "terrain-library")
            self.assertNotIn(str(library), json.dumps(inspection.to_dict()))

            payload = compile_project_mixed_module_bundle(
                project, "src/main.hocus", {"terrain": library},
            ).to_dict()
            payload["dependencies"][0]["digest"] = "sha256:" + "0" * 64
            with self.assertRaises(BundleValidationError):
                decode_compiled_bundle(payload)


if __name__ == "__main__":
    unittest.main()
