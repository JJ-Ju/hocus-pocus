"""The ``rop_image`` backend: a Copernicus node's image through a temporary ``rop_image``
in its own network (review 18 papercut 1), in the host, GUI and headless alike (COPs need
no child hython). About 0.2 s. Also the COP helpers ``geo_info``/``inspect what: image``
use (:func:`image_summary`)."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import hint_tool

from ..tools.geo import num
from ..tools.readers import stale_file_notes
from ..tools.registry import HostContext
from .base import INTERNAL_KEY, Backend, Env, LookResult, failure, mark_internal, on_main

CHANNEL_NAMES = {1: ("mono",), 2: ("u", "v"), 3: ("r", "g", "b"), 4: ("r", "g", "b", "a")}
NON_IMAGE_OUTPUTS = ("Geometry", "VDB")


def is_cop_node(node: Any) -> bool:
    """A Copernicus node (category ``Cop``)."""
    import hou

    return isinstance(node, hou.CopNode)


def is_cop_network(node: Any) -> bool:
    """A network whose children are Copernicus nodes (``/img/<copnet>``, a SOP copnet)."""
    import hou

    try:
        return node.childTypeCategory() == hou.copNodeTypeCategory()
    except Exception:
        return False


def cop_display(net: Any) -> Any:
    """The display-flagged Cop node in a COP network, or None."""
    for child in net.children():
        with contextlib.suppress(Exception):
            if child.isDisplayFlagSet():
                return child
    return None


def cop_image_node(node: Any) -> Any:
    """``node`` when it is a Cop node, a COP network's display node, else None."""
    if is_cop_node(node):
        return node
    if is_cop_network(node):
        return cop_display(node)
    return None


def _rect(rect: Any) -> list[Any]:
    """``[xmin, ymin, xmax, ymax]`` of a ``hou.BoundingRect``."""
    return [num(v, 6) for v in (*rect.min(), *rect.max())]


def _channel_stats(layer: Any, count: int) -> dict[str, Any]:
    names = CHANNEL_NAMES.get(count) or tuple(f"c{i}" for i in range(count))
    stats: dict[str, Any] = {}
    for index, name in enumerate(names):
        with contextlib.suppress(Exception):
            stats[name] = {
                "min": num(layer.computeMin(index), 6),
                "max": num(layer.computeMax(index), 6),
                "mean": num(layer.computeAverage(index), 6),
            }
    return stats


def image_summary(node: Any, frame: float | None = None, *, stats: bool = True) -> dict[str, Any]:
    """What a Cop node's first output holds (review 18 papercut 3): ``{output, layer_type,
    resolution, data_window, pixel_scale, storage, border, constant?, channels: {name:
    {min, max, mean}}}`` from ``CopNode.layer()``; other outputs are named in
    ``other_outputs``. A non-image output (geometry, VDB) has only its type. Main thread."""
    names = list(node.outputNames())
    types = list(node.outputDataTypes())
    out: dict[str, Any] = {"output": names[0] if names else None}
    out["layer_type"] = types[0] if types else None
    layer = node.layer(0) if frame is None else node.layerAtFrame(float(frame), 0)
    if layer is not None:
        out["resolution"] = list(layer.bufferResolution())
        out["data_window"] = _rect(layer.dataWindow())
        out["pixel_scale"] = [num(v, 6) for v in layer.pixelScale()]
        with contextlib.suppress(Exception):
            out["storage"] = layer.storageType().name().lower()
            out["border"] = layer.border().name().lower()
        with contextlib.suppress(Exception):
            if layer.isConstant():
                out["constant"] = True
        if stats:
            out["channels"] = _channel_stats(layer, int(layer.channelCount()))
    others = [
        {"name": name, "layer_type": types[i] if i < len(types) else None}
        for i, name in enumerate(names)
        if i > 0
    ]
    if others:
        out["other_outputs"] = others
    return out


def render_cop(
    ctx: HostContext, node: Any, frame: float, out_file: str, *, resolution_given: bool = False
) -> dict[str, Any]:
    """Render the Cop ``node`` through a temporary ``rop_image`` in its network to
    ``out_file`` (review 18 papercut 1) and return the capture's ``info``. The ROP is made
    outside undo and events and deleted afterwards; about 0.2 s. Main thread."""
    import hou

    from ..tools.events import muted

    types = list(node.outputDataTypes())
    if types and types[0] in NON_IMAGE_OUTPUTS:
        raise ToolError(
            "invalid_argument",
            f"{node.path()} outputs {types[0]}, not an image layer.",
            hint=f"{hint_tool('geo_info', path=node.path())} reads it; capture an image node "
            "instead.",
        )
    # D80: a File COP keeps the image it loaded after its file is overwritten.
    stale = stale_file_notes(node, frame)
    errors: list[str] = []
    with hou.undos.disabler(), muted():
        rop = node.parent().createNode("rop_image", "__hocuspocus_capture__")
        try:
            mark_internal(rop)
            for name, value in (("coppath", node.path()), ("copoutput", out_file), ("trange", 0)):
                rop.parm(name).set(value)
            try:
                rop.render(frame_range=(frame, frame), verbose=False)
            except hou.OperationFailed as exc:
                errors.append(str(exc).strip())
            errors += [str(e) for e in rop.errors()]
        finally:
            with contextlib.suppress(Exception):
                rop.destroy()
    if errors or not os.path.isfile(out_file):
        message, detail = failure(f"{node.path()} did not render an image", errors)
        raise ToolError(
            "cook_failed",
            message,
            hint=f"Check the node's errors with {hint_tool('problems', root=node.path())}, "
            "then capture again.",
            detail=detail or None,
        )
    layer = image_summary(node, frame, stats=False)
    info: dict[str, Any] = {
        "scene": "cop",
        "cop_path": node.path(),
        "layer": {k: layer[k] for k in ("layer_type", "resolution", "data_window") if k in layer},
    }
    if "other_outputs" in layer:
        info["layer"]["other_outputs"] = [o["name"] for o in layer["other_outputs"]]
    notes = list(stale)
    if resolution_given:
        notes.append("resolution is ignored with cop_path: the image is the COP's own size.")
    if notes:
        info["notes"] = notes
    return info


def cop_size(info: dict[str, Any]) -> tuple[int, int]:
    """The rendered size of a COP capture: the COP's own resolution."""
    resolution = info.get("layer", {}).get("resolution") or (0, 0)
    return int(resolution[0]), int(resolution[1])


def _cop_networks() -> list[str]:
    """COP networks under /img, with their display nodes, for the capture note."""
    import hou

    found = []
    img = hou.node("/img")
    for net in img.children() if img is not None else ():
        if is_cop_network(net) and not net.userData(INTERNAL_KEY):
            display = cop_display(net)
            found.append(net.path() + (f" (display {display.path()})" if display else ""))
    return found[:3]


class RopImageBackend(Backend):
    """A Cop node's image (``scene: cop``). Runs in the host on the live network."""

    name = "rop_image"

    def can_run(self, spec: Any, env: Env) -> tuple[bool, str]:
        if spec.kind != "cop":
            return False, "it renders Copernicus nodes only"
        return True, ""

    def render(self, spec: Any, ctx: Any) -> LookResult:
        job = spec.prepared

        def run() -> dict[str, Any]:
            import hou

            return render_cop(ctx, hou.node(job.target["cop"]), job.frame, job.out_file)

        info = on_main(ctx, run, job.remaining())
        notes = info.pop("notes", [])
        return LookResult(info=info, notes=notes)


ROP_IMAGE = RopImageBackend()
