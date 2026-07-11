"""Deterministic structural bundles for the offline-to-Houdini boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .compiler import SUPPORTED_LANGUAGE_VERSIONS
from .model import COMPILER_VERSION, GRAPH_SPEC_VERSION, CompileResult

BUNDLE_VERSION = "0.1"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_DEPTH = 128
MAX_BUNDLE_VALUES = 250_000
MAX_DEPENDENCIES = 4096
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT_UID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_BUNDLE_KEYS = {
    "$schema",
    "kind",
    "bundleVersion",
    "bundleDigest",
    "compilerVersion",
    "graphSpecVersion",
    "languageVersion",
    "portable",
    "projectUid",
    "projectManifestDigest",
    "projectLockDigest",
    "entrySource",
    "dependencies",
    "catalogConstraints",
    "requiredCapabilities",
    "sourceMaps",
    "graphSpec",
}
_GRAPH_KEYS = {
    "$schema", "kind", "graphSpecVersion", "languageVersion", "name", "target", "category", "mode",
    "expectedRevision", "ownership", "externalNodes", "nodes", "display", "render", "output", "layout", "span",
}


class BundleValidationError(ValueError):
    """Typed rejection of an external compiled bundle."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class CompiledBundle:
    _payload_json: str
    digest: str

    @classmethod
    def from_result(cls, result: CompileResult) -> "CompiledBundle":
        if not result.valid or result.graph_spec is None:
            raise ValueError("A compiled bundle requires a valid GraphSpec result.")
        if (result.project_uid is None) != (result.project_manifest_digest is None):
            raise ValueError("Portable project UID and manifest digest must be present together.")
        graph_spec = result.graph_spec.to_dict()
        entry_uri = result.source_uri or result.source_name
        payload: dict[str, Any] = {
            "$schema": "hocuspocus://schemas/compiled-bundle/v0.1",
            "kind": "hocus_compiled_bundle",
            "bundleVersion": BUNDLE_VERSION,
            "compilerVersion": COMPILER_VERSION,
            "graphSpecVersion": GRAPH_SPEC_VERSION,
            "languageVersion": result.language_version,
            "portable": result.project_uid is not None and result.project_manifest_digest is not None,
            "projectUid": result.project_uid,
            "projectManifestDigest": result.project_manifest_digest,
            "projectLockDigest": result.project_lock_digest,
            "entrySource": {
                "uri": entry_uri,
                "digest": result.source_digest,
                "kind": result.source_kind,
            },
            "dependencies": [],
            "catalogConstraints": {},
            "requiredCapabilities": _required_capabilities(graph_spec),
            "sourceMaps": {
                "format": "graph-spec-spans-v0.1",
                "entrySourceUri": entry_uri,
                "embeddedInGraphSpec": True,
            },
            "graphSpec": graph_spec,
        }
        canonical = _canonical_json(payload)
        digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        return cls(canonical, digest)

    @property
    def payload(self) -> dict[str, Any]:
        """Return a detached payload so callers cannot invalidate the digest."""

        return json.loads(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {**json.loads(self._payload_json), "bundleDigest": self.digest}

    def to_json(self, *, pretty: bool = False) -> str:
        if pretty:
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return _canonical_json(self.to_dict())


def decode_compiled_bundle(value: Any) -> CompiledBundle:
    """Validate untrusted bundle content without reading source files or Houdini state."""

    if not isinstance(value, dict):
        raise BundleValidationError("HOCUS500", "Compiled bundle must be a JSON object.")
    _validate_complexity(value)
    keys = set(value)
    if keys != _BUNDLE_KEYS:
        raise BundleValidationError(
            "HOCUS501",
            "Compiled bundle has missing or unknown top-level fields.",
            details={"missing": sorted(_BUNDLE_KEYS - keys), "unknown": sorted(keys - _BUNDLE_KEYS)},
        )
    declared_digest = _require_digest(value.get("bundleDigest"), "bundleDigest", "HOCUS502")
    payload = dict(value)
    del payload["bundleDigest"]
    try:
        canonical = _canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise BundleValidationError("HOCUS503", f"Compiled bundle is not canonicalizable JSON: {exc}") from exc
    if len(canonical.encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise BundleValidationError("HOCUS504", f"Compiled bundle exceeds the {MAX_BUNDLE_BYTES}-byte limit.")
    actual_digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    if not hmac.compare_digest(declared_digest, actual_digest):
        raise BundleValidationError(
            "HOCUS505",
            "Compiled bundle digest does not match its canonical content.",
            details={"declaredDigest": declared_digest, "actualDigest": actual_digest},
        )

    _require_equal(payload, "$schema", "hocuspocus://schemas/compiled-bundle/v0.1", "HOCUS506")
    _require_equal(payload, "kind", "hocus_compiled_bundle", "HOCUS506")
    _require_equal(payload, "bundleVersion", BUNDLE_VERSION, "HOCUS507")
    _require_equal(payload, "compilerVersion", COMPILER_VERSION, "HOCUS507")
    _require_equal(payload, "graphSpecVersion", GRAPH_SPEC_VERSION, "HOCUS507")
    language_version = payload.get("languageVersion")
    if language_version not in SUPPORTED_LANGUAGE_VERSIONS:
        raise BundleValidationError("HOCUS507", "Compiled bundle language version is unsupported.")

    portable = payload.get("portable")
    if not isinstance(portable, bool):
        raise BundleValidationError("HOCUS508", "portable must be a boolean.")
    project_uid = payload.get("projectUid")
    manifest_digest = payload.get("projectManifestDigest")
    lock_digest = payload.get("projectLockDigest")
    if portable:
        if not isinstance(project_uid, str) or not _PROJECT_UID_PATTERN.fullmatch(project_uid):
            raise BundleValidationError("HOCUS509", "Portable bundles require a valid stable projectUid.")
        _require_digest(manifest_digest, "projectManifestDigest", "HOCUS509")
    elif project_uid is not None or manifest_digest is not None:
        raise BundleValidationError("HOCUS509", "Preview-only bundles cannot claim portable project identity.")
    if lock_digest is not None:
        _require_digest(lock_digest, "projectLockDigest", "HOCUS509")

    entry = _validate_source(payload.get("entrySource"), "entrySource", allow_kinds={"project_file", "workspace_file", "memory"})
    if portable:
        if entry["kind"] != "project_file" or not entry["uri"].startswith(f"hocus-project://{project_uid}/"):
            raise BundleValidationError("HOCUS510", "Portable entry source URI must match its project UID.")
    elif entry["kind"] == "project_file":
        raise BundleValidationError("HOCUS510", "Preview-only bundles cannot claim a project_file entry source.")

    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list) or len(dependencies) > MAX_DEPENDENCIES:
        raise BundleValidationError("HOCUS511", f"dependencies must be an array with at most {MAX_DEPENDENCIES} entries.")
    dependency_uris: set[str] = set()
    for index, dependency in enumerate(dependencies):
        normalized = _validate_source(dependency, f"dependencies[{index}]", allow_kinds={"module"})
        if normalized["uri"] in dependency_uris:
            raise BundleValidationError("HOCUS512", "Dependency source URIs must be unique.", details={"uri": normalized["uri"]})
        dependency_uris.add(normalized["uri"])

    if not isinstance(payload.get("catalogConstraints"), dict):
        raise BundleValidationError("HOCUS513", "catalogConstraints must be an object.")
    graph_spec = payload.get("graphSpec")
    if not isinstance(graph_spec, dict):
        raise BundleValidationError("HOCUS514", "graphSpec must be an object.")
    _require_equal(graph_spec, "$schema", "hocuspocus://schemas/graph-spec/v0.1", "HOCUS514")
    _require_equal(graph_spec, "kind", "graph_spec", "HOCUS514")
    _require_equal(graph_spec, "graphSpecVersion", GRAPH_SPEC_VERSION, "HOCUS514")
    _require_equal(graph_spec, "languageVersion", language_version, "HOCUS514")
    nodes = graph_spec.get("nodes")
    if not isinstance(nodes, list) or len(nodes) > 10_000:
        raise BundleValidationError("HOCUS515", "graphSpec.nodes must be an array with at most 10000 entries.")
    _validate_graph_spec(graph_spec)

    capabilities = payload.get("requiredCapabilities")
    expected_capabilities = _required_capabilities(graph_spec)
    if capabilities != expected_capabilities:
        raise BundleValidationError(
            "HOCUS516",
            "requiredCapabilities does not match the GraphSpec content.",
            details={"expected": expected_capabilities, "actual": capabilities},
        )
    source_maps = payload.get("sourceMaps")
    if not isinstance(source_maps, dict) or set(source_maps) != {"format", "entrySourceUri", "embeddedInGraphSpec"}:
        raise BundleValidationError("HOCUS517", "sourceMaps has an invalid shape.")
    if source_maps != {
        "format": "graph-spec-spans-v0.1",
        "entrySourceUri": entry["uri"],
        "embeddedInGraphSpec": True,
    }:
        raise BundleValidationError("HOCUS517", "sourceMaps is inconsistent with the entry source.")
    return CompiledBundle(canonical, declared_digest)


def _validate_source(value: Any, label: str, *, allow_kinds: set[str]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"uri", "digest", "kind"}:
        raise BundleValidationError("HOCUS518", f"{label} has an invalid source-record shape.")
    uri = value.get("uri")
    kind = value.get("kind")
    if not isinstance(uri, str) or not uri or len(uri) > 4096 or "://" not in uri:
        raise BundleValidationError("HOCUS518", f"{label}.uri must be a bounded canonical URI.")
    if kind not in allow_kinds:
        raise BundleValidationError("HOCUS518", f"{label}.kind is invalid.")
    digest = _require_digest(value.get("digest"), f"{label}.digest", "HOCUS518")
    return {"uri": uri, "digest": digest, "kind": kind}


def _validate_graph_spec(graph: dict[str, Any]) -> None:
    if set(graph) != _GRAPH_KEYS:
        raise BundleValidationError("HOCUS520", "graphSpec has missing or unknown fields.")
    if not isinstance(graph["name"], str) or not graph["name"]:
        raise BundleValidationError("HOCUS520", "graphSpec.name must be a non-empty string.")
    for key in ("target", "category", "ownership", "display", "render", "output", "layout"):
        if graph[key] is not None and not isinstance(graph[key], str):
            raise BundleValidationError("HOCUS520", f"graphSpec.{key} must be a string or null.")
    if graph["mode"] not in {"merge", "reconcile"}:
        raise BundleValidationError("HOCUS520", "graphSpec.mode must be merge or reconcile.")
    if graph["expectedRevision"] is not None and (
        not isinstance(graph["expectedRevision"], int) or isinstance(graph["expectedRevision"], bool) or graph["expectedRevision"] < 0
    ):
        raise BundleValidationError("HOCUS520", "graphSpec.expectedRevision must be a nonnegative integer or null.")
    _validate_span(graph["span"], "graphSpec.span")
    external_nodes = graph["externalNodes"]
    if not isinstance(external_nodes, list) or len(external_nodes) > 10_000:
        raise BundleValidationError("HOCUS520", "graphSpec.externalNodes must be a bounded array.")
    symbols: set[str] = set()
    for index, external in enumerate(external_nodes):
        label = f"graphSpec.externalNodes[{index}]"
        if not isinstance(external, dict) or set(external) != {"symbol", "path", "adopted", "span"}:
            raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
        _validate_symbol(external["symbol"], symbols, label)
        if not isinstance(external["path"], str) or not external["path"].startswith("/"):
            raise BundleValidationError("HOCUS520", f"{label}.path must be an absolute Houdini path.")
        if not isinstance(external["adopted"], bool):
            raise BundleValidationError("HOCUS520", f"{label}.adopted must be a boolean.")
        _validate_span(external["span"], f"{label}.span")
    for index, node in enumerate(graph["nodes"]):
        label = f"graphSpec.nodes[{index}]"
        if not isinstance(node, dict) or set(node) != {"symbol", "typeName", "inputs", "parms", "span"}:
            raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
        _validate_symbol(node["symbol"], symbols, label)
        if not isinstance(node["typeName"], str) or not node["typeName"]:
            raise BundleValidationError("HOCUS520", f"{label}.typeName must be a non-empty string.")
        if not isinstance(node["inputs"], list) or not isinstance(node["parms"], list):
            raise BundleValidationError("HOCUS520", f"{label} inputs and parms must be arrays.")
        _validate_span(node["span"], f"{label}.span")
        for input_index, input_spec in enumerate(node["inputs"]):
            _validate_input(input_spec, f"{label}.inputs[{input_index}]")
        for parm_index, parm in enumerate(node["parms"]):
            _validate_parm(parm, f"{label}.parms[{parm_index}]")


def _validate_symbol(value: Any, symbols: set[str], label: str) -> None:
    if not isinstance(value, str) or not value or value in symbols:
        raise BundleValidationError("HOCUS520", f"{label}.symbol must be a unique non-empty string.")
    symbols.add(value)


def _validate_input(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"index", "source", "span"}:
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    if not isinstance(value["index"], int) or isinstance(value["index"], bool) or value["index"] < 0:
        raise BundleValidationError("HOCUS520", f"{label}.index must be a nonnegative integer.")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"symbol", "outputIndex", "span"}:
        raise BundleValidationError("HOCUS520", f"{label}.source has an invalid shape.")
    if not isinstance(source["symbol"], str) or not source["symbol"]:
        raise BundleValidationError("HOCUS520", f"{label}.source.symbol must be non-empty.")
    if not isinstance(source["outputIndex"], int) or isinstance(source["outputIndex"], bool) or source["outputIndex"] < 0:
        raise BundleValidationError("HOCUS520", f"{label}.source.outputIndex must be nonnegative.")
    _validate_span(source["span"], f"{label}.source.span")
    _validate_span(value["span"], f"{label}.span")


def _validate_parm(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"name", "value", "span"}:
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    if not isinstance(value["name"], str) or not value["name"]:
        raise BundleValidationError("HOCUS520", f"{label}.name must be non-empty.")
    _validate_value(value["value"], f"{label}.value")
    _validate_span(value["span"], f"{label}.span")


def _validate_value(value: Any, label: str) -> None:
    if not isinstance(value, dict) or "kind" not in value:
        raise BundleValidationError("HOCUS520", f"{label} must be a typed value object.")
    kind = value["kind"]
    if kind == "literal" and set(value) == {"kind", "value", "span"}:
        _validate_span(value["span"], f"{label}.span")
        return
    if kind == "array" and set(value) == {"kind", "items", "span"} and isinstance(value["items"], list):
        for index, item in enumerate(value["items"]):
            _validate_value(item, f"{label}.items[{index}]")
        _validate_span(value["span"], f"{label}.span")
        return
    if kind == "code" and set(value) == {"kind", "language", "body", "span"}:
        if not isinstance(value["language"], str) or not isinstance(value["body"], str):
            raise BundleValidationError("HOCUS520", f"{label} code language and body must be strings.")
        _validate_span(value["span"], f"{label}.span")
        return
    raise BundleValidationError("HOCUS520", f"{label} has an invalid typed value shape.")


def _validate_span(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sourceUri", "start", "end"}:
        raise BundleValidationError("HOCUS520", f"{label} has an invalid span shape.")
    if not isinstance(value["sourceUri"], str) or not value["sourceUri"]:
        raise BundleValidationError("HOCUS520", f"{label}.sourceUri must be non-empty.")
    for endpoint in ("start", "end"):
        position = value[endpoint]
        if not isinstance(position, dict) or set(position) != {"offset", "line", "column"}:
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} has an invalid position shape.")
        if any(not isinstance(position[key], int) or isinstance(position[key], bool) for key in position):
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} values must be integers.")
        if position["offset"] < 0 or position["line"] < 1 or position["column"] < 1:
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} values are out of range.")


def _required_capabilities(graph_spec: dict[str, Any]) -> list[str]:
    capabilities = {"edit_scene"}
    stack: list[Any] = [graph_spec]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if value.get("kind") == "code":
                capabilities.add("run_code")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return sorted(capabilities)


def _validate_complexity(value: Any) -> None:
    count = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > MAX_BUNDLE_VALUES or depth > MAX_BUNDLE_DEPTH:
            raise BundleValidationError("HOCUS519", "Compiled bundle exceeds structural complexity limits.")
        if isinstance(item, float) and not math.isfinite(item):
            raise BundleValidationError("HOCUS519", "Compiled bundle contains a non-finite number.")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def _require_digest(value: Any, label: str, code: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise BundleValidationError(code, f"{label} must be a lowercase SHA-256 digest.")
    return value


def _require_equal(payload: dict[str, Any], key: str, expected: Any, code: str) -> None:
    if payload.get(key) != expected:
        raise BundleValidationError(code, f"{key} must equal {expected!r}.")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)
