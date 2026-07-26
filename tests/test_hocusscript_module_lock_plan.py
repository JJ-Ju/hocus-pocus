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

from hocuspocus.hocusscript import plan_project_module_lock
from hocuspocus.hocusscript.expander import ModuleExpansionError
from hocuspocus.hocusscript.module_lock_plan_result import _prospective_lock_payload
from hocuspocus.hocusscript.project import ProjectError
from hocuspocus.hocusscript.resolved_modules import (
    ModuleResolutionError,
    ResolvedModuleLimits,
    module_source_digest,
    module_transitive_digest,
)
from hocuspocus.hocusscript.resolver import resolve_project_module_dag
from test_hocusscript_external_roots import (
    _digest,
    _library_manifest,
    _write_library,
    _write_project,
)


PROJECT_UID = "external-root-project"


def _write_source(path: Path, source: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)


def _fixture(base: Path, *, pinned: bool = True) -> tuple[Path, Path, Path]:
    project, alpha, beta = base / "project", base / "alpha", base / "beta"
    alpha_manifest = _library_manifest("alpha-library", "1.2.3")
    beta_manifest = _library_manifest("beta-library", "2.0.0", ("main.hocus",))
    _write_library(alpha, alpha_manifest)
    _write_library(beta, beta_manifest)
    _write_project(project, (
        ("alpha", "alpha-library", "1.2.3", _digest(alpha_manifest) if pinned else None),
        ("beta", "beta-library", "2.0.0", _digest(beta_manifest)),
    ))
    _write_source(
        project / "src/main.hocus",
        b'hocus 0.2; import { Local } from "local.hocus"; '
        b'graph Main { target "/obj/main"; }',
    )
    _write_source(
        project / "modules/local.hocus",
        b'hocus 0.2; import { Alpha } from "@alpha/modules/main.hocus"; '
        b'module Local() exports () {}',
    )
    _write_source(
        alpha / "modules/main.hocus",
        b'hocus 0.2; import { Helper } from "./helper.hocus"; '
        b'import { Beta } from "@beta/main.hocus"; module Alpha() exports () {}',
    )
    _write_source(alpha / "modules/helper.hocus", b"hocus 0.2; module Helper() exports () {}")
    _write_source(beta / "main.hocus", b"hocus 0.2; module Beta() exports () {}")
    return project, alpha, beta


def _plan(project: Path, alpha: Path, beta: Path, **kwargs):
    return plan_project_module_lock(
        project,
        ["src/main.hocus"],
        {"beta": beta, "alpha": alpha},
        **kwargs,
    )


def _publish_test_lock(project: Path, result) -> None:
    # Test setup only: G2 itself must remain read-only.
    payload = _prospective_lock_payload(result)
    (project / "pins/hocus.lock.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )


class MixedModuleLockPlanTests(unittest.TestCase):
    def test_mixed_closure_relative_and_cross_library_provenance_and_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            result = _plan(project, alpha, beta)
            records = {item.module_uri: item for item in result.modules}
            expected_uris = {
                f"hocus-project://{PROJECT_UID}/modules/local.hocus",
                "hocus-module://alpha-library/modules/helper.hocus",
                "hocus-module://alpha-library/modules/main.hocus",
                "hocus-module://beta-library/main.hocus",
            }
            self.assertEqual(set(records), expected_uris)
            self.assertEqual(result.added_uris, tuple(sorted(expected_uris)))
            self.assertEqual(result.removed_uris, ())
            self.assertEqual(result.changed_uris, ())

            local = records[f"hocus-project://{PROJECT_UID}/modules/local.hocus"]
            self.assertEqual((local.project_uid, local.external_alias), (PROJECT_UID, None))
            self.assertIsNone(local.library_uid)
            alpha_main = records["hocus-module://alpha-library/modules/main.hocus"]
            self.assertEqual(
                (
                    alpha_main.project_uid,
                    alpha_main.library_uid,
                    alpha_main.library_version,
                    alpha_main.external_alias,
                ),
                (None, "alpha-library", "1.2.3", "alpha"),
            )
            self.assertEqual(alpha_main.module_manifest_digest, _digest(
                (alpha / "hocus.module.toml").read_bytes()
            ))
            beta_main = records["hocus-module://beta-library/main.hocus"]
            self.assertEqual(
                (beta_main.library_uid, beta_main.library_version, beta_main.external_alias),
                ("beta-library", "2.0.0", "beta"),
            )

            native_sources = {
                local.module_uri: project / local.source_path,
                alpha_main.module_uri: alpha / alpha_main.source_path,
                beta_main.module_uri: beta / beta_main.source_path,
                "hocus-module://alpha-library/modules/helper.hocus": alpha / "modules/helper.hocus",
            }
            for uri, record in records.items():
                self.assertEqual(record.content_digest, module_source_digest(native_sources[uri].read_bytes()))
                self.assertEqual(
                    record.transitive_digest,
                    module_transitive_digest(
                        uri=uri,
                        source_digest=record.content_digest,
                        interface_digest=record.interface_digest,
                        dependencies=(
                            (child, records[child].transitive_digest)
                            for child in record.dependencies
                        ),
                    ),
                )
            self.assertEqual(
                alpha_main.dependencies,
                (
                    "hocus-module://alpha-library/modules/helper.hocus",
                    "hocus-module://beta-library/main.hocus",
                ),
            )

    def test_exact_added_changed_removed_diff_against_current_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            initial = _plan(project, alpha, beta)
            _publish_test_lock(project, initial)
            unchanged = _plan(project, alpha, beta)
            self.assertFalse(unchanged.changed)
            self.assertEqual((unchanged.added_uris, unchanged.removed_uris, unchanged.changed_uris), ((), (), ()))

            _write_source(
                alpha / "modules/helper.hocus",
                b"hocus 0.2; module Helper(value: int = 2) exports () {}",
            )
            changed = _plan(project, alpha, beta)
            self.assertEqual(changed.added_uris, ())
            self.assertEqual(changed.removed_uris, ())
            self.assertEqual(changed.changed_uris, (
                "hocus-module://alpha-library/modules/helper.hocus",
                "hocus-module://alpha-library/modules/main.hocus",
                f"hocus-project://{PROJECT_UID}/modules/local.hocus",
            ))

            _publish_test_lock(project, changed)
            _write_source(
                project / "src/main.hocus",
                b'hocus 0.2; import { Beta } from "@beta/main.hocus"; '
                b'graph Main { target "/obj/main"; }',
            )
            removed = _plan(project, alpha, beta)
            self.assertEqual(removed.added_uris, ())
            self.assertEqual(removed.changed_uris, ())
            self.assertEqual(removed.removed_uris, (
                "hocus-module://alpha-library/modules/helper.hocus",
                "hocus-module://alpha-library/modules/main.hocus",
                f"hocus-project://{PROJECT_UID}/modules/local.hocus",
            ))

    def test_relocation_path_free_deterministic_and_read_only(self) -> None:
        payloads = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory in (first, second):
                base = Path(directory)
                project, alpha, beta = _fixture(base)
                before = _tree_snapshot(base)
                result = _plan(project, alpha, beta)
                after = _tree_snapshot(base)
                self.assertEqual(after, before)
                payload = result.to_dict()
                rendered = json.dumps(payload, sort_keys=True) + repr(result)
                for native in (project, alpha, beta, base):
                    self.assertNotIn(str(native), rendered)
                payloads.append(payload)
            self.assertEqual(payloads[0], payloads[1])

    def test_manifest_entry_gate_and_unpinned_root_fail_closed(self) -> None:
        for mode, code in (("private", "HOCUS462"), ("unpinned", "HOCUS459")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                project, alpha, beta = _fixture(Path(temporary), pinned=mode != "unpinned")
                if mode == "private":
                    _write_source(
                        project / "modules/local.hocus",
                        b'hocus 0.2; import { Helper } from "@alpha/modules/helper.hocus"; '
                        b'module Local() exports () {}',
                    )
                with self.assertRaises(ProjectError) as rejected:
                    _plan(project, alpha, beta)
                self.assertEqual(rejected.exception.code, code)

    def test_external_bare_escape_and_unapproved_alias_imports_are_rejected(self) -> None:
        cases = (
            (b'hocus 0.2; import { Helper } from "helper.hocus"; module Alpha() exports () {}', "HOCUS460"),
            (b'hocus 0.2; import { Escape } from "../../escape.hocus"; module Alpha() exports () {}', "HOCUS460"),
            (b'hocus 0.2; import { Other } from "@unknown/main.hocus"; module Alpha() exports () {}', "HOCUS460"),
            (b'hocus 0.2; import { Alpha } from "@alpha/modules/main.hocus"; module Alpha() exports () {}', "HOCUS460"),
            (b'hocus 0.2; module WrongName() exports () {}', "HOCUS462"),
        )
        for source, code in cases:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                project, alpha, beta = _fixture(base)
                _write_source(alpha / "modules/main.hocus", source)
                _write_source(base / "escape.hocus", b"hocus 0.2; module Escape() exports () {}")
                with self.assertRaises(ProjectError) as rejected:
                    _plan(project, alpha, beta)
                self.assertEqual(rejected.exception.code, code)

    def test_limits_cycles_cancellation_and_races_fail_closed_without_writes(self) -> None:
        limit_cases = (
            ResolvedModuleLimits(module_files=1),
            ResolvedModuleLimits(import_depth=1),
            ResolvedModuleLimits(aggregate_source_bytes=32),
        )
        for limits in limit_cases:
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                project, alpha, beta = _fixture(base)
                before = _tree_snapshot(base)
                with self.assertRaises(ModuleResolutionError) as rejected:
                    _plan(project, alpha, beta, limits=limits)
                self.assertEqual(rejected.exception.code, "HOCUS464")
                self.assertEqual(_tree_snapshot(base), before)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            _write_source(
                alpha / "modules/helper.hocus",
                b'hocus 0.2; import { Alpha } from "./main.hocus"; module Helper() exports () {}',
            )
            with self.assertRaises(ModuleResolutionError) as cycle:
                _plan(project, alpha, beta)
            self.assertEqual(cycle.exception.code, "HOCUS463")

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            calls = 0

            def cancel() -> bool:
                nonlocal calls
                calls += 1
                return calls > 8

            before = _tree_snapshot(base)
            with self.assertRaises((ModuleResolutionError, ProjectError)) as cancelled:
                _plan(project, alpha, beta, cancelled=cancel)
            self.assertEqual(cancelled.exception.code, "HOCUS465")
            self.assertEqual(_tree_snapshot(base), before)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            from hocuspocus.hocusscript import module_lock_plan as plan_module

            real_read = plan_module._read_target
            reads: dict[str, int] = {}

            def race(target, limits, cancelled):
                reads[target.uri] = reads.get(target.uri, 0) + 1
                if reads[target.uri] == 2 and target.uri.endswith("modules/helper.hocus"):
                    target.path.write_bytes(b"hocus 0.2; module Helper(changed: int = 1) exports () {}")
                return real_read(target, limits, cancelled)

            original_lock = (project / "pins/hocus.lock.json").read_bytes()
            with patch("hocuspocus.hocusscript.module_lock_plan._read_target", new=race):
                with self.assertRaises(ProjectError) as drift:
                    _plan(project, alpha, beta)
            self.assertEqual(drift.exception.code, "HOCUS428")
            self.assertEqual((project / "pins/hocus.lock.json").read_bytes(), original_lock)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            from hocuspocus.hocusscript import module_lock_plan as plan_module

            alternate = project / "modules/alternate.hocus"
            _write_source(alternate, b"hocus 0.2; module Local() exports () {}")
            real_select = plan_module._select_project_module_target
            selections = 0

            def winner_race(context, importer, specifier, *, cancelled=None):
                nonlocal selections
                selected = real_select(context, importer, specifier, cancelled=cancelled)
                if specifier == "local.hocus":
                    selections += 1
                    if selections > 1:
                        return alternate.resolve(strict=True)
                return selected

            original_lock = (project / "pins/hocus.lock.json").read_bytes()
            with patch(
                "hocuspocus.hocusscript.module_lock_plan._select_project_module_target",
                new=winner_race,
            ):
                with self.assertRaises(ProjectError) as winner_changed:
                    _plan(project, alpha, beta)
            self.assertEqual(winner_changed.exception.code, "HOCUS428")
            self.assertEqual((project / "pins/hocus.lock.json").read_bytes(), original_lock)

    def test_module_file_limit_counts_visiting_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            _write_source(
                project / "src/main.hocus",
                b'hocus 0.2; import { Alpha } from "@alpha/modules/main.hocus"; '
                b'graph Main { target "/obj/main"; }',
            )
            _write_source(
                alpha / "modules/main.hocus",
                b'hocus 0.2; import { Helper } from "./helper.hocus"; '
                b'module Alpha() exports () {}',
            )
            before = _tree_snapshot(base)
            with self.assertRaises(ModuleResolutionError) as rejected:
                _plan(
                    project, alpha, beta,
                    limits=ResolvedModuleLimits(module_files=1),
                )
            self.assertEqual(rejected.exception.code, "HOCUS464")
            self.assertEqual(_tree_snapshot(base), before)

    def test_semantically_invalid_entry_expansion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            _write_source(
                project / "src/main.hocus",
                b'hocus 0.2; import { Alpha } from "@alpha/modules/main.hocus"; '
                b'graph Main { target "/obj/main"; use bad @id("bad") = Alpha(); }',
            )
            _write_source(
                alpha / "modules/main.hocus",
                b'hocus 0.2; module Alpha(required: int) exports () {}',
            )
            before = _tree_snapshot(base)
            with self.assertRaises(ModuleExpansionError) as rejected:
                _plan(project, alpha, beta)
            self.assertEqual(rejected.exception.code, "HOCUS469")
            self.assertEqual(_tree_snapshot(base), before)

    def test_existing_project_only_resolver_remains_isolated_from_external_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            with self.assertRaises(ProjectError) as rejected:
                resolve_project_module_dag(project, "src/main.hocus")
            self.assertEqual(rejected.exception.code, "HOCUS462")
            # The opt-in G2 surface succeeds without changing the legacy resolver contract.
            self.assertEqual(len(_plan(project, alpha, beta).modules), 4)


if __name__ == "__main__":
    unittest.main()
