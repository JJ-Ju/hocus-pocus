"""Native read-only HocusScript 0.2 project compiler integration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from os import PathLike
from typing import Any, Callable, Mapping

from .diagnostics import Diagnostic
from .expander import ExpansionLimits, expand_resolved_module_dag
from .formatter import format_syntax
from .model import (
    MODULE_COMPILER_VERSION, MODULE_GRAPH_SPEC_VERSION, MODULE_LANGUAGE_VERSION,
    GraphSpec, graph_spec_from_dict,
)
from .mixed_resolution import _resolve_project_mixed_module_session
from .resolved_modules import ResolvedModuleDag, ResolvedModuleLimits
from .resolver import resolve_project_module_dag

MAX_MODULE_COMPILE_RESULT_BYTES = 48 * 1024 * 1024


class ModuleProjectCompileError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class FormattedModuleSource:
    uri: str
    source_digest: str
    interface_digest: str
    transitive_digest: str
    formatted_source: str
    formatted_source_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "uri": self.uri,
            "sourceDigest": self.source_digest,
            "interfaceDigest": self.interface_digest,
            "transitiveDigest": self.transitive_digest,
            "formattedSource": self.formatted_source,
            "formattedSourceDigest": self.formatted_source_digest,
        }


@dataclass(frozen=True, slots=True)
class ModuleProjectCompileResult:
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
    modules: tuple[FormattedModuleSource, ...]
    resolved_module_set_json: str
    resolved_module_set_digest: str
    handoff_digest: str
    graph_spec_json: str
    graph_spec_digest: str
    expansion_map_digest: str
    diagnostics: tuple[Diagnostic, ...]
    compile_digest: str

    @property
    def resolved_module_set(self) -> dict[str, Any]:
        return json.loads(self.resolved_module_set_json)

    @property
    def graph_spec(self) -> GraphSpec:
        return graph_spec_from_dict(json.loads(self.graph_spec_json))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": "expansion",
            "valid": True,
            "compilerVersion": MODULE_COMPILER_VERSION,
            "graphSpecVersion": MODULE_GRAPH_SPEC_VERSION,
            "languageVersion": MODULE_LANGUAGE_VERSION,
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
            "modules": [item.to_dict() for item in self.modules],  # dependency-first
            "resolvedModuleSet": self.resolved_module_set,
            "resolvedModuleSetDigest": self.resolved_module_set_digest,
            "handoffDigest": self.handoff_digest,
            "graphSpec": json.loads(self.graph_spec_json),
            "graphSpecDigest": self.graph_spec_digest,
            "expansionMap": json.loads(self.graph_spec_json)["expansionMap"],
            "expansionMapDigest": self.expansion_map_digest,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "compileDigest": self.compile_digest,
            "readyForSemanticResolution": True,
            "readyForDocumentLowering": False,
            "readyForApply": False,
        }

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            encoded = json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        else:
            encoded = _canonical_json(self.to_dict())
        if len(encoded.encode("utf-8")) > MAX_MODULE_COMPILE_RESULT_BYTES:
            raise ModuleProjectCompileError("HOCUS464", "Module compile result exceeds its byte limit.")
        return encoded


def compile_project_module_graph(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleProjectCompileResult:
    """Compile one explicit native v3 project entry through sealed pure expansion.

    This function performs no discovery, writes, catalog resolution, bundle creation,
    Houdini access, or live/MCP registration.
    """

    dag = resolve_project_module_dag(
        project_directory, entry_source_path, limits=limits, cancelled=cancelled,
    )
    return _compile_resolved_module_dag(dag, limits=limits, cancelled=cancelled)


def compile_project_mixed_module_graph(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleProjectCompileResult:
    """Compile an entry against its exact G3-published mixed-root lock closure."""

    result, recheck = _compile_project_mixed_module_graph_session(
        project_directory,
        entry_source_path,
        module_roots,
        limits=limits,
        cancelled=cancelled,
    )
    recheck()
    return result


def _compile_project_mixed_module_graph_session(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    module_roots: Mapping[str, str | PathLike[str]],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ModuleProjectCompileResult, Callable[[], None]]:
    session = _resolve_project_mixed_module_session(
        project_directory,
        entry_source_path,
        module_roots,
        limits=limits,
        cancelled=cancelled,
    )
    result = _compile_resolved_module_dag(
        session.dag, limits=limits, cancelled=cancelled,
    )
    session.recheck()
    return result, session.recheck


def _compile_resolved_module_dag(
    dag: ResolvedModuleDag,
    *,
    limits: ResolvedModuleLimits | None,
    cancelled: Callable[[], bool] | None,
) -> ModuleProjectCompileResult:
    selected_limits = limits or ResolvedModuleLimits()
    expansion_limits = ExpansionLimits.from_resolved(selected_limits)
    graph_spec = expand_resolved_module_dag(
        dag, limits=expansion_limits, cancellation=cancelled,
    )
    _checkpoint(cancelled)
    formatted_entry = format_syntax(dag.entry_syntax)
    formatted_modules: list[FormattedModuleSource] = []
    units = _resolved_units(dag)
    for record in dag.ordered_modules:
        _checkpoint(cancelled)
        syntax = units[record.dependency.uri].syntax
        formatted = format_syntax(syntax)
        formatted_modules.append(FormattedModuleSource(
            record.dependency.uri,
            record.dependency.source_digest,
            record.dependency.interface_digest,
            record.dependency.transitive_digest,
            formatted,
            _digest_text(formatted),
        ))
    graph_dict = graph_spec.to_dict()
    expansion_dict = graph_spec.expansion_map.to_dict()
    resolved_set_digest = _digest_text(dag.resolved_module_set_json)
    graph_digest = _digest_json(graph_dict)
    expansion_digest = _digest_json(expansion_dict)
    if dag.catalog_content_digest is None or dag.catalog_fingerprint is None:
        raise ModuleProjectCompileError("HOCUS460", "Native module compilation requires sealed catalog pins.")
    core = {
        "domain": "hocus-module-compile-result-v1",
        "compilerVersion": MODULE_COMPILER_VERSION,
        "projectUid": dag.resolved_module_set["projectUid"],
        "projectManifestDigest": dag.resolved_module_set["projectManifestDigest"],
        "projectLockDigest": dag.resolved_module_set["projectLockDigest"],
        "catalogContentDigest": dag.catalog_content_digest,
        "catalogFingerprint": dag.catalog_fingerprint,
        "resolverPolicyDigest": dag.resolved_module_set["resolverPolicyDigest"],
        "entrySourceUri": dag.entry_source_uri,
        "entrySourceDigest": dag.entry_source_digest,
        "formattedEntrySourceDigest": _digest_text(formatted_entry),
        "modules": [item.to_dict() for item in formatted_modules],
        "resolvedModuleSetDigest": resolved_set_digest,
        "handoffDigest": dag.handoff_digest,
        "graphSpecDigest": graph_digest,
        "expansionMapDigest": expansion_digest,
    }
    result = ModuleProjectCompileResult(
        dag.resolved_module_set["projectUid"],
        dag.resolved_module_set["projectManifestDigest"],
        dag.resolved_module_set["projectLockDigest"],
        dag.catalog_content_digest,
        dag.catalog_fingerprint,
        dag.resolved_module_set["resolverPolicyDigest"],
        dag.entry_source_uri,
        dag.entry_source_digest, formatted_entry, _digest_text(formatted_entry),
        tuple(formatted_modules), dag.resolved_module_set_json, resolved_set_digest,
        dag.handoff_digest, _canonical_json(graph_dict), graph_digest, expansion_digest, (),
        _digest_json(core),
    )
    result.to_json()
    return result


def _resolved_units(dag):
    from .expander import resolved_units_from_dag
    return resolved_units_from_dag(dag)


def _checkpoint(callback: Callable[[], bool] | None) -> None:
    if callback is None:
        return
    try:
        value = callback()
    except Exception as exc:
        raise ModuleProjectCompileError("HOCUS499", "Cancellation callback failed.") from exc
    if type(value) is not bool:
        raise ModuleProjectCompileError("HOCUS499", "Cancellation callback must return a boolean.")
    if value:
        raise ModuleProjectCompileError("HOCUS499", "Module project compilation was cancelled.")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False,
    )


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_json(value: Any) -> str:
    return _digest_text(_canonical_json(value))
