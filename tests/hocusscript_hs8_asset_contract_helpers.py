from __future__ import annotations

import json

from hocuspocus.hocusscript.asset_contract import (
    AssetContractError,
    canonical_asset_contract_json,
    decode_asset_contract,
)
from hocuspocus.hocusscript.asset_contract_validation import validate_asset_contract


def _contract() -> dict:
    digest = "sha256:" + "1" * 64
    return {
        "$schema": "hocuspocus://schemas/asset-contract/v1",
        "kind": "hocus_asset_contract",
        "contractVersion": 1,
        "identity": {
            "assetId": "rock_family.a",
            "name": "RockFamily",
            "assetType": "rock",
        },
        "space": {
            "linearUnit": "meter",
            "metersPerUnit": 1.0,
            "upAxis": "Y",
            "forwardAxis": "-Z",
            "handedness": "right",
        },
        "naming": {
            "policyId": "uppercase_ascii_asset_name_v1",
            "caseSensitive": True,
            "requiredNames": ["Rock_LOD0"],
        },
        "geometry": {
            "pivot": {
                "mode": "base",
                "position": [0.0, 0.0, 0.0],
                "tolerance": 0.001,
            },
            "bounds": {
                "minimum": [-1.0, 0.0, -1.0],
                "maximum": [1.0, 2.0, 1.0],
                "tolerance": 0.01,
            },
            "topology": {
                "manifold": True,
                "watertight": True,
                "maxNgonSides": 4,
                "allowDegenerate": False,
            },
            "normals": {
                "required": True,
                "consistent": True,
                "unitLengthTolerance": 0.01,
            },
            "tangents": {
                "required": True,
                "orthogonal": True,
                "orthogonalTolerance": 0.01,
            },
        },
        "surface": {
            "uvSets": [{
                "name": "st",
                "required": True,
                "udimTiles": [1001],
                "allowDuplicateUvTriangles": False,
                "duplicateUvTriangleMeasurementRequired": True,
                "texelDensityMeasurementRequired": True,
                "texelDensity": {
                    "minimum": 512.0,
                    "maximum": 1024.0,
                    "unit": "px_per_m",
                },
            }],
            "materialSlots": [{"name": "Rock", "required": True}],
        },
        "delivery": {
            "lods": [{
                "name": "LOD0",
                "maxTriangles": 50000,
                "maxVertices": 30000,
                "maxRelativeTriangleReduction": 1.0,
                "relativeTriangleReductionMeasurementRequired": True,
            }],
            "collision": {
                "mode": "convex",
                "requireConvex": True,
                "maxPrimitives": 8,
                "maxTriangles": 1000,
            },
            "instancing": {
                "required": True,
                "prototypePrimPath": "/Rock/Prototype",
                "representation": "native_instance",
                "maxUniqueMeshes": 4,
                "maxUnpackedInstances": 0,
            },
            "platformBudgets": [{
                "platform": "PC",
                "maxTriangles": 50000,
                "maxVertices": 30000,
                "maxTextureBytes": 67108864,
                "maxMaterialSlots": 2,
                "maxInstances": 10000,
            }],
        },
        "usd": {
            "kind": "component",
            "purpose": "render",
            "variants": [{
                "name": "quality",
                "allowedValues": ["high", "low"],
                "requiredValue": "high",
            }],
            "publish": {
                "rootPrim": "/Rock",
                "defaultPrim": "/Rock",
                "payload": "payload",
            },
            "primBindings": [
                {
                    "name": "collision",
                    "role": "collision",
                    "primPath": "/Rock/Prototype/Collision",
                    "purpose": "proxy",
                    "visibility": "invisible",
                    "materialPrimPath": None,
                },
                {
                    "name": "LOD0",
                    "role": "render",
                    "primPath": "/Rock/Prototype/LOD0",
                    "purpose": "render",
                    "visibility": "inherited",
                    "materialPrimPath": "/Rock/Looks/Rock",
                },
            ],
        },
        "dependencies": [{
            "id": "rock_material",
            "kind": "asset",
            "version": "1.0.0",
            "digest": digest,
        }],
    }


def _observation() -> dict:
    digest = "sha256:" + "1" * 64
    return {
        "assetId": "rock_family.a",
        "space": {
            "metersPerUnit": 1.0,
            "upAxis": "Y",
            "forwardAxis": "-Z",
            "handedness": "right",
        },
        "names": ["Rock_LOD0"],
        "geometry": {
            "pivot": [0.0, 0.0, 0.0],
            "bounds": {
                "minimum": [-1.0, 0.0, -1.0],
                "maximum": [1.0, 2.0, 1.0],
            },
            "topology": {
                "manifold": True,
                "watertight": True,
                "maxNgonSides": 4,
                "degenerateCount": 0,
            },
            "normals": {
                "present": True,
                "consistent": True,
                "maxUnitLengthError": 0.001,
            },
            "tangents": {
                "present": True,
                "orthogonal": True,
                "maxOrthogonalError": 0.001,
            },
        },
        "surface": {
            "uvSets": [{
                "name": "st",
                "udimTiles": [1001],
                "duplicateUvTriangleCount": {
                    "status": "measured", "value": 0,
                },
                "texelDensity": {
                    "status": "measured",
                    "value": 700.0,
                    "unit": "px_per_scene_unit",
                },
            }],
            "materialSlots": ["Rock"],
            "textureBytes": 4096,
        },
        "delivery": {
            "lods": [{
                "name": "LOD0",
                "triangles": 40000,
                "vertices": 25000,
                "relativeTriangleReduction": {
                    "status": "measured", "value": 0.5,
                },
            }],
            "collision": {
                "mode": "convex",
                "convex": True,
                "primitives": 4,
                "triangles": 500,
            },
            "instancing": {
                "used": True,
                "prototypePrimPath": "/Rock/Prototype",
                "representation": "native_instance",
                "uniqueMeshes": 2,
                "unpackedInstances": 0,
            },
            "platformMetrics": [{
                "platform": "PC",
                "triangles": 40000,
                "vertices": 25000,
                "textureBytes": 4096,
                "materialSlots": 1,
                "instances": 500,
            }],
        },
        "usd": {
            "kind": "component",
            "purpose": "render",
            "variantSelections": [{"name": "quality", "value": "high"}],
            "rootPrim": "/Rock",
            "defaultPrim": "/Rock",
            "payload": "payload",
            "primBindings": [
                {
                    "name": "collision",
                    "role": "collision",
                    "primPath": "/Rock/Prototype/Collision",
                    "purpose": "proxy",
                    "visibility": "invisible",
                    "materialPrimPath": None,
                },
                {
                    "name": "LOD0",
                    "role": "render",
                    "primPath": "/Rock/Prototype/LOD0",
                    "purpose": "render",
                    "visibility": "inherited",
                    "materialPrimPath": "/Rock/Looks/Rock",
                },
            ],
        },
        "dependencies": [{
            "id": "rock_material",
            "kind": "asset",
            "version": "1.0.0",
            "digest": digest,
        }],
    }


def assert_hs8_asset_contract_foundation(testcase) -> None:
    contract = _contract()
    observed = _observation()
    decoded = decode_asset_contract(contract)
    testcase.assertEqual(
        decoded.digest,
        decode_asset_contract(json.dumps(contract, indent=2)).digest,
    )
    testcase.assertEqual(
        canonical_asset_contract_json(contract),
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    valid = validate_asset_contract(contract, observed)
    testcase.assertTrue(valid.valid)
    testcase.assertEqual(valid.diagnostics, ())
    testcase.assertEqual(valid.coverage, {"notObserved": []})
    testcase.assertEqual(valid.digest, validate_asset_contract(contract, observed).digest)
    wrong_prototype = json.loads(json.dumps(observed))
    wrong_prototype["delivery"]["instancing"]["prototypePrimPath"] = (
        "/Rock/WrongPrototype"
    )
    prototype_report = validate_asset_contract(contract, wrong_prototype)
    testcase.assertFalse(prototype_report.valid)
    testcase.assertIn(
        "/delivery/instancing/prototypePrimPath",
        {item.json_pointer for item in prototype_report.diagnostics},
    )
    unsupported_representation = json.loads(json.dumps(contract))
    unsupported_representation["delivery"]["instancing"]["representation"] = (
        "packed_primitive"
    )
    with testcase.assertRaises(AssetContractError):
        decode_asset_contract(unsupported_representation)

    centimeter_contract = json.loads(json.dumps(contract))
    centimeter_contract["space"]["linearUnit"] = "centimeter"
    centimeter_contract["space"]["metersPerUnit"] = 0.01
    centimeter_observation = json.loads(json.dumps(observed))
    centimeter_observation["space"]["metersPerUnit"] = 0.01
    centimeter_observation["surface"]["uvSets"][0]["texelDensity"]["value"] = 7.0
    testcase.assertTrue(
        validate_asset_contract(
            centimeter_contract,
            centimeter_observation,
        ).valid
    )
    wrong_unit_contract = json.loads(json.dumps(centimeter_contract))
    wrong_unit_contract["surface"]["uvSets"][0]["texelDensity"]["unit"] = (
        "px_per_cm"
    )
    testcase.assertFalse(
        validate_asset_contract(
            wrong_unit_contract,
            centimeter_observation,
        ).valid
    )
    px_per_cm_contract = json.loads(json.dumps(wrong_unit_contract))
    px_per_cm_contract["surface"]["uvSets"][0]["texelDensity"].update({
        "minimum": 5.12,
        "maximum": 10.24,
    })
    testcase.assertTrue(
        validate_asset_contract(
            px_per_cm_contract,
            centimeter_observation,
        ).valid
    )
    ambiguous_density = json.loads(json.dumps(observed))
    ambiguous_density["surface"]["uvSets"][0]["texelDensity"].pop("unit")
    with testcase.assertRaises(AssetContractError) as rejected:
        validate_asset_contract(contract, ambiguous_density)
    testcase.assertEqual(rejected.exception.code, "HOCUS953")

    failed = json.loads(json.dumps(observed))
    failed["names"] = ["bad"]
    failed["geometry"]["topology"]["manifold"] = False
    failed["surface"]["uvSets"][0]["texelDensity"]["value"] = 1.0
    failed["delivery"]["lods"][0]["triangles"] = 50001
    failed["usd"]["purpose"] = "proxy"
    failed["dependencies"][0]["version"] = "2.0.0"
    report = validate_asset_contract(contract, failed)
    testcase.assertFalse(report.valid)
    testcase.assertEqual(
        {item.code for item in report.diagnostics},
        {"HOCUS954", "HOCUS955", "HOCUS956", "HOCUS957", "HOCUS958", "HOCUS959"},
    )
    testcase.assertEqual(
        [item.json_pointer for item in report.diagnostics],
        sorted(item.json_pointer for item in report.diagnostics),
    )
    testcase.assertNotIn("\\", json.dumps(report.to_dict()))

    partial_contract = json.loads(json.dumps(contract))
    partial_contract["surface"]["uvSets"][0][
        "duplicateUvTriangleMeasurementRequired"
    ] = False
    partial_contract["surface"]["uvSets"][0][
        "texelDensityMeasurementRequired"
    ] = False
    partial_contract["delivery"]["lods"][0][
        "relativeTriangleReductionMeasurementRequired"
    ] = False
    partial = json.loads(json.dumps(observed))
    partial["surface"]["uvSets"][0]["duplicateUvTriangleCount"] = {
        "status": "not_observed",
        "reasonCode": "host_api_unavailable",
    }
    partial["surface"]["uvSets"][0]["texelDensity"] = {
        "status": "not_observed",
        "reasonCode": "texture_resolution_unavailable",
    }
    partial["delivery"]["lods"][0]["relativeTriangleReduction"] = {
        "status": "not_observed",
        "reasonCode": "runtime_camera_model_unavailable",
    }
    partial_report = validate_asset_contract(partial_contract, partial)
    testcase.assertTrue(partial_report.valid)
    testcase.assertEqual(len(partial_report.coverage["notObserved"]), 3)
    testcase.assertTrue(
        all(not item["required"] for item in partial_report.coverage["notObserved"])
    )

    malformed = json.loads(json.dumps(contract))
    malformed["hostPath"] = "C:\\secret\\asset"
    with testcase.assertRaises(AssetContractError) as rejected:
        decode_asset_contract(malformed)
    testcase.assertEqual(rejected.exception.code, "HOCUS950")

    noncanonical = json.loads(json.dumps(contract))
    noncanonical["surface"]["uvSets"][0]["udimTiles"] = [1002, 1001]
    with testcase.assertRaises(AssetContractError) as rejected:
        decode_asset_contract(noncanonical)
    testcase.assertEqual(rejected.exception.code, "HOCUS952")

    unsupported_policy = json.loads(json.dumps(contract))
    unsupported_policy["naming"]["policyId"] = "caller_regex_v1"
    with testcase.assertRaises(AssetContractError) as rejected:
        decode_asset_contract(unsupported_policy)
    testcase.assertEqual(rejected.exception.code, "HOCUS950")

    caller_regex = json.loads(json.dumps(contract))
    caller_regex["naming"]["pattern"] = "^(a|aa)+$"
    with testcase.assertRaises(AssetContractError) as rejected:
        decode_asset_contract(caller_regex)
    testcase.assertEqual(rejected.exception.code, "HOCUS950")

    bad_observation = json.loads(json.dumps(observed))
    bad_observation["hostPath"] = "/tmp/private"
    with testcase.assertRaises(AssetContractError) as rejected:
        validate_asset_contract(contract, bad_observation)
    testcase.assertEqual(rejected.exception.code, "HOCUS953")
