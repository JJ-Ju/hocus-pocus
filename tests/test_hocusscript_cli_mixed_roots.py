from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from hocuspocus.hocusscript import (
    compile_project_mixed_module_bundle,
    compile_project_mixed_module_semantic,
    verify_project_lock,
)
from hocuspocus.hocusscript.cli import main
from test_hocusscript_module_bundle import _prepare_project
from test_hocusscript_module_lock_plan import _fixture
from test_hocusscript_parser import VALID_SOURCE


def _run(arguments: list[str]) -> tuple[int, str, str]:
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = main(arguments)
    return code, output.getvalue(), errors.getvalue()


def _module_root_arguments(
    alpha: Path,
    beta: Path,
    *,
    reverse: bool = False,
) -> list[str]:
    values = (("alpha", alpha), ("beta", beta))
    if reverse:
        values = tuple(reversed(values))
    return [item for alias, path in values for item in ("--module-root", f"{alias}={path}")]


def _assert_path_free(test: unittest.TestCase, text: str, *paths: Path) -> None:
    for path in paths:
        test.assertNotIn(str(path), text)


def _write_legacy_project(root: Path) -> None:
    (root / "hocus.project.toml").write_text(
        'schema_version = 1\n[project]\nuid = "legacy-cli-project"\n',
        encoding="utf-8",
    )
    (root / "demo.hocus").write_text(VALID_SOURCE, encoding="utf-8")


class HocusScriptMixedRootCliTests(unittest.TestCase):
    def test_mixed_lock_requires_exact_digest_and_preserves_lock_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            lock = project / "pins/hocus.lock.json"
            original = lock.read_bytes()
            code, output, errors = _run([
                "lock",
                "src/main.hocus",
                "--update",
                "--project",
                str(project),
                *_module_root_arguments(alpha, beta),
            ])
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("HOCUS453", errors)
            self.assertEqual(lock.read_bytes(), original)
            _assert_path_free(self, errors, project, alpha, beta)

    def test_mixed_lock_check_and_compile_are_deterministic_and_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "approved=module-roots"
            project, alpha, beta = _fixture(base)
            original_lock_digest = verify_project_lock(project).lock_digest
            lock_code, lock_output, lock_errors = _run([
                "lock",
                "src/main.hocus",
                "--update",
                "--project",
                str(project),
                "--expected-lock-digest",
                original_lock_digest,
                *_module_root_arguments(alpha, beta),
            ])
            self.assertEqual(lock_code, 0, lock_errors)
            self.assertEqual(lock_errors, "")
            receipt = json.loads(lock_output)
            self.assertEqual(receipt["previousLockDigest"], original_lock_digest)
            self.assertEqual(receipt["lockDigest"], verify_project_lock(project).lock_digest)
            self.assertTrue(any(
                item["moduleUri"].startswith("hocus-module://")
                for item in receipt["modules"]
            ))
            _assert_path_free(self, lock_output, base, project, alpha, beta)
            _assert_path_free(
                self,
                (project / "pins/hocus.lock.json").read_text("utf-8"),
                base,
                project,
                alpha,
                beta,
            )

            roots = {"alpha": alpha, "beta": beta}
            expected_check = compile_project_mixed_module_semantic(
                project, "src/main.hocus", roots,
            ).to_dict()
            expected_compile = compile_project_mixed_module_bundle(
                project, "src/main.hocus", roots,
            ).to_json(pretty=True)
            lock_bytes = (project / "pins/hocus.lock.json").read_bytes()

            checks = []
            bundles = []
            for reverse in (False, True):
                check_code, check_output, check_errors = _run([
                    "check",
                    "src/main.hocus",
                    "--project",
                    str(project),
                    "--json",
                    *_module_root_arguments(alpha, beta, reverse=reverse),
                ])
                self.assertEqual(check_code, 0, check_errors)
                self.assertEqual(check_errors, "")
                checks.append(json.loads(check_output))

                compile_code, compile_output, compile_errors = _run([
                    "compile",
                    "src/main.hocus",
                    "--project",
                    str(project),
                    *_module_root_arguments(alpha, beta, reverse=reverse),
                ])
                self.assertEqual(compile_code, 0, compile_errors)
                self.assertEqual(compile_errors, "")
                bundles.append(compile_output)
                _assert_path_free(
                    self,
                    check_output + compile_output,
                    base,
                    project,
                    alpha,
                    beta,
                )

            self.assertEqual(checks, [expected_check, expected_check])
            self.assertEqual(bundles, [expected_compile, expected_compile])
            self.assertEqual((project / "pins/hocus.lock.json").read_bytes(), lock_bytes)
            bundle_payload = json.loads(bundles[0])
            self.assertEqual(bundle_payload["bundleVersion"], "0.3")
            self.assertTrue(any(
                item["uri"].startswith("hocus-module://")
                for item in bundle_payload["dependencies"]
            ))

    def test_malformed_duplicate_and_relative_roots_are_typed_before_dispatch(self) -> None:
        absolute = str(Path.cwd().resolve())
        cases = (
            ("missing-separator", ["--module-root", "alpha"]),
            ("empty-alias", ["--module-root", f"={absolute}"]),
            ("empty-path", ["--module-root", "alpha="]),
            ("invalid-alias", ["--module-root", f"Alpha={absolute}"]),
            ("relative", ["--module-root", "alpha=relative/root"]),
            (
                "duplicate",
                ["--module-root", f"alpha={absolute}", "--module-root", f"alpha={absolute}"],
            ),
        )
        with patch(
            "hocuspocus.hocusscript.cli.compile_project_mixed_module_semantic",
            side_effect=AssertionError("mixed check dispatch was reached"),
        ) as mixed_check, patch(
            "hocuspocus.hocusscript.cli.compile_project_mixed_module_bundle",
            side_effect=AssertionError("mixed compile dispatch was reached"),
        ) as mixed_compile, patch(
            "hocuspocus.hocusscript.cli.update_project_mixed_module_lock",
            side_effect=AssertionError("mixed lock dispatch was reached"),
        ) as mixed_lock:
            for label, arguments in cases:
                with self.subTest(label=label):
                    code, output, errors = _run([
                        "compile",
                        "src/main.hocus",
                        "--project",
                        "not-a-project",
                        *arguments,
                    ])
                    self.assertEqual(code, 1)
                    self.assertEqual(output, "")
                    self.assertIn("HOCUS458", errors)
                    self.assertNotIn("Traceback", errors)
        mixed_check.assert_not_called()
        mixed_compile.assert_not_called()
        mixed_lock.assert_not_called()

    def test_roots_are_complete_per_call_and_never_ambient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, alpha, beta = _fixture(base)
            expected = verify_project_lock(project).lock_digest
            code, output, errors = _run([
                "lock",
                "src/main.hocus",
                "--update",
                "--project",
                str(project),
                "--expected-lock-digest",
                expected,
                *_module_root_arguments(alpha, beta),
            ])
            self.assertEqual(code, 0, errors)
            self.assertNotEqual(output, "")

            with patch.dict(
                os.environ,
                {"HOCUS_MODULE_ROOTS": f"alpha={alpha};beta={beta}"},
                clear=False,
            ):
                code, output, errors = _run([
                    "compile", "src/main.hocus", "--project", str(project),
                ])
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("HOCUS460", errors)
            _assert_path_free(self, errors, base, project, alpha, beta)

            code, output, errors = _run([
                "check",
                "src/main.hocus",
                "--project",
                str(project),
                "--json",
                "--module-root",
                f"alpha={alpha}",
            ])
            self.assertEqual(code, 1)
            self.assertEqual(errors, "")
            failure = json.loads(output)
            self.assertFalse(failure["valid"])
            self.assertEqual(failure["diagnostics"][0]["code"], "HOCUS458")
            _assert_path_free(self, output, base, project, alpha, beta)

            code, output, errors = _run([
                "compile",
                "src/main.hocus",
                "--project",
                str(project),
                *_module_root_arguments(alpha, beta),
            ])
            self.assertEqual(code, 0, errors)
            self.assertNotEqual(output, "")

    def test_legacy_no_flag_dispatch_remains_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _prepare_project(project)
            with patch(
                "hocuspocus.hocusscript.cli.compile_project_mixed_module_semantic",
                side_effect=AssertionError("mixed check should not be selected"),
            ), patch(
                "hocuspocus.hocusscript.cli.compile_project_mixed_module_bundle",
                side_effect=AssertionError("mixed compile should not be selected"),
            ):
                check_code, check_output, check_errors = _run([
                    "check", "src/main.hocus", "--project", str(project), "--json",
                ])
                compile_code, compile_output, compile_errors = _run([
                    "compile", "src/main.hocus", "--project", str(project),
                ])
            self.assertEqual(check_code, 0, check_errors)
            self.assertTrue(json.loads(check_output)["valid"])
            self.assertEqual(compile_code, 0, compile_errors)
            self.assertEqual(json.loads(compile_output)["bundleVersion"], "0.3")

    def test_nonconsumer_commands_reject_module_root_as_an_unknown_option(self) -> None:
        commands = (
            ["format", "src/main.hocus", "--project", "project"],
            ["write-export", "handoff.json", "src/main.hocus", "--project", "project"],
        )
        secret = Path.cwd().resolve() / "Confidential Module Library"
        forms = (
            (["--module-root", f"alpha={secret}"], "--module-root is available only"),
            ([f"--module-root=alpha={secret}"], "--module-root is available only"),
            (["--module-ro", f"alpha={secret}"], "exact --module-root option spelling"),
            ([f"--module-ro=alpha={secret}"], "exact --module-root option spelling"),
        )
        for command in commands:
            for form, message in forms:
                with self.subTest(command=command[0], form=form[0]):
                    output, errors = StringIO(), StringIO()
                    with redirect_stdout(output), redirect_stderr(errors), self.assertRaises(
                        SystemExit,
                    ) as rejected:
                        main([*command, *form])
                    self.assertEqual(rejected.exception.code, 2)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn(message, errors.getvalue())
                    self.assertNotIn(str(secret), errors.getvalue())

    def test_consumer_commands_reject_abbreviated_root_option_without_dispatch(self) -> None:
        secret = Path.cwd().resolve() / "Confidential Module Library"
        forms = (
            ["--module-ro", f"alpha={secret}"],
            [f"--module-ro=alpha={secret}"],
        )
        with patch(
            "hocuspocus.hocusscript.cli.ProjectContext.load",
            side_effect=AssertionError("project dispatch was reached"),
        ), patch(
            "hocuspocus.hocusscript.cli.compile_project_mixed_module_semantic",
            side_effect=AssertionError("mixed dispatch was reached"),
        ):
            for form in forms:
                output, errors = StringIO(), StringIO()
                with self.subTest(form=form[0]), redirect_stdout(output), redirect_stderr(
                    errors,
                ), self.assertRaises(SystemExit) as rejected:
                    main([
                        "check", "src/main.hocus", "--project", "project", "--json", *form,
                    ])
                self.assertEqual(rejected.exception.code, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("exact --module-root option spelling", errors.getvalue())
                self.assertNotIn(str(secret), errors.getvalue())

    def test_language_01_rejects_module_roots_without_mixed_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            _write_legacy_project(project)
            root_argument = ["--module-root", f"alpha={project.resolve()}"]
            with patch(
                "hocuspocus.hocusscript.cli.compile_project_mixed_module_semantic",
                side_effect=AssertionError("mixed check should not be selected"),
            ), patch(
                "hocuspocus.hocusscript.cli.compile_project_mixed_module_bundle",
                side_effect=AssertionError("mixed compile should not be selected"),
            ):
                code, output, errors = _run([
                    "check",
                    "demo.hocus",
                    "--project",
                    str(project),
                    "--json",
                    *root_argument,
                ])
                self.assertEqual(code, 1)
                self.assertEqual(errors, "")
                self.assertEqual(
                    json.loads(output)["diagnostics"][0]["code"],
                    "HOCUS460",
                )
                _assert_path_free(self, output, project)

                code, output, errors = _run([
                    "compile",
                    "demo.hocus",
                    "--project",
                    str(project),
                    *root_argument,
                ])
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertIn("HOCUS460", errors)
                _assert_path_free(self, errors, project)


if __name__ == "__main__":
    unittest.main()
