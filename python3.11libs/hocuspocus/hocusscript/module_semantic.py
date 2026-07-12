"""Pinned native semantic resolution for sealed HocusScript 0.2 module graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from os import PathLike
from typing import TYPE_CHECKING, Any, Callable, Mapping

from .model import MODULE_GRAPH_SPEC_VERSION, MODULE_LANGUAGE_VERSION, ExpansionOrigin, graph_spec_from_dict
from .module_compiler import (
    MAX_MODULE_COMPILE_RESULT_BYTES,
    ModuleProjectCompileResult,
    compile_project_module_graph,
)
from .project import ProjectContext
from .resolved_modules import ResolvedModuleLimits
from .semantic import CatalogConstraint, SemanticResult, resolve_graph

if TYPE_CHECKING:
    from .bundle import CompiledBundle

# These sentinels detect accidental construction/replacement inside one Python
# process. They are invariant checks, not an authorization or security boundary.
_FACTORY_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _SemanticInvariant:
    compile_result: ModuleProjectCompileResult
    semantic_result: SemanticResult
    semantic_json: str
    semantic_digest: str


class ModuleSemanticCompileError(ValueError):
    """Typed failure at the native module semantic integration boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ModuleSemanticCompileResult:
    """Inspectable immutable result bound to its internally compiled inputs.

    The private fields guard ordinary construction and replacement mistakes only;
    they do not claim to protect against arbitrary code in the same process.
    """

    compile_result: ModuleProjectCompileResult
    semantic_result: SemanticResult
    semantic_json: str
    semantic_digest: str
    _construction_token: object = field(repr=False, compare=False)
    _invariant: _SemanticInvariant = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _FACTORY_TOKEN:
            raise ModuleSemanticCompileError(
                "HOCUS480", "Module semantic result factory invariant was not satisfied.",
            )
        if type(self.compile_result) is not ModuleProjectCompileResult or type(self.semantic_result) is not SemanticResult:
            raise ModuleSemanticCompileError("HOCUS480", "Module semantic result provenance is invalid.")
        if (
            self._invariant.compile_result is not self.compile_result
            or self._invariant.semantic_result is not self.semantic_result
            or self._invariant.semantic_json != self.semantic_json
            or self._invariant.semantic_digest != self.semantic_digest
        ):
            raise ModuleSemanticCompileError("HOCUS480", "Module semantic result invariant is inconsistent.")
        try:
            payload = json.loads(self.semantic_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ModuleSemanticCompileError("HOCUS480", "Module semantic JSON is invalid.") from exc
        if _canonical_json(payload) != self.semantic_json or _digest_text(self.semantic_json) != self.semantic_digest:
            raise ModuleSemanticCompileError("HOCUS480", "Module semantic JSON or digest is noncanonical.")
        graph = self.compile_result.graph_spec
        if graph.expansion_map is None:
            raise ModuleSemanticCompileError("HOCUS480", "Module semantic result lost expansion provenance.")
        expected = _canonical_json(
            _semantic_payload_with_origins(self.semantic_result, graph.expansion_map.mappings)
        )
        if self.semantic_json != expected:
            raise ModuleSemanticCompileError("HOCUS480", "Module semantic JSON conflicts with its retained result.")

    @property
    def semantic(self) -> dict[str, Any]:
        return json.loads(self.semantic_json)

    @property
    def valid(self) -> bool:
        return self.semantic_result.valid

    @property
    def ready_for_document_lowering(self) -> bool:
        return self.semantic_result.ready_for_document_lowering

    def to_dict(self) -> dict[str, Any]:
        compiled = self.compile_result
        return {
            "stage": "semantic",
            "valid": self.valid,
            "readyForBundle": self.valid,
            "readyForDocumentLowering": self.ready_for_document_lowering,
            "readyForApply": False,
            "projectUid": compiled.project_uid,
            "projectManifestDigest": compiled.project_manifest_digest,
            "projectLockDigest": compiled.project_lock_digest,
            "catalogContentDigest": compiled.catalog_content_digest,
            "catalogFingerprint": compiled.catalog_fingerprint,
            "entrySourceUri": compiled.entry_source_uri,
            "entrySourceDigest": compiled.entry_source_digest,
            "compileDigest": compiled.compile_digest,
            "graphSpecDigest": compiled.graph_spec_digest,
            "semantic": self.semantic,
            "semanticDigest": self.semantic_digest,
        }

    def to_json(self, *, pretty: bool = False) -> str:
        encoded = (
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if pretty else _canonical_json(self.to_dict())
        )
        if len(encoded.encode("utf-8")) > MAX_MODULE_COMPILE_RESULT_BYTES:
            raise ModuleSemanticCompileError("HOCUS464", "Module semantic result exceeds its byte limit.")
        return encoded


def compile_project_module_semantic(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ModuleSemanticCompileResult:
    """Compile and semantically resolve one explicitly selected native project entry.

    Catalog state, constraints, and operator selections are always derived inside
    this function. Callers cannot inject a snapshot, digest, binding, or selection.
    """

    _checkpoint(cancelled)
    compiled = compile_project_module_graph(
        project_directory, entry_source_path, limits=limits, cancelled=cancelled,
    )
    _checkpoint(cancelled)
    project = ProjectContext.load(project_directory, validate_lock=True)
    _checkpoint(cancelled)
    _require_exact_project_snapshot(compiled, project)

    try:
        graph_payload = json.loads(compiled.graph_spec_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ModuleSemanticCompileError("HOCUS481", "Trusted module GraphSpec JSON is invalid.") from exc
    if (
        not isinstance(graph_payload, dict)
        or graph_payload.get("graphSpecVersion") != MODULE_GRAPH_SPEC_VERSION
        or graph_payload.get("languageVersion") != MODULE_LANGUAGE_VERSION
    ):
        raise ModuleSemanticCompileError(
            "HOCUS481", "Module semantic resolution requires GraphSpec 0.3 and language 0.2.",
        )
    if _digest_text(compiled.graph_spec_json) != compiled.graph_spec_digest:
        raise ModuleSemanticCompileError("HOCUS481", "Trusted module GraphSpec digest is inconsistent.")
    expansion_payload = graph_payload.get("expansionMap")
    if _digest_json(expansion_payload) != compiled.expansion_map_digest:
        raise ModuleSemanticCompileError("HOCUS481", "Trusted module expansion-map digest is inconsistent.")
    try:
        graph = graph_spec_from_dict(graph_payload)
    except ValueError as exc:
        raise ModuleSemanticCompileError("HOCUS481", "Trusted module GraphSpec failed strict decoding.") from exc
    if graph.graph_spec_version != MODULE_GRAPH_SPEC_VERSION or graph.expansion_map is None:
        raise ModuleSemanticCompileError("HOCUS481", "Module semantic resolution requires GraphSpec 0.3.")

    assert project.catalog is not None
    semantic_result = resolve_graph(
        graph,
        project.catalog,
        constraint=CatalogConstraint(compiled.catalog_fingerprint),
    )
    _checkpoint(cancelled)
    semantic_payload = _semantic_payload_with_origins(semantic_result, graph.expansion_map.mappings)
    semantic_json = _canonical_json(semantic_payload)
    semantic_digest = _digest_text(semantic_json)
    invariant = _SemanticInvariant(compiled, semantic_result, semantic_json, semantic_digest)
    result = ModuleSemanticCompileResult(
        compiled,
        semantic_result,
        semantic_json,
        semantic_digest,
        _FACTORY_TOKEN,
        invariant,
    )
    result.to_json()
    return result


def compile_project_module_bundle(
    project_directory: str | PathLike[str],
    entry_source_path: str | PathLike[str],
    *,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> "CompiledBundle":
    """Compile one project entry directly into a pinned semantic bundle.

    This one-shot public boundary deliberately exposes no catalog snapshot,
    semantic selection, digest, or intermediate-result input.
    """

    semantic = compile_project_module_semantic(
        project_directory,
        entry_source_path,
        limits=limits,
        cancelled=cancelled,
    )
    _checkpoint(cancelled)
    if not semantic.valid:
        errors = tuple(
            item for item in semantic.semantic_result.diagnostics
            if item.severity == "error"
        )
        raise ModuleSemanticCompileError(
            "HOCUS482",
            "Module semantic resolution is invalid; bundle creation is blocked.",
            details={
                "diagnosticCount": len(semantic.semantic_result.diagnostics),
                "errorCount": len(errors),
                "errorCodes": sorted({item.code for item in errors}),
            },
        )
    from .bundle import _bundle_from_module_semantic
    bundle = _bundle_from_module_semantic(semantic)
    _checkpoint(cancelled)
    return bundle


def _require_exact_project_snapshot(
    compiled: ModuleProjectCompileResult,
    project: ProjectContext,
) -> None:
    actual = (
        project.uid,
        project.manifest_digest,
        project.lock_digest,
        project.catalog_content_digest,
        project.catalog_fingerprint,
    )
    expected = (
        compiled.project_uid,
        compiled.project_manifest_digest,
        compiled.project_lock_digest,
        compiled.catalog_content_digest,
        compiled.catalog_fingerprint,
    )
    if project.manifest_version != 3 or project.language_version != MODULE_LANGUAGE_VERSION:
        raise ModuleSemanticCompileError("HOCUS480", "Module semantic resolution requires a v3 language 0.2 project.")
    if project.catalog is None or any(value is None for value in actual) or actual != expected:
        raise ModuleSemanticCompileError(
            "HOCUS480", "Project, lock, or catalog pins changed after module compilation.",
        )


def _semantic_payload_with_origins(
    semantic_result: SemanticResult,
    mappings: tuple[ExpansionOrigin, ...],
) -> dict[str, Any]:
    payload = semantic_result.to_dict()
    diagnostics = payload.get("diagnostics", [])
    for diagnostic in diagnostics:
        pointer = diagnostic.get("jsonPointer") if isinstance(diagnostic, dict) else None
        origin = _longest_origin(pointer, mappings)
        diagnostic["originId"] = origin.origin_id if origin is not None else None
        diagnostic["stackId"] = origin.stack_id if origin is not None else None
    return payload


def _longest_origin(
    pointer: Any,
    mappings: tuple[ExpansionOrigin, ...],
) -> ExpansionOrigin | None:
    if not isinstance(pointer, str):
        return None
    candidates = [
        item for item in mappings
        if pointer == item.generated_pointer
        or item.generated_pointer == ""
        or pointer.startswith(item.generated_pointer + "/")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item.generated_pointer))


def _checkpoint(callback: Callable[[], bool] | None) -> None:
    if callback is None:
        return
    try:
        value = callback()
    except Exception as exc:
        raise ModuleSemanticCompileError("HOCUS499", "Cancellation callback failed.") from exc
    if type(value) is not bool:
        raise ModuleSemanticCompileError("HOCUS499", "Cancellation callback must return a boolean.")
    if value:
        raise ModuleSemanticCompileError("HOCUS499", "Module semantic compilation was cancelled.")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False,
    )


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_json(value: Any) -> str:
    return _digest_text(_canonical_json(value))
