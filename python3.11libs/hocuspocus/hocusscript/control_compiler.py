"""One-shot native compiler for the same-project HocusScript 0.3 lane."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from os import PathLike
from typing import Any, Callable, Mapping

from .control_artifact import ControlCompiledBundle, _compile_control_bundle
from .control_catalog import (
    ControlCatalogValidationResult,
    validate_control_catalog_program,
)
from .control_expander import expand_control_graph
from .control_resolver import (
    ControlResolverLimits,
    ResolvedControlProgram,
    resolve_project_control_program,
)
from .control_mixed_resolution import resolve_project_mixed_control_program
from .control_semantic import ControlExpansionLimits
from .formatter import format_syntax


class ControlProjectCompileError(ValueError):
    """Typed failure at the native HocusScript 0.3 compiler boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ControlProjectCompileResult:
    """Portable authenticated output from one exact native compiler session."""

    project_uid: str
    project_manifest_digest: str
    project_lock_digest: str
    catalog_content_digest: str
    catalog_fingerprint: str
    resolver_policy_digest: str
    entry_source_uri: str
    entry_source_digest: str
    formatted_entry_source: str
    formatted_entry_source_digest: str
    resolved_module_set_json: str
    resolved_module_set_digest: str
    handoff_digest: str
    graph_spec_json: str
    graph_spec_digest: str
    catalog_admission: ControlCatalogValidationResult
    bundle: ControlCompiledBundle
    compile_digest: str

    @property
    def valid(self) -> bool:
        return True

    @property
    def graph_spec(self) -> dict[str, Any]:
        return json.loads(self.graph_spec_json)

    @property
    def resolved_module_set(self) -> dict[str, Any]:
        return json.loads(self.resolved_module_set_json)

    @property
    def semantic(self) -> dict[str, Any]:
        return self.bundle.payload["semanticResolution"]

    def to_dict(self) -> dict[str, Any]:
        diagnostics = self.semantic["diagnostics"]
        payload = self.bundle.payload
        return {
            "stage": "semantic",
            "valid": True,
            "compilerVersion": payload["compilerVersion"],
            "graphSpecVersion": payload["graphSpecVersion"],
            "languageVersion": payload["languageVersion"],
            "projectUid": self.project_uid,
            "projectManifestDigest": self.project_manifest_digest,
            "projectLockDigest": self.project_lock_digest,
            "catalogContentDigest": self.catalog_content_digest,
            "catalogFingerprint": self.catalog_fingerprint,
            "resolverPolicyDigest": self.resolver_policy_digest,
            "entrySourceUri": self.entry_source_uri,
            "entrySourceDigest": self.entry_source_digest,
            "formattedEntrySource": self.formatted_entry_source,
            "formattedEntrySourceDigest": self.formatted_entry_source_digest,
            "resolvedModuleSet": self.resolved_module_set,
            "resolvedModuleSetDigest": self.resolved_module_set_digest,
            "handoffDigest": self.handoff_digest,
            "graphSpec": self.graph_spec,
            "graphSpecDigest": self.graph_spec_digest,
            "catalogAdmission": self.catalog_admission.to_dict(),
            "semanticResolution": self.semantic,
            "diagnosticCount": len(diagnostics),
            "diagnostics": diagnostics,
            "bundleDigest": self.bundle.digest,
            "compileDigest": self.compile_digest,
            "readyForDocumentLowering": True,
            "readyForApply": False,
        }

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
        return _canonical_json(self.to_dict())


def compile_project_control_program(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    *,
    limits: ControlResolverLimits | ControlExpansionLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ControlProjectCompileResult:
    """Resolve, admit, expand, semantically resolve, and bundle one v4 entry."""

    program = resolve_project_control_program(
        project_directory,
        entry_source_path,
        limits=limits,
        cancelled=cancelled,
    )
    return _compile_resolved_control_program(program, cancelled)


def compile_project_mixed_control_program(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ControlResolverLimits | ControlExpansionLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ControlProjectCompileResult:
    """Compile one v4 entry through an exact per-call external root mapping."""

    program = resolve_project_mixed_control_program(
        project_directory,
        entry_source_path,
        module_roots,
        limits=limits,
        cancelled=cancelled,
    )
    return _compile_resolved_control_program(program, cancelled)


def _compile_resolved_control_program(
    program: ResolvedControlProgram,
    cancelled: Callable[[], bool] | None,
) -> ControlProjectCompileResult:
    catalog = program._project.catalog
    if catalog is None:
        raise ControlProjectCompileError(
            "HOCUS495",
            "Native control compilation requires the verified catalog snapshot.",
        )
    admission = validate_control_catalog_program(
        program.entry_syntax,
        program.entry_imports,
        program.modules,
        catalog,
        expected_catalog_fingerprint=program.catalog_fingerprint,
        limits=program.control_limits,
        cancellation=cancelled,
    )
    if not admission.valid:
        primary = admission.diagnostics[0]
        raise ControlProjectCompileError(
            primary.code,
            primary.message,
            details={
                "diagnostic": primary.to_dict(),
                "diagnostics": [item.to_dict() for item in admission.diagnostics],
            },
        )
    graph = expand_control_graph(
        program.entry_source,
        program.entry_source_uri,
        program.entry_imports,
        program.modules,
        limits=program.control_limits,
        cancellation=cancelled,
    )
    bundle = _compile_control_bundle(
        graph,
        program.resolved_module_set,
        entry_source_digest=program.entry_source_digest,
        catalog=catalog,
        catalog_content_digest=program.catalog_content_digest,
        catalog_fingerprint=program.catalog_fingerprint,
        admitted_required_capabilities=admission.required_capabilities,
    )
    program.recheck()
    return _build_result(program, graph, admission, bundle)


def _build_result(
    program: ResolvedControlProgram,
    graph: dict[str, Any],
    admission: ControlCatalogValidationResult,
    bundle: ControlCompiledBundle,
) -> ControlProjectCompileResult:
    bundle_payload = bundle.payload
    formatted = format_syntax(program.entry_syntax)
    formatted_digest = _digest_text(formatted)
    graph_json = _canonical_json(graph)
    graph_digest = _digest_text(graph_json)
    core = {
        "domain": "hocus-control-project-compile-v1",
        "compilerVersion": bundle_payload["compilerVersion"],
        "projectUid": program.project_uid,
        "projectManifestDigest": program.project_manifest_digest,
        "projectLockDigest": program.project_lock_digest,
        "catalogContentDigest": program.catalog_content_digest,
        "catalogFingerprint": program.catalog_fingerprint,
        "resolverPolicyDigest": program.resolver_policy_digest,
        "entrySourceUri": program.entry_source_uri,
        "entrySourceDigest": program.entry_source_digest,
        "formattedEntrySourceDigest": formatted_digest,
        "resolvedModuleSetDigest": program.resolved_module_set_digest,
        "handoffDigest": program.handoff_digest,
        "graphSpecDigest": graph_digest,
        "bundleDigest": bundle.digest,
    }
    return ControlProjectCompileResult(
        program.project_uid,
        program.project_manifest_digest,
        program.project_lock_digest,
        program.catalog_content_digest,
        program.catalog_fingerprint,
        program.resolver_policy_digest,
        program.entry_source_uri,
        program.entry_source_digest,
        formatted,
        formatted_digest,
        program.resolved_module_set_json,
        program.resolved_module_set_digest,
        program.handoff_digest,
        graph_json,
        graph_digest,
        admission,
        bundle,
        _digest_text(_canonical_json(core)),
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ControlProjectCompileError",
    "ControlProjectCompileResult",
    "compile_project_mixed_control_program",
    "compile_project_control_program",
]
