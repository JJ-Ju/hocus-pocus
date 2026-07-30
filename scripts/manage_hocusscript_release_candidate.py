"""Create or verify one strict RC2 release-candidate manifest offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "python3.11libs"
if str(LIBRARY) not in sys.path:
    sys.path.insert(0, str(LIBRARY))

from release_evidence_support import write_receipt  # noqa: E402

from hocuspocus.hocusscript.release_authority import (  # noqa: E402
    ReleaseAuthorityError,
    decode_json_document,
)
from hocuspocus.hocusscript.release_candidate import (  # noqa: E402
    ReleaseCandidateError,
    create_release_candidate_manifest,
    verify_release_candidate_manifest,
)


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        content = path.expanduser().resolve(strict=True).read_bytes()
    except OSError as exc:
        raise ReleaseCandidateError(f"{label} is unavailable.") from exc
    try:
        return decode_json_document(content, label=label)
    except ReleaseAuthorityError as exc:
        raise ReleaseCandidateError(str(exc)) from exc


def _output(path: Path, value: dict[str, Any]) -> Path:
    try:
        return write_receipt(path, value)
    except ValueError as exc:
        raise ReleaseCandidateError(str(exc)) from exc


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or verify a self-digested immutable-candidate identity. "
            "This command never grants release authority."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--inputs", required=True, type=Path)
    create.add_argument("--rc1-evidence-set", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", required=True, type=Path)
    verify.add_argument("--expected-inputs", required=True, type=Path)
    verify.add_argument("--rc1-evidence-set", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        if arguments.command == "create":
            inputs = _read(arguments.inputs, "Release-candidate inputs")
            evidence = _read(arguments.rc1_evidence_set, "RC1 evidence set")
            manifest = create_release_candidate_manifest(inputs, evidence)
            output = _output(arguments.output, manifest)
            result = verify_release_candidate_manifest(
                manifest,
                inputs,
                evidence,
            )
            result["output"] = str(output)
        else:
            result = verify_release_candidate_manifest(
                _read(arguments.manifest, "Release-candidate manifest"),
                _read(arguments.expected_inputs, "Expected RC2 inputs"),
                _read(arguments.rc1_evidence_set, "RC1 evidence set"),
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ReleaseCandidateError as exc:
        print(
            json.dumps(
                {
                    "verified": False,
                    "immutableCandidateIdentified": False,
                    "releaseAuthorized": False,
                    "errorCode": "HOCUS996",
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
