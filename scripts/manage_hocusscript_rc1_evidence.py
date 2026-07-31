"""Create or verify a strict post-freeze RC1 evidence set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from release_evidence_support import (
    ROOT,
    canonical_json,
    content_digest,
    decode_internal_receipt,
    workspace_snapshot,
    write_receipt,
)
from hs8_install_manifest import create_manifest

from hocuspocus.hocusscript.release_evidence import (
    ReleaseEvidenceError,
    create_rc1_evidence_set,
    verify_rc1_evidence_set,
)
from hocuspocus.live.package_search_provenance import (
    PACKAGE_SEARCH_SCHEMA,
    PackageSearchProvenanceError,
    decode_effective_package_search,
)

_INTERNAL = {
    "performance": "hocus_performance_benchmark_receipt",
    "compatibility": "hocus_compatibility_matrix_receipt",
    "graphStore": "hocus_graph_store_upgrade_receipt",
}
_INTERNAL_SCHEMA = "hocuspocus://schemas/internal-release-evidence/v1"


def _read(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        content = path.expanduser().resolve(strict=True).read_bytes()
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"invalid constant {item}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseEvidenceError(f"{label} is not strict JSON.") from exc
    if not isinstance(value, dict):
        raise ReleaseEvidenceError(f"{label} must be a JSON object.")
    return value, content_digest(content)


def _candidate(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot["clean"] is not True:
        raise ReleaseEvidenceError(
            "RC1 evidence must be rerun after freeze on a clean worktree."
        )
    return {
        "commitDigest": snapshot["commitDigest"],
        "treeDigest": snapshot["treeDigest"],
        "workspaceSnapshotDigest": snapshot["snapshotDigest"],
        "fileCount": len(snapshot["entries"]),
        "clean": True,
    }


def _identities(arguments: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    current = workspace_snapshot()
    source_manifest = create_manifest(ROOT)
    identities = {}
    for name, kind in _INTERNAL.items():
        value, file_hash = _read(getattr(arguments, name), kind)
        decoded = decode_internal_receipt(value, expected_kind=kind)
        if decoded["candidate"] != current:
            raise ReleaseEvidenceError(
                f"{kind} was not produced from the current exact workspace."
            )
        identities[name] = {
            "schema": _INTERNAL_SCHEMA,
            "kind": kind,
            "receiptDigest": decoded["receiptDigest"],
            "fileDigest": file_hash,
        }
    package, package_file_hash = _read(
        arguments.packageSearch,
        "Effective package-search receipt",
    )
    decoded_package = decode_effective_package_search(package)
    _verify_current_installed_payload(decoded_package, source_manifest)
    identities["packageSearch"] = {
        "schema": PACKAGE_SEARCH_SCHEMA,
        "kind": decoded_package["kind"],
        "receiptDigest": decoded_package["receiptDigest"],
        "fileDigest": package_file_hash,
        "installedPayloadManifestDigest": decoded_package[
            "installedPayload"
        ]["manifestDigest"],
        "runtimeDigest": content_digest(
            canonical_json(decoded_package["houdini"])
        ),
    }
    if create_manifest(ROOT) != source_manifest or workspace_snapshot() != current:
        raise ReleaseEvidenceError(
            "Workspace changed while RC1 package evidence was bound."
        )
    return _candidate(current), identities


def _verify_current_installed_payload(
    package_receipt: dict[str, Any],
    source_manifest: dict[str, Any],
) -> None:
    installed = package_receipt["installedPayload"]
    if (
        installed["manifestDigest"] != source_manifest["manifestDigest"]
        or installed["artifactCount"] != len(source_manifest["files"])
    ):
        raise ReleaseEvidenceError(
            "Effective package-search receipt was not produced from the "
            "current exact governed source payload."
        )


def _output(path: Path, value: dict[str, Any]) -> Path:
    try:
        return write_receipt(path, value)
    except ValueError as exc:
        raise ReleaseEvidenceError(str(exc)) from exc


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "verify"):
        selected = subparsers.add_parser(command)
        selected.add_argument("--performance", required=True, type=Path)
        selected.add_argument("--compatibility", required=True, type=Path)
        selected.add_argument("--graph-store", dest="graphStore", required=True, type=Path)
        selected.add_argument(
            "--package-search",
            dest="packageSearch",
            required=True,
            type=Path,
        )
        if command == "create":
            selected.add_argument("--output", required=True, type=Path)
        else:
            selected.add_argument("--evidence-set", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        candidate, identities = _identities(arguments)
        expected = create_rc1_evidence_set(candidate, identities)
        if arguments.command == "create":
            _output(arguments.output, expected)
            result = expected
        else:
            supplied, _ = _read(arguments.evidence_set, "RC1 evidence set")
            verified = verify_rc1_evidence_set(supplied)
            if verified != expected:
                raise ReleaseEvidenceError(
                    "RC1 evidence set differs from current receipts or workspace."
                )
            result = verified
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        OSError,
        PackageSearchProvenanceError,
        ReleaseEvidenceError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "verified": False,
                    "releaseAuthorized": False,
                    "errorCode": "HOCUS997",
                    "message": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate field: {key}")
        value[key] = item
    return value


if __name__ == "__main__":
    raise SystemExit(main())
