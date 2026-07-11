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

BUNDLE_VERSION = "0.2"
LEGACY_BUNDLE_VERSION = "0.1"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_BUNDLE_DEPTH = 128
MAX_BUNDLE_VALUES = 250_000
MAX_DEPENDENCIES = 4096
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT_UID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BUNDLE_KEYS_V01 = {
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
_BUNDLE_KEYS_V02 = {*_BUNDLE_KEYS_V01, "semanticResolution"}
_GRAPH_KEYS = {
    "$schema", "kind", "graphSpecVersion", "languageVersion", "name", "target", "category", "mode",
    "expectedRevision", "ownership", "externalNodes", "nodes", "display", "render", "output", "layout", "span", "fieldSpans",
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
        semantic = result.semantic_result.to_dict() if result.semantic_result is not None else None
        if semantic is not None:
            if not semantic.get("valid"):
                raise ValueError("A semantic bundle requires a valid semantic resolution.")
            if not result.catalog_fingerprint or not result.catalog_content_digest:
                raise ValueError("A semantic bundle requires exact catalog fingerprint and content digest pins.")
            bundle_version = BUNDLE_VERSION
            schema_uri = "hocuspocus://schemas/compiled-bundle/v0.2"
            catalog_constraints = {
                "schemaVersion": 1,
                "fingerprint": result.catalog_fingerprint,
                "contentDigest": result.catalog_content_digest,
            }
            required_capabilities = list(semantic["requiredCapabilities"])
        else:
            bundle_version = LEGACY_BUNDLE_VERSION
            schema_uri = "hocuspocus://schemas/compiled-bundle/v0.1"
            catalog_constraints = {}
            required_capabilities = _required_capabilities(graph_spec)
        payload: dict[str, Any] = {
            "$schema": schema_uri,
            "kind": "hocus_compiled_bundle",
            "bundleVersion": bundle_version,
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
            "catalogConstraints": catalog_constraints,
            "requiredCapabilities": required_capabilities,
            "sourceMaps": {
                "format": "graph-spec-spans-v0.1",
                "entrySourceUri": entry_uri,
                "embeddedInGraphSpec": True,
            },
            "graphSpec": graph_spec,
        }
        if semantic is not None:
            payload["semanticResolution"] = semantic
        canonical = _canonical_json(payload)
        digest = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        return decode_compiled_bundle({**payload, "bundleDigest": digest})

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
    bundle_version = value.get("bundleVersion")
    expected_keys = _BUNDLE_KEYS_V02 if bundle_version == BUNDLE_VERSION else _BUNDLE_KEYS_V01
    keys = set(value)
    if bundle_version not in {LEGACY_BUNDLE_VERSION, BUNDLE_VERSION} or keys != expected_keys:
        raise BundleValidationError(
            "HOCUS501",
            "Compiled bundle has missing or unknown top-level fields.",
            details={"missing": sorted(expected_keys - keys), "unknown": sorted(keys - expected_keys)},
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

    expected_schema = f"hocuspocus://schemas/compiled-bundle/v{bundle_version}"
    _require_equal(payload, "$schema", expected_schema, "HOCUS506")
    _require_equal(payload, "kind", "hocus_compiled_bundle", "HOCUS506")
    supported_compilers = (
        {"0.1.1", COMPILER_VERSION}
        if bundle_version == LEGACY_BUNDLE_VERSION
        else {COMPILER_VERSION}
    )
    if payload.get("compilerVersion") not in supported_compilers:
        raise BundleValidationError("HOCUS507", "Compiled bundle compiler version is unsupported.")
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
    if bundle_version == BUNDLE_VERSION and portable and lock_digest is None:
        raise BundleValidationError("HOCUS509", "Portable semantic bundles require projectLockDigest.")
    if not portable and lock_digest is not None:
        raise BundleValidationError("HOCUS509", "Preview-only bundles cannot claim a project lock digest.")

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

    catalog_constraints = payload.get("catalogConstraints")
    if bundle_version == LEGACY_BUNDLE_VERSION:
        if catalog_constraints != {}:
            raise BundleValidationError("HOCUS513", "Bundle v0.1 catalogConstraints must be empty.")
    else:
        _validate_catalog_constraints(catalog_constraints)
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
    _validate_declared_source_uris(graph_spec, {entry["uri"], *dependency_uris})

    capabilities = payload.get("requiredCapabilities")
    expected_capabilities = _required_capabilities(graph_spec)
    if capabilities != expected_capabilities:
        raise BundleValidationError(
            "HOCUS516",
            "requiredCapabilities does not match the GraphSpec content.",
            details={"expected": expected_capabilities, "actual": capabilities},
        )
    if bundle_version == BUNDLE_VERSION:
        semantic = _validate_semantic_resolution(
            payload.get("semanticResolution"), catalog_constraints, graph_spec
        )
        if semantic["requiredCapabilities"] != capabilities:
            raise BundleValidationError(
                "HOCUS516",
                "Semantic capability manifest does not match requiredCapabilities.",
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


def _validate_catalog_constraints(value: Any) -> dict[str, Any]:
    keys = {"schemaVersion", "fingerprint", "contentDigest"}
    if not isinstance(value, dict) or set(value) != keys:
        raise BundleValidationError("HOCUS513", "Bundle v0.2 requires an exact catalog constraint.")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise BundleValidationError("HOCUS513", "Catalog constraint schemaVersion must be 1.")
    _require_digest(value["fingerprint"], "catalogConstraints.fingerprint", "HOCUS513")
    _require_digest(value["contentDigest"], "catalogConstraints.contentDigest", "HOCUS513")
    return value


def _validate_semantic_resolution(
    value: Any, constraint: dict[str, Any], graph: dict[str, Any]
) -> dict[str, Any]:
    keys = {
        "stage", "valid", "readyForDocumentLowering", "catalogFingerprint", "diagnostics",
        "operatorSelections", "parameterSelections", "connectionSelections", "deferredChecks",
        "requiredCapabilities",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise BundleValidationError("HOCUS521", "semanticResolution has an invalid shape.")
    if value["stage"] != "semantic" or value["valid"] is not True:
        raise BundleValidationError("HOCUS521", "A semantic bundle requires a valid semantic-stage result.")
    if not isinstance(value["readyForDocumentLowering"], bool):
        raise BundleValidationError("HOCUS521", "readyForDocumentLowering must be a boolean.")
    fingerprint = _require_digest(value["catalogFingerprint"], "semanticResolution.catalogFingerprint", "HOCUS521")
    if fingerprint != constraint["fingerprint"]:
        raise BundleValidationError("HOCUS521", "Semantic and catalog-constraint fingerprints differ.")
    capabilities = value["requiredCapabilities"]
    if (
        not isinstance(capabilities, list)
        or capabilities != sorted(set(capabilities))
        or any(item not in {"edit_scene", "run_code"} for item in capabilities)
    ):
        raise BundleValidationError("HOCUS521", "Semantic requiredCapabilities is invalid.")
    diagnostics = value["diagnostics"]
    if not isinstance(diagnostics, list) or len(diagnostics) > 500:
        raise BundleValidationError("HOCUS521", "Semantic diagnostics must be a bounded array.")
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict) or diagnostic.get("severity") == "error":
            raise BundleValidationError("HOCUS521", "A valid semantic bundle cannot contain error diagnostics.")
        if (
            diagnostic.get("severity") not in {"info", "warning"}
            or not isinstance(diagnostic.get("code"), str)
            or not diagnostic["code"]
            or not isinstance(diagnostic.get("phase"), str)
            or not isinstance(diagnostic.get("message"), str)
            or not diagnostic["message"]
        ):
            raise BundleValidationError("HOCUS521", "Semantic diagnostic records are malformed.")
    selection_shapes = {
        "operatorSelections": {
            "nodeSymbol", "nodeIndex", "jsonPointer", "category", "qualifiedName", "namespace",
            "version", "sourceKind", "definitionDigest",
        },
        "parameterSelections": {
            "nodeSymbol", "nodeIndex", "parmIndex", "jsonPointer", "authoredToken", "parameterToken",
            "componentIndex", "valueType", "conversion", "menuToken", "codeSurface",
        },
        "connectionSelections": {
            "nodeSymbol", "nodeIndex", "inputIndex", "inputName", "sourceSymbol", "outputIndex",
            "outputName", "jsonPointer",
        },
        "deferredChecks": {"kind", "jsonPointer", "symbol", "message"},
    }
    for field, shape in selection_shapes.items():
        records = value[field]
        if not isinstance(records, list) or len(records) > 50_000:
            raise BundleValidationError("HOCUS521", f"semanticResolution.{field} must be a bounded array.")
        for record in records:
            if not isinstance(record, dict) or set(record) != shape:
                raise BundleValidationError("HOCUS521", f"semanticResolution.{field} contains an invalid record.")
            pointer = record.get("jsonPointer")
            if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
                raise BundleValidationError("HOCUS521", f"semanticResolution.{field} has an invalid JSON pointer.")

    operator_selections = value["operatorSelections"]
    if len(operator_selections) != len(graph["nodes"]):
        raise BundleValidationError("HOCUS521", "Semantic operator selections do not cover every graph node.")
    for index, (record, node) in enumerate(zip(operator_selections, graph["nodes"])):
        _require_semantic_index(record["nodeIndex"], f"operatorSelections[{index}].nodeIndex", expected=index)
        _require_semantic_string(record["nodeSymbol"], f"operatorSelections[{index}].nodeSymbol", expected=node["symbol"])
        _require_semantic_string(record["jsonPointer"], f"operatorSelections[{index}].jsonPointer", expected=f"/nodes/{index}/typeName")
        _require_semantic_string(record["category"], f"operatorSelections[{index}].category")
        _require_semantic_string(record["qualifiedName"], f"operatorSelections[{index}].qualifiedName")
        _require_nullable_semantic_string(record["namespace"], f"operatorSelections[{index}].namespace")
        _require_nullable_semantic_string(record["version"], f"operatorSelections[{index}].version")
        if record["sourceKind"] not in {"builtin", "hda", "package", "labs"}:
            raise BundleValidationError("HOCUS521", "Semantic operator sourceKind is invalid.")
        if record["definitionDigest"] is not None:
            _require_digest(record["definitionDigest"], "semantic operator definitionDigest", "HOCUS521")
        if graph.get("category") is not None and record["category"] != graph["category"]:
            raise BundleValidationError("HOCUS521", "Semantic operator category conflicts with GraphSpec category.")

    expected_parms = [
        (node_index, parm_index, node, parm)
        for node_index, node in enumerate(graph["nodes"])
        for parm_index, parm in enumerate(node["parms"])
    ]
    parameter_selections = value["parameterSelections"]
    if len(parameter_selections) != len(expected_parms):
        raise BundleValidationError("HOCUS521", "Semantic parameter selections do not cover every authored parameter.")
    for record, (node_index, parm_index, node, parm) in zip(parameter_selections, expected_parms):
        _require_semantic_index(record["nodeIndex"], "parameter selection nodeIndex", expected=node_index)
        _require_semantic_index(record["parmIndex"], "parameter selection parmIndex", expected=parm_index)
        _require_semantic_string(record["nodeSymbol"], "parameter selection nodeSymbol", expected=node["symbol"])
        _require_semantic_string(record["jsonPointer"], "parameter selection jsonPointer", expected=f"/nodes/{node_index}/parms/{parm_index}")
        _require_semantic_string(record["authoredToken"], "parameter selection authoredToken", expected=parm["name"])
        _require_semantic_string(record["parameterToken"], "parameter selection parameterToken")
        if record["componentIndex"] is not None:
            _require_semantic_index(record["componentIndex"], "parameter selection componentIndex")
        if record["valueType"] not in {
            "bool", "int", "float", "string", "tuple", "menu", "code", "button",
            "node_path", "parm_path", "file_path", "usd_prim_path", "asset_reference",
            "ramp", "multiparm",
        }:
            raise BundleValidationError("HOCUS521", "Parameter selection valueType is invalid.")
        for field in ("conversion", "menuToken", "codeSurface"):
            _require_nullable_semantic_string(record[field], f"parameter selection {field}")
        if record["conversion"] not in {None, "int_to_float"}:
            raise BundleValidationError("HOCUS521", "Parameter selection conversion is invalid.")
        if record["codeSurface"] not in {None, "vex", "python", "hscript"}:
            raise BundleValidationError("HOCUS521", "Parameter selection codeSurface is invalid.")

    outcomes: dict[str, str] = {}
    for record in value["connectionSelections"]:
        node_index = _require_semantic_index(record["nodeIndex"], "connection selection nodeIndex")
        if node_index >= len(graph["nodes"]):
            raise BundleValidationError("HOCUS521", "Connection selection nodeIndex is outside GraphSpec.")
        node = graph["nodes"][node_index]
        _require_semantic_string(record["nodeSymbol"], "connection selection nodeSymbol", expected=node["symbol"])
        pointer = record["jsonPointer"]
        prefix = f"/nodes/{node_index}/inputs/"
        if not pointer.startswith(prefix) or not pointer[len(prefix):].isdigit():
            raise BundleValidationError("HOCUS521", "Connection selection JSON pointer is invalid.")
        ordinal = int(pointer[len(prefix):])
        if ordinal >= len(node["inputs"]):
            raise BundleValidationError("HOCUS521", "Connection selection points outside GraphSpec inputs.")
        authored = node["inputs"][ordinal]
        _require_semantic_index(record["inputIndex"], "connection selection inputIndex", expected=authored["index"])
        _require_semantic_string(record["sourceSymbol"], "connection selection sourceSymbol", expected=authored["source"]["symbol"])
        _require_semantic_index(record["outputIndex"], "connection selection outputIndex", expected=authored["source"]["outputIndex"])
        _require_nullable_semantic_string(record["inputName"], "connection selection inputName")
        _require_nullable_semantic_string(record["outputName"], "connection selection outputName")
        if pointer in outcomes:
            raise BundleValidationError("HOCUS521", "Semantic input outcomes must be unique.")
        outcomes[pointer] = "resolved"

    for record in value["deferredChecks"]:
        if record["kind"] != "external_output":
            raise BundleValidationError("HOCUS521", "Semantic deferred-check kind is invalid.")
        _require_semantic_string(record["symbol"], "deferred-check symbol")
        _require_semantic_string(record["message"], "deferred-check message")
        pointer = record["jsonPointer"]
        if not pointer.endswith("/source"):
            raise BundleValidationError("HOCUS521", "Deferred-check pointer must identify an input source.")
        input_pointer = pointer[:-len("/source")]
        parts = input_pointer.strip("/").split("/")
        if (
            len(parts) != 4
            or parts[0] != "nodes"
            or not parts[1].isdigit()
            or parts[2] != "inputs"
            or not parts[3].isdigit()
        ):
            raise BundleValidationError("HOCUS521", "Deferred-check pointer is outside GraphSpec inputs.")
        node_index, input_index = int(parts[1]), int(parts[3])
        if node_index >= len(graph["nodes"]) or input_index >= len(graph["nodes"][node_index]["inputs"]):
            raise BundleValidationError("HOCUS521", "Deferred-check pointer is outside GraphSpec inputs.")
        authored_symbol = graph["nodes"][node_index]["inputs"][input_index]["source"]["symbol"]
        external_symbols = {item["symbol"] for item in graph["externalNodes"]}
        if record["symbol"] != authored_symbol or authored_symbol not in external_symbols:
            raise BundleValidationError("HOCUS521", "Deferred-check symbol is not the authored external source.")
        if not any(
            diagnostic.get("code") == "HOCUS643" and diagnostic.get("jsonPointer") == pointer
            for diagnostic in diagnostics
        ):
            raise BundleValidationError("HOCUS521", "Deferred external checks require a matching diagnostic.")
        if input_pointer in outcomes:
            raise BundleValidationError("HOCUS521", "Semantic input outcomes must be unique.")
        outcomes[input_pointer] = "deferred"

    expected_inputs = {
        f"/nodes/{node_index}/inputs/{input_index}"
        for node_index, node in enumerate(graph["nodes"])
        for input_index, _ in enumerate(node["inputs"])
    }
    if set(outcomes) != expected_inputs:
        raise BundleValidationError("HOCUS521", "Semantic input outcomes do not cover every authored connection.")
    ready = not value["deferredChecks"]
    if value["readyForDocumentLowering"] != ready:
        raise BundleValidationError("HOCUS521", "Semantic document-lowering readiness is inconsistent with deferred checks.")
    return value


def _require_semantic_index(value: Any, label: str, *, expected: int | None = None) -> int:
    if type(value) is not int or value < 0 or (expected is not None and value != expected):
        raise BundleValidationError("HOCUS521", f"{label} is invalid.")
    return value


def _require_semantic_string(value: Any, label: str, *, expected: str | None = None) -> str:
    if not isinstance(value, str) or not value or (expected is not None and value != expected):
        raise BundleValidationError("HOCUS521", f"{label} is invalid.")
    return value


def _require_nullable_semantic_string(value: Any, label: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise BundleValidationError("HOCUS521", f"{label} is invalid.")


def _validate_graph_spec(graph: dict[str, Any]) -> None:
    if set(graph) != _GRAPH_KEYS:
        raise BundleValidationError("HOCUS520", "graphSpec has missing or unknown fields.")
    if not isinstance(graph["name"], str) or not _IDENTIFIER_PATTERN.fullmatch(graph["name"]):
        raise BundleValidationError("HOCUS520", "graphSpec.name must be a HocusScript identifier.")
    if not isinstance(graph["target"], str) or not _is_canonical_houdini_path(graph["target"]):
        raise BundleValidationError("HOCUS520", "graphSpec.target must be a canonical absolute Houdini path.")
    if graph["category"] is not None and (
        not isinstance(graph["category"], str) or not _IDENTIFIER_PATTERN.fullmatch(graph["category"])
    ):
        raise BundleValidationError("HOCUS520", "graphSpec.category must be an identifier or null.")
    if graph["ownership"] is not None and (
        not isinstance(graph["ownership"], str) or not graph["ownership"].strip()
    ):
        raise BundleValidationError("HOCUS520", "graphSpec.ownership must be a non-empty string or null.")
    for key in ("display", "render", "output"):
        if graph[key] is not None and (
            not isinstance(graph[key], str) or not _IDENTIFIER_PATTERN.fullmatch(graph[key])
        ):
            raise BundleValidationError("HOCUS520", f"graphSpec.{key} must be an identifier or null.")
    if graph["layout"] not in {None, "auto"}:
        raise BundleValidationError("HOCUS520", "graphSpec.layout must be auto or null.")
    if graph["mode"] not in {"merge", "reconcile"}:
        raise BundleValidationError("HOCUS520", "graphSpec.mode must be merge or reconcile.")
    if graph["mode"] == "reconcile" and graph["ownership"] is None:
        raise BundleValidationError("HOCUS520", "Reconcile GraphSpecs require ownership.")
    if graph["expectedRevision"] is not None and (
        not isinstance(graph["expectedRevision"], int) or isinstance(graph["expectedRevision"], bool) or graph["expectedRevision"] < 0
    ):
        raise BundleValidationError("HOCUS520", "graphSpec.expectedRevision must be a nonnegative integer or null.")
    _validate_span(graph["span"], "graphSpec.span")
    field_spans = graph["fieldSpans"]
    allowed_field_spans = {
        "languageVersion", "name", "target", "category", "mode", "expectedRevision", "ownership",
        "display", "render", "output", "layout",
    }
    if not isinstance(field_spans, dict) or "name" not in field_spans or set(field_spans) - allowed_field_spans:
        raise BundleValidationError("HOCUS520", "graphSpec.fieldSpans has an invalid shape.")
    for key, span in field_spans.items():
        _validate_span(span, f"graphSpec.fieldSpans.{key}")
    external_nodes = graph["externalNodes"]
    if not isinstance(external_nodes, list) or len(external_nodes) > 10_000:
        raise BundleValidationError("HOCUS520", "graphSpec.externalNodes must be a bounded array.")
    symbols: set[str] = set()
    mutable_symbols: set[str] = set()
    for index, external in enumerate(external_nodes):
        label = f"graphSpec.externalNodes[{index}]"
        if not isinstance(external, dict) or set(external) not in (
            {"symbol", "path", "adopted", "span"},
            {"symbol", "path", "adopted", "span", "fieldSpans"},
        ):
            raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
        _validate_symbol(external["symbol"], symbols, label)
        if not isinstance(external["path"], str) or not _is_canonical_houdini_path(external["path"]):
            raise BundleValidationError("HOCUS520", f"{label}.path must be a canonical absolute Houdini path.")
        target_prefix = graph["target"].rstrip("/") + "/"
        if external["path"] != graph["target"] and not external["path"].startswith(target_prefix):
            raise BundleValidationError("HOCUS520", f"{label}.path is outside the graph target.")
        if not isinstance(external["adopted"], bool):
            raise BundleValidationError("HOCUS520", f"{label}.adopted must be a boolean.")
        if external["adopted"]:
            mutable_symbols.add(external["symbol"])
        _validate_span(external["span"], f"{label}.span")
        _validate_optional_field_spans(external, label, {"symbol", "path"})
    for index, node in enumerate(graph["nodes"]):
        label = f"graphSpec.nodes[{index}]"
        if not isinstance(node, dict) or set(node) not in (
            {"symbol", "typeName", "inputs", "parms", "span"},
            {"symbol", "typeName", "inputs", "parms", "span", "fieldSpans"},
        ):
            raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
        _validate_symbol(node["symbol"], symbols, label)
        mutable_symbols.add(node["symbol"])
        if not isinstance(node["typeName"], str) or not node["typeName"].strip() or len(node["typeName"]) > 4096:
            raise BundleValidationError("HOCUS520", f"{label}.typeName must be a non-empty string.")
        if not isinstance(node["inputs"], list) or not isinstance(node["parms"], list):
            raise BundleValidationError("HOCUS520", f"{label} inputs and parms must be arrays.")
        _validate_span(node["span"], f"{label}.span")
        _validate_optional_field_spans(node, label, {"symbol", "typeName"})
        input_identities: set[int] = set()
        for input_index, input_spec in enumerate(node["inputs"]):
            _validate_input(input_spec, f"{label}.inputs[{input_index}]")
            if input_spec["index"] in input_identities:
                raise BundleValidationError("HOCUS520", f"{label} has duplicate input indexes.")
            input_identities.add(input_spec["index"])
        parm_identities: set[str] = set()
        for parm_index, parm in enumerate(node["parms"]):
            _validate_parm(parm, f"{label}.parms[{parm_index}]")
            if parm["name"] in parm_identities:
                raise BundleValidationError("HOCUS520", f"{label} has duplicate parameter assignments.")
            parm_identities.add(parm["name"])

    for node in graph["nodes"]:
        for input_spec in node["inputs"]:
            if input_spec["source"]["symbol"] not in symbols:
                raise BundleValidationError("HOCUS520", "GraphSpec input references an unknown symbol.")
    for directive in ("display", "render", "output"):
        symbol = graph[directive]
        if symbol is not None and symbol not in symbols:
            raise BundleValidationError("HOCUS520", f"graphSpec.{directive} references an unknown symbol.")
        if symbol is not None and symbol not in mutable_symbols:
            raise BundleValidationError("HOCUS520", f"graphSpec.{directive} targets a read-only existing symbol.")


def _is_canonical_houdini_path(path: str) -> bool:
    if path == "/":
        return True
    if not path.startswith("/") or path.endswith("/"):
        return False
    segments = path.split("/")[1:]
    return bool(segments) and all(segment not in {"", ".", ".."} for segment in segments)


def _validate_symbol(value: Any, symbols: set[str], label: str) -> None:
    if (
        not isinstance(value, str)
        or not _IDENTIFIER_PATTERN.fullmatch(value)
        or value in symbols
    ):
        raise BundleValidationError("HOCUS520", f"{label}.symbol must be a unique identifier.")
    symbols.add(value)


def _validate_input(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) not in (
        {"index", "source", "span"}, {"index", "source", "span", "fieldSpans"},
    ):
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    if not isinstance(value["index"], int) or isinstance(value["index"], bool) or value["index"] < 0:
        raise BundleValidationError("HOCUS520", f"{label}.index must be a nonnegative integer.")
    source = value["source"]
    if not isinstance(source, dict) or set(source) not in (
        {"symbol", "outputIndex", "span"}, {"symbol", "outputIndex", "span", "fieldSpans"},
    ):
        raise BundleValidationError("HOCUS520", f"{label}.source has an invalid shape.")
    if not isinstance(source["symbol"], str) or not _IDENTIFIER_PATTERN.fullmatch(source["symbol"]):
        raise BundleValidationError("HOCUS520", f"{label}.source.symbol must be an identifier.")
    if not isinstance(source["outputIndex"], int) or isinstance(source["outputIndex"], bool) or source["outputIndex"] < 0:
        raise BundleValidationError("HOCUS520", f"{label}.source.outputIndex must be nonnegative.")
    _validate_span(source["span"], f"{label}.source.span")
    _validate_span(value["span"], f"{label}.span")
    _validate_optional_field_spans(source, f"{label}.source", {"symbol", "outputIndex"})
    _validate_optional_field_spans(value, label, {"index"})


def _validate_parm(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) not in (
        {"name", "value", "span"}, {"name", "value", "span", "fieldSpans"},
    ):
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    if not isinstance(value["name"], str) or not _IDENTIFIER_PATTERN.fullmatch(value["name"]):
        raise BundleValidationError("HOCUS520", f"{label}.name must be an identifier.")
    _validate_value(value["value"], f"{label}.value")
    _validate_span(value["span"], f"{label}.span")
    _validate_optional_field_spans(value, label, {"name"})


def _validate_optional_field_spans(value: dict[str, Any], label: str, expected: set[str]) -> None:
    if "fieldSpans" not in value:
        return
    field_spans = value["fieldSpans"]
    if not isinstance(field_spans, dict) or set(field_spans) != expected:
        raise BundleValidationError("HOCUS520", f"{label}.fieldSpans has an invalid shape.")
    for key, span in field_spans.items():
        _validate_span(span, f"{label}.fieldSpans.{key}")


def _validate_value(value: Any, label: str) -> None:
    if not isinstance(value, dict) or "kind" not in value:
        raise BundleValidationError("HOCUS520", f"{label} must be a typed value object.")
    kind = value["kind"]
    if kind == "literal" and set(value) == {"kind", "value", "span"}:
        literal = value["value"]
        if literal is not None and not isinstance(literal, (str, bool, int, float)):
            raise BundleValidationError("HOCUS520", f"{label}.value is not a scalar literal.")
        _validate_span(value["span"], f"{label}.span")
        return
    if kind == "array" and set(value) == {"kind", "items", "span"} and isinstance(value["items"], list):
        for index, item in enumerate(value["items"]):
            _validate_value(item, f"{label}.items[{index}]")
        _validate_span(value["span"], f"{label}.span")
        return
    if kind == "code" and set(value) in (
        {"kind", "language", "body", "span"},
        {"kind", "language", "body", "span", "bodySpan", "offsetMap"},
    ):
        if value["language"] not in {"vex", "python", "hscript"} or not isinstance(value["body"], str):
            raise BundleValidationError("HOCUS520", f"{label} code language must be vex/python/hscript and body must be a string.")
        _validate_span(value["span"], f"{label}.span")
        if "bodySpan" in value:
            _validate_span(value["bodySpan"], f"{label}.bodySpan")
            _validate_code_offset_map(value["offsetMap"], value["body"], value["bodySpan"], label)
        return
    raise BundleValidationError("HOCUS520", f"{label} has an invalid typed value shape.")


def _validate_code_offset_map(value: Any, body: str, body_span: dict[str, Any], label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"bodyLength", "checkpoints"}:
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap has an invalid shape.")
    if type(value["bodyLength"]) is not int or value["bodyLength"] != len(body):
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap body length is inconsistent.")
    checkpoints = value["checkpoints"]
    if not isinstance(checkpoints, list) or not checkpoints:
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoints must be non-empty.")
    previous = (-1, -1)
    normalized: list[tuple[int, int]] = []
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict) or set(checkpoint) != {"bodyOffset", "sourceOffset"}:
            raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoint has an invalid shape.")
        pair = (checkpoint["bodyOffset"], checkpoint["sourceOffset"])
        if any(type(item) is not int or item < 0 for item in pair):
            raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoints must be monotonic integers.")
        if previous != (-1, -1):
            body_delta = pair[0] - previous[0]
            source_delta = pair[1] - previous[1]
            if body_delta <= 0 or source_delta < body_delta:
                raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoints are not physically possible.")
        previous = pair
        normalized.append(pair)
    expected_start = body_span["start"]["offset"]
    expected_end = body_span["end"]["offset"]
    if normalized[0] != (0, expected_start) or normalized[-1] != (len(body), expected_end):
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap endpoints are inconsistent with bodySpan.")


def _validate_span(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sourceUri", "start", "end"}:
        raise BundleValidationError("HOCUS520", f"{label} has an invalid span shape.")
    if not isinstance(value["sourceUri"], str) or not value["sourceUri"] or len(value["sourceUri"]) > 1024:
        raise BundleValidationError("HOCUS520", f"{label}.sourceUri must be a bounded non-empty string.")
    for endpoint in ("start", "end"):
        position = value[endpoint]
        if not isinstance(position, dict) or set(position) != {"offset", "line", "column"}:
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} has an invalid position shape.")
        if any(not isinstance(position[key], int) or isinstance(position[key], bool) for key in position):
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} values must be integers.")
        if position["offset"] < 0 or position["line"] < 1 or position["column"] < 1:
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} values are out of range.")
    start = value["start"]
    end = value["end"]
    if end["offset"] < start["offset"] or (end["line"], end["column"]) < (start["line"], start["column"]):
        raise BundleValidationError("HOCUS520", f"{label} end precedes its start.")


def _validate_declared_source_uris(value: Any, allowed: set[str]) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if {"sourceUri", "start", "end"}.issubset(item) and item["sourceUri"] not in allowed:
                raise BundleValidationError(
                    "HOCUS520",
                    "GraphSpec source span references an undeclared source URI.",
                    details={"sourceUri": item["sourceUri"]},
                )
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


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
