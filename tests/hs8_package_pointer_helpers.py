"""Private package-pointer fixtures for the existing HS8 scenario."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def pointer_authority_files(root: Path) -> tuple[str, str]:
    config = b'token_mode = "generated"\ntoken = "' + b"x" * 32 + b'"\n'
    config_path = root / "config" / "default.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(config)
    manifest_digest = "sha256:" + hashlib.sha256(b"manifest").hexdigest()
    manifest_path = root / "package" / "install-manifest-v1.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({"manifestDigest": manifest_digest}),
        encoding="utf-8",
    )
    return "sha256:" + hashlib.sha256(config).hexdigest(), manifest_digest


def package_pointer(
    root_name: str,
    config_digest: str,
    manifest_digest: str,
) -> dict[str, Any]:
    return {
        "env": [
            {"HOCUSPOCUS_ROOT": f"$HOUDINI_PACKAGE_PATH/{root_name}"},
            {
                "PYTHONPATH": {
                    "method": "prepend",
                    "value": "$HOCUSPOCUS_ROOT/python3.11libs",
                }
            },
            {"PYTHONDONTWRITEBYTECODE": "1"},
        ],
        "hpath": "$HOCUSPOCUS_ROOT",
        "hocuspocus": {
            "schemaVersion": 1,
            "activeConfigDigest": config_digest,
            "installManifestDigest": manifest_digest,
        },
    }


__all__ = ["package_pointer", "pointer_authority_files"]
