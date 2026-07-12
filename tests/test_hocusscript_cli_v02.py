from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import compile_project_module_bundle, verify_project_lock
from hocuspocus.hocusscript.cli import main
from test_hocusscript_module_bundle import _prepare_project


def _run(arguments: list[str]) -> tuple[int, str, str]:
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        code = main(arguments)
    return code, output.getvalue(), errors.getvalue()


class HocusScriptModuleCliTests(unittest.TestCase):
    def test_check_json_and_compile_stdout_are_deterministic_and_portable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            check_code, check_output, check_errors = _run([
                "check", "src/main.hocus", "--project", str(root), "--json",
            ])
            self.assertEqual(check_code, 0, check_errors)
            checked = json.loads(check_output)
            self.assertEqual(checked["stage"], "semantic")
            self.assertTrue(checked["valid"])
            self.assertNotIn(str(root), check_output)

            compile_code, compile_output, compile_errors = _run([
                "compile", "src/main.hocus", "--project", str(root),
            ])
            self.assertEqual(compile_code, 0, compile_errors)
            expected = compile_project_module_bundle(root, "src/main.hocus").to_json(pretty=True)
            self.assertEqual(compile_output, expected)
            self.assertEqual(json.loads(compile_output)["bundleVersion"], "0.3")
            self.assertNotIn(str(root), compile_output)

    def test_invalid_semantics_use_typed_stderr_without_partial_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            source = root / "src/main.hocus"
            source.write_bytes(source.read_bytes().replace(b'"sop::null"', b'"missing::operator"'))

            check_code, check_output, check_errors = _run([
                "check", "src/main.hocus", "--project", str(root),
            ])
            self.assertEqual(check_code, 1)
            self.assertEqual(check_output, "")
            self.assertIn("HOCUS624", check_errors)
            self.assertNotIn("Traceback", check_errors)

            compile_code, compile_output, compile_errors = _run([
                "compile", "src/main.hocus", "--project", str(root),
            ])
            self.assertEqual(compile_code, 1)
            self.assertEqual(compile_output, "")
            self.assertIn("HOCUS482", compile_errors)
            self.assertNotIn("Traceback", compile_errors)

    def test_syntax_invalid_json_is_structured_and_no_strict_is_explicitly_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            (root / "src/main.hocus").write_text(
                "hocus 0.2; graph Main { node",
                encoding="utf-8",
            )
            code, output, errors = _run([
                "check", "src/main.hocus", "--project", str(root), "--json",
            ])
            self.assertEqual(code, 1)
            self.assertEqual(errors, "")
            payload = json.loads(output)
            self.assertFalse(payload["valid"])
            self.assertEqual(payload["diagnostics"][0]["code"], "HOCUS218")
            self.assertIn("span", payload["diagnostics"][0])

            code, output, errors = _run([
                "check", "src/main.hocus", "--project", str(root), "--no-strict",
            ])
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("HOCUS460", errors)

    def test_compile_output_is_exclusive_and_exact_digest_replaceable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            output_path = Path(temporary) / "artifacts" / "main.bundle.json"
            _prepare_project(root)
            arguments = [
                "compile", "src/main.hocus", "--project", str(root),
                "--output", str(output_path),
            ]
            created, stdout, errors = _run(arguments)
            self.assertEqual(created, 0, errors)
            self.assertEqual(stdout, "")
            original = output_path.read_bytes()

            refused, stdout, errors = _run(arguments)
            self.assertEqual(refused, 1)
            self.assertEqual(stdout, "")
            self.assertIn("HOCUS440", errors)
            self.assertEqual(output_path.read_bytes(), original)

            digest = "sha256:" + hashlib.sha256(original).hexdigest()
            replaced, stdout, errors = _run([
                *arguments, "--expected-output-digest", digest,
            ])
            self.assertEqual(replaced, 0, errors)
            self.assertEqual(stdout, "")
            self.assertEqual(output_path.read_bytes(), original)

            stale, stdout, errors = _run([
                *arguments, "--expected-output-digest", "sha256:" + "0" * 64,
            ])
            self.assertEqual(stale, 1)
            self.assertEqual(stdout, "")
            self.assertIn("HOCUS418", errors)
            self.assertEqual(output_path.read_bytes(), original)

    def test_format_is_lock_independent_for_graph_and_module_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            (root / "pins/hocus.lock.json").write_text("not-json", encoding="utf-8")
            graph = root / "src/main.hocus"
            graph.write_text(
                'hocus 0.2; graph Main { target "/obj/geo1"; category Sop; node n: "sop::null" {} }',
                encoding="utf-8",
            )
            code, formatted, errors = _run([
                "format", "src/main.hocus", "--project", str(root),
            ])
            self.assertEqual(code, 0, errors)
            self.assertIn("graph Main {\n", formatted)
            self.assertEqual(graph.read_text("utf-8").count("\n"), 0)

            module = root / "modules-b/root.hocus"
            code, stdout, errors = _run([
                "format", "modules-b/root.hocus", "--project", str(root), "--write",
            ])
            self.assertEqual(code, 0, errors)
            self.assertEqual(stdout, "")
            self.assertIn("module Root", module.read_text("utf-8"))

    def test_lock_update_delegates_to_derived_writer_and_emits_portable_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            expected = verify_project_lock(root).lock_digest
            code, output, errors = _run([
                "lock", "src/main.hocus", "--update", "--project", str(root),
                "--expected-lock-digest", expected,
            ])
            self.assertEqual(code, 0, errors)
            receipt = json.loads(output)
            self.assertEqual(receipt["previousLockDigest"], expected)
            self.assertEqual(receipt["lockDigest"], verify_project_lock(root).lock_digest)
            self.assertNotIn(str(root), output)

            refused, refused_output, refused_errors = _run([
                "lock", "src/main.hocus", "--update", "--project", str(root),
            ])
            self.assertEqual(refused, 1)
            self.assertEqual(refused_output, "")
            self.assertIn("HOCUS453", refused_errors)

    def test_python_module_entrypoint_runs_without_houdini(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _prepare_project(root)
            environment = dict(os.environ)
            library_root = str(ROOT / "python3.11libs")
            environment["PYTHONPATH"] = os.pathsep.join(filter(None, (
                library_root, environment.get("PYTHONPATH", ""),
            )))
            completed = subprocess.run(
                [
                    sys.executable, "-m", "hocuspocus.hocusscript", "check",
                    "src/main.hocus", "--project", str(root), "--json",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["valid"])
            self.assertEqual(completed.stderr, "")
            self.assertNotIn(str(root), completed.stdout)

    def test_json_project_failures_do_not_leak_host_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "private-project"
            code, output, errors = _run([
                "check", "src/main.hocus", "--project", str(missing), "--json",
            ])
            self.assertEqual(code, 1)
            self.assertEqual(errors, "")
            self.assertFalse(json.loads(output)["valid"])
            self.assertNotIn(str(missing), output)

            root = Path(temporary) / "project"
            _prepare_project(root)
            code, output, errors = _run([
                "check", "src/missing.hocus", "--project", str(root), "--json",
            ])
            self.assertEqual(code, 1)
            self.assertEqual(errors, "")
            self.assertFalse(json.loads(output)["valid"])
            self.assertNotIn(str(root), output)


if __name__ == "__main__":
    unittest.main()
