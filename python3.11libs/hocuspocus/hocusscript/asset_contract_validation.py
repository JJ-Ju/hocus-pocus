"""Deterministic validation of observed asset facts against HS8 contracts."""

from __future__ import annotations

import hashlib
import copy
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .asset_contract import (
    AssetContractError,
    _naming_policy_accepts,
    decode_asset_contract,
)


_MAX_OBSERVATION_BYTES = 2_097_152
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PRIM_RE = re.compile(r"^/[A-Za-z_][A-Za-z0-9_/]*$")
_NOT_OBSERVED_REASONS = {
    "host_api_unavailable",
    "texture_resolution_unavailable",
    "runtime_camera_model_unavailable",
    "required_input_unavailable",
    "not_applicable",
}


@dataclass(frozen=True, slots=True)
class AssetContractDiagnostic:
    severity: str
    code: str
    message: str
    json_pointer: str
    expected: Any
    actual: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "jsonPointer": self.json_pointer,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class AssetContractReport:
    contract_digest: str
    observation_digest: str
    valid: bool
    diagnostics: tuple[AssetContractDiagnostic, ...]
    coverage: dict[str, Any]
    digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "hocus_asset_contract_report",
            "reportVersion": 1,
            "contractDigest": self.contract_digest,
            "observationDigest": self.observation_digest,
            "valid": self.valid,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "coverage": copy.deepcopy(self.coverage),
            "reportDigest": self.digest,
        }


def validate_asset_contract(
    contract_content: Mapping[str, Any] | str | bytes,
    observation_content: Mapping[str, Any] | str | bytes,
) -> AssetContractReport:
    """Validate content-only observed facts and return a stable report."""
    contract = decode_asset_contract(contract_content)
    observation = _decode_observation(observation_content)
    diagnostics: list[AssetContractDiagnostic] = []
    not_observed: list[dict[str, Any]] = []
    _validate_identity_space_naming(contract.content, observation, diagnostics)
    _validate_geometry(contract.content["geometry"], observation["geometry"], diagnostics)
    _validate_surface(
        contract.content["surface"],
        contract.content["space"],
        observation["surface"],
        diagnostics,
        not_observed,
    )
    _validate_delivery(
        contract.content["delivery"],
        observation["delivery"],
        diagnostics,
        not_observed,
    )
    _validate_usd(contract.content["usd"], observation["usd"], diagnostics)
    _validate_dependencies(contract.content["dependencies"], observation["dependencies"], diagnostics)
    ordered = tuple(sorted(
        diagnostics,
        key=lambda item: (item.json_pointer, item.code, item.message),
    ))
    observation_json = _canonical_json(observation)
    observation_digest = _sha256(observation_json)
    coverage = {
        "notObserved": sorted(
            not_observed,
            key=lambda item: (item["jsonPointer"], item["reasonCode"]),
        ),
    }
    body = {
        "kind": "hocus_asset_contract_report",
        "reportVersion": 1,
        "contractDigest": contract.digest,
        "observationDigest": observation_digest,
        "valid": not ordered,
        "diagnostics": [item.to_dict() for item in ordered],
        "coverage": coverage,
    }
    return AssetContractReport(
        contract_digest=contract.digest,
        observation_digest=observation_digest,
        valid=not ordered,
        diagnostics=ordered,
        coverage=coverage,
        digest=_sha256(_canonical_json(body)),
    )


def _decode_observation(content: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(content, Mapping):
        try:
            raw = json.dumps(content, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise AssetContractError(
                "HOCUS953", "Asset observation contains a non-JSON value."
            ) from exc
    elif isinstance(content, str):
        raw = content.encode("utf-8")
    elif isinstance(content, bytes):
        raw = content
    else:
        raise AssetContractError("HOCUS953", "Asset observation must be JSON content.")
    if len(raw) > _MAX_OBSERVATION_BYTES:
        raise AssetContractError("HOCUS953", "Asset observation exceeds 2 MiB.")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetContractError("HOCUS953", "Asset observation is not valid JSON.") from exc
    _observation_shape(value)
    return value


def _observation_shape(value: Any) -> None:
    _keys(value, "", {
        "assetId", "space", "names", "geometry", "surface",
        "delivery", "usd", "dependencies",
    })
    _matching(value["assetId"], "/assetId", _ID_RE, "identifier")
    _keys(value["space"], "/space", {
        "metersPerUnit", "upAxis", "forwardAxis", "handedness",
    })
    _finite(value["space"]["metersPerUnit"], "/space/metersPerUnit")
    _one_of(value["space"]["upAxis"], "/space/upAxis", {"X", "Y", "Z"})
    _one_of(
        value["space"]["forwardAxis"], "/space/forwardAxis",
        {"X", "Y", "Z", "-X", "-Y", "-Z"},
    )
    _one_of(value["space"]["handedness"], "/space/handedness", {"left", "right"})
    _string_array(value["names"], "/names", 4096)
    _ordered(value["names"], "/names", lambda item: item)
    _geometry_shape(value["geometry"])
    _surface_shape(value["surface"])
    _delivery_shape(value["delivery"])
    _usd_shape(value["usd"])
    dependencies = _list(value["dependencies"], "/dependencies", 256)
    for index, dependency in enumerate(dependencies):
        pointer = f"/dependencies/{index}"
        _keys(dependency, pointer, {"id", "kind", "version", "digest"})
        _matching(dependency["id"], pointer + "/id", _ID_RE, "identifier")
        _one_of(dependency["kind"], pointer + "/kind", {"asset", "hda", "module", "texture", "usd"})
        _matching(dependency["version"], pointer + "/version", _VERSION_RE, "version")
        _matching(dependency["digest"], pointer + "/digest", _DIGEST_RE, "digest")
    _ordered(value["dependencies"], "/dependencies", lambda item: (item["kind"], item["id"]))


def _geometry_shape(value: Any) -> None:
    _keys(value, "/geometry", {"pivot", "bounds", "topology", "normals", "tangents"})
    _vector(value["pivot"], "/geometry/pivot")
    _keys(value["bounds"], "/geometry/bounds", {"minimum", "maximum"})
    _vector(value["bounds"]["minimum"], "/geometry/bounds/minimum")
    _vector(value["bounds"]["maximum"], "/geometry/bounds/maximum")
    _keys(value["topology"], "/geometry/topology", {
        "manifold", "watertight", "maxNgonSides", "degenerateCount",
    })
    topology = value["topology"]
    _bool(topology["manifold"], "/geometry/topology/manifold")
    _bool(topology["watertight"], "/geometry/topology/watertight")
    _count(topology["maxNgonSides"], "/geometry/topology/maxNgonSides")
    _count(topology["degenerateCount"], "/geometry/topology/degenerateCount")
    _keys(value["normals"], "/geometry/normals", {
        "present", "consistent", "maxUnitLengthError",
    })
    _keys(value["tangents"], "/geometry/tangents", {
        "present", "orthogonal", "maxOrthogonalError",
    })
    for key in ("normals", "tangents"):
        frame = value[key]
        _bool(frame["present"], f"/geometry/{key}/present")
        flag = "consistent" if key == "normals" else "orthogonal"
        error = "maxUnitLengthError" if key == "normals" else "maxOrthogonalError"
        _bool(frame[flag], f"/geometry/{key}/{flag}")
        _finite(frame[error], f"/geometry/{key}/{error}")


def _surface_shape(value: Any) -> None:
    _keys(value, "/surface", {"uvSets", "materialSlots", "textureBytes"})
    uv_sets = _list(value["uvSets"], "/surface/uvSets", 32)
    for index, uv_set in enumerate(uv_sets):
        pointer = f"/surface/uvSets/{index}"
        _keys(uv_set, pointer, {
            "name", "udimTiles", "duplicateUvTriangleCount", "texelDensity",
        })
        _matching(uv_set["name"], pointer + "/name", _NAME_RE, "name")
        tiles = _list(uv_set["udimTiles"], pointer + "/udimTiles", 256)
        for tile_index, tile in enumerate(tiles):
            _count(tile, f"{pointer}/udimTiles/{tile_index}")
        _ordered(tiles, pointer + "/udimTiles", lambda item: item)
        _measurement(
            uv_set["duplicateUvTriangleCount"],
            pointer + "/duplicateUvTriangleCount",
            integer=True,
        )
        _texel_density_measurement(
            uv_set["texelDensity"],
            pointer + "/texelDensity",
        )
    _ordered(uv_sets, "/surface/uvSets", lambda item: item["name"])
    slots = _string_array(value["materialSlots"], "/surface/materialSlots", 256)
    _ordered(slots, "/surface/materialSlots", lambda item: item)
    _count(value["textureBytes"], "/surface/textureBytes")


def _delivery_shape(value: Any) -> None:
    _keys(value, "/delivery", {"lods", "collision", "instancing", "platformMetrics"})
    lods = _list(value["lods"], "/delivery/lods", 16)
    for index, lod in enumerate(lods):
        pointer = f"/delivery/lods/{index}"
        _keys(
            lod,
            pointer,
            {"name", "triangles", "vertices", "relativeTriangleReduction"},
        )
        _matching(lod["name"], pointer + "/name", _NAME_RE, "name")
        _count(lod["triangles"], pointer + "/triangles")
        _count(lod["vertices"], pointer + "/vertices")
        _measurement(
            lod["relativeTriangleReduction"],
            pointer + "/relativeTriangleReduction",
        )
    _ordered(lods, "/delivery/lods", lambda item: item["name"])
    collision = value["collision"]
    _keys(
        collision,
        "/delivery/collision",
        {"mode", "convex", "primitives", "triangles"},
    )
    _one_of(collision["mode"], "/delivery/collision/mode", {"none", "simple", "convex", "mesh"})
    _bool(collision["convex"], "/delivery/collision/convex")
    _count(collision["primitives"], "/delivery/collision/primitives")
    _count(collision["triangles"], "/delivery/collision/triangles")
    instancing = value["instancing"]
    _keys(instancing, "/delivery/instancing", {
        "used", "prototypePrimPath", "representation",
        "uniqueMeshes", "unpackedInstances",
    })
    _bool(instancing["used"], "/delivery/instancing/used")
    _matching(
        instancing["prototypePrimPath"],
        "/delivery/instancing/prototypePrimPath",
        _PRIM_RE,
        "USD prim path",
    )
    _one_of(
        instancing["representation"],
        "/delivery/instancing/representation",
        {"native_instance", "point_instancer"},
    )
    _count(instancing["uniqueMeshes"], "/delivery/instancing/uniqueMeshes")
    _count(instancing["unpackedInstances"], "/delivery/instancing/unpackedInstances")
    metrics = _list(value["platformMetrics"], "/delivery/platformMetrics", 64)
    metric_keys = {
        "platform", "triangles", "vertices", "textureBytes",
        "materialSlots", "instances",
    }
    for index, metric in enumerate(metrics):
        pointer = f"/delivery/platformMetrics/{index}"
        _keys(metric, pointer, metric_keys)
        _matching(metric["platform"], pointer + "/platform", _NAME_RE, "name")
        for key in metric_keys - {"platform"}:
            _count(metric[key], pointer + "/" + key)
    _ordered(metrics, "/delivery/platformMetrics", lambda item: item["platform"])


def _usd_shape(value: Any) -> None:
    _keys(value, "/usd", {
        "kind", "purpose", "variantSelections", "rootPrim", "defaultPrim",
        "payload", "primBindings",
    })
    _one_of(value["kind"], "/usd/kind", {"component", "assembly", "group"})
    _one_of(value["purpose"], "/usd/purpose", {"default", "proxy", "render", "guide"})
    _one_of(value["payload"], "/usd/payload", {"inline", "payload", "reference"})
    for key in ("rootPrim", "defaultPrim"):
        _matching(value[key], "/usd/" + key, _PRIM_RE, "USD prim path")
    selections = _list(value["variantSelections"], "/usd/variantSelections", 64)
    for index, selection in enumerate(selections):
        pointer = f"/usd/variantSelections/{index}"
        _keys(selection, pointer, {"name", "value"})
        _matching(selection["name"], pointer + "/name", _NAME_RE, "name")
        _matching(selection["value"], pointer + "/value", _NAME_RE, "name")
    _ordered(selections, "/usd/variantSelections", lambda item: item["name"])
    bindings = _list(value["primBindings"], "/usd/primBindings", 256)
    if not bindings:
        raise AssetContractError(
            "HOCUS953", "Expected at least one USD prim binding.", "/usd/primBindings",
        )
    for index, binding in enumerate(bindings):
        pointer = f"/usd/primBindings/{index}"
        _keys(binding, pointer, {
            "name", "role", "primPath", "purpose", "visibility", "materialPrimPath",
        })
        _matching(binding["name"], pointer + "/name", _NAME_RE, "name")
        _one_of(binding["role"], pointer + "/role", {"render", "collision"})
        _matching(binding["primPath"], pointer + "/primPath", _PRIM_RE, "USD prim path")
        _one_of(
            binding["purpose"], pointer + "/purpose",
            {"default", "proxy", "render", "guide"},
        )
        _one_of(
            binding["visibility"], pointer + "/visibility",
            {"inherited", "invisible"},
        )
        material = binding["materialPrimPath"]
        if material is not None:
            _matching(
                material,
                pointer + "/materialPrimPath",
                _PRIM_RE,
                "USD prim path",
            )
    _ordered(
        bindings,
        "/usd/primBindings",
        lambda item: (item["role"], item["name"]),
    )


def _validate_identity_space_naming(
    contract: dict[str, Any],
    observed: dict[str, Any],
    output: list[AssetContractDiagnostic],
) -> None:
    _equal(output, "HOCUS954", "/assetId", contract["identity"]["assetId"], observed["assetId"])
    space = contract["space"]
    facts = observed["space"]
    _equal(output, "HOCUS954", "/space/metersPerUnit", space["metersPerUnit"], facts["metersPerUnit"])
    for key in ("upAxis", "forwardAxis", "handedness"):
        _equal(output, "HOCUS954", "/space/" + key, space[key], facts[key])
    policy_id = contract["naming"]["policyId"]
    case_sensitive = contract["naming"]["caseSensitive"]
    names = observed["names"]
    for index, name in enumerate(names):
        if not _naming_policy_accepts(policy_id, name):
            _add(output, "HOCUS954", f"/names/{index}", policy_id, name)
    required = set(contract["naming"]["requiredNames"])
    actual = set(
        names if case_sensitive else (item.casefold() for item in names)
    )
    for name in sorted(required):
        candidate = name if case_sensitive else name.casefold()
        if candidate not in actual:
            _add(output, "HOCUS954", "/names", name, None)


def _validate_geometry(
    contract: dict[str, Any],
    observed: dict[str, Any],
    output: list[AssetContractDiagnostic],
) -> None:
    pivot = contract["pivot"]
    _vector_close(output, "/geometry/pivot", pivot["position"], observed["pivot"], pivot["tolerance"])
    bounds = contract["bounds"]
    _vector_close(output, "/geometry/bounds/minimum", bounds["minimum"], observed["bounds"]["minimum"], bounds["tolerance"])
    _vector_close(output, "/geometry/bounds/maximum", bounds["maximum"], observed["bounds"]["maximum"], bounds["tolerance"])
    topology = contract["topology"]
    facts = observed["topology"]
    for key in ("manifold", "watertight"):
        if topology[key]:
            _equal(output, "HOCUS955", "/geometry/topology/" + key, True, facts[key])
    _maximum(output, "HOCUS955", "/geometry/topology/maxNgonSides", topology["maxNgonSides"], facts["maxNgonSides"])
    if not topology["allowDegenerate"]:
        _maximum(output, "HOCUS955", "/geometry/topology/degenerateCount", 0, facts["degenerateCount"])
    _validate_frame(contract["normals"], observed["normals"], output, "normals")
    _validate_frame(contract["tangents"], observed["tangents"], output, "tangents")


def _validate_frame(
    contract: dict[str, Any],
    observed: dict[str, Any],
    output: list[AssetContractDiagnostic],
    name: str,
) -> None:
    flag = "consistent" if name == "normals" else "orthogonal"
    tolerance = "unitLengthTolerance" if name == "normals" else "orthogonalTolerance"
    error = "maxUnitLengthError" if name == "normals" else "maxOrthogonalError"
    if contract["required"]:
        _equal(output, "HOCUS955", f"/geometry/{name}/present", True, observed["present"])
    if contract[flag]:
        _equal(output, "HOCUS955", f"/geometry/{name}/{flag}", True, observed[flag])
    _maximum(output, "HOCUS955", f"/geometry/{name}/{error}", contract[tolerance], observed[error])


def _validate_surface(
    contract: dict[str, Any],
    space: dict[str, Any],
    observed: dict[str, Any],
    output: list[AssetContractDiagnostic],
    not_observed: list[dict[str, Any]],
) -> None:
    actual_uvs = {item["name"]: item for item in observed["uvSets"]}
    for uv_contract in contract["uvSets"]:
        pointer = "/surface/uvSets/" + uv_contract["name"]
        actual = actual_uvs.get(uv_contract["name"])
        if actual is None:
            if uv_contract["required"]:
                _add(output, "HOCUS956", pointer, "present", None)
            continue
        required_tiles = set(uv_contract["udimTiles"])
        actual_tiles = set(actual["udimTiles"])
        if not required_tiles.issubset(actual_tiles):
            _add(output, "HOCUS956", pointer + "/udimTiles", sorted(required_tiles), sorted(actual_tiles))
        duplicates = actual["duplicateUvTriangleCount"]
        if duplicates["status"] == "not_observed":
            _record_not_observed(
                not_observed,
                pointer + "/duplicateUvTriangleCount",
                duplicates,
                uv_contract["duplicateUvTriangleMeasurementRequired"],
            )
            if uv_contract["duplicateUvTriangleMeasurementRequired"]:
                _add(
                    output, "HOCUS956", pointer + "/duplicateUvTriangleCount",
                    "measured", duplicates,
                )
        elif not uv_contract["allowDuplicateUvTriangles"]:
            _maximum(
                output, "HOCUS956", pointer + "/duplicateUvTriangleCount",
                0, duplicates["value"],
            )
        density = uv_contract["texelDensity"]
        measured_density = actual["texelDensity"]
        if measured_density["status"] == "not_observed":
            _record_not_observed(
                not_observed,
                pointer + "/texelDensity",
                measured_density,
                uv_contract["texelDensityMeasurementRequired"],
            )
            if uv_contract["texelDensityMeasurementRequired"]:
                _add(
                    output, "HOCUS956", pointer + "/texelDensity",
                    "measured", measured_density,
                )
        else:
            normalized_density = _normalized_texel_density(
                measured_density,
                meters_per_unit=space["metersPerUnit"],
                target_unit=density["unit"],
            )
            _range(
                output, "HOCUS956", pointer + "/texelDensity",
                density["minimum"], density["maximum"],
                normalized_density,
            )
    actual_slots = set(observed["materialSlots"])
    for slot in contract["materialSlots"]:
        if slot["required"] and slot["name"] not in actual_slots:
            _add(output, "HOCUS956", "/surface/materialSlots", slot["name"], None)


def _validate_delivery(
    contract: dict[str, Any],
    observed: dict[str, Any],
    output: list[AssetContractDiagnostic],
    not_observed: list[dict[str, Any]],
) -> None:
    actual_lods = {item["name"]: item for item in observed["lods"]}
    for lod in contract["lods"]:
        pointer = "/delivery/lods/" + lod["name"]
        actual = actual_lods.get(lod["name"])
        if actual is None:
            _add(output, "HOCUS957", pointer, "present", None)
            continue
        for maximum_key, actual_key in (
            ("maxTriangles", "triangles"),
            ("maxVertices", "vertices"),
        ):
            _maximum(output, "HOCUS957", pointer + "/" + actual_key, lod[maximum_key], actual[actual_key])
        reduction = actual["relativeTriangleReduction"]
        if reduction["status"] == "not_observed":
            _record_not_observed(
                not_observed,
                pointer + "/relativeTriangleReduction",
                reduction,
                lod["relativeTriangleReductionMeasurementRequired"],
            )
            if lod["relativeTriangleReductionMeasurementRequired"]:
                _add(
                    output, "HOCUS957", pointer + "/relativeTriangleReduction",
                    "measured", reduction,
                )
        else:
            _maximum(
                output, "HOCUS957", pointer + "/relativeTriangleReduction",
                lod["maxRelativeTriangleReduction"], reduction["value"],
            )
    collision = contract["collision"]
    facts = observed["collision"]
    _equal(output, "HOCUS957", "/delivery/collision/mode", collision["mode"], facts["mode"])
    if collision["requireConvex"]:
        _equal(
            output,
            "HOCUS957",
            "/delivery/collision/convex",
            True,
            facts["convex"],
        )
    _maximum(output, "HOCUS957", "/delivery/collision/primitives", collision["maxPrimitives"], facts["primitives"])
    _maximum(output, "HOCUS957", "/delivery/collision/triangles", collision["maxTriangles"], facts["triangles"])
    instancing = contract["instancing"]
    facts = observed["instancing"]
    if instancing["required"]:
        _equal(output, "HOCUS957", "/delivery/instancing/used", True, facts["used"])
    for key in ("prototypePrimPath", "representation"):
        _equal(
            output,
            "HOCUS957",
            "/delivery/instancing/" + key,
            instancing[key],
            facts[key],
        )
    _maximum(output, "HOCUS957", "/delivery/instancing/uniqueMeshes", instancing["maxUniqueMeshes"], facts["uniqueMeshes"])
    _maximum(output, "HOCUS957", "/delivery/instancing/unpackedInstances", instancing["maxUnpackedInstances"], facts["unpackedInstances"])
    actual_budgets = {item["platform"]: item for item in observed["platformMetrics"]}
    for budget in contract["platformBudgets"]:
        pointer = "/delivery/platformMetrics/" + budget["platform"]
        actual = actual_budgets.get(budget["platform"])
        if actual is None:
            _add(output, "HOCUS957", pointer, "present", None)
            continue
        for maximum_key, actual_key in (
            ("maxTriangles", "triangles"), ("maxVertices", "vertices"),
            ("maxTextureBytes", "textureBytes"), ("maxMaterialSlots", "materialSlots"),
            ("maxInstances", "instances"),
        ):
            _maximum(output, "HOCUS957", pointer + "/" + actual_key, budget[maximum_key], actual[actual_key])


def _validate_usd(
    contract: dict[str, Any],
    observed: dict[str, Any],
    output: list[AssetContractDiagnostic],
) -> None:
    for key in ("kind", "purpose"):
        _equal(output, "HOCUS958", "/usd/" + key, contract[key], observed[key])
    publish = contract["publish"]
    for key in ("rootPrim", "defaultPrim", "payload"):
        _equal(output, "HOCUS958", "/usd/" + key, publish[key], observed[key])
    actual_bindings = {
        (item["role"], item["name"]): item
        for item in observed["primBindings"]
    }
    for expected in contract["primBindings"]:
        key = (expected["role"], expected["name"])
        pointer = "/usd/primBindings/" + expected["role"] + ":" + expected["name"]
        _equal(output, "HOCUS958", pointer, expected, actual_bindings.get(key))
    expected_keys = {
        (item["role"], item["name"])
        for item in contract["primBindings"]
    }
    for role, name in sorted(set(actual_bindings) - expected_keys):
        _add(
            output,
            "HOCUS958",
            "/usd/primBindings/" + role + ":" + name,
            None,
            actual_bindings[(role, name)],
        )
    actual = {item["name"]: item["value"] for item in observed["variantSelections"]}
    for variant in contract["variants"]:
        pointer = "/usd/variantSelections/" + variant["name"]
        selected = actual.get(variant["name"])
        if selected not in variant["allowedValues"]:
            _add(output, "HOCUS958", pointer, variant["allowedValues"], selected)
        elif variant["requiredValue"] is not None:
            _equal(output, "HOCUS958", pointer, variant["requiredValue"], selected)


def _validate_dependencies(
    contract: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    output: list[AssetContractDiagnostic],
) -> None:
    actual = {(item["kind"], item["id"]): item for item in observed}
    for dependency in contract:
        key = (dependency["kind"], dependency["id"])
        pointer = "/dependencies/" + dependency["kind"] + ":" + dependency["id"]
        found = actual.get(key)
        if found is None:
            _add(output, "HOCUS959", pointer, dependency, None)
            continue
        for field in ("version", "digest"):
            _equal(output, "HOCUS959", pointer + "/" + field, dependency[field], found[field])
    expected_keys = {(item["kind"], item["id"]) for item in contract}
    for kind, identifier in sorted(set(actual) - expected_keys):
        _add(
            output, "HOCUS959", "/dependencies/" + kind + ":" + identifier,
            None, actual[(kind, identifier)],
        )


def _keys(value: Any, pointer: str, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise AssetContractError("HOCUS953", "Asset observation has invalid object keys.", pointer)


def _list(value: Any, pointer: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise AssetContractError("HOCUS953", f"Expected at most {maximum} items.", pointer)
    return value


def _text(value: Any, pointer: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise AssetContractError("HOCUS953", "Expected bounded text.", pointer)
    return value


def _string_array(value: Any, pointer: str, maximum: int) -> list[str]:
    values = _list(value, pointer, maximum)
    for index, item in enumerate(values):
        _matching(item, f"{pointer}/{index}", _NAME_RE, "name")
    return values


def _matching(value: Any, pointer: str, pattern: re.Pattern[str], label: str) -> str:
    value = _text(value, pointer)
    if not pattern.fullmatch(value):
        raise AssetContractError("HOCUS953", f"Expected a path-free {label}.", pointer)
    return value


def _one_of(value: Any, pointer: str, allowed: set[str]) -> str:
    value = _text(value, pointer)
    if value not in allowed:
        raise AssetContractError("HOCUS953", "Observed enum value is unsupported.", pointer)
    return value


def _measurement(
    value: Any,
    pointer: str,
    *,
    integer: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssetContractError(
            "HOCUS953", "Observed measurement must be an object.", pointer,
        )
    status = value.get("status")
    if status == "measured":
        _keys(value, pointer, {"status", "value"})
        if integer:
            _count(value["value"], pointer + "/value")
        else:
            _finite(value["value"], pointer + "/value")
        return value
    if status == "not_observed":
        _keys(value, pointer, {"status", "reasonCode"})
        _one_of(
            value["reasonCode"],
            pointer + "/reasonCode",
            _NOT_OBSERVED_REASONS,
        )
        return value
    raise AssetContractError(
        "HOCUS953",
        "Observed measurement status must be measured or not_observed.",
        pointer + "/status",
    )


def _texel_density_measurement(
    value: Any,
    pointer: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssetContractError(
            "HOCUS953", "Observed measurement must be an object.", pointer,
        )
    if value.get("status") == "measured":
        _keys(value, pointer, {"status", "value", "unit"})
        _finite(value["value"], pointer + "/value")
        _one_of(
            value["unit"],
            pointer + "/unit",
            {"px_per_scene_unit", "px_per_m", "px_per_cm"},
        )
        return value
    return _measurement(value, pointer)


def _normalized_texel_density(
    measurement: dict[str, Any],
    *,
    meters_per_unit: float,
    target_unit: str,
) -> float:
    value = float(measurement["value"])
    source_unit = measurement["unit"]
    if source_unit == "px_per_scene_unit":
        px_per_m = value / meters_per_unit
    elif source_unit == "px_per_cm":
        px_per_m = value * 100.0
    else:
        px_per_m = value
    return px_per_m / 100.0 if target_unit == "px_per_cm" else px_per_m


def _record_not_observed(
    output: list[dict[str, Any]],
    pointer: str,
    measurement: dict[str, Any],
    required: bool,
) -> None:
    output.append({
        "jsonPointer": pointer,
        "reasonCode": measurement["reasonCode"],
        "required": required,
    })


def _ordered(value: list[Any], pointer: str, key) -> None:
    keys = [key(item) for item in value]
    if keys != sorted(set(keys)):
        raise AssetContractError(
            "HOCUS953", "Observed array must be sorted and unique.", pointer
        )


def _finite(value: Any, pointer: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AssetContractError("HOCUS953", "Expected a finite number.", pointer)
    return float(value)


def _count(value: Any, pointer: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000_000_000:
        raise AssetContractError("HOCUS953", "Expected a bounded nonnegative integer.", pointer)
    return value


def _bool(value: Any, pointer: str) -> bool:
    if not isinstance(value, bool):
        raise AssetContractError("HOCUS953", "Expected a boolean.", pointer)
    return value


def _vector(value: Any, pointer: str) -> None:
    values = _list(value, pointer, 3)
    if len(values) != 3:
        raise AssetContractError("HOCUS953", "Expected a three-component vector.", pointer)
    for index, item in enumerate(values):
        _finite(item, f"{pointer}/{index}")


def _add(
    output: list[AssetContractDiagnostic],
    code: str,
    pointer: str,
    expected: Any,
    actual: Any,
) -> None:
    output.append(AssetContractDiagnostic(
        severity="error",
        code=code,
        message="Observed asset does not satisfy its production contract.",
        json_pointer=pointer,
        expected=expected,
        actual=actual,
    ))


def _equal(
    output: list[AssetContractDiagnostic],
    code: str,
    pointer: str,
    expected: Any,
    actual: Any,
) -> None:
    if expected != actual:
        _add(output, code, pointer, expected, actual)


def _maximum(
    output: list[AssetContractDiagnostic],
    code: str,
    pointer: str,
    maximum: float,
    actual: float,
) -> None:
    if actual > maximum:
        _add(output, code, pointer, {"maximum": maximum}, actual)


def _range(
    output: list[AssetContractDiagnostic],
    code: str,
    pointer: str,
    minimum: float,
    maximum: float,
    actual: float,
) -> None:
    if not minimum <= actual <= maximum:
        _add(output, code, pointer, {"minimum": minimum, "maximum": maximum}, actual)


def _vector_close(
    output: list[AssetContractDiagnostic],
    pointer: str,
    expected: list[float],
    actual: list[float],
    tolerance: float,
) -> None:
    for index, (expected_value, actual_value) in enumerate(zip(expected, actual)):
        if abs(expected_value - actual_value) > tolerance:
            _add(output, "HOCUS955", f"{pointer}/{index}", {"value": expected_value, "tolerance": tolerance}, actual_value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
