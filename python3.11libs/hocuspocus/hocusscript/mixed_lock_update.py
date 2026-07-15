"""Explicit leased publication of independently derived mixed-root locks."""

from __future__ import annotations

from os import PathLike
from typing import Callable, Iterable, Mapping

from .external_roots import _bounded_authored_roots
from .lock_update import _bounded_entries
from .mixed_lock_update_result import MixedModuleLockUpdateResult
from .module_lock_plan import _MixedModuleLockDerivation, _derive_mixed_module_lock
from .project import (
    DIGEST_PATTERN,
    LockVerificationResult,
    ProjectContext,
    ProjectError,
    _publish_derived_mixed_module_lock,
)
from .resolved_modules import ResolvedModuleLimits, _validate_limits
from .resolver import _validate_project_directory


def update_project_mixed_module_lock(
    project_directory: str | PathLike[str],
    entry_source_paths: Iterable[str | PathLike[str]],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    expected_lock_digest: str,
    allow_write: bool = False,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> MixedModuleLockUpdateResult:
    """Independently derive and atomically publish a mixed project/library lock."""

    if allow_write is not True:
        raise ProjectError(
            "HOCUS455",
            "Mixed module lock publication requires explicit allow_write=True authority.",
        )
    if (
        type(expected_lock_digest) is not str
        or DIGEST_PATTERN.fullmatch(expected_lock_digest) is None
    ):
        raise ProjectError(
            "HOCUS453",
            "Mixed module lock publication requires an exact current lock digest.",
        )
    project_value = _validate_project_directory(project_directory)
    selected_limits = limits or ResolvedModuleLimits()
    _validate_limits(selected_limits)
    authored_entries = _bounded_entries(
        entry_source_paths,
        selected_limits.module_files,
        cancelled,
    )
    authored_roots = _bounded_authored_roots(module_roots, cancelled)
    retained: _MixedModuleLockDerivation | None = None

    def derive(project: ProjectContext):
        nonlocal retained
        retained = _derive_mixed_module_lock(
            project.root,
            authored_entries,
            authored_roots,
            limits=selected_limits,
            cancelled=cancelled,
        )
        if (
            retained.project_uid != project.uid
            or retained.manifest_digest != project.manifest_digest
            or retained.current_lock_digest != expected_lock_digest
        ):
            raise ProjectError(
                "HOCUS453",
                "Mixed module derivation does not match the leased project snapshot.",
            )
        return retained.modules, retained.recheck

    def build_result(
        previous: str,
        before: LockVerificationResult,
        after: LockVerificationResult,
        catalog_digest: str,
        catalog_fingerprint: str,
    ) -> MixedModuleLockUpdateResult:
        if retained is None:
            raise ProjectError("HOCUS459", "Mixed module derivation result is unavailable.")
        # This plan-shaped validation is reconstructed solely from retained
        # under-lease evidence; no caller plan or digest reaches this path.
        plan = retained.plan_result()
        if (
            previous != expected_lock_digest
            or before.lock_digest != previous
            or before.project_uid != retained.project_uid
            or before.manifest_digest != retained.manifest_digest
            or before.modules != retained.current_modules
            or after.project_uid != retained.project_uid
            or after.manifest_digest != retained.manifest_digest
            or after.modules != retained.modules
            or after.lock_digest != plan.prospective_lock_digest
            or catalog_digest != retained.catalog_content_digest
            or catalog_fingerprint != retained.catalog_fingerprint
        ):
            raise ProjectError(
                "HOCUS459",
                "Mixed module publication result conflicts with its under-lease derivation.",
            )
        before_by_uri = {item.module_uri: item for item in before.modules}
        after_by_uri = {item.module_uri: item for item in after.modules}
        added = tuple(sorted(set(after_by_uri) - set(before_by_uri)))
        removed = tuple(sorted(set(before_by_uri) - set(after_by_uri)))
        changed = tuple(sorted(
            uri for uri in set(before_by_uri) & set(after_by_uri)
            if before_by_uri[uri] != after_by_uri[uri]
        ))
        if (
            added != plan.added_uris
            or removed != plan.removed_uris
            or changed != plan.changed_uris
        ):
            raise ProjectError("HOCUS459", "Mixed module publication diff is inconsistent.")
        return MixedModuleLockUpdateResult(
            retained.project_uid,
            retained.manifest_digest,
            previous,
            after.lock_digest,
            retained.catalog_path,
            catalog_digest,
            catalog_fingerprint,
            retained.external_roots_inspection_digest,
            retained.resolver_policy_digest,
            retained.entries,
            retained.modules,
            added,
            removed,
            changed,
        )

    return _publish_derived_mixed_module_lock(
        project_value,
        expected_lock_digest=expected_lock_digest,
        derive=derive,
        build_result=build_result,
    )
