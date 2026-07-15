from __future__ import annotations

from copy import deepcopy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.model import ModuleDependency
from hocuspocus.hocusscript.resolved_modules import (
    ModuleResolutionError,
    ResolvedImport,
    _validate_mixed_import_edge,
    _validate_mixed_policy,
)


DIGEST = "sha256:" + "1" * 64


def _policy() -> dict:
    return {
        "schemaVersion": 1,
        "kind": "native_mixed_roots_v1",
        "projectMode": "project_and_explicit_external_roots",
        "projectPolicy": {
            "schemaVersion": 1,
            "kind": "native_project_v1",
            "projectMode": "same_project_only",
            "relativeResolution": "importer_relative_project_contained",
            "moduleDirectories": ["modules"],
            "bareResolution": "ordered_first_occupied_fail_closed",
            "externalAliases": False,
            "casePolicy": "portable",
            "linkPolicy": "reject_reparse",
        },
        "externalLibraries": [{
            "alias": "alpha",
            "libraryUid": "alpha-library",
            "libraryVersion": "1.2.3",
            "moduleManifestDigest": DIGEST,
            "entryModules": ["modules/main.hocus"],
        }],
        "projectExternalResolution": "alias_entry_modules_only",
        "externalRelativeResolution": "same_library_only",
        "externalCrossLibraryResolution": "alias_entry_modules_only",
        "externalBareResolution": "disabled",
        "externalToProject": False,
        "casePolicy": "portable",
        "linkPolicy": "reject_reparse",
    }


def _dependency(path: str) -> ModuleDependency:
    return ModuleDependency(
        f"hocus-module://alpha-library/{path}",
        "Alpha",
        path,
        "external_library",
        "alpha-library",
        "alpha",
        "1.2.3",
        DIGEST,
        DIGEST,
        DIGEST,
        DIGEST,
    )


class MixedResolutionValidationTests(unittest.TestCase):
    def test_mixed_policy_requires_exact_native_project_subpolicy(self) -> None:
        valid = _policy()
        self.assertEqual(tuple(_validate_mixed_policy(valid)), ("alpha",))

        invalid_subpolicy = deepcopy(valid)
        invalid_subpolicy["projectPolicy"] = {"anything": "accepted"}
        boolean_version = deepcopy(valid)
        boolean_version["schemaVersion"] = True
        duplicate_directories = deepcopy(valid)
        duplicate_directories["projectPolicy"]["moduleDirectories"] = ["modules", "MODULES"]
        for value in (invalid_subpolicy, boolean_version, duplicate_directories):
            with self.subTest(value=value), self.assertRaises(ModuleResolutionError) as rejected:
                _validate_mixed_policy(value)
            self.assertEqual(rejected.exception.code, "HOCUS460")

    def test_alias_import_is_bound_to_exact_manifest_entry_path(self) -> None:
        pins = _validate_mixed_policy(_policy())
        resolved = ResolvedImport(
            "@alpha/modules/main.hocus",
            "Alpha",
            "Alpha",
            "hocus-module://alpha-library/modules/other.hocus",
            None,  # type: ignore[arg-type]
        )
        with self.assertRaises(ModuleResolutionError) as rejected:
            _validate_mixed_import_edge(None, resolved, _dependency("modules/other.hocus"), pins)
        self.assertEqual(rejected.exception.code, "HOCUS462")

    def test_same_library_relative_import_is_bound_to_normalized_target_path(self) -> None:
        pins = _validate_mixed_policy(_policy())
        importer = _dependency("modules/main.hocus")
        resolved = ResolvedImport(
            "./helper.hocus",
            "Alpha",
            "Alpha",
            "hocus-module://alpha-library/other/helper.hocus",
            None,  # type: ignore[arg-type]
        )
        with self.assertRaises(ModuleResolutionError) as rejected:
            _validate_mixed_import_edge(
                importer, resolved, _dependency("other/helper.hocus"), pins,
            )
        self.assertEqual(rejected.exception.code, "HOCUS462")


if __name__ == "__main__":
    unittest.main()
