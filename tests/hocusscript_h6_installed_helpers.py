"""Private contract helper for the single public H6 installed workflow."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "scripts/smoke_hocusscript_h6.py"
H5_MAIN = ROOT / "scripts/smoke_hocusscript_h5.py"
SUPPORT = ROOT / "scripts/smoke_hocusscript_h6_support.py"


def exercise_h6_installed_workflow(
    case: Any,
    receipt: dict[str, Any] | None = None,
) -> None:
    """Qualify the lean installed harness or validate its captured receipt."""

    support = _load_support()
    for path in (MAIN, SUPPORT):
        source = path.read_text(encoding="utf-8")
        case.assertLessEqual(len(source.splitlines()), 1200)
        compile(source, str(path), "exec")
    main_tree = ast.parse(MAIN.read_text(encoding="utf-8"), filename=str(MAIN))
    case.assertFalse(_adds_repository_python_path(main_tree))
    for path in (H5_MAIN, MAIN):
        _assert_wrong_host_rejects_before_side_effects(case, path)
    case.assertEqual(
        tuple(support.SOURCE_TOOL_NAMES),
        (
            "source.project.describe",
            "source.file.search",
            "source.file.read",
            "source.file.apply_patch",
            "source.file.write_export",
            "source.project.build",
            "source.project.navigate",
        ),
    )
    critical = set(support.H6_CRITICAL_MODULES)
    case.assertTrue(
        {
            "hocuspocus.core.workspace_authority",
            "hocuspocus.core.workspace_registry",
            "hocuspocus.hocusscript._workspace_native",
            "hocuspocus.hocusscript.project_services",
            "hocuspocus.hocusscript.project_write_lifecycle",
            "hocuspocus.hocusscript.workspace_io",
            "hocuspocus.live.ops.source_resources",
            "hocuspocus.live.ops.source_workspace",
        }.issubset(critical)
    )
    case.assertEqual(
        set(support.H6_CRITICAL_ARTIFACTS),
        {
            "config/default.toml",
            "python_panels/HocusPocus.pypanel",
        },
    )
    _assert_installer_token_alignment(case, support)
    selected = receipt or _representative_receipt(support)
    support.validate_acceptance_result(selected)
    with case.assertRaises(RuntimeError):
        support.validate_acceptance_result(
            {**selected, "cookExecuted": True},
        )


def _load_support() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_h6_installed_support_contract",
        SUPPORT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the H6 installed support contract.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _adds_repository_python_path(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            node.func.attr in {"append", "insert"}
            and isinstance(owner, ast.Attribute)
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "sys"
            and owner.attr == "path"
        ):
            return True
    return False


def _assert_wrong_host_rejects_before_side_effects(
    case: Any,
    path: Path,
) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    main = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    events: list[str] = []
    namespace = {
        "hou": SimpleNamespace(
            applicationVersionString=lambda: "21.0.729",
            hipFile=SimpleNamespace(
                clear=lambda **_kwargs: events.append("scene-clear"),
            ),
        ),
        "logging": SimpleNamespace(
            INFO=20,
            basicConfig=lambda **_kwargs: events.append("logging"),
        ),
        "tempfile": SimpleNamespace(
            TemporaryDirectory=lambda **_kwargs: events.append("temporary"),
        ),
    }
    module = ast.fix_missing_locations(ast.Module(body=[main], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    with case.subTest(wrong_host_guard=path.name):
        with case.assertRaisesRegex(RuntimeError, "22.0.368"):
            namespace["main"]()
        case.assertEqual(events, [])


def _assert_installer_token_alignment(case: Any, support: ModuleType) -> None:
    repository = (ROOT / "config/default.toml").read_bytes()
    installed = repository.replace(
        b'token = ""',
        b'token = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"',
        1,
    )
    case.assertEqual(
        support.normalize_installed_config(repository, installed),
        repository,
    )
    rejected = {
        "non_token_drift": installed.replace(
            b"auto_start = true",
            b"auto_start = false",
            1,
        ),
        "short_token": installed.replace(
            b"A" * 32,
            b"A" * 31,
            1,
        ),
        "wrong_mode": installed.replace(
            b'token_mode = "generated"',
            b'token_mode = "disabled"',
            1,
        ),
        "duplicate_token": installed + b'\ntoken = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"\n',
    }
    for label, candidate in rejected.items():
        with case.subTest(h6_installer_token_alignment=label):
            with case.assertRaises(RuntimeError):
                support.normalize_installed_config(repository, candidate)


def _representative_receipt(support: ModuleType) -> dict[str, Any]:
    return {
        "status": "passed",
        "alignment": {"houdini": "22.0.368", "h6Modules": {}},
        "sourceTools": list(support.SOURCE_TOOL_NAMES),
        "project": {
            "bundleVersion": "0.4",
            "nativeEditorVisible": True,
        },
        "live": {
            "previewed": True,
            "planned": True,
            "applied": True,
            "verified": True,
        },
        "export": {
            "written": True,
            "recompiled": True,
            "reconciled": True,
            "semanticPreserved": True,
            "exactBytes": True,
            "digestVerified": True,
        },
        "git": {"nativeBytesVisible": True},
        "revocation": {
            "denied": True,
            "resourceDenied": True,
            "listFiltered": True,
        },
        "cookExecuted": False,
    }


__all__ = ["exercise_h6_installed_workflow"]
