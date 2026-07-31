"""Houdini startup helpers for HocusPocus."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import stat
import sys
from typing import Any


_GOVERNED_ROOTS = (
    "config",
    "docs/schemas",
    "python_panels",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package",
)
_MAX_GOVERNED_ENTRIES = 4096
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_hocuspocus: Any | None = None
_bootstrap_failure: dict[str, str] | None = None
_source_only_finder: Any | None = None


class _BootstrapAdmissionError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


_PYTHONRC_SOURCE = Path(_BootstrapAdmissionError.__init__.__code__.co_filename)


class _SourceOnlyFinder:
    """Load governed HocusPocus modules from source without consulting bytecode."""

    def __init__(self, package_root: Path):
        self._package_root = package_root.resolve(strict=True)

    def _source_for(self, fullname: str) -> tuple[Path, bool]:
        parts = fullname.split(".")
        if not parts or parts[0] != "hocuspocus":
            raise ImportError("HOCUS998 source-only loader scope violation.")
        target = self._package_root.joinpath(*parts[1:])
        package_source = target / "__init__.py"
        module_source = target.with_suffix(".py")
        candidate = package_source if package_source.is_file() else module_source
        try:
            metadata = os.lstat(candidate)
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._package_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ImportError("HOCUS998 governed source is unavailable.") from exc
        if _is_alias(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise ImportError("HOCUS998 governed source is unsafe.")
        return resolved, candidate == package_source

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: Any = None,
    ):
        if fullname != "hocuspocus" and not fullname.startswith("hocuspocus."):
            return None
        source, is_package = self._source_for(fullname)
        locations = [str(source.parent)] if is_package else None
        return importlib.util.spec_from_file_location(
            fullname,
            source,
            loader=self,
            submodule_search_locations=locations,
        )

    @staticmethod
    def create_module(spec):
        return None

    def exec_module(self, module) -> None:
        source, _ = self._source_for(module.__name__)
        try:
            payload = source.read_bytes()
            code = compile(payload, str(source), "exec", dont_inherit=True)
        except (OSError, SyntaxError, ValueError) as exc:
            raise ImportError("HOCUS998 governed source could not be loaded.") from exc
        exec(code, module.__dict__)


def hocuspocus_server_status():
    if _bootstrap_failure is not None:
        return {
            "running": False,
            "startupFailure": dict(_bootstrap_failure),
        }
    if _hocuspocus is None:
        return {"running": False}
    return _hocuspocus.server_status()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


def _is_alias(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _installed_root() -> Path:
    try:
        script = _PYTHONRC_SOURCE.resolve(strict=True)
        installed_root = script.parents[2]
        raw_root = os.environ.get("HOCUSPOCUS_ROOT")
        if not raw_root or "\0" in raw_root:
            raise _BootstrapAdmissionError("invalid_install_root")
        configured_root = Path(raw_root).resolve(strict=True)
        if not _same_path(configured_root, installed_root):
            raise _BootstrapAdmissionError("invalid_install_root")
        if _is_alias(os.lstat(installed_root)):
            raise _BootstrapAdmissionError("unsafe_install_alias")
        return installed_root
    except _BootstrapAdmissionError:
        raise
    except (IndexError, OSError, RuntimeError, ValueError) as exc:
        raise _BootstrapAdmissionError("invalid_install_root") from exc


def _reject_ungoverned_bytecode(installed_root: Path) -> None:
    pending: list[Path] = []
    for relative in _GOVERNED_ROOTS:
        governed = installed_root.joinpath(*relative.split("/"))
        try:
            metadata = os.lstat(governed)
        except OSError as exc:
            raise _BootstrapAdmissionError("invalid_install_layout") from exc
        if _is_alias(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise _BootstrapAdmissionError("unsafe_install_alias")
        pending.append(governed)

    seen = 0
    while pending:
        current = pending.pop()
        try:
            entries = os.scandir(current)
        except OSError as exc:
            raise _BootstrapAdmissionError("invalid_install_layout") from exc
        with entries:
            for entry in entries:
                seen += 1
                if seen > _MAX_GOVERNED_ENTRIES:
                    raise _BootstrapAdmissionError("install_layout_too_large")
                folded = entry.name.casefold()
                if folded == "__pycache__" or folded.endswith((".pyc", ".pyo")):
                    raise _BootstrapAdmissionError("ungoverned_bytecode")
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise _BootstrapAdmissionError("invalid_install_layout") from exc
                if _is_alias(metadata):
                    raise _BootstrapAdmissionError("unsafe_install_alias")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(Path(entry.path))


def _reject_preloaded_modules() -> None:
    if any(
        name == "hocuspocus" or name.startswith("hocuspocus.")
        for name in tuple(sys.modules)
    ):
        raise _BootstrapAdmissionError("preloaded_module")


def _verify_import_winner(installed_root: Path) -> None:
    global _source_only_finder
    expected_package = installed_root / "python3.11libs" / "hocuspocus"
    expected_origin = expected_package / "__init__.py"
    try:
        specification = importlib.machinery.PathFinder.find_spec("hocuspocus")
        if (
            specification is None
            or specification.origin is None
            or not isinstance(
                specification.loader,
                importlib.machinery.SourceFileLoader,
            )
        ):
            raise _BootstrapAdmissionError("invalid_import_winner")
        origin = Path(specification.origin).resolve(strict=True)
        locations = tuple(specification.submodule_search_locations or ())
        if len(locations) != 1:
            raise _BootstrapAdmissionError("invalid_import_winner")
        package = Path(locations[0]).resolve(strict=True)
        if (
            not _same_path(origin, expected_origin.resolve(strict=True))
            or not _same_path(package, expected_package.resolve(strict=True))
        ):
            raise _BootstrapAdmissionError("invalid_import_winner")
        finder = _SourceOnlyFinder(expected_package)
        sys.meta_path.insert(0, finder)
        _source_only_finder = finder
    except _BootstrapAdmissionError:
        raise
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise _BootstrapAdmissionError("invalid_import_winner") from exc


def _admit_source_import() -> None:
    installed_root = _installed_root()
    _reject_preloaded_modules()
    _reject_ungoverned_bytecode(installed_root)
    _verify_import_winner(installed_root)


def _record_bootstrap_failure(reason: str) -> None:
    global _bootstrap_failure
    _bootstrap_failure = {
        "code": "HOCUS998",
        "kind": "runtime_admission",
        "reason": reason,
        "message": "HocusPocus startup was blocked by source admission.",
    }
    message = f"HOCUS998 HocusPocus startup blocked: {reason}."
    sys.stderr.write(message + "\n")
    try:
        import hou  # type: ignore

        hou.ui.setStatusMessage(message, severity=hou.severityType.Error)
    except Exception:
        pass


def _maybe_autostart_hocuspocus() -> None:
    global _hocuspocus
    try:
        _admit_source_import()
        import hocuspocus
        from hocuspocus.core.settings import load_settings
    except _BootstrapAdmissionError as exc:
        _record_bootstrap_failure(exc.reason)
        return
    except Exception:
        _record_bootstrap_failure("source_import_failed")
        return

    _hocuspocus = hocuspocus
    try:
        settings = load_settings()
    except Exception:
        return
    if not settings.auto_start:
        return
    try:
        hocuspocus.start_server()
    except Exception:
        # Runtime admission retains a sanitized HOCUS998 status after import.
        return


_maybe_autostart_hocuspocus()
