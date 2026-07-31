"""Production fixture sources and helpers for installed HS8 acceptance."""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
from typing import Any

import hou  # type: ignore
from PIL import Image, ImageDraw
from pxr import Sdf, Usd, UsdGeom  # type: ignore

from hocuspocus.hocusscript.build_provenance import (
    _components_from_measured_dependencies,
    component_from_content,
    create_build_provenance,
)
from hocuspocus.live.production_usd_geometry import (
    _canonicalize_right_handed_meshes,
)


SOP_ROOT = "/obj/hs8_rock_family"
SOP_OUTPUT = SOP_ROOT + "/OUT_ROCK_FAMILY"
USD_OUTPUT = "/stage/configure_publish_layer"
MATERIAL = "/mat/hs8_rock_material"
MAX_USDA_OUTPUT_BYTES = 64 * 1024 * 1024

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "hs8"
FIXTURE_FILES = {
    "material": "material.hocus",
    "rock-family": "rock-family.hocus",
    "rock-family-reconcile": "rock-family-reconcile.hocus",
    "usd": "usd.hocus",
    "asset-contract": "asset-contract.json",
    "baseline-contact-sheet": "baseline-contact-sheet.png",
    "visual-review-request": "visual-review-request.json",
}
FIXTURE_BYTES = {
    name: (FIXTURE_ROOT / filename).read_bytes()
    for name, filename in FIXTURE_FILES.items()
}
TRANSIENT_HOUDINI_CUSTOM_DATA_KEYS = frozenset({
    "HoudiniCreatorNode",
    "HoudiniDataId",
    "HoudiniEditorNodes",
    "HoudiniPrimEditorNodes",
    "HoudiniSavePath",
    "HoudiniVolumeFilePaths",
})
MATERIAL_SOURCE = FIXTURE_BYTES["material"].decode("utf-8")
ROCK_SOURCE = FIXTURE_BYTES["rock-family"].decode("utf-8")
ROCK_RECONCILE_SOURCE = FIXTURE_BYTES["rock-family-reconcile"].decode("utf-8")
USD_SOURCE = FIXTURE_BYTES["usd"].decode("utf-8")


def cook_fixture(paths: tuple[str, ...]) -> dict[str, Any]:
    """Explicitly authorize cooks only for named disposable fixture outputs."""

    before = _counts()
    started = __import__("time").perf_counter()
    for path in paths:
        node = hou.node(path)
        if node is None:
            raise RuntimeError(f"HS8 authorized cook node is missing: {path}")
        node.cook(force=True)
        errors = tuple(node.errors())
        if errors:
            raise RuntimeError(f"HS8 fixture cook failed at {path}: {errors!r}")
    elapsed = round((__import__("time").perf_counter() - started) * 1000.0, 3)
    after = _counts()
    changed = {
        path: after[path] - before.get(path, 0)
        for path in after if after[path] != before.get(path, 0)
    }
    unintended = [
        path for path in changed
        if not any(path == allowed or path.startswith(allowed.rsplit("/", 1)[0] + "/") for allowed in paths)
    ]
    if unintended:
        raise RuntimeError(f"HS8 cooked outside authorized fixture networks: {unintended!r}")
    diagnostics = _node_diagnostics(paths)
    return {
        "authorizedPaths": list(paths),
        "elapsedMs": elapsed,
        "before": before,
        "after": after,
        "changed": changed,
        "errorCount": diagnostics["errorCount"],
        "warningCount": diagnostics["warningCount"],
        "diagnostics": diagnostics["items"],
    }


def _counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for root_path in (SOP_ROOT, "/stage"):
        root = hou.node(root_path)
        if root is None:
            continue
        nodes = (root, *root.allSubChildren())
        for node in nodes:
            counts[node.path()] = int(node.cookCount())
    return dict(sorted(counts.items()))


def _node_diagnostics(paths: tuple[str, ...]) -> dict[str, Any]:
    items = []
    error_count = 0
    warning_count = 0
    for path in paths:
        node = hou.node(path)
        if node is None:
            raise RuntimeError(f"HS8 diagnostic node is missing: {path}")
        for candidate in (node, *node.allSubChildren()):
            errors = tuple(candidate.errors())
            warnings = tuple(candidate.warnings())
            error_count += len(errors)
            warning_count += len(warnings)
            if errors or warnings:
                items.append({
                    "nodePath": candidate.path(),
                    "errors": list(errors),
                    "warnings": list(warnings),
                })
    return {
        "errorCount": error_count,
        "warningCount": warning_count,
        "items": items,
    }


def process_peak_working_set_bytes() -> int:
    """Read the host process peak working set from the Windows kernel."""

    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory_info = kernel32.K32GetProcessMemoryInfo
    get_memory_info.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    )
    get_memory_info.restype = wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    if not get_memory_info(
        process,
        ctypes.byref(counters),
        counters.cb,
    ):
        raise RuntimeError("HS8 could not read the host peak working set.")
    return int(counters.PeakWorkingSetSize)


def artist_override() -> dict[str, Any]:
    root = hou.node(SOP_ROOT)
    artist = hou.node(SOP_ROOT + "/artist_override")
    return {
        "rootTag": root.userData("artist.review") if root is not None else None,
        "artistNode": artist.path() if artist is not None else None,
        "artistColor": list(artist.color().rgb()) if artist is not None else None,
    }


def add_artist_override() -> dict[str, Any]:
    root = hou.node(SOP_ROOT)
    if root is None:
        raise RuntimeError("HS8 SOP root is missing.")
    root.setUserData("artist.review", "protected")
    artist = root.createNode("null", "artist_override", run_init_scripts=False)
    artist.setColor(hou.Color((0.9, 0.3, 0.1)))
    return artist_override()


def _remove_transient_houdini_custom_data(layer: Sdf.Layer) -> None:
    def clean_prim(prim_spec: Any) -> None:
        clean_spec(prim_spec)
        for property_spec in tuple(prim_spec.properties):
            if _transient_houdini_property(property_spec):
                prim_spec.RemoveProperty(property_spec)
                continue
            clean_spec(property_spec)
        for child_spec in prim_spec.nameChildren:
            clean_prim(child_spec)

    def clean_spec(spec: Any) -> None:
        custom_data = dict(spec.customData)
        retained = {
            key: value for key, value in custom_data.items()
            if key not in TRANSIENT_HOUDINI_CUSTOM_DATA_KEYS
        }
        if len(retained) != len(custom_data):
            spec.customData = retained

    clean_spec(layer.pseudoRoot)
    for root_spec in layer.rootPrims:
        clean_prim(root_spec)


def _transient_houdini_property(property_spec: Any) -> bool:
    if str(property_spec.name) != "info:sourceAsset":
        return False
    value = getattr(property_spec, "default", None)
    if not isinstance(value, Sdf.AssetPath):
        return False
    return value.path.startswith(("op:", "opdef:", "oplib:"))


def export_usd(path: Path) -> dict[str, Any]:
    node = hou.node(USD_OUTPUT)
    stage = node.stage() if node is not None else None
    if stage is None:
        raise RuntimeError("HS8 USD fixture export failed.")
    flattened = stage.Flatten(False)
    if flattened is None:
        raise RuntimeError("HS8 flattened USD fixture export failed.")
    layer_data = dict(flattened.customLayerData)
    layer_data["hocuspocus"] = {
        "forwardAxis": "-Z",
        "pivotMode": "origin",
    }
    flattened.customLayerData = layer_data
    _canonicalize_right_handed_meshes(
        flattened, Usd=Usd, UsdGeom=UsdGeom,
    )
    _remove_transient_houdini_custom_data(flattened)
    for dependency in flattened.GetCompositionAssetDependencies():
        identifier = str(getattr(dependency, "path", dependency))
        if Sdf.Layer.IsAnonymousLayerIdentifier(identifier):
            raise RuntimeError(
                "HS8 flattened USD has an anonymous composition dependency.",
            )
    payload = flattened.ExportToString()
    if not isinstance(payload, str) or not payload.startswith("#usda"):
        raise RuntimeError("HS8 flattened USD serialization failed.")
    encoded = payload.encode("utf-8")
    if len(encoded) > MAX_USDA_OUTPUT_BYTES:
        raise RuntimeError("HS8 flattened USD exceeds its byte limit.")
    parsed = Sdf.Layer.CreateAnonymous(".usda")
    if parsed is None or not parsed.ImportFromString(payload):
        raise RuntimeError("HS8 flattened USD serialization is invalid.")
    path.write_bytes(encoded)
    return {
        "name": path.name,
        "bytes": len(encoded),
        "digest": "sha256:" + hashlib.sha256(encoded).hexdigest(),
    }


def comparison_projection(observation: dict[str, Any]) -> dict[str, Any]:
    """Exclude timing, output serialization, and cumulative cook counters."""

    projection = {
        "geometry": copy.deepcopy(observation["geometry"]),
        "usd": copy.deepcopy(observation["usd"]),
        "dependencies": copy.deepcopy(observation["dependencies"]),
        "metrics": {
            key: value for key, value in observation["metrics"].items()
            if key != "observationMs"
        },
    }
    for stage in projection["usd"]:
        stage.get("rootLayer", {}).pop("identifierDigest", None)
    if "finalUsd" in observation:
        projection["finalUsd"] = copy.deepcopy(observation["finalUsd"])
        projection["finalUsd"].pop("path", None)
    return projection


def write_report(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "name": path.name,
        "bytes": path.stat().st_size,
        "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def render_contact_sheet(path: Path) -> dict[str, Any]:
    """Render four deterministic asset-only projections without a desktop grab."""

    node = hou.node(SOP_OUTPUT)
    geometry = node.geometry() if node is not None else None
    if geometry is None:
        raise RuntimeError("HS8 contact sheet requires pre-cooked output geometry.")
    if (
        int(geometry.intrinsicValue("pointcount")) > 10_000_000
        or int(geometry.intrinsicValue("primitivecount")) > 10_000_000
        or int(geometry.intrinsicValue("vertexcount")) > 30_000_000
    ):
        raise RuntimeError("HS8 contact-sheet geometry exceeds bounded render limits.")
    material = hou.node(MATERIAL)
    if material is None:
        raise RuntimeError("HS8 contact sheet requires the authored material.")
    material_facts = [
        (parm.name(), str(parm.eval()))
        for parm in material.parms()
        if parm.name() in {"basecolor", "basecolorr", "basecolorg", "basecolorb", "rough", "metallic"}
    ]
    material_digest = hashlib.sha256(
        json.dumps(material_facts, sort_keys=True).encode(),
    ).hexdigest()
    base = tuple(72 + int(material_digest[index:index + 2], 16) // 3 for index in (0, 2, 4))
    usd_node = hou.node(USD_OUTPUT)
    stage = usd_node.stage() if usd_node is not None else None
    if stage is None:
        raise RuntimeError("HS8 contact sheet requires the authored USD stage.")
    usd_facts = [
        {
            "path": str(prim.GetPath()),
            "kind": prim.GetMetadata("kind"),
            "variants": [
                (name, prim.GetVariantSet(name).GetVariantSelection())
                for name in sorted(prim.GetVariantSets().GetNames())
            ],
            "payload": bool(prim.HasAuthoredPayloads()),
            "reference": bool(prim.HasAuthoredReferences()),
        }
        for prim in stage.Traverse()
    ]
    usd_digest = hashlib.sha256(
        json.dumps(usd_facts, sort_keys=True).encode(),
    ).hexdigest()
    views = (
        ("front", lambda p: (p[0], p[1], p[2]), lambda n: (n[0], n[1], n[2])),
        ("side", lambda p: (p[2], p[1], -p[0]), lambda n: (n[2], n[1], -n[0])),
        ("top", lambda p: (p[0], p[2], p[1]), lambda n: (n[0], n[2], n[1])),
        (
            "iso",
            lambda p: (p[0] - p[2], p[1] + 0.35 * (p[0] + p[2]), p[0] + p[2]),
            lambda n: (n[0] - n[2], n[1] + 0.35 * (n[0] + n[2]), n[0] + n[2]),
        ),
    )
    sheet = Image.new("RGB", (512, 512), (18, 20, 24))
    light = (0.35, 0.55, 0.76)
    for index, (label, project, project_normal) in enumerate(views):
        projected = {
            point.number(): project(tuple(float(value) for value in point.position()))
            for point in geometry.points()
        }
        values = list(projected.values())
        low_x, high_x = min(p[0] for p in values), max(p[0] for p in values)
        low_y, high_y = min(p[1] for p in values), max(p[1] for p in values)
        scale = 210.0 / max(high_x - low_x, high_y - low_y, 1e-6)
        offset_x, offset_y = (index % 2) * 256, (index // 2) * 256

        def pixel(value: tuple[float, float, float]) -> tuple[float, float]:
            return (
                offset_x + 128 + (value[0] - (low_x + high_x) / 2) * scale,
                offset_y + 128 - (value[1] - (low_y + high_y) / 2) * scale,
            )

        draw = ImageDraw.Draw(sheet)
        primitives = sorted(
            geometry.prims(),
            key=lambda prim: sum(projected[v.point().number()][2] for v in prim.vertices())
            / max(len(prim.vertices()), 1),
        )
        for primitive in primitives:
            polygon = [pixel(projected[v.point().number()]) for v in primitive.vertices()]
            if len(polygon) >= 3:
                normal_attribute = (
                    geometry.findVertexAttrib("N")
                    or geometry.findPointAttrib("N")
                )
                if normal_attribute is None:
                    source_normal = tuple(
                        float(value) for value in primitive.normal()
                    )
                else:
                    vertex_owned = geometry.findVertexAttrib("N") is not None
                    values = [
                        (
                            vertex if vertex_owned else vertex.point()
                        ).attribValue(normal_attribute)
                        for vertex in primitive.vertices()
                    ]
                    source_normal = tuple(
                        sum(float(value[axis]) for value in values) / len(values)
                        for axis in range(3)
                    )
                normal = project_normal(source_normal)
                length = max(sum(value * value for value in normal) ** 0.5, 1e-9)
                diffuse = max(
                    0.0,
                    sum(normal[axis] / length * light[axis] for axis in range(3)),
                )
                shade = 0.28 + 0.72 * diffuse
                fill = tuple(min(255, max(0, round(value * shade))) for value in base)
                outline = tuple(min(255, round(value * 1.25)) for value in fill)
                draw.polygon(polygon, fill=fill, outline=outline)
        draw.text((offset_x + 10, offset_y + 9), label, fill=(235, 235, 230))
        draw.text(
            (offset_x + 10, offset_y + 235),
            f"MAT {material_digest[:8]} USD {usd_digest[:8]}",
            fill=(210, 214, 220),
        )
        draw.rectangle((offset_x, offset_y, offset_x + 255, offset_y + 255), outline=(72, 78, 88))
    sheet.save(path, format="PNG", optimize=False, compress_level=9)
    return {
        "supported": True,
        "mode": "headless-geometry-projection",
        "name": path.name,
        "bytes": path.stat().st_size,
        "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        "views": ["front", "side", "top", "iso"],
        "resolution": [512, 512],
        "materialDigest": "sha256:" + material_digest,
        "usdCompositionDigest": "sha256:" + usd_digest,
    }


def fixture_contract() -> dict[str, Any]:
    """Return the immutable fixture contract before any geometry or USD cook."""

    template = json.loads(FIXTURE_BYTES["asset-contract"])
    return template


def build_manifest(
    *,
    observation: dict[str, Any],
    dependency_measurements: list[dict[str, Any]],
    catalog: Any,
    installed_modules: list[dict[str, Any]],
    package_search_receipt: dict[str, Any],
    outputs: dict[str, bytes],
) -> Any:
    """Bind source, compiler, catalog, effective search, and production outputs."""

    source_values = {
        name: FIXTURE_BYTES[name]
        for name in (
            "material", "rock-family", "rock-family-reconcile", "usd",
        )
    }
    dependencies = observation["dependencies"]
    hdas, inputs = _components_from_measured_dependencies(
        dependencies=dependencies,
        measurements=dependency_measurements,
        uri_authority="hs8.fixture",
    )
    module_bytes = json.dumps(
        installed_modules, sort_keys=True, separators=(",", ":"),
    ).encode()
    package_search_bytes = json.dumps(
        package_search_receipt, sort_keys=True, separators=(",", ":"),
    ).encode()
    recipe_bytes = json.dumps({
        "version": 1,
        "graphs": ["material", "rock-family", "rock-family-reconcile", "usd"],
        "postApplyOperations": [{
            "operation": "parm.set",
            "operationVersion": 1,
            "parmPath": SOP_ROOT + "/shop_materialpath",
            "value": MATERIAL,
        }],
    }, sort_keys=True, separators=(",", ":")).encode()
    return create_build_provenance(
        asset_uri="hocus-asset://hs8.fixture/rock-family",
        target_platform="houdini",
        recipe=component_from_content(
            "recipe", "hocus-recipe://hs8.fixture/production-v1",
            recipe_bytes,
        ),
        sources=tuple(
            component_from_content(
                "source",
                (
                    f"hocus-project://hs8.fixture/{FIXTURE_FILES[name]}"
                ),
                value,
            )
            for name, value in sorted(source_values.items())
        ),
        compiler=component_from_content(
            "compiler", "hocus-compiler://hs8.fixture/installed",
            module_bytes, version="0.9.0",
        ),
        catalog=component_from_content(
            "catalog", "hocus-catalog://hs8.fixture/live-v2",
            catalog.to_json().encode(), fingerprint=catalog.fingerprint,
        ),
        modules=(
            component_from_content(
                "module", "hocus-module://hs8.fixture/installed-runtime",
                module_bytes,
            ),
        ),
        hdas=hdas,
        inputs=(
            *inputs,
            component_from_content(
                "input",
                "hocus-input://hs8.fixture/asset-contract.json",
                FIXTURE_BYTES["asset-contract"],
                version="1",
            ),
            component_from_content(
                "input",
                "hocus-input://hs8.fixture/effective-package-search.json",
                package_search_bytes,
                version="1",
            ),
        ),
        outputs=tuple(
            component_from_content(
                "output", f"hocus-output://hs8.fixture/{name}", content,
                role=name.rsplit(".", 1)[0],
                media_type=(
                    "image/png" if name.endswith(".png")
                    else "model/vnd.usd" if name.endswith(".usda")
                    else "application/json"
                ),
            )
            for name, content in sorted(outputs.items())
        ),
    )
