"""Exact nested validation for effective package-search receipts."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from hocuspocus.hocusscript.build_provenance import canonical_digest


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCATOR = re.compile(
    r"^(?:hocus-install|houdini-install|hocus-search)://.{0,8160}$"
)
_CONDITIONS = {
    "enable", "load_package_once", "package_path", "process_order",
    "recommends", "requires",
}


def validate_package_search_receipt(value: Mapping[str, Any]) -> None:
    """Validate every nested field, type, order, and derived digest."""

    _object(value["houdini"], {
        "product", "version", "build", "platform", "featureFlags",
    }, "houdini")
    houdini = value["houdini"]
    for field in ("product", "version", "build", "platform"):
        _text(houdini[field], f"houdini.{field}")
    flags = _array(houdini["featureFlags"], 4096, "houdini.featureFlags")
    if flags != sorted(set(flags)) or any(not _valid_text(item) for item in flags):
        _fail("Houdini feature flags are invalid or non-canonical.")

    _object(value["installedPayload"], {
        "rootLocator", "rootDigest", "manifestDigest", "artifactCount",
    }, "installedPayload")
    installed = value["installedPayload"]
    if installed["rootLocator"] != "hocus-install://root":
        _fail("Installed payload root locator is invalid.")
    _digest(installed["rootDigest"], "installedPayload.rootDigest")
    _digest(installed["manifestDigest"], "installedPayload.manifestDigest")
    _integer(installed["artifactCount"], 1, 20_000, "artifactCount")

    trace = _trace(value["packageTrace"])
    packages = _packages(value["packages"], trace)
    search = value["searchOrder"]
    _object(search, {"package", "houdini", "hda", "python"}, "searchOrder")
    for kind in ("package", "houdini", "hda", "python"):
        _search_rows(search[kind], kind)

    operators, hda_libraries = _operators(value["operatorWinners"])
    shadows = _shadows(value["shadowing"], operators)
    hda_libraries.update(item["shadowedLocator"] for item in shadows)
    if value["loadedLibraryDigest"] != canonical_digest(sorted(hda_libraries)):
        _fail("Loaded-library digest is inconsistent.")

    _object(value["precedence"], {
        "packageProcessing", "searchOrderDigest", "operatorWinnerDigest",
    }, "precedence")
    precedence = value["precedence"]
    processing = _array(
        precedence["packageProcessing"], 4096, "packageProcessing",
    )
    if any(not _valid_locator(item) for item in processing):
        _fail("Package processing contains an invalid locator.")
    expected_processing = [
        item["sourceLocator"]
        for item in sorted(
            (row for row in packages if row["loaded"]),
            key=lambda row: row["evaluationRank"],
        )
    ]
    if processing != expected_processing or processing != trace["processed"]:
        _fail("Package processing order is inconsistent.")
    if precedence["searchOrderDigest"] != canonical_digest(search):
        _fail("Search-order digest is inconsistent.")
    if precedence["operatorWinnerDigest"] != canonical_digest(operators):
        _fail("Operator-winner digest is inconsistent.")


def _trace(value: Any) -> dict[str, Any]:
    _object(value, {
        "authority", "events", "loadedLocators", "disabledLocators",
        "skippedLocators", "traceDigest",
    }, "packageTrace")
    if value["authority"] != "HOUDINI_PACKAGE_VERBOSE=1":
        _fail("Package-trace authority is invalid.")
    events = _array(value["events"], 12_288, "packageTrace.events")
    for rank, event in enumerate(events):
        _object(event, {"rank", "kind", "sourceLocator"}, "trace event")
        if (
            event["rank"] != rank
            or event["kind"] not in {"discovered", "processed", "load_once"}
            or not _valid_locator(event["sourceLocator"])
        ):
            _fail("Package-trace event is invalid or out of order.")
    result: dict[str, Any] = {}
    for status in ("loaded", "disabled", "skipped"):
        field = status + "Locators"
        rows = _array(value[field], 4096, f"packageTrace.{field}")
        if len(rows) != len(set(rows)) or any(
            not _valid_locator(item) for item in rows
        ):
            _fail(f"Package-trace {status} locators are invalid.")
        result[status] = rows
    if (
        set(result["loaded"]).intersection(result["disabled"])
        or set(result["loaded"]).intersection(result["skipped"])
        or set(result["disabled"]).intersection(result["skipped"])
    ):
        _fail("Package-trace status sets overlap.")
    result["discovered"] = [
        item["sourceLocator"] for item in events
        if item["kind"] == "discovered"
    ]
    result["processed"] = [
        item["sourceLocator"] for item in events
        if item["kind"] == "processed"
    ]
    if (
        len(result["discovered"]) != len(set(result["discovered"]))
        or len(result["processed"]) != len(set(result["processed"]))
        or set(result["processed"]) != set(result["loaded"])
        or set(result["discovered"]) != set(
            result["loaded"] + result["disabled"] + result["skipped"]
        )
    ):
        _fail("Package-trace events disagree with their status summaries.")
    unsigned = {key: item for key, item in value.items() if key != "traceDigest"}
    if value["traceDigest"] != canonical_digest(unsigned):
        _fail("Package-trace digest is inconsistent.")
    return result


def _packages(value: Any, trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _array(value, 4096, "packages")
    fields = {
        "name", "sourceLocator", "contentDigest", "byteLength", "loaded",
        "status", "discoveryRank", "evaluationRank", "processOrder",
        "conditionKeys", "conditionDigest", "evaluatedDigest",
        "declaresHocusPocusRoot",
    }
    for rank, row in enumerate(rows):
        _package_row(row, fields, rank)
    if [row["sourceLocator"] for row in rows] != trace["discovered"]:
        _fail("Package rows disagree with trace discovery order.")
    for status in ("loaded", "disabled", "skipped"):
        if {
            row["sourceLocator"] for row in rows if row["status"] == status
        } != set(trace[status]):
            _fail("Package rows disagree with trace status.")
    ranks = sorted(row["evaluationRank"] for row in rows if row["loaded"])
    if ranks != list(range(len(ranks))):
        _fail("Package evaluation ranks are not contiguous.")
    return rows


def _package_row(row: Any, fields: set[str], rank: int) -> None:
    _object(row, fields, "package")
    _text(row["name"], "package.name")
    if not _valid_locator(row["sourceLocator"]):
        _fail("Package source locator is invalid.")
    _digest(row["contentDigest"], "package.contentDigest")
    _integer(row["byteLength"], 0, 1024 * 1024, "package.byteLength")
    if row["status"] not in {"loaded", "disabled", "skipped"}:
        _fail("Package status is invalid.")
    if (
        type(row["loaded"]) is not bool
        or row["loaded"] is not (row["status"] == "loaded")
        or row["discoveryRank"] != rank
    ):
        _fail("Package discovery status or order is inconsistent.")
    _integer(row["evaluationRank"], -1, 4095, "evaluationRank")
    if row["loaded"] is not (row["evaluationRank"] >= 0):
        _fail("Package evaluation rank is inconsistent.")
    order = row["processOrder"]
    if order is not None and (
        isinstance(order, bool)
        or not isinstance(order, (int, float))
        or not math.isfinite(order)
    ):
        _fail("Package process_order is invalid.")
    keys = _array(row["conditionKeys"], 6, "conditionKeys")
    if keys != sorted(set(keys)) or not set(keys).issubset(_CONDITIONS):
        _fail("Package condition keys are invalid or non-canonical.")
    _digest(row["conditionDigest"], "conditionDigest")
    _digest(row["evaluatedDigest"], "evaluatedDigest")
    if type(row["declaresHocusPocusRoot"]) is not bool:
        _fail("Package root declaration flag is invalid.")


def _search_rows(value: Any, kind: str) -> None:
    rows = _array(value, 4096, f"{kind} search rows")
    seen = set()
    for rank, row in enumerate(rows):
        _object(row, {"rank", "locator", "exists", "directory"}, "search row")
        if (
            row["rank"] != rank
            or not _valid_locator(row["locator"])
            or row["locator"] in seen
            or type(row["exists"]) is not bool
            or type(row["directory"]) is not bool
            or row["directory"] and not row["exists"]
        ):
            _fail("Search row is invalid or non-canonical.")
        seen.add(row["locator"])


def _operators(value: Any) -> tuple[list[dict[str, Any]], set[str]]:
    rows = _array(value, 16_384, "operatorWinners")
    if rows != sorted(
        rows, key=lambda item: (item.get("category", ""), item.get("qualifiedName", "")),
    ):
        _fail("Operator winners are not in canonical order.")
    identities = set()
    hda_libraries = set()
    for row in rows:
        _object(row, {
            "category", "qualifiedName", "sourceKind", "packageId", "winner",
        }, "operator winner")
        _text(row["category"], "operator.category")
        _text(row["qualifiedName"], "operator.qualifiedName")
        identity = (row["category"], row["qualifiedName"])
        if identity in identities:
            _fail("Operator winner identity is duplicated.")
        identities.add(identity)
        if row["sourceKind"] not in {"builtin", "package", "labs", "hda"}:
            _fail("Operator source kind is invalid.")
        if row["packageId"] is not None:
            _text(row["packageId"], "operator.packageId")
        library = _operator_winner(row)
        if library is not None:
            hda_libraries.add(library)
    return rows, hda_libraries


def _operator_winner(row: dict[str, Any]) -> str | None:
    winner = row["winner"]
    if not isinstance(winner, dict):
        _fail("Operator winner identity is absent.")
    kind = winner.get("kind")
    if kind == "internal":
        _object(winner, {"kind", "sourceType"}, "internal winner")
        if (
            row["sourceKind"] != "builtin"
            or row["packageId"] is not None
            or winner["sourceType"] != "Internal"
        ):
            _fail("Internal operator winner is unexplained.")
        return None
    if kind == "binary":
        _binary_winner(row, winner)
        return None
    if kind == "hda":
        return _hda_winner(row, winner)
    _fail("Operator winner kind is unsupported.")


def _binary_winner(row: dict[str, Any], winner: dict[str, Any]) -> None:
    _object(winner, {
        "kind", "sourceType", "libraryLocator", "contentDigest", "byteLength",
    }, "binary winner")
    if row["sourceKind"] == "hda" or winner["sourceType"] != "CompiledCode":
        _fail("Binary operator source type is inconsistent.")
    if not _valid_locator(winner["libraryLocator"]):
        _fail("Binary operator locator is invalid.")
    _digest(winner["contentDigest"], "binary.contentDigest")
    _integer(
        winner["byteLength"], 0, 2 * 1024 * 1024 * 1024,
        "binary.byteLength",
    )


def _hda_winner(row: dict[str, Any], winner: dict[str, Any]) -> str:
    _object(winner, {
        "kind", "libraryLocator", "contentDigest", "version", "preferred",
    }, "HDA winner")
    if row["sourceKind"] != "hda" or not _valid_locator(winner["libraryLocator"]):
        _fail("HDA winner source or locator is inconsistent.")
    _digest(winner["contentDigest"], "HDA contentDigest")
    if winner["version"] is not None:
        _text(winner["version"], "HDA version")
    if type(winner["preferred"]) is not bool:
        _fail("HDA preferred flag is invalid.")
    return winner["libraryLocator"]


def _shadows(value: Any, operators: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _array(value, 16_384, "shadowing")
    expected = sorted(rows, key=lambda item: (
        item.get("category", ""), item.get("qualifiedName", ""),
        item.get("shadowedLocator", ""),
    ))
    if rows != expected:
        _fail("HDA shadow records are not in canonical order.")
    winners = {
        (item["category"], item["qualifiedName"]): item["winner"]
        for item in operators
    }
    seen = set()
    for row in rows:
        _object(row, {
            "category", "qualifiedName", "winnerLocator", "shadowedLocator",
            "shadowedDigest",
        }, "HDA shadow")
        key = (row["category"], row["qualifiedName"], row["shadowedLocator"])
        winner = winners.get(key[:2])
        if (
            key in seen
            or not isinstance(winner, dict)
            or winner.get("kind") != "hda"
            or row["winnerLocator"] != winner["libraryLocator"]
            or not _valid_locator(row["shadowedLocator"])
            or row["shadowedLocator"] == row["winnerLocator"]
        ):
            _fail("HDA shadow record is inconsistent.")
        _digest(row["shadowedDigest"], "shadowedDigest")
        seen.add(key)
    return rows


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(f"{label} has an invalid exact envelope.")
    return value


def _array(value: Any, maximum: int, label: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail(f"{label} is not a bounded array.")
    return value


def _text(value: Any, label: str) -> str:
    if not _valid_text(value):
        _fail(f"{label} is invalid.")
    return value


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value.encode("utf-8")) <= 1024


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        _fail(f"{label} is invalid.")
    return value


def _valid_locator(value: Any) -> bool:
    return isinstance(value, str) and _LOCATOR.fullmatch(value) is not None


def _integer(value: Any, low: int, high: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        _fail(f"{label} is invalid.")
    return value


def _fail(message: str) -> None:
    raise ValueError(message)


__all__ = ["validate_package_search_receipt"]
