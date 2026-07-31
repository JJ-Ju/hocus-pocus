"""Selective reconcile cleanup for retained managed document nodes."""

from __future__ import annotations

from typing import Any


def protected_owned_dependencies(
    document: dict[str, Any],
    ownership: str,
    preserved_node_paths: set[str],
    retained_node_uids: set[str],
) -> tuple[list[tuple[str, int, Any]], set[str]]:
    """Locate artist state that requires an omitted owned node to be retained."""

    removed_nodes = removed_owned_node_uids(
        document, ownership, preserved_node_paths, retained_node_uids,
    )
    references: list[tuple[str, int, Any]] = []
    blocked_nodes: set[str] = set()
    for field in ("edges", "parameterBindings", "codeBlobs"):
        for index, item in enumerate(document[field]):
            if _owner(item) == ownership or _is_default_observation(item):
                continue
            referenced = {
                item.get("nodeUid"),
                item.get("from", {}).get("nodeUid"),
                item.get("to", {}).get("nodeUid"),
                item.get("target", {}).get("nodeUid"),
            } & removed_nodes
            if referenced:
                references.append((field, index, item.get("uid")))
                blocked_nodes.update(referenced)
    return references, blocked_nodes


def reconcile_owned_state(
    document: dict[str, Any],
    ownership: str,
    preserved_node_paths: set[str],
    retained_node_uids: set[str],
    protected_node_uids: set[str] | None = None,
) -> list[str]:
    """Remove prior managed state while preserving retained nodes and artist fields."""

    protected = protected_node_uids or set()
    nodes = document["nodes"]
    retained = {
        item["uid"]: item
        for item in nodes
        if _owner(item) == ownership and item.get("uid") in retained_node_uids
    }
    manifests: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for uid, node in retained.items():
        manifest = validated_managed_fields(node, uid)
        if manifest is None:
            missing.append(str(uid))
        else:
            manifests[uid] = manifest
            _reset_managed_flags(node, manifest)

    removed_entities = [
        item
        for field in ("nodes", "ports", "edges", "parameterBindings", "codeBlobs")
        for item in document.get(field, [])
        if isinstance(item, dict)
        and _owner(item) == ownership
        and not _references_node(item, protected)
        and not (
            field == "nodes"
            and (
                item.get("path") in preserved_node_paths
                or item.get("uid") in retained_node_uids
            )
        )
    ]
    missing.extend(
        str(item.get("uid", ""))
        for item in removed_entities
        if _source_map(item) is None
    )
    removed_nodes = {
        item["uid"]
        for item in nodes
        if _owner(item) == ownership
        and item.get("path") not in preserved_node_paths
        and item.get("uid") not in retained_node_uids
        and item.get("uid") not in protected
    }
    document["nodes"] = [
        item for item in nodes if item.get("uid") not in removed_nodes
    ]

    removed_edges, removed_port_keys = _removed_connections(
        document["edges"], ownership, removed_nodes, manifests, protected,
    )
    document["edges"] = [
        item for item in document["edges"] if item.get("uid") not in removed_edges
    ]
    document["ports"] = [
        item
        for item in document.get("ports", [])
        if item.get("nodeUid") not in removed_nodes
        and (item.get("nodeUid") in protected or _owner(item) != ownership)
        and (
            item.get("nodeUid"),
            item.get("direction"),
            item.get("index"),
        )
        not in removed_port_keys
    ]

    removed_bindings = {
        item["uid"]
        for item in document["parameterBindings"]
        if item.get("nodeUid") not in protected
        and (
            item.get("nodeUid") in removed_nodes
            or _owner(item) == ownership
            or item.get("parmName")
            in (manifests.get(item.get("nodeUid"), {}).get("parameters") or ())
        )
    }
    document["parameterBindings"] = [
        item
        for item in document["parameterBindings"]
        if item.get("uid") not in removed_bindings
    ]
    document["codeBlobs"] = [
        item
        for item in document["codeBlobs"]
        if item.get("target", {}).get("nodeUid") in protected
        or (
            item.get("target", {}).get("nodeUid") not in removed_nodes
        and item.get("target", {}).get("bindingUid") not in removed_bindings
        and _owner(item) != ownership
        )
    ]
    return sorted(set(missing))


def removed_owned_node_uids(
    document: dict[str, Any],
    ownership: str,
    preserved_node_paths: set[str],
    retained_node_uids: set[str],
) -> set[str]:
    return {
        item["uid"]
        for item in document["nodes"]
        if _owner(item) == ownership
        and item.get("path") not in preserved_node_paths
        and item.get("uid") not in retained_node_uids
    }


def _removed_connections(
    edges: list[dict[str, Any]],
    ownership: str,
    removed_nodes: set[str],
    manifests: dict[str, dict[str, Any]],
    protected_nodes: set[str],
) -> tuple[set[str], set[tuple[Any, Any, Any]]]:
    removed: set[str] = set()
    ports: set[tuple[Any, Any, Any]] = set()
    for edge in edges:
        source, target = edge.get("from", {}), edge.get("to", {})
        if source.get("nodeUid") in protected_nodes or target.get("nodeUid") in protected_nodes:
            continue
        destination_uid = target.get("nodeUid")
        manifest = manifests.get(destination_uid, {})
        managed_input = (
            edge.get("kind") == "data"
            and target.get("portIndex") in (manifest.get("inputs") or ())
        )
        managed_output = (
            edge.get("kind") == "output_flag"
            and bool((manifests.get(source.get("nodeUid"), {}).get("flags") or {}).get("output"))
        )
        if (
            _owner(edge) == ownership
            or source.get("nodeUid") in removed_nodes
            or destination_uid in removed_nodes
            or managed_input
            or managed_output
        ):
            removed.add(edge.get("uid"))
            for endpoint, direction in ((source, "output"), (target, "input")):
                ports.add((
                    endpoint.get("nodeUid"), direction, endpoint.get("portIndex"),
                ))
    return removed, ports


def _references_node(item: dict[str, Any], node_uids: set[str]) -> bool:
    return bool({
        item.get("nodeUid"),
        item.get("from", {}).get("nodeUid"),
        item.get("to", {}).get("nodeUid"),
        item.get("target", {}).get("nodeUid"),
    } & node_uids)


def validated_managed_fields(
    node: dict[str, Any], uid: str,
) -> dict[str, Any] | None:
    metadata = node.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    value = hocus.get("managedFields") if isinstance(hocus, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"type", "inputs", "parameters", "flags", "nodeUid"}
        or value.get("type") is not True
        or value.get("nodeUid") != uid
        or not isinstance(value.get("inputs"), list)
        or any(type(item) is not int or item < 0 for item in value["inputs"])
        or not isinstance(value.get("parameters"), list)
        or any(not isinstance(item, str) or not item for item in value["parameters"])
        or not isinstance(value.get("flags"), dict)
        or not set(value["flags"]) <= {"display", "render", "output"}
        or any(type(item) is not bool for item in value["flags"].values())
    ):
        return None
    return value


def _reset_managed_flags(
    node: dict[str, Any], manifest: dict[str, Any],
) -> None:
    flags = node.get("flags")
    if not isinstance(flags, dict):
        return
    for name in ("display", "render"):
        if manifest["flags"].get(name):
            flags[name] = False


def _owner(item: dict[str, Any]) -> Any:
    metadata = item.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    return hocus.get("ownership") if isinstance(hocus, dict) else None


def _is_default_observation(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata")
    return (
        isinstance(metadata, dict)
        and metadata.get("isAtDefault") is True
    )


def _source_map(entity: dict[str, Any]) -> tuple[Any, Any, Any] | None:
    metadata = entity.get("metadata")
    hocus = metadata.get("hocus") if isinstance(metadata, dict) else None
    if not isinstance(hocus, dict):
        return None
    values = hocus.get("sourceUri"), hocus.get("jsonPointer"), hocus.get("span")
    return values if isinstance(values[0], str) and isinstance(values[1], str) and values[2] is not None else None
