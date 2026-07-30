"""Pure, content-addressed HS8 build provenance contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable, Mapping


BUILD_PROVENANCE_SCHEMA = "hocuspocus://schemas/build-provenance-manifest/v1"
MAX_BUILD_COMPONENTS = 4096
MAX_BUILD_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_COMPONENT_BYTES = 1 << 40

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLATFORM = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PORTABLE_URI = re.compile(
    r"^hocus-(?:asset|catalog|compiler|hda|input|module|output|project|recipe)"
    r"://[a-z0-9][a-z0-9.-]{0,127}/"
    r"(?!/)(?!\.{1,2}(?:/|$))(?!.*?/\.{1,2}(?:/|$))"
    r"(?!.*//)(?!.*[?#\\:])[^/]+(?:/[^/]+)*$"
)
_KINDS = frozenset(
    {"recipe", "source", "compiler", "catalog", "module", "hda", "input", "output"}
)


class BuildProvenanceError(ValueError):
    """Typed failure at the pure HS8 provenance boundary."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class BuildComponent:
    """One portable identity record derived from caller-supplied content."""

    kind: str
    uri: str
    content_digest: str
    byte_length: int
    version: str | None = None
    fingerprint: str | None = None
    role: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        _validate_component(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "uri": self.uri,
            "contentDigest": self.content_digest,
            "byteLength": self.byte_length,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "role": self.role,
            "mediaType": self.media_type,
        }

    @classmethod
    def from_dict(cls, value: Any) -> BuildComponent:
        if not isinstance(value, dict) or set(value) != {
            "kind", "uri", "contentDigest", "byteLength", "version",
            "fingerprint", "role", "mediaType",
        }:
            raise _invalid("Build component has an invalid envelope.")
        return cls(
            kind=value["kind"],
            uri=value["uri"],
            content_digest=value["contentDigest"],
            byte_length=value["byteLength"],
            version=value["version"],
            fingerprint=value["fingerprint"],
            role=value["role"],
            media_type=value["mediaType"],
        )


@dataclass(frozen=True, slots=True)
class BuildProvenanceManifest:
    """Canonical identity of all deterministic build inputs and outputs."""

    _payload_json: str
    manifest_digest: str

    @property
    def build_identity(self) -> str:
        return self.to_dict()["buildIdentity"]

    @property
    def output_set_digest(self) -> str:
        return self.to_dict()["outputSetDigest"]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(json.loads(self._payload_json))

    def to_json(self, *, pretty: bool = False) -> str:
        if not pretty:
            return self._payload_json
        return json.dumps(
            self.to_dict(), ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True,
        ) + "\n"

    @classmethod
    def from_dict(cls, value: Any) -> BuildProvenanceManifest:
        payload = _normalize_manifest(value)
        return cls(_canonical_json(payload), payload["manifestDigest"])


def component_from_content(
    kind: str,
    uri: str,
    content: bytes,
    *,
    version: str | None = None,
    fingerprint: str | None = None,
    role: str | None = None,
    media_type: str | None = None,
) -> BuildComponent:
    """Create provenance from explicit bytes without consulting host state."""

    if not isinstance(content, bytes):
        raise _invalid("Build component content must be bytes.")
    if len(content) > MAX_COMPONENT_BYTES:
        raise BuildProvenanceError(
            "HOCUS981",
            "Build component exceeds its content byte limit.",
            details={"byteLength": len(content), "maxBytes": MAX_COMPONENT_BYTES},
        )
    return BuildComponent(
        kind=kind,
        uri=uri,
        content_digest=_digest_bytes(content),
        byte_length=len(content),
        version=version,
        fingerprint=fingerprint,
        role=role,
        media_type=media_type,
    )


def _components_from_measured_dependencies(
    *,
    dependencies: Iterable[Mapping[str, Any]],
    measurements: Iterable[Mapping[str, Any]],
    uri_authority: str,
) -> tuple[tuple[BuildComponent, ...], tuple[BuildComponent, ...]]:
    """Bind declared dependencies to caller-supplied authenticated measurements."""

    declared = tuple(islice(iter(dependencies), MAX_BUILD_COMPONENTS + 1))
    observed = tuple(islice(iter(measurements), MAX_BUILD_COMPONENTS + 1))
    if len(declared) > MAX_BUILD_COMPONENTS or len(observed) > MAX_BUILD_COMPONENTS:
        raise BuildProvenanceError(
            "HOCUS981", "Build dependency evidence exceeds its item limit."
        )
    if (
        not isinstance(uri_authority, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,127}", uri_authority) is None
    ):
        raise _invalid("Build dependency URI authority is invalid.")

    evidence: dict[tuple[str, str], tuple[str, str, int]] = {}
    for item in observed:
        kind, item_id, version, digest = _dependency_identity(item)
        byte_length = item.get("byteLength")
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or not 0 <= byte_length <= MAX_COMPONENT_BYTES
        ):
            raise _invalid("Build dependency byteLength is invalid.")
        key = (kind, item_id)
        receipt = (version, digest, byte_length)
        previous = evidence.get(key)
        if previous is not None and previous != receipt:
            raise _invalid("Build dependency measurements conflict.")
        evidence[key] = receipt

    seen: set[tuple[str, str]] = set()
    hdas: list[BuildComponent] = []
    inputs: list[BuildComponent] = []
    for index, item in enumerate(declared):
        kind, item_id, version, digest = _dependency_identity(item)
        key = (kind, item_id)
        if key in seen:
            raise _invalid("Build dependencies contain a duplicate identity.")
        seen.add(key)
        receipt = evidence.get(key)
        if receipt is None:
            raise _invalid("Build dependency measurement is missing.")
        measured_version, measured_digest, byte_length = receipt
        if (version, digest) != (measured_version, measured_digest):
            raise _invalid("Build dependency measurement does not match its declaration.")
        component_kind = "hda" if kind == "hda" else "input"
        component = BuildComponent(
            kind=component_kind,
            uri=(
                f"hocus-{component_kind}://{uri_authority}/"
                f"dependency-{index}"
            ),
            content_digest=digest,
            byte_length=byte_length,
            version=version,
        )
        (hdas if component_kind == "hda" else inputs).append(component)
    if set(evidence) != seen:
        raise _invalid("Build dependency measurements contain undeclared evidence.")
    return tuple(hdas), tuple(inputs)


def _dependency_identity(item: Mapping[str, Any]) -> tuple[str, str, str, str]:
    if not isinstance(item, Mapping):
        raise _invalid("Build dependency evidence must be an object.")
    values = tuple(item.get(key) for key in ("kind", "id", "version", "digest"))
    if any(not isinstance(value, str) or not value for value in values):
        raise _invalid("Build dependency identity is invalid.")
    kind, item_id, version, digest = values
    return kind, item_id, version, digest


def create_build_provenance(
    *,
    asset_uri: str,
    target_platform: str,
    recipe: BuildComponent,
    sources: Iterable[BuildComponent],
    compiler: BuildComponent,
    catalog: BuildComponent,
    modules: Iterable[BuildComponent] = (),
    hdas: Iterable[BuildComponent] = (),
    inputs: Iterable[BuildComponent] = (),
    outputs: Iterable[BuildComponent] = (),
) -> BuildProvenanceManifest:
    """Seal deterministic input identity and output identity in one manifest."""

    if not _valid_uri(asset_uri, "asset"):
        raise _invalid("asset_uri must be a canonical hocus-asset URI.")
    if not isinstance(target_platform, str) or _PLATFORM.fullmatch(target_platform) is None:
        raise _invalid("target_platform is invalid.")
    groups = {
        "sources": _component_group(sources, "source", required=True),
        "modules": _component_group(modules, "module"),
        "hdas": _component_group(hdas, "hda"),
        "inputs": _component_group(inputs, "input"),
        "outputs": _component_group(outputs, "output"),
    }
    _require_kind(recipe, "recipe")
    _require_kind(compiler, "compiler")
    _require_kind(catalog, "catalog")
    identity = {
        "assetUri": asset_uri,
        "targetPlatform": target_platform,
        "recipe": recipe.to_dict(),
        "sources": groups["sources"],
        "compiler": compiler.to_dict(),
        "catalog": catalog.to_dict(),
        "modules": groups["modules"],
        "hdas": groups["hdas"],
        "inputs": groups["inputs"],
    }
    payload = {
        "$schema": BUILD_PROVENANCE_SCHEMA,
        "kind": "hocus_build_provenance",
        "schemaVersion": 1,
        **identity,
        "outputs": groups["outputs"],
        "buildIdentity": canonical_digest(identity),
        "outputSetDigest": canonical_digest({"outputs": groups["outputs"]}),
    }
    payload["manifestDigest"] = canonical_digest(payload)
    encoded = _canonical_json(payload)
    if len(encoded.encode("utf-8")) > MAX_BUILD_MANIFEST_BYTES:
        raise BuildProvenanceError("HOCUS981", "Build provenance manifest is too large.")
    return BuildProvenanceManifest(encoded, payload["manifestDigest"])


def canonical_digest(value: Any) -> str:
    """Digest one JSON value under the shared strict canonical encoding."""

    return _digest_bytes(_canonical_json(value).encode("utf-8"))


def _normalize_manifest(value: Any) -> dict[str, Any]:
    fields = {
        "$schema", "kind", "schemaVersion", "assetUri", "targetPlatform", "recipe",
        "sources", "compiler", "catalog", "modules", "hdas", "inputs", "outputs",
        "buildIdentity", "outputSetDigest", "manifestDigest",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise _invalid("Build provenance manifest has an invalid envelope.")
    if (
        value["$schema"] != BUILD_PROVENANCE_SCHEMA
        or value["kind"] != "hocus_build_provenance"
        or value["schemaVersion"] != 1
    ):
        raise _invalid("Build provenance manifest version is unsupported.")
    rebuilt = create_build_provenance(
        asset_uri=value["assetUri"],
        target_platform=value["targetPlatform"],
        recipe=BuildComponent.from_dict(value["recipe"]),
        sources=_decode_group(value["sources"]),
        compiler=BuildComponent.from_dict(value["compiler"]),
        catalog=BuildComponent.from_dict(value["catalog"]),
        modules=_decode_group(value["modules"]),
        hdas=_decode_group(value["hdas"]),
        inputs=_decode_group(value["inputs"]),
        outputs=_decode_group(value["outputs"]),
    )
    expected = rebuilt.to_dict()
    for field in ("buildIdentity", "outputSetDigest", "manifestDigest"):
        if value[field] != expected[field]:
            raise BuildProvenanceError(
                "HOCUS982",
                f"Build provenance {field} does not match its canonical content.",
                details={"expected": expected[field], "actual": value[field]},
            )
    normalized = copy.deepcopy(value)
    if len(_canonical_json(normalized).encode("utf-8")) > MAX_BUILD_MANIFEST_BYTES:
        raise BuildProvenanceError("HOCUS981", "Build provenance manifest is too large.")
    return normalized


def _component_group(
    values: Iterable[BuildComponent], kind: str, *, required: bool = False,
) -> list[dict[str, Any]]:
    try:
        items = tuple(islice(iter(values), MAX_BUILD_COMPONENTS + 1))
    except TypeError as exc:
        raise _invalid(f"{kind} components must be iterable.") from exc
    if (required and not items) or len(items) > MAX_BUILD_COMPONENTS:
        raise BuildProvenanceError(
            "HOCUS981", f"{kind} component count is outside its bounded range."
        )
    for item in items:
        _require_kind(item, kind)
    ordered = sorted(items, key=lambda item: item.uri)
    if len({item.uri for item in ordered}) != len(ordered):
        raise _invalid(f"{kind} component URIs must be unique.")
    return [item.to_dict() for item in ordered]


def _decode_group(value: Any) -> tuple[BuildComponent, ...]:
    if not isinstance(value, list):
        raise _invalid("Build component group must be an array.")
    if len(value) > MAX_BUILD_COMPONENTS:
        raise BuildProvenanceError(
            "HOCUS981", "Build component group exceeds its item limit."
        )
    return tuple(BuildComponent.from_dict(item) for item in value)


def _require_kind(value: Any, kind: str) -> None:
    if not isinstance(value, BuildComponent) or value.kind != kind:
        raise _invalid(f"Expected one {kind} build component.")


def _validate_component(value: BuildComponent) -> None:
    if value.kind not in _KINDS or not _valid_uri(value.uri, value.kind):
        raise _invalid("Build component kind or URI is invalid.")
    if (
        not isinstance(value.content_digest, str)
        or _DIGEST.fullmatch(value.content_digest) is None
        or type(value.byte_length) is not int
        or not 0 <= value.byte_length <= MAX_COMPONENT_BYTES
    ):
        raise _invalid("Build component content identity is invalid.")
    for field in ("version", "fingerprint", "role", "media_type"):
        text = getattr(value, field)
        if text is not None and (
            not isinstance(text, str) or not text or len(text.encode("utf-8")) > 1024
        ):
            raise _invalid(f"Build component {field} is invalid.")
    if value.kind == "compiler" and value.version is None:
        raise _invalid("Compiler provenance requires a version.")
    if value.kind == "catalog" and value.fingerprint is None:
        raise _invalid("Catalog provenance requires a fingerprint.")
    if value.kind == "output" and (value.role is None or value.media_type is None):
        raise _invalid("Output provenance requires role and media_type.")
    if value.kind != "output" and (value.role is not None or value.media_type is not None):
        raise _invalid("Only output provenance may declare role or media_type.")


def _valid_uri(value: Any, kind: str) -> bool:
    uri_kind = "project" if kind == "source" else kind
    return (
        isinstance(value, str)
        and len(value.encode("utf-8")) <= 8192
        and _PORTABLE_URI.fullmatch(value) is not None
        and value.startswith(f"hocus-{uri_kind}://")
    )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid("Build payload must be finite JSON data.") from exc


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _invalid(message: str) -> BuildProvenanceError:
    return BuildProvenanceError("HOCUS980", message)


__all__ = [
    "BUILD_PROVENANCE_SCHEMA",
    "BuildComponent",
    "BuildProvenanceError",
    "BuildProvenanceManifest",
    "canonical_digest",
    "component_from_content",
    "create_build_provenance",
]
