"""Select the native project build lane for H6 source operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .bundle import CompiledBundle
from .control_compiler import (
    compile_project_control_program,
    compile_project_mixed_control_program,
)
from .module_compiler import (
    compile_project_mixed_module_graph,
    compile_project_module_graph,
)
from .module_semantic import (
    compile_project_mixed_module_bundle,
    compile_project_module_bundle,
)
from .project import ProjectContext, compile_path
from .project_service_support import SourceServiceError


def check_project(
    project: ProjectContext,
    entry: Path,
    roots: Mapping[str, Path],
    mixed: bool,
    cancelled: Callable[[], bool] | None,
) -> Any:
    """Validate one entry through its frozen language and manifest lane."""

    if project.manifest_version in {4, 5}:
        function = (
            compile_project_mixed_control_program
            if mixed
            else compile_project_control_program
        )
    elif project.manifest_version == 3:
        function = (
            compile_project_mixed_module_graph
            if mixed
            else compile_project_module_graph
        )
    elif _flat_project_lane(project, mixed):
        _checkpoint(cancelled)
        result = compile_path(
            entry,
            project_directory=project.root,
            strict=True,
            validate_lock=True,
        )
        _checkpoint(cancelled)
        return result
    else:
        raise SourceServiceError(
            "HOCUS830",
            "Project build does not support this manifest/language lane.",
        )
    if mixed:
        return function(project.root, entry, roots, cancelled=cancelled)
    return function(project.root, entry, cancelled=cancelled)


def compile_project(
    project: ProjectContext,
    entry: Path,
    roots: Mapping[str, Path],
    mixed: bool,
    cancelled: Callable[[], bool] | None,
) -> Any:
    """Compile one entry to the carrier appropriate for its frozen lane."""

    if project.manifest_version in {4, 5}:
        return check_project(project, entry, roots, mixed, cancelled).bundle
    if _flat_project_lane(project, mixed):
        result = check_project(project, entry, roots, mixed, cancelled)
        _checkpoint(cancelled)
        return CompiledBundle.from_result(result)
    if project.manifest_version != 3:
        raise SourceServiceError(
            "HOCUS830",
            "Project compile does not support this manifest/language lane.",
        )
    function = (
        compile_project_mixed_module_bundle
        if mixed
        else compile_project_module_bundle
    )
    if mixed:
        return function(project.root, entry, roots, cancelled=cancelled)
    return function(project.root, entry, cancelled=cancelled)


def _flat_project_lane(project: ProjectContext, mixed: bool) -> bool:
    return (
        not mixed
        and project.manifest_version in {1, 2}
        and project.language_version == "0.1"
    )


def _checkpoint(cancelled: Callable[[], bool] | None) -> None:
    if callable(cancelled) and cancelled():
        raise SourceServiceError("HOCUS825", "Source build was cancelled.")


__all__ = ["check_project", "compile_project"]
