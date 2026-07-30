"""Verify every supported HocusScript carrier row and emit an external receipt."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Callable

from release_evidence_support import (
    ROOT,
    canonical_json,
    content_digest,
    file_digest,
    receipt,
    write_receipt,
)

from hocuspocus.hocusscript import compile_source, resolve_graph
from hocuspocus.hocusscript.bundle import CompiledBundle, decode_compiled_bundle
from hocuspocus.hocusscript.contracts import (
    decode_control_bundle_envelope,
    decode_value_bundle_envelope,
)
from tests.hocusscript_hs7_helpers import value_bundle
from tests.test_hocusscript_authoring_scenarios import (
    _compiled_bundle,
    _control_bundle,
    _digest,
    _module_bundle,
    _provider,
)

GOLDEN_PATH = ROOT / "scripts" / "fixtures" / "release" / "compatibility-goldens.json"
DECODER_FIXTURE_PATH = (
    ROOT
    / "scripts"
    / "fixtures"
    / "release"
    / "compatibility-decoder-carriers.json"
)
LEGACY_SOURCE = """hocus 0.1;
graph compatibility {
  target "/obj/compatibility";
  category Sop;
  mode merge;
  node source: "acme::source::1.0" {}
  node sink_node: "sink" { input[0] = source.output[0]; }
  output = sink_node;
}
"""


def _redigest(carrier: dict[str, Any]) -> dict[str, Any]:
    unsigned = copy.deepcopy(carrier)
    unsigned.pop("bundleDigest", None)
    unsigned["bundleDigest"] = content_digest(canonical_json(unsigned))
    return unsigned


def _native_legacy_carrier(
    *,
    bundle_version: str,
    compiler_version: str,
    graph_spec_version: str,
) -> dict[str, Any]:
    provider = _provider()
    result = compile_source(
        LEGACY_SOURCE,
        "compatibility.hocus",
        source_uri="hocus-project://compatibility/compatibility.hocus",
    )
    if not result.valid or result.graph_spec is None:
        raise RuntimeError("Compatibility source failed structural compilation.")
    if bundle_version == "0.2":
        result.semantic_result = resolve_graph(result.graph_spec, provider)
        if not result.semantic_result.valid:
            raise RuntimeError("Compatibility source failed semantic resolution.")
        result.catalog_fingerprint = provider.catalog.fingerprint
        result.catalog_content_digest = _digest(provider.catalog.to_json())
    result.source_kind = "project_file"
    result.project_uid = "compatibility"
    result.project_manifest_digest = _digest("compatibility-manifest")
    result.project_lock_digest = _digest("compatibility-lock")
    carrier = CompiledBundle.from_result(result).to_dict()
    expected = (bundle_version, compiler_version, graph_spec_version)
    actual = (
        carrier["bundleVersion"],
        carrier["compilerVersion"],
        carrier["graphSpecVersion"],
    )
    if actual != expected:
        raise RuntimeError(
            "Current native source-to-carrier producer emitted an unexpected "
            f"compatibility tuple: {actual!r}."
        )
    return carrier


def _carriers() -> list[dict[str, Any]]:
    provider = _provider()
    value, _ = value_bundle(provider)
    definitions = (
        (
            "legacy-011-g01-b01",
            "0.1",
            "0.1.1",
            "0.1",
            "0.1",
            "retained-exact-decoder-fixture",
        ),
        (
            "legacy-020-g01-b01",
            "0.1",
            "0.2.0",
            "0.1",
            "0.1",
            "retained-exact-decoder-fixture",
        ),
        (
            "legacy-030-g02-b01",
            "0.1",
            "0.3.0",
            "0.2",
            "0.1",
            "native-source-to-carrier",
        ),
        (
            "legacy-020-g01-b02",
            "0.1",
            "0.2.0",
            "0.1",
            "0.2",
            "retained-exact-decoder-fixture",
        ),
        (
            "legacy-030-g02-b02",
            "0.1",
            "0.3.0",
            "0.2",
            "0.2",
            "native-source-to-carrier",
        ),
        (
            "static-040-g03-b03",
            "0.2",
            "0.4.0",
            "0.3",
            "0.3",
            "native-source-to-carrier",
        ),
        (
            "control-050-g04-b04",
            "0.3",
            "0.5.0",
            "0.4",
            "0.4",
            "native-source-to-carrier",
        ),
        (
            "value-060-g05-b05",
            "0.4",
            "0.6.0",
            "0.5",
            "0.5",
            "native-source-to-carrier",
        ),
    )
    decoder_document = json.loads(DECODER_FIXTURE_PATH.read_text(encoding="utf-8"))
    decoder_rows = decoder_document.get("rows")
    if (
        decoder_document.get("$schema")
        != "hocuspocus://schemas/internal-compatibility-decoder-fixtures/v1"
        or decoder_document.get("kind")
        != "hocus_internal_compatibility_decoder_fixtures"
        or type(decoder_document.get("schemaVersion")) is not int
        or decoder_document.get("schemaVersion") != 1
        or not isinstance(decoder_rows, list)
    ):
        raise ValueError("Compatibility decoder fixture envelope is invalid.")
    retained = {
        item["id"]: item["carrier"]
        for item in decoder_rows
        if isinstance(item, dict)
        and set(item) == {"id", "carrier"}
        and isinstance(item["id"], str)
        and isinstance(item["carrier"], dict)
    }
    expected_retained = {
        item[0] for item in definitions if item[-1] == "retained-exact-decoder-fixture"
    }
    if set(retained) != expected_retained or len(retained) != len(decoder_rows):
        raise ValueError("Compatibility decoder fixture rows are invalid.")
    current = {
        ("0.1", "0.3.0", "0.2", "0.1"): _native_legacy_carrier(
            bundle_version="0.1",
            compiler_version="0.3.0",
            graph_spec_version="0.2",
        ),
        ("0.1", "0.3.0", "0.2", "0.2"): _compiled_bundle().to_dict(),
        ("0.2", "0.4.0", "0.3", "0.3"): _module_bundle(),
        ("0.3", "0.5.0", "0.4", "0.4"): _control_bundle(),
        ("0.4", "0.6.0", "0.5", "0.5"): value,
    }
    rows: list[dict[str, Any]] = []
    for (
        row_id,
        language,
        compiler,
        graph_spec,
        bundle,
        proof_type,
    ) in definitions:
        key = (language, compiler, graph_spec, bundle)
        carrier = retained.get(row_id) if proof_type.startswith("retained-") else current[key]
        rows.append(
            {
                "id": row_id,
                "languageVersion": language,
                "compilerVersion": compiler,
                "graphSpecVersion": graph_spec,
                "bundleVersion": bundle,
                "proofType": proof_type,
                "carrier": carrier,
            }
        )
    return rows


def _decoder(bundle_version: str) -> Callable[[Any], Any]:
    if bundle_version == "0.4":
        return decode_control_bundle_envelope
    if bundle_version == "0.5":
        return decode_value_bundle_envelope
    return decode_compiled_bundle


def _golden(row: dict[str, Any]) -> dict[str, Any]:
    carrier = row["carrier"]
    return {
        key: row[key]
        for key in (
            "id",
            "languageVersion",
            "compilerVersion",
            "graphSpecVersion",
            "bundleVersion",
            "proofType",
        )
    } | ({
        "fixtureDigest": content_digest(canonical_json(carrier)),
        "graphSpecDigest": content_digest(canonical_json(carrier["graphSpec"])),
        "bundleDigest": carrier["bundleDigest"],
    } if row["proofType"] == "retained-exact-decoder-fixture" else {
        "entrySourceDigest": carrier["entrySource"]["digest"],
        "graphSpecDigest": content_digest(canonical_json(carrier["graphSpec"])),
        "bundleDigest": carrier["bundleDigest"],
    })


def _rejection(
    row: dict[str, Any],
    name: str,
    mutate: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    hostile = copy.deepcopy(row["carrier"])
    mutate(hostile)
    hostile = _redigest(hostile)
    try:
        _decoder(row["bundleVersion"])(hostile)
    except (TypeError, ValueError) as error:
        return {
            "case": name,
            "passed": True,
            "errorType": type(error).__name__,
            "diagnosticCode": getattr(error, "code", None),
        }
    return {"case": name, "passed": False, "errorType": None, "diagnosticCode": None}


def _row_evidence(row: dict[str, Any]) -> dict[str, Any]:
    carrier = row["carrier"]
    _decoder(row["bundleVersion"])(carrier)
    incompatible_compiler = {
        "0.1": "0.3.0",
        "0.2": "0.2.0",
        "0.3": "0.5.0",
        "0.4": "0.6.0",
        "0.5": "0.5.0",
    }[row["graphSpecVersion"]]
    next_bundle = {
        "0.1": "0.2",
        "0.2": "0.3",
        "0.3": "0.4",
        "0.4": "0.5",
        "0.5": "0.6",
    }[row["bundleVersion"]]
    rejections = [
        _rejection(
            row,
            "cross-row-field-mixing",
            lambda value: value.update(compilerVersion=incompatible_compiler),
        ),
        _rejection(
            row,
            "silent-version-upgrade",
            lambda value: value.update(
                bundleVersion=next_bundle,
                **{"$schema": f"hocuspocus://schemas/compiled-bundle/v{next_bundle}"},
            ),
        ),
        _rejection(
            row,
            "historical-field-smuggling",
            lambda value: value.update(
                legacyCompatibility={"compilerVersion": "0.1.1"}
            ),
        ),
    ]
    return {
        "id": row["id"],
        "exactDecodeAccepted": True,
        "rejections": rejections,
        "passed": all(item["passed"] for item in rejections),
    }


def run() -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    rows = _carriers()
    actual_goldens = [_golden(row) for row in rows]
    fixture = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    golden_match = fixture["rows"] == actual_goldens
    matrix = [_row_evidence(row) for row in rows]
    passed = golden_match and all(row["passed"] for row in matrix)
    evidence = {
        "goldenMatrixMatched": golden_match,
        "supportedRowCount": len(rows),
        "decoderFixtureRowCount": sum(
            row["proofType"] == "retained-exact-decoder-fixture"
            for row in rows
        ),
        "nativeSourceToCarrierRowCount": sum(
            row["proofType"] == "native-source-to-carrier"
            for row in rows
        ),
        "rows": matrix,
        "passed": passed,
    }
    value = receipt(
        "hocus_compatibility_matrix_receipt",
        evidence,
        fixture_digests={
            "compatibility-decoder-carriers.json": file_digest(
                DECODER_FIXTURE_PATH
            ),
            "compatibility-goldens.json": file_digest(GOLDEN_PATH),
        },
    )
    return value, actual_goldens, passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--print-goldens", action="store_true")
    arguments = parser.parse_args()
    value, goldens, passed = run()
    if arguments.print_goldens:
        print(json.dumps(goldens, allow_nan=False, indent=2, sort_keys=True))
    else:
        if arguments.output is None:
            parser.error("--output is required unless --print-goldens is used")
        write_receipt(arguments.output, value)
        print(json.dumps(value["evidence"], indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
