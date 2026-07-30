"""GraphSpec and shared structural validation for compiled bundles."""

from __future__ import annotations

import json
import math
from typing import Any

from .bundle import (
    MAX_BUNDLE_DEPTH,
    MAX_BUNDLE_VALUES,
    BundleValidationError,
    _DIGEST_PATTERN,
    _GRAPH_KEYS,
    _IDENTIFIER_PATTERN,
)
from .model import (
    CONTROL_GRAPH_SPEC_VERSION,
    EXPLICIT_NODE_ID_PATTERN,
    GRAPH_SPEC_VERSION,
    LEGACY_GRAPH_SPEC_VERSION,
    MODULE_GRAPH_SPEC_VERSION,
    VALUE_GRAPH_SPEC_VERSION,
)


def required_expansion_pointers(graph: dict[str, Any]) -> set[str]:
    pointers = {""}
    pointers.update(f"/externalNodes/{index}" for index, _ in enumerate(graph["externalNodes"]))
    for node_index, node in enumerate(graph["nodes"]):
        prefix = f"/nodes/{node_index}"
        pointers.add(prefix)
        pointers.update(f"{prefix}/inputs/{index}" for index, _ in enumerate(node["inputs"]))
        pointers.update(f"{prefix}/parms/{index}" for index, _ in enumerate(node["parms"]))
    from .runtime_pointers import runtime_entity_pointers
    pointers.update(runtime_entity_pointers(graph))
    pointers.update(
        f"/editorEntities/{index}"
        for index, _ in enumerate(graph.get("editorEntities", []))
    )
    for field in ("display", "render", "output", "layout"):
        if graph[field] is not None:
            pointers.add(f"/{field}")
    return pointers


def validate_graph_spec(
    graph: dict[str, Any], *, graph_spec_version: str,
    module_dependencies: dict[str, dict[str, Any]] | None = None,
    entry_source_uri: str | None = None,
    module_limits: dict[str, int] | None = None,
    structural_only: bool = False,
) -> None:
    _validate_graph_envelope(graph, graph_spec_version, structural_only)
    symbols, mutable_symbols = _validate_external_nodes(graph)
    _validate_authored_nodes(graph, graph_spec_version, symbols, mutable_symbols)
    _validate_graph_references(graph, symbols, mutable_symbols)
    if graph_spec_version == MODULE_GRAPH_SPEC_VERSION:
        _validate_module_graph_limits(
            graph, module_dependencies or {}, entry_source_uri or "", module_limits
        )


def _validate_graph_envelope(
    graph: dict[str, Any], graph_spec_version: str, structural_only: bool,
) -> None:
    expected_keys = set(_GRAPH_KEYS)
    if graph_spec_version == VALUE_GRAPH_SPEC_VERSION:
        expected_keys.update({"editorEntities", "spareParameters", "animations"})
    if (
        not structural_only
        and graph_spec_version in {
            MODULE_GRAPH_SPEC_VERSION,
            CONTROL_GRAPH_SPEC_VERSION,
            VALUE_GRAPH_SPEC_VERSION,
        }
    ):
        expected_keys.add("expansionMap")
    if set(graph) != expected_keys:
        raise BundleValidationError("HOCUS520", "graphSpec has missing or unknown fields.")
    _validate_graph_identity(graph)
    _validate_graph_options(graph)
    _validate_graph_revision(graph)
    _validate_graph_spans(graph)
    if graph_spec_version == VALUE_GRAPH_SPEC_VERSION:
        try:
            from .editor_carrier import validate_editor_carrier
            from .runtime_carrier import validate_runtime_carrier
            validate_editor_carrier(graph["editorEntities"])
            validate_runtime_carrier(
                graph["spareParameters"], graph["animations"],
                ownership=graph["ownership"],
                node_symbols={
                    item["symbol"] for item in graph["nodes"]
                },
                forbidden_ids={
                    item["explicitId"] for item in graph["nodes"]
                    if item.get("explicitId") is not None
                } | {
                    item["explicitId"] for item in graph["editorEntities"]
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BundleValidationError(
                "HOCUS520", f"graphSpec HS7 entity carrier is invalid: {exc}"
            ) from exc


def _validate_graph_identity(graph: dict[str, Any]) -> None:
    if not isinstance(graph["name"], str) or not _IDENTIFIER_PATTERN.fullmatch(graph["name"]):
        raise BundleValidationError("HOCUS520", "graphSpec.name must be a HocusScript identifier.")
    if not isinstance(graph["target"], str) or not _is_canonical_houdini_path(graph["target"]):
        raise BundleValidationError("HOCUS520", "graphSpec.target must be a canonical absolute Houdini path.")
    category = graph["category"]
    if category is not None and (
        not isinstance(category, str) or not _IDENTIFIER_PATTERN.fullmatch(category)
    ):
        raise BundleValidationError("HOCUS520", "graphSpec.category must be an identifier or null.")


def _validate_graph_options(graph: dict[str, Any]) -> str | None:
    ownership = graph["ownership"]
    if ownership is not None and (not isinstance(ownership, str) or not ownership.strip()):
        raise BundleValidationError("HOCUS520", "graphSpec.ownership must be a non-empty string or null.")
    _validate_directives(graph)
    if graph["layout"] not in {None, "auto"}:
        raise BundleValidationError("HOCUS520", "graphSpec.layout must be auto or null.")
    if graph["mode"] not in {"merge", "reconcile"}:
        raise BundleValidationError("HOCUS520", "graphSpec.mode must be merge or reconcile.")
    if graph["mode"] == "reconcile" and ownership is None:
        raise BundleValidationError("HOCUS520", "Reconcile GraphSpecs require ownership.")
    return ownership


def _validate_graph_revision(graph: dict[str, Any]) -> None:
    revision = graph["expectedRevision"]
    if revision is not None and (type(revision) is not int or revision < 0):
        raise BundleValidationError(
            "HOCUS520", "graphSpec.expectedRevision must be a nonnegative integer or null."
        )


def _validate_graph_spans(graph: dict[str, Any]) -> None:
    validate_span(graph["span"], "graphSpec.span")
    field_spans = graph["fieldSpans"]
    allowed = {
        "languageVersion", "name", "target", "category", "mode", "expectedRevision",
        "ownership", "display", "render", "output", "layout",
    }
    if not isinstance(field_spans, dict) or "name" not in field_spans or set(field_spans) - allowed:
        raise BundleValidationError("HOCUS520", "graphSpec.fieldSpans has an invalid shape.")
    for key, span in field_spans.items():
        validate_span(span, f"graphSpec.fieldSpans.{key}")


def _validate_directives(graph: dict[str, Any]) -> None:
    for key in ("display", "render", "output"):
        value = graph[key]
        if value is not None and (
            not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value)
        ):
            raise BundleValidationError(
                "HOCUS520", f"graphSpec.{key} must be an identifier or null."
            )


def _validate_external_nodes(
    graph: dict[str, Any],
) -> tuple[set[str], set[str]]:
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
        path = external["path"]
        if not isinstance(path, str) or not _is_canonical_houdini_path(path):
            raise BundleValidationError(
                "HOCUS520", f"{label}.path must be a canonical absolute Houdini path."
            )
        target_prefix = graph["target"].rstrip("/") + "/"
        if path != graph["target"] and not path.startswith(target_prefix):
            raise BundleValidationError("HOCUS520", f"{label}.path is outside the graph target.")
        if not isinstance(external["adopted"], bool):
            raise BundleValidationError("HOCUS520", f"{label}.adopted must be a boolean.")
        if external["adopted"]:
            mutable_symbols.add(external["symbol"])
        validate_span(external["span"], f"{label}.span")
        _validate_optional_field_spans(external, label, {"symbol", "path"})
    return symbols, mutable_symbols


def _validate_authored_nodes(
    graph: dict[str, Any], graph_spec_version: str,
    symbols: set[str], mutable_symbols: set[str],
) -> None:
    explicit_ids: set[str] = set()
    for index, node in enumerate(graph["nodes"]):
        label = f"graphSpec.nodes[{index}]"
        _validate_node_shape(node, label, graph_spec_version)
        _validate_symbol(node["symbol"], symbols, label)
        mutable_symbols.add(node["symbol"])
        _validate_explicit_id(node.get("explicitId"), label, graph_spec_version, explicit_ids)
        if not isinstance(node["typeName"], str) or not node["typeName"].strip() or len(node["typeName"]) > 4096:
            raise BundleValidationError("HOCUS520", f"{label}.typeName must be a non-empty string.")
        if not isinstance(node["inputs"], list) or not isinstance(node["parms"], list):
            raise BundleValidationError("HOCUS520", f"{label} inputs and parms must be arrays.")
        validate_span(node["span"], f"{label}.span")
        expected_spans = {"symbol", "typeName"}
        if node.get("explicitId") is not None:
            expected_spans.add("explicitId")
        _validate_optional_field_spans(node, label, expected_spans)
        _validate_node_inputs(node, label, graph_spec_version)
        _validate_node_parms(
            node, label, tagged_values=graph_spec_version == VALUE_GRAPH_SPEC_VERSION
        )


def _validate_node_shape(node: Any, label: str, graph_spec_version: str) -> None:
    required = {"symbol", "typeName", "inputs", "parms", "span"}
    optional = {"fieldSpans"}
    if graph_spec_version in {
        GRAPH_SPEC_VERSION,
        MODULE_GRAPH_SPEC_VERSION,
        CONTROL_GRAPH_SPEC_VERSION,
        VALUE_GRAPH_SPEC_VERSION,
    }:
        optional.add("explicitId")
    if not isinstance(node, dict) or not required.issubset(node) or set(node) - required - optional:
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")


def _validate_explicit_id(
    explicit_id: Any, label: str, graph_spec_version: str, seen: set[str],
) -> None:
    if graph_spec_version == LEGACY_GRAPH_SPEC_VERSION and explicit_id is not None:
        raise BundleValidationError("HOCUS520", f"{label}.explicitId requires GraphSpec v0.2.")
    if explicit_id is None:
        return
    if not isinstance(explicit_id, str) or not EXPLICIT_NODE_ID_PATTERN.fullmatch(explicit_id):
        raise BundleValidationError("HOCUS520", f"{label}.explicitId is invalid.")
    if explicit_id in seen:
        raise BundleValidationError("HOCUS520", f"{label}.explicitId must be unique.")
    seen.add(explicit_id)


def _validate_node_inputs(
    node: dict[str, Any], label: str, graph_spec_version: str,
) -> None:
    identities: set[tuple[str, Any]] = set()
    for index, input_spec in enumerate(node["inputs"]):
        _validate_input(
            input_spec, f"{label}.inputs[{index}]",
            named=graph_spec_version == VALUE_GRAPH_SPEC_VERSION,
        )
        key = ("name", input_spec["name"]) if "name" in input_spec else ("index", input_spec["index"])
        if key in identities:
            raise BundleValidationError("HOCUS520", f"{label} has duplicate input selectors.")
        identities.add(key)


def _validate_node_parms(
    node: dict[str, Any], label: str, *, tagged_values: bool,
) -> None:
    identities: set[str] = set()
    for index, parm in enumerate(node["parms"]):
        _validate_parm(
            parm, f"{label}.parms[{index}]", tagged_values=tagged_values
        )
        if parm["name"] in identities:
            raise BundleValidationError(
                "HOCUS520", f"{label} has duplicate parameter assignments."
            )
        identities.add(parm["name"])


def _validate_graph_references(
    graph: dict[str, Any], symbols: set[str], mutable_symbols: set[str],
) -> None:
    for node in graph["nodes"]:
        for input_spec in node["inputs"]:
            if input_spec["source"]["symbol"] not in symbols:
                raise BundleValidationError(
                    "HOCUS520", "GraphSpec input references an unknown symbol."
                )
    for directive in ("display", "render", "output"):
        symbol = graph[directive]
        if symbol is not None and symbol not in symbols:
            raise BundleValidationError(
                "HOCUS520", f"graphSpec.{directive} references an unknown symbol."
            )
        if symbol is not None and symbol not in mutable_symbols:
            raise BundleValidationError(
                "HOCUS520", f"graphSpec.{directive} targets a read-only existing symbol."
            )
    if graph.get("graphSpecVersion") == VALUE_GRAPH_SPEC_VERSION:
        try:
            from .editor_carrier import validate_editor_carrier_references
            validate_editor_carrier_references(
                graph["editorEntities"],
                node_symbols=symbols,
                mutable_node_symbols=mutable_symbols,
            )
            if {
                item["explicitId"] for item in graph["editorEntities"]
            } & {
                item["explicitId"] for item in graph["nodes"]
                if item.get("explicitId") is not None
            }:
                raise ValueError("editor entity ID collides with a node ID")
            from .editor_carrier import validate_dot_route_conflicts
            validate_dot_route_conflicts(graph["editorEntities"], graph)
        except ValueError as exc:
            raise BundleValidationError("HOCUS520", str(exc)) from exc


def _validate_module_graph_limits(
    graph: dict[str, Any], dependencies: dict[str, dict[str, Any]],
    entry_source_uri: str, module_limits: dict[str, int] | None,
) -> None:
    limits = module_limits or {
        "expandedNodes": 10_000, "sourceMapEntries": 100_000,
        "instances": 4096, "instanceDepth": 64, "aggregateCodeBytes": 4_194_304,
    }
    if len(graph["nodes"]) > limits["expandedNodes"]:
        raise BundleValidationError("HOCUS520", "Expanded nodes exceed resolved module limits.")
    code_bytes = sum(
        len(value["body"].encode("utf-8"))
        for node in graph["nodes"]
        for parm in node["parms"]
        for value in _walk_graph_values(parm["value"])
        if isinstance(value, dict) and value.get("kind") == "code"
    )
    if code_bytes > limits["aggregateCodeBytes"]:
        raise BundleValidationError("HOCUS520", "Expanded code exceeds resolved module limits.")
    from .bundle import _validate_expansion_map
    _validate_expansion_map(graph["expansionMap"], dependencies, entry_source_uri, graph, limits)


def _walk_graph_values(value: Any):
    stack = [value]
    while stack:
        item = stack.pop()
        yield item
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _is_canonical_houdini_path(path: str) -> bool:
    if path == "/":
        return True
    if not path.startswith("/") or path.endswith("/"):
        return False
    segments = path.split("/")[1:]
    return bool(segments) and all(segment not in {"", ".", ".."} for segment in segments)


def _validate_symbol(value: Any, symbols: set[str], label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value) or value in symbols:
        raise BundleValidationError(
            "HOCUS520", f"{label}.symbol must be a unique identifier."
        )
    symbols.add(value)


def _validate_input(value: Any, label: str, *, named: bool) -> None:
    if not isinstance(value, dict):
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    selector = "name" if "name" in value else "index"
    allowed = {selector, "source", "span"}
    if set(value) not in (allowed, allowed | {"fieldSpans"}) or (
        selector == "name" and not named
    ):
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    selected = value[selector]
    if selector == "index" and (type(selected) is not int or selected < 0):
        raise BundleValidationError("HOCUS520", f"{label}.index must be a nonnegative integer.")
    if selector == "name" and (
        not isinstance(selected, str) or not selected or len(selected) > 256
    ):
        raise BundleValidationError("HOCUS520", f"{label}.name must be a non-empty bounded string.")
    source = value["source"]
    if not isinstance(source, dict):
        raise BundleValidationError("HOCUS520", f"{label}.source has an invalid shape.")
    output_selector = "outputName" if "outputName" in source else "outputIndex"
    source_allowed = {"symbol", output_selector, "span"}
    if set(source) not in (source_allowed, source_allowed | {"fieldSpans"}) or (
        output_selector == "outputName" and not named
    ):
        raise BundleValidationError("HOCUS520", f"{label}.source has an invalid shape.")
    if not isinstance(source["symbol"], str) or not _IDENTIFIER_PATTERN.fullmatch(source["symbol"]):
        raise BundleValidationError("HOCUS520", f"{label}.source.symbol must be an identifier.")
    output = source[output_selector]
    if output_selector == "outputIndex" and (type(output) is not int or output < 0):
        raise BundleValidationError("HOCUS520", f"{label}.source.outputIndex must be nonnegative.")
    if output_selector == "outputName" and (
        not isinstance(output, str) or not output or len(output) > 256
    ):
        raise BundleValidationError("HOCUS520", f"{label}.source.outputName is invalid.")
    validate_span(source["span"], f"{label}.source.span")
    validate_span(value["span"], f"{label}.span")
    _validate_optional_field_spans(source, f"{label}.source", {"symbol", output_selector})
    _validate_optional_field_spans(value, label, {selector})


def _validate_parm(value: Any, label: str, *, tagged_values: bool) -> None:
    if not isinstance(value, dict) or set(value) not in (
        {"name", "value", "span"}, {"name", "value", "span", "fieldSpans"},
    ):
        raise BundleValidationError("HOCUS520", f"{label} has an invalid shape.")
    if not isinstance(value["name"], str) or not _IDENTIFIER_PATTERN.fullmatch(value["name"]):
        raise BundleValidationError("HOCUS520", f"{label}.name must be an identifier.")
    _validate_value(value["value"], f"{label}.value", tagged_values=tagged_values)
    validate_span(value["span"], f"{label}.span")
    _validate_optional_field_spans(value, label, {"name"})


def _validate_optional_field_spans(
    value: dict[str, Any], label: str, expected: set[str],
) -> None:
    if "fieldSpans" not in value:
        return
    field_spans = value["fieldSpans"]
    if not isinstance(field_spans, dict) or set(field_spans) != expected:
        raise BundleValidationError("HOCUS520", f"{label}.fieldSpans has an invalid shape.")
    for key, span in field_spans.items():
        validate_span(span, f"{label}.fieldSpans.{key}")


def _validate_value(value: Any, label: str, *, tagged_values: bool = False) -> None:
    if not isinstance(value, dict) or "kind" not in value:
        raise BundleValidationError("HOCUS520", f"{label} must be a typed value object.")
    kind = value["kind"]
    if kind == "literal" and set(value) == {"kind", "value", "span"}:
        literal = value["value"]
        if literal is not None and not isinstance(literal, (str, bool, int, float)):
            raise BundleValidationError("HOCUS520", f"{label}.value is not a scalar literal.")
        validate_span(value["span"], f"{label}.span")
        return
    if kind == "array" and set(value) == {"kind", "items", "span"} and isinstance(value["items"], list):
        for index, item in enumerate(value["items"]):
            _validate_value(
                item, f"{label}.items[{index}]", tagged_values=tagged_values
            )
        validate_span(value["span"], f"{label}.span")
        return
    if kind == "code" and set(value) in (
        {"kind", "language", "body", "span"},
        {"kind", "language", "body", "span", "bodySpan", "offsetMap"},
    ):
        if value["language"] not in {"vex", "python", "hscript"} or not isinstance(value["body"], str):
            raise BundleValidationError(
                "HOCUS520", f"{label} code language must be vex/python/hscript and body must be a string."
            )
        validate_span(value["span"], f"{label}.span")
        if "bodySpan" in value:
            validate_span(value["bodySpan"], f"{label}.bodySpan")
            _validate_code_offset_map(value["offsetMap"], value["body"], value["bodySpan"], label)
        return
    if tagged_values:
        from .value_carrier_validation import validate_tagged_graph_value

        if validate_tagged_graph_value(
            value, label, validate_span=validate_span,
            validate_value=lambda item, child_label: _validate_value(
                item, child_label, tagged_values=True
            ),
        ):
            return
    raise BundleValidationError("HOCUS520", f"{label} has an invalid typed value shape.")


def _validate_code_offset_map(
    value: Any, body: str, body_span: dict[str, Any], label: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {"bodyLength", "checkpoints"}:
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap has an invalid shape.")
    if type(value["bodyLength"]) is not int or value["bodyLength"] != len(body):
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap body length is inconsistent.")
    checkpoints = value["checkpoints"]
    if not isinstance(checkpoints, list) or not checkpoints:
        raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoints must be non-empty.")
    normalized: list[tuple[int, int]] = []
    previous = (-1, -1)
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict) or set(checkpoint) != {"bodyOffset", "sourceOffset"}:
            raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoint has an invalid shape.")
        pair = (checkpoint["bodyOffset"], checkpoint["sourceOffset"])
        if any(type(item) is not int or item < 0 for item in pair):
            raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoints must be monotonic integers.")
        if previous != (-1, -1) and (pair[0] <= previous[0] or pair[1] - previous[1] < pair[0] - previous[0]):
            raise BundleValidationError("HOCUS520", f"{label}.offsetMap checkpoints are not physically possible.")
        previous = pair
        normalized.append(pair)
    endpoints = (body_span["start"]["offset"], body_span["end"]["offset"])
    if normalized[0] != (0, endpoints[0]) or normalized[-1] != (len(body), endpoints[1]):
        raise BundleValidationError(
            "HOCUS520", f"{label}.offsetMap endpoints are inconsistent with bodySpan."
        )


def validate_span(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sourceUri", "start", "end"}:
        raise BundleValidationError("HOCUS520", f"{label} has an invalid span shape.")
    if not isinstance(value["sourceUri"], str) or not value["sourceUri"] or len(value["sourceUri"]) > 1024:
        raise BundleValidationError(
            "HOCUS520", f"{label}.sourceUri must be a bounded non-empty string."
        )
    for endpoint in ("start", "end"):
        position = value[endpoint]
        if not isinstance(position, dict) or set(position) != {"offset", "line", "column"}:
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} has an invalid position shape.")
        if any(type(position[key]) is not int for key in position):
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} values must be integers.")
        if position["offset"] < 0 or position["line"] < 1 or position["column"] < 1:
            raise BundleValidationError("HOCUS520", f"{label}.{endpoint} values are out of range.")
    start, end = value["start"], value["end"]
    if end["offset"] < start["offset"] or (end["line"], end["column"]) < (start["line"], start["column"]):
        raise BundleValidationError("HOCUS520", f"{label} end precedes its start.")


def validate_declared_source_uris(value: Any, allowed: set[str]) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if {"sourceUri", "start", "end"}.issubset(item) and item["sourceUri"] not in allowed:
                raise BundleValidationError(
                    "HOCUS520", "GraphSpec source span references an undeclared source URI.",
                    details={"sourceUri": item["sourceUri"]},
                )
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def required_capabilities(graph_spec: dict[str, Any]) -> list[str]:
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


def validate_complexity(value: Any, *, max_values: int = MAX_BUNDLE_VALUES) -> None:
    count = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > max_values or depth > MAX_BUNDLE_DEPTH:
            raise BundleValidationError(
                "HOCUS519", "Compiled bundle exceeds structural complexity limits."
            )
        if isinstance(item, float) and not math.isfinite(item):
            raise BundleValidationError(
                "HOCUS519", "Compiled bundle contains a non-finite number."
            )
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)


def require_digest(value: Any, label: str, code: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise BundleValidationError(code, f"{label} must be a lowercase SHA-256 digest.")
    return value


def require_equal(payload: dict[str, Any], key: str, expected: Any, code: str) -> None:
    if payload.get(key) != expected:
        raise BundleValidationError(code, f"{key} has an unsupported value.")


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
