"""Guarded native publication for deterministic text artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from os import PathLike, fspath
from pathlib import Path
from typing import Any


_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class NativeArtifactError(ValueError):
    """Typed failure from the native artifact publication boundary."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class NativeArtifactReceipt:
    """Portable receipt for one successfully published byte sequence."""

    content_digest: str
    byte_length: int
    replaced: bool

    def __post_init__(self) -> None:
        if (
            _DIGEST_PATTERN.fullmatch(self.content_digest) is None
            or type(self.byte_length) is not int
            or self.byte_length < 0
            or type(self.replaced) is not bool
        ):
            raise ValueError("Native artifact receipt is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contentDigest": self.content_digest,
            "byteLength": self.byte_length,
            "replaced": self.replaced,
        }


def publish_text_artifact(
    path: str | PathLike[str],
    text: str,
    *,
    expected_digest: str | None = None,
    max_bytes: int,
) -> NativeArtifactReceipt:
    """Exclusively create or exact-digest replace one UTF-8 text artifact.

    Content validation and receipt construction happen before filesystem access.
    Every fallible verification is complete before the atomic publication step.
    """

    if not isinstance(text, str):
        raise NativeArtifactError("HOCUS490", "Native artifact text must be a string.")
    if type(max_bytes) is not int or max_bytes < 1:
        raise NativeArtifactError("HOCUS490", "max_bytes must be a positive integer.")
    if expected_digest is not None and (
        not isinstance(expected_digest, str)
        or _DIGEST_PATTERN.fullmatch(expected_digest) is None
    ):
        raise NativeArtifactError(
            "HOCUS490", "expected_digest must be a lowercase sha256 digest."
        )
    try:
        content = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise NativeArtifactError("HOCUS490", "Native artifact text must be valid UTF-8.") from exc
    if len(content) > max_bytes:
        raise NativeArtifactError(
            "HOCUS490",
            "Native artifact exceeds its byte limit.",
            details={"byteLength": len(content), "maxBytes": max_bytes},
        )
    content_digest = _digest(content)
    receipt = NativeArtifactReceipt(content_digest, len(content), expected_digest is not None)

    try:
        raw_path = fspath(path)
        if not isinstance(raw_path, str) or not raw_path:
            raise TypeError
        destination = Path(raw_path).expanduser()
    except (TypeError, ValueError, OSError) as exc:
        raise NativeArtifactError("HOCUS490", "Native artifact path is invalid.") from exc

    original_mode: int | None = None
    if expected_digest is not None:
        actual = _read_digest(destination, missing_is_conflict=True)
        if actual != expected_digest:
            raise NativeArtifactError(
                "HOCUS491",
                "Existing artifact does not match expected_digest.",
                details={"expectedDigest": expected_digest, "actualDigest": actual},
            )
        try:
            original_mode = stat.S_IMODE(destination.stat().st_mode)
        except FileNotFoundError as exc:
            raise NativeArtifactError(
                "HOCUS491", "Artifact disappeared before replacement."
            ) from exc
        except OSError as exc:
            raise NativeArtifactError("HOCUS492", "Could not inspect existing artifact.") from exc

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
        )
    except OSError as exc:
        raise NativeArtifactError("HOCUS492", "Could not prepare native artifact publication.") from exc

    temporary = Path(temporary_name)
    published = False
    unowned_descriptor: int | None = descriptor
    try:
        try:
            opened = os.fdopen(descriptor, "wb")
            unowned_descriptor = None
            with opened as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if original_mode is not None:
                os.chmod(temporary, original_mode)
            if _read_digest(temporary, missing_is_conflict=False) != content_digest:
                raise NativeArtifactError(
                    "HOCUS492", "Temporary artifact failed its final content verification."
                )

            if expected_digest is None:
                try:
                    os.link(temporary, destination)
                except FileExistsError as exc:
                    raise NativeArtifactError(
                        "HOCUS491", "Destination already exists; exact replacement authority is required."
                    ) from exc
            else:
                actual = _read_digest(destination, missing_is_conflict=True)
                if actual != expected_digest:
                    raise NativeArtifactError(
                        "HOCUS491",
                        "Artifact changed immediately before replacement.",
                        details={"expectedDigest": expected_digest, "actualDigest": actual},
                    )
                os.replace(temporary, destination)
            published = True
        except NativeArtifactError:
            raise
        except OSError as exc:
            raise NativeArtifactError("HOCUS492", "Could not publish native artifact.") from exc
    finally:
        if unowned_descriptor is not None:
            try:
                os.close(unowned_descriptor)
            except OSError:
                pass
        # Publication is already final after link/replace. Cleanup is deliberately
        # best-effort so it cannot mask a primary failure or invalidate success.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    assert published
    return receipt


def _read_digest(path: Path, *, missing_is_conflict: bool) -> str:
    try:
        with path.open("rb") as handle:
            digest = hashlib.sha256()
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return "sha256:" + digest.hexdigest()
    except FileNotFoundError as exc:
        code = "HOCUS491" if missing_is_conflict else "HOCUS492"
        message = (
            "Replacement requires an existing artifact."
            if missing_is_conflict else "Temporary artifact disappeared before publication."
        )
        raise NativeArtifactError(code, message) from exc
    except OSError as exc:
        raise NativeArtifactError("HOCUS492", "Could not read native artifact bytes.") from exc


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()
