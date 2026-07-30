"""Evidence-only HS8 clean-image/VM qualification wrapper.

The caller declaration and self-digested environment receipt are useful
provenance, but are not authenticated authority. Until CI injects verification
against an external trust anchor, this wrapper can collect evidence but cannot
authorize a release or certify the isolation boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


SCHEMA = "hocuspocus://schemas/hs8-clean-image-qualification/v1"
ENVIRONMENT_SCHEMA = (
    "hocuspocus://schemas/hs8-clean-image-environment/v1"
)
MAX_ENVIRONMENT_RECEIPT_BYTES = 64 * 1024
_DIGEST_LENGTH = len("sha256:") + 64


class CleanImageQualificationError(RuntimeError):
    """Fail-closed CI environment or delegated-qualification error."""


def qualify_clean_image(
    *,
    environment_receipt_path: Path,
    hython: Path,
    installed_root: Path,
    harness: Path | None,
    mode: str,
    timeout_seconds: float,
    temporary_parent: Path | None,
    visual_review: Path | None = None,
    trust_policy: Path | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Collect claimed clean-image evidence without granting authority."""

    if os.environ.get("HOCUSPOCUS_HS8_CLEAN_IMAGE") != "1":
        raise CleanImageQualificationError(
            "Clean-image qualification requires an external ephemeral runner."
        )
    environment = _read_environment_receipt(environment_receipt_path)
    qualifier = _same_host_qualifier()
    try:
        same_host = qualifier.qualify_two_clean_processes(
            hython=hython,
            installed_root=installed_root,
            harness=harness,
            mode=mode,
            timeout_seconds=timeout_seconds,
            visual_review=visual_review,
            trust_policy=trust_policy,
            temporary_parent=temporary_parent,
            evidence_root=evidence_root,
        )
    except qualifier.CleanProcessQualificationError as exc:
        raise CleanImageQualificationError(str(exc)) from exc
    installed_digest = same_host["installedPayload"]["manifestDigest"]
    if installed_digest != environment["installedPayloadManifestDigest"]:
        raise CleanImageQualificationError(
            "Clean-image receipt does not bind the installed HS8 payload."
        )
    unsigned = {
        "$schema": SCHEMA,
        "kind": "hocus_hs8_clean_image_qualification",
        "schemaVersion": 1,
        "passed": True,
        "isolationBoundary": "caller_declared_clean_image_or_vm",
        "qualificationMode": same_host["qualificationMode"],
        # Neither a caller-set environment flag nor a self-digested receipt is
        # an authenticated CI trust anchor.
        "releaseAuthorized": False,
        "environmentReceiptDigest": environment["receiptDigest"],
        "sameHostQualificationDigest": same_host["receiptDigest"],
        "visualReviewEvidenceDigest": same_host[
            "visualReviewEvidenceDigest"
        ],
        "visualApprovalDigest": same_host["visualApprovalDigest"],
        "installedPayloadManifestDigest": installed_digest,
    }
    unsigned["receiptDigest"] = _canonical_digest(unsigned)
    return unsigned


def _read_environment_receipt(path: Path) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CleanImageQualificationError(
            "Clean-image environment receipt is unavailable."
        ) from exc
    if not resolved.is_file() or resolved.stat().st_size > MAX_ENVIRONMENT_RECEIPT_BYTES:
        raise CleanImageQualificationError(
            "Clean-image environment receipt is missing or unbounded."
        )
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CleanImageQualificationError(
            "Clean-image environment receipt is invalid JSON."
        ) from exc
    return _normalize_environment_receipt(value)


def _normalize_environment_receipt(value: Any) -> dict[str, Any]:
    fields = {
        "$schema", "kind", "schemaVersion", "isolationBoundary", "ephemeral",
        "imageDigest", "runnerDigest", "sourceSnapshotDigest",
        "installedPayloadManifestDigest", "receiptDigest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CleanImageQualificationError(
            "Clean-image environment receipt has an invalid envelope."
        )
    if (
        value["$schema"] != ENVIRONMENT_SCHEMA
        or value["kind"] != "hocus_hs8_clean_image_environment"
        or value["schemaVersion"] != 1
        or value["isolationBoundary"] != "clean_image_or_vm"
        or value["ephemeral"] is not True
    ):
        raise CleanImageQualificationError(
            "Clean-image environment identity is invalid."
        )
    for field in (
        "imageDigest", "runnerDigest", "sourceSnapshotDigest",
        "installedPayloadManifestDigest", "receiptDigest",
    ):
        if not _is_digest(value[field]):
            raise CleanImageQualificationError(
                f"Clean-image environment {field} is invalid."
            )
    unsigned = {
        key: item for key, item in value.items() if key != "receiptDigest"
    }
    if value["receiptDigest"] != _canonical_digest(unsigned):
        raise CleanImageQualificationError(
            "Clean-image environment receipt digest does not match its content."
        )
    return dict(value)


def _same_host_qualifier() -> ModuleType:
    path = Path(__file__).resolve().with_name(
        "qualify_hocusscript_hs8_clean_process.py"
    )
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_hs8_same_host_qualifier", path,
    )
    if spec is None or spec.loader is None:
        raise CleanImageQualificationError(
            "Could not load the HS8 same-host qualifier."
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _is_digest(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or not value.startswith("sha256:")
    ):
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


def _canonical_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CleanImageQualificationError(
            "Clean-image receipt must contain finite JSON."
        ) from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect evidence inside a caller-declared ephemeral clean image "
            "or VM. The receipt is non-authoritative until CI verifies it "
            "against an external trust anchor."
        ),
    )
    parser.add_argument("--environment-receipt", required=True, type=Path)
    parser.add_argument("--hython", required=True, type=Path)
    parser.add_argument("--installed-root", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=("technical", "release"),
        default="technical",
    )
    parser.add_argument("--harness", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--temporary-parent", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--visual-review", type=Path)
    parser.add_argument("--trust-policy", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        receipt = qualify_clean_image(
            environment_receipt_path=arguments.environment_receipt,
            hython=arguments.hython,
            installed_root=arguments.installed_root,
            harness=arguments.harness,
            mode=arguments.mode,
            timeout_seconds=arguments.timeout_seconds,
            temporary_parent=arguments.temporary_parent,
            visual_review=arguments.visual_review,
            trust_policy=arguments.trust_policy,
            evidence_root=arguments.evidence_root,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except CleanImageQualificationError as exc:
        print(json.dumps({
            "accepted": False,
            "errorCode": "HOCUS994",
            "message": str(exc),
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
