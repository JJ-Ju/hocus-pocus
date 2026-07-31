"""Shared bounded, path-free workspace recovery record."""

from __future__ import annotations

import json

MAX_RECOVERY_ARTIFACTS = 2
MAX_RECOVERY_BYTES = 24 * 1024 * 1024


class RecoveryRequired(OSError):
    def __init__(self, artifacts: tuple[dict[str, object], ...]):
        super().__init__(16, "workspace recovery evidence retained")
        self.artifacts = artifacts


def encode_recovery_record(
    target: str,
    parent: str,
    recovery: RecoveryRequired,
) -> bytes:
    artifacts = tuple(
        {**artifact, "path": "/".join(filter(None, (parent, str(artifact["path"]))))}
        for artifact in recovery.artifacts
    )
    total = sum(int(artifact["size"]) for artifact in artifacts)
    if len(artifacts) > MAX_RECOVERY_ARTIFACTS or total > MAX_RECOVERY_BYTES:
        raise OSError(27, "workspace recovery evidence exceeds bound")
    return json.dumps(
        {
            "artifacts": artifacts,
            "limits": {
                "maxArtifacts": MAX_RECOVERY_ARTIFACTS,
                "maxBytes": MAX_RECOVERY_BYTES,
                "maxIncidents": 1,
            },
            "resolution": "resolve target and artifacts, then delete marker last",
            "state": "unresolved",
            "target": target,
            "version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8") + b"\n"


def artifact_metadata(name: str, role: str, content: bytes) -> dict[str, object]:
    import hashlib

    return {
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "path": name,
        "role": role,
        "size": len(content),
    }
