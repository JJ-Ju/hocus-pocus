from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    LockVerificationResult, ModuleLockRecord, ModuleResolutionError, ModuleSourceEnvelope,
    ResolvedImport, ResolvedModuleLimits, compile_source, module_interface_digest,
    module_source_digest, module_transitive_digest, validate_resolved_module_dag,
)
from hocuspocus.hocusscript.parser import parse_syntax


DIGEST = "sha256:" + "a" * 64
PROJECT = "city"
ENTRY = "hocus-project://city/main.hocus"
POLICY = {"resolution": ["relative", "module_directories"], "casePolicy": "portable"}
POLICY_DIGEST = module_interface_digest(POLICY)


@dataclass(frozen=True)
class Fixture:
    name: str
    envelope: ModuleSourceEnvelope
    lock: ModuleLockRecord


def _module(name: str, dependencies: tuple[Fixture, ...] = ()) -> Fixture:
    relative = f"modules/{name.lower()}.hocus"
    uri = f"hocus-project://{PROJECT}/{relative}"
    imports_text = "\n".join(
        f'import {{ {item.name} }} from "./{item.name.lower()}.hocus";'
        for item in dependencies
    )
    source = (f"hocus 0.2;\n{imports_text}\nmodule {name}() exports () {{}}").encode()
    syntax = parse_syntax(source.decode(), uri)
    targets = {item.name: item.lock.module_uri for item in dependencies}
    imports = tuple(
        ResolvedImport(item.specifier, item.imported_name, item.local_name,
                       targets[item.imported_name], item.span)
        for item in syntax.imports
    )
    interface = {"schemaVersion": 1, "moduleName": name, "parameters": [], "exports": []}
    source_digest = module_source_digest(source)
    interface_digest = module_interface_digest(interface)
    dependency_uris = tuple(sorted(item.lock.module_uri for item in dependencies))
    transitive = module_transitive_digest(
        uri=uri, source_digest=source_digest, interface_digest=interface_digest,
        dependencies=((item.lock.module_uri, item.lock.transitive_digest)
                      for item in sorted(dependencies, key=lambda value: value.lock.module_uri)),
    )
    lock = ModuleLockRecord(
        uri, PROJECT, None, None, None, "0.2", relative, source_digest,
        interface_digest, transitive, dependency_uris, None,
    )
    return Fixture(name, ModuleSourceEnvelope(uri, source, imports), lock)


def _entry(roots: tuple[Fixture, ...], uri: str = ENTRY) -> tuple[bytes, tuple[ResolvedImport, ...]]:
    declarations = "\n".join(
        f'import {{ {item.name} }} from "modules/{item.name.lower()}.hocus";'
        for item in roots
    )
    source = f"hocus 0.2;\n{declarations}\ngraph Main {{}}".encode()
    syntax = parse_syntax(source.decode(), uri)
    targets = {item.name: item.lock.module_uri for item in roots}
    imports = tuple(
        ResolvedImport(item.specifier, item.imported_name, item.local_name,
                       targets[item.imported_name], item.span)
        for item in syntax.imports
    )
    return source, imports


def _validate(fixtures, *, roots=None, lock_records=None, entry=None, entry_imports=None,
              entry_uri=ENTRY, **kwargs):
    fixtures = tuple(fixtures)
    selected_roots = tuple(roots) if roots is not None else fixtures
    source, imports = _entry(selected_roots, entry_uri)
    return validate_resolved_module_dag(
        (item.envelope for item in fixtures),
        lock_verification=LockVerificationResult(
            PROJECT, DIGEST, DIGEST,
            tuple(lock_records) if lock_records is not None else tuple(item.lock for item in fixtures),
        ),
        entry_source_uri=entry_uri,
        entry_source=source if entry is None else entry,
        entry_imports=imports if entry_imports is None else entry_imports,
        resolver_policy=POLICY,
        resolver_policy_digest=POLICY_DIGEST,
        **kwargs,
    )


class ResolvedModuleDagTests(unittest.TestCase):
    def test_catalog_pins_are_paired_strict_and_sealed_but_optional_for_pure_callers(self) -> None:
        leaf = _module("Leaf")
        unpinned = _validate((leaf,), roots=(leaf,))
        self.assertIsNone(unpinned.catalog_content_digest)
        self.assertIsNone(unpinned.catalog_fingerprint)
        fingerprint = "sha256:" + "b" * 64
        pinned = _validate(
            (leaf,), roots=(leaf,),
            catalog_content_digest=DIGEST, catalog_fingerprint=fingerprint,
        )
        self.assertEqual(pinned.catalog_content_digest, DIGEST)
        self.assertEqual(pinned.catalog_fingerprint, fingerprint)
        self.assertNotEqual(pinned.handoff_digest, unpinned.handoff_digest)
        for kwargs in (
            {"catalog_content_digest": DIGEST},
            {"catalog_fingerprint": fingerprint},
            {"catalog_content_digest": "bad", "catalog_fingerprint": fingerprint},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ModuleResolutionError) as rejected:
                _validate((leaf,), roots=(leaf,), **kwargs)
            self.assertEqual(rejected.exception.code, "HOCUS461")

    def test_verified_reachable_dag_is_exact_sorted_and_schema_valid(self) -> None:
        alpha, zulu = _module("Alpha"), _module("Zulu")
        root = _module("Root", (zulu, alpha))
        result = _validate((root, zulu, alpha), roots=(root,))
        self.assertEqual(result.ordered_uris, (alpha.lock.module_uri, zulu.lock.module_uri, root.lock.module_uri))
        self.assertIs(result.sources_by_uri[alpha.lock.module_uri], alpha.envelope.source)
        schema = json.loads((ROOT / "docs/schemas/resolved-module-set-v1.schema.json").read_text())
        Draft202012Validator(schema).validate(result.resolved_module_set)

    def test_lock_is_authority_for_identity_content_interface_and_dependencies(self) -> None:
        leaf = _module("Leaf")
        corruptions = (
            dataclasses.replace(leaf.lock, content_digest=DIGEST),
            dataclasses.replace(leaf.lock, interface_digest=DIGEST),
            dataclasses.replace(leaf.lock, transitive_digest=DIGEST),
            dataclasses.replace(leaf.lock, source_path="modules/other.hocus"),
            dataclasses.replace(leaf.lock, dependencies=("hocus-project://city/modules/missing.hocus",)),
        )
        for locked in corruptions:
            with self.subTest(locked=locked), self.assertRaises(ModuleResolutionError):
                _validate((leaf,), roots=(leaf,), lock_records=(locked,))
        with self.assertRaises(ModuleResolutionError):
            _validate((leaf,), roots=(leaf,), lock_records=())

    def test_entry_bytes_import_spans_reachability_and_missing_closure_are_enforced(self) -> None:
        leaf, unused = _module("Leaf"), _module("Unused")
        source, imports = _entry((leaf,))
        with self.assertRaises(ModuleResolutionError):
            _validate((leaf,), roots=(leaf,), entry=b"hocus 0.2; module Wrong() exports () {}")
        with self.assertRaises(ModuleResolutionError):
            _validate((leaf,), roots=(leaf,), entry_imports=())
        with self.assertRaises(ModuleResolutionError):
            _validate((leaf, unused), roots=(leaf,), entry=source, entry_imports=imports)
        parent = _module("Parent", (leaf,))
        with self.assertRaises(ModuleResolutionError):
            _validate((parent,), roots=(parent,), lock_records=(parent.lock, leaf.lock))

    def test_entry_and_module_budgets_are_o1_bounded_and_cancellable(self) -> None:
        leaf = _module("Leaf")
        limits = dataclasses.replace(ResolvedModuleLimits(), aggregate_source_bytes=20)
        with self.assertRaises(ModuleResolutionError) as aggregate:
            _validate((), roots=(), limits=limits)
        self.assertEqual(aggregate.exception.code, "HOCUS464")
        hostile = dataclasses.replace(
            leaf.envelope,
            imports=tuple(ResolvedImport("x.hocus", "X", f"X{i}", leaf.lock.module_uri,
                                         parse_syntax(leaf.envelope.source.decode(), leaf.lock.module_uri).span)
                          for i in range(2)),
        )
        with self.assertRaises(ModuleResolutionError) as bounded:
            _validate((dataclasses.replace(leaf, envelope=hostile),), roots=(leaf,),
                      limits=dataclasses.replace(ResolvedModuleLimits(), module_files=1))
        self.assertEqual(bounded.exception.code, "HOCUS464")
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaises(ModuleResolutionError) as cancelled:
            _validate((leaf,), roots=(leaf,), cancelled=cancel)
        self.assertEqual(cancelled.exception.code, "HOCUS465")
        large_lock = tuple(
            dataclasses.replace(
                leaf.lock,
                module_uri=f"hocus-project://city/modules/unrelated{i}.hocus",
                source_path=f"modules/unrelated{i}.hocus",
            )
            for i in range(100)
        )
        checks = 0
        def cancel_large():
            nonlocal checks
            checks += 1
            return checks >= 8
        with self.assertRaises(ModuleResolutionError) as large_cancelled:
            _validate((leaf,), roots=(leaf,), lock_records=(leaf.lock, *large_lock),
                      cancelled=cancel_large)
        self.assertEqual(large_cancelled.exception.code, "HOCUS465")

    def test_external_modules_and_entry_uri_as_module_fail_closed(self) -> None:
        leaf = _module("Leaf")
        external = dataclasses.replace(
            leaf.lock, module_uri="hocus-module://vendor/modules/leaf.hocus",
            project_uid=None, library_uid="vendor", library_version="1.0.0",
            module_manifest_digest=DIGEST, external_alias="vendor-lib",
        )
        external_envelope = dataclasses.replace(leaf.envelope, uri=external.module_uri)
        with self.assertRaises(ModuleResolutionError):
            _validate((Fixture("Leaf", external_envelope, external),), roots=(), lock_records=(external,))
        entry_lock = dataclasses.replace(leaf.lock, module_uri=ENTRY, source_path="main.hocus")
        entry_envelope = dataclasses.replace(leaf.envelope, uri=ENTRY)
        with self.assertRaises(ModuleResolutionError):
            _validate((Fixture("Leaf", entry_envelope, entry_lock),), roots=(), lock_records=(entry_lock,))

    def test_portable_paths_and_bounded_module_names_are_enforced(self) -> None:
        leaf = _module("Leaf")
        for path in ("modules/CON.hocus", "modules/leaf.hocus.", "modules/e\u0301.hocus"):
            locked = dataclasses.replace(
                leaf.lock, source_path=path,
                module_uri=f"hocus-project://city/{path}",
            )
            envelope = dataclasses.replace(leaf.envelope, uri=locked.module_uri)
            with self.subTest(path=path), self.assertRaises(ModuleResolutionError):
                _validate((Fixture("Leaf", envelope, locked),), roots=(), lock_records=(locked,))
        entry_alias_lock = dataclasses.replace(
            leaf.lock, module_uri="hocus-project://city/Main.hocus", source_path="Main.hocus",
        )
        entry_alias = dataclasses.replace(leaf.envelope, uri=entry_alias_lock.module_uri)
        with self.assertRaises(ModuleResolutionError):
            _validate((Fixture("Leaf", entry_alias, entry_alias_lock),), roots=(),
                      lock_records=(entry_alias_lock,))
        long_name = "M" * 129
        source = f"hocus 0.2; module {long_name}() exports () {{}}".encode()
        long = dataclasses.replace(leaf.envelope, source=source)
        locked = dataclasses.replace(leaf.lock, content_digest=module_source_digest(source))
        with self.assertRaises(ModuleResolutionError):
            _validate((Fixture(long_name, long, locked),), roots=(), lock_records=(locked,))

    def test_content_only_cancellation_errors_and_language_01_are_preserved(self) -> None:
        leaf = _module("Leaf")
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem")):
            self.assertEqual(_validate((leaf,), roots=(leaf,)).sources_by_uri[leaf.lock.module_uri], leaf.envelope.source)
        with self.assertRaises(ModuleResolutionError) as failed:
            _validate((leaf,), roots=(leaf,), cancelled=mock.Mock(side_effect=RuntimeError("secret")))
        self.assertNotIn("secret", failed.exception.message)
        self.assertTrue(compile_source('hocus 0.1; graph g { target "/obj/g"; }', "g").valid)
        self.assertFalse(compile_source('hocus 0.2; graph g {}', "g").valid)


if __name__ == "__main__":
    unittest.main()
