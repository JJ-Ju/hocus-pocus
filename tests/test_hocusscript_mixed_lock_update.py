from __future__ import annotations

import inspect
import json
import shutil
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from hocuspocus.hocusscript import (
    MixedModuleLockUpdateResult,
    plan_project_module_lock,
    update_project_mixed_module_lock,
)
from hocuspocus.hocusscript.expander import ModuleExpansionError
from hocuspocus.hocusscript.lock_update import update_project_module_lock
from hocuspocus.hocusscript.project import ProjectError, verify_project_lock
from hocuspocus.hocusscript.resolved_modules import ModuleResolutionError, ResolvedModuleLimits
from hocuspocus.hocusscript.resolver import resolve_project_module_dag
from test_hocusscript_module_lock_plan import PROJECT_UID, _fixture, _write_source


def _roots(alpha: Path, beta: Path) -> dict[str, Path]:
    return {"beta": beta, "alpha": alpha}


def _publish(project: Path, alpha: Path, beta: Path, *, expected: str | None = None, **kwargs):
    return update_project_mixed_module_lock(
        project,
        ["src/main.hocus"],
        _roots(alpha, beta),
        expected_lock_digest=expected or verify_project_lock(project).lock_digest,
        allow_write=True,
        **kwargs,
    )


def _assert_transaction_clean(test: unittest.TestCase, project: Path) -> None:
    pins = project / "pins"
    test.assertFalse((pins / ".hocus.lock.json.update-lease").exists())
    test.assertEqual(list(pins.glob(".hocus.lock.json.*.tmp")), [])


class _BombMapping(Mapping):
    def __getitem__(self, key):
        raise AssertionError("module roots were accessed")

    def __iter__(self):
        raise AssertionError("module roots were enumerated")

    def __len__(self):
        raise AssertionError("module roots were counted")


class _BombIterable:
    def __iter__(self):
        raise AssertionError("entry sources were enumerated")


class MixedModuleLockUpdateTests(unittest.TestCase):
    def test_default_denies_before_root_enumeration_and_plan_authority_is_absent(self) -> None:
        for entries, roots in ((["src/main.hocus"], _BombMapping()), (_BombIterable(), {})):
            with self.subTest(entries=type(entries).__name__, roots=type(roots).__name__):
                with self.assertRaises(ProjectError) as denied:
                    update_project_mixed_module_lock(
                        "not-a-project",
                        entries,
                        roots,
                        expected_lock_digest="sha256:" + "0" * 64,
                    )
                self.assertEqual(denied.exception.code, "HOCUS455")
        parameters = inspect.signature(update_project_mixed_module_lock).parameters
        self.assertNotIn("plan", parameters)
        self.assertNotIn("plan_digest", parameters)

        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            advisory = plan_project_module_lock(
                project, ["src/main.hocus"], _roots(alpha, beta)
            )
            with self.assertRaises(TypeError):
                update_project_mixed_module_lock(
                    project,
                    ["src/main.hocus"],
                    _roots(alpha, beta),
                    expected_lock_digest=verify_project_lock(project).lock_digest,
                    allow_write=True,
                    plan=advisory,
                )

    def test_exact_expected_digest_is_required_and_checked_before_derivation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            original = lock.read_bytes()
            for expected in ("bad", "sha256:" + "f" * 64):
                with self.subTest(expected=expected), patch(
                    "hocuspocus.hocusscript.mixed_lock_update._derive_mixed_module_lock",
                    side_effect=AssertionError("stale authority reached derivation"),
                ):
                    with self.assertRaises(ProjectError) as rejected:
                        update_project_mixed_module_lock(
                            project,
                            ["src/main.hocus"],
                            _roots(alpha, beta),
                            expected_lock_digest=expected,
                            allow_write=True,
                        )
                    self.assertEqual(rejected.exception.code, "HOCUS453")
                self.assertEqual(lock.read_bytes(), original)
                _assert_transaction_clean(self, project)

            with self.assertRaises(TypeError):
                update_project_mixed_module_lock(
                    project,
                    ["src/main.hocus"],
                    _roots(alpha, beta),
                    allow_write=True,
                )

    def test_exact_publish_repeat_change_and_remove_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            initial_digest = verify_project_lock(project).lock_digest
            created = _publish(project, alpha, beta, expected=initial_digest)
            self.assertIsInstance(created, MixedModuleLockUpdateResult)
            self.assertEqual(created.previous_lock_digest, initial_digest)
            expected_uris = (
                "hocus-module://alpha-library/modules/helper.hocus",
                "hocus-module://alpha-library/modules/main.hocus",
                "hocus-module://beta-library/main.hocus",
                f"hocus-project://{PROJECT_UID}/modules/local.hocus",
            )
            self.assertEqual(created.added_uris, expected_uris)
            self.assertEqual((created.removed_uris, created.changed_uris), ((), ()))
            verified = verify_project_lock(project)
            self.assertEqual(verified.lock_digest, created.lock_digest)
            self.assertEqual(verified.modules, created.modules)
            self.assertTrue(any(item.external_alias == "alpha" for item in created.modules))

            lock_bytes = (project / "pins/hocus.lock.json").read_bytes()
            lock_stat = (project / "pins/hocus.lock.json").stat()
            repeated = _publish(project, alpha, beta, expected=created.lock_digest)
            self.assertFalse(repeated.changed)
            self.assertEqual((repeated.added_uris, repeated.removed_uris, repeated.changed_uris), ((), (), ()))
            self.assertEqual((project / "pins/hocus.lock.json").read_bytes(), lock_bytes)
            repeated_stat = (project / "pins/hocus.lock.json").stat()
            self.assertEqual(repeated_stat.st_mtime_ns, lock_stat.st_mtime_ns)
            self.assertEqual(repeated_stat.st_ino, lock_stat.st_ino)

            _write_source(
                alpha / "modules/helper.hocus",
                b"hocus 0.2; module Helper(value: int = 2) exports () {}",
            )
            changed = _publish(project, alpha, beta, expected=repeated.lock_digest)
            self.assertEqual(changed.added_uris, ())
            self.assertEqual(changed.removed_uris, ())
            self.assertEqual(changed.changed_uris, (
                "hocus-module://alpha-library/modules/helper.hocus",
                "hocus-module://alpha-library/modules/main.hocus",
                f"hocus-project://{PROJECT_UID}/modules/local.hocus",
            ))

            _write_source(
                project / "src/main.hocus",
                b'hocus 0.2; import { Beta } from "@beta/main.hocus"; '
                b'graph Main { target "/obj/main"; }',
            )
            removed = _publish(project, alpha, beta, expected=changed.lock_digest)
            self.assertEqual((removed.added_uris, removed.changed_uris), ((), ()))
            self.assertEqual(removed.removed_uris, (
                "hocus-module://alpha-library/modules/helper.hocus",
                "hocus-module://alpha-library/modules/main.hocus",
                f"hocus-project://{PROJECT_UID}/modules/local.hocus",
            ))
            self.assertEqual(
                tuple(item.module_uri for item in verify_project_lock(project).modules),
                ("hocus-module://beta-library/main.hocus",),
            )

    def test_rederives_fresh_under_lease_without_calling_public_planner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            advisory = plan_project_module_lock(
                project, ["src/main.hocus"], _roots(alpha, beta)
            )
            old_helper = next(
                item.content_digest for item in advisory.modules
                if item.module_uri.endswith("modules/helper.hocus")
            )
            _write_source(
                alpha / "modules/helper.hocus",
                b"hocus 0.2; module Helper(value: int = 9) exports () {}",
            )
            from hocuspocus.hocusscript import mixed_lock_update as update_module

            real_derive = update_module._derive_mixed_module_lock

            def derive_under_lease(*args, **kwargs):
                self.assertTrue(
                    (project / "pins/.hocus.lock.json.update-lease").exists()
                )
                return real_derive(*args, **kwargs)

            with patch(
                "hocuspocus.hocusscript.module_lock_plan.plan_project_module_lock",
                side_effect=AssertionError("public advisory planner was trusted"),
            ), patch(
                "hocuspocus.hocusscript.mixed_lock_update._derive_mixed_module_lock",
                new=derive_under_lease,
            ):
                result = _publish(project, alpha, beta)
            new_helper = next(
                item.content_digest for item in result.modules
                if item.module_uri.endswith("modules/helper.hocus")
            )
            self.assertNotEqual(new_helper, old_helper)
            _assert_transaction_clean(self, project)

    def test_lease_contention_and_receipt_failure_cannot_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            original = lock.read_bytes()
            lease = project / "pins/.hocus.lock.json.update-lease"
            lease.write_bytes(b"held\n")
            try:
                with self.assertRaises(ProjectError) as contended:
                    _publish(project, alpha, beta)
                self.assertEqual(contended.exception.code, "HOCUS453")
                self.assertEqual(lock.read_bytes(), original)
                self.assertTrue(lease.exists())
                self.assertEqual(list((project / "pins").glob(".hocus.lock.json.*.tmp")), [])
            finally:
                lease.unlink(missing_ok=True)

        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            original = lock.read_bytes()
            with patch(
                "hocuspocus.hocusscript.mixed_lock_update.MixedModuleLockUpdateResult",
                side_effect=ProjectError("HOCUS459", "forced receipt failure"),
            ):
                with self.assertRaises(ProjectError) as failed:
                    _publish(project, alpha, beta)
            self.assertEqual(failed.exception.code, "HOCUS459")
            self.assertEqual(lock.read_bytes(), original)
            _assert_transaction_clean(self, project)

    def test_malformed_exact_current_lock_is_rejected_not_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            payload = json.loads(lock.read_text("utf-8"))
            payload["unexpected"] = "invalid-current-lock"
            lock.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            malformed = lock.read_bytes()
            from hocuspocus.hocusscript.project import _canonical_lock_file_digest

            exact_digest = _canonical_lock_file_digest(lock)
            with patch(
                "hocuspocus.hocusscript.mixed_lock_update._derive_mixed_module_lock",
                side_effect=AssertionError("invalid current lock reached derivation"),
            ):
                with self.assertRaises(ProjectError):
                    _publish(project, alpha, beta, expected=exact_digest)
            self.assertEqual(lock.read_bytes(), malformed)
            _assert_transaction_clean(self, project)

    def test_semantic_and_limit_failures_preserve_lock(self) -> None:
        cases = ("semantic", "limit")
        for mode in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                project, alpha, beta = _fixture(Path(temporary))
                lock = project / "pins/hocus.lock.json"
                original = lock.read_bytes()
                kwargs = {}
                if mode == "semantic":
                    _write_source(
                        project / "src/main.hocus",
                        b'hocus 0.2; import { Alpha } from "@alpha/modules/main.hocus"; '
                        b'graph Main { target "/obj/main"; use bad @id("bad") = Alpha(); }',
                    )
                    _write_source(
                        alpha / "modules/main.hocus",
                        b"hocus 0.2; module Alpha(required: int) exports () {}",
                    )
                    error = ModuleExpansionError
                else:
                    kwargs["limits"] = ResolvedModuleLimits(module_files=1)
                    error = ModuleResolutionError
                with self.assertRaises(error):
                    _publish(project, alpha, beta, **kwargs)
                self.assertEqual(lock.read_bytes(), original)
                _assert_transaction_clean(self, project)

    def test_source_root_manifest_project_catalog_and_lock_races_do_not_publish(self) -> None:
        modes = (
            "project-source",
            "external-source",
            "root",
            "external-manifest",
            "project-manifest",
            "catalog",
            "lock",
        )
        for mode in modes:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                project, alpha, beta = _fixture(base)
                lock = project / "pins/hocus.lock.json"
                original = lock.read_bytes()
                adversarial_lock: bytes | None = None
                from hocuspocus.hocusscript import project as project_module

                real_atomic = project_module._atomic_write_lock

                def inject(path, content, **kwargs):
                    nonlocal adversarial_lock
                    if mode == "project-source":
                        _write_source(
                            project / "modules/local.hocus",
                            b'hocus 0.2; import { Alpha } from "@alpha/modules/main.hocus"; '
                            b'module Local(value: int = 1) exports () {}',
                        )
                    elif mode == "external-source":
                        _write_source(
                            alpha / "modules/helper.hocus",
                            b"hocus 0.2; module Helper(value: int = 1) exports () {}",
                        )
                    elif mode == "root":
                        old = base / "alpha-old"
                        alpha.rename(old)
                        shutil.copytree(old, alpha)
                    elif mode == "external-manifest":
                        manifest = alpha / "hocus.module.toml"
                        manifest.write_bytes(manifest.read_bytes() + b"\n")
                    elif mode == "project-manifest":
                        manifest = project / "hocus.project.toml"
                        manifest.write_bytes(manifest.read_bytes() + b"\n")
                    elif mode == "catalog":
                        catalog = project / "catalog/catalog.json"
                        catalog.write_bytes(catalog.read_bytes() + b" ")
                    elif mode == "lock":
                        payload = json.loads(lock.read_text("utf-8"))
                        payload["raceMarker"] = True
                        adversarial_lock = json.dumps(payload, sort_keys=True).encode("utf-8")
                        lock.write_bytes(adversarial_lock)
                    return real_atomic(path, content, **kwargs)

                with patch(
                    "hocuspocus.hocusscript.project._atomic_write_lock",
                    new=inject,
                ):
                    with self.assertRaises((ProjectError, ModuleResolutionError)):
                        _publish(project, alpha, beta)
                self.assertEqual(lock.read_bytes(), adversarial_lock or original)
                _assert_transaction_clean(self, project)

    def test_resolution_winner_race_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            original = lock.read_bytes()
            alternate = project / "modules/alternate.hocus"
            _write_source(alternate, b"hocus 0.2; module Local() exports () {}")
            from hocuspocus.hocusscript import module_lock_plan as plan_module

            real_select = plan_module._select_project_module_target
            selections = 0

            def race(context, importer, specifier, *, cancelled=None):
                nonlocal selections
                selected = real_select(context, importer, specifier, cancelled=cancelled)
                if specifier == "local.hocus":
                    selections += 1
                    if selections > 1:
                        return alternate.resolve(strict=True)
                return selected

            with patch(
                "hocuspocus.hocusscript.module_lock_plan._select_project_module_target",
                new=race,
            ):
                with self.assertRaises(ProjectError) as rejected:
                    _publish(project, alpha, beta)
            self.assertEqual(rejected.exception.code, "HOCUS428")
            self.assertEqual(lock.read_bytes(), original)
            _assert_transaction_clean(self, project)

    def test_under_lease_cancellation_and_replace_failure_cleanup(self) -> None:
        for mode in ("cancel", "replace"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                project, alpha, beta = _fixture(Path(temporary))
                lock = project / "pins/hocus.lock.json"
                original = lock.read_bytes()
                if mode == "cancel":
                    from hocuspocus.hocusscript import mixed_lock_update as update_module

                    real_derive = update_module._derive_mixed_module_lock
                    entered = False

                    def enter_then_derive(*args, **kwargs):
                        nonlocal entered
                        self.assertTrue(
                            (project / "pins/.hocus.lock.json.update-lease").exists()
                        )
                        entered = True
                        return real_derive(*args, **kwargs)

                    callback = lambda: entered
                    patches = (
                        patch(
                            "hocuspocus.hocusscript.mixed_lock_update._derive_mixed_module_lock",
                            new=enter_then_derive,
                        ),
                    )
                    error = (ProjectError, ModuleResolutionError)
                else:
                    callback = None
                    patches = (
                        patch(
                            "hocuspocus.hocusscript.project.os.replace",
                            side_effect=OSError("replace failed"),
                        ),
                    )
                    error = ProjectError

                with patches[0], self.assertRaises(error):
                    _publish(project, alpha, beta, cancelled=callback)
                self.assertEqual(lock.read_bytes(), original)
                _assert_transaction_clean(self, project)

    def test_relocation_stable_host_path_free_receipt(self) -> None:
        payloads = []
        locks = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory in (first, second):
                base = Path(directory)
                project, alpha, beta = _fixture(base)
                result = _publish(project, alpha, beta)
                payload = result.to_dict()
                rendered = json.dumps(payload, sort_keys=True) + repr(result)
                for native in (base, project, alpha, beta):
                    self.assertNotIn(str(native), rendered)
                payloads.append(payload)
                locks.append((project / "pins/hocus.lock.json").read_bytes())
            self.assertEqual(payloads[0], payloads[1])
            self.assertEqual(locks[0], locks[1])

    def test_legacy_resolver_and_same_project_writer_remain_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            original = (project / "pins/hocus.lock.json").read_bytes()
            with self.assertRaises(ProjectError) as resolver_rejected:
                resolve_project_module_dag(project, "src/main.hocus")
            self.assertEqual(resolver_rejected.exception.code, "HOCUS462")
            with self.assertRaises(ProjectError) as writer_rejected:
                update_project_module_lock(
                    project,
                    ["src/main.hocus"],
                    allow_write=True,
                    expected_lock_digest=verify_project_lock(project).lock_digest,
                )
            self.assertEqual(writer_rejected.exception.code, "HOCUS460")
            self.assertEqual((project / "pins/hocus.lock.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
