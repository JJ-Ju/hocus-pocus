"""Fixture construction and verification for installed HS7 family acceptance."""

from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.live.ops.document_network_families import (
    network_family_policy,
    resolve_network_family,
)


SUPPORTED_ROOTS = {
    "sop": "/obj/hs7_family_sop",
    "mat": "/mat",
    "lop": "/stage",
    "top": "/tasks/hs7_family_top",
}
UNSUPPORTED_CATEGORIES = {
    "rop": ("Driver", "/out"),
    "dop": ("Dop", "/obj/hs7_family_dop"),
    "cop": ("Cop2", "/img"),
    "chop": ("Chop", "/ch"),
}
_SAFE_FIXTURE_TYPES = {
    # SOP Split supplies a real nonzero output.  It is an opaque HDA network,
    # while Blast supplies a string parameter whose raw Houdini value
    # round-trips without the on/off aliases used by toggle parameters.
    "sop": (("split", "blast", "group"),),
    "mat": (
        ("abs", "compare", "cmp"),
    ),
    "lop": (("null", "cache", "behavior"),),
    "top": (("null", "attributeclassify", "attribname"),),
}


class FixtureUnavailable(RuntimeError):
    def __init__(self, family: str, reason: str, **details: Any):
        super().__init__(reason)
        self.evidence = {
            "family": family,
            "reason": reason,
            "details": details,
        }


@dataclass(frozen=True, slots=True)
class FamilyFixture:
    family: str
    root_path: str
    category: str
    source_type_name: str
    destination_type_name: str
    source_is_network: bool
    destination_is_network: bool
    input_index: int
    output_index: int
    input_name: str | None
    output_name: str | None
    parm_name: str
    parm_default: Any
    parm_value: Any

    @property
    def source_path(self) -> str:
        return f"{self.root_path.rstrip('/')}/hs7_{self.family}_source"

    @property
    def destination_path(self) -> str:
        return f"{self.root_path.rstrip('/')}/hs7_{self.family}_dest"


def _safe_call(target: Any, name: str, default: Any = None) -> Any:
    method = getattr(target, name, None)
    if not callable(method):
        return default
    try:
        return method()
    except Exception:
        return default


def _connector_name(node_type: Any, direction: str) -> str | None:
    names = _safe_call(node_type, direction + "Names", ())
    if not isinstance(names, (tuple, list)) or not names:
        return None
    value = str(names[0] or "").strip()
    return value or None


def select_family_fixture(
    hou_module: Any,
    operations: Any,
    family: str,
) -> FamilyFixture:
    root_path = SUPPORTED_ROOTS[family]
    root = hou_module.node(root_path)
    if root is None:
        raise FixtureUnavailable(
            family, "required Houdini network root is unavailable",
            rootPath=root_path,
        )
    category = _safe_call(root, "childTypeCategory")
    category_name = str(_safe_call(category, "name", "") or "").strip()
    resolved = operations._document_network_family(root_path, category_name)
    if resolved != family:
        raise FixtureUnavailable(
            family, "live child category resolved to another network family",
            rootPath=root_path,
            childCategory=category_name,
            resolvedFamily=resolved,
        )
    node_types = _safe_call(category, "nodeTypes", {})
    if not isinstance(node_types, dict):
        raise FixtureUnavailable(
            family, "child category did not expose a node-type mapping",
            rootPath=root_path,
            childCategory=category_name,
        )
    selection = next(
        (
            item for item in _SAFE_FIXTURE_TYPES[family]
            if item[0] in node_types and item[1] in node_types
        ),
        None,
    )
    if selection is None:
        raise FixtureUnavailable(
            family, "no approved fixed-port fixture operator is installed",
            approvedTypes=[
                {"source": source, "destination": dest, "parameter": parm}
                for source, dest, parm in _SAFE_FIXTURE_TYPES[family]
            ],
            availableTypes=sorted(node_types)[:32],
        )
    source_alias, destination_alias, parameter_name = selection
    source_type = node_types[source_alias]
    destination_type = node_types[destination_alias]
    source_name = str(_safe_call(source_type, "name", source_alias) or "").strip()
    destination_name = str(
        _safe_call(destination_type, "name", destination_alias) or ""
    ).strip()
    selected_types = {
        source_name: source_type,
        destination_name: destination_type,
    }
    live_bounds = {
        name: (
            _safe_call(selected_types[name], "maxNumInputs", -1),
            _safe_call(selected_types[name], "maxNumOutputs", -1),
        )
        for name in {source_name, destination_name}
    }
    if any(
        not isinstance(maximum_inputs, int)
        or not isinstance(maximum_outputs, int)
        or not 1 <= maximum_inputs <= 64
        or not 1 <= maximum_outputs <= 64
        for maximum_inputs, maximum_outputs in live_bounds.values()
    ):
        raise FixtureUnavailable(
            family, "approved operator is not a bounded fixed-port fixture",
            nodeTypes=[source_name, destination_name],
            liveBounds={
                name: {"maxInputs": bounds[0], "maxOutputs": bounds[1]}
                for name, bounds in live_bounds.items()
            },
        )
    catalog_operators = {
        item.qualified_name: item
        for item in operations._catalog.operators
        if item.category == category_name
        and item.qualified_name in {source_name, destination_name}
    }
    source_operator = catalog_operators.get(source_name)
    destination_operator = catalog_operators.get(destination_name)
    if source_operator is None or destination_operator is None:
        raise FixtureUnavailable(
            family,
            "approved operator is absent from the exact live catalog",
            nodeTypes=[source_name, destination_name],
            childCategory=category_name,
        )
    source_outputs = _fixed_connector_layout(source_operator.outputs)
    destination_inputs = _fixed_connector_layout(destination_operator.inputs)
    source_inputs = _fixed_connector_layout(source_operator.inputs)
    destination_outputs = _fixed_connector_layout(destination_operator.outputs)
    parameter = next(
        (
            item
            for item in destination_operator.parameters
            if item.token == parameter_name
            and _fixture_parameter((item,)) is not None
        ),
        None,
    )
    if (
        not source_inputs
        or not source_outputs
        or not destination_inputs
        or not destination_outputs
        or parameter is None
    ):
        raise FixtureUnavailable(
            family,
            "approved fixture lacks an exact fixed connector layout or reversible parameter",
            sourceType=source_name,
            destinationType=destination_name,
            fixedInputs=[item.index for item in destination_inputs],
            fixedOutputs=[item.index for item in source_outputs],
            parameter=parameter.token if parameter is not None else None,
        )
    input_connector = min(destination_inputs, key=lambda item: item.index)
    output_connector = max(source_outputs, key=lambda item: item.index)
    parm_value = _alternate_value(parameter)
    return FamilyFixture(
        family=family,
        root_path=root_path,
        category=category_name,
        source_type_name=source_name,
        destination_type_name=destination_name,
        source_is_network=_instance_is_network(root, source_name, "source"),
        destination_is_network=_instance_is_network(
            root, destination_name, "destination",
        ),
        input_index=input_connector.index,
        output_index=output_connector.index,
        input_name=input_connector.name,
        output_name=output_connector.name,
        parm_name=parameter.token,
        parm_default=parameter.default,
        parm_value=parm_value,
    )


def _instance_is_network(root: Any, type_name: str, role: str) -> bool:
    node = None
    try:
        node = root.createNode(
            type_name,
            node_name=f"__hs7_shape_{role}__",
            run_init_scripts=False,
            load_contents=False,
            exact_type_name=True,
        )
        return bool(node.isNetwork())
    except Exception as exc:
        raise FixtureUnavailable(
            resolve_network_family(root.path(), _safe_call(
                _safe_call(root, "childTypeCategory"), "name", "",
            )),
            "approved fixture network shape could not be inspected safely",
            nodeType=type_name,
            role=role,
            errorType=type(exc).__name__,
        ) from exc
    finally:
        if node is not None:
            node.destroy()


def _fixed_connector_layout(connectors: Any) -> list[Any]:
    items = list(connectors)
    if not items or any(
        type(item.index) is not int
        or item.index < 0
        or item.cardinality not in {"one", "optional"}
        or (item.name is not None and not isinstance(item.name, str))
        for item in items
    ) or len({item.index for item in items}) != len(items):
        return []
    return items


def _fixture_parameter(parameters: Any) -> Any | None:
    return next(
        (
            item
            for item in parameters
            if item.assignable
            and item.tuple_size == 1
            and item.value_type in {"bool", "int", "float", "string", "menu"}
            and item.default is not None
            and _alternate_value(item) != item.default
        ),
        None,
    )


def _alternate_value(parameter: Any) -> Any:
    value = parameter.default
    if parameter.value_type == "bool":
        return not value
    if parameter.value_type == "menu":
        return next(
            (item.token for item in parameter.menu if item.token != value),
            value,
        )
    if parameter.value_type == "string":
        return str(value) + "_hs7"
    if parameter.value_type == "int":
        candidates = (int(value) + 1, int(value) - 1)
        return next(
            (item for item in candidates if _inside_range(parameter, item)),
            value,
        )
    if parameter.value_type == "float":
        candidates = (float(value) + 1.0, float(value) - 1.0)
        return next(
            (item for item in candidates if _inside_range(parameter, item)),
            value,
        )
    return value


def _inside_range(parameter: Any, value: int | float) -> bool:
    constraint = parameter.range
    if constraint is None:
        return True
    if constraint.minimum is not None:
        if value < constraint.minimum or (
            value == constraint.minimum and not constraint.minimum_inclusive
        ):
            return False
    if constraint.maximum is not None:
        if value > constraint.maximum or (
            value == constraint.maximum and not constraint.maximum_inclusive
        ):
            return False
    return True


def _fixture_node(
    fixture: FamilyFixture,
    *,
    source: bool,
) -> dict[str, Any]:
    role = "source" if source else "dest"
    path = fixture.source_path if source else fixture.destination_path
    is_network = (
        fixture.source_is_network
        if source
        else fixture.destination_is_network
    )
    result = {
        "uid": f"node:hs7:{fixture.family}:{role}",
        "name": path.rsplit("/", 1)[-1],
        "typeName": (
            fixture.source_type_name
            if source
            else fixture.destination_type_name
        ),
        "category": fixture.category,
        "path": path,
        "parentPath": fixture.root_path,
        "isNetwork": is_network,
        "position": [0.0 if source else 2.0, 0.0],
        "flags": {
            "display": fixture.family in {"sop", "lop", "top"} and not source,
            "render": fixture.family in {"sop", "top"} and not source,
            "bypass": False,
            "template": False,
        },
        "metadata": {"hs7Fixture": True},
    }
    if is_network:
        result["subnetworkDocumentId"] = f"network:{path}"
    return result


def build_fixture_target(
    baseline: dict[str, Any],
    fixture: FamilyFixture,
) -> dict[str, Any]:
    target = copy.deepcopy(baseline)
    source = _fixture_node(fixture, source=True)
    destination = _fixture_node(fixture, source=False)
    target["nodes"].extend((source, destination))
    target.setdefault("ports", []).extend((
        {
            "uid": f"port:{source['uid']}:output:{fixture.output_index}",
            "nodeUid": source["uid"],
            "direction": "output",
            "name": fixture.output_name or "",
            "index": fixture.output_index,
            "kind": "data",
            "metadata": {},
        },
        {
            "uid": f"port:{destination['uid']}:input:{fixture.input_index}",
            "nodeUid": destination["uid"],
            "direction": "input",
            "name": fixture.input_name or "",
            "index": fixture.input_index,
            "kind": "data",
            "metadata": {},
        },
    ))
    edge = {
        "uid": f"edge:data:{destination['uid']}:{fixture.input_index}",
        "kind": "data",
        "from": {"nodeUid": source["uid"], "portIndex": fixture.output_index},
        "to": {"nodeUid": destination["uid"], "portIndex": fixture.input_index},
        "metadata": {"connectionOrder": 0},
    }
    if fixture.output_name:
        edge["from"]["portName"] = fixture.output_name
    if fixture.input_name:
        edge["to"]["portName"] = fixture.input_name
    target["edges"].append(edge)
    target["parameterBindings"].append({
        "uid": f"binding:{destination['uid']}:{fixture.parm_name}",
        "nodeUid": destination["uid"],
        "parmName": fixture.parm_name,
        "valueMode": "literal",
        "value": fixture.parm_value,
        "metadata": {"hs7Fixture": True},
    })
    if fixture.family == "sop":
        root_uid = next(
            node["uid"]
            for node in target["nodes"]
            if node["path"] == fixture.root_path
        )
        target["edges"].append({
            "uid": f"edge:output:{root_uid}",
            "kind": "output_flag",
            "from": {"nodeUid": destination["uid"]},
            "to": {"nodeUid": root_uid},
            "metadata": {},
        })
    target["diagnostics"] = []
    return target


def fixture_source(
    fixture: FamilyFixture,
    *,
    mode: str,
    include_connection: bool,
    include_parameter: bool,
) -> str:
    source_id = f"node:hs7:{fixture.family}:source"
    dest_id = f"node:hs7:{fixture.family}:dest"
    body = []
    if include_connection:
        body.append(
            f"    input[{fixture.input_index}] = "
            f"hs7_{fixture.family}_source.output[{fixture.output_index}];"
        )
    if include_parameter:
        body.append(
            f"    {fixture.parm_name} = {_source_literal(fixture.parm_value)};"
        )
    output = (
        f"\n  display = hs7_{fixture.family}_dest;"
        if fixture.family in {"sop", "lop", "top"} else ""
    )
    if fixture.family in {"sop", "top"}:
        output += f"\n  render = hs7_{fixture.family}_dest;"
    if fixture.family == "sop":
        output += f"\n  output = hs7_{fixture.family}_dest;"
    return (
        "hocus 0.1;\n\n"
        f"graph hs7_{fixture.family} {{\n"
        f"  target {json.dumps(fixture.root_path)};\n"
        f"  category {fixture.category};\n"
        f"  mode {mode};\n"
        f"  ownership {json.dumps(f'hs7.family.{fixture.family}')};\n"
        f"  node hs7_{fixture.family}_source @id({json.dumps(source_id)}): "
        f"{json.dumps(fixture.source_type_name)} {{}}\n"
        f"  node hs7_{fixture.family}_dest @id({json.dumps(dest_id)}): "
        f"{json.dumps(fixture.destination_type_name)} {{\n"
        + ("\n".join(body) + "\n" if body else "")
        + "  }\n"
        + output
        + "\n}\n"
    )


def _source_literal(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def structural_signature(
    document: dict[str, Any],
    fixture: FamilyFixture,
) -> dict[str, Any]:
    fixture_nodes = {
        str(node.get("uid")): node
        for node in document.get("nodes", [])
        if str(node.get("path", "")) in {
            fixture.source_path, fixture.destination_path,
        }
    }
    fixture_uids = set(fixture_nodes)
    edges = [
        {
            "uid": edge.get("uid"),
            "kind": edge.get("kind"),
            "from": copy.deepcopy(edge.get("from")),
            "to": copy.deepcopy(edge.get("to")),
        }
        for edge in document.get("edges", [])
        if isinstance(edge, dict)
        and (
            str((edge.get("from") or {}).get("nodeUid")) in fixture_uids
            or str((edge.get("to") or {}).get("nodeUid")) in fixture_uids
        )
    ]
    return {
        "family": (document.get("metadata") or {}).get("networkFamily"),
        "nodes": sorted(
            (
                uid,
                node.get("path"),
                node.get("typeName"),
                node.get("category"),
            )
            for uid, node in fixture_nodes.items()
        ),
        "edges": sorted(edges, key=lambda item: str(item["uid"])),
        "bindings": sorted(
            (
                item.get("uid"),
                item.get("parmName"),
                item.get("value"),
            )
            for item in document.get("parameterBindings", [])
            if isinstance(item, dict)
            and str(item.get("nodeUid")) in fixture_uids
        ),
    }


def assert_zero_cooks(hou_module: Any, fixture: FamilyFixture) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (fixture.source_path, fixture.destination_path):
        node = hou_module.node(path)
        if node is None:
            raise FixtureUnavailable(
                fixture.family, "applied fixture node is absent", path=path,
            )
        count = _safe_call(node, "cookCount", None)
        if not isinstance(count, int):
            raise FixtureUnavailable(
                fixture.family, "fixture node does not expose cookCount",
                path=path,
            )
        counts[path] = count
    if any(count != 0 for count in counts.values()):
        raise FixtureUnavailable(
            fixture.family, "fixture caused a Houdini cook",
            cookCounts=counts,
        )
    return counts


def unsupported_policy_evidence(operations: Any) -> list[dict[str, Any]]:
    evidence = []
    for family, (category, path) in UNSUPPORTED_CATEGORIES.items():
        resolved = resolve_network_family(None, path, category)
        policy = network_family_policy(resolved)
        if resolved != family or policy.structural_indexed_apply:
            raise RuntimeError(
                f"Unsupported family policy unexpectedly admitted {family}."
            )
        try:
            operations._hocus_require_network_family_policy(
                {"networkFamily": family}
            )
        except JsonRpcError as exc:
            diagnostic = (
                exc.data.get("diagnosticCode")
                if isinstance(exc.data, dict) else None
            )
            if diagnostic != "HOCUS741":
                raise RuntimeError(
                    f"Unsupported {family} rejection used {diagnostic!r}."
                ) from exc
            evidence.append({
                "family": family,
                "category": category,
                "resolvedFamily": resolved,
                "diagnosticCode": diagnostic,
            })
        else:
            raise RuntimeError(f"Unsupported family {family} was admitted.")
    return evidence


def installed_module_receipt(
    repository_root: Path,
    installed_root: Path,
    module_name: str,
) -> dict[str, str]:
    module = importlib.import_module(module_name)
    installed_path = Path(inspect.getfile(module)).resolve()
    relative = installed_path.relative_to(installed_root)
    repository_path = repository_root / relative
    installed_digest = hashlib.sha256(installed_path.read_bytes()).hexdigest()
    repository_digest = hashlib.sha256(repository_path.read_bytes()).hexdigest()
    if installed_digest != repository_digest:
        raise RuntimeError(f"Installed HS7 module is stale: {module_name}.")
    return {
        "module": module_name,
        "relativePath": relative.as_posix(),
        "digest": "sha256:" + installed_digest,
    }
