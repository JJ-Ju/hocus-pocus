from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.catalog import decode_catalog_snapshot
from hocuspocus.hocusscript.project import ProjectError
from hocuspocus.hocusscript.project import ProjectContext
from hocuspocus.hocusscript.resolved_modules import (
    ModuleResolutionError, ResolvedModuleLimits, module_interface_digest, module_source_digest,
    module_transitive_digest,
)
from hocuspocus.hocusscript.resolver import resolve_project_module_dag


UID = "native-project"


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _interface(name: str) -> dict:
    return {"schemaVersion": 1, "moduleName": name, "parameters": [], "exports": []}


def _module_record(path: str, name: str, source: bytes, dependencies=(), transitive_children=()):
    uri = f"hocus-project://{UID}/{path}"
    source_digest = module_source_digest(source)
    interface_digest = module_interface_digest(_interface(name))
    transitive = module_transitive_digest(
        uri=uri, source_digest=source_digest, interface_digest=interface_digest,
        dependencies=transitive_children,
    )
    return {
        "moduleUri": uri, "projectUid": UID, "libraryUid": None,
        "libraryVersion": None, "moduleManifestDigest": None,
        "languageVersion": "0.2", "sourcePath": path,
        "contentDigest": source_digest, "interfaceDigest": interface_digest,
        "transitiveDigest": transitive, "dependencies": list(dependencies),
        "externalAlias": None,
    }


def _write_project(root: Path, *, entry: bytes, records: list[dict], files: dict[str, bytes],
                   module_directories=("modules-a", "modules-b")) -> None:
    for directory in ("src", "modules-a", "modules-b", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    manifest = f'''schema_version = 3
[project]
uid = "{UID}"
source_directories = ["src"]
module_directories = [{", ".join(json.dumps(item) for item in module_directories)}]
[language]
version = "0.2"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
'''.encode()
    (root / "hocus.project.toml").write_bytes(manifest)
    (root / "src/main.hocus").write_bytes(entry)
    for relative, content in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    catalog = (ROOT / "tests/fixtures/hocusscript/catalog/catalog-v1.json").read_bytes()
    (root / "catalog/catalog.json").write_bytes(catalog)
    snapshot = decode_catalog_snapshot(catalog)
    lock = {
        "$schema": "hocuspocus://schemas/hocus-lock/v3",
        "kind": "hocus_project_lock", "schemaVersion": 3,
        "projectUid": UID, "manifestDigest": _digest(manifest), "languageVersion": "0.2",
        "catalog": {"schemaVersion": 1, "path": "catalog/catalog.json",
                    "contentDigest": _digest(catalog), "fingerprint": snapshot.fingerprint},
        "modules": sorted(records, key=lambda item: item["moduleUri"]),
    }
    (root / "pins/hocus.lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")


def _valid_project(root: Path) -> None:
    leaf_source = b"hocus 0.2; module Leaf() exports () {}"
    leaf = _module_record("modules-b/leaf.hocus", "Leaf", leaf_source)
    root_source = b'hocus 0.2; import { Leaf } from "./leaf.hocus"; module Root() exports () {}'
    root_record = _module_record(
        "modules-b/root.hocus", "Root", root_source,
        dependencies=(leaf["moduleUri"],),
        transitive_children=((leaf["moduleUri"], leaf["transitiveDigest"]),),
    )
    entry = b'hocus 0.2; import { Root } from "root.hocus"; graph Main {}'
    _write_project(
        root, entry=entry, records=[leaf, root_record],
        files={"modules-b/leaf.hocus": leaf_source, "modules-b/root.hocus": root_source},
    )


class NativeResolverTests(unittest.TestCase):
    def test_ordered_bare_and_relative_resolution_is_relocation_stable(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first, second = Path(first_dir), Path(second_dir)
            _valid_project(first)
            _valid_project(second)
            one = resolve_project_module_dag(first, "src/main.hocus")
            two = resolve_project_module_dag(second, Path("src/main.hocus"))
            context = ProjectContext.load(first)
            self.assertEqual(one.catalog_content_digest, context.catalog_content_digest)
            self.assertEqual(one.catalog_fingerprint, context.catalog_fingerprint)
            self.assertEqual(one.resolved_module_set, two.resolved_module_set)
            self.assertEqual(one.catalog_content_digest, two.catalog_content_digest)
            self.assertEqual(one.catalog_fingerprint, two.catalog_fingerprint)
            self.assertEqual(one.ordered_uris, (
                f"hocus-project://{UID}/modules-b/leaf.hocus",
                f"hocus-project://{UID}/modules-b/root.hocus",
            ))

    def test_explicit_project_and_relative_entry_are_required(self) -> None:
        with self.assertRaises(ProjectError):
            resolve_project_module_dag(None, "src/main.hocus")
        with self.assertRaises(ProjectError):
            resolve_project_module_dag(r"\\?\C:\device-root", "src/main.hocus")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            for entry in (str((root / "src/main.hocus").resolve()), "../main.hocus"):
                with self.subTest(entry=entry), self.assertRaises(ProjectError):
                    resolve_project_module_dag(root, entry)

    def test_traversal_and_external_alias_imports_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b'hocus 0.2; import { X } from "../../../outside.hocus"; graph Main {}'
            _write_project(root, entry=source, records=[], files={})
            with self.assertRaises(ProjectError):
                resolve_project_module_dag(root, "src/main.hocus")
            source = b'hocus 0.2; import { X } from "@studio/x.hocus"; graph Main {}'
            _write_project(root, entry=source, records=[], files={})
            with self.assertRaises(ProjectError):
                resolve_project_module_dag(root, "src/main.hocus")

    def test_earlier_root_shadow_makes_lock_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            (root / "modules-a/root.hocus").write_bytes(
                b"hocus 0.2; module Root() exports () {}"
            )
            with self.assertRaises(ProjectError) as stale:
                resolve_project_module_dag(root, "src/main.hocus")
            self.assertEqual(stale.exception.code, "HOCUS462")

    def test_portable_case_alias_lock_and_native_budgets_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = b"hocus 0.2; module Leaf() exports () {}"
            lower = _module_record("modules-b/leaf.hocus", "Leaf", source)
            upper = dict(lower)
            upper["sourcePath"] = "modules-b/LEAF.hocus"
            upper["moduleUri"] = f"hocus-project://{UID}/modules-b/LEAF.hocus"
            _write_project(root, entry=b"hocus 0.2; graph Main {}",
                           records=[lower, upper], files={})
            with self.assertRaises(ProjectError):
                resolve_project_module_dag(root, "src/main.hocus")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            with self.assertRaises(ModuleResolutionError) as count:
                resolve_project_module_dag(
                    root, "src/main.hocus",
                    limits=ResolvedModuleLimits(module_files=1),
                )
            self.assertEqual(count.exception.code, "HOCUS464")
            with self.assertRaises(ModuleResolutionError) as aggregate:
                resolve_project_module_dag(
                    root, "src/main.hocus",
                    limits=ResolvedModuleLimits(aggregate_source_bytes=64),
                )
            self.assertEqual(aggregate.exception.code, "HOCUS464")

    def test_native_cycle_is_rejected_before_sealing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a_source = b'hocus 0.2; import { B } from "./b.hocus"; module A() exports () {}'
            b_source = b'hocus 0.2; import { A } from "./a.hocus"; module B() exports () {}'
            a = _module_record("modules-a/a.hocus", "A", a_source)
            b = _module_record("modules-a/b.hocus", "B", b_source)
            a["dependencies"] = [b["moduleUri"]]
            b["dependencies"] = [a["moduleUri"]]
            entry = b'hocus 0.2; import { A } from "a.hocus"; graph Main {}'
            _write_project(
                root, entry=entry, records=[a, b],
                files={"modules-a/a.hocus": a_source, "modules-a/b.hocus": b_source},
            )
            with self.assertRaises(ProjectError) as cycle:
                resolve_project_module_dag(root, "src/main.hocus")
            self.assertEqual(cycle.exception.code, "HOCUS451")

    def test_changed_during_read_and_resolution_recheck_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            with patch("hocuspocus.hocusscript.resolver._read_bounded_stable",
                       side_effect=ProjectError("HOCUS428", "changed")):
                with self.assertRaises(ProjectError) as changed:
                    resolve_project_module_dag(root, "src/main.hocus")
            self.assertEqual(changed.exception.code, "HOCUS428")

            from hocuspocus.hocusscript.resolver import _lexically_occupied as occupied
            calls = 0
            def appears(path):
                nonlocal calls
                if path.name == "root.hocus" and path.parent.name == "modules-a":
                    calls += 1
                    if calls >= 2:
                        path.write_bytes(b"hocus 0.2; module Root() exports () {}")
                        return True
                return occupied(path)
            with patch("hocuspocus.hocusscript.resolver._lexically_occupied", new=appears):
                with self.assertRaises(ProjectError) as raced:
                    resolve_project_module_dag(root, "src/main.hocus")
            self.assertEqual(raced.exception.code, "HOCUS428")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlink_escape_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside_dir:
            root, outside = Path(temporary), Path(outside_dir)
            _valid_project(root)
            (outside / "root.hocus").write_bytes(b"hocus 0.2; module Root() exports () {}")
            link = root / "modules-a/root.hocus"
            try:
                link.symlink_to(outside / "root.hocus")
            except OSError:
                self.skipTest("symlink creation not permitted")
            with self.assertRaises(ProjectError):
                resolve_project_module_dag(root, "src/main.hocus")

    def test_empty_verified_lock_allows_import_free_graph_and_preserves_01_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_project(root, entry=b"hocus 0.2; graph Main {}", records=[], files={})
            result = resolve_project_module_dag(root, "src/main.hocus")
            self.assertEqual(result.ordered_uris, ())
            (root / "src/main.hocus").write_bytes(b"hocus 0.1; graph Main {}")
            with self.assertRaises(ProjectError):
                resolve_project_module_dag(root, "src/main.hocus")

    def test_cancellation_is_checked_around_native_project_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _valid_project(root)
            calls = 0
            def cancel():
                nonlocal calls
                calls += 1
                return calls >= 2
            with self.assertRaises(ModuleResolutionError) as cancelled:
                resolve_project_module_dag(root, "src/main.hocus", cancelled=cancel)
            self.assertEqual(cancelled.exception.code, "HOCUS465")


if __name__ == "__main__":
    unittest.main()
