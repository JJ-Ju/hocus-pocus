"""Shared canonical receipt helpers for internal V1 release evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIB = ROOT / "python3.11libs"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_DIGEST = re.compile(
    r"^(?:git-sha1:[0-9a-f]{40}|git-sha256:[0-9a-f]{64})$"
)
for path in (ROOT, PYTHON_LIB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_digest(value: bytes | str) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    return content_digest(path.read_bytes())


def candidate_identity() -> dict[str, Any]:
    return workspace_snapshot()


def workspace_snapshot() -> dict[str, Any]:
    """Hash every tracked and untracked nonignored candidate input."""

    before = _workspace_state()
    paths = _candidate_paths()
    entries = _snapshot_entries(paths, _tracked_modes())
    confirmed_paths = _candidate_paths()
    confirmed_entries = _snapshot_entries(confirmed_paths, _tracked_modes())
    after = _workspace_state()
    if (
        before != after
        or paths != confirmed_paths
        or entries != confirmed_entries
    ):
        raise RuntimeError("Workspace changed while its candidate snapshot was read.")
    unsigned = {
        "$schema": "hocuspocus://schemas/internal-workspace-snapshot/v1",
        "kind": "hocus_internal_workspace_snapshot",
        "schemaVersion": 1,
        "commitDigest": before["commitDigest"],
        "treeDigest": before["treeDigest"],
        "clean": before["clean"],
        "entries": entries,
    }
    return {**unsigned, "snapshotDigest": content_digest(canonical_json(unsigned))}


def _snapshot_entries(
    paths: list[str],
    modes: dict[str, str],
) -> list[dict[str, Any]]:
    entries = []
    for relative in paths:
        path = ROOT / Path(relative)
        if path.is_symlink():
            target = os.readlink(path)
            content = target.encode("utf-8")
            kind = "symlink"
        elif path.is_file():
            content = path.read_bytes()
            kind = "file"
        elif not path.exists():
            content = b""
            kind = "missing"
        else:
            raise RuntimeError(f"Candidate input is not a file: {relative}")
        entries.append(
            {
                "path": relative,
                "kind": kind,
                "gitMode": modes.get(relative),
                "byteLength": len(content),
                "contentDigest": content_digest(content),
            }
        )
    return entries


def environment_identity(
    *,
    houdini_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    identity = {
        "machine": platform.node(),
        "operatingSystem": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "pythonImplementation": platform.python_implementation(),
    }
    if houdini_identity is not None:
        identity["houdini"] = houdini_identity
    return identity


def receipt(
    kind: str,
    evidence: dict[str, Any],
    *,
    fixture_digests: dict[str, str],
    houdini_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unsigned = {
        "$schema": "hocuspocus://schemas/internal-release-evidence/v1",
        "kind": kind,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "candidate": candidate_identity(),
        "environment": environment_identity(houdini_identity=houdini_identity),
        "fixtureDigests": dict(sorted(fixture_digests.items())),
        "evidence": evidence,
    }
    return {**unsigned, "receiptDigest": content_digest(canonical_json(unsigned))}


def decode_internal_receipt(
    value: Any,
    *,
    expected_kind: str,
) -> dict[str, Any]:
    fields = {
        "$schema",
        "kind",
        "generatedAt",
        "candidate",
        "environment",
        "fixtureDigests",
        "evidence",
        "receiptDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Internal release receipt has an invalid envelope.")
    if (
        value["$schema"] != "hocuspocus://schemas/internal-release-evidence/v1"
        or value["kind"] != expected_kind
        or not isinstance(value["generatedAt"], str)
        or not isinstance(value["environment"], dict)
        or not isinstance(value["fixtureDigests"], dict)
        or not isinstance(value["evidence"], dict)
        or value["evidence"].get("passed") is not True
    ):
        raise ValueError("Internal release receipt identity or result is invalid.")
    _validate_workspace_snapshot(value["candidate"])
    unsigned = {key: item for key, item in value.items() if key != "receiptDigest"}
    if value["receiptDigest"] != content_digest(canonical_json(unsigned)):
        raise ValueError("Internal release receipt digest does not match its content.")
    return value


def write_receipt(path: Path, value: dict[str, Any]) -> Path:
    content = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    target = _external_output_path(path)
    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{target.name}.candidate.",
            dir=target.parent,
        )
        temporary = Path(raw_temporary)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
    except FileExistsError as exc:
        raise ValueError("Release receipt output already exists.") from exc
    except OSError as exc:
        raise ValueError(
            "Release receipt could not be published exclusively."
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise ValueError(
                    "Release receipt temporary output could not be removed."
                ) from exc
    return target


def _external_output_path(path: Path) -> Path:
    expanded = path.expanduser()
    lexical = Path(os.path.abspath(expanded))
    if not lexical.name or not lexical.parent.is_dir():
        raise ValueError("Release receipt output parent must already exist.")
    _reject_reparse_chain(lexical.parent)
    if os.path.lexists(lexical):
        raise ValueError("Release receipt output already exists.")
    parent = lexical.parent.resolve(strict=True)
    resolved = parent / lexical.name
    repository = ROOT.resolve(strict=True)
    if resolved == repository or repository in resolved.parents:
        raise ValueError("Release receipts must be written outside the repository.")
    return resolved


def _reject_reparse_chain(path: Path) -> None:
    selected = path
    while True:
        try:
            metadata = os.lstat(selected)
        except OSError as exc:
            raise ValueError("Release receipt output path is unavailable.") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if stat.S_ISLNK(metadata.st_mode) or attributes & reparse_flag:
            raise ValueError(
                "Release receipt output path cannot contain a reparse point."
            )
        parent = selected.parent
        if parent == selected:
            return
        selected = parent


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_bytes(*arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _workspace_state() -> dict[str, Any]:
    object_format = _git("rev-parse", "--show-object-format")
    prefix = "git-sha1:" if object_format == "sha1" else "git-sha256:"
    return {
        "commitDigest": prefix + _git("rev-parse", "HEAD^{commit}"),
        "treeDigest": prefix + _git("rev-parse", "HEAD^{tree}"),
        "clean": not bool(
            _git_bytes(
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            )
        ),
    }


def _candidate_paths() -> list[str]:
    raw = _git_bytes(
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    paths = [
        item.decode("utf-8", errors="strict").replace("\\", "/")
        for item in raw.split(b"\0")
        if item
    ]
    if paths != sorted(set(paths), key=lambda item: item.encode("utf-8")):
        paths = sorted(set(paths), key=lambda item: item.encode("utf-8"))
    return paths


def _tracked_modes() -> dict[str, str]:
    modes = {}
    for record in _git_bytes("ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        path = raw_path.decode("utf-8", errors="strict").replace("\\", "/")
        modes[path] = mode
    return modes


def _validate_workspace_snapshot(value: Any) -> None:
    fields = {
        "$schema",
        "kind",
        "schemaVersion",
        "commitDigest",
        "treeDigest",
        "clean",
        "entries",
        "snapshotDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Workspace snapshot has an invalid envelope.")
    if (
        value["$schema"]
        != "hocuspocus://schemas/internal-workspace-snapshot/v1"
        or value["kind"] != "hocus_internal_workspace_snapshot"
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or not isinstance(value["clean"], bool)
        or not isinstance(value["entries"], list)
        or not isinstance(value["commitDigest"], str)
        or _GIT_DIGEST.fullmatch(value["commitDigest"]) is None
        or not isinstance(value["treeDigest"], str)
        or _GIT_DIGEST.fullmatch(value["treeDigest"]) is None
        or value["commitDigest"].split(":", 1)[0]
        != value["treeDigest"].split(":", 1)[0]
    ):
        raise ValueError("Workspace snapshot identity is invalid.")
    previous = None
    for entry in value["entries"]:
        entry_fields = {
            "path",
            "kind",
            "gitMode",
            "byteLength",
            "contentDigest",
        }
        if (
            not isinstance(entry, dict)
            or set(entry) != entry_fields
            or not isinstance(entry["path"], str)
            or not entry["path"]
            or "\\" in entry["path"]
            or entry["kind"] not in {"file", "symlink", "missing"}
            or (
                entry["gitMode"] is not None
                and (
                    not isinstance(entry["gitMode"], str)
                    or re.fullmatch(r"[0-7]{6}", entry["gitMode"]) is None
                )
            )
            or type(entry["byteLength"]) is not int
            or entry["byteLength"] < 0
            or not isinstance(entry["contentDigest"], str)
            or _DIGEST.fullmatch(entry["contentDigest"]) is None
        ):
            raise ValueError("Workspace snapshot entry is invalid.")
        encoded = entry["path"].encode("utf-8")
        if previous is not None and encoded <= previous:
            raise ValueError("Workspace snapshot paths are not unique and sorted.")
        previous = encoded
    unsigned = {key: item for key, item in value.items() if key != "snapshotDigest"}
    if value["snapshotDigest"] != content_digest(canonical_json(unsigned)):
        raise ValueError("Workspace snapshot digest does not match its content.")
