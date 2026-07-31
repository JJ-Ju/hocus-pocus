"""Bounded, fail-closed dependency closure for reopened production USD."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable


MAX_USD_BYTES = 64 * 1024 * 1024
MAX_USD_DEPENDENCIES = 256
MAX_USD_DEPENDENCY_BYTES = 256 * 1024 * 1024
MAX_USD_SPECS = 1_000_000
MAX_USD_AUTHORED_VALUES = 1_000_000


class UsdDependencyError(RuntimeError):
    """The reopened USD dependency closure is incomplete or unauthorized."""


def asset_dependencies(
    stage: Any,
    usd_path: Path,
    *,
    contract: Mapping[str, Any],
    Sdf: Any,
) -> list[dict[str, Any]]:
    """Bind every external USD/asset dependency to exact declared bytes."""

    root = stage.GetRootLayer()
    used_layers = _used_file_layers(stage)
    authored: dict[str, set[str]] = {}
    for layer in used_layers:
        for raw in _layer_composition_assets(layer):
            _add_dependency_path(authored, layer, raw, "composition", Sdf=Sdf)
        for raw in _layer_external_assets(layer):
            _add_dependency_path(authored, layer, raw, "asset", Sdf=Sdf)
        for raw in _layer_authored_asset_paths(layer, Sdf=Sdf):
            _add_dependency_path(authored, layer, raw, "asset", Sdf=Sdf)
    for raw in root.subLayerPaths:
        _add_dependency_path(authored, root, raw, "composition", Sdf=Sdf)
    root_path = _layer_file_path(root)
    if root_path != usd_path:
        raise UsdDependencyError(
            "Reopened USD root layer does not match the observed output."
        )
    for layer in used_layers:
        path = _layer_file_path(layer)
        if path != root_path:
            authored.setdefault(str(path), set()).add("composition")
    if contract["usd"]["publish"]["payload"] == "inline" and any(
        "composition" in roles for roles in authored.values()
    ):
        raise UsdDependencyError(
            "Inline USD publish policy forbids external composition layers."
        )
    return _dependency_receipts(
        authored,
        usd_path.parent,
        contract["dependencies"],
    )


def _used_file_layers(stage: Any) -> list[Any]:
    session = stage.GetSessionLayer()
    result = []
    for layer in stage.GetUsedLayers():
        if not layer.anonymous:
            result.append(layer)
        elif layer != session or not layer.empty:
            raise UsdDependencyError(
                "USD composition closure contains an anonymous layer."
            )
    if len(result) > MAX_USD_DEPENDENCIES + 1:
        raise UsdDependencyError("USD layer closure is too large.")
    return result


def _layer_composition_assets(layer: Any) -> set[str]:
    result = {
        str(getattr(value, "path", value))
        for value in layer.GetCompositionAssetDependencies()
        if str(getattr(value, "path", value))
    }
    pending = list(layer.rootPrims)
    while pending:
        spec = pending.pop()
        pending.extend(spec.nameChildren)
        for list_op in (spec.referenceList, spec.payloadList):
            result.update(
                str(item.assetPath)
                for item in list_op.GetAppliedItems()
                if str(item.assetPath)
            )
    return result


def _layer_external_assets(layer: Any) -> set[str]:
    composition = _layer_composition_assets(layer)
    return {
        str(getattr(value, "path", value))
        for value in layer.GetExternalAssetDependencies()
        if str(getattr(value, "path", value)) not in composition
    }


def _layer_authored_asset_paths(layer: Any, *, Sdf: Any) -> set[str]:
    """Collect asset values from every authored Sdf spec field and time sample."""

    specs: list[Any] = []
    visited_paths = 0

    def collect(path: Any) -> None:
        nonlocal visited_paths
        visited_paths += 1
        if visited_paths > MAX_USD_SPECS:
            raise UsdDependencyError("USD authored spec closure is too large.")
        spec = layer.GetObjectAtPath(path)
        if spec is not None:
            specs.append(spec)

    layer.Traverse(Sdf.Path.absoluteRootPath, collect)
    result: set[str] = set()
    remaining = MAX_USD_AUTHORED_VALUES
    for spec in specs:
        for key in spec.ListInfoKeys():
            if key == "subLayerOffsets":
                continue
            try:
                value = spec.GetInfo(key)
            except (RuntimeError, TypeError) as exc:
                raise UsdDependencyError(
                    "USD authored spec field could not be inspected."
                ) from exc
            paths, visited = _asset_paths_in_value(
                value,
                maximum=remaining,
                Sdf=Sdf,
            )
            result.update(paths)
            remaining -= visited
        for sample in layer.ListTimeSamplesForPath(spec.path):
            paths, visited = _asset_paths_in_value(
                layer.QueryTimeSample(spec.path, sample),
                maximum=remaining,
                Sdf=Sdf,
            )
            result.update(paths)
            remaining -= visited
    return result


def _asset_paths_in_value(
    value: Any,
    *,
    maximum: int,
    Sdf: Any,
) -> tuple[set[str], int]:
    result: set[str] = set()
    pending = [value]
    visited = 0
    while pending:
        visited += 1
        if visited > maximum:
            raise UsdDependencyError("USD authored value closure is too large.")
        current = pending.pop()
        if isinstance(current, Sdf.AssetPath):
            if current.path:
                result.add(str(current.path))
        elif isinstance(current, Mapping):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple, Sdf.AssetPathArray)):
            pending.extend(current)
    return result, visited


def _add_dependency_path(
    output: dict[str, set[str]],
    layer: Any,
    raw: str,
    role: str,
    *,
    Sdf: Any,
) -> None:
    if not raw or raw.startswith(("op:", "opdef:", "oplib:")):
        raise UsdDependencyError(
            "USD dependency uses an unresolved or ambient asset scheme."
        )
    resolved = str(Sdf.ComputeAssetPathRelativeToLayer(layer, raw) or "")
    if not resolved:
        raise UsdDependencyError("USD dependency could not be resolved.")
    path = Path(resolved)
    if not path.is_absolute():
        raise UsdDependencyError(
            "USD dependency did not resolve to an absolute local file."
        )
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise UsdDependencyError("USD dependency traverses a symbolic link.")
    output.setdefault(str(path.resolve()), set()).add(role)


def _layer_file_path(layer: Any) -> Path:
    if layer is None or layer.anonymous:
        raise UsdDependencyError(
            "USD composition closure contains an anonymous layer."
        )
    raw = str(layer.realPath or layer.resolvedPath or "")
    if not raw:
        raise UsdDependencyError("USD layer has no resolved file identity.")
    path = Path(raw).resolve()
    if not path.is_file():
        raise UsdDependencyError("USD layer cannot be read.")
    return path


def _dependency_receipts(
    paths: Mapping[str, set[str]],
    authority_root: Path,
    declared: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if len(paths) > MAX_USD_DEPENDENCIES:
        raise UsdDependencyError("USD dependency closure is too large.")
    candidates = list(declared)
    used: set[tuple[str, str]] = set()
    receipts = []
    total = 0
    root = authority_root.resolve()
    for raw_path in sorted(paths):
        path = Path(raw_path)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise UsdDependencyError(
                "USD dependency escapes the authorized output root."
            ) from exc
        try:
            before = path.stat()
            regular = path.is_file() and not path.is_symlink()
        except OSError as exc:
            raise UsdDependencyError("USD dependency cannot be read.") from exc
        if not regular:
            raise UsdDependencyError("USD dependency is not a regular file.")
        if before.st_size > MAX_USD_BYTES:
            raise UsdDependencyError("USD dependency exceeds its byte limit.")
        try:
            content = path.read_bytes()
            after = path.stat()
        except OSError as exc:
            raise UsdDependencyError("USD dependency cannot be read.") from exc
        if (
            len(content) != before.st_size
            or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size)
            != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size)
        ):
            raise UsdDependencyError("USD dependency changed while observed.")
        total += len(content)
        if total > MAX_USD_DEPENDENCY_BYTES:
            raise UsdDependencyError(
                "USD dependency closure exceeds its byte limit."
            )
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        roles = paths[raw_path]
        allowed = {"usd", "asset"} if "composition" in roles else {"texture", "asset"}
        matches = [
            item for item in candidates
            if item["kind"] in allowed and item["digest"] == digest
            and (item["kind"], item["id"]) not in used
        ]
        if len(matches) != 1:
            raise UsdDependencyError(
                "USD dependency is ambient or ambiguously declared by the contract."
            )
        match = matches[0]
        used.add((match["kind"], match["id"]))
        receipts.append({
            **{key: match[key] for key in ("id", "kind", "version", "digest")},
            "byteLength": len(content),
            "roles": sorted(roles),
        })
    return receipts


__all__ = ["UsdDependencyError", "asset_dependencies"]
