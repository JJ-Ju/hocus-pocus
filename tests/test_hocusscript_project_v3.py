from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import (
    ProjectContext,
    ProjectError,
    compile_path,
    update_project_lock,
    verify_project_lock,
)
from hocuspocus.hocusscript.project import ExternalLibraryAlias, _validate_module_locks
import hocuspocus.hocusscript.project as project_module


DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)
DIGEST_C = "sha256:" + ("c" * 64)


def _manifest(*, module_directories: str = '["modules", "vendor"]', version: str = "0.2") -> str:
    return f'''schema_version = 3
[project]
uid = "local-project"
source_directories = ["src"]
module_directories = {module_directories}
[language]
version = "{version}"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
[external_aliases.studio]
library_uid = "studio-library"
version = "1.2.3"
module_manifest_digest = "{DIGEST_A}"
'''


def _project(root: Path, *, manifest: str | None = None) -> None:
    for directory in ("src", "modules", "vendor", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "hocus.project.toml").write_text(manifest or _manifest(), encoding="utf-8")
    shutil.copyfile(
        ROOT / "tests" / "fixtures" / "hocusscript" / "catalog" / "catalog-v1.json",
        root / "catalog" / "catalog.json",
    )


def _module_records() -> list[dict]:
    external_uri = "hocus-module://studio-library/math/noise.hocus"
    local_uri = "hocus-project://local-project/tools/build.hocus"
    return [
        {
            "moduleUri": external_uri,
            "projectUid": None,
            "libraryUid": "studio-library",
            "libraryVersion": "1.2.3",
            "moduleManifestDigest": DIGEST_A,
            "languageVersion": "0.2",
            "sourcePath": "math/noise.hocus",
            "contentDigest": DIGEST_B,
            "interfaceDigest": DIGEST_C,
            "transitiveDigest": DIGEST_A,
            "dependencies": [],
            "externalAlias": "studio",
        },
        {
            "moduleUri": local_uri,
            "projectUid": "local-project",
            "libraryUid": None,
            "libraryVersion": None,
            "moduleManifestDigest": None,
            "languageVersion": "0.2",
            "sourcePath": "tools/build.hocus",
            "contentDigest": DIGEST_A,
            "interfaceDigest": DIGEST_B,
            "transitiveDigest": DIGEST_C,
            "dependencies": [external_uri],
            "externalAlias": None,
        },
    ]


class HocusScriptProjectV3Tests(unittest.TestCase):
    def test_v3_ordered_roots_aliases_and_explicit_lock_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            preview = ProjectContext.load(root, validate_lock=False)
            self.assertEqual(preview.manifest_version, 3)
            self.assertEqual(
                preview.module_directories,
                ((root / "modules").resolve(), (root / "vendor").resolve()),
            )
            self.assertEqual(preview.external_aliases[0].alias, "studio")
            self.assertEqual(preview.external_aliases[0].library_uid, "studio-library")
            self.assertEqual(preview.external_aliases[0].library_version, "1.2.3")

            with self.assertRaises(ProjectError) as denied:
                update_project_lock(root, _module_records())
            self.assertEqual(denied.exception.code, "HOCUS455")
            self.assertFalse((root / "pins" / "hocus.lock.json").exists())

            with self.assertRaises(ProjectError) as modules_disabled:
                update_project_lock(root, _module_records(), allow_write=True)
            self.assertEqual(modules_disabled.exception.code, "HOCUS456")
            created = update_project_lock(root, [], allow_write=True)
            self.assertEqual(created.modules, ())
            context = ProjectContext.load(root)
            self.assertEqual(context.language_version, "0.2")
            self.assertEqual(context.locked_modules, created.modules)
            (root / "src" / "main.hocus").write_text(
                'hocus 0.1; graph demo { target "/obj/geo1"; }', encoding="utf-8"
            )
            with self.assertRaises(ProjectError) as disabled:
                compile_path("src/main.hocus", project_directory=root)
            self.assertEqual(disabled.exception.code, "HOCUS456")

            lock_path = root / "pins" / "hocus.lock.json"
            before = lock_path.read_bytes()
            verified = verify_project_lock(root)
            self.assertEqual(verified.lock_digest, created.lock_digest)
            self.assertEqual(lock_path.read_bytes(), before)
            self.assertEqual(json.loads(before)["schemaVersion"], 3)

    def test_update_requires_expected_digest_and_rechecks_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            created = update_project_lock(root, [], allow_write=True)
            lock_path = root / "pins" / "hocus.lock.json"
            original = lock_path.read_bytes()
            for expected in (None, DIGEST_B):
                with self.assertRaises(ProjectError) as rejected:
                    update_project_lock(
                        root, [], expected_lock_digest=expected, allow_write=True
                    )
                self.assertEqual(rejected.exception.code, "HOCUS453")
                self.assertEqual(lock_path.read_bytes(), original)

            target = "hocuspocus.hocusscript.project._canonical_lock_file_digest"
            with patch(target, side_effect=[created.lock_digest, DIGEST_C]):
                with self.assertRaises(ProjectError) as raced:
                    update_project_lock(
                        root,
                        [],
                        expected_lock_digest=created.lock_digest,
                        allow_write=True,
                    )
            self.assertEqual(raced.exception.code, "HOCUS453")
            self.assertEqual(lock_path.read_bytes(), original)

    def test_create_is_no_overwrite_if_lock_appears_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            lock_path = root / "pins" / "hocus.lock.json"

            def competing_create(_temporary, destination):
                Path(destination).write_bytes(b"competing-writer")
                raise FileExistsError(destination)

            with patch("hocuspocus.hocusscript.project.os.link", side_effect=competing_create):
                with self.assertRaises(ProjectError) as raced:
                    update_project_lock(root, [], allow_write=True)
            self.assertEqual(raced.exception.code, "HOCUS453")
            self.assertEqual(lock_path.read_bytes(), b"competing-writer")

    def test_update_lease_rechecks_inputs_and_returns_its_written_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            lease = root / "pins" / ".hocus.lock.json.update-lease"
            lease.write_text("busy", encoding="utf-8")
            with self.assertRaises(ProjectError) as busy:
                update_project_lock(root, [], allow_write=True)
            self.assertEqual(busy.exception.code, "HOCUS453")
            self.assertFalse((root / "pins" / "hocus.lock.json").exists())
            lease.unlink()

            original_recheck = project_module._recheck_update_inputs

            def mutate_catalog(project, **kwargs):
                assert project.catalog_path is not None
                project.catalog_path.write_bytes(project.catalog_path.read_bytes() + b" ")
                return original_recheck(project, **kwargs)

            with patch(
                "hocuspocus.hocusscript.project._recheck_update_inputs",
                side_effect=mutate_catalog,
            ):
                with self.assertRaises(ProjectError) as changed:
                    update_project_lock(root, [], allow_write=True)
            self.assertEqual(changed.exception.code, "HOCUS453")
            self.assertFalse((root / "pins" / "hocus.lock.json").exists())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            with patch(
                "hocuspocus.hocusscript.project.verify_project_lock",
                side_effect=AssertionError("post-write verification must not run"),
            ):
                result = update_project_lock(root, [], allow_write=True)
            self.assertEqual(result.modules, ())
            self.assertEqual(result.lock_digest, verify_project_lock(root).lock_digest)

    def test_nonempty_iterables_fail_closed_and_generation_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            pulls = 0

            def unbounded():
                nonlocal pulls
                while True:
                    pulls += 1
                    yield _module_records()[0]

            with self.assertRaises(ProjectError) as disabled:
                update_project_lock(root, unbounded(), allow_write=True)
            self.assertEqual(disabled.exception.code, "HOCUS456")
            self.assertEqual(pulls, 1)
            self.assertFalse((root / "pins" / "hocus.lock.json").exists())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            with patch("hocuspocus.hocusscript.project.MAX_LOCK_BYTES_V3", 1):
                with self.assertRaises(ProjectError) as oversized:
                    update_project_lock(root, [], allow_write=True)
            self.assertEqual(oversized.exception.code, "HOCUS410")
            self.assertFalse((root / "pins" / "hocus.lock.json").exists())

    def test_manifest_paths_aliases_and_language_are_adversarially_validated(self) -> None:
        invalid_manifests = (
            _manifest(module_directories='["../escape"]'),
            _manifest(module_directories='["C:/escape"]'),
            _manifest(version="0.1"),
            _manifest() + '\n[external_aliases.bad]\nlibrary_uid = "x"\nversion = "latest"\n',
            _manifest() + '\n[external_aliases.pathful]\nlibrary_uid = "other"\nversion = "1.0.0"\npath = "../outside"\n',
            _manifest() + '\n[external_aliases.Studio]\nlibrary_uid = "other"\nversion = "1.0.0"\n',
            _manifest() + '\n[external_aliases.studio_lib]\nlibrary_uid = "other"\nversion = "1.0.0"\n',
            _manifest() + '\n[external_aliases.second]\nlibrary_uid = "studio-library"\nversion = "2.0.0"\n',
            _manifest() + '\n[external_aliases.bad-semver]\nlibrary_uid = "other"\nversion = "1.0.0-01"\n',
            _manifest(module_directories='["CON"]'),
            _manifest(module_directories='["modules./nested"]'),
        )
        for manifest in invalid_manifests:
            with self.subTest(manifest=manifest[-100:]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _project(root, manifest=manifest)
                with self.assertRaises(ProjectError):
                    ProjectContext.load(root, validate_lock=False)

        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside:
            root = Path(temporary)
            _project(root)
            module_root = root / "modules"
            module_root.rmdir()
            try:
                module_root.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable")
            with self.assertRaises(ProjectError) as escaped:
                ProjectContext.load(root, validate_lock=False)
            self.assertEqual(escaped.exception.code, "HOCUS409" if escaped.exception.code == "HOCUS409" else "HOCUS449")

    def test_compile_gate_precedes_v3_lock_and_catalog_loading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            (root / "pins" / "hocus.lock.json").write_text("not-json", encoding="utf-8")
            (root / "src" / "main.hocus").write_text("hocus 0.2;", encoding="utf-8")
            with patch(
                "hocuspocus.hocusscript.project._load_lock",
                side_effect=AssertionError("disabled compile must not load v3 lock"),
            ):
                with self.assertRaises(ProjectError) as disabled:
                    compile_path("src/main.hocus", project_directory=root)
            self.assertEqual(disabled.exception.code, "HOCUS456")

    def test_v1_and_v2_projects_hydrate_empty_v3_fields_without_migration_writes(self) -> None:
        manifests = (
            'schema_version = 1\n[project]\nuid = "legacy-one"\n',
            'schema_version = 2\n[project]\nuid = "legacy-two"\n'
            '[lock]\npolicy = "required"\npath = "pins/lock.json"\n'
            '[catalog]\npath = "catalog/catalog.json"\n',
        )
        for version, manifest in enumerate(manifests, 1):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "hocus.project.toml").write_text(manifest, encoding="utf-8")
                before = (root / "hocus.project.toml").read_bytes()
                context = ProjectContext.load(root, validate_lock=False)
                self.assertEqual(context.manifest_version, version)
                self.assertEqual(context.module_directories, ())
                self.assertEqual(context.external_aliases, ())
                self.assertEqual(context.locked_modules, ())
                self.assertEqual((root / "hocus.project.toml").read_bytes(), before)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = (
                'schema_version = 2\n[project]\nuid = "legacy-two"\n'
                '[language]\nversion = "0.2"\n'
                '[lock]\npolicy = "required"\npath = "pins/lock.json"\n'
                '[catalog]\npath = "catalog/catalog.json"\n'
            )
            (root / "hocus.project.toml").write_text(manifest, encoding="utf-8")
            with self.assertRaises(ProjectError) as rejected:
                ProjectContext.load(root, validate_lock=False)
            self.assertEqual(rejected.exception.code, "HOCUS421")

    def test_module_lock_rejects_alias_drift_uri_drift_cycles_and_language_02(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            cases = []
            alias_drift = _module_records()
            alias_drift[0]["libraryVersion"] = "2.0.0"
            cases.append(alias_drift)
            uri_drift = _module_records()
            uri_drift[0]["moduleUri"] = "hocus-project://studio-library/math/noise.hocus"
            cases.append(uri_drift)
            language = _module_records()
            language[0]["languageVersion"] = "0.1"
            cases.append(language)
            cycle = _module_records()
            cycle[0]["dependencies"] = [cycle[1]["moduleUri"]]
            cases.append(cycle)
            aliases = ProjectContext.load(root, validate_lock=False).external_aliases
            for records in cases:
                with self.subTest(records=records), self.assertRaises(ProjectError) as rejected:
                    _validate_module_locks(
                        records, project_uid="local-project", external_aliases=aliases
                    )
                self.assertEqual(rejected.exception.code, "HOCUS451")
                self.assertFalse((root / "pins" / "hocus.lock.json").exists())

    def test_module_lock_enforces_portable_identity_library_coherence_and_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            aliases = ProjectContext.load(root, validate_lock=False).external_aliases

            case_alias = _module_records()[1]
            upper = dict(case_alias)
            upper["sourcePath"] = "Tools/Build.hocus"
            upper["moduleUri"] = "hocus-project://local-project/Tools/Build.hocus"
            lower = dict(case_alias)
            lower["dependencies"] = []
            with self.assertRaises(ProjectError) as duplicate:
                _validate_module_locks(
                    sorted([upper, lower], key=lambda item: item["moduleUri"]),
                    project_uid="local-project",
                    external_aliases=aliases,
                )
            self.assertEqual(duplicate.exception.code, "HOCUS451")

            external_one = dict(_module_records()[0])
            external_two = dict(external_one)
            external_two["sourcePath"] = "math/vector.hocus"
            external_two["moduleUri"] = "hocus-module://studio-library/math/vector.hocus"
            external_two["moduleManifestDigest"] = DIGEST_B
            with self.assertRaises(ProjectError) as incoherent:
                _validate_module_locks(
                    sorted([external_one, external_two], key=lambda item: item["moduleUri"]),
                    project_uid="local-project",
                    external_aliases=(
                        ExternalLibraryAlias("studio", "studio-library", "1.2.3", None),
                    ),
                )
            self.assertEqual(incoherent.exception.code, "HOCUS451")

            def chain(count: int) -> list[dict]:
                records = []
                for index in range(count):
                    path = f"m{index:04d}.hocus"
                    uri = f"hocus-project://local-project/{path}"
                    dependency = (
                        []
                        if index == count - 1
                        else [f"hocus-project://local-project/m{index + 1:04d}.hocus"]
                    )
                    records.append({
                        "moduleUri": uri,
                        "projectUid": "local-project",
                        "libraryUid": None,
                        "libraryVersion": None,
                        "moduleManifestDigest": None,
                        "languageVersion": "0.2",
                        "sourcePath": path,
                        "contentDigest": DIGEST_A,
                        "interfaceDigest": DIGEST_B,
                        "transitiveDigest": DIGEST_C,
                        "dependencies": dependency,
                        "externalAlias": None,
                    })
                return records

            self.assertEqual(
                len(_validate_module_locks(
                    chain(64), project_uid="local-project", external_aliases=()
                )),
                64,
            )
            with self.assertRaises(ProjectError) as too_deep:
                _validate_module_locks(
                    chain(65), project_uid="local-project", external_aliases=()
                )
            self.assertEqual(too_deep.exception.code, "HOCUS451")

    def test_v3_schemas_accept_exact_contract_and_reject_physical_alias_paths(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema is not installed")
        project_schema = json.loads(
            (ROOT / "docs" / "schemas" / "hocus-project-v3.schema.json").read_text("utf-8")
        )
        lock_schema = json.loads(
            (ROOT / "docs" / "schemas" / "hocus-lock-v3.schema.json").read_text("utf-8")
        )
        Draft202012Validator.check_schema(project_schema)
        Draft202012Validator.check_schema(lock_schema)
        manifest = {
            "schema_version": 3,
            "project": {
                "uid": "local-project",
                "source_directories": ["src"],
                "module_directories": ["modules", "vendor"],
            },
            "language": {"version": "0.2"},
            "lock": {"policy": "required", "path": "pins/hocus.lock.json"},
            "catalog": {"path": "catalog/catalog.json"},
            "external_aliases": {
                "studio": {
                    "library_uid": "studio-library",
                    "version": "1.2.3",
                    "module_manifest_digest": DIGEST_A,
                }
            },
        }
        Draft202012Validator(project_schema).validate(manifest)
        pathful = json.loads(json.dumps(manifest))
        pathful["external_aliases"]["studio"]["path"] = "../studio"
        self.assertTrue(list(Draft202012Validator(project_schema).iter_errors(pathful)))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root)
            update_project_lock(root, [], allow_write=True)
            lock = json.loads((root / "pins" / "hocus.lock.json").read_text("utf-8"))
        Draft202012Validator(lock_schema).validate(lock)
        invalid = json.loads(json.dumps(lock))
        invalid["modules"] = _module_records()
        invalid["modules"][0]["externalAlias"] = None
        self.assertTrue(list(Draft202012Validator(lock_schema).iter_errors(invalid)))


if __name__ == "__main__":
    unittest.main()
