"""Pure, content-addressed HS8 production asset contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping


ASSET_CONTRACT_KIND = "hocus_asset_contract"
ASSET_CONTRACT_VERSION = 1
ASSET_CONTRACT_SCHEMA_URI = "hocuspocus://schemas/asset-contract/v1"
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_UPPERCASE_ASSET_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAMING_POLICY_PATTERNS = {
    "portable_ascii_asset_name_v1": _NAME_RE,
    "uppercase_ascii_asset_name_v1": _UPPERCASE_ASSET_NAME_RE,
}
_MAX_CONTENT_BYTES = 1_048_576


class AssetContractError(ValueError):
    """Typed rejection of malformed or non-canonical contract content."""

    def __init__(self, code: str, message: str, pointer: str = ""):
        super().__init__(message)
        self.code = code
        self.pointer = pointer

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self), "jsonPointer": self.pointer}


@dataclass(frozen=True, slots=True)
class AssetContract:
    """A validated, canonical, Houdini-independent asset contract."""

    content: dict[str, Any]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(_canonical_json(self.content))


def decode_asset_contract(
    content: Mapping[str, Any] | str | bytes,
) -> AssetContract:
    """Decode and strictly validate an asset contract from content."""
    value = _decode_content(content)
    _validate_contract(value)
    canonical = _canonical_json(value)
    return AssetContract(
        content=json.loads(canonical),
        digest="sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def canonical_asset_contract_json(
    content: Mapping[str, Any] | str | bytes,
) -> str:
    """Return the one stable JSON representation used for contract digests."""
    return _canonical_json(decode_asset_contract(content).content)


def _decode_content(content: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(content, Mapping):
        try:
            encoded = json.dumps(content, allow_nan=False)
            value = json.loads(encoded)
        except (TypeError, ValueError) as exc:
            raise AssetContractError(
                "HOCUS950", "Asset contract contains a non-JSON value."
            ) from exc
    elif isinstance(content, (str, bytes)):
        raw = content.encode("utf-8") if isinstance(content, str) else content
        if len(raw) > _MAX_CONTENT_BYTES:
            raise AssetContractError("HOCUS950", "Asset contract exceeds 1 MiB.")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssetContractError(
                "HOCUS950", "Asset contract is not valid UTF-8 JSON."
            ) from exc
    else:
        raise AssetContractError("HOCUS950", "Asset contract must be JSON content.")
    if not isinstance(value, dict):
        raise AssetContractError("HOCUS950", "Asset contract must be an object.")
    return value


def _validate_contract(value: dict[str, Any]) -> None:
    _object(
        value,
        "",
        {
            "$schema", "kind", "contractVersion", "identity", "space", "naming",
            "geometry", "surface", "delivery", "usd", "dependencies",
        },
    )
    if value["$schema"] != ASSET_CONTRACT_SCHEMA_URI:
        _fail("HOCUS951", "Unsupported asset-contract schema.", "/$schema")
    if value["kind"] != ASSET_CONTRACT_KIND:
        _fail("HOCUS951", "Unsupported asset-contract kind.", "/kind")
    if value["contractVersion"] != ASSET_CONTRACT_VERSION:
        _fail("HOCUS951", "Unsupported asset-contract version.", "/contractVersion")
    _validate_identity(value["identity"])
    _validate_space(value["space"])
    _validate_naming(value["naming"])
    _validate_geometry(value["geometry"])
    _validate_surface(value["surface"])
    _validate_delivery(value["delivery"])
    _validate_usd(value["usd"])
    dependencies = _array(value["dependencies"], "/dependencies", 256)
    for index, dependency in enumerate(dependencies):
        pointer = f"/dependencies/{index}"
        _object(dependency, pointer, {"id", "kind", "version", "digest"})
        _identifier(dependency["id"], pointer + "/id")
        _enum(dependency["kind"], pointer + "/kind", {"asset", "hda", "module", "texture", "usd"})
        _version(dependency["version"], pointer + "/version")
        _digest(dependency["digest"], pointer + "/digest")
    _ordered_unique(dependencies, "/dependencies", lambda item: (item["kind"], item["id"]))


def _validate_identity(value: Any) -> None:
    _object(value, "/identity", {"assetId", "name", "assetType"})
    _identifier(value["assetId"], "/identity/assetId")
    _name(value["name"], "/identity/name")
    _enum(value["assetType"], "/identity/assetType", {
        "environment", "hard_surface", "rock", "destruction", "simulation", "assembly", "other",
    })


def _validate_space(value: Any) -> None:
    _object(
        value, "/space",
        {"linearUnit", "metersPerUnit", "upAxis", "forwardAxis", "handedness"},
    )
    _enum(value["linearUnit"], "/space/linearUnit", {"millimeter", "centimeter", "meter"})
    _number(value["metersPerUnit"], "/space/metersPerUnit", 0.000001, 1000.0)
    expected_scale = {"millimeter": 0.001, "centimeter": 0.01, "meter": 1.0}
    if value["metersPerUnit"] != expected_scale[value["linearUnit"]]:
        _fail("HOCUS952", "Linear unit and meter scale disagree.", "/space/metersPerUnit")
    _enum(value["upAxis"], "/space/upAxis", {"X", "Y", "Z"})
    _enum(value["forwardAxis"], "/space/forwardAxis", {"X", "Y", "Z", "-X", "-Y", "-Z"})
    if value["upAxis"] == value["forwardAxis"].lstrip("-"):
        _fail("HOCUS952", "Up and forward axes must differ.", "/space/forwardAxis")
    _enum(value["handedness"], "/space/handedness", {"left", "right"})


def _validate_naming(value: Any) -> None:
    _object(value, "/naming", {"policyId", "caseSensitive", "requiredNames"})
    policy_id = _enum(
        value["policyId"],
        "/naming/policyId",
        set(_NAMING_POLICY_PATTERNS),
    )
    _boolean(value["caseSensitive"], "/naming/caseSensitive")
    names = _array(value["requiredNames"], "/naming/requiredNames", 256)
    for index, name in enumerate(names):
        _name(name, f"/naming/requiredNames/{index}")
        if not _naming_policy_accepts(policy_id, name):
            _fail(
                "HOCUS952",
                "Required name does not satisfy its naming policy.",
                f"/naming/requiredNames/{index}",
            )
    _ordered_unique(names, "/naming/requiredNames", lambda item: item)


def _naming_policy_accepts(policy_id: str, value: str) -> bool:
    pattern = _NAMING_POLICY_PATTERNS.get(policy_id)
    return pattern is not None and pattern.fullmatch(value) is not None


def _validate_geometry(value: Any) -> None:
    _object(value, "/geometry", {"pivot", "bounds", "topology", "normals", "tangents"})
    pivot = value["pivot"]
    _object(pivot, "/geometry/pivot", {"mode", "position", "tolerance"})
    _enum(pivot["mode"], "/geometry/pivot/mode", {"origin", "center", "base", "explicit"})
    _vector(pivot["position"], "/geometry/pivot/position")
    _number(pivot["tolerance"], "/geometry/pivot/tolerance", 0.0, 1_000_000.0)
    bounds = value["bounds"]
    _object(bounds, "/geometry/bounds", {"minimum", "maximum", "tolerance"})
    minimum = _vector(bounds["minimum"], "/geometry/bounds/minimum")
    maximum = _vector(bounds["maximum"], "/geometry/bounds/maximum")
    if any(low > high for low, high in zip(minimum, maximum)):
        _fail("HOCUS952", "Bounds minimum exceeds maximum.", "/geometry/bounds")
    _number(bounds["tolerance"], "/geometry/bounds/tolerance", 0.0, 1_000_000.0)
    topology = value["topology"]
    _object(
        topology, "/geometry/topology",
        {"manifold", "watertight", "maxNgonSides", "allowDegenerate"},
    )
    _boolean(topology["manifold"], "/geometry/topology/manifold")
    _boolean(topology["watertight"], "/geometry/topology/watertight")
    _integer(topology["maxNgonSides"], "/geometry/topology/maxNgonSides", 3, 1024)
    _boolean(topology["allowDegenerate"], "/geometry/topology/allowDegenerate")
    _validate_vector_frame(value["normals"], "/geometry/normals", "consistent")
    _validate_vector_frame(value["tangents"], "/geometry/tangents", "orthogonal")


def _validate_vector_frame(value: Any, pointer: str, flag: str) -> None:
    tolerance_key = "unitLengthTolerance" if flag == "consistent" else "orthogonalTolerance"
    _object(value, pointer, {"required", flag, tolerance_key})
    _boolean(value["required"], pointer + "/required")
    _boolean(value[flag], pointer + "/" + flag)
    _number(value[tolerance_key], pointer + "/" + tolerance_key, 0.0, 1.0)


def _validate_surface(value: Any) -> None:
    _object(value, "/surface", {"uvSets", "materialSlots"})
    uv_sets = _array(value["uvSets"], "/surface/uvSets", 32)
    for index, uv_set in enumerate(uv_sets):
        pointer = f"/surface/uvSets/{index}"
        _object(
            uv_set, pointer,
            {
                "name", "required", "udimTiles",
                "allowDuplicateUvTriangles",
                "duplicateUvTriangleMeasurementRequired", "texelDensity",
                "texelDensityMeasurementRequired",
            },
        )
        _name(uv_set["name"], pointer + "/name")
        _boolean(uv_set["required"], pointer + "/required")
        tiles = _array(uv_set["udimTiles"], pointer + "/udimTiles", 256)
        for tile_index, tile in enumerate(tiles):
            _integer(tile, f"{pointer}/udimTiles/{tile_index}", 1001, 9999)
        _ordered_unique(tiles, pointer + "/udimTiles", lambda item: item)
        _boolean(
            uv_set["allowDuplicateUvTriangles"],
            pointer + "/allowDuplicateUvTriangles",
        )
        _boolean(
            uv_set["duplicateUvTriangleMeasurementRequired"],
            pointer + "/duplicateUvTriangleMeasurementRequired",
        )
        _boolean(
            uv_set["texelDensityMeasurementRequired"],
            pointer + "/texelDensityMeasurementRequired",
        )
        density = uv_set["texelDensity"]
        _object(density, pointer + "/texelDensity", {"minimum", "maximum", "unit"})
        low = _number(density["minimum"], pointer + "/texelDensity/minimum", 0.0, 1e9)
        high = _number(density["maximum"], pointer + "/texelDensity/maximum", 0.0, 1e9)
        if low > high:
            _fail("HOCUS952", "Texel-density minimum exceeds maximum.", pointer + "/texelDensity")
        _enum(density["unit"], pointer + "/texelDensity/unit", {"px_per_cm", "px_per_m"})
    _ordered_unique(uv_sets, "/surface/uvSets", lambda item: item["name"])
    slots = _array(value["materialSlots"], "/surface/materialSlots", 256)
    for index, slot in enumerate(slots):
        _object(slot, f"/surface/materialSlots/{index}", {"name", "required"})
        _name(slot["name"], f"/surface/materialSlots/{index}/name")
        _boolean(slot["required"], f"/surface/materialSlots/{index}/required")
    _ordered_unique(slots, "/surface/materialSlots", lambda item: item["name"])


def _validate_delivery(value: Any) -> None:
    _object(value, "/delivery", {"lods", "collision", "instancing", "platformBudgets"})
    lods = _array(value["lods"], "/delivery/lods", 16, minimum=1)
    for index, lod in enumerate(lods):
        pointer = f"/delivery/lods/{index}"
        _object(
            lod,
            pointer,
            {
                "name", "maxTriangles", "maxVertices",
                "maxRelativeTriangleReduction",
                "relativeTriangleReductionMeasurementRequired",
            },
        )
        _name(lod["name"], pointer + "/name")
        _integer(lod["maxTriangles"], pointer + "/maxTriangles", 0, 1_000_000_000)
        _integer(lod["maxVertices"], pointer + "/maxVertices", 0, 1_000_000_000)
        _number(
            lod["maxRelativeTriangleReduction"],
            pointer + "/maxRelativeTriangleReduction",
            0.0,
            1.0,
        )
        _boolean(
            lod["relativeTriangleReductionMeasurementRequired"],
            pointer + "/relativeTriangleReductionMeasurementRequired",
        )
    _ordered_unique(lods, "/delivery/lods", lambda item: item["name"])
    collision = value["collision"]
    _object(
        collision,
        "/delivery/collision",
        {"mode", "requireConvex", "maxPrimitives", "maxTriangles"},
    )
    _enum(collision["mode"], "/delivery/collision/mode", {"none", "simple", "convex", "mesh"})
    _boolean(collision["requireConvex"], "/delivery/collision/requireConvex")
    _integer(collision["maxPrimitives"], "/delivery/collision/maxPrimitives", 0, 1_000_000)
    _integer(collision["maxTriangles"], "/delivery/collision/maxTriangles", 0, 100_000_000)
    instancing = value["instancing"]
    _object(instancing, "/delivery/instancing", {
        "required", "prototypePrimPath", "representation",
        "maxUniqueMeshes", "maxUnpackedInstances",
    })
    _boolean(instancing["required"], "/delivery/instancing/required")
    _prim_path(
        instancing["prototypePrimPath"],
        "/delivery/instancing/prototypePrimPath",
    )
    _enum(
        instancing["representation"],
        "/delivery/instancing/representation",
        {"native_instance", "point_instancer"},
    )
    _integer(instancing["maxUniqueMeshes"], "/delivery/instancing/maxUniqueMeshes", 0, 1_000_000)
    _integer(instancing["maxUnpackedInstances"], "/delivery/instancing/maxUnpackedInstances", 0, 1_000_000_000)
    budgets = _array(value["platformBudgets"], "/delivery/platformBudgets", 64, minimum=1)
    budget_keys = {
        "platform", "maxTriangles", "maxVertices", "maxTextureBytes",
        "maxMaterialSlots", "maxInstances",
    }
    for index, budget in enumerate(budgets):
        pointer = f"/delivery/platformBudgets/{index}"
        _object(budget, pointer, budget_keys)
        _name(budget["platform"], pointer + "/platform")
        for key in budget_keys - {"platform"}:
            _integer(budget[key], pointer + "/" + key, 0, 1_000_000_000_000)
    _ordered_unique(budgets, "/delivery/platformBudgets", lambda item: item["platform"])


def _validate_usd(value: Any) -> None:
    _object(value, "/usd", {"kind", "purpose", "variants", "publish", "primBindings"})
    _enum(value["kind"], "/usd/kind", {"component", "assembly", "group"})
    _enum(value["purpose"], "/usd/purpose", {"default", "proxy", "render", "guide"})
    variants = _array(value["variants"], "/usd/variants", 64)
    for index, variant in enumerate(variants):
        pointer = f"/usd/variants/{index}"
        _object(variant, pointer, {"name", "allowedValues", "requiredValue"})
        _name(variant["name"], pointer + "/name")
        allowed = _array(variant["allowedValues"], pointer + "/allowedValues", 256, minimum=1)
        for value_index, allowed_value in enumerate(allowed):
            _name(allowed_value, f"{pointer}/allowedValues/{value_index}")
        _ordered_unique(allowed, pointer + "/allowedValues", lambda item: item)
        required = variant["requiredValue"]
        if required is not None:
            _name(required, pointer + "/requiredValue")
            if required not in allowed:
                _fail("HOCUS952", "Required variant is not allowed.", pointer + "/requiredValue")
    _ordered_unique(variants, "/usd/variants", lambda item: item["name"])
    publish = value["publish"]
    _object(publish, "/usd/publish", {"rootPrim", "defaultPrim", "payload"})
    for key in ("rootPrim", "defaultPrim"):
        prim = _string(publish[key], "/usd/publish/" + key, 512)
        if not re.fullmatch(r"/[A-Za-z_][A-Za-z0-9_/]*", prim):
            _fail("HOCUS952", "USD prim path is not canonical.", "/usd/publish/" + key)
    root = publish["rootPrim"]
    if publish["defaultPrim"] != root and not publish["defaultPrim"].startswith(root + "/"):
        _fail("HOCUS952", "Default prim must be under the publish root.", "/usd/publish/defaultPrim")
    _enum(publish["payload"], "/usd/publish/payload", {"inline", "payload", "reference"})
    _validate_prim_bindings(value["primBindings"], root)


def _validate_prim_bindings(value: Any, root: str) -> None:
    bindings = _array(value, "/usd/primBindings", 256, minimum=1)
    for index, binding in enumerate(bindings):
        pointer = f"/usd/primBindings/{index}"
        _object(binding, pointer, {
            "name", "role", "primPath", "purpose", "visibility", "materialPrimPath",
        })
        _name(binding["name"], pointer + "/name")
        _enum(binding["role"], pointer + "/role", {"render", "collision"})
        _prim_path(binding["primPath"], pointer + "/primPath")
        _enum(binding["purpose"], pointer + "/purpose", {"default", "proxy", "render", "guide"})
        _enum(binding["visibility"], pointer + "/visibility", {"inherited", "invisible"})
        material = binding["materialPrimPath"]
        if material is not None:
            _prim_path(material, pointer + "/materialPrimPath")
        if binding["role"] == "render" and material is None:
            _fail(
                "HOCUS952",
                "Render prim bindings require an explicit material prim.",
                pointer + "/materialPrimPath",
            )
        if binding["role"] == "collision" and binding["purpose"] != "proxy":
            _fail(
                "HOCUS952",
                "Collision prim bindings require proxy purpose.",
                pointer + "/purpose",
            )
        if not binding["primPath"].startswith(root + "/"):
            _fail(
                "HOCUS952",
                "Bound prim must be under the publish root.",
                pointer + "/primPath",
            )
    _ordered_unique(
        bindings,
        "/usd/primBindings",
        lambda item: (item["role"], item["name"]),
    )
    paths = [item["primPath"] for item in bindings]
    if len(paths) != len(set(paths)):
        _fail("HOCUS952", "USD prim bindings must use unique prim paths.", "/usd/primBindings")


def _prim_path(value: Any, pointer: str) -> str:
    prim = _string(value, pointer, 512)
    if not re.fullmatch(r"/[A-Za-z_][A-Za-z0-9_/]*", prim):
        _fail("HOCUS952", "USD prim path is not canonical.", pointer)
    return prim


def _object(value: Any, pointer: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("HOCUS950", "Expected an object.", pointer)
    actual = set(value)
    if actual != keys:
        unexpected = sorted(actual - keys)
        missing = sorted(keys - actual)
        message = f"Object keys differ; missing={missing}, unexpected={unexpected}."
        _fail("HOCUS950", message, pointer)
    return value


def _array(value: Any, pointer: str, maximum: int, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail("HOCUS950", f"Expected {minimum} to {maximum} items.", pointer)
    return value


def _string(value: Any, pointer: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail("HOCUS950", f"Expected 1 to {maximum} characters.", pointer)
    return value


def _identifier(value: Any, pointer: str) -> str:
    value = _string(value, pointer, 128)
    if not _ID_RE.fullmatch(value):
        _fail("HOCUS950", "Expected a path-free stable identifier.", pointer)
    return value


def _name(value: Any, pointer: str) -> str:
    value = _string(value, pointer, 128)
    if not _NAME_RE.fullmatch(value):
        _fail("HOCUS950", "Expected a canonical name.", pointer)
    return value


def _version(value: Any, pointer: str) -> str:
    value = _string(value, pointer, 128)
    if not _VERSION_RE.fullmatch(value):
        _fail("HOCUS950", "Expected a path-free version.", pointer)
    return value


def _digest(value: Any, pointer: str) -> str:
    value = _string(value, pointer, 71)
    if not _DIGEST_RE.fullmatch(value):
        _fail("HOCUS950", "Expected a lowercase SHA-256 digest.", pointer)
    return value


def _boolean(value: Any, pointer: str) -> bool:
    if not isinstance(value, bool):
        _fail("HOCUS950", "Expected a boolean.", pointer)
    return value


def _integer(value: Any, pointer: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        _fail("HOCUS950", f"Expected an integer from {minimum} to {maximum}.", pointer)
    return value


def _number(value: Any, pointer: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("HOCUS950", "Expected a finite number.", pointer)
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        _fail("HOCUS950", f"Expected a number from {minimum} to {maximum}.", pointer)
    return result


def _vector(value: Any, pointer: str) -> tuple[float, float, float]:
    items = _array(value, pointer, 3, minimum=3)
    return tuple(_number(item, f"{pointer}/{index}", -1e12, 1e12) for index, item in enumerate(items))


def _enum(value: Any, pointer: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        _fail("HOCUS950", f"Expected one of {sorted(allowed)}.", pointer)
    return value


def _ordered_unique(value: list[Any], pointer: str, key) -> None:
    keys = [key(item) for item in value]
    if keys != sorted(set(keys)):
        _fail("HOCUS952", "Array must be sorted and unique.", pointer)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    )


def _fail(code: str, message: str, pointer: str) -> None:
    raise AssetContractError(code, message, pointer)
