"""Offline CLI for the external HS8 release-authority boundary."""

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

from hocuspocus.hocusscript.release_authority import (  # noqa: E402
    ReleaseAuthorityError,
    decode_json_document,
    verify_clean_image_attestation,
    verify_final_release_decision,
    verify_release_candidate_review_binding,
    verify_visual_approval,
)


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        content = path.expanduser().resolve(strict=True).read_bytes()
    except OSError as exc:
        raise ReleaseAuthorityError(f"{label} is unavailable.") from exc
    return decode_json_document(content, label=label)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify externally signed HS8 authority. The trust policy and "
            "expected bindings must come from independent operator inputs."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    clean = subparsers.add_parser("clean-image")
    _common(clean)
    clean.add_argument("--attestation", required=True, type=Path)
    clean.add_argument("--expected-clean-bindings", required=True, type=Path)
    visual = subparsers.add_parser("visual-approval")
    _common(visual)
    visual.add_argument("--approval", required=True, type=Path)
    visual.add_argument("--expected-review-request", required=True, type=Path)
    visual.add_argument("--expected-review-evidence", required=True, type=Path)
    _candidate_inputs(visual)
    release = subparsers.add_parser("release")
    _common(release)
    release.add_argument("--clean-image-attestation", required=True, type=Path)
    release.add_argument("--visual-approval", required=True, type=Path)
    release.add_argument("--final-decision", required=True, type=Path)
    release.add_argument("--expected-final-bindings", required=True, type=Path)
    release.add_argument("--expected-review-request", required=True, type=Path)
    release.add_argument("--expected-review-evidence", required=True, type=Path)
    _candidate_inputs(release)
    release.add_argument("--release-channel", required=True)
    return parser.parse_args(argv)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--trust-policy", required=True, type=Path)


def _candidate_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release-candidate-manifest", required=True, type=Path)
    parser.add_argument("--expected-candidate-inputs", required=True, type=Path)
    parser.add_argument("--rc1-evidence-set", required=True, type=Path)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        policy = _read(arguments.trust_policy, "Trust policy")
        if arguments.command == "clean-image":
            result = verify_clean_image_attestation(
                _read(arguments.attestation, "Clean-image attestation"),
                policy,
                _read(
                    arguments.expected_clean_bindings,
                    "Expected clean-image bindings",
                ),
            )
        elif arguments.command == "visual-approval":
            request = _read(
                arguments.expected_review_request,
                "Expected visual review request",
            )
            candidate = verify_release_candidate_review_binding(
                _read(
                    arguments.release_candidate_manifest,
                    "Release-candidate manifest",
                ),
                _read(
                    arguments.expected_candidate_inputs,
                    "Expected release-candidate inputs",
                ),
                _read(arguments.rc1_evidence_set, "RC1 evidence set"),
                request,
            )
            result = verify_visual_approval(
                _read(arguments.approval, "Signed visual approval"),
                policy,
                request,
                _read(
                    arguments.expected_review_evidence,
                    "Expected visual review evidence",
                ),
            )
            result["candidateManifestDigest"] = candidate["manifestDigest"]
        else:
            result = verify_final_release_decision(
                _read(
                    arguments.clean_image_attestation,
                    "Clean-image attestation",
                ),
                _read(arguments.visual_approval, "Signed visual approval"),
                _read(arguments.final_decision, "Final release decision"),
                policy,
                _read(
                    arguments.expected_final_bindings,
                    "Expected final bindings",
                ),
                expected_review_request=_read(
                    arguments.expected_review_request,
                    "Expected visual review request",
                ),
                expected_review_evidence=_read(
                    arguments.expected_review_evidence,
                    "Expected visual review evidence",
                ),
                release_candidate_manifest=_read(
                    arguments.release_candidate_manifest,
                    "Release-candidate manifest",
                ),
                expected_candidate_inputs=_read(
                    arguments.expected_candidate_inputs,
                    "Expected release-candidate inputs",
                ),
                rc1_evidence_set=_read(
                    arguments.rc1_evidence_set,
                    "RC1 evidence set",
                ),
                expected_release_channel=arguments.release_channel,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ReleaseAuthorityError as exc:
        print(
            json.dumps(
                {
                    "verified": False,
                    "releaseAuthorized": False,
                    "errorCode": "HOCUS995",
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
