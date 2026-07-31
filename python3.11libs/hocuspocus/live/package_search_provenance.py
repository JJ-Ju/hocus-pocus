"""Strict live provenance for Houdini package and definition search authority."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from hocuspocus.hocusscript.build_provenance import canonical_digest
from hocuspocus.hocusscript.catalog import CatalogSnapshot
from hocuspocus.live.catalog_provider import (
    LiveCatalogExtractionError,
    LiveHoudiniCatalogProvider,
    definition_content_digest,
)
from hocuspocus.live.package_startup_trace import (
    PackageStartupTraceError,
    load_package_startup_trace,
)
from hocuspocus.live.package_search_validation import (
    validate_package_search_receipt,
)


PACKAGE_SEARCH_SCHEMA = (
    "hocuspocus://schemas/effective-package-search-provenance/v1"
)
MAX_PACKAGES = 4096
MAX_OPERATORS = 16384
MAX_SEARCH_PATHS = 4096
MAX_PACKAGE_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_FILES = 20_000
MAX_MANIFEST_FILE_BYTES = 64 * 1024 * 1024
MAX_BINARY_BYTES = 2 * 1024 * 1024 * 1024

_INSTALL_MANIFEST_SCHEMA = "hocuspocus://schemas/install-manifest/v1"
_INSTALL_GOVERNED_ROOTS = (
    "config",
    "docs/schemas",
    "python_panels",
    "python3.11libs",
    "scripts",
    "toolbar",
    "package",
)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_CONDITION_KEYS = frozenset({
    "enable",
    "load_package_once",
    "package_path",
    "process_order",
    "recommends",
    "requires",
})
_RECEIPT_FIELDS = {
    "$schema",
    "kind",
    "schemaVersion",
    "houdini",
    "installedPayload",
    "packageTrace",
    "packages",
    "searchOrder",
    "precedence",
    "operatorWinners",
    "shadowing",
    "loadedLibraryDigest",
    "receiptDigest",
}


class PackageSearchProvenanceError(RuntimeError):
    """Fail-closed package, path, definition, or receipt error."""

    def __init__(self, message: str):
        super().__init__(message)
        self.code = "HOCUS991"
        self.message = message


def collect_effective_package_search(
    hou_module: Any,
    provider: LiveHoudiniCatalogProvider,
    catalog: CatalogSnapshot,
    *,
    installed_root: Path,
    install_manifest: Mapping[str, Any],
    modules: Mapping[str, Any] | None = None,
    python_paths: Sequence[str] | None = None,
    startup_trace: str | bytes | Path | None = None,
) -> dict[str, Any]:
    """Collect and self-verify one deterministic effective-search receipt."""

    root = _resolved_directory(installed_root, "installed HocusPocus root")
    manifest_identity = _manifest_identity(install_manifest)
    loaded_package_info = _loaded_package_info(hou_module)
    try:
        trace = load_package_startup_trace(
            startup_trace,
            expand=lambda item: _expand_string(hou_module, item),
        )
    except PackageStartupTraceError as exc:
        raise PackageSearchProvenanceError(str(exc)) from exc
    actual_paths = _effective_search_paths(
        hou_module, provider, loaded_package_info,
        tuple(sys.path if python_paths is None else python_paths),
        trace,
    )
    authorities = _path_authorities(hou_module, root, actual_paths)
    search_order = {
        kind: _search_rows(paths, authorities)
        for kind, paths in actual_paths.items()
    }
    _reject_repository_imports(root, modules or sys.modules)
    _reject_hocuspocus_shadow_paths(root, actual_paths)
    packages = _package_records(
        hou_module, actual_paths["package"], authorities, loaded_package_info,
        trace,
    )
    _require_active_hocuspocus_package(
        hou_module, packages, root, authorities,
    )
    operators, shadowing, loaded_libraries = _operator_records(
        hou_module, catalog, authorities,
    )
    precedence = {
        "packageProcessing": [
            _portable_locator(item, authorities) for item in trace["processed"]
        ],
        "searchOrderDigest": canonical_digest(search_order),
        "operatorWinnerDigest": canonical_digest(operators),
    }
    unsigned = {
        "$schema": PACKAGE_SEARCH_SCHEMA,
        "kind": "hocus_effective_package_search_provenance",
        "schemaVersion": 1,
        "houdini": catalog.houdini.to_dict(),
        "installedPayload": {
            "rootLocator": "hocus-install://root",
            "rootDigest": manifest_identity["rootDigest"],
            "manifestDigest": manifest_identity["manifestDigest"],
            "artifactCount": manifest_identity["artifactCount"],
        },
        "packageTrace": _portable_trace(trace, authorities),
        "packages": packages,
        "searchOrder": search_order,
        "precedence": precedence,
        "operatorWinners": operators,
        "shadowing": shadowing,
        "loadedLibraryDigest": canonical_digest(loaded_libraries),
    }
    receipt = {**unsigned, "receiptDigest": canonical_digest(unsigned)}
    return decode_effective_package_search(receipt)


def verify_effective_package_search(
    value: Any,
    hou_module: Any,
    provider: LiveHoudiniCatalogProvider,
    catalog: CatalogSnapshot,
    *,
    installed_root: Path,
    install_manifest: Mapping[str, Any],
    modules: Mapping[str, Any] | None = None,
    python_paths: Sequence[str] | None = None,
    startup_trace: str | bytes | Path | None = None,
) -> dict[str, Any]:
    """Re-derive live authority and require an exact receipt match."""

    decoded = decode_effective_package_search(value)
    expected = collect_effective_package_search(
        hou_module,
        provider,
        catalog,
        installed_root=installed_root,
        install_manifest=install_manifest,
        modules=modules,
        python_paths=python_paths,
        startup_trace=startup_trace,
    )
    if decoded != expected:
        raise PackageSearchProvenanceError(
            "Effective Houdini package-search receipt differs from live state."
        )
    return decoded


def decode_effective_package_search(value: Any) -> dict[str, Any]:
    """Decode the exact bounded carrier without consulting Houdini."""

    if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS:
        raise PackageSearchProvenanceError(
            "Effective package-search receipt has an invalid envelope."
        )
    if (
        value.get("$schema") != PACKAGE_SEARCH_SCHEMA
        or value.get("kind") != "hocus_effective_package_search_provenance"
        or value.get("schemaVersion") != 1
    ):
        raise PackageSearchProvenanceError(
            "Effective package-search receipt version is unsupported."
        )
    _bounded_array(value.get("packages"), MAX_PACKAGES, "packages")
    _bounded_array(value.get("operatorWinners"), MAX_OPERATORS, "operators")
    _bounded_array(value.get("shadowing"), MAX_OPERATORS, "shadowing")
    order = value.get("searchOrder")
    if not isinstance(order, dict) or set(order) != {
        "package", "houdini", "hda", "python",
    }:
        raise PackageSearchProvenanceError("Search-order envelope is invalid.")
    for kind, rows in order.items():
        _bounded_array(rows, MAX_SEARCH_PATHS, f"{kind} search paths")
    try:
        validate_package_search_receipt(value)
    except ValueError as exc:
        raise PackageSearchProvenanceError(str(exc)) from exc
    digest = value.get("receiptDigest")
    unsigned = {key: item for key, item in value.items() if key != "receiptDigest"}
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise PackageSearchProvenanceError("Package-search receipt digest is invalid.")
    if digest != canonical_digest(unsigned):
        raise PackageSearchProvenanceError(
            "Package-search receipt digest does not match its content."
        )
    normalized = copy.deepcopy(value)
    try:
        encoded = json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PackageSearchProvenanceError(
            "Package-search receipt must contain finite JSON."
        ) from exc
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise PackageSearchProvenanceError(
            "Package-search receipt exceeds its byte limit."
        )
    return normalized


def _effective_search_paths(
    hou_module: Any,
    provider: LiveHoudiniCatalogProvider,
    loaded_packages: Mapping[str, Mapping[str, Any]] | None,
    python_paths: tuple[str, ...],
    trace: Mapping[str, Any],
) -> dict[str, tuple[Path, ...]]:
    return {
        "package": _effective_package_paths(
            hou_module, provider, loaded_packages, trace,
        ),
        "houdini": _houdini_paths(hou_module, None),
        "hda": _houdini_paths(hou_module, "HOUDINI_OTLSCAN_PATH"),
        "python": _canonical_paths(
            Path(item or os.getcwd()) for item in python_paths
        ),
    }


def _effective_package_paths(
    hou_module: Any,
    provider: LiveHoudiniCatalogProvider,
    loaded_packages: Mapping[str, Mapping[str, Any]] | None,
    trace: Mapping[str, Any],
) -> tuple[Path, ...]:
    """Include startup roots plus dynamically queued loaded-package roots."""

    values = list(provider.package_directories())
    values.extend(
        _package_info_path(hou_module, info).parent
        for info in (loaded_packages or {}).values()
    )
    values.extend(
        item["path"].parent for item in trace["events"]
        if item["kind"] == "discovered"
    )
    return _canonical_paths(values)


def _houdini_paths(hou_module: Any, variable: str | None) -> tuple[Path, ...]:
    operation = getattr(hou_module, "houdiniPath", None)
    if not callable(operation):
        raise PackageSearchProvenanceError("hou.houdiniPath is unavailable.")
    try:
        values = operation() if variable is None else operation(variable)
    except Exception as exc:
        raise PackageSearchProvenanceError(
            f"Houdini could not expand {variable or 'HOUDINI_PATH'}."
        ) from exc
    if not isinstance(values, (tuple, list)):
        raise PackageSearchProvenanceError("Houdini search path is not an array.")
    return _canonical_paths(Path(str(item)) for item in values)


def _path_authorities(
    hou_module: Any,
    installed_root: Path,
    searches: Mapping[str, tuple[Path, ...]],
) -> tuple[tuple[str, Path], ...]:
    result: list[tuple[str, Path]] = [("hocus-install://root", installed_root)]
    hfs = _expanded_path(hou_module, "$HFS")
    if hfs is not None:
        result.append(("houdini-install://root", hfs))
    for kind in ("package", "houdini", "hda", "python"):
        result.extend(
            (f"hocus-search://{kind}/{index}", path)
            for index, path in enumerate(searches[kind])
        )
    return tuple(result)


def _search_rows(
    paths: tuple[Path, ...],
    authorities: tuple[tuple[str, Path], ...],
) -> list[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "locator": _portable_locator(path, authorities),
            "exists": path.exists(),
            "directory": path.is_dir(),
        }
        for rank, path in enumerate(paths)
    ]


def _package_records(
    hou_module: Any,
    package_dirs: tuple[Path, ...],
    authorities: tuple[tuple[str, Path], ...],
    loaded: Mapping[str, Mapping[str, Any]] | None,
    trace: Mapping[str, Any],
) -> list[dict[str, Any]]:
    discovered = _discovered_package_files(package_dirs)
    loaded_paths: dict[str, tuple[str, Mapping[str, Any]]] = {}
    if loaded is not None:
        for name, info in loaded.items():
            source = _package_info_path(hou_module, info)
            key = _path_key(source)
            if key in loaded_paths:
                raise PackageSearchProvenanceError(
                    "Multiple loaded packages resolve to the same source file."
                )
            loaded_paths[key] = (name, info)
            discovered.setdefault(key, source)
    trace_events = [
        item for item in trace["events"] if item["kind"] == "discovered"
    ]
    trace_paths = {_path_key(item["path"]): item["path"] for item in trace_events}
    if set(discovered) != set(trace_paths):
        raise PackageSearchProvenanceError(
            "Enumerated package files differ from the authoritative startup trace."
        )
    trace_loaded = {_path_key(item) for item in trace["loaded"]}
    if loaded is not None and set(loaded_paths) != trace_loaded:
        raise PackageSearchProvenanceError(
            "hou.ui.packageInfo differs from the authoritative loaded-package trace."
        )
    if loaded is None:
        loaded_paths = {
            _path_key(item): (item.stem, {})
            for item in trace["loaded"]
        }
    status = {
        **{_path_key(item): "loaded" for item in trace["loaded"]},
        **{_path_key(item): "disabled" for item in trace["disabled"]},
        **{_path_key(item): "skipped" for item in trace["skipped"]},
    }
    processing_rank = {
        _path_key(item): rank for rank, item in enumerate(trace["processed"])
    }
    discovery_rank = {
        _path_key(item["path"]): rank for rank, item in enumerate(trace_events)
    }
    records = []
    for key, source in trace_paths.items():
        loaded_entry = loaded_paths.get(key)
        records.append(_package_record(
            hou_module,
            source,
            loaded_entry,
            authorities,
            status=status[key],
            discovery_rank=discovery_rank[key],
            processing_rank=processing_rank.get(key, -1),
        ))
    records.sort(key=lambda item: item["discoveryRank"])
    if len(records) > MAX_PACKAGES:
        raise PackageSearchProvenanceError("Package file count exceeds its limit.")
    return records


def _package_record(
    hou_module: Any,
    source: Path,
    loaded: tuple[str, Mapping[str, Any]] | None,
    authorities: tuple[tuple[str, Path], ...],
    *,
    status: str,
    discovery_rank: int,
    processing_rank: int,
) -> dict[str, Any]:
    content = _bounded_file(source, "Houdini package file", MAX_PACKAGE_BYTES)
    try:
        payload = json.loads(
            content.decode("utf-8"),
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"invalid constant {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PackageSearchProvenanceError(
            "Evaluated Houdini package file is not strict UTF-8 JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise PackageSearchProvenanceError("Houdini package root must be an object.")
    conditions = {
        key: payload[key] for key in sorted(_CONDITION_KEYS.intersection(payload))
    }
    name, info = loaded or (source.stem, {})
    raw_order = payload.get("process_order")
    process_order = (
        raw_order
        if isinstance(raw_order, (int, float))
        and not isinstance(raw_order, bool)
        and math.isfinite(raw_order)
        else None
    )
    if "process_order" in payload and process_order is None:
        raise PackageSearchProvenanceError(
            "Houdini package process_order is not a finite number."
        )
    return {
        "name": _bounded_text(name, "package name"),
        "sourceLocator": _portable_locator(source, authorities),
        "contentDigest": _digest_bytes(content),
        "byteLength": len(content),
        "loaded": loaded is not None,
        "status": status,
        "discoveryRank": discovery_rank,
        "evaluationRank": processing_rank,
        "processOrder": process_order,
        "conditionKeys": sorted(conditions),
        "conditionDigest": canonical_digest(conditions),
        "evaluatedDigest": canonical_digest(
            _portable_package_info(hou_module, info, authorities)
        ),
        "declaresHocusPocusRoot": _contains_key(payload, "HOCUSPOCUS_ROOT"),
    }


def _loaded_package_info(
    hou_module: Any,
) -> dict[str, Mapping[str, Any]] | None:
    ui = getattr(hou_module, "ui", None)
    operation = getattr(ui, "packageInfo", None)
    if not callable(operation):
        return None
    try:
        raw = operation()
        value = json.loads(raw)
    except Exception as exc:
        raise PackageSearchProvenanceError(
            "Houdini loaded-package evaluation is unavailable or invalid."
        ) from exc
    if not isinstance(value, dict) or len(value) > MAX_PACKAGES:
        raise PackageSearchProvenanceError(
            "Houdini loaded-package evaluation is unbounded."
        )
    result = {}
    for name, info in value.items():
        if not isinstance(name, str) or not isinstance(info, Mapping):
            raise PackageSearchProvenanceError(
                "Houdini package evaluation contains an invalid record."
            )
        result[name] = info
    return result


def _package_info_path(hou_module: Any, info: Mapping[str, Any]) -> Path:
    value = info.get("File path")
    if not isinstance(value, str) or not value:
        raise PackageSearchProvenanceError(
            "Loaded package evaluation omits its source file."
        )
    expanded = _expand_string(hou_module, value)
    return _resolved_file(Path(expanded), "loaded package source")


def _discovered_package_files(
    directories: tuple[Path, ...],
) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for directory in directories:
        try:
            files = tuple(directory.glob("*.json"))
        except OSError as exc:
            raise PackageSearchProvenanceError(
                "Houdini package directory cannot be enumerated."
            ) from exc
        for path in sorted(files, key=lambda item: item.name.casefold()):
            resolved = _resolved_file(path, "discovered package source")
            result.setdefault(_path_key(resolved), resolved)
    return result


def _portable_package_info(
    hou_module: Any,
    value: Any,
    authorities: tuple[tuple[str, Path], ...],
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _portable_package_info(hou_module, item, authorities)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [
            _portable_package_info(hou_module, item, authorities)
            for item in value
        ]
    if isinstance(value, str) and _looks_like_path(value):
        expanded = _expand_string(hou_module, value)
        return _portable_locator(_resolved_path(Path(expanded)), authorities)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _portable_trace(
    trace: Mapping[str, Any],
    authorities: tuple[tuple[str, Path], ...],
) -> dict[str, Any]:
    evidence = {
        "authority": trace["authority"],
        "events": [
            {
                "rank": item["rank"],
                "kind": item["kind"],
                "sourceLocator": _portable_locator(item["path"], authorities),
            }
            for item in trace["events"]
        ],
        "loadedLocators": [
            _portable_locator(item, authorities) for item in trace["loaded"]
        ],
        "disabledLocators": [
            _portable_locator(item, authorities) for item in trace["disabled"]
        ],
        "skippedLocators": [
            _portable_locator(item, authorities) for item in trace["skipped"]
        ],
    }
    return {**evidence, "traceDigest": canonical_digest(evidence)}


def _require_active_hocuspocus_package(
    hou_module: Any,
    packages: list[dict[str, Any]],
    installed_root: Path,
    authorities: tuple[tuple[str, Path], ...],
) -> None:
    declared = [item for item in packages if item["declaresHocusPocusRoot"]]
    loaded = [item for item in declared if item["loaded"]]
    if len(loaded) != 1 or len(declared) != 1:
        raise PackageSearchProvenanceError(
            "HocusPocus package authority is absent, duplicated, or shadowed."
        )
    configured = _expanded_path(hou_module, "$HOCUSPOCUS_ROOT")
    if configured != installed_root:
        raise PackageSearchProvenanceError(
            "Loaded HocusPocus package does not select the installed root."
        )
    if _portable_locator(configured, authorities) != "hocus-install://root":
        raise PackageSearchProvenanceError(
            "Installed HocusPocus root has ambiguous path authority."
        )


def _operator_records(
    hou_module: Any,
    catalog: CatalogSnapshot,
    authorities: tuple[tuple[str, Path], ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    category_map = _node_type_categories(hou_module)
    records = []
    shadowing = []
    loaded_libraries: set[str] = set()
    for operator in catalog.operators:
        node_type = _node_type(category_map, operator.category, operator.qualified_name)
        record, shadows, libraries = _operator_record(
            hou_module, operator, node_type, authorities,
        )
        records.append(record)
        shadowing.extend(shadows)
        loaded_libraries.update(libraries)
    if len(records) > MAX_OPERATORS or len(shadowing) > MAX_OPERATORS:
        raise PackageSearchProvenanceError(
            "Operator winner evidence exceeds its item limit."
        )
    records.sort(key=lambda item: (item["category"], item["qualifiedName"]))
    shadowing.sort(key=lambda item: (
        item["category"], item["qualifiedName"], item["shadowedLocator"],
    ))
    _verify_loaded_libraries(hou_module, loaded_libraries, authorities)
    return records, shadowing, sorted(loaded_libraries)


def _operator_record(
    hou_module: Any,
    operator: Any,
    node_type: Any,
    authorities: tuple[tuple[str, Path], ...],
) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    source = operator.source
    base = {
        "category": operator.category,
        "qualifiedName": operator.qualified_name,
        "sourceKind": source.kind,
        "packageId": source.package_id,
        "winner": None,
    }
    if source.kind != "hda":
        base["winner"] = _native_winner(
            hou_module, source, node_type, authorities,
        )
        return base, [], set()
    if node_type is None or source.hda_library is None:
        raise PackageSearchProvenanceError(
            "Catalog HDA operator has no live node type or HDA identity."
        )
    definitions = _installed_definitions(node_type)
    candidates = [
        _definition_record(
            hou_module, item, operator.qualified_name, authorities,
        )
        for item in definitions
    ]
    currents = [item for item in candidates if item["current"]]
    preferred = [item for item in candidates if item["preferred"]]
    if (
        len(currents) != 1
        or len(preferred) > 1
        or (preferred and preferred[0] != currents[0])
    ):
        raise PackageSearchProvenanceError(
            "HDA operator winner is absent or ambiguous."
        )
    winner_definition = _required_call(node_type, "definition")
    winner = _definition_record(
        hou_module, winner_definition, operator.qualified_name, authorities,
    )
    if winner != currents[0]:
        raise PackageSearchProvenanceError(
            "Node type definition disagrees with its current HDA winner."
        )
    if winner["contentDigest"] != source.hda_library.content_digest:
        raise PackageSearchProvenanceError(
            "Catalog HDA identity differs from the selected live definition."
        )
    base["winner"] = {
        "kind": "hda",
        **{
            key: winner[key]
            for key in ("libraryLocator", "contentDigest", "version", "preferred")
        },
    }
    shadows = [
        {
            "category": operator.category,
            "qualifiedName": operator.qualified_name,
            "winnerLocator": winner["libraryLocator"],
            "shadowedLocator": item["libraryLocator"],
            "shadowedDigest": item["contentDigest"],
        }
        for item in candidates
        if item != winner
    ]
    return base, shadows, {item["libraryLocator"] for item in candidates}


def _native_winner(
    hou_module: Any,
    source: Any,
    node_type: Any,
    authorities: tuple[tuple[str, Path], ...],
) -> dict[str, Any]:
    if source.hda_library is not None or node_type is None:
        raise PackageSearchProvenanceError(
            "Non-HDA catalog operator has invalid live provenance."
        )
    source_type = _enum_name(_required_call(node_type, "source"))
    source_path = _required_call(node_type, "sourcePath")
    if not isinstance(source_path, str) or not source_path:
        raise PackageSearchProvenanceError(
            "Native operator omits its source-path identity."
        )
    if source_type == "Internal" and source_path == "Internal":
        if source.kind != "builtin" or source.package_id is not None:
            raise PackageSearchProvenanceError(
                "Package operator is unexplained by an internal builtin."
            )
        return {"kind": "internal", "sourceType": source_type}
    if source_type != "CompiledCode" or source_path == "Internal":
        raise PackageSearchProvenanceError(
            "Non-HDA operator has an unexplained plugin source."
        )
    binary = _resolved_file(
        Path(_expand_string(hou_module, source_path)),
        "native operator backing library",
    )
    locator = _portable_locator(binary, authorities)
    if locator.startswith("hocus-search://external/"):
        raise PackageSearchProvenanceError(
            "Native operator binary is outside every search authority."
        )
    return {
        "kind": "binary",
        "sourceType": source_type,
        "libraryLocator": locator,
        "contentDigest": _digest_regular_file(binary),
        "byteLength": binary.stat().st_size,
    }


def _definition_record(
    hou_module: Any,
    definition: Any,
    raw_name: str,
    authorities: tuple[tuple[str, Path], ...],
) -> dict[str, Any]:
    library = _required_call(definition, "libraryFilePath")
    if not isinstance(library, str) or not library or library == "Embedded":
        raise PackageSearchProvenanceError(
            "Embedded or unnamed HDA definitions are unexplained release inputs."
        )
    path = _resolved_hda_library(Path(_expand_string(hou_module, library)))
    locator = _portable_locator(path, authorities)
    if locator.startswith("hocus-search://external/"):
        raise PackageSearchProvenanceError(
            "Loaded HDA definition is outside every effective search authority."
        )
    try:
        content_digest = definition_content_digest(definition, raw_name)
    except LiveCatalogExtractionError as exc:
        message = "Loaded HDA definition has no bounded stable byte identity."
        raise PackageSearchProvenanceError(message) from exc
    return {
        "libraryLocator": locator,
        "contentDigest": content_digest,
        "version": _optional_text(_optional_call(definition, "version")),
        "current": _required_bool(definition, "isCurrent"),
        "preferred": _required_bool(definition, "isPreferred"),
    }


def _installed_definitions(node_type: Any) -> tuple[Any, ...]:
    values = _required_call(node_type, "allInstalledDefinitions")
    if not isinstance(values, (tuple, list)) or not values:
        raise PackageSearchProvenanceError(
            "HDA node type has no installed definition candidates."
        )
    return tuple(values)


def _verify_loaded_libraries(
    hou_module: Any,
    explained: set[str],
    authorities: tuple[tuple[str, Path], ...],
) -> None:
    hda = getattr(hou_module, "hda", None)
    values = _required_call(hda, "loadedFiles")
    if not isinstance(values, (tuple, list)):
        raise PackageSearchProvenanceError("Loaded HDA library list is invalid.")
    actual = set()
    for value in values:
        if not isinstance(value, str) or value == "Embedded":
            raise PackageSearchProvenanceError(
                "Embedded or malformed loaded HDA library is unexplained."
            )
        expanded = Path(_expand_string(hou_module, value))
        if not expanded.exists():
            # Absent optional registrations have no loadable byte identity.
            continue
        path = _resolved_hda_library(expanded)
        locator = _portable_locator(path, authorities)
        if path.is_dir() and locator not in explained:
            # Directory placeholders require an explained live definition.
            continue
        actual.add(locator)
    if actual != explained:
        raise PackageSearchProvenanceError(
            "Loaded HDA libraries differ from explained operator definitions."
        )


def _node_type_categories(hou_module: Any) -> Mapping[str, Any]:
    values = _required_call(hou_module, "nodeTypeCategories")
    if not isinstance(values, Mapping):
        raise PackageSearchProvenanceError("Houdini node categories are invalid.")
    return values


def _node_type(
    categories: Mapping[str, Any],
    category_name: str,
    qualified_name: str,
) -> Any:
    category = categories.get(category_name)
    if category is None:
        for candidate in categories.values():
            if _optional_text(_optional_call(candidate, "name")) == category_name:
                category = candidate
                break
    values = _required_call(category, "nodeTypes")
    if not isinstance(values, Mapping):
        raise PackageSearchProvenanceError("Houdini node types are invalid.")
    direct = values.get(qualified_name)
    if direct is not None:
        return direct
    for candidate in values.values():
        if _optional_text(_optional_call(candidate, "name")) == qualified_name:
            return candidate
    return None


def _reject_repository_imports(
    installed_root: Path,
    modules: Mapping[str, Any],
) -> None:
    for name, module in modules.items():
        if name != "hocuspocus" and not name.startswith("hocuspocus."):
            continue
        source = getattr(module, "__file__", None)
        if not isinstance(source, str):
            raise PackageSearchProvenanceError(
                "Loaded HocusPocus module has no file identity."
            )
        path = _resolved_file(Path(source), "loaded HocusPocus module")
        if path != installed_root and installed_root not in path.parents:
            raise PackageSearchProvenanceError(
                "HocusPocus module was imported outside the installed payload."
            )


def _reject_hocuspocus_shadow_paths(
    installed_root: Path,
    searches: Mapping[str, tuple[Path, ...]],
) -> None:
    for kind in ("houdini", "python"):
        for root in searches[kind]:
            candidates = (
                root / "hocuspocus" / "__init__.py",
                root / "python3.11libs" / "hocuspocus" / "__init__.py",
            )
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                resolved = _resolved_file(candidate, "HocusPocus search candidate")
                if resolved != installed_root and installed_root not in resolved.parents:
                    raise PackageSearchProvenanceError(
                        "A non-installed search path shadows HocusPocus."
                    )


def _portable_locator(
    path: Path,
    authorities: tuple[tuple[str, Path], ...],
) -> str:
    selected = _resolved_path(path)
    for label, root in authorities:
        if selected == root:
            return label
        if root in selected.parents:
            relative = selected.relative_to(root).as_posix()
            return f"{label}/{relative}"
    return (
        "hocus-search://external/"
        + canonical_digest(_path_key(selected)).removeprefix("sha256:")
    )


def _canonical_paths(values: Any) -> tuple[Path, ...]:
    result = []
    seen = set()
    for value in values:
        path = _resolved_path(Path(value))
        key = _path_key(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    if len(result) > MAX_SEARCH_PATHS:
        raise PackageSearchProvenanceError("Search path count exceeds its limit.")
    return tuple(result)


def _expanded_path(hou_module: Any, value: str) -> Path | None:
    expanded = _expand_string(hou_module, value)
    if not expanded or expanded == value:
        return None
    return _resolved_path(Path(expanded))


def _expand_string(hou_module: Any, value: str) -> str:
    operation = getattr(hou_module, "expandString", None)
    if callable(operation):
        try:
            expanded = operation(value)
        except Exception as exc:
            raise PackageSearchProvenanceError(
                "Houdini failed to expand package/search authority."
            ) from exc
        if isinstance(expanded, str):
            return expanded
    return os.path.expandvars(value)


def _resolved_directory(value: Path, label: str) -> Path:
    path = _resolved_path(value)
    if not path.is_dir():
        raise PackageSearchProvenanceError(f"{label} is not a directory.")
    return path


def _resolved_file(value: Path, label: str) -> Path:
    path = _resolved_path(value)
    if path.is_symlink() or not path.is_file():
        raise PackageSearchProvenanceError(f"{label} is not a regular file.")
    return path


def _resolved_hda_library(value: Path) -> Path:
    if value.is_symlink():
        raise PackageSearchProvenanceError(
            "Loaded HDA library cannot be a symbolic link."
        )
    path = _resolved_path(value)
    if not path.is_file() and not path.is_dir():
        raise PackageSearchProvenanceError(
            "Loaded HDA library has no byte-addressable backing."
        )
    return path


def _resolved_path(value: Path) -> Path:
    try:
        return value.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PackageSearchProvenanceError("Search authority path is invalid.") from exc


def _manifest_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "$schema", "kind", "schemaVersion", "governedRoots", "files",
        "manifestDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise PackageSearchProvenanceError(
            "Install manifest has an invalid envelope."
        )
    files = value.get("files")
    roots = value.get("governedRoots")
    if (
        value.get("$schema") != _INSTALL_MANIFEST_SCHEMA
        or value.get("kind") != "hocus_install_manifest"
        or value.get("schemaVersion") != 1
        or roots != list(_INSTALL_GOVERNED_ROOTS)
        or not isinstance(files, list)
        or not 0 < len(files) <= MAX_MANIFEST_FILES
    ):
        raise PackageSearchProvenanceError("Install manifest identity is invalid.")
    seen: set[str] = set()
    for row in files:
        _validate_manifest_row(row, seen)
    order = [item["relativePath"] for item in files]
    root_rank = {
        name: index for index, name in enumerate(_INSTALL_GOVERNED_ROOTS)
    }
    if order != sorted(
        order,
        key=lambda item: (
            root_rank[_manifest_root(item)],
            item.casefold(),
        ),
    ):
        raise PackageSearchProvenanceError(
            "Install manifest files are not in canonical order."
        )
    unsigned = {key: item for key, item in value.items() if key != "manifestDigest"}
    digest = value.get("manifestDigest")
    if (
        not isinstance(digest, str)
        or not _DIGEST.fullmatch(digest)
        or digest != canonical_digest(unsigned)
    ):
        raise PackageSearchProvenanceError("Install manifest digest is invalid.")
    root_identity = {
        "rootLocator": "hocus-install://root",
        "manifestSchema": _INSTALL_MANIFEST_SCHEMA,
        "manifestKind": "hocus_install_manifest",
        "manifestVersion": 1,
        "governedRoots": list(_INSTALL_GOVERNED_ROOTS),
    }
    return {
        "rootDigest": canonical_digest(root_identity),
        "manifestDigest": digest,
        "artifactCount": len(files),
    }


def _validate_manifest_row(value: Any, seen: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "relativePath", "role", "byteLength", "contentDigest",
    }:
        raise PackageSearchProvenanceError("Install manifest file row is invalid.")
    relative = value.get("relativePath")
    pure = PurePosixPath(relative) if isinstance(relative, str) else None
    parts = pure.parts if pure is not None else ()
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or ":" in relative
        or pure is None
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in parts)
        or _manifest_root(relative) is None
        or relative == "package/install-manifest-v1.json"
        or relative in seen
    ):
        raise PackageSearchProvenanceError(
            "Install manifest relative path is invalid."
        )
    seen.add(relative)
    byte_length = value.get("byteLength")
    expected_role = (
        "generated_config"
        if relative == "config/default.toml"
        else "immutable"
    )
    if (
        value.get("role") != expected_role
        or not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or not 0 <= byte_length <= MAX_MANIFEST_FILE_BYTES
        or not isinstance(value.get("contentDigest"), str)
        or not _DIGEST.fullmatch(value["contentDigest"])
    ):
        raise PackageSearchProvenanceError(
            "Install manifest file identity is invalid."
        )


def _manifest_root(relative: str) -> str | None:
    for root in _INSTALL_GOVERNED_ROOTS:
        if relative.startswith(root + "/"):
            return root
    return None


def _bounded_file(path: Path, label: str, maximum: int) -> bytes:
    try:
        size = path.stat().st_size
        if not 0 <= size <= maximum:
            raise PackageSearchProvenanceError(f"{label} exceeds its byte limit.")
        content = path.read_bytes()
    except OSError as exc:
        raise PackageSearchProvenanceError(f"{label} cannot be read.") from exc
    if len(content) != size:
        raise PackageSearchProvenanceError(f"{label} changed while being read.")
    return content


def _required_call(value: Any, name: str) -> Any:
    operation = getattr(value, name, None)
    if not callable(operation):
        raise PackageSearchProvenanceError(f"Required Houdini API {name} is absent.")
    try:
        return operation()
    except Exception as exc:
        raise PackageSearchProvenanceError(
            f"Required Houdini API {name} failed."
        ) from exc


def _optional_call(value: Any, name: str) -> Any:
    operation = getattr(value, name, None)
    if not callable(operation):
        return None
    try:
        return operation()
    except Exception:
        return None


def _required_bool(value: Any, name: str) -> bool:
    result = _required_call(value, name)
    if not isinstance(result, bool):
        raise PackageSearchProvenanceError(f"HDA {name} result is not boolean.")
    return result


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _enum_name(value: Any) -> str:
    text = str(value).strip()
    name = text.rsplit(".", 1)[-1]
    return _bounded_text(name, "Houdini source type")


def _digest_regular_file(path: Path) -> str:
    import hashlib

    try:
        before = path.stat()
        if not 0 <= before.st_size <= MAX_BINARY_BYTES:
            raise PackageSearchProvenanceError(
                "Native operator backing library exceeds its byte limit."
            )
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        after = path.stat()
    except OSError as exc:
        raise PackageSearchProvenanceError(
            "Native operator backing library cannot be read."
        ) from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise PackageSearchProvenanceError(
            "Native operator backing library changed while being read."
        )
    return "sha256:" + digest.hexdigest()


def _bounded_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise PackageSearchProvenanceError(f"{label} is invalid.")
    return value


def _bounded_array(value: Any, maximum: int, label: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise PackageSearchProvenanceError(f"{label} is not a bounded array.")
    return value


def _contains_key(value: Any, expected: str) -> bool:
    if isinstance(value, Mapping):
        return expected in value or any(
            _contains_key(item, expected) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, expected) for item in value)
    return False


def _looks_like_path(value: str) -> bool:
    return (
        value.startswith(("$", "/", "\\"))
        or _WINDOWS_ABSOLUTE.match(value) is not None
        or "/" in value
        or "\\" in value
    )


def _path_key(value: Path) -> str:
    return str(value).replace("\\", "/").casefold()


def _digest_bytes(value: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = ["PACKAGE_SEARCH_SCHEMA", "PackageSearchProvenanceError",
           "collect_effective_package_search", "decode_effective_package_search",
           "verify_effective_package_search"]
