"""Installed-Houdini smoke for the first-use MCP authoring workflow."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import hou  # type: ignore
import hocuspocus

from hocuspocus.core.settings import ServerSettings
from hocuspocus.core.server import HocusPocusRuntime


def _installed_module_path() -> Path:
    module_path = Path(hocuspocus.__file__).resolve()
    checkout_root = Path(__file__).resolve().parents[1]
    if checkout_root == module_path or checkout_root in module_path.parents:
        raise RuntimeError("Smoke loaded HocusPocus from the source checkout.")
    return module_path


def _runtime(logger: logging.Logger) -> HocusPocusRuntime:
    runtime = HocusPocusRuntime(
        ServerSettings(token_mode="disabled", auto_start=False),
        logger,
    )
    runtime.dispatcher.start()
    runtime.monitor.start()
    return runtime


def _call(
    runtime: HocusPocusRuntime,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = runtime.handle_request(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        principal_id="installed-h22-smoke",
    )
    if not isinstance(response, dict) or "error" in response:
        raise RuntimeError(f"{name} failed: {response!r}")
    return response["result"]["structuredContent"]


def _discover(runtime: HocusPocusRuntime) -> None:
    listed = runtime.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        },
        principal_id="installed-h22-smoke",
    )
    tools = {item["name"]: item for item in listed["result"]["tools"]}
    if "object.create_geometry" not in tools:
        raise RuntimeError("Geometry bootstrap is not publicly discoverable.")
    tasks = tools["node_types.list_compatible"]["inputSchema"]["properties"][
        "task"
    ]["enum"]
    if "copying" not in tasks:
        raise RuntimeError("Compatibility task enum is missing copying.")


def _assert_copy_metadata(runtime: HocusPocusRuntime) -> dict[str, Any]:
    copy_info = _call(
        runtime,
        3,
        "node_types.get_info",
        {
            "category": "Sop",
            "type_name": "copytopoints",
            "detail_level": "full_parms",
        },
    )
    key_parms = {item.get("name") for item in copy_info.get("keyParms", [])}
    if (
        copy_info.get("typeName") != "copytopoints"
        or copy_info.get("typeId") != "Sop/copytopoints"
        or "pack" not in key_parms
    ):
        raise RuntimeError("Copy to Points metadata did not resolve.")
    qualified = _call(
        runtime,
        31,
        "node_types.get_info",
        {"type_id": "Sop/copytopoints", "detail_level": "key_parms"},
    )
    if qualified.get("typeName") != "copytopoints":
        raise RuntimeError("Category-qualified Copy to Points metadata did not resolve.")
    return copy_info


def _assert_catalog_search(runtime: HocusPocusRuntime) -> tuple[dict[str, Any], dict[str, Any]]:
    bevel_search = _call(
        runtime,
        32,
        "node_types.list",
        {"category": "Sop", "query": "poly bevel", "limit": 20},
    )
    if not any(
        str(item.get("typeName", "")).startswith("polybevel")
        for item in bevel_search.get("items", [])
    ):
        raise RuntimeError("Token-normalized PolyBevel search returned no result.")
    intent = _call(
        runtime,
        4,
        "node_types.list_compatible",
        {
            "intent": "copy geometry onto points",
            "category": "Sop",
            "limit": 20,
        },
    )
    if intent.get("resolvedTask") != "copying":
        raise RuntimeError("Compatibility intent did not resolve to copying.")
    return bevel_search, intent


def _exercise_first_use(
    runtime: HocusPocusRuntime,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    _discover(runtime)
    bootstrap = _call(
        runtime,
        2,
        "object.create_geometry",
        {"name": "hocus_first_use", "unique_name": True},
    )
    root_path = str(bootstrap["rootPath"])
    if (
        hou.node(root_path) is None
        or bootstrap.get("document", {}).get("rootPath") != root_path
    ):
        raise RuntimeError("Geometry bootstrap did not return its live SOP document.")
    copy_info = _assert_copy_metadata(runtime)
    bevel_search, intent = _assert_catalog_search(runtime)
    checkout = _call(
        runtime,
        5,
        "document.checkout",
        {"scope": "network", "root_path": root_path},
    )
    if (
        checkout.get("documentDelivery", {}).get("mode") != "inline"
        or checkout.get("document", {}).get("rootPath") != root_path
    ):
        raise RuntimeError("Small checkout was not returned inline.")
    plan = _call(
        runtime,
        6,
        "document.apply",
        {"checkout_id": bootstrap["checkoutId"], "mode": "validate_only"},
    )
    if plan.get("mode") != "validate_only" or plan.get("applied") is not False:
        raise RuntimeError("Bootstrap checkout did not reach document planning.")
    return bootstrap, checkout, copy_info, bevel_search, intent


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger("hocuspocus.first-use-smoke")
    module_path = _installed_module_path()
    runtime = _runtime(logger)
    bootstrap: dict[str, Any] | None = None
    checkout: dict[str, Any] | None = None
    hou.hipFile.clear(suppress_save_prompt=True)
    try:
        bootstrap, checkout, copy_info, bevel_search, intent = _exercise_first_use(
            runtime
        )
        root_path = str(bootstrap["rootPath"])
        print(
            json.dumps(
                {
                    "houdiniVersion": hou.applicationVersionString(),
                    "modulePath": str(module_path),
                    "rootPath": root_path,
                    "bootstrapDelivery": bootstrap["documentDelivery"]["mode"],
                    "checkoutDelivery": checkout["documentDelivery"]["mode"],
                    "copyToPointsParmCount": len(copy_info.get("allParms", [])),
                    "copyToPointsTypeId": copy_info["typeId"],
                    "polyBevelSearchCount": bevel_search["count"],
                    "resolvedTask": intent["resolvedTask"],
                    "resolutionKind": intent["resolutionKind"],
                    "matchedTerms": intent["matchedTerms"],
                    "planMode": "validate_only",
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        if checkout is not None:
            _call(
                runtime,
                7,
                "document.discard_checkout",
                {"checkout_id": checkout["checkoutId"]},
            )
        if bootstrap is not None:
            admission = (
                runtime.operations._graph_store.get_document_by_root_path(
                    bootstrap["rootPath"]
                )
            )
            if admission is None:
                raise RuntimeError("Installed smoke lost its graph-store admission.")
            _call(
                runtime,
                8,
                "document.discard_checkout",
                {"checkout_id": bootstrap["checkoutId"]},
            )
            _call(
                runtime,
                9,
                "node.delete",
                {"path": bootstrap["rootPath"], "ignore_missing": True},
            )
            removed = runtime.operations._graph_store.discard_document_admission(
                admission
            )
            residue = runtime.operations._graph_store.get_document_by_root_path(
                bootstrap["rootPath"]
            )
            if not removed or residue is not None:
                raise RuntimeError("Installed smoke left a graph-store document behind.")
        runtime.monitor.stop()
        runtime.dispatcher.stop()
        runtime.workspace_authority.close()


if __name__ == "__main__":
    raise SystemExit(main())
