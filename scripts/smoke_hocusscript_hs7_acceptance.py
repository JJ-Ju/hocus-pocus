"""Real Houdini 22.0.368 acceptance for HS7 editor, runtime, and value lanes."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import hou  # type: ignore

from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from smoke_hocusscript_h5 import _H5SmokeOperations, _preview_artifact
from smoke_hocusscript_hs7_acceptance_support import (
    apply_reconcile,
    assert_zero_cooks,
    compile_value_bundle,
    document_projection,
    expect_preview_rejection,
    export_recompile,
    preview_plan_apply,
    projection_differences,
    rollback_injection,
    save_reopen,
)


ROOTS = {
    "editor": "/obj/hs7_editor_acceptance",
    "runtime": "/obj/hs7_runtime_acceptance",
    "typed": "/obj/hs7_typed_acceptance",
}

EDITOR_SOURCE = '''hocus 0.4;
graph HS7Editor {
  target "/obj/hs7_editor_acceptance";
  category Sop;
  ownership "hs7";
  mode merge;
  layout = auto;
  display = dst;
  render = dst;
  output = dst;
  node src @id("editor.src"): "null" {}
  node dst @id("editor.dst"): "null" {}
  network_dot @id("editor.dot") {
    position = [1.0, 2.0];
    input = node src.output[0];
    outputs = [node dst.input[0]];
  }
  network_box @id("editor.box") {
    label = "HS7 Managed";
    position = [-1.0, -1.0];
    size = [7.0, 5.0];
    color = [0.25, 0.5, 0.75];
    items = [node src, dot "editor.dot"];
  }
  sticky_note @id("editor.note") {
    text = "HS7 source-authored";
    position = [4.0, 2.0];
    size = [3.0, 2.0];
    color = [0.75, 0.5, 0.25];
  }
  node_comment @id("editor.comment") {
    node = node src;
    text = "HS7 source";
  }
  layout_constraint @id("editor.layout") {
    kind = "align_y";
    items = [node dst, dot "editor.dot"];
    anchor = node src;
  }
}
'''

EDITOR_RECONCILE = EDITOR_SOURCE.replace(
    "mode merge;", "mode reconcile;",
).replace(
    '''  sticky_note @id("editor.note") {
    text = "HS7 source-authored";
    position = [4.0, 2.0];
    size = [3.0, 2.0];
    color = [0.75, 0.5, 0.25];
  }
  node_comment @id("editor.comment") {
    node = node src;
    text = "HS7 source";
  }
''',
    "",
)

RUNTIME_SOURCE = '''hocus 0.4;
graph HS7Runtime {
  target "/obj/hs7_runtime_acceptance";
  category Sop;
  ownership "hs7";
  mode merge;
  layout = auto;
  node runtime @id("runtime.node"): "null" {
    spare gain @id("runtime.spare.gain") {
      label = "Gain";
      type = "float";
      tuple_size = 1;
      default = [1.25];
      menu_items = [];
    }
    spare vector @id("runtime.spare.vector") {
      label = "Vector";
      type = "float";
      tuple_size = 3;
      default = [1.0, 2.0, 3.0];
      menu_items = [];
    }
    spare steps @id("runtime.spare.steps") {
      label = "Steps";
      type = "int";
      tuple_size = 1;
      default = 2;
      menu_items = [];
    }
    spare label_text @id("runtime.spare.label") {
      label = "Label";
      type = "string";
      tuple_size = 1;
      default = "ready";
      menu_items = [];
    }
    spare enabled @id("runtime.spare.enabled") {
      label = "Enabled";
      type = "toggle";
      tuple_size = 1;
      default = true;
      menu_items = [];
    }
    spare quality @id("runtime.spare.quality") {
      label = "Quality";
      type = "menu";
      tuple_size = 1;
      default = "high";
      menu_items = [["low", "Low"], ["high", "High"]];
    }
    animate gain @id("runtime.animation.gain") {
      value_type = "float";
      value = 1.25;
      authored_fps = 24.0;
      display_fps = 30.0;
      extrapolation = ["constant", "cycle"];
      keys = [
        [0.0, 1.25, "constant"],
        [1.0, 2.5, "linear"],
        [2.0, 1.0, "bezier", 0.0, 1.0]
      ];
    }
    animate steps @id("runtime.animation.steps") {
      value_type = "int";
      value = 2;
      authored_fps = 24.0;
      display_fps = 24.0;
      extrapolation = ["linear", "oscillate"];
      keys = [[0.0, 2, "constant"], [1.0, 4, "linear"]];
    }
  }
  display = runtime;
  render = runtime;
  output = runtime;
}
'''

RUNTIME_RECONCILE = '''hocus 0.4;
graph HS7Runtime {
  target "/obj/hs7_runtime_acceptance";
  category Sop;
  ownership "hs7";
  mode reconcile;
  layout = auto;
  node runtime @id("runtime.node"): "null" {}
  display = runtime;
  render = runtime;
  output = runtime;
}
'''

TYPED_SOURCE = '''hocus 0.4;
graph HS7Typed {
  target "/obj/hs7_typed_acceptance";
  category Sop;
  ownership "hs7";
  mode merge;
  layout = auto;
  node adjust @id("typed.adjust"): "attribadjustfloat" {
    remapramp = ramp(
      points = [[0.0, 0.1], [0.5, 0.8], [1.0, 0.2]],
      basis = ["constant", "linear", "bezier"]
    );
  }
  node add_prims @id("typed.add"): "add" {
    prims = multiparm(instances = [
      instance("triangle", { prim = "0 1 2"; closed = true; }),
      instance("line", { prim = "2 3"; closed = false; })
    ]);
  }
  display = add_prims;
  render = add_prims;
  output = add_prims;
}
'''

TYPED_RECONCILE = '''hocus 0.4;
graph HS7Typed {
  target "/obj/hs7_typed_acceptance";
  category Sop;
  ownership "hs7";
  mode reconcile;
  layout = auto;
  node adjust @id("typed.adjust"): "attribadjustfloat" {}
  node add_prims @id("typed.add"): "add" {}
  display = add_prims;
  render = add_prims;
  output = add_prims;
}
'''

_EDITOR_COLLECTIONS = (
    "nodes", "ports", "edges", "networkBoxes", "stickyNotes",
    "nodeComments", "networkDots", "layoutConstraints",
)
_RUNTIME_COLLECTIONS = ("nodes", "spareParameters", "animations")
_TYPED_COLLECTIONS = ("nodes", "parameterBindings")


class _HS7AcceptanceOperations(_H5SmokeOperations):
    def _document_preview_live_catalog(
        self, _graph_spec_version: str | None = None,
    ) -> Any:
        return self._catalog


def _progress(stage: str) -> None:
    print(f"HS7_EXT_STAGE {stage}", file=sys.stderr, flush=True)


def _prepare_roots(operations: Any) -> None:
    parent = hou.node("/obj")
    if parent is None:
        raise RuntimeError("Houdini /obj is unavailable for HS7 acceptance.")
    for label, path in ROOTS.items():
        if hou.node(path) is not None:
            raise RuntimeError(f"Refusing to reuse HS7 acceptance root: {path}.")
        parent.createNode(
            "geo",
            node_name=path.rsplit("/", 1)[-1],
            run_init_scripts=False,
            load_contents=False,
        )
        operations._document_stamp_live_node_uid(
            path, f"node:hs7:acceptance-root:{label}",
        )
    operations._monitor.mark_dirty("hs7.acceptance.roots")


def _project(
    operations: Any, root: str, collections: tuple[str, ...],
) -> dict[str, Any]:
    return document_projection(
        operations._document_current_network_payload(root, force_sync=True),
        collections=collections,
    )


def _assert_editor(document: dict[str, Any]) -> None:
    managed = [
        item for item in document["nodes"]
        if isinstance((item.get("metadata") or {}).get("hocus"), dict)
    ]
    pointers = {
        item["metadata"]["hocus"]["jsonPointer"] for item in managed
    }
    nodes = {item["uid"]: item for item in managed}
    if (
        pointers != {"/nodes/0", "/nodes/1"}
        or set(nodes) != {"editor.src", "editor.dst"}
    ):
        raise RuntimeError("HS7 editor node provenance changed.")
    src, dst = nodes["editor.src"], nodes["editor.dst"]
    if (
        (src["uid"], src["name"]) != ("editor.src", "src")
        or (dst["uid"], dst["name"]) != ("editor.dst", "dst")
    ):
        raise RuntimeError("HS7 direct root identity or live name changed.")
    dot = document["networkDots"]
    boxes = [
        item for item in document["networkBoxes"]
        if item.get("label") == "HS7 Managed"
    ]
    notes = [
        item for item in document["stickyNotes"]
        if item.get("text") == "HS7 source-authored"
    ]
    comments = [
        item for item in document["nodeComments"]
        if item.get("text") == "HS7 source"
    ]
    constraints = document["layoutConstraints"]
    if not all(len(value) == 1 for value in (dot, boxes, notes, comments, constraints)):
        raise RuntimeError("HS7 editor entities did not round-trip one-for-one.")
    route = dot[0]
    if (
        route["input"] != {
            "itemUid": src["uid"], "outputIndex": 0,
        }
        or route["outputs"] != [{
            "nodeUid": dst["uid"], "inputIndex": 0,
        }]
    ):
        raise RuntimeError("HS7 node-to-dot-to-node topology changed.")
    if set(boxes[0]["itemUids"]) != {src["uid"], route["uid"]}:
        raise RuntimeError("HS7 network-box membership changed.")
    if (
        src["position"][1] != dst["position"][1]
        or src["position"][1] != route["position"][1]
    ):
        raise RuntimeError("HS7 align_y layout constraint was not realized.")
    if (
        boxes[0]["label"] != "HS7 Managed"
        or notes[0]["text"] != "HS7 source-authored"
        or comments[0]["text"] != "HS7 source"
    ):
        raise RuntimeError("HS7 editor labels or comments changed.")


def _assert_runtime(document: dict[str, Any]) -> None:
    spares = {item["name"]: item for item in document["spareParameters"]}
    expected = {
        "gain": ("float", 1, [1.25]),
        "vector": ("float", 3, [1.0, 2.0, 3.0]),
        "steps": ("int", 1, 2),
        "label_text": ("string", 1, "ready"),
        "enabled": ("toggle", 1, True),
        "quality": ("menu", 1, "high"),
    }
    actual = {
        name: (item["type"], item["tupleSize"], item["default"])
        for name, item in spares.items()
    }
    if actual != expected:
        raise RuntimeError(
            f"HS7 managed spare contract changed: {actual!r}"
        )
    animations = {
        item["parmName"]: item for item in document["animations"]
    }
    if set(animations) != {"gain", "steps"}:
        raise RuntimeError("HS7 numeric animation targets changed.")
    if (
        [item["timeSeconds"] for item in animations["gain"]["keys"]]
        != [0.0, 1.0, 2.0]
        or [item["interpolation"] for item in animations["gain"]["keys"]]
        != ["constant", "linear", "bezier"]
        or animations["gain"]["extrapolation"]
        != {"before": "constant", "after": "cycle"}
        or any(
            type(item["value"]) is not int
            for item in animations["steps"]["keys"]
        )
    ):
        raise RuntimeError("HS7 seconds/key/interpolation contract changed.")


def _assert_typed(document: dict[str, Any]) -> None:
    bindings = {
        (item["parmName"], item["valueMode"]): item
        for item in document["parameterBindings"]
    }
    ramp = bindings.get(("remapramp", "ramp"))
    multiparm = bindings.get(("prims", "multiparm"))
    if (
        ramp is None
        or ramp["points"] != [
            {"position": 0.0, "value": 0.1},
            {"position": 0.5, "value": 0.8},
            {"position": 1.0, "value": 0.2},
        ]
        or ramp["basis"] != ["constant", "linear", "bezier"]
    ):
        raise RuntimeError("HS7 attribadjustfloat ramp changed.")
    if (
        multiparm is None
        or [item["instanceId"] for item in multiparm["instances"]]
        != ["triangle", "line"]
        or multiparm["instances"][0]["fields"]
        != [
            {"name": "prim", "value": {"kind": "literal", "value": "0 1 2"}},
            {"name": "closed", "value": {"kind": "literal", "value": True}},
        ]
        or multiparm["instances"][1]["fields"]
        != [
            {"name": "prim", "value": {"kind": "literal", "value": "2 3"}},
            {"name": "closed", "value": {"kind": "literal", "value": False}},
        ]
    ):
        raise RuntimeError("HS7 add.prims multiparm changed.")


def _only_child(root_path: str) -> Any:
    root = hou.node(root_path)
    children = tuple(root.children()) if root is not None else ()
    if len(children) != 1:
        raise RuntimeError(
            f"HS7 expected exactly one child below {root_path}, got {len(children)}."
        )
    return children[0]


def _child_of_type(root_path: str, type_name: str) -> Any:
    root = hou.node(root_path)
    matches = tuple(
        child for child in (root.children() if root is not None else ())
        if child.type().name() == type_name
    )
    if len(matches) != 1:
        raise RuntimeError(
            f"HS7 expected one {type_name} below {root_path}, got {len(matches)}."
        )
    return matches[0]


def _add_artist_spare() -> None:
    node = _only_child(ROOTS["runtime"])
    if node is None:
        raise RuntimeError("HS7 runtime node is unavailable for artist fixture.")
    group = node.parmTemplateGroup()
    group.append(hou.StringParmTemplate(
        "artist_note", "Artist Note", 1, default_value=("keep",),
    ))
    node.setParmTemplateGroup(group)
    if node.parm("artist_note") is None:
        raise RuntimeError("HS7 artist spare fixture was not created.")


def _add_artist_sticky() -> None:
    root = hou.node(ROOTS["editor"])
    sticky = root.createStickyNote()
    sticky.setText("Artist preserved")
    sticky.setPosition(hou.Vector2(9.0, 4.0))
    sticky.setSize(hou.Vector2(3.0, 2.0))


def _artist_state() -> dict[str, bool]:
    runtime = _only_child(ROOTS["runtime"])
    editor = hou.node(ROOTS["editor"])
    return {
        "spare": runtime is not None and runtime.parm("artist_note") is not None,
        "sticky": editor is not None and any(
            item.text() == "Artist preserved" for item in editor.stickyNotes()
        ),
    }


def _assert_reconciled_live_values() -> None:
    runtime = _only_child(ROOTS["runtime"])
    adjust = _child_of_type(ROOTS["typed"], "attribadjustfloat")
    add = _child_of_type(ROOTS["typed"], "add")
    if (
        runtime is None
        or any(runtime.parm(name) is not None for name in (
            "gain", "vector", "steps", "label_text", "enabled", "quality",
        ))
        or runtime.parm("artist_note") is None
    ):
        raise RuntimeError("HS7 runtime reconcile did not preserve only artist spares.")
    ramp = adjust.parm("remapramp") if adjust is not None else None
    prims = add.parm("prims") if add is not None else None
    if (
        ramp is None
        or not ramp.isAtDefault()
        or prims is None
        or not prims.isAtDefault()
    ):
        raise RuntimeError("HS7 typed reconcile did not restore Houdini defaults.")


def _time_sample_rejection(operations: Any) -> list[str]:
    document = operations._document_current_network_payload(
        ROOTS["runtime"], force_sync=True,
    )
    forged = copy.deepcopy(document)
    forged["timeSamples"] = [{"usdPath": "/World", "time": 1.0}]
    codes = {
        str(item.get("code"))
        for item in operations._document_validate_network_document(forged)
        if isinstance(item, dict)
    }
    if "animation.usd_time_samples.unsupported" not in codes:
        raise RuntimeError("HS7 unsupported USD time samples were not denied.")
    return sorted(codes)


def _locked_runtime_rejection(
    operations: Any,
    catalog: Any,
    _temporary_root: Path,
    context: RequestContext,
) -> dict[str, Any]:
    asset = hou.node("/obj/hs7_locked_boundary")
    if asset is None or not asset.isLockedHDA():
        return {
            "skipped": True,
            "reason": "the disposable locked-HDA fixture is unavailable",
        }
    source = RUNTIME_SOURCE.replace(
        ROOTS["runtime"], asset.path(),
    ).replace("graph HS7Runtime", "graph HS7RuntimeLocked")
    bundle = compile_value_bundle(
        source, label="runtime-locked", catalog=catalog,
    )
    codes = expect_preview_rejection(
        operations, bundle,
        codes={"document.locked_hda_boundary"},
        context=context,
    )
    return {"skipped": False, "rootPath": asset.path(), "diagnosticCodes": codes}


def _export_projection(
    operations: Any,
    *,
    root: str,
    graph_name: str,
    catalog: Any,
    context: RequestContext,
    assertion: Any,
) -> dict[str, Any]:
    bundle, source = export_recompile(
        operations, root_path=root, graph_name=graph_name,
        catalog=catalog, context=context,
    )
    preview = operations.document_preview_bundle(
        {"bundle": bundle}, context,
    )["structuredContent"]
    artifact = _preview_artifact(operations, preview)
    if not preview.get("valid"):
        raise RuntimeError(
            f"HS7 export/recompile changed {root}: "
            f"{preview.get('diagnostics')!r}; source={source!r}"
        )
    assertion(artifact["document"])
    return {
        "bundleDigest": bundle["bundleDigest"],
        "sourceDigest": "sha256:" + __import__("hashlib").sha256(
            source.encode("utf-8")
        ).hexdigest(),
        "sourceLength": len(source),
    }


def run_installed_hs7_acceptance(
    temporary_root: Path,
) -> dict[str, Any]:
    """Execute the installed extension without cooking any managed node."""

    _progress("catalog-v2")
    catalog = LiveHoudiniCatalogProvider(
        hou, catalog_version=2,
    ).get_catalog()
    operation_root = temporary_root / "hs7-extension"
    operation_root.mkdir(parents=True, exist_ok=True)
    operations = _HS7AcceptanceOperations(catalog, operation_root)
    context = RequestContext(
        caller_id="hs7-installed-extension",
        permissions=("observe", "edit_scene", "write_files"),
        timeout_seconds=300.0,
    )
    _prepare_roots(operations)
    authored = {
        "editor": EDITOR_SOURCE,
        "runtime": RUNTIME_SOURCE,
        "typed": TYPED_SOURCE,
    }
    sources = {
        "editor": EDITOR_RECONCILE,
        "runtime": RUNTIME_RECONCILE,
        "typed": TYPED_RECONCILE,
    }
    collections = {
        "editor": _EDITOR_COLLECTIONS,
        "runtime": _RUNTIME_COLLECTIONS,
        "typed": _TYPED_COLLECTIONS,
    }
    graph_names = {
        "editor": "HS7Editor",
        "runtime": "HS7Runtime",
        "typed": "HS7Typed",
    }
    assertions = {
        "editor": _assert_editor,
        "runtime": _assert_runtime,
        "typed": _assert_typed,
    }
    applies, initial, bundles = {}, {}, {}
    for label in ("editor", "runtime", "typed"):
        _progress(f"compile-{label}")
        bundles[label] = compile_value_bundle(
            authored[label], label=label, catalog=catalog,
        )
        _progress(f"apply-{label}")
        applies[label], candidate = preview_plan_apply(
            operations, bundles[label], label=label, context=context,
        )
        live = operations._document_current_network_payload(
            ROOTS[label], force_sync=True,
        )
        candidate_projection = document_projection(
            candidate, collections=collections[label],
        )
        live_projection = document_projection(
            live, collections=collections[label],
        )
        if candidate_projection != live_projection:
            raise RuntimeError(
                f"HS7 {label} preview did not match reimport: "
                f"{projection_differences(candidate_projection, live_projection)!r}"
            )
        assertions[label](live)
        initial[label] = document_projection(
            live, collections=collections[label],
        )
    _add_artist_spare()
    if not _artist_state()["spare"]:
        raise RuntimeError("HS7 artist-spare fixture is unavailable.")
    initial_cooks = assert_zero_cooks(tuple(ROOTS.values()))
    _progress("save-reopen")
    save_reopen(
        operations,
        operation_root / "hs7-real-acceptance.hip",
        context,
    )
    reopened = {}
    for label in ("editor", "runtime", "typed"):
        live = operations._document_current_network_payload(
            ROOTS[label], force_sync=True,
        )
        assertions[label](live)
        reopened[label] = document_projection(
            live, collections=collections[label],
        )
        if reopened[label] != initial[label]:
            raise RuntimeError(f"HS7 {label} changed across save/reopen.")
    if not _artist_state()["spare"]:
        raise RuntimeError("HS7 artist spare changed across save/reopen.")
    _progress("export-recompile")
    exported = {
        label: _export_projection(
            operations, root=ROOTS[label],
            graph_name=graph_names[label],
            catalog=catalog, context=context,
            assertion=assertions[label],
        )
        for label in ("editor", "runtime", "typed")
    }
    _progress("negative-boundaries")
    _add_artist_sticky()
    if _artist_state() != {"spare": True, "sticky": True}:
        raise RuntimeError("HS7 artist fixtures are unavailable.")
    time_samples = _time_sample_rejection(operations)
    locked = _locked_runtime_rejection(
        operations, catalog, temporary_root, context,
    )
    reconciles, rollbacks = {}, {}
    for label in ("editor", "runtime", "typed"):
        _progress(f"reconcile-rollback-{label}")
        reconcile_bundle = compile_value_bundle(
            sources[label], label=label, catalog=catalog,
        )
        reconciles[label] = apply_reconcile(
            operations, reconcile_bundle,
            label=f"{label}-reconcile", context=context,
        )
        rollbacks[label] = rollback_injection(
            operations, bundles[label], root_path=ROOTS[label],
            context=context,
            projection=lambda document, names=collections[label]:
                document_projection(document, collections=names),
        )
    reconciled = {
        label: _project(operations, ROOTS[label], collections[label])
        for label in ("editor", "runtime", "typed")
    }
    if (
        reconciled["runtime"]["spareParameters"]
        or reconciled["runtime"]["animations"]
        or any(
            item.get("uid") in {"editor.note", "editor.comment"}
            for field in ("stickyNotes", "nodeComments")
            for item in reconciled["editor"][field]
        )
        or reconciled["typed"]["parameterBindings"]
    ):
        raise RuntimeError("HS7 reconcile retained omitted managed entities.")
    if _artist_state() != {"spare": True, "sticky": True}:
        raise RuntimeError("HS7 reconcile removed artist-owned state.")
    _assert_reconciled_live_values()
    final_cooks = assert_zero_cooks(tuple(ROOTS.values()))
    return {
        "accepted": True,
        "catalogVersion": catalog.catalog_version,
        "apply": applies,
        "saveReopen": {
            "path": "hs7-real-acceptance.hip",
            "projectionsMatch": True,
        },
        "exportRecompile": exported,
        "reconcile": reconciles,
        "rollbackInjection": rollbacks,
        "unsupportedTimeSamples": {
            "denied": True, "diagnosticCodes": time_samples,
        },
        "lockedRuntimeBoundary": locked,
        "artistStatePreserved": _artist_state(),
        "cookCounts": {
            "initial": initial_cooks, "final": final_cooks,
        },
        "cookExecuted": False,
    }


def main() -> int:
    if hou.applicationVersionString() != "22.0.368":
        raise RuntimeError(
            "HS7 extension acceptance requires Houdini 22.0.368, got "
            f"{hou.applicationVersionString()}."
        )
    temporary = tempfile.TemporaryDirectory(prefix="hocuspocus-hs7-ext-")
    try:
        hou.hipFile.clear(suppress_save_prompt=True)
        result = run_installed_hs7_acceptance(
            Path(temporary.name).resolve(),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
