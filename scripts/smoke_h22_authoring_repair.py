"""Installed Houdini 22 proof for HDA values, authority, revisions, and undo."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

import hou  # type: ignore
import hocuspocus

from hocuspocus.core.server import HocusPocusRuntime
from hocuspocus.core.settings import ServerSettings


def _installed_module_path() -> Path:
    module_path = Path(hocuspocus.__file__).resolve()
    checkout = Path(__file__).resolve().parents[1]
    if checkout == module_path or checkout in module_path.parents:
        raise RuntimeError("Authoring repair smoke loaded source-tree modules.")
    return module_path


def _runtime(root: Path, *, allow_file_write: bool = True) -> HocusPocusRuntime:
    settings = ServerSettings(
        token_mode="disabled",
        auto_start=False,
        policy_profile="procedural-authoring",
        allow_scene_edit=True,
        allow_file_write=allow_file_write,
        enable_exec_tools=True,
        approved_roots=[str(root)],
    )
    runtime = HocusPocusRuntime(
        settings, logging.getLogger("hocuspocus.authoring-repair-smoke")
    )
    runtime.dispatcher.start()
    runtime.monitor.start()
    return runtime


def _request(
    runtime: HocusPocusRuntime,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return runtime.handle_request(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        principal_id="installed-h22-authoring-repair",
    )


def _call(
    runtime: HocusPocusRuntime,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = _request(runtime, request_id, name, arguments)
    if "error" in response:
        raise RuntimeError(f"{name} failed: {response['error']!r}")
    return response["result"]["structuredContent"]


def _expect_error(
    runtime: HocusPocusRuntime,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    response = _request(runtime, request_id, name, arguments)
    error = response.get("error")
    if not isinstance(error, dict):
        raise RuntimeError(f"{name} unexpectedly succeeded: {response!r}")
    return error


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_asset(path: Path) -> Any:
    geo = hou.node("/obj").createNode("geo", "hocus_authoring_source")
    box = geo.createNode("box", "box1")
    box.parmTuple("size").set((4.0, 2.0, 1.0))
    box.parm("type").set(1)
    instance = geo.createDigitalAsset(
        name="hocuspocus::authoring_repair_smoke::1.0",
        hda_file_name=str(path),
        description="HocusPocus authoring repair smoke",
        version="1.0",
        create_backup=False,
    )
    instance.matchCurrentDefinition()
    return instance


def _prove_hda_authoring(
    runtime: HocusPocusRuntime,
    instance: Any,
    hda_path: Path,
) -> dict[str, Any]:
    instance_path = instance.path()
    promoted = _call(
        runtime,
        10,
        "hda.promote_parm",
        {
            "instance_path": instance_path,
            "source_parm_path": f"{instance_path}/box1/sizex",
            "promoted_name": "box_size",
        },
    )
    if promoted["capturedSourceValue"] != [4.0, 2.0, 1.0]:
        raise RuntimeError("Promotion did not preserve the Box size tuple.")
    updated = _call(
        runtime,
        11,
        "hda.set_instance_parms",
        {
            "instance_path": instance_path,
            "assignments": [{"name": "box_size", "value": [5.0, 3.0, 2.0]}],
        },
    )
    if tuple(instance.parmTuple("box_size").eval()) != (5.0, 3.0, 2.0):
        raise RuntimeError("Locked HDA interface update did not reach the instance.")
    menu = _call(
        runtime,
        12,
        "hda.promote_parm",
        {
            "instance_path": instance_path,
            "source_parm_path": f"{instance_path}/box1/type",
            "promoted_name": "box_type",
        },
    )
    if menu["capturedSourceValue"] != [1]:
        raise RuntimeError("Menu promotion did not preserve its integer default.")
    menu_parm = instance.parm("box_type")
    menu_token = menu_parm.parmTemplate().menuItems()[0]
    menu_update = _call(
        runtime,
        14,
        "hda.set_instance_parms",
        {
            "instance_path": instance_path,
            "assignments": [{"name": "box_type", "value": menu_token}],
        },
    )
    if menu_parm.eval() != 0:
        raise RuntimeError("Menu-token interface update did not canonicalize to index 0.")

    instance.allowEditingOfContents()
    animated = instance.node("box1").parm("divrate1")
    animated.setExpression("$F", language=hou.exprLanguage.Hscript)
    instance.type().definition().updateFromNode(instance)
    instance.matchCurrentDefinition()
    before_rejection = _digest(hda_path)
    rejected = _expect_error(
        runtime,
        13,
        "hda.promote_parm",
        {
            "instance_path": instance_path,
            "source_parm_path": f"{instance_path}/box1/divrate1",
            "promoted_name": "animated_divisions",
        },
    )
    if _digest(hda_path) != before_rejection:
        raise RuntimeError("Rejected animated promotion changed the HDA library.")
    return {
        "preservedValue": promoted["capturedSourceValue"],
        "updatedValue": updated["assignments"][0]["value"],
        "menuValue": menu["capturedSourceValue"],
        "menuTokenValue": menu_update["assignments"][0]["value"],
        "animatedPromotionError": rejected["message"],
    }


def _prove_write_authority(instance: Any, hda_path: Path, root: Path) -> str:
    runtime = _runtime(root, allow_file_write=False)
    try:
        before = _digest(hda_path)
        error = _expect_error(
            runtime,
            20,
            "hda.promote_parm",
            {
                "instance_path": instance.path(),
                "source_parm_path": f"{instance.path()}/box1/scale",
                "promoted_name": "blocked_scale",
            },
        )
        if _digest(hda_path) != before:
            raise RuntimeError("File-write denial changed the HDA library.")
        missing = (error.get("data") or {}).get("missingCapabilities", [])
        if "write_files" not in missing:
            raise RuntimeError(f"HDA mutation did not require write_files: {error!r}")
        return str((error.get("data") or {}).get("errorFamily", "policy"))
    finally:
        runtime.monitor.stop()
        runtime.dispatcher.stop()
        runtime.workspace_authority.close()
        runtime.operation_history.close()


def _prove_undo_and_revisions(runtime: HocusPocusRuntime) -> dict[str, Any]:
    geo = hou.node("/obj").createNode("geo", "hocus_undo_parent")
    before_revision = runtime.monitor.snapshot()["structuralRevision"]
    created = _call(
        runtime,
        30,
        "node.create",
        {
            "parent_path": geo.path(),
            "node_type_name": "null",
            "node_name": "undo_target",
        },
    )
    after_revision = runtime.monitor.snapshot()["structuralRevision"]
    if after_revision != before_revision + 1:
        raise RuntimeError("One node.create did not produce one structural revision.")
    undo_labels = tuple(hou.undos.undoLabels())
    if not undo_labels:
        raise RuntimeError("Houdini did not expose the node.create undo entry.")
    undone = _call(
        runtime,
        31,
        "scene.undo",
        {"expected_label": undo_labels[0]},
    )
    if hou.node(created["path"]) is not None:
        raise RuntimeError("Guarded Houdini 22 undo left the created node present.")
    redo_labels = tuple(hou.undos.redoLabels())
    if not redo_labels:
        raise RuntimeError("Houdini did not expose the node.create redo entry.")
    redone = _call(
        runtime,
        32,
        "scene.redo",
        {"expected_label": redo_labels[0]},
    )
    if hou.node(created["path"]) is None:
        raise RuntimeError("Guarded Houdini 22 redo did not restore the node.")
    return {
        "structuralRevisionDelta": after_revision - before_revision,
        "undoLabel": undo_labels[0],
        "undo": undone["stackAction"],
        "redo": redone["stackAction"],
    }


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    module_path = _installed_module_path()
    hou.hipFile.clear(suppress_save_prompt=True)
    with tempfile.TemporaryDirectory(prefix="hocuspocus-authoring-") as raw:
        root = Path(raw)
        hda_path = root / "authoring_repair.hda"
        instance = _create_asset(hda_path)
        runtime = _runtime(root)
        try:
            session = _call(runtime, 1, "session.info", {})
            if "run_code" not in session.get("grantedCapabilities", []):
                raise RuntimeError("Procedural authoring profile lacks run_code.")
            hda = _prove_hda_authoring(runtime, instance, hda_path)
            authority = _prove_write_authority(instance, hda_path, root)
            undo = _prove_undo_and_revisions(runtime)
            print(json.dumps({
                "houdiniVersion": hou.applicationVersionString(),
                "modulePath": str(module_path),
                "hda": hda,
                "writeAuthorityDenial": authority,
                "undoAndRevisions": undo,
            }, sort_keys=True))
            return 0
        finally:
            runtime.monitor.stop()
            runtime.dispatcher.stop()
            runtime.workspace_authority.close()
            runtime.operation_history.close()


if __name__ == "__main__":
    raise SystemExit(main())
