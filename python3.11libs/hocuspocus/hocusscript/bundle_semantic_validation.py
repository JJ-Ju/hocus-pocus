"""Semantic and expansion-map validation for compiled bundles."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote, unquote

from .bundle import (
    BundleValidationError,
    _EXPANSION_STACK_DIGEST_DOMAIN,
    _IDENTIFIER_PATTERN,
    _JSON_POINTER_PATTERN,
    _MODULE_URI_PATTERN,
    _canonical_json,
    _require_digest,
    _required_expansion_pointers,
    _validate_span,
)
from .model import EXPLICIT_NODE_ID_PATTERN, MODULE_GRAPH_SPEC_VERSION

def _validate_semantic_resolution(
    value: Any, constraint: dict[str, Any], graph: dict[str, Any],
    *, require_module_provenance: bool = False,
) -> dict[str, Any]:
    diagnostics = _validate_semantic_envelope(
        value, constraint, graph, require_module_provenance
    )
    _validate_operator_selections(value["operatorSelections"], graph)
    _validate_parameter_selections(value["parameterSelections"], graph)
    outcomes = _validate_connection_selections(value["connectionSelections"], graph)
    _validate_deferred_checks(value["deferredChecks"], graph, diagnostics, outcomes)
    expected_inputs = {
        f"/nodes/{node_index}/inputs/{input_index}"
        for node_index, node in enumerate(graph["nodes"])
        for input_index, _ in enumerate(node["inputs"])
    }
    if set(outcomes) != expected_inputs:
        raise BundleValidationError(
            "HOCUS521", "Semantic input outcomes do not cover every authored connection."
        )
    ready = not value["deferredChecks"]
    if value["readyForDocumentLowering"] != ready:
        raise BundleValidationError(
            "HOCUS521",
            "Semantic document-lowering readiness is inconsistent with deferred checks.",
        )
    return value


def _validate_semantic_envelope(
    value: Any, constraint: dict[str, Any], graph: dict[str, Any],
    require_module_provenance: bool,
) -> list[dict[str, Any]]:
    keys = {
        "stage", "valid", "readyForDocumentLowering", "catalogFingerprint", "diagnostics",
        "operatorSelections", "parameterSelections", "connectionSelections", "deferredChecks",
        "requiredCapabilities",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise BundleValidationError("HOCUS521", "semanticResolution has an invalid shape.")
    if value["stage"] != "semantic" or value["valid"] is not True:
        raise BundleValidationError(
            "HOCUS521", "A semantic bundle requires a valid semantic-stage result."
        )
    if not isinstance(value["readyForDocumentLowering"], bool):
        raise BundleValidationError("HOCUS521", "readyForDocumentLowering must be a boolean.")
    fingerprint = _require_digest(
        value["catalogFingerprint"], "semanticResolution.catalogFingerprint", "HOCUS521"
    )
    if fingerprint != constraint["fingerprint"]:
        raise BundleValidationError(
            "HOCUS521", "Semantic and catalog-constraint fingerprints differ."
        )
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
        _validate_semantic_diagnostic(diagnostic, graph, require_module_provenance)
    _validate_selection_shapes(value)
    return diagnostics


def _validate_semantic_diagnostic(
    diagnostic: Any, graph: dict[str, Any], require_module_provenance: bool,
) -> None:
    if not isinstance(diagnostic, dict) or diagnostic.get("severity") == "error":
        raise BundleValidationError(
            "HOCUS521", "A valid semantic bundle cannot contain error diagnostics."
        )
    if (
        diagnostic.get("severity") not in {"info", "warning"}
        or not isinstance(diagnostic.get("code"), str) or not diagnostic["code"]
        or not isinstance(diagnostic.get("phase"), str)
        or not isinstance(diagnostic.get("message"), str) or not diagnostic["message"]
    ):
        raise BundleValidationError("HOCUS521", "Semantic diagnostic records are malformed.")
    if require_module_provenance:
        _validate_semantic_diagnostic_provenance(diagnostic, graph)


def _validate_selection_shapes(value: dict[str, Any]) -> None:
    shapes = {
        "operatorSelections": {
            "nodeSymbol", "nodeIndex", "jsonPointer", "category", "qualifiedName", "namespace",
            "version", "sourceKind", "definitionDigest",
        },
        "parameterSelections": {
            "nodeSymbol", "nodeIndex", "parmIndex", "jsonPointer", "authoredToken",
            "parameterToken", "componentIndex", "valueType", "conversion", "menuToken",
            "codeSurface",
        },
        "connectionSelections": {
            "nodeSymbol", "nodeIndex", "inputIndex", "inputName", "sourceSymbol",
            "outputIndex", "outputName", "jsonPointer",
        },
        "deferredChecks": {"kind", "jsonPointer", "symbol", "message"},
    }
    for field, shape in shapes.items():
        records = value[field]
        if not isinstance(records, list) or len(records) > 50_000:
            raise BundleValidationError(
                "HOCUS521", f"semanticResolution.{field} must be a bounded array."
            )
        for record in records:
            pointer = record.get("jsonPointer") if isinstance(record, dict) else None
            if not isinstance(record, dict) or set(record) != shape:
                raise BundleValidationError(
                    "HOCUS521", f"semanticResolution.{field} contains an invalid record."
                )
            if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
                raise BundleValidationError(
                    "HOCUS521", f"semanticResolution.{field} has an invalid JSON pointer."
                )


def _validate_operator_selections(
    selections: list[dict[str, Any]], graph: dict[str, Any],
) -> None:
    if len(selections) != len(graph["nodes"]):
        raise BundleValidationError(
            "HOCUS521", "Semantic operator selections do not cover every graph node."
        )
    for index, (record, node) in enumerate(zip(selections, graph["nodes"])):
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
            raise BundleValidationError(
                "HOCUS521", "Semantic operator category conflicts with GraphSpec category."
            )


def _validate_parameter_selections(
    selections: list[dict[str, Any]], graph: dict[str, Any],
) -> None:
    expected = [
        (node_index, parm_index, node, parm)
        for node_index, node in enumerate(graph["nodes"])
        for parm_index, parm in enumerate(node["parms"])
    ]
    if len(selections) != len(expected):
        raise BundleValidationError(
            "HOCUS521", "Semantic parameter selections do not cover every authored parameter."
        )
    for record, authored in zip(selections, expected):
        _validate_parameter_selection(record, authored)


def _validate_parameter_selection(
    record: dict[str, Any], authored: tuple[int, int, dict[str, Any], dict[str, Any]],
) -> None:
    node_index, parm_index, node, parm = authored
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


def _validate_connection_selections(
    selections: list[dict[str, Any]], graph: dict[str, Any],
) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for record in selections:
        node_index = _require_semantic_index(
            record["nodeIndex"], "connection selection nodeIndex"
        )
        if node_index >= len(graph["nodes"]):
            raise BundleValidationError(
                "HOCUS521", "Connection selection nodeIndex is outside GraphSpec."
            )
        node = graph["nodes"][node_index]
        _validate_connection_selection(record, node, node_index, outcomes)
    return outcomes


def _validate_connection_selection(
    record: dict[str, Any], node: dict[str, Any], node_index: int,
    outcomes: dict[str, str],
) -> None:
    _require_semantic_string(
        record["nodeSymbol"], "connection selection nodeSymbol", expected=node["symbol"]
    )
    pointer = record["jsonPointer"]
    prefix = f"/nodes/{node_index}/inputs/"
    if not pointer.startswith(prefix) or not pointer[len(prefix):].isdigit():
        raise BundleValidationError(
            "HOCUS521", "Connection selection JSON pointer is invalid."
        )
    ordinal = int(pointer[len(prefix):])
    if ordinal >= len(node["inputs"]):
        raise BundleValidationError(
            "HOCUS521", "Connection selection points outside GraphSpec inputs."
        )
    authored = node["inputs"][ordinal]
    _require_semantic_index(record["inputIndex"], "connection selection inputIndex", expected=authored["index"])
    _require_semantic_string(record["sourceSymbol"], "connection selection sourceSymbol", expected=authored["source"]["symbol"])
    _require_semantic_index(record["outputIndex"], "connection selection outputIndex", expected=authored["source"]["outputIndex"])
    _require_nullable_semantic_string(record["inputName"], "connection selection inputName")
    _require_nullable_semantic_string(record["outputName"], "connection selection outputName")
    if pointer in outcomes:
        raise BundleValidationError("HOCUS521", "Semantic input outcomes must be unique.")
    outcomes[pointer] = "resolved"


def _validate_deferred_checks(
    checks: list[dict[str, Any]], graph: dict[str, Any],
    diagnostics: list[dict[str, Any]], outcomes: dict[str, str],
) -> None:
    external_symbols = {item["symbol"] for item in graph["externalNodes"]}
    for record in checks:
        if record["kind"] != "external_output":
            raise BundleValidationError("HOCUS521", "Semantic deferred-check kind is invalid.")
        _require_semantic_string(record["symbol"], "deferred-check symbol")
        _require_semantic_string(record["message"], "deferred-check message")
        pointer = record["jsonPointer"]
        if not pointer.endswith("/source"):
            raise BundleValidationError(
                "HOCUS521", "Deferred-check pointer must identify an input source."
            )
        input_pointer = pointer[:-len("/source")]
        parts = input_pointer.strip("/").split("/")
        if (
            len(parts) != 4 or parts[0] != "nodes" or not parts[1].isdigit()
            or parts[2] != "inputs" or not parts[3].isdigit()
        ):
            raise BundleValidationError(
                "HOCUS521", "Deferred-check pointer is outside GraphSpec inputs."
            )
        node_index, input_index = int(parts[1]), int(parts[3])
        if node_index >= len(graph["nodes"]) or input_index >= len(graph["nodes"][node_index]["inputs"]):
            raise BundleValidationError(
                "HOCUS521", "Deferred-check pointer is outside GraphSpec inputs."
            )
        authored_symbol = graph["nodes"][node_index]["inputs"][input_index]["source"]["symbol"]
        if record["symbol"] != authored_symbol or authored_symbol not in external_symbols:
            raise BundleValidationError(
                "HOCUS521", "Deferred-check symbol is not the authored external source."
            )
        if not any(
            item.get("code") == "HOCUS643" and item.get("jsonPointer") == pointer
            for item in diagnostics
        ):
            raise BundleValidationError(
                "HOCUS521", "Deferred external checks require a matching diagnostic."
            )
        if input_pointer in outcomes:
            raise BundleValidationError("HOCUS521", "Semantic input outcomes must be unique.")
        outcomes[input_pointer] = "deferred"


def _validate_semantic_diagnostic_provenance(
    diagnostic: dict[str, Any], graph: dict[str, Any],
) -> None:
    """Bind a module diagnostic to the canonical enclosing expansion origin."""

    allowed = {
        "severity", "code", "phase", "message", "jsonPointer", "originId", "stackId",
        "sourceUri", "span", "related", "notes", "fixes", "details", "expansionStack",
        "entityUid", "houdiniPath",
    }
    required = {
        "jsonPointer", "originId", "stackId", "related", "expansionStack",
        "entityUid", "houdiniPath",
    }
    if (
        not required.issubset(diagnostic)
        or set(diagnostic) - allowed
    ):
        raise BundleValidationError(
            "HOCUS521", "Bundle v0.3 semantic diagnostics have an invalid provenance shape."
        )
    if diagnostic["expansionStack"] != [] or diagnostic["related"] != []:
        raise BundleValidationError(
            "HOCUS521", "Bundle v0.3 diagnostics cannot embed expansion frames or related source records."
        )
    if diagnostic["entityUid"] is not None or diagnostic["houdiniPath"] is not None:
        raise BundleValidationError(
            "HOCUS521", "Offline Bundle v0.3 diagnostics cannot claim live entity or Houdini paths."
        )
    pointer = diagnostic.get("jsonPointer")
    if pointer is not None and (
        not isinstance(pointer, str)
        or len(pointer) > 8192
        or _JSON_POINTER_PATTERN.fullmatch(pointer) is None
        or not _json_pointer_resolves(graph, pointer)
    ):
        raise BundleValidationError("HOCUS521", "Semantic diagnostic jsonPointer is invalid.")
    mapping = _enclosing_expansion_mapping(pointer, graph["expansionMap"]["mappings"])
    expected_origin = mapping["originId"] if mapping is not None else None
    expected_stack = mapping["stackId"] if mapping is not None else None
    origin_id = diagnostic["originId"]
    stack_id = diagnostic["stackId"]
    if origin_id is not None:
        _require_digest(origin_id, "semantic diagnostic originId", "HOCUS521")
    if stack_id is not None:
        _require_digest(stack_id, "semantic diagnostic stackId", "HOCUS521")
    if origin_id != expected_origin or stack_id != expected_stack:
        raise BundleValidationError(
            "HOCUS521",
            "Semantic diagnostic provenance does not match its enclosing expansion mapping.",
            details={
                "jsonPointer": pointer,
                "expectedOriginId": expected_origin,
                "expectedStackId": expected_stack,
            },
        )
    if mapping is None:
        if "sourceUri" in diagnostic or "span" in diagnostic:
            raise BundleValidationError(
                "HOCUS521", "Diagnostics without an expansion origin cannot claim source locations."
            )
        return
    source_uri = diagnostic.get("sourceUri")
    span = diagnostic.get("span")
    primary = mapping["primarySpan"]
    if (
        source_uri != primary["sourceUri"]
        or not _is_canonical_portable_source_uri(source_uri)
        or not _diagnostic_span_is_strictly_contained(span, primary)
    ):
        raise BundleValidationError(
            "HOCUS521", "Semantic diagnostic source location is not portable or contained in its origin."
        )


def _enclosing_expansion_mapping(
    pointer: str | None, mappings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if pointer is None:
        return None
    matches = [
        mapping for mapping in mappings
        if mapping["generatedPointer"] == pointer
        or mapping["generatedPointer"] == ""
        or pointer.startswith(mapping["generatedPointer"] + "/")
    ]
    return max(matches, key=lambda item: len(item["generatedPointer"]), default=None)


def _is_canonical_portable_source_uri(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 4096:
        return False
    match = _MODULE_URI_PATTERN.fullmatch(value)
    if match is None:
        return False
    encoded_path = match.group(3)
    try:
        decoded_path = unquote(encoded_path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return False
    return (
        quote(decoded_path, safe="/-._~") == encoded_path
        and decoded_path.endswith(".hocus")
        and not decoded_path.startswith("/")
        and "\\" not in decoded_path
        and ":" not in decoded_path
        and all(part not in {"", ".", ".."} for part in decoded_path.split("/"))
    )


def _diagnostic_span_is_strictly_contained(value: Any, primary: dict[str, Any]) -> bool:
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        return False
    for endpoint in ("start", "end"):
        position = value[endpoint]
        if not isinstance(position, dict) or set(position) != {"offset", "line", "column"}:
            return False
        if any(type(position[key]) is not int for key in position):
            return False
        if position["offset"] < 0 or position["line"] < 1 or position["column"] < 1:
            return False
    start, end = value["start"], value["end"]
    primary_start, primary_end = primary["start"], primary["end"]
    if not (
        primary_start["offset"] <= start["offset"] < end["offset"] <= primary_end["offset"]
        and (primary_start["line"], primary_start["column"])
        <= (start["line"], start["column"])
        < (end["line"], end["column"])
        <= (primary_end["line"], primary_end["column"])
    ):
        return False
    if start["offset"] == primary_start["offset"] and (
        start["line"], start["column"]
    ) != (primary_start["line"], primary_start["column"]):
        return False
    if end["offset"] == primary_end["offset"] and (
        end["line"], end["column"]
    ) != (primary_end["line"], primary_end["column"]):
        return False
    if start["line"] == primary_start["line"] and (
        start["offset"] - primary_start["offset"]
        != start["column"] - primary_start["column"]
    ):
        return False
    if end["line"] == primary_end["line"] and (
        primary_end["offset"] - end["offset"]
        != primary_end["column"] - end["column"]
    ):
        return False
    if start["line"] == end["line"] and (
        end["column"] - start["column"] != end["offset"] - start["offset"]
    ):
        return False
    return True


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


def _validate_expansion_map(
    value: Any, module_dependencies: dict[str, dict[str, Any]], entry_source_uri: str,
    graph: dict[str, Any], limits: dict[str, int],
) -> None:
    required = {"$schema", "kind", "schemaVersion", "graphSpecVersion", "entrySourceUri", "stacks", "mappings"}
    if not isinstance(value, dict) or set(value) != required:
        raise BundleValidationError("HOCUS520", "graphSpec.expansionMap has an invalid shape.")
    if (
        value["$schema"] != "hocuspocus://schemas/expansion-map/v1"
        or value["kind"] != "hocus_expansion_map" or value["schemaVersion"] != 1
        or value["graphSpecVersion"] != MODULE_GRAPH_SPEC_VERSION
        or value["entrySourceUri"] != entry_source_uri
    ):
        raise BundleValidationError("HOCUS520", "graphSpec.expansionMap envelope is inconsistent.")
    stacks, stack_ids = _validate_expansion_stacks(value["stacks"], module_dependencies)
    mappings = value["mappings"]
    if not isinstance(mappings, list) or len(mappings) > limits["sourceMapEntries"]:
        raise BundleValidationError("HOCUS520", "graphSpec.expansionMap.mappings must be bounded.")
    pointers: list[str] = []
    origin_ids: set[str] = set()
    for index, mapping in enumerate(mappings):
        label = f"graphSpec.expansionMap.mappings[{index}]"
        keys = {
            "originId", "generatedPointer", "originKind", "primarySpan", "relatedOrigins",
            "stackId",
        }
        if not isinstance(mapping, dict) or set(mapping) != keys:
            raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
        origin_id = _validate_expansion_mapping(mapping, label, graph, stack_ids)
        if origin_id in origin_ids:
            raise BundleValidationError("HOCUS520", f"{label}.originId is invalid or duplicated.")
        origin_ids.add(origin_id)
        pointers.append(mapping["generatedPointer"])
    _validate_expansion_coverage(pointers, mappings, stack_ids, graph)
    instance_paths = {
        tuple(frame["instanceIdPath"]) for stack in stacks for frame in stack["frames"]
    }
    if len(instance_paths) > limits["instances"]:
        raise BundleValidationError("HOCUS520", "Expansion instances exceed resolved module limits.")
    if any(len(path) > limits["instanceDepth"] for path in instance_paths):
        raise BundleValidationError("HOCUS520", "Expansion instance depth exceeds resolved module limits.")


def _validate_expansion_stacks(
    stacks: Any, module_dependencies: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(stacks, list) or len(stacks) > 10_000:
        raise BundleValidationError("HOCUS520", "graphSpec.expansionMap.stacks must be bounded.")
    stack_ids: list[str] = []
    for stack_index, stack in enumerate(stacks):
        stack_label = f"graphSpec.expansionMap.stacks[{stack_index}]"
        if not isinstance(stack, dict) or set(stack) != {"stackId", "frames"}:
            raise BundleValidationError("HOCUS520", f"{stack_label} has an invalid shape.")
        frames = stack["frames"]
        if not isinstance(frames, list) or not 1 <= len(frames) <= 64:
            raise BundleValidationError("HOCUS520", f"{stack_label}.frames must contain 1 to 64 frames.")
        for frame_index, frame in enumerate(frames):
            frame_label = f"{stack_label}.frames[{frame_index}]"
            if not isinstance(frame, dict) or set(frame) != {
                "moduleUri", "sourceDigest", "moduleName", "instanceSymbol",
                "instanceIdPath", "importSpan", "useSpan",
            }:
                raise BundleValidationError("HOCUS520", f"{frame_label} has an invalid shape.")
            uri = frame["moduleUri"]
            source_digest = _require_digest(frame["sourceDigest"], f"{frame_label}.sourceDigest", "HOCUS520")
            module = module_dependencies.get(uri) if isinstance(uri, str) else None
            if module is None or module["sourceDigest"] != source_digest:
                raise BundleValidationError("HOCUS520", f"{frame_label} does not match a locked module.")
            for field in ("moduleName", "instanceSymbol"):
                if not isinstance(frame[field], str) or not _IDENTIFIER_PATTERN.fullmatch(frame[field]):
                    raise BundleValidationError("HOCUS520", f"{frame_label}.{field} is invalid.")
            if frame["moduleName"] != module["moduleName"]:
                raise BundleValidationError("HOCUS520", f"{frame_label}.moduleName conflicts with the resolved module.")
            instance_path = frame["instanceIdPath"]
            if (
                not isinstance(instance_path, list) or len(instance_path) > 64
                or any(not isinstance(item, str) or not EXPLICIT_NODE_ID_PATTERN.fullmatch(item)
                       for item in instance_path)
            ):
                raise BundleValidationError("HOCUS520", f"{frame_label}.instanceIdPath is invalid.")
            if frame["importSpan"] is not None:
                _validate_span(frame["importSpan"], f"{frame_label}.importSpan")
            _validate_span(frame["useSpan"], f"{frame_label}.useSpan")
        stack_id = _require_digest(stack["stackId"], f"{stack_label}.stackId", "HOCUS520")
        stack_payload = {"domain": _EXPANSION_STACK_DIGEST_DOMAIN, "frames": frames}
        expected_stack_id = "sha256:" + hashlib.sha256(
            _canonical_json(stack_payload).encode("utf-8")
        ).hexdigest()
        if stack_id != expected_stack_id:
            raise BundleValidationError("HOCUS520", f"{stack_label}.stackId does not match frames.")
        stack_ids.append(stack_id)
    if stack_ids != sorted(set(stack_ids)):
        raise BundleValidationError("HOCUS520", "Expansion stacks must be uniquely sorted by stackId.")
    return stacks, stack_ids



def _validate_expansion_mapping(
    mapping: dict[str, Any], label: str, graph: dict[str, Any], stack_ids: list[str],
) -> str:
    origin_id = _require_digest(mapping["originId"], f"{label}.originId", "HOCUS520")
    pointer = mapping["generatedPointer"]
    if (
        not isinstance(pointer, str)
        or len(pointer) > 8192
        or _JSON_POINTER_PATTERN.fullmatch(pointer) is None
        or not _json_pointer_resolves(graph, pointer)
    ):
        raise BundleValidationError("HOCUS520", f"{label}.generatedPointer is invalid.")
    if mapping["originKind"] not in {"definition", "argument", "export", "synthetic"}:
        raise BundleValidationError("HOCUS520", f"{label}.originKind is invalid.")
    _validate_span(mapping["primarySpan"], f"{label}.primarySpan")
    related = mapping["relatedOrigins"]
    if not isinstance(related, list) or len(related) > 16:
        raise BundleValidationError("HOCUS520", f"{label}.relatedOrigins must be bounded.")
    for related_index, item in enumerate(related):
        related_label = f"{label}.relatedOrigins[{related_index}]"
        if not isinstance(item, dict) or set(item) != {"role", "span"} or item["role"] not in {
            "definition", "parameter_declaration", "argument", "export", "instance",
        }:
            raise BundleValidationError("HOCUS520", f"{related_label} is invalid.")
        _validate_span(item["span"], f"{related_label}.span")
    if mapping["stackId"] is not None and mapping["stackId"] not in stack_ids:
        raise BundleValidationError("HOCUS520", f"{label}.stackId references an unknown stack.")
    origin_payload = {key: mapping[key] for key in sorted(mapping) if key != "originId"}
    expected_origin_id = "sha256:" + hashlib.sha256(
        _canonical_json(origin_payload).encode("utf-8")
    ).hexdigest()
    if origin_id != expected_origin_id:
        raise BundleValidationError("HOCUS520", f"{label}.originId is invalid or duplicated.")
    return origin_id


def _validate_expansion_coverage(
    pointers: list[str], mappings: list[dict[str, Any]], stack_ids: list[str],
    graph: dict[str, Any],
) -> None:
    if pointers != sorted(set(pointers)):
        raise BundleValidationError("HOCUS520", "Expansion mappings must be uniquely sorted by generatedPointer.")
    required_pointers = _required_expansion_pointers(graph)
    if pointers != sorted(required_pointers):
        raise BundleValidationError(
            "HOCUS520", "Expansion mappings do not exactly cover the GraphSpec v0.3 origin surface.",
            details={
                "missing": sorted(required_pointers - set(pointers)),
                "unknown": sorted(set(pointers) - required_pointers),
            },
        )
    referenced_stacks = {mapping["stackId"] for mapping in mappings if mapping["stackId"] is not None}
    if referenced_stacks != set(stack_ids):
        raise BundleValidationError("HOCUS520", "Expansion stacks must be referenced exactly once or more.")


def _json_pointer_resolves(value: Any, pointer: str) -> bool:
    current = value
    if pointer == "":
        return True
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (token != "0" and token.startswith("0")):
                return False
            index = int(token)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return True
