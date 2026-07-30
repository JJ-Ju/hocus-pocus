"""Private exact-version bundle admission for future document consumers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .bundle import (
    MODULE_BUNDLE_VERSION,
    BundleValidationError,
    CompiledBundle,
    decode_compiled_bundle,
)
from .contracts import (
    CONTROL_BUNDLE_VERSION,
    VALUE_BUNDLE_VERSION,
    CarrierContractError,
    decode_control_bundle_envelope,
    decode_value_bundle_envelope,
)

_AUTHENTICATED_CARRIER_HINT = "authenticated_carrier_hint"
_DOCUMENT_BUNDLE_VERSIONS = {
    MODULE_BUNDLE_VERSION, CONTROL_BUNDLE_VERSION, VALUE_BUNDLE_VERSION,
}


class _DocumentBundleBoundaryError(ValueError):
    """Typed private rejection before a carrier reaches document lowering."""

    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class _DecodedDocumentBundle:
    """Detached authenticated carrier content, not source-byte attestation.

    Source URIs and positions have carrier integrity and declared-source
    containment, but portable bundles contain no source bytes with which to
    verify interior line, column, or offset relationships.
    """

    version: str
    digest: str
    _payload_json: str
    source_location_classification: str = _AUTHENTICATED_CARRIER_HINT

    def __post_init__(self) -> None:
        """Reject direct construction unless every stored field re-authenticates."""

        if self.source_location_classification != _AUTHENTICATED_CARRIER_HINT:
            raise ValueError("Decoded document bundle classification is invalid.")
        try:
            payload = json.loads(self._payload_json)
            if (
                not isinstance(payload, dict)
                or payload.get("bundleVersion") != self.version
                or self.version not in _DOCUMENT_BUNDLE_VERSIONS
            ):
                raise ValueError("Decoded document bundle version is invalid.")
            candidate = {**payload, "bundleDigest": self.digest}
            if self.version == MODULE_BUNDLE_VERSION:
                authenticated = decode_compiled_bundle(candidate).to_dict()
            elif self.version == CONTROL_BUNDLE_VERSION:
                authenticated = decode_control_bundle_envelope(candidate)
            else:
                authenticated = decode_value_bundle_envelope(candidate)
            unsigned = dict(authenticated)
            declared_digest = unsigned.pop("bundleDigest")
            canonical = json.dumps(
                unsigned,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        except (BundleValidationError, CarrierContractError, TypeError, ValueError) as exc:
            raise ValueError("Decoded document bundle content is unauthenticated.") from exc
        if declared_digest != self.digest or canonical != self._payload_json:
            raise ValueError("Decoded document bundle content is noncanonical.")

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self._payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "bundleDigest": self.digest}


def _decode_document_bundle_content(value: Any) -> _DecodedDocumentBundle:
    """Authenticate exact Bundle 0.3/0.4 content without enabling lowering."""

    candidate = value.to_dict() if type(value) is CompiledBundle else value
    if not isinstance(candidate, Mapping):
        _fail_boundary(None, "Document bundle content must be a JSON object.")
    version = candidate.get("bundleVersion")
    if type(version) is not str or version not in _DOCUMENT_BUNDLE_VERSIONS:
        _fail_boundary(
            version,
            "Document bundle content requires exact Bundle 0.3 or Bundle 0.4.",
        )
    try:
        if version == MODULE_BUNDLE_VERSION:
            decoded = decode_compiled_bundle(dict(candidate))
            authenticated = decoded.to_dict()
        elif version == CONTROL_BUNDLE_VERSION:
            authenticated = decode_control_bundle_envelope(candidate)
        else:
            authenticated = decode_value_bundle_envelope(candidate)
    except (BundleValidationError, CarrierContractError) as exc:
        _fail_boundary(
            version,
            "Document bundle content failed its exact-version carrier contract.",
            cause=exc,
        )
    digest = authenticated["bundleDigest"]
    payload = dict(authenticated)
    del payload["bundleDigest"]
    return _DecodedDocumentBundle(
        version,
        digest,
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ),
    )


def _fail_boundary(
    version: Any,
    message: str,
    *,
    cause: BundleValidationError | CarrierContractError | None = None,
) -> None:
    details = {"bundleVersion": version}
    if cause is not None:
        details["causeCode"] = cause.code
    error = _DocumentBundleBoundaryError("HOCUS700", message, details=details)
    if cause is None:
        raise error
    raise error from cause
