"""Pure content-only validation for already-resolved HocusScript module DAGs."""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
from dataclasses import dataclass
from itertools import islice
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote, unquote_to_bytes

from .diagnostics import HocusSourceError, SourceSpan
from .model import MODULE_LANGUAGE_VERSION, ModuleDependency
from .module_paths import is_literal_import_specifier, is_relative_hocus_path
from .parser import parse_syntax
from .modules import MAX_MODULE_ENTRIES
from .project import (
    LockVerificationResult,
    MAX_EXTERNAL_ALIASES,
    MAX_PROJECT_DIRECTORIES,
    ModuleLockRecord,
    ProjectError,
    SEMANTIC_VERSION_PATTERN,
    _portable_path_key,
    _validate_relative_artifact_path,
)
from .syntax import LiteralExpr, SyntaxSource


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UID = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_ALIAS = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_MODULE_URI = re.compile(r"^hocus-(project|module)://([a-z0-9][a-z0-9.-]{0,127})/(.+)$")
_TRANSITIVE_DOMAIN = "hocus-module-transitive-v1"
_MAX_INTERFACE_BYTES = 256 * 1024
_MAX_INTERFACE_VALUES = 50_000
_MAX_INTERFACE_DEPTH = 64


class ModuleResolutionError(ValueError):
    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ResolvedImport:
    specifier: str
    imported_name: str
    local_name: str
    target_uri: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ModuleSourceEnvelope:
    uri: str
    source: bytes
    imports: tuple[ResolvedImport, ...]


@dataclass(frozen=True, slots=True)
class ResolvedModuleLimits:
    source_bytes_per_file: int = 1_048_576
    aggregate_source_bytes: int = 8_388_608
    module_files: int = 4096
    import_depth: int = 64
    instance_depth: int = 64
    instances: int = 4096
    parameters_per_module: int = 256
    exports_per_module: int = 256
    expanded_nodes: int = 10_000
    aggregate_code_bytes: int = 4_194_304
    source_map_entries: int = 100_000
    diagnostics: int = 500

    def to_dict(self) -> dict[str, int]:
        return {
            "sourceBytesPerFile": self.source_bytes_per_file,
            "aggregateSourceBytes": self.aggregate_source_bytes,
            "moduleFiles": self.module_files,
            "importDepth": self.import_depth,
            "instanceDepth": self.instance_depth,
            "instances": self.instances,
            "parametersPerModule": self.parameters_per_module,
            "exportsPerModule": self.exports_per_module,
            "expandedNodes": self.expanded_nodes,
            "aggregateCodeBytes": self.aggregate_code_bytes,
            "sourceMapEntries": self.source_map_entries,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True, slots=True)
class ResolvedModuleRecord:
    dependency: ModuleDependency
    source: bytes
    interface_json: str
    imports: tuple[ResolvedImport, ...]

    @property
    def interface(self) -> dict[str, Any]:
        return json.loads(self.interface_json)


@dataclass(frozen=True, slots=True)
class ResolvedModuleDag:
    ordered_modules: tuple[ResolvedModuleRecord, ...]
    resolved_module_set_json: str
    entry_source_uri: str
    entry_source: bytes
    entry_source_digest: str
    entry_syntax: SyntaxSource
    entry_imports: tuple[ResolvedImport, ...]
    catalog_content_digest: str | None
    catalog_fingerprint: str | None
    handoff_digest: str

    @property
    def ordered_uris(self) -> tuple[str, ...]:
        return tuple(item.dependency.uri for item in self.ordered_modules)

    @property
    def records_by_uri(self) -> dict[str, dict[str, Any]]:
        return {item.dependency.uri: item.dependency.to_dict() for item in self.ordered_modules}

    @property
    def sources_by_uri(self) -> dict[str, bytes]:
        return {item.dependency.uri: item.source for item in self.ordered_modules}

    @property
    def interfaces_by_uri(self) -> dict[str, dict[str, Any]]:
        return {item.dependency.uri: item.interface for item in self.ordered_modules}

    @property
    def imports_by_uri(self) -> dict[str, tuple[ResolvedImport, ...]]:
        return {item.dependency.uri: item.imports for item in self.ordered_modules}

    @property
    def resolved_module_set(self) -> dict[str, Any]:
        return json.loads(self.resolved_module_set_json)


def validate_resolved_module_dag(
    modules: Iterable[ModuleSourceEnvelope],
    *,
    lock_verification: LockVerificationResult,
    entry_source_uri: str,
    entry_source: bytes,
    entry_imports: Iterable[ResolvedImport],
    resolver_policy: Mapping[str, Any],
    resolver_policy_digest: str,
    catalog_content_digest: str | None = None,
    catalog_fingerprint: str | None = None,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ResolvedModuleDag:
    """Validate caller-resolved module content and emit the portable v1 module set.

    Source parsing is pure and content-only. This function never reads paths,
    discovers projects, writes locks, resolves catalogs, or imports Houdini.
    """

    return _validate_resolved_module_dag_common(
        modules,
        lock_verification=lock_verification,
        entry_source_uri=entry_source_uri,
        entry_source=entry_source,
        entry_imports=entry_imports,
        resolver_policy=resolver_policy,
        resolver_policy_digest=resolver_policy_digest,
        catalog_content_digest=catalog_content_digest,
        catalog_fingerprint=catalog_fingerprint,
        limits=limits,
        cancelled=cancelled,
        mixed=False,
    )


def _validate_resolved_mixed_module_dag(
    modules: Iterable[ModuleSourceEnvelope],
    *,
    lock_verification: LockVerificationResult,
    entry_source_uri: str,
    entry_source: bytes,
    entry_imports: Iterable[ResolvedImport],
    resolver_policy: Mapping[str, Any],
    resolver_policy_digest: str,
    catalog_content_digest: str | None = None,
    catalog_fingerprint: str | None = None,
    limits: ResolvedModuleLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ResolvedModuleDag:
    """Validate a privately resolved exact mixed-root DAG without path access."""

    return _validate_resolved_module_dag_common(
        modules,
        lock_verification=lock_verification,
        entry_source_uri=entry_source_uri,
        entry_source=entry_source,
        entry_imports=entry_imports,
        resolver_policy=resolver_policy,
        resolver_policy_digest=resolver_policy_digest,
        catalog_content_digest=catalog_content_digest,
        catalog_fingerprint=catalog_fingerprint,
        limits=limits,
        cancelled=cancelled,
        mixed=True,
    )


def _validate_resolved_module_dag_common(
    modules: Iterable[ModuleSourceEnvelope],
    *,
    lock_verification: LockVerificationResult,
    entry_source_uri: str,
    entry_source: bytes,
    entry_imports: Iterable[ResolvedImport],
    resolver_policy: Mapping[str, Any],
    resolver_policy_digest: str,
    catalog_content_digest: str | None,
    catalog_fingerprint: str | None,
    limits: ResolvedModuleLimits | None,
    cancelled: Callable[[], bool] | None,
    mixed: bool,
) -> ResolvedModuleDag:

    selected_limits = limits or ResolvedModuleLimits()
    _validate_limits(selected_limits)
    _checkpoint(cancelled)
    if not isinstance(lock_verification, LockVerificationResult):
        _fail("HOCUS460", "lock_verification must be a verified LockVerificationResult.")
    project_uid = lock_verification.project_uid
    if not isinstance(project_uid, str) or _UID.fullmatch(project_uid) is None:
        _fail("HOCUS460", "Verified lock project_uid is invalid.")
    entry_identity = canonical_module_uri(entry_source_uri)
    if entry_identity is None or entry_identity[:2] != ("project", project_uid):
        _fail("HOCUS460", "entry_source_uri must be a canonical URI for project_uid.")
    project_manifest_digest = _require_digest(lock_verification.manifest_digest, "manifest_digest")
    project_lock_digest = _require_digest(lock_verification.lock_digest, "lock_digest")
    policy_json = _canonical_json(resolver_policy, "resolver_policy")
    if len(policy_json.encode("utf-8")) > _MAX_INTERFACE_BYTES:
        _fail("HOCUS461", "resolver_policy exceeds the metadata byte limit.")
    expected_policy_digest = _digest(policy_json.encode("utf-8"))
    if resolver_policy_digest != expected_policy_digest:
        _fail("HOCUS461", "resolver_policy_digest does not match resolver_policy.")
    mixed_pins = _validate_mixed_policy(resolver_policy) if mixed else {}
    if (catalog_content_digest is None) != (catalog_fingerprint is None):
        _fail("HOCUS461", "Catalog content digest and fingerprint must be supplied together.")
    if catalog_content_digest is not None:
        _require_digest(catalog_content_digest, "catalog_content_digest")
        _require_digest(catalog_fingerprint, "catalog_fingerprint")

    entry_syntax = _parse_exact_source(entry_source, entry_source_uri, selected_limits, root="graph")
    aggregate_bytes = len(entry_source)
    if aggregate_bytes > selected_limits.aggregate_source_bytes:
        _fail("HOCUS464", "Entry source exceeds aggregateSourceBytes.")
    supplied_entry_imports = _take_bounded(
        entry_imports, selected_limits.module_files, "entry_imports", cancelled,
    )
    _validate_import_correspondence(entry_syntax, supplied_entry_imports, entry_source_uri)

    supplied = _take_bounded(modules, selected_limits.module_files, "modules", cancelled)
    lock_records = _validated_lock_records(lock_verification, selected_limits, cancelled)
    by_uri: dict[str, ResolvedModuleRecord] = {}
    portable_paths: set[tuple[str, str]] = {
        (f"project:{project_uid}", _portable_path_key(entry_identity[2]))
    }
    for index, envelope in enumerate(supplied):
        _checkpoint(cancelled)
        if not isinstance(envelope, ModuleSourceEnvelope):
            _fail("HOCUS460", "Each module must be a ModuleSourceEnvelope.", index=index)
        if envelope.uri == entry_source_uri:
            _fail("HOCUS462", "Entry source cannot also be supplied as a module.", uri=envelope.uri)
        lock_record = lock_records.get(envelope.uri)
        if lock_record is None:
            _fail("HOCUS462", "Supplied module is absent from the verified lock.", uri=envelope.uri)
        if lock_record.external_alias is not None and not mixed:
            _fail("HOCUS460", "External module aliases remain disabled in Batch B.", uri=envelope.uri)
        record = _validate_module(
            envelope,
            lock_record,
            project_uid,
            selected_limits,
            cancelled,
            mixed=mixed,
            mixed_pins=mixed_pins,
        )
        uri = record.dependency.uri
        path_key = (
            f"{record.dependency.origin}:{record.dependency.owner_uid}",
            _portable_path_key(record.dependency.relative_path),
        )
        if uri in by_uri or path_key in portable_paths:
            _fail("HOCUS462", "Module URIs and paths must be portably unique.", uri=uri)
        by_uri[uri] = record
        portable_paths.add(path_key)
        aggregate_bytes += len(record.source)
        if aggregate_bytes > selected_limits.aggregate_source_bytes:
            _fail("HOCUS464", "Aggregate module source exceeds aggregateSourceBytes.")

    for uri in sorted(by_uri):
        _checkpoint(cancelled)
        record = by_uri[uri]
        dependency_targets = record.dependency.dependencies
        import_targets = tuple(sorted(item.target_uri for item in record.imports))
        if import_targets != dependency_targets:
            _fail("HOCUS462", "Literal imports do not exactly match locked dependency URIs.", uri=uri)
        local_names: set[str] = set()
        specifiers: set[str] = set()
        if len(record.imports) > selected_limits.module_files:
            _fail("HOCUS464", "Module imports exceed moduleFiles.", uri=uri)
        for item in record.imports:
            _checkpoint(cancelled)
            if item.target_uri not in by_uri:
                _fail("HOCUS462", "Literal import targets an unresolved module.", uri=uri, target=item.target_uri)
            target = by_uri[item.target_uri].dependency
            if item.imported_name != target.module_name:
                _fail("HOCUS462", "Imported module name conflicts with the target interface.", uri=uri)
            if item.local_name in local_names or item.specifier in specifiers:
                _fail("HOCUS462", "Literal import names and specifiers must be unique within a module.", uri=uri)
            local_names.add(item.local_name)
            specifiers.add(item.specifier)
            if item.specifier.startswith("@") and not mixed:
                _fail("HOCUS460", "External module aliases remain disabled in Batch B.", uri=uri)
            if mixed:
                _validate_mixed_import_edge(record.dependency, item, target, mixed_pins)

    entry_targets = _validate_entry_imports(
        supplied_entry_imports,
        by_uri,
        cancelled,
        mixed=mixed,
        mixed_pins=mixed_pins,
    )
    reachable: set[str] = set()
    pending = list(reversed(sorted(entry_targets)))
    while pending:
        _checkpoint(cancelled)
        uri = pending.pop()
        if uri in reachable:
            continue
        record = by_uri.get(uri)
        if record is None:
            _fail("HOCUS462", "Entry-transitive module is missing.", target=uri)
        reachable.add(uri)
        pending.extend(reversed(record.dependency.dependencies))
    unreachable = sorted(set(by_uri) - reachable)
    if unreachable:
        _fail("HOCUS462", "Supplied modules must be reachable from entry imports.", uri=unreachable[0])

    ordered_uris = _validate_dag(by_uri, selected_limits.import_depth, cancelled)
    for uri in ordered_uris:
        _checkpoint(cancelled)
        dependency = by_uri[uri].dependency
        expected = _transitive_digest(dependency, by_uri)
        if dependency.transitive_digest != expected:
            _fail("HOCUS463", "Module transitive_digest is incompatible with its bottom-up closure.", uri=uri)

    ordered_records = tuple(by_uri[uri] for uri in ordered_uris)
    module_set = {
        "$schema": "hocuspocus://schemas/resolved-module-set/v1",
        "kind": "hocus_resolved_module_set",
        "schemaVersion": 1,
        "languageVersion": MODULE_LANGUAGE_VERSION,
        "projectUid": project_uid,
        "entrySourceUri": entry_source_uri,
        "projectManifestDigest": project_manifest_digest,
        "projectLockDigest": project_lock_digest,
        "resolverPolicyDigest": resolver_policy_digest,
        "limits": selected_limits.to_dict(),
        "modules": [by_uri[uri].dependency.to_dict() for uri in sorted(by_uri)],
    }
    entry_digest = module_source_digest(entry_source)
    module_set_json = _canonical_json(module_set, "resolved_module_set")
    return ResolvedModuleDag(
        ordered_records,
        module_set_json,
        entry_source_uri,
        entry_source,
        entry_digest,
        entry_syntax,
        supplied_entry_imports,
        catalog_content_digest,
        catalog_fingerprint,
        _resolved_dag_handoff_digest(
            entry_source_uri=entry_source_uri,
            entry_source_digest=entry_digest,
            entry_imports=supplied_entry_imports,
            ordered_modules=ordered_records,
            resolved_module_set_json=module_set_json,
            catalog_content_digest=catalog_content_digest,
            catalog_fingerprint=catalog_fingerprint,
        ),
    )


def module_source_digest(source: bytes) -> str:
    if type(source) is not bytes:
        raise TypeError("source must be exact bytes")
    return _digest(source)


def _resolved_dag_handoff_digest(
    *, entry_source_uri: str, entry_source_digest: str,
    entry_imports: tuple[ResolvedImport, ...],
    ordered_modules: tuple[ResolvedModuleRecord, ...],
    resolved_module_set_json: str,
    catalog_content_digest: str | None,
    catalog_fingerprint: str | None,
) -> str:
    """Seal every resolver-selected entry and nested import edge for expansion."""

    def encoded_import(item: ResolvedImport) -> dict[str, Any]:
        return {
            "specifier": item.specifier,
            "importedName": item.imported_name,
            "localName": item.local_name,
            "targetUri": item.target_uri,
            "span": item.span.to_dict(),
        }

    payload = {
        "domain": "hocus-resolved-dag-handoff-v1",
        "entrySourceUri": entry_source_uri,
        "entrySourceDigest": entry_source_digest,
        "entryImports": [encoded_import(item) for item in entry_imports],
        "resolvedModuleSet": json.loads(resolved_module_set_json),
        "resolvedModuleSetDigest": _digest(resolved_module_set_json.encode("utf-8")),
        "catalogPins": {
            "contentDigest": catalog_content_digest,
            "fingerprint": catalog_fingerprint,
        },
        "modules": [
            {
                "dependency": record.dependency.to_dict(),
                "imports": [encoded_import(item) for item in record.imports],
            }
            for record in ordered_modules
        ],
    }
    return _digest(_canonical_json(payload, "resolved_dag_handoff").encode("utf-8"))


def _take_bounded(
    values: Iterable[Any], maximum: int, label: str,
    cancelled: Callable[[], bool] | None,
) -> tuple[Any, ...]:
    output: list[Any] = []
    try:
        for item in islice(iter(values), maximum + 1):
            _checkpoint(cancelled)
            output.append(item)
    except ModuleResolutionError:
        raise
    except Exception as exc:
        raise ModuleResolutionError(
            "HOCUS460", f"{label} must be a bounded iterable.",
            details={"errorType": exc.__class__.__name__},
        ) from exc
    if len(output) > maximum:
        _fail("HOCUS464", f"{label} exceeds moduleFiles.")
    return tuple(output)


def module_interface_digest(interface: Mapping[str, Any]) -> str:
    return _digest(_canonical_json(interface, "interface").encode("utf-8"))


def module_transitive_digest(
    *, uri: str, source_digest: str, interface_digest: str,
    dependencies: Iterable[tuple[str, str]],
) -> str:
    payload = {
        "domain": _TRANSITIVE_DOMAIN,
        "uri": uri,
        "sourceDigest": source_digest,
        "interfaceDigest": interface_digest,
        "dependencies": [
            {"uri": dependency_uri, "transitiveDigest": digest}
            for dependency_uri, digest in dependencies
        ],
    }
    return _digest(_canonical_json(payload, "transitive_digest").encode("utf-8"))


def _validate_module(
    value: ModuleSourceEnvelope, locked: ModuleLockRecord, project_uid: str,
    limits: ResolvedModuleLimits,
    cancelled: Callable[[], bool] | None,
    *,
    mixed: bool,
    mixed_pins: Mapping[str, Mapping[str, Any]],
) -> ResolvedModuleRecord:
    if locked.module_uri != value.uri:
        _fail("HOCUS462", "Envelope URI does not match its verified lock record.", uri=value.uri)
    identity = canonical_module_uri(locked.module_uri)
    try:
        _validate_relative_artifact_path(locked.source_path, "locked module sourcePath", code="HOCUS460")
    except ProjectError:
        _fail("HOCUS460", "Verified module sourcePath is not portable.", uri=value.uri)
    if locked.external_alias is None:
        if (
            identity != ("project", project_uid, locked.source_path)
            or locked.project_uid != project_uid
            or locked.library_uid is not None
            or locked.library_version is not None
            or locked.module_manifest_digest is not None
            or locked.language_version != MODULE_LANGUAGE_VERSION
        ):
            _fail("HOCUS460", "Verified local module provenance is invalid.", uri=value.uri)
        origin = "project"
        owner_uid = project_uid
        alias = None
        version = None
        manifest_digest = None
    else:
        pin = mixed_pins.get(locked.external_alias) if mixed else None
        if (
            pin is None
            or not isinstance(locked.library_uid, str)
            or identity != ("module", locked.library_uid, locked.source_path)
            or locked.project_uid is not None
            or locked.library_uid != pin.get("libraryUid")
            or locked.library_version != pin.get("libraryVersion")
            or locked.module_manifest_digest != pin.get("moduleManifestDigest")
            or locked.language_version != MODULE_LANGUAGE_VERSION
        ):
            _fail("HOCUS460", "Verified external module provenance is invalid.", uri=value.uri)
        origin = "external_library"
        owner_uid = locked.library_uid
        alias = locked.external_alias
        version = locked.library_version
        manifest_digest = locked.module_manifest_digest
    syntax = _parse_exact_source(value.source, value.uri, limits, root="module")
    assert syntax.module is not None
    module_name = syntax.module.name
    if len(module_name) > 128 or _IDENTIFIER.fullmatch(module_name) is None:
        _fail("HOCUS460", "Module name must be a bounded identifier.", uri=value.uri)
    source_digest = module_source_digest(value.source)
    if source_digest != locked.content_digest:
        _fail("HOCUS461", "Exact source bytes do not match the verified lock.", uri=value.uri)
    interface = _module_interface(syntax, limits, value.uri)
    interface_json = _canonical_json(interface, "derived_interface")
    if len(interface_json.encode("utf-8")) > _MAX_INTERFACE_BYTES:
        _fail("HOCUS464", "Module interface exceeds its byte limit.", uri=value.uri)
    _validate_json_complexity(json.loads(interface_json))
    if _digest(interface_json.encode("utf-8")) != locked.interface_digest:
        _fail("HOCUS461", "Derived interface does not match the verified lock.", uri=value.uri)
    _require_digest(locked.transitive_digest, "transitive_digest")
    if (
        not isinstance(locked.dependencies, tuple)
        or len(locked.dependencies) > limits.module_files
        or locked.dependencies != tuple(sorted(set(locked.dependencies)))
        or any(not isinstance(item, str) or canonical_module_uri(item) is None for item in locked.dependencies)
        or value.uri in locked.dependencies
    ):
        _fail("HOCUS462", "Locked dependencies must be bounded sorted canonical URIs.", uri=value.uri)
    if not isinstance(value.imports, tuple):
        _fail("HOCUS460", "Module imports must be a tuple.", uri=value.uri)
    if len(value.imports) > limits.module_files:
        _fail("HOCUS464", "Module imports exceed moduleFiles.", uri=value.uri)
    _validate_import_correspondence(syntax, value.imports, value.uri)
    dependency = ModuleDependency(
        locked.module_uri, module_name, locked.source_path, origin, owner_uid,
        alias, version, manifest_digest, locked.content_digest, locked.interface_digest,
        locked.transitive_digest, locked.dependencies, locked.language_version,
    )
    return ResolvedModuleRecord(dependency, value.source, interface_json, value.imports)


def _parse_exact_source(
    source: bytes, uri: str, limits: ResolvedModuleLimits, *, root: str,
) -> SyntaxSource:
    if type(source) is not bytes:
        _fail("HOCUS461", "Source content must be exact bytes.", uri=uri)
    if len(source) > limits.source_bytes_per_file:
        _fail("HOCUS464", "Source exceeds sourceBytesPerFile.", uri=uri)
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        _fail("HOCUS461", "Source must be valid UTF-8.", uri=uri)
    try:
        syntax = parse_syntax(text, uri)
    except (HocusSourceError, TypeError, ValueError, RecursionError) as exc:
        code = exc.diagnostic.code if isinstance(exc, HocusSourceError) else "HOCUS466"
        raise ModuleResolutionError(
            "HOCUS466", "Source failed strict language 0.2 parsing.",
            details={"uri": uri, "sourceCode": code},
        ) from exc
    valid_root = syntax.graph is not None and syntax.module is None if root == "graph" else (
        syntax.module is not None and syntax.graph is None
    )
    if syntax.version is None or syntax.version.value != MODULE_LANGUAGE_VERSION or not valid_root:
        _fail("HOCUS466", f"Resolved source must contain one language 0.2 {root} root.", uri=uri)
    return syntax


def _validate_import_correspondence(
    syntax: SyntaxSource, imports: tuple[ResolvedImport, ...], uri: str,
) -> None:
    if len(imports) != len(syntax.imports):
        _fail("HOCUS462", "Resolved imports do not exactly match source declarations.", uri=uri)
    for declared, resolved in zip(syntax.imports, imports):
        if not isinstance(resolved, ResolvedImport) or not is_literal_import_specifier(resolved.specifier):
            _fail("HOCUS462", "Imports must be resolved literal .hocus declarations.", uri=uri)
        if (
            _IDENTIFIER.fullmatch(resolved.imported_name or "") is None
            or _IDENTIFIER.fullmatch(resolved.local_name or "") is None
            or canonical_module_uri(resolved.target_uri) is None
        ):
            _fail("HOCUS462", "Resolved import metadata is invalid.", uri=uri)
        _validate_import_span(resolved.span, uri, syntax.span.end.offset)
        if (
            declared.specifier != resolved.specifier
            or declared.imported_name != resolved.imported_name
            or declared.local_name != resolved.local_name
            or declared.span != resolved.span
        ):
            _fail("HOCUS462", "Resolved import metadata or span conflicts with exact source.", uri=uri)


def _validated_lock_records(
    verification: LockVerificationResult, limits: ResolvedModuleLimits,
    cancelled: Callable[[], bool] | None,
) -> dict[str, ModuleLockRecord]:
    if not isinstance(verification.modules, tuple) or len(verification.modules) > ResolvedModuleLimits().module_files:
        _fail("HOCUS460", "Verified lock modules must be a bounded tuple.")
    records: dict[str, ModuleLockRecord] = {}
    paths: set[tuple[str, str]] = set()
    for item in verification.modules:
        _checkpoint(cancelled)
        if not isinstance(item, ModuleLockRecord) or canonical_module_uri(item.module_uri) is None:
            _fail("HOCUS460", "Verified lock contains an invalid module record.")
        if item.module_uri in records:
            _fail("HOCUS462", "Verified lock contains duplicate module URIs.", uri=item.module_uri)
        try:
            _validate_relative_artifact_path(item.source_path, "locked module sourcePath", code="HOCUS460")
        except ProjectError:
            _fail("HOCUS460", "Verified lock contains a nonportable module path.", uri=item.module_uri)
        owner = item.project_uid or item.library_uid
        if not isinstance(owner, str):
            _fail("HOCUS460", "Verified lock module owner is invalid.", uri=item.module_uri)
        origin = "project" if item.project_uid is not None else "library"
        key = (f"{origin}:{owner}", _portable_path_key(item.source_path))
        if key in paths:
            _fail("HOCUS462", "Verified lock contains portable path aliases.", uri=item.module_uri)
        if not isinstance(item.dependencies, tuple) or len(item.dependencies) > ResolvedModuleLimits().module_files:
            _fail("HOCUS464", "Verified lock dependencies exceed moduleFiles.", uri=item.module_uri)
        paths.add(key)
        records[item.module_uri] = item
    return records


def _validate_mixed_policy(value: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    expected_keys = {
        "schemaVersion", "kind", "projectMode", "projectPolicy",
        "externalLibraries", "projectExternalResolution",
        "externalRelativeResolution", "externalCrossLibraryResolution",
        "externalBareResolution", "externalToProject", "casePolicy", "linkPolicy",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected_keys
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("kind") != "native_mixed_roots_v1"
        or value.get("projectMode") != "project_and_explicit_external_roots"
        or not _is_valid_project_policy(value.get("projectPolicy"))
        or value.get("projectExternalResolution") != "alias_entry_modules_only"
        or value.get("externalRelativeResolution") != "same_library_only"
        or value.get("externalCrossLibraryResolution") != "alias_entry_modules_only"
        or value.get("externalBareResolution") != "disabled"
        or value.get("externalToProject") is not False
        or value.get("casePolicy") != "portable"
        or value.get("linkPolicy") != "reject_reparse"
    ):
        _fail("HOCUS460", "Mixed resolver policy is invalid.")
    libraries = value.get("externalLibraries")
    if (
        not isinstance(libraries, list)
        or not libraries
        or len(libraries) > MAX_EXTERNAL_ALIASES
    ):
        _fail("HOCUS460", "Mixed resolver policy libraries are invalid.")
    pins: dict[str, Mapping[str, Any]] = {}
    library_uids: set[str] = set()
    for item in libraries:
        if not isinstance(item, Mapping) or set(item) != {
            "alias", "libraryUid", "libraryVersion", "moduleManifestDigest", "entryModules",
        }:
            _fail("HOCUS460", "Mixed resolver policy library pin is invalid.")
        alias = item.get("alias")
        library_uid = item.get("libraryUid")
        entries = item.get("entryModules")
        if (
            not isinstance(alias, str)
            or _ALIAS.fullmatch(alias) is None
            or alias in pins
            or not isinstance(library_uid, str)
            or _UID.fullmatch(library_uid) is None
            or library_uid in library_uids
            or not isinstance(item.get("libraryVersion"), str)
            or SEMANTIC_VERSION_PATTERN.fullmatch(item["libraryVersion"]) is None
            or not isinstance(item.get("moduleManifestDigest"), str)
            or _DIGEST.fullmatch(item["moduleManifestDigest"]) is None
            or not isinstance(entries, list)
            or not entries
            or len(entries) > MAX_MODULE_ENTRIES
            or entries != sorted(set(entries))
            or any(not isinstance(entry, str) or not is_relative_hocus_path(entry) for entry in entries)
        ):
            _fail("HOCUS460", "Mixed resolver policy library pin is invalid.")
        pins[alias] = item
        library_uids.add(library_uid)
    if tuple(pins) != tuple(sorted(pins)):
        _fail("HOCUS460", "Mixed resolver policy library pins must be alias-sorted.")
    return pins


def _is_valid_project_policy(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "schemaVersion", "kind", "projectMode", "relativeResolution",
        "moduleDirectories", "bareResolution", "externalAliases",
        "casePolicy", "linkPolicy",
    }:
        return False
    directories = value.get("moduleDirectories")
    if (
        type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("kind") != "native_project_v1"
        or value.get("projectMode") != "same_project_only"
        or value.get("relativeResolution") != "importer_relative_project_contained"
        or value.get("bareResolution") != "ordered_first_occupied_fail_closed"
        or value.get("externalAliases") is not False
        or value.get("casePolicy") != "portable"
        or value.get("linkPolicy") != "reject_reparse"
        or not isinstance(directories, list)
        or len(directories) > MAX_PROJECT_DIRECTORIES
    ):
        return False
    portable: set[str] = set()
    for directory in directories:
        if directory == ".":
            key = "."
        else:
            try:
                _validate_relative_artifact_path(
                    directory, "module directory", code="HOCUS460",
                )
            except ProjectError:
                return False
            key = _portable_path_key(directory)
        if key in portable:
            return False
        portable.add(key)
    return True


def _validate_mixed_import_edge(
    importer: ModuleDependency | None,
    resolved: ResolvedImport,
    target: ModuleDependency,
    pins: Mapping[str, Mapping[str, Any]],
) -> None:
    specifier = resolved.specifier
    alias: str | None = None
    if specifier.startswith("@"):
        alias, separator, tail = specifier[1:].partition("/")
        pin = pins.get(alias)
        if not separator or pin is None or tail not in pin["entryModules"]:
            _fail("HOCUS460", "Mixed alias imports must target approved manifest entries.")
        if target.origin != "external_library" or target.alias != alias:
            _fail("HOCUS462", "Mixed alias import target conflicts with its library pin.")
        if target.relative_path != tail:
            _fail("HOCUS462", "Mixed alias import path conflicts with its target.")
    importer_origin = "project" if importer is None else importer.origin
    if importer_origin == "project":
        if target.origin == "external_library" and alias is None:
            _fail("HOCUS460", "Project-to-library imports require an explicit alias entry.")
        if target.origin == "project" and alias is not None:
            _fail("HOCUS460", "Project alias imports cannot target project modules.")
        return
    if importer is None or importer.origin != "external_library":
        _fail("HOCUS460", "Mixed import owner provenance is invalid.")
    if target.origin == "project":
        _fail("HOCUS460", "External libraries cannot import project modules.")
    if target.origin != "external_library":
        _fail("HOCUS460", "External import target provenance is invalid.")
    if target.owner_uid == importer.owner_uid:
        if alias is not None or not specifier.startswith(("./", "../")):
            _fail("HOCUS460", "Same-library imports must use explicit relative paths.")
        relative = posixpath.normpath(
            posixpath.join(posixpath.dirname(importer.relative_path), specifier)
        )
        if not is_relative_hocus_path(relative) or relative != target.relative_path:
            _fail("HOCUS462", "Same-library relative import conflicts with its target.")
    elif alias is None or alias == importer.alias:
        _fail("HOCUS460", "Cross-library imports require a different explicit alias entry.")


def _validate_entry_imports(
    imports: tuple[ResolvedImport, ...], by_uri: Mapping[str, ResolvedModuleRecord],
    cancelled: Callable[[], bool] | None,
    *,
    mixed: bool,
    mixed_pins: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    targets: list[str] = []
    names: set[str] = set()
    specifiers: set[str] = set()
    for item in imports:
        _checkpoint(cancelled)
        if item.specifier.startswith("@") and not mixed:
            _fail("HOCUS460", "External module aliases remain disabled in Batch B.")
        target = by_uri.get(item.target_uri)
        if target is None:
            _fail("HOCUS462", "Entry import targets a missing supplied module.", target=item.target_uri)
        if item.imported_name != target.dependency.module_name:
            _fail("HOCUS462", "Entry imported name conflicts with target module.", target=item.target_uri)
        if mixed:
            _validate_mixed_import_edge(None, item, target.dependency, mixed_pins)
        if item.local_name in names or item.specifier in specifiers:
            _fail("HOCUS462", "Entry import aliases and specifiers must be unique.")
        names.add(item.local_name)
        specifiers.add(item.specifier)
        targets.append(item.target_uri)
    return tuple(targets)


def _validate_dag(
    by_uri: Mapping[str, ResolvedModuleRecord], max_depth: int,
    cancelled: Callable[[], bool] | None,
) -> tuple[str, ...]:
    remaining = {uri: len(record.dependency.dependencies) for uri, record in by_uri.items()}
    parents: dict[str, list[str]] = {uri: [] for uri in by_uri}
    for uri, record in by_uri.items():
        for child in record.dependency.dependencies:
            if child not in by_uri:
                _fail("HOCUS462", "Module dependency is unresolved.", uri=uri, target=child)
            parents[child].append(uri)
    ready = sorted(uri for uri, count in remaining.items() if count == 0)
    ordered: list[str] = []
    depths: dict[str, int] = {}
    while ready:
        _checkpoint(cancelled)
        uri = ready.pop(0)
        record = by_uri[uri]
        depth = 1 + max((depths[item] for item in record.dependency.dependencies), default=0)
        if depth > max_depth:
            _fail("HOCUS464", "Module DAG exceeds importDepth.", uri=uri)
        depths[uri] = depth
        ordered.append(uri)
        for parent in sorted(parents[uri]):
            remaining[parent] -= 1
            if remaining[parent] == 0:
                ready.append(parent)
        ready.sort()
    if len(ordered) != len(by_uri):
        _fail("HOCUS463", "Module dependency graph contains a cycle.")
    return tuple(ordered)


def _transitive_digest(
    dependency: ModuleDependency, by_uri: Mapping[str, ResolvedModuleRecord],
) -> str:
    return module_transitive_digest(
        uri=dependency.uri,
        source_digest=dependency.source_digest,
        interface_digest=dependency.interface_digest,
        dependencies=(
            (uri, by_uri[uri].dependency.transitive_digest)
            for uri in dependency.dependencies
        ),
    )


def _validate_limits(value: ResolvedModuleLimits) -> None:
    maxima = ResolvedModuleLimits()
    if not isinstance(value, ResolvedModuleLimits):
        _fail("HOCUS460", "limits must be ResolvedModuleLimits.")
    for key, maximum in maxima.to_dict().items():
        actual = value.to_dict()[key]
        if type(actual) is not int or not 1 <= actual <= maximum:
            _fail("HOCUS464", "Resolved module limit is outside the v1 contract.", limit=key)


def _validate_json_complexity(value: Any) -> None:
    pending = [(value, 1)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > _MAX_INTERFACE_VALUES or depth > _MAX_INTERFACE_DEPTH:
            _fail("HOCUS464", "Module interface exceeds structural limits.")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def _validate_import_span(value: Any, source_uri: str, source_length: int) -> None:
    if not isinstance(value, SourceSpan) or value.source_name != source_uri:
        _fail("HOCUS462", "Import span must identify its importing module source.", uri=source_uri)
    start, end = value.start, value.end
    if (
        type(start.offset) is not int or type(end.offset) is not int
        or not 0 <= start.offset <= end.offset <= source_length
        or type(start.line) is not int or type(end.line) is not int
        or type(start.column) is not int or type(end.column) is not int
        or min(start.line, end.line, start.column, end.column) < 1
    ):
        _fail("HOCUS462", "Import span is outside its exact source content.", uri=source_uri)


def canonical_module_uri(value: Any) -> tuple[str, str, str] | None:
    """Parse a canonical portable project/module URI without touching the filesystem."""
    match = _MODULE_URI.fullmatch(value) if isinstance(value, str) else None
    if match is None or "?" in value or "#" in value or "\\" in value:
        return None
    scheme, authority, encoded_path = match.groups()
    try:
        decoded_path = unquote_to_bytes(encoded_path).decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not is_relative_hocus_path(decoded_path):
        return None
    if encoded_path != quote(decoded_path, safe="/-._~"):
        return None
    return scheme, authority, decoded_path


def _module_interface(
    syntax: SyntaxSource, limits: ResolvedModuleLimits, uri: str,
) -> dict[str, Any]:
    module = syntax.module
    assert module is not None
    if len(module.parameters) > limits.parameters_per_module:
        _fail("HOCUS464", "Module parameters exceed parametersPerModule.", uri=uri)
    if len(module.exports) > limits.exports_per_module:
        _fail("HOCUS464", "Module exports exceed exportsPerModule.", uri=uri)
    supported = {"bool", "int", "float", "string", "node_output"}
    parameter_names: set[str] = set()
    parameters: list[dict[str, Any]] = []
    for parameter in module.parameters:
        if parameter.name in parameter_names or parameter.type_name not in supported:
            _fail("HOCUS466", "Module parameter interface is invalid.", uri=uri)
        parameter_names.add(parameter.name)
        has_default = parameter.default is not None
        default: Any = None
        if has_default:
            if not isinstance(parameter.default, LiteralExpr):
                _fail("HOCUS466", "Module parameter defaults must be literals.", uri=uri)
            default = parameter.default.value
            if not _literal_matches_type(default, parameter.type_name):
                _fail("HOCUS466", "Module parameter default does not match its exact type.", uri=uri)
        parameters.append({
            "name": parameter.name,
            "type": parameter.type_name,
            "hasDefault": has_default,
            "default": default,
        })
    export_names: set[str] = set()
    exports: list[dict[str, str]] = []
    for exported in module.exports:
        if exported.name in export_names or exported.type_name not in supported:
            _fail("HOCUS466", "Module export interface is invalid.", uri=uri)
        export_names.add(exported.name)
        exports.append({"name": exported.name, "type": exported.type_name})
    return {
        "schemaVersion": 1,
        "moduleName": module.name,
        "parameters": parameters,
        "exports": exports,
    }


def _literal_matches_type(value: Any, type_name: str) -> bool:
    if type_name == "bool":
        return type(value) is bool
    if type_name == "int":
        return type(value) is int
    if type_name == "float":
        return type(value) is float and math.isfinite(value)
    if type_name == "string":
        return isinstance(value, str)
    return False


def _canonical_json(value: Any, label: str) -> str:
    if not isinstance(value, Mapping):
        _fail("HOCUS461", f"{label} must be a JSON object.")
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        _fail("HOCUS461", f"{label} is not canonical JSON: {exc}")


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _fail("HOCUS461", f"{label} must be a lowercase SHA-256 digest.")
    return value


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _checkpoint(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None:
        try:
            is_cancelled = cancelled()
        except Exception as exc:
            raise ModuleResolutionError(
                "HOCUS465", "Cancellation callback failed.",
                details={"errorType": exc.__class__.__name__},
            ) from exc
        if type(is_cancelled) is not bool:
            _fail("HOCUS465", "Cancellation callback must return bool.")
        if is_cancelled:
            _fail("HOCUS465", "Module DAG validation was cancelled.")


def _fail(code: str, message: str, **details: Any) -> None:
    raise ModuleResolutionError(code, message, details=details)
