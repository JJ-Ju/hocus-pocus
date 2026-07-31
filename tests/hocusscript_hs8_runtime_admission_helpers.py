"""Focused hostile checks for installed host and Python-loader admission."""

from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import hocuspocus.startup as startup_module
from hocuspocus.core.settings import ServerSettings


ROOT = Path(__file__).resolve().parents[1]
PYTHONRC = ROOT / "scripts" / "python" / "pythonrc.py"
_GOVERNED_ROOTS = (
    "config",
    "docs/schemas",
    "python_panels",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package",
)


def assert_hs8_runtime_admission(testcase: Any) -> None:
    """Prove exact H22 admission precedes construction and rejects bytecode."""

    original_runtime = startup_module._runtime
    original_failure = startup_module._startup_failure
    startup_module._runtime = None
    startup_module._startup_failure = None
    try:
        _assert_wrong_host_rejected(testcase)
        _assert_exact_host_constructs(testcase)
        _assert_external_cache_rejected(testcase)
        _assert_loaded_bytecode_rejected(testcase)
        _assert_pythonrc_source_only_subprocess(testcase)
    finally:
        startup_module._runtime = original_runtime
        startup_module._startup_failure = original_failure


def _loader_patches() -> tuple[Any, Any, Any]:
    return (
        mock.patch.object(sys, "pycache_prefix", None),
        mock.patch.object(sys, "dont_write_bytecode", True),
        mock.patch.object(
            startup_module, "_cached_file_exists", return_value=False,
        ),
    )


def _assert_wrong_host_rejected(testcase: Any) -> None:
    prefix, writes, cached = _loader_patches()
    with (
        prefix,
        writes,
        cached,
        mock.patch.object(
            startup_module, "_houdini_version", return_value="22.0.999",
        ),
        mock.patch(
            "hocuspocus.core.server.HocusPocusRuntime",
        ) as runtime_class,
    ):
        with testcase.assertRaises(startup_module.RuntimeAdmissionError) as caught:
            startup_module.start_server()
        testcase.assertEqual(caught.exception.code, "HOCUS998")
        runtime_class.assert_not_called()
    with mock.patch.object(
        startup_module, "load_settings", return_value=ServerSettings(),
    ):
        failure = startup_module.server_status()["startupFailure"]
    testcase.assertEqual(failure["reason"], "unsupported_houdini")
    testcase.assertNotIn("\\", failure["message"])


def _assert_exact_host_constructs(testcase: Any) -> None:
    prefix, writes, cached = _loader_patches()
    runtime = mock.Mock()
    runtime.status.return_value = {"running": True}
    with (
        prefix,
        writes,
        cached,
        mock.patch.object(
            startup_module, "_houdini_version", return_value="22.0.368",
        ),
        mock.patch.object(
            startup_module, "load_settings", return_value=ServerSettings(),
        ),
        mock.patch.object(
            startup_module, "configure_logging", return_value=mock.Mock(),
        ),
        mock.patch(
            "hocuspocus.core.server.HocusPocusRuntime",
            return_value=runtime,
        ) as runtime_class,
    ):
        testcase.assertTrue(startup_module.start_server()["running"])
        runtime_class.assert_called_once()
        runtime.start.assert_called_once()
        startup_module.stop_server()


def _assert_external_cache_rejected(testcase: Any) -> None:
    with (
        mock.patch.object(sys, "pycache_prefix", "C:/hostile-cache"),
        mock.patch.object(sys, "dont_write_bytecode", True),
        mock.patch.object(
            startup_module, "_houdini_version", return_value="22.0.368",
        ),
        testcase.assertRaisesRegex(
            startup_module.RuntimeAdmissionError, "bytecode caching",
        ),
    ):
        startup_module.start_server()


def _assert_loaded_bytecode_rejected(testcase: Any) -> None:
    with tempfile.TemporaryDirectory(prefix="hs8-bytecode-admission-") as raw:
        cached = Path(raw) / "hostile.pyc"
        cached.write_bytes(b"not governed")
        hostile = SimpleNamespace(__cached__=str(cached))
        with (
            mock.patch.dict(
                sys.modules, {"hocuspocus.hostile_probe": hostile},
            ),
            mock.patch.object(sys, "pycache_prefix", None),
            mock.patch.object(sys, "dont_write_bytecode", True),
            mock.patch.object(
                startup_module, "_houdini_version", return_value="22.0.368",
            ),
            mock.patch.object(
                startup_module, "_governed_module_name",
                side_effect=lambda name: name == "hocuspocus.hostile_probe",
            ),
            testcase.assertRaisesRegex(
                startup_module.RuntimeAdmissionError,
                "ungoverned loaded Python bytecode",
            ),
        ):
            startup_module.start_server()


def _fixture_install(root: Path) -> None:
    for relative in _GOVERNED_ROOTS:
        root.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=True)
    bootstrap = root / "scripts" / "python" / "pythonrc.py"
    bootstrap.parent.mkdir(parents=True, exist_ok=True)
    bootstrap.write_bytes(PYTHONRC.read_bytes())
    package = root / "python3.11libs" / "hocuspocus"
    (package / "core").mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        "def server_status():\n"
        "    return {'running': False, 'fixture': 'source'}\n"
        "def start_server():\n"
        "    raise AssertionError('autostart must remain disabled')\n",
        encoding="utf-8",
    )
    (package / "core" / "__init__.py").write_text("", encoding="utf-8")
    (package / "core" / "settings.py").write_text(
        "from types import SimpleNamespace\n"
        "def load_settings():\n"
        "    return SimpleNamespace(auto_start=False)\n",
        encoding="utf-8",
    )


_BOOTSTRAP_DRIVER = """
import json
import os
import runpy
import sys
import types

sys.path.insert(0, os.environ["HOCUS_TEST_WINNER"])
if os.environ.get("HOCUS_TEST_PRELOAD") == "1":
    sys.modules["hocuspocus"] = types.ModuleType("hocuspocus")
namespace = runpy.run_path(os.environ["HOCUS_TEST_BOOTSTRAP"], run_name="__main__")
print(json.dumps(namespace["hocuspocus_server_status"](), sort_keys=True))
"""


def _run_bootstrap(
    root: Path,
    *,
    configured_root: Path | None = None,
    winner: Path | None = None,
    preload: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HOCUSPOCUS_ROOT": str(configured_root or root),
            "HOCUS_TEST_BOOTSTRAP": str(
                root / "scripts" / "python" / "pythonrc.py"
            ),
            "HOCUS_TEST_WINNER": str(
                (winner or root) / "python3.11libs"
            ),
        }
    )
    if preload:
        environment["HOCUS_TEST_PRELOAD"] = "1"
    else:
        environment.pop("HOCUS_TEST_PRELOAD", None)
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", _BOOTSTRAP_DRIVER],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=20,
    )


def _assert_bootstrap_rejection(
    testcase: Any,
    result: subprocess.CompletedProcess[str],
    reason: str,
    physical_roots: tuple[Path, ...],
) -> None:
    testcase.assertEqual(result.returncode, 0, result.stderr)
    testcase.assertIn(f"HOCUS998 HocusPocus startup blocked: {reason}.", result.stderr)
    status = json.loads(result.stdout)
    testcase.assertFalse(status["running"])
    testcase.assertEqual(status["startupFailure"]["reason"], reason)
    combined = result.stdout + result.stderr
    for root in physical_roots:
        testcase.assertNotIn(str(root), combined)


def _install_valid_hostile_bytecode(root: Path, marker: Path) -> None:
    source = root / "python3.11libs" / "hocuspocus" / "__init__.py"
    benign = source.read_bytes()
    source.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['HOCUS_TEST_MARKER']).write_text('executed')\n",
        encoding="utf-8",
    )
    py_compile.compile(
        str(source),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )
    source.write_bytes(benign)
    environment = os.environ.copy()
    environment["HOCUS_TEST_MARKER"] = str(marker)
    control = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            (
                "import os,sys;"
                "sys.path.insert(0,os.environ['HOCUS_TEST_WINNER']);"
                "import hocuspocus"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **environment,
            "HOCUS_TEST_WINNER": str(root / "python3.11libs"),
        },
        timeout=20,
    )
    if control.returncode != 0 or not marker.is_file():
        raise AssertionError("Hostile bytecode fixture was not import-valid.")
    marker.unlink()


def _assert_pythonrc_source_only_subprocess(testcase: Any) -> None:
    with tempfile.TemporaryDirectory(prefix="hs8-source-admission-") as raw:
        base = Path(raw)
        installed = base / "installed"
        other = base / "other"
        shadow = base / "shadow"
        marker = base / "hostile-marker"
        _fixture_install(installed)
        _fixture_install(shadow)
        other.mkdir()
        (shadow / "python3.11libs" / "hocuspocus" / "__init__.py").write_text(
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['HOCUS_TEST_MARKER']).write_text('shadowed')\n",
            encoding="utf-8",
        )

        with testcase.subTest("exact source winner"):
            result = _run_bootstrap(installed)
            testcase.assertEqual(result.returncode, 0, result.stderr)
            testcase.assertEqual(
                json.loads(result.stdout),
                {"fixture": "source", "running": False},
            )
            testcase.assertEqual(result.stderr, "")

        with testcase.subTest("wrong installed root"):
            result = _run_bootstrap(installed, configured_root=other)
            _assert_bootstrap_rejection(
                testcase,
                result,
                "invalid_install_root",
                (installed, other),
            )

        with testcase.subTest("wrong import winner"):
            environment_marker = os.environ.get("HOCUS_TEST_MARKER")
            os.environ["HOCUS_TEST_MARKER"] = str(marker)
            try:
                result = _run_bootstrap(installed, winner=shadow)
            finally:
                if environment_marker is None:
                    os.environ.pop("HOCUS_TEST_MARKER", None)
                else:
                    os.environ["HOCUS_TEST_MARKER"] = environment_marker
            _assert_bootstrap_rejection(
                testcase,
                result,
                "invalid_import_winner",
                (installed, shadow),
            )
            testcase.assertFalse(marker.exists())

        with testcase.subTest("preloaded module"):
            result = _run_bootstrap(installed, preload=True)
            _assert_bootstrap_rejection(
                testcase,
                result,
                "preloaded_module",
                (installed,),
            )

        with testcase.subTest("valid adjacent bytecode"):
            _install_valid_hostile_bytecode(installed, marker)
            environment_marker = os.environ.get("HOCUS_TEST_MARKER")
            os.environ["HOCUS_TEST_MARKER"] = str(marker)
            try:
                result = _run_bootstrap(installed)
            finally:
                if environment_marker is None:
                    os.environ.pop("HOCUS_TEST_MARKER", None)
                else:
                    os.environ["HOCUS_TEST_MARKER"] = environment_marker
            _assert_bootstrap_rejection(
                testcase,
                result,
                "ungoverned_bytecode",
                (installed,),
            )
            testcase.assertFalse(marker.exists())


__all__ = ["assert_hs8_runtime_admission"]
