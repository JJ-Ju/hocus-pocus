"""Leased publication of explicit-root HocusScript 0.3 module locks."""

from __future__ import annotations

from os import PathLike
from typing import Callable, Iterable, Mapping

from .control_lock_update import _load_catalog, _lock_payload
from .control_mixed_resolution import (
    _MixedControlSession,
    _project_pins,
)
from .control_resolver import ControlResolverLimits, _select_limits
from .control_semantic import ControlExpansionLimits
from .external_roots import _bounded_authored_roots
from .lock_update import _bounded_entries
from .lock_update_result import ModuleLockUpdateEntry, ModuleLockUpdateResult
from .project import (
    DIGEST_PATTERN,
    LockVerificationResult,
    ModuleLockRecord,
    ProjectContext,
    ProjectError,
    _atomic_write_lock,
    _check_expected_lock,
    _exclusive_update_lease,
    _recheck_update_inputs,
    verify_project_lock,
)
from .project_lock_validation import validate_module_locks
from .resolved_modules import module_source_digest
from .resolver import _validate_project_directory


def update_project_mixed_control_lock(
    project_directory: str | PathLike[str],
    entry_source_paths: Iterable[str | PathLike[str]],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    expected_lock_digest: str,
    allow_write: bool = False,
    limits: ControlResolverLimits | ControlExpansionLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleLockUpdateResult:
    """Independently derive and publish a mixed v4 lock under exact authority."""

    if allow_write is not True:
        raise ProjectError(
            "HOCUS455",
            "Mixed control lock publication requires explicit allow_write=True authority.",
        )
    if (
        type(expected_lock_digest) is not str
        or DIGEST_PATTERN.fullmatch(expected_lock_digest) is None
    ):
        raise ProjectError(
            "HOCUS453",
            "Mixed control lock publication requires an exact current lock digest.",
        )
    project_value = _validate_project_directory(project_directory)
    resolver_limits, control_limits = _select_limits(limits)
    entries = _bounded_entries(
        entry_source_paths,
        resolver_limits.module_files,
        cancelled,
    )
    roots = _bounded_authored_roots(module_roots, cancelled)
    return _publish_mixed_control_lock(
        project_value,
        entries,
        roots,
        expected_lock_digest=expected_lock_digest,
        limits=resolver_limits,
        control_limits=control_limits,
        cancelled=cancelled,
    )


def _publish_mixed_control_lock(
    project_directory: str,
    entries: tuple[str, ...],
    module_roots: Mapping[str, PathLike[str] | str],
    *,
    expected_lock_digest: str,
    limits: ControlResolverLimits,
    control_limits: ControlExpansionLimits,
    cancelled: Callable[[], bool] | None,
) -> ModuleLockUpdateResult:
    initial = ProjectContext.load(project_directory, validate_lock=False)
    _require_mixed_publish_project(initial)
    assert initial.lock_path is not None
    with _exclusive_update_lease(initial.lock_path):
        project = ProjectContext.load(project_directory, validate_lock=False)
        _require_stable_mixed_project(initial, project)
        assert project.lock_path is not None
        prior_digest = _check_expected_lock(
            project.lock_path,
            project.root,
            expected_lock_digest,
        )
        if prior_digest is None:
            raise ProjectError(
                "HOCUS453",
                "Mixed control publication requires a valid existing v4 lock.",
            )
        before = verify_project_lock(project.root)
        if before.lock_digest != prior_digest:
            raise ProjectError(
                "HOCUS453",
                "Verified v4 lock does not match expected publication authority.",
            )
        catalog, catalog_digest = _load_catalog(project)
        session = _MixedControlSession.create(
            project.root,
            entries,
            module_roots,
            limits,
            control_limits,
            cancelled,
            verify_lock=False,
        )
        _require_leased_session(project, before, session)
        session.scan()
        modules = _strict_mixed_modules(
            session.derive_records(),
            project,
        )
        session.validate_entries(catalog)
        encoded, lock_digest = _lock_payload(
            project,
            modules,
            catalog,
            catalog_digest,
        )
        after = LockVerificationResult(
            project.uid or "",
            project.manifest_digest or "",
            lock_digest,
            modules,
        )
        result = ModuleLockUpdateResult.from_verifications(
            before,
            after,
            previous_lock_digest=prior_digest,
            catalog_content_digest=catalog_digest,
            catalog_fingerprint=catalog.fingerprint,
            entries=tuple(
                ModuleLockUpdateEntry(
                    entry.target.uri,
                    module_source_digest(entry.source),
                )
                for entry in session.entries
            ),
        )

        def before_publish() -> None:
            _recheck_update_inputs(
                project,
                catalog_digest=catalog_digest,
                initial_lock_digest=prior_digest,
            )
            session.recheck()

        _atomic_write_lock(
            project.lock_path,
            encoded,
            expected_lock_digest=expected_lock_digest,
            before_publish=before_publish,
        )
        return result


def _strict_mixed_modules(
    modules: tuple[ModuleLockRecord, ...],
    project: ProjectContext,
) -> tuple[ModuleLockRecord, ...]:
    validated = validate_module_locks(
        [item.to_dict() for item in modules],
        project_uid=project.uid or "",
        external_aliases=project.external_aliases,
        expected_language_version="0.3",
    )
    if validated != modules:
        raise ProjectError(
            "HOCUS451",
            "Derived mixed control records are not canonical.",
        )
    return validated


def _require_mixed_publish_project(project: ProjectContext) -> None:
    if (
        project.manifest_version != 4
        or project.language_version != "0.3"
        or project.uid is None
        or project.manifest_digest is None
        or project.lock_path is None
        or project.catalog_path is None
        or project.catalog_relative_path is None
        or not project.external_aliases
    ):
        raise ProjectError(
            "HOCUS452",
            "Mixed control publication requires a portable v4 project with aliases.",
        )


def _require_stable_mixed_project(
    initial: ProjectContext,
    project: ProjectContext,
) -> None:
    _require_mixed_publish_project(project)
    if (
        project.root != initial.root
        or project.uid != initial.uid
        or project.manifest_digest != initial.manifest_digest
        or project.lock_path != initial.lock_path
        or project.catalog_path != initial.catalog_path
        or project.catalog_relative_path != initial.catalog_relative_path
        or project.module_directory_paths != initial.module_directory_paths
        or project.external_aliases != initial.external_aliases
    ):
        raise ProjectError(
            "HOCUS453",
            "Mixed control project configuration changed before lock update.",
        )


def _require_leased_session(
    project: ProjectContext,
    before: LockVerificationResult,
    session: _MixedControlSession,
) -> None:
    context = session.context
    if (
        context.root != project.root
        or context.uid != project.uid
        or context.manifest_digest != project.manifest_digest
        or context.lock_digest != before.lock_digest
        or context.locked_modules != before.modules
        or _project_pins(context)[0:5] != (
            project.root,
            project.uid,
            project.manifest_version,
            project.language_version,
            project.manifest_digest,
        )
    ):
        raise ProjectError(
            "HOCUS453",
            "Mixed control derivation escaped its leased project snapshot.",
        )


__all__ = ["update_project_mixed_control_lock"]
