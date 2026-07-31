"""Focused assertions for the external HS8 release-authority boundary."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hocuspocus.hocusscript.release_authority import (
    CLEAN_IMAGE_SCHEMA,
    CLEAN_BINDING_FIELDS,
    FINAL_DECISION_SCHEMA,
    FINAL_BINDING_FIELDS,
    TRUST_POLICY_SCHEMA,
    VISUAL_APPROVAL_SCHEMA,
    ReleaseAuthorityError,
    canonical_json_bytes,
    policy_digest,
    signature_message,
    signed_artifact_digest,
    verify_clean_image_attestation,
    verify_final_release_decision,
    verify_visual_approval,
)
from hocuspocus.hocusscript.release_candidate import (
    create_release_candidate_manifest,
)
from hocuspocus.hocusscript.release_evidence import create_rc1_evidence_set


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "docs" / "schemas"
CLI = ROOT / "scripts" / "verify_hocusscript_hs8_release_authority.py"
NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)


def assert_hs8_external_release_authority(testcase: Any) -> None:
    """Exercise schemas, strict bindings, signature trust, and the offline CLI."""

    with testcase.subTest("strict versioned schemas"):
        _assert_schemas(testcase)
    clean_key = Ed25519PrivateKey.generate()
    visual_key = Ed25519PrivateKey.generate()
    release_key = Ed25519PrivateKey.generate()
    policy = _policy(clean_key, visual_key, release_key)
    request = _review_request()
    evidence = _review_evidence(request)
    candidate = _release_candidate_context(request)
    approval = _visual_approval(policy, request, evidence, visual_key)
    final_bindings = _final_bindings(approval, candidate["manifest"])
    clean_bindings = _clean_bindings(final_bindings)
    clean = _clean_attestation(policy, clean_bindings, clean_key)
    decision = _final_decision(policy, final_bindings, clean, release_key)
    with testcase.subTest("schema instances"):
        _assert_schema_instances(policy, clean, approval, decision)
    with testcase.subTest("independent external roles authorize exact candidate"):
        clean_result = verify_clean_image_attestation(
            clean, policy, clean_bindings, now=NOW,
        )
        testcase.assertTrue(clean_result["cleanImageCertified"])
        testcase.assertFalse(clean_result["releaseAuthorized"])
        release_result = verify_final_release_decision(
            clean,
            approval,
            decision,
            policy,
            final_bindings,
            expected_review_request=request,
            expected_review_evidence=evidence,
            **_candidate_kwargs(candidate),
            expected_release_channel="v1-production",
            now=NOW,
        )
        testcase.assertTrue(release_result["releaseAuthorized"])
        testcase.assertEqual(
            release_result["cleanImageAttestationDigest"],
            signed_artifact_digest(clean),
        )
        testcase.assertNotIn(
            "visualApprovalDigest",
            clean["payload"]["bindings"],
        )
    _assert_visual_authority_boundaries(
        testcase, clean, approval, decision, policy, request, evidence,
        final_bindings, candidate, clean_key, visual_key,
    )
    _assert_all_bindings_are_exact(
        testcase, clean, approval, decision, policy, request, evidence,
        clean_bindings, final_bindings, candidate,
    )
    _assert_self_digests_are_not_authority(
        testcase, clean, approval, decision, policy, request, evidence,
        clean_bindings, final_bindings, candidate,
    )
    _assert_final_cross_bindings(
        testcase, clean, approval, decision, policy, request, evidence,
        final_bindings, candidate,
    )
    with testcase.subTest("offline CLI"):
        _assert_cli(
            testcase,
            policy, request, evidence, candidate,
        )


def _assert_schemas(testcase: Any) -> None:
    import jsonschema

    artifacts = (
        ("hs8-release-trust-policy-v1.schema.json", TRUST_POLICY_SCHEMA),
        (
            "hs8-external-clean-image-attestation-v1.schema.json",
            CLEAN_IMAGE_SCHEMA,
        ),
        ("hs8-final-release-decision-v1.schema.json", FINAL_DECISION_SCHEMA),
        ("hs8-signed-visual-approval-v1.schema.json", VISUAL_APPROVAL_SCHEMA),
    )
    for filename, schema_id in artifacts:
        schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        testcase.assertEqual(schema["$id"], schema_id)
        testcase.assertFalse(schema["additionalProperties"])
    testcase.assertLessEqual(
        len(
            (
                ROOT
                / "python3.11libs"
                / "hocuspocus"
                / "hocusscript"
                / "release_authority.py"
            ).read_text(encoding="utf-8").splitlines()
        ),
        1200,
    )


def _assert_schema_instances(
    policy: dict[str, Any],
    clean: dict[str, Any],
    approval: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    import jsonschema

    for filename, payload in (
        ("hs8-release-trust-policy-v1.schema.json", policy),
        ("hs8-external-clean-image-attestation-v1.schema.json", clean),
        ("hs8-signed-visual-approval-v1.schema.json", approval),
        ("hs8-final-release-decision-v1.schema.json", decision),
    ):
        schema = json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)


def _assert_all_bindings_are_exact(
    testcase: Any,
    clean: dict[str, Any],
    approval: dict[str, Any],
    decision: dict[str, Any],
    policy: dict[str, Any],
    request: dict[str, Any],
    evidence: dict[str, Any],
    clean_bindings: dict[str, str],
    final_bindings: dict[str, str],
    candidate: dict[str, Any],
) -> None:
    for field in CLEAN_BINDING_FIELDS:
        with testcase.subTest(clean_binding=field):
            expected = dict(clean_bindings)
            expected[field] = _digest(f"other-{field}".encode("ascii"))
            with testcase.assertRaises(ReleaseAuthorityError):
                verify_clean_image_attestation(
                    clean, policy, expected, now=NOW,
                )
    for field in FINAL_BINDING_FIELDS:
        with testcase.subTest(final_binding=field):
            expected = dict(final_bindings)
            expected[field] = _digest(f"other-{field}".encode("ascii"))
            with testcase.assertRaises(ReleaseAuthorityError):
                verify_final_release_decision(
                    clean,
                    approval,
                    decision,
                    policy,
                    expected,
                    expected_review_request=request,
                    expected_review_evidence=evidence,
                    **_candidate_kwargs(candidate),
                    expected_release_channel="v1-production",
                    now=NOW,
                )


def _assert_visual_authority_boundaries(
    testcase: Any,
    clean: dict[str, Any],
    approval: dict[str, Any],
    decision: dict[str, Any],
    policy: dict[str, Any],
    request: dict[str, Any],
    evidence: dict[str, Any],
    final_bindings: dict[str, str],
    candidate: dict[str, Any],
    clean_key: Ed25519PrivateKey,
    visual_key: Ed25519PrivateKey,
) -> None:
    result = verify_visual_approval(
        approval, policy, request, evidence, now=NOW,
    )
    testcase.assertTrue(result["visualApproved"])
    with testcase.subTest("duplicate public material across roles"):
        duplicated = copy.deepcopy(policy)
        duplicated["roles"]["visualReviewer"]["keys"][0]["publicKey"] = (
            duplicated["roles"]["cleanImageAttestor"]["keys"][0]["publicKey"]
        )
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                approval, duplicated, request, evidence, now=NOW,
            )
    with testcase.subTest("duplicate public material within threshold"):
        duplicated = copy.deepcopy(policy)
        first = duplicated["roles"]["visualReviewer"]["keys"][0]
        second = dict(first)
        second["keyId"] = "visual-reviewer-2027"
        second["principalId"] = "hocus-principal://release-reviewer-two"
        duplicated["roles"]["visualReviewer"] = {
            "minimumSignatures": 2,
            "keys": [first, second],
        }
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                approval, duplicated, request, evidence, now=NOW,
            )
    with testcase.subTest("boolean carrier version"):
        malformed = copy.deepcopy(approval)
        malformed["schemaVersion"] = True
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                malformed, policy, request, evidence, now=NOW,
            )
    with testcase.subTest("request and evidence substitution"):
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                approval, policy, {}, evidence, now=NOW,
            )
        other_request = dict(request)
        other_request["baselineDigest"] = _digest(b"other-baseline")
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                approval, policy, other_request, evidence, now=NOW,
            )
        other_evidence = dict(evidence)
        other_evidence["notesDigest"] = _digest(b"other-notes")
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                approval, policy, request, other_evidence, now=NOW,
            )
        cross_evidence = dict(evidence)
        cross_evidence["candidateOutputSetDigest"] = _digest(b"other-output")
        cross_approval = _visual_approval(
            policy, request, cross_evidence, visual_key,
        )
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_visual_approval(
                cross_approval, policy, request, cross_evidence, now=NOW,
            )
    with testcase.subTest("key must be active at artifact issuance"):
        future_policy = copy.deepcopy(policy)
        future_policy["roles"]["visualReviewer"]["keys"][0]["notBefore"] = (
            "2026-07-29T11:20:00Z"
        )
        pre_activation = _visual_approval(
            future_policy, request, evidence, visual_key,
        )
        with testcase.assertRaisesRegex(
            ReleaseAuthorityError,
            "not trusted at artifact issuance",
        ):
            verify_visual_approval(
                pre_activation, future_policy, request, evidence, now=NOW,
            )
    with testcase.subTest("approval substitution and chronology"):
        other_approval = copy.deepcopy(approval)
        other_approval["payload"]["expiresAt"] = "2026-07-30T12:00:00Z"
        other_approval["signatures"] = [
            _signature("visual-reviewer-2026", visual_key, other_approval)
        ]
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_final_release_decision(
                clean, other_approval, decision, policy, final_bindings,
                expected_review_request=request,
                expected_review_evidence=evidence,
                **_candidate_kwargs(candidate),
                expected_release_channel="v1-production",
                now=NOW,
            )
        late_clean = copy.deepcopy(clean)
        late_clean["payload"]["issuedAt"] = "2026-07-29T11:20:00Z"
        late_clean["signatures"] = [
            _signature("ci-clean-2026", clean_key, late_clean)
        ]
        late_decision = _final_decision(
            policy,
            final_bindings,
            late_clean,
            _release_private_key(decision),
        )
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_final_release_decision(
                late_clean, approval, late_decision, policy, final_bindings,
                expected_review_request=request,
                expected_review_evidence=evidence,
                **_candidate_kwargs(candidate),
                expected_release_channel="v1-production",
                now=NOW,
            )


def _assert_self_digests_are_not_authority(
    testcase: Any,
    clean: dict[str, Any],
    approval: dict[str, Any],
    decision: dict[str, Any],
    policy: dict[str, Any],
    request: dict[str, Any],
    evidence: dict[str, Any],
    clean_bindings: dict[str, str],
    final_bindings: dict[str, str],
    candidate: dict[str, Any],
) -> None:
    with testcase.subTest("valid repository digests plus invalid signature"):
        forged = copy.deepcopy(clean)
        forged["signatures"][0]["signature"] = _b64(bytes(64))
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_clean_image_attestation(
                forged, policy, clean_bindings, now=NOW,
            )
    with testcase.subTest("extra and duplicate-shaped authority fields"):
        malformed = copy.deepcopy(decision)
        malformed["payload"]["receiptDigest"] = _digest(b"self")
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_final_release_decision(
                clean,
                approval,
                malformed,
                policy,
                final_bindings,
                expected_review_request=request,
                expected_review_evidence=evidence,
                **_candidate_kwargs(candidate),
                expected_release_channel="v1-production",
                now=NOW,
            )


def _assert_final_cross_bindings(
    testcase: Any,
    clean: dict[str, Any],
    approval: dict[str, Any],
    decision: dict[str, Any],
    policy: dict[str, Any],
    request: dict[str, Any],
    evidence: dict[str, Any],
    final_bindings: dict[str, str],
    candidate: dict[str, Any],
) -> None:
    for field in (
        "candidateDigest",
        "sourceSnapshotDigest",
        "dependencySetDigest",
        "installedPayloadManifestDigest",
        "runtimeDigest",
        "technicalQualificationReceiptDigest",
    ):
        with testcase.subTest(candidate_final_binding=field):
            other_bindings = dict(final_bindings)
            other_bindings[field] = _digest(
                f"parallel-{field}".encode("ascii")
            )
            other_clean = _clean_attestation(
                policy,
                _clean_bindings(other_bindings),
                _clean_private_key(),
            )
            other_decision = _final_decision(
                policy,
                other_bindings,
                other_clean,
                _release_private_key(decision),
            )
            with testcase.assertRaisesRegex(
                ReleaseAuthorityError,
                "differ from the verified release candidate",
            ):
                verify_final_release_decision(
                    other_clean,
                    approval,
                    other_decision,
                    policy,
                    other_bindings,
                    expected_review_request=request,
                    expected_review_evidence=evidence,
                    **_candidate_kwargs(candidate),
                    expected_release_channel="v1-production",
                    now=NOW,
                )
    with testcase.subTest("final decision binds exact signed attestation"):
        other_clean = copy.deepcopy(clean)
        other_clean["payload"]["expiresAt"] = "2026-07-30T12:00:00Z"
        other_clean["signatures"] = [
            _signature("ci-clean-2026", _clean_private_key(), other_clean)
        ]
        with testcase.assertRaises(ReleaseAuthorityError):
            verify_final_release_decision(
                other_clean,
                approval,
                decision,
                policy,
                final_bindings,
                expected_review_request=request,
                expected_review_evidence=evidence,
                **_candidate_kwargs(candidate),
                expected_release_channel="v1-production",
                now=NOW,
            )
    with testcase.subTest("visual request must belong to verified candidate"):
        other_request = dict(request)
        other_request["candidateOutputSetDigest"] = _digest(b"candidate-b-output")
        other_evidence = _review_evidence(other_request)
        other_approval = _visual_approval(
            policy,
            other_request,
            other_evidence,
            _RELEASE_KEYS["visual-reviewer-2026"],
        )
        other_bindings = dict(final_bindings)
        other_bindings["visualApprovalDigest"] = signed_artifact_digest(
            other_approval
        )
        other_decision = _final_decision(
            policy,
            other_bindings,
            clean,
            _release_private_key(decision),
        )
        with testcase.assertRaisesRegex(
            ReleaseAuthorityError,
            "not bound by the verified candidate",
        ):
            verify_final_release_decision(
                clean,
                other_approval,
                other_decision,
                policy,
                other_bindings,
                expected_review_request=other_request,
                expected_review_evidence=other_evidence,
                **_candidate_kwargs(candidate),
                expected_release_channel="v1-production",
                now=NOW,
            )
    with testcase.subTest("authentic rejection cannot authorize release"):
        release_key = _release_private_key(decision)
        rejected = _final_decision(
            policy,
            final_bindings,
            clean,
            release_key,
            decision_value="rejected",
        )
        result = verify_final_release_decision(
            clean,
            approval,
            rejected,
            policy,
            final_bindings,
            expected_review_request=request,
            expected_review_evidence=evidence,
            **_candidate_kwargs(candidate),
            expected_release_channel="v1-production",
            now=NOW,
        )
        testcase.assertTrue(result["verified"])
        testcase.assertFalse(result["releaseAuthorized"])


def _assert_cli(
    testcase: Any,
    policy: dict[str, Any],
    request: dict[str, Any],
    evidence: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    current = datetime.now(timezone.utc).replace(microsecond=0)
    cli_policy = copy.deepcopy(policy)
    for role in cli_policy["roles"].values():
        role["keys"][0]["notBefore"] = _timestamp(current - timedelta(days=1))
        role["keys"][0]["notAfter"] = _timestamp(current + timedelta(days=1))
    cli_approval = _visual_approval(
        cli_policy,
        request,
        evidence,
        _RELEASE_KEYS["visual-reviewer-2026"],
        issued_at=_timestamp(current - timedelta(minutes=2)),
        expires_at=_timestamp(current + timedelta(hours=1)),
    )
    cli_final_bindings = _final_bindings(
        cli_approval,
        candidate["manifest"],
    )
    cli_clean_bindings = _clean_bindings(cli_final_bindings)
    cli_clean = _clean_attestation(
        cli_policy,
        cli_clean_bindings,
        _RELEASE_KEYS["ci-clean-2026"],
        issued_at=_timestamp(current - timedelta(minutes=3)),
        expires_at=_timestamp(current + timedelta(hours=1)),
    )
    cli_decision = _final_decision(
        cli_policy,
        cli_final_bindings,
        cli_clean,
        _RELEASE_KEYS["release-board-2026"],
        issued_at=_timestamp(current - timedelta(minutes=1)),
        expires_at=_timestamp(current + timedelta(hours=1)),
    )
    with tempfile.TemporaryDirectory(prefix="hs8-release-authority-") as value:
        root = Path(value)
        paths = {}
        for name, payload in (
            ("clean", cli_clean),
            ("approval", cli_approval),
            ("decision", cli_decision),
            ("policy", cli_policy),
            ("review-request", request),
            ("review-evidence", evidence),
            ("clean-bindings", cli_clean_bindings),
            ("final-bindings", cli_final_bindings),
            ("candidate-manifest", candidate["manifest"]),
            ("candidate-inputs", candidate["inputs"]),
            ("rc1-evidence", candidate["rc1"]),
        ):
            path = root / f"{name}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths[name] = path
        clean_completed = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "clean-image",
                "--attestation",
                str(paths["clean"]),
                "--trust-policy",
                str(paths["policy"]),
                "--expected-clean-bindings",
                str(paths["clean-bindings"]),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        testcase.assertEqual(
            clean_completed.returncode,
            0,
            clean_completed.stderr,
        )
        testcase.assertTrue(
            json.loads(clean_completed.stdout)["cleanImageCertified"],
        )
        visual_completed = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "visual-approval",
                "--approval",
                str(paths["approval"]),
                "--trust-policy",
                str(paths["policy"]),
                "--expected-review-request",
                str(paths["review-request"]),
                "--expected-review-evidence",
                str(paths["review-evidence"]),
                "--release-candidate-manifest",
                str(paths["candidate-manifest"]),
                "--expected-candidate-inputs",
                str(paths["candidate-inputs"]),
                "--rc1-evidence-set",
                str(paths["rc1-evidence"]),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        testcase.assertEqual(
            visual_completed.returncode,
            0,
            visual_completed.stderr,
        )
        testcase.assertTrue(
            json.loads(visual_completed.stdout)["visualApproved"],
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "release",
                "--clean-image-attestation",
                str(paths["clean"]),
                "--final-decision",
                str(paths["decision"]),
                "--visual-approval",
                str(paths["approval"]),
                "--trust-policy",
                str(paths["policy"]),
                "--expected-final-bindings",
                str(paths["final-bindings"]),
                "--expected-review-request",
                str(paths["review-request"]),
                "--expected-review-evidence",
                str(paths["review-evidence"]),
                "--release-candidate-manifest",
                str(paths["candidate-manifest"]),
                "--expected-candidate-inputs",
                str(paths["candidate-inputs"]),
                "--rc1-evidence-set",
                str(paths["rc1-evidence"]),
                "--release-channel",
                "v1-production",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        testcase.assertEqual(completed.returncode, 0, completed.stderr)
        testcase.assertTrue(json.loads(completed.stdout)["releaseAuthorized"])
        replay = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "clean-image",
                "--attestation",
                str(paths["clean"]),
                "--trust-policy",
                str(paths["policy"]),
                "--expected-clean-bindings",
                str(paths["clean-bindings"]),
                "--now",
                "2026-07-29T12:00:00Z",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        testcase.assertEqual(replay.returncode, 2)
        testcase.assertIn("unrecognized arguments: --now", replay.stderr)


def _policy(
    clean_key: Ed25519PrivateKey,
    visual_key: Ed25519PrivateKey,
    release_key: Ed25519PrivateKey,
) -> dict[str, Any]:
    return {
        "$schema": TRUST_POLICY_SCHEMA,
        "kind": "hocus_hs8_release_trust_policy",
        "schemaVersion": 1,
        "policyId": "studio://release-policy/hs8-v1",
        "requireDistinctPrincipals": True,
        "roles": {
            "cleanImageAttestor": {
                "minimumSignatures": 1,
                "keys": [_key("ci-clean-2026", "ci://clean-image", clean_key)],
            },
            "releaseDecisionAuthority": {
                "minimumSignatures": 1,
                "keys": [
                    _key(
                        "release-board-2026",
                        "studio://release-board",
                        release_key,
                    )
                ],
            },
            "visualReviewer": {
                "minimumSignatures": 1,
                "keys": [
                    _key(
                        "visual-reviewer-2026",
                        "hocus-principal://release-reviewer",
                        visual_key,
                    )
                ],
            },
        },
    }


def _key(
    key_id: str,
    principal_id: str,
    private: Ed25519PrivateKey,
) -> dict[str, Any]:
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return {
        "keyId": key_id,
        "principalId": principal_id,
        "algorithm": "Ed25519",
        "publicKey": _b64(raw),
        "notBefore": "2026-01-01T00:00:00Z",
        "notAfter": "2027-01-01T00:00:00Z",
    }


def _final_bindings(
    approval: dict[str, Any],
    candidate_manifest: dict[str, Any],
) -> dict[str, str]:
    inputs = candidate_manifest["inputs"]
    result = {
        "candidateDigest": candidate_manifest["manifestDigest"],
        "sourceSnapshotDigest": inputs["source"]["sourceArchiveDigest"],
        "installedPayloadManifestDigest": inputs["installedCandidate"][
            "installManifestDigest"
        ],
        "runtimeDigest": inputs["installedCandidate"]["runtimeDigest"],
        "environmentReceiptDigest": _digest(b"environment-receipt"),
        "dependencySetDigest": inputs["execution"]["dependencySetDigest"],
        "technicalQualificationReceiptDigest": inputs["evidence"][
            "technicalQualificationReceiptDigest"
        ],
        "visualApprovalDigest": signed_artifact_digest(approval),
    }
    assert set(result) == set(FINAL_BINDING_FIELDS)
    return result


def _clean_bindings(final_bindings: dict[str, str]) -> dict[str, str]:
    return {
        field: final_bindings[field]
        for field in CLEAN_BINDING_FIELDS
    }


def _release_candidate_context(
    request: dict[str, Any],
) -> dict[str, Any]:
    rc1 = _rc1_evidence()
    inputs = {
        "source": {
            "commitDigest": rc1["candidate"]["commitDigest"],
            "treeDigest": rc1["candidate"]["treeDigest"],
            "sourceArchiveDigest": _digest(b"source-archive"),
        },
        "execution": {
            "runnerSetDigest": _digest(b"runners"),
            "dependencySetDigest": _digest(b"dependencies"),
        },
        "releaseAssets": {
            "fixtureSetDigest": _digest(b"fixtures"),
            "baselineSetDigest": _digest(b"baselines"),
            "reviewRequestDigest": _digest(canonical_json_bytes(request)),
            "schemaSetDigest": _digest(b"schemas"),
        },
        "installedCandidate": {
            "installManifestDigest": rc1["installedPayloadManifestDigest"],
            "activePointerDigest": _digest(b"active-pointer"),
            "runtimeDigest": rc1["runtimeDigest"],
        },
        "evidence": {
            "technicalQualificationReceiptDigest": _digest(b"technical"),
            "packageProvenanceReceiptDigest": rc1["receipts"][
                "packageSearch"
            ]["receiptDigest"],
            "rc1EvidenceDigest": rc1["evidenceSetDigest"],
        },
    }
    return {
        "manifest": create_release_candidate_manifest(inputs, rc1),
        "inputs": inputs,
        "rc1": rc1,
    }


def _candidate_kwargs(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "release_candidate_manifest": candidate["manifest"],
        "expected_candidate_inputs": candidate["inputs"],
        "rc1_evidence_set": candidate["rc1"],
    }


def _rc1_evidence() -> dict[str, Any]:
    common = {
        "performance": "hocus_performance_benchmark_receipt",
        "compatibility": "hocus_compatibility_matrix_receipt",
        "graphStore": "hocus_graph_store_upgrade_receipt",
    }
    receipts = {
        name: {
            "schema": "hocuspocus://schemas/internal-release-evidence/v1",
            "kind": kind,
            "receiptDigest": _digest(f"{name}-receipt".encode()),
            "fileDigest": _digest(f"{name}-file".encode()),
        }
        for name, kind in common.items()
    }
    receipts["packageSearch"] = {
        "schema": "hocuspocus://schemas/effective-package-search-provenance/v1",
        "kind": "hocus_effective_package_search_provenance",
        "receiptDigest": _digest(b"package-receipt"),
        "fileDigest": _digest(b"package-file"),
        "installedPayloadManifestDigest": _digest(b"install-manifest"),
        "runtimeDigest": _digest(b"runtime"),
    }
    return create_rc1_evidence_set(
        {
            "commitDigest": "git-sha1:" + "1" * 40,
            "treeDigest": "git-sha1:" + "2" * 40,
            "workspaceSnapshotDigest": _digest(b"workspace"),
            "fileCount": 1,
            "clean": True,
        },
        receipts,
    )


def _clean_attestation(
    policy: dict[str, Any],
    bindings: dict[str, str],
    private: Ed25519PrivateKey,
    *,
    issued_at: str = "2026-07-29T11:00:00Z",
    expires_at: str = "2026-07-30T11:00:00Z",
) -> dict[str, Any]:
    artifact = {
        "$schema": CLEAN_IMAGE_SCHEMA,
        "kind": "hocus_hs8_external_clean_image_attestation",
        "schemaVersion": 1,
        "payload": {
            "authorityRole": "clean_image_attestor",
            "canonicalization": "RFC8785",
            "trustPolicy": {
                "policyId": policy["policyId"],
                "policyDigest": policy_digest(policy),
            },
            "bindings": dict(bindings),
            "isolationBoundary": "clean_image_or_vm",
            "ephemeral": True,
            "result": "passed",
            "issuedAt": issued_at,
            "expiresAt": expires_at,
        },
        "signatures": [],
    }
    artifact["signatures"] = [
        _signature("ci-clean-2026", private, artifact)
    ]
    return artifact


def _review_request() -> dict[str, Any]:
    return {
        "$schema": "hocuspocus://schemas/visual-review-request/v1",
        "kind": "hocus_visual_version_review_request",
        "reviewVersion": 1,
        "assetUri": "hocus-asset://hs8.fixture/rock-family",
        "candidateProvenanceManifestDigest": _digest(b"provenance"),
        "candidateOutputSetDigest": _digest(b"outputs"),
        "visualComparisonDigest": _digest(b"comparison"),
        "candidateVersionId": "hs8-rock-family-v1",
        "reviewPolicyId": "hs8-installed-visual-review-v1",
        "baselineFile": "baseline-contact-sheet.png",
        "baselineDigest": _digest(b"baseline"),
        "decision": "review_pending",
    }


def _review_evidence(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "hocus_visual_version_review_evidence",
        "reviewVersion": 1,
        **{
            field: request[field]
            for field in (
                "assetUri",
                "candidateProvenanceManifestDigest",
                "candidateOutputSetDigest",
                "visualComparisonDigest",
                "candidateVersionId",
                "reviewPolicyId",
            )
        },
        "reviewerPrincipalId": "hocus-principal://release-reviewer",
        "decision": "approved",
        "notesDigest": None,
    }


def _visual_approval(
    policy: dict[str, Any],
    request: dict[str, Any],
    evidence: dict[str, Any],
    private: Ed25519PrivateKey,
    *,
    issued_at: str = "2026-07-29T11:15:00Z",
    expires_at: str = "2026-07-30T11:00:00Z",
) -> dict[str, Any]:
    artifact = {
        "$schema": VISUAL_APPROVAL_SCHEMA,
        "kind": "hocus_hs8_signed_visual_approval",
        "schemaVersion": 1,
        "payload": {
            "authorityRole": "visual_reviewer",
            "canonicalization": "RFC8785",
            "trustPolicy": {
                "policyId": policy["policyId"],
                "policyDigest": policy_digest(policy),
            },
            "reviewRequestDigest": _digest(
                json.dumps(
                    request, ensure_ascii=False, separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii")
            ),
            "reviewEvidenceDigest": _digest(
                json.dumps(
                    evidence, ensure_ascii=False, separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii")
            ),
            "reviewEvidence": dict(evidence),
            "issuedAt": issued_at,
            "expiresAt": expires_at,
        },
        "signatures": [],
    }
    artifact["signatures"] = [
        _signature("visual-reviewer-2026", private, artifact)
    ]
    return artifact


def _final_decision(
    policy: dict[str, Any],
    bindings: dict[str, str],
    clean: dict[str, Any],
    private: Ed25519PrivateKey,
    *,
    decision_value: str = "approved",
    issued_at: str = "2026-07-29T11:30:00Z",
    expires_at: str = "2026-07-30T11:00:00Z",
) -> dict[str, Any]:
    artifact = {
        "$schema": FINAL_DECISION_SCHEMA,
        "kind": "hocus_hs8_final_release_decision",
        "schemaVersion": 1,
        "payload": {
            "authorityRole": "release_decision_authority",
            "canonicalization": "RFC8785",
            "trustPolicy": {
                "policyId": policy["policyId"],
                "policyDigest": policy_digest(policy),
            },
            "bindings": dict(bindings),
            "cleanImageAttestationDigest": signed_artifact_digest(clean),
            "releaseChannel": "v1-production",
            "decision": decision_value,
            "issuedAt": issued_at,
            "expiresAt": expires_at,
        },
        "signatures": [],
    }
    artifact["signatures"] = [
        _signature("release-board-2026", private, artifact)
    ]
    return artifact


_RELEASE_KEYS: dict[str, Ed25519PrivateKey] = {}


def _signature(
    key_id: str,
    private: Ed25519PrivateKey,
    artifact: dict[str, Any],
) -> dict[str, str]:
    _RELEASE_KEYS[key_id] = private
    return {
        "keyId": key_id,
        "algorithm": "Ed25519",
        "signature": _b64(private.sign(signature_message(artifact))),
    }


def _release_private_key(_decision: dict[str, Any]) -> Ed25519PrivateKey:
    return _RELEASE_KEYS["release-board-2026"]


def _clean_private_key() -> Ed25519PrivateKey:
    return _RELEASE_KEYS["ci-clean-2026"]


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


__all__ = ["assert_hs8_external_release_authority"]
