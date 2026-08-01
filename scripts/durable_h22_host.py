"""Disposable Houdini 22 host used by the durable stdio acceptance harness."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import hou  # type: ignore

from hocuspocus.core.server import HocusPocusRuntime
from hocuspocus.core.settings import load_settings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--launch-generation", type=int, required=True)
    parser.add_argument("--installed-root", type=Path, required=True)
    return parser.parse_args()


def _installed_alignment(root: Path) -> tuple[str, list[dict[str, str]]]:
    from hs8_install_manifest import audit_loaded_modules, verify_manifest

    manifest = verify_manifest(root)
    selected = {
        name: module
        for name, module in sys.modules.items()
        if module is not None
        and (name == "hocuspocus" or name.startswith("hocuspocus."))
    }
    return manifest["manifestDigest"], audit_loaded_modules(root, selected, manifest)


def _write_ready(
    path: Path,
    runtime: HocusPocusRuntime,
    generation: int,
    alignment: tuple[str, list[dict[str, str]]],
) -> None:
    manifest_digest, module_receipts = alignment
    payload = {
        "schemaVersion": 1,
        "pid": os.getpid(),
        "launchGeneration": generation,
        "hostInstanceId": runtime.host_identity.instance_id,
        "hostGeneration": runtime.host_identity.generation,
        "houdiniVersion": hou.applicationVersionString(),
        "port": runtime.settings.port,
        "authRequired": runtime.settings.token_mode != "disabled",
        "installManifestDigest": manifest_digest,
        "moduleReceipts": module_receipts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    candidate.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    candidate.replace(path)


def main() -> int:
    arguments = _arguments()
    if not hou.applicationVersionString().startswith("22."):
        raise RuntimeError("Durability acceptance requires Houdini 22.")
    installed_root = arguments.installed_root.resolve(strict=True)
    settings = load_settings(installed_root / "config" / "default.toml")
    settings.host = "127.0.0.1"
    settings.port = arguments.port
    settings.auto_start = False
    if settings.token_mode == "disabled" or not settings.resolved_token():
        raise RuntimeError("Durability acceptance requires bearer authentication.")
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    runtime = HocusPocusRuntime(
        settings,
        logging.getLogger("hocuspocus.durable-host"),
    )
    runtime.start()
    alignment = _installed_alignment(installed_root)
    _write_ready(
        arguments.ready_file,
        runtime,
        arguments.launch_generation,
        alignment,
    )
    try:
        for line in sys.stdin:
            if line.strip().lower() == "stop":
                break
    finally:
        runtime.stop()
        try:
            arguments.ready_file.unlink()
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
