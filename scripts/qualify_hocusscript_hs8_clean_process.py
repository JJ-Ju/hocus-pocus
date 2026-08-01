"""Run installed HS8 acceptance twice in isolated same-host Houdini processes.

This is a same-host clean-process gate, not clean-machine proof. It launches
only installed harness/support/fixture bytes after matching them to source,
does not import repository HocusPocus modules, and does not compare timings.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping
SCHEMA = "hocuspocus://schemas/hs8-clean-process-qualification/v1"
MAX_STDOUT_BYTES = 32 * 1024 * 1024
MAX_STDERR_BYTES = 8 * 1024 * 1024
MAX_RETAINED_STREAM_BYTES = 1024 * 1024
MAX_RETAINED_EVIDENCE_BYTES = 5 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 3600.0
QUALIFICATION_MODES = frozenset({"technical", "release"})
EXPECTED_OUTPUT_URIS = frozenset({
    "hocus-output://hs8.fixture/contact-sheet.png",
    "hocus-output://hs8.fixture/numeric-report.json",
    "hocus-output://hs8.fixture/rock-family.usda",
})
IDENTITY_CATEGORIES = ("recipe", "source", "compiler", "catalog", "module",
                       "hda", "input", "package_search")
INHERITED_ENVIRONMENT = (
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMSPEC", "HFS",
    "HOUDINI_LICENSE_SERVER", "HOUDINI_LMHOST", "LANG", "LC_ALL",
    "LD_LIBRARY_PATH", "LM_LICENSE_FILE", "PATH", "PATHEXT",
    "PROCESSOR_ARCHITECTURE", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "SESI_LMHOST", "SSL_CERT_DIR", "SSL_CERT_FILE",
    "SYSTEMDRIVE", "SYSTEMROOT", "TZ", "WINDIR",
)
PACKAGING_CHECK_IDS = (
    "contract", "artistOverrides", "provenance", "outputs", "budget",
    "deterministic", "numeric",
)
PUBLISH_CHECK_IDS = PACKAGING_CHECK_IDS + ("visual", "visualVersionReview")

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PORTABLE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_REVIEWER_ID = re.compile(
    r"^(?:hocus-principal://[a-z0-9][a-z0-9._-]{0,127}|"
    r"hprincipal_[0-9a-f]{32}|"
    r"sha256:[0-9a-f]{64})$"
)
_VERSIONED_INSTALL = re.compile(r"^HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}$")
_PORTABLE_URI = re.compile(
    r"^hocus-(?:asset|output)://[a-z0-9][a-z0-9.-]{0,127}/"
    r"(?!/)(?!\.{1,2}(?:/|$))(?!.*?/\.{1,2}(?:/|$))"
    r"(?!.*//)(?!.*[?#\\:])[^/]+(?:/[^/]+)*$"
)
class CleanProcessQualificationError(RuntimeError):
    """Fail-closed orchestration or receipt-validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
def qualify_two_clean_processes(
    *,
    hython: Path,
    installed_root: Path,
    harness: Path | None,
    mode: str,
    timeout_seconds: float,
    visual_review: Path | None = None,
    trust_policy: Path | None = None,
    temporary_parent: Path | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Launch two same-host installed-Houdini builds and compare evidence."""

    qualification_mode = _qualification_mode(mode)
    (
        hython,
        installed_root,
        harness,
        installed_payload,
    ) = _validate_layout(
        hython, installed_root, harness,
    )
    review_helper = _visual_review_helper()
    try:
        review_payload = review_helper.select_detached_visual_review(
            visual_review, trust_policy=trust_policy, installed_root=installed_root,
            source_root=Path(__file__).resolve().parents[1],
            mode=qualification_mode,
        )
    except review_helper.VisualReviewError as exc:
        raise _invalid(str(exc)) from exc
    timeout = _timeout(timeout_seconds)
    parent = _temporary_parent(evidence_root or temporary_parent)
    temporary = Path(tempfile.mkdtemp(
        prefix="hocuspocus-hs8-clean-process-",
        dir=str(parent) if parent is not None else None,
    ))
    succeeded = False
    try:
        root = temporary
        projections = []
        run_receipts = []
        package_receipts = []
        for ordinal in (1, 2):
            run_root = root / f"run-{ordinal}"
            run_root.mkdir()
            child = _run_installed_harness(
                hython=hython,
                installed_root=installed_root,
                harness=harness,
                run_root=run_root,
                timeout_seconds=timeout,
                ordinal=ordinal,
                mode=qualification_mode,
                visual_review=review_payload,
            )
            projection, receipt = project_portable_receipt(
                child, mode=qualification_mode,
            )
            expected_review_digest = (
                review_payload["digest"]
                if review_payload is not None else _canonical_digest(None)
            )
            if receipt["visualReviewEvidenceDigest"] != expected_review_digest:
                raise _invalid("Child review digest differs from detached approval.")
            projections.append(projection)
            package_receipts.append(
                _object(
                    _object(
                        child.get("installedAlignment"),
                        "installedAlignment",
                    ).get("packageSearch"),
                    "packageSearch",
                ),
            )
            run_receipts.append({
                "run": ordinal,
                "qualificationDigest": receipt["qualificationDigest"],
                "attestationDigest": receipt["attestationDigest"],
                "buildReportDigest": receipt["buildReportDigest"],
                "packagingReceiptDigest": receipt["packagingReceiptDigest"],
                "publishReceiptDigest": receipt["publishReceiptDigest"],
                "visualReviewEvidenceDigest": receipt[
                    "visualReviewEvidenceDigest"
                ],
            })
        differing = _differing_fields(projections[0], projections[1])
        if differing:
            raise CleanProcessQualificationError(
                "HOCUS993",
                "Fresh Houdini processes produced different portable evidence: "
                + ", ".join(differing),
            )
        if package_receipts[0] != package_receipts[1]:
            raise CleanProcessQualificationError(
                "HOCUS993",
                "Fresh Houdini processes produced different full package receipts.",
            )
        if evidence_root is not None:
            retained = temporary / "effective-package-search.json"
            with retained.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(
                    package_receipts[0],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ) + "\n")
        succeeded = True
    except Exception as exc:
        _retain_failure_evidence(temporary, exc)
        raise
    finally:
        if succeeded and evidence_root is None:
            shutil.rmtree(temporary, ignore_errors=True)
    unsigned = {
        "$schema": SCHEMA,
        "kind": "hocus_hs8_clean_process_qualification",
        "schemaVersion": 1,
        "passed": True,
        "isolationBoundary": "same_host_clean_process",
        "qualificationMode": qualification_mode,
        "releaseAuthorized": False,
        "processCount": 2,
        "isolatedState": [
            "houdini-user-preferences",
            "houdini-temp",
            "process-temp",
            "python-bytecode-disabled",
            "xdg-cache",
        ],
        "timingCompared": False,
        "identityCategories": list(IDENTITY_CATEGORIES),
        "installedPayload": installed_payload,
        "portableEvidence": projections[0],
        "portableEvidenceDigest": _canonical_digest(projections[0]),
        "visualReviewEvidenceDigest": projections[0][
            "visualVersionReviewEvidenceDigest"
        ],
        "visualApprovalDigest": (
            review_payload["approvalDigest"]
            if review_payload is not None else None
        ),
        "runs": run_receipts,
    }
    unsigned["receiptDigest"] = _canonical_digest(unsigned)
    return unsigned
def project_portable_receipt(
    child: Mapping[str, Any],
    *,
    mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one child receipt and remove run-local/timing evidence."""

    qualification_mode = _qualification_mode(mode)
    if not isinstance(child, Mapping) or child.get("accepted") is not True:
        raise _invalid("Installed HS8 child did not return an accepted receipt.")
    expected_publish = qualification_mode == "release"
    expected_review_status = (
        "approved" if expected_publish else "review_pending"
    )
    if (
        child.get("readyForPublish") is not False
        or child.get("reviewStatus") != expected_review_status
    ):
        raise _invalid("Installed HS8 child returned the wrong review decision.")
    qualification = _object(child.get("productionQualification"), "qualification")
    if set(qualification) != {
        "$schema", "kind", "schemaVersion", "assetUri", "contractReport",
        "buildReport", "packagingGate", "publishGate", "readyForPackaging",
        "readyForPublish", "authority", "qualificationDigest",
    } or (
        qualification.get("$schema")
        != "hocuspocus://schemas/production-qualification/v1"
        or qualification.get("kind") != "hocus_production_qualification"
        or qualification.get("schemaVersion") != 1
    ):
        raise _invalid("Child qualification has an invalid exact envelope.")
    _verify_digest(qualification, "qualificationDigest", "qualification")
    authority = _object(qualification.get("authority"), "qualification.authority")
    if set(authority) != {"mode", "attestationDigest"}:
        raise _invalid("Child qualification authority has an invalid envelope.")
    attestation_digest = _qualification_authority(authority, release=False)
    if (
        qualification.get("readyForPackaging") is not False
        or qualification.get("readyForPublish") is not False
    ):
        raise _invalid("Child qualification decisions do not match its mode.")
    report = _object(qualification.get("buildReport"), "buildReport")
    _verify_digest(report, "reportDigest", "build report")
    _review_evidence, review_digest = _review_projection(
        report, release=expected_publish,
    )
    contract = _object(qualification.get("contractReport"), "contractReport")
    _verify_digest(contract, "reportDigest", "contract report")
    packaging = _object(qualification.get("packagingGate"), "packagingGate")
    publish = _object(qualification.get("publishGate"), "publishGate")
    _verify_gate(
        packaging, report, "packaging", upstream=None,
        expected_decision="pass",
    )
    _verify_gate(
        publish, report, "publish", upstream=packaging,
        expected_decision="pass" if expected_publish else "fail",
    )
    if qualification.get("assetUri") != report.get("assetUri"):
        raise _invalid("Qualification and build report asset identities differ.")
    deterministic = _object(
        _object(report.get("comparisons"), "comparisons").get("deterministic"),
        "deterministicComparison",
    )
    outputs = _deterministic_outputs(deterministic, report)
    contact = _object(
        _object(child.get("visualEvidence"), "visualEvidence").get("contactSheet"),
        "contactSheet",
    )
    contact_digest = _digest(contact.get("digest"), "contactSheet.digest")
    if outputs["hocus-output://hs8.fixture/contact-sheet.png"] != contact_digest:
        raise _invalid("Contact-sheet evidence is not bound to the output manifest.")
    observed = _object(child.get("observation"), "observation")
    first_observation = _digest(
        observed.get("deterministicDigest"), "observation.deterministicDigest",
    )
    rebuilt_observation = _digest(
        _object(child.get("cleanRebuild"), "cleanRebuild").get("observationDigest"),
        "cleanRebuild.observationDigest",
    )
    if first_observation != rebuilt_observation:
        raise _invalid("Child clean rebuild differs from its first production build.")
    installed_modules = _installed_modules(child)
    alignment = _object(child.get("installedAlignment"), "installedAlignment")
    package_search = _object(alignment.get("packageSearch"), "packageSearch")
    metrics = _stable_metrics(_object(report.get("metrics"), "metrics"))
    provenance_digest = _digest(
        report.get("provenanceManifestDigest"), "provenanceManifestDigest",
    )
    if child.get("buildManifestDigest") != provenance_digest:
        raise _invalid("Outer and qualified build-manifest digests differ.")
    if child.get("contractDigest") != contract.get("contractDigest"):
        raise _invalid("Outer and qualified contract digests differ.")
    if report.get("contractReportDigest") != contract.get("reportDigest"):
        raise _invalid("Build report is not bound to its contract report.")
    projection = {
        "assetUri": _portable_uri(report.get("assetUri"), "assetUri"),
        "targetPlatform": _bounded_text(
            report.get("targetPlatform"), "targetPlatform", 128,
        ),
        "buildIdentity": _digest(report.get("buildIdentity"), "buildIdentity"),
        "provenanceManifestDigest": provenance_digest,
        "outputSetDigest": _digest(
            report.get("outputSetDigest"), "outputSetDigest",
        ),
        "contractReportDigest": _digest(
            report.get("contractReportDigest"), "contractReportDigest",
        ),
        "contractObservationDigest": _digest(
            contract.get("observationDigest"), "contractObservationDigest",
        ),
        "outputs": [
            {"outputUri": uri, "contentDigest": outputs[uri]}
            for uri in sorted(outputs)
        ],
        "contactSheetDigest": contact_digest,
        "productionObservationDigest": first_observation,
        "reviewStatus": expected_review_status,
        "visualVersionReviewEvidenceDigest": review_digest,
        "stableMetrics": metrics,
        "installedModules": installed_modules,
        "packageSearchReceiptDigest": _digest(
            package_search.get("receiptDigest"), "packageSearch.receiptDigest",
        ),
    }
    receipt = {
        "qualificationDigest": qualification["qualificationDigest"],
        "attestationDigest": attestation_digest,
        "buildReportDigest": report["reportDigest"],
        "packagingReceiptDigest": packaging["receiptDigest"],
        "publishReceiptDigest": publish["receiptDigest"],
        "visualReviewEvidenceDigest": review_digest,
    }
    return projection, receipt
def _qualification_authority(
    authority: Mapping[str, Any],
    *,
    release: bool,
) -> str | None:
    del release
    if (
        authority.get("mode") != "content_only"
        or authority.get("attestationDigest") is not None
    ):
        raise _invalid("Technical qualification claimed review authority.")
    return None
def _run_installed_harness(
    *,
    hython: Path,
    installed_root: Path,
    harness: Path,
    run_root: Path,
    timeout_seconds: float,
    ordinal: int,
    mode: str,
    visual_review: Mapping[str, str] | None,
) -> dict[str, Any]:
    environment = _isolated_environment(
        installed_root,
        run_root,
        mode=mode,
        visual_review=visual_review,
    )
    helper = _child_process_helper()
    trace = _capture_authoritative_package_trace(
        helper, hython=hython, harness=harness, run_root=run_root,
        environment=environment, timeout_seconds=timeout_seconds,
        ordinal=ordinal,
    )
    try:
        shutil.rmtree(run_root)
        run_root.mkdir()
        environment = _isolated_environment(
            installed_root, run_root, mode=mode, visual_review=visual_review,
        )
        (run_root / "package-startup-trace.log").write_bytes(trace)
    except OSError as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", "Could not reset isolated state after package trace.",
        ) from exc
    try:
        result = helper.run_child(
            [str(hython), "-u", str(harness)],
            cwd=str(harness.parent),
            environment=environment,
            run_root=run_root,
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=MAX_STDOUT_BYTES,
            max_stderr_bytes=MAX_STDERR_BYTES,
        )
    except helper.ChildProcessError as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", f"Installed HS8 process {ordinal}: {exc}",
        ) from exc
    if result.returncode != 0:
        message = _child_failure_message(result.stdout, result.stderr)
        raise CleanProcessQualificationError(
            "HOCUS992",
            f"Installed HS8 process {ordinal} failed with code "
            f"{result.returncode}: {message}",
        )
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CleanProcessQualificationError(
            "HOCUS992",
            f"Installed HS8 process {ordinal} returned invalid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise CleanProcessQualificationError(
            "HOCUS992",
            f"Installed HS8 process {ordinal} returned a non-object receipt.",
        )
    return payload
def _capture_authoritative_package_trace(
    helper: ModuleType, *, hython: Path, harness: Path, run_root: Path,
    environment: Mapping[str, str], timeout_seconds: float, ordinal: int,
) -> bytes:
    probe_root = run_root.parent / f"package-trace-probe-{ordinal}"
    probe_root.mkdir()
    probe_environment = dict(environment)
    probe_environment["HOUDINI_PACKAGE_VERBOSE"] = "1"
    probe_environment.pop("HOCUSPOCUS_HS8_PACKAGE_TRACE", None)
    try:
        result = helper.run_child(
            [str(hython), "-u", "-c", "pass"], cwd=str(harness.parent),
            environment=probe_environment, run_root=probe_root,
            timeout_seconds=timeout_seconds, max_stdout_bytes=1024 * 1024,
            max_stderr_bytes=MAX_STDERR_BYTES,
        )
        trace = result.stderr
    except helper.ChildProcessError as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", f"Installed HS8 package-trace probe {ordinal}: {exc}",
        ) from exc
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)
    if (
        result.returncode != 0
        or trace.count(b"= = = Houdini Package log = = =") != 1
        or b"= = = = = = = = = = = = = = = =" not in trace
    ):
        raise CleanProcessQualificationError(
            "HOCUS991",
            f"Installed HS8 package-trace probe {ordinal} was incomplete.",
        )
    return trace
def _isolated_environment(
    installed_root: Path,
    run_root: Path,
    *,
    mode: str,
    visual_review: Mapping[str, str] | None,
) -> dict[str, str]:
    package_directory = run_root / "packages"
    directories = {
        "HOUDINI_USER_PREF_DIR": run_root / "houdini__HVER__",
        "HOUDINI_TEMP_DIR": run_root / "houdini-temp",
        "TEMP": run_root / "process-temp",
        "TMP": run_root / "process-temp",
        "XDG_CACHE_HOME": run_root / "xdg-cache",
    }
    concrete_directories = {
        directory
        for directory in directories.values()
        if "__HVER__" not in str(directory)
    }
    diagnostic_directory = run_root / "diagnostics"
    for directory in {
        *concrete_directories, package_directory, diagnostic_directory,
    }:
        directory.mkdir(parents=True, exist_ok=True)
    package_manifest = {
        "env": [
            {"HOCUSPOCUS_ROOT": installed_root.as_posix()},
            {
                "PYTHONPATH": {
                    "method": "prepend",
                    "value": "$HOCUSPOCUS_ROOT/python3.11libs",
                },
            },
            {"PYTHONDONTWRITEBYTECODE": "1"},
        ],
        "hpath": "$HOCUSPOCUS_ROOT",
    }
    (package_directory / "hocuspocus.json").write_text(
        json.dumps(package_manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    environment = _inherited_environment()
    environment.update({
        name: str(path)
        for name, path in directories.items()
    })
    environment.update({
        "HOCUSPOCUS_ROOT": str(installed_root),
        "HOCUSPOCUS_HS8_QUALIFICATION_MODE": mode,
        "HOUDINI_PACKAGE_DIR": str(package_directory),
        "HOUDINI_NO_ENV_FILE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "HOCUSPOCUS_HS8_PACKAGE_TRACE": str(
            run_root / "package-startup-trace.log",
        ),
    })
    if mode == "technical":
        environment["HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT"] = str(
            diagnostic_directory,
        )
    if visual_review is not None:
        environment["HOCUSPOCUS_HS8_VISUAL_REVIEW_CONTENT"] = visual_review[
            "content"
        ]
        environment["HOCUSPOCUS_HS8_VISUAL_REVIEW_DIGEST"] = visual_review[
            "digest"
        ]
    return environment
def _inherited_environment() -> dict[str, str]:
    environment = {}
    for name in INHERITED_ENVIRONMENT:
        value = os.environ.get(name)
        if value is None:
            continue
        if "\0" in value or len(value.encode("utf-8")) > 32 * 1024:
            raise CleanProcessQualificationError(
                "HOCUS991",
                f"Inherited environment value {name} is invalid or unbounded.",
            )
        environment[name] = value
    return environment
def _deterministic_outputs(
    comparison: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, str]:
    if (
        comparison.get("kind") != "deterministic_rebuild_comparison"
        or comparison.get("passed") is not True
        or comparison.get("buildIdentityMatches") is not True
        or comparison.get("outputSetMatches") is not True
    ):
        raise _invalid("Child deterministic rebuild comparison did not pass.")
    if comparison.get("candidateManifestDigest") != report.get(
        "provenanceManifestDigest",
    ):
        raise _invalid("Deterministic comparison is not bound to the build report.")
    rows = comparison.get("outputs")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise _invalid("Deterministic output comparison is invalid.")
    outputs: dict[str, str] = {}
    for row in rows:
        value = _object(row, "deterministic output")
        uri = _portable_uri(value.get("outputUri"), "outputUri")
        before = _digest(value.get("baselineDigest"), "baselineDigest")
        after = _digest(value.get("candidateDigest"), "candidateDigest")
        if value.get("status") != "match" or before != after or uri in outputs:
            raise _invalid("Deterministic output comparison is inconsistent.")
        outputs[uri] = after
    if set(outputs) != EXPECTED_OUTPUT_URIS:
        raise _invalid("Installed HS8 output set is incomplete or unexpected.")
    if report.get("outputCount") != len(outputs):
        raise _invalid("Build report output count differs from its comparison.")
    return outputs
def _verify_gate(
    gate: Mapping[str, Any],
    report: Mapping[str, Any],
    expected_gate: str,
    *,
    upstream: Mapping[str, Any] | None,
    expected_decision: str,
) -> None:
    if set(gate) != {
        "$schema", "kind", "schemaVersion", "gate", "reportDigest",
        "upstreamReceiptDigest", "upstreamDecision", "checks", "decision",
        "receiptDigest",
    } or (
        gate.get("$schema") != "hocuspocus://schemas/publish-gate-receipt/v1"
        or gate.get("kind") != "hocus_gate_receipt"
        or gate.get("schemaVersion") != 1
    ):
        raise _invalid(f"{expected_gate} gate has an invalid exact envelope.")
    _verify_digest(gate, "receiptDigest", expected_gate + " gate")
    if (
        gate.get("gate") != expected_gate
        or gate.get("decision") != expected_decision
        or gate.get("reportDigest") != report.get("reportDigest")
    ):
        raise _invalid(f"{expected_gate} gate is invalid or did not pass.")
    if upstream is None:
        if (
            gate.get("upstreamReceiptDigest") is not None
            or gate.get("upstreamDecision") is not None
        ):
            raise _invalid("Packaging gate unexpectedly declares upstream evidence.")
    elif (
        gate.get("upstreamReceiptDigest") != upstream.get("receiptDigest")
        or gate.get("upstreamDecision") != "pass"
    ):
        raise _invalid("Publish gate is not bound to its passing packaging gate.")
    checks = gate.get("checks")
    expected_ids = (
        PACKAGING_CHECK_IDS if expected_gate == "packaging"
        else PUBLISH_CHECK_IDS
    )
    if (
        not isinstance(checks, list)
        or [check.get("id") for check in checks if isinstance(check, dict)]
        != list(expected_ids)
    ):
        raise _invalid(f"{expected_gate} gate has invalid checks.")
    expected_results = [True] * len(expected_ids)
    if expected_gate == "publish" and expected_decision == "fail":
        expected_results[-1] = False
    if [
        check.get("passed") if isinstance(check, dict) else None
        for check in checks
    ] != expected_results:
        raise _invalid(f"{expected_gate} gate has unexpected check decisions.")
    for check in checks:
        if set(check) != {"id", "passed", "evidenceDigest"}:
            raise _invalid(f"{expected_gate} gate check has an invalid envelope.")
        _digest(check.get("evidenceDigest"), "gate check evidenceDigest")
def _review_projection(
    report: Mapping[str, Any],
    *,
    release: bool,
) -> tuple[dict[str, Any] | None, str]:
    if release:
        return _visual_version_review(report)
    if report.get("visualVersionReviewEvidence") is not None:
        raise _invalid("Technical qualification contains review approval.")
    digest = _digest(
        report.get("visualVersionReviewEvidenceDigest"),
        "visualVersionReviewEvidenceDigest",
    )
    if digest != _canonical_digest(None):
        raise _invalid("Pending review digest does not bind a null carrier.")
    return None, digest
def _visual_version_review(
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    value = _object(
        report.get("visualVersionReviewEvidence"),
        "visualVersionReviewEvidence",
    )
    fields = {
        "kind", "reviewVersion", "assetUri",
        "candidateProvenanceManifestDigest", "candidateOutputSetDigest",
        "visualComparisonDigest", "candidateVersionId", "reviewPolicyId",
        "reviewerPrincipalId", "decision", "notesDigest",
    }
    if set(value) != fields:
        raise _invalid("Visual version review evidence has an invalid envelope.")
    candidate_version = _portable_id(
        value.get("candidateVersionId"), "candidateVersionId",
    )
    policy = _portable_id(value.get("reviewPolicyId"), "reviewPolicyId")
    reviewer = value.get("reviewerPrincipalId")
    if not isinstance(reviewer, str) or _REVIEWER_ID.fullmatch(reviewer) is None:
        raise _invalid("reviewerPrincipalId is not portable.")
    notes = value.get("notesDigest")
    if notes is not None:
        notes = _digest(notes, "notesDigest")
    comparisons = _object(report.get("comparisons"), "comparisons")
    expected = {
        "assetUri": report.get("assetUri"),
        "candidateProvenanceManifestDigest": report.get(
            "provenanceManifestDigest",
        ),
        "candidateOutputSetDigest": report.get("outputSetDigest"),
        "visualComparisonDigest": _canonical_digest(comparisons.get("visual")),
    }
    if (
        value.get("kind") != "hocus_visual_version_review_evidence"
        or value.get("reviewVersion") != 1
        or value.get("decision") != "approved"
        or any(value.get(field) != expected_value for field, expected_value in expected.items())
    ):
        raise _invalid("Visual version review does not approve this candidate.")
    digest = _digest(
        report.get("visualVersionReviewEvidenceDigest"),
        "visualVersionReviewEvidenceDigest",
    )
    if digest != _canonical_digest(value):
        raise _invalid("Visual version review digest does not match its content.")
    normalized = dict(value)
    normalized["candidateVersionId"] = candidate_version
    normalized["reviewPolicyId"] = policy
    normalized["reviewerPrincipalId"] = reviewer
    normalized["notesDigest"] = notes
    return normalized, digest
def _installed_modules(child: Mapping[str, Any]) -> list[dict[str, str]]:
    alignment = _object(child.get("installedAlignment"), "installedAlignment")
    modules = alignment.get("modules")
    if not isinstance(modules, list) or not 1 <= len(modules) <= 4096:
        raise _invalid("Installed module alignment is absent or unbounded.")
    result = []
    for item in modules:
        value = _object(item, "installed module")
        relative = _bounded_text(value.get("relativePath"), "relativePath", 1024)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative:
            raise _invalid("Installed module receipt contains a non-portable path.")
        result.append({
            "module": _bounded_text(value.get("module"), "module", 256),
            "relativePath": relative,
            "digest": _digest(value.get("digest"), "installed module digest"),
        })
    ordered = sorted(result, key=lambda item: item["module"])
    if len({item["module"] for item in ordered}) != len(ordered):
        raise _invalid("Installed module receipts must be unique.")
    return ordered
def _stable_metrics(metrics: Mapping[str, Any]) -> dict[str, int]:
    fields = (
        "polygonCount", "textureCount", "textureBytes", "outputBytes",
        "cookErrorCount", "cookWarningCount",
    )
    result = {}
    for field in fields:
        value = metrics.get(field)
        if type(value) is not int or value < 0:
            raise _invalid(f"Stable metric {field} is invalid.")
        result[field] = value
    return result
def _verify_digest(
    value: Mapping[str, Any],
    field: str,
    label: str,
) -> None:
    actual = _digest(value.get(field), f"{label}.{field}")
    unsigned = {key: item for key, item in value.items() if key != field}
    if actual != _canonical_digest(unsigned):
        raise _invalid(f"{label} digest does not match its canonical content.")
def _validate_layout(
    hython: Path,
    installed_root: Path,
    harness: Path | None,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    executable = _resolved_file(hython, "hython")
    if executable.name.casefold() not in {"hython", "hython.exe"}:
        raise CleanProcessQualificationError(
            "HOCUS991", "The selected executable is not hython.",
        )
    installed = _resolved_directory(installed_root, "installed root")
    repository = Path(__file__).resolve().parents[1]
    if installed == repository or repository in installed.parents:
        raise CleanProcessQualificationError(
            "HOCUS991", "Installed root must not resolve inside the repository.",
        )
    if not (installed / "python3.11libs" / "hocuspocus").is_dir():
        raise CleanProcessQualificationError(
            "HOCUS991", "Installed root does not contain HocusPocus Python modules.",
        )
    package_file = installed.parent / "hocuspocus.json"
    if (
        package_file.is_symlink()
        or not package_file.is_file()
        or package_file.stat().st_size > 64 * 1024
    ):
        raise CleanProcessQualificationError(
            "HOCUS991", "Installed Houdini package manifest is missing or unbounded.",
        )
    if _active_package_root(package_file) != installed:
        raise CleanProcessQualificationError(
            "HOCUS991",
            "Installed root is not selected by the active Houdini package pointer.",
        )
    expected_harness = (
        installed / "scripts" / "smoke_hocusscript_hs8.py"
    ).resolve()
    selected_harness = _resolved_file(
        harness if harness is not None else expected_harness,
        "installed HS8 harness",
    )
    if selected_harness != expected_harness:
        raise CleanProcessQualificationError(
            "HOCUS991", "HS8 harness must come from the installed payload.",
        )
    installed_payload = _verify_installed_payload(repository, installed)
    return (
        executable,
        installed,
        selected_harness,
        installed_payload,
    )
def _active_package_root(package_file: Path) -> Path:
    helper = _package_pointer_helper()
    try:
        return helper.active_package_root(package_file)
    except helper.PackagePointerError as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", str(exc),
        ) from exc


def _package_pointer_helper() -> ModuleType:
    path = Path(__file__).resolve().with_name("hs8_package_pointer.py")
    spec = importlib.util.spec_from_file_location("_hocus_hs8_package_pointer", path)
    if spec is None or spec.loader is None:
        raise CleanProcessQualificationError(
            "HOCUS991", "Package-pointer verifier is unavailable.",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def _verify_installed_payload(
    source_root: Path,
    installed_root: Path,
) -> dict[str, Any]:
    helper = _install_manifest_helper()
    try:
        source = helper.create_manifest(source_root)
        installed = helper.verify_manifest(installed_root)
    except helper.InstallManifestError as exc:
        raise CleanProcessQualificationError("HOCUS991", str(exc)) from exc
    if source != installed:
        raise CleanProcessQualificationError(
            "HOCUS991",
            "Installed governed manifest differs from the source checkout.",
        )
    return {
        "artifactCount": len(installed["files"]),
        "manifestDigest": installed["manifestDigest"],
        "artifacts": installed["files"],
    }
def _install_manifest_helper() -> ModuleType:
    path = Path(__file__).resolve().with_name("hs8_install_manifest.py")
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_hs8_install_manifest", path,
    )
    if spec is None or spec.loader is None:
        raise CleanProcessQualificationError(
            "HOCUS991", "Could not load the governed install manifest helper.",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def _child_process_helper() -> ModuleType:
    path = Path(__file__).resolve().with_name("hs8_child_process.py")
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_hs8_child_process", path,
    )
    if spec is None or spec.loader is None:
        raise CleanProcessQualificationError(
            "HOCUS991", "Could not load the bounded child-process helper.",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def _visual_review_helper() -> ModuleType:
    path = Path(__file__).resolve().with_name("hs8_visual_review.py")
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_hs8_visual_review", path,
    )
    if spec is None or spec.loader is None:
        raise CleanProcessQualificationError(
            "HOCUS991", "Could not load detached visual-review validation.",
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def _resolved_payload_file(
    root: Path,
    relative: str,
    label: str,
) -> Path:
    selected = (root / Path(relative)).resolve()
    if root not in selected.parents or not selected.is_file():
        raise CleanProcessQualificationError(
            "HOCUS991",
            f"{label} HS8 payload artifact is missing or unsafe: {relative}.",
        )
    if selected.stat().st_size > 32 * 1024 * 1024:
        raise CleanProcessQualificationError(
            "HOCUS991", f"{label} HS8 payload artifact is unbounded.",
        )
    return selected
def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", "Could not digest an HS8 payload artifact.",
        ) from exc
    return "sha256:" + digest.hexdigest()
def _resolved_file(value: Path, label: str) -> Path:
    try:
        resolved = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", f"{label} path is unavailable.",
        ) from exc
    if not resolved.is_file():
        raise CleanProcessQualificationError("HOCUS991", f"{label} is not a file.")
    return resolved
def _resolved_directory(value: Path, label: str) -> Path:
    try:
        resolved = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CleanProcessQualificationError(
            "HOCUS991", f"{label} path is unavailable.",
        ) from exc
    if not resolved.is_dir():
        raise CleanProcessQualificationError(
            "HOCUS991", f"{label} is not a directory.",
        )
    return resolved
def _temporary_parent(value: Path | None) -> Path | None:
    if value is None:
        return None
    return _resolved_directory(value, "temporary parent")
def _qualification_mode(value: Any) -> str:
    if not isinstance(value, str) or value not in QUALIFICATION_MODES:
        raise CleanProcessQualificationError(
            "HOCUS991", "Qualification mode must be technical or release.",
        )
    return value
def _timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 1.0 <= float(value) <= MAX_TIMEOUT_SECONDS
    ):
        raise CleanProcessQualificationError(
            "HOCUS991",
            f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS:g}.",
        )
    return float(value)
def _retain_failure_evidence(root: Path, exc: BaseException) -> None:
    try:
        retained = _retained_streams(root)
        retained_rows, retained_total = _reset_evidence_root(root, retained)
    except (OSError, shutil.Error) as evidence_error:
        raise CleanProcessQualificationError(
            "HOCUS991",
            "Qualification failed and failure evidence could not be sanitized.",
        ) from evidence_error
    payload = {
        "kind": "hocus_hs8_failure_evidence",
        "errorType": type(exc).__name__,
        "message": str(exc)[:4096],
        "retainedFiles": retained_rows,
    }
    try:
        failure_path = root / "failure.json"
        with failure_path.open("x", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
            )
        if (
            retained_total + failure_path.stat().st_size
            > MAX_RETAINED_EVIDENCE_BYTES
        ):
            raise CleanProcessQualificationError(
                "HOCUS991", "Retained failure evidence exceeds its aggregate limit.",
            )
    except OSError as evidence_error:
        raise CleanProcessQualificationError(
            "HOCUS991", "Failure evidence could not be retained safely.",
        ) from evidence_error
    if isinstance(exc, CleanProcessQualificationError):
        exc.message += f" Failure evidence retained at {root}."
        exc.args = (exc.message,)
def _retained_streams(root: Path) -> list[tuple[str, bytes, int]]:
    retained: list[tuple[str, bytes, int]] = []
    for run_name in ("run-1", "run-2"):
        selections = [
            (f"{run_name}/stdout.json", root / run_name / "stdout.json"),
            (f"{run_name}/stderr.log", root / run_name / "stderr.log"),
        ]
        diagnostic_root = root / run_name / "diagnostics"
        selections.extend(
            (
                f"{run_name}/diagnostics/{name}",
                diagnostic_root / name,
            )
            for name in (
                "first-rock-family.usda",
                "reopened-rock-family.usda",
                "rebuilt-rock-family.usda",
                "failure-evidence-diagnostic.json",
            )
        )
        for relative, selected in selections:
            if selected.is_symlink() or not selected.is_file():
                continue
            try:
                resolved = selected.resolve(strict=True)
            except OSError:
                continue
            if root not in resolved.parents:
                continue
            original_size = resolved.stat().st_size
            with resolved.open("rb") as handle:
                if selected.name == "stderr.log" and original_size > MAX_RETAINED_STREAM_BYTES:
                    handle.seek(-MAX_RETAINED_STREAM_BYTES, os.SEEK_END)
                content = handle.read(MAX_RETAINED_STREAM_BYTES)
            retained.append((relative, content, original_size))
    return retained
def _reset_evidence_root(
    root: Path,
    retained: list[tuple[str, bytes, int]],
) -> tuple[list[dict[str, Any]], int]:
    shutil.rmtree(root)
    root.mkdir(mode=0o700)
    rows = []
    total = 0
    for relative, content, original_size in retained:
        total += len(content)
        if total > MAX_RETAINED_EVIDENCE_BYTES:
            raise CleanProcessQualificationError(
                "HOCUS991", "Retained failure evidence exceeds its aggregate limit.",
            )
        target = root / Path(relative)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(content)
        rows.append({
            "relativePath": relative,
            "originalBytes": original_size,
            "retainedBytes": len(content),
            "truncated": original_size != len(content),
        })
    return rows, total
def _child_failure_message(stdout: bytes, stderr: bytes) -> str:
    try:
        payload = json.loads(stdout.decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            return payload["message"][:2048]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return stderr.decode("utf-8", errors="replace")[-2048:].strip() or "no diagnostic"
def _differing_fields(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> list[str]:
    keys = sorted(set(first) | set(second))
    return [
        key for key in keys
        if _canonical_json(first.get(key)) != _canonical_json(second.get(key))
    ]
def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object.")
    return value
def _portable_uri(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > 8192
        or _PORTABLE_URI.fullmatch(value) is None
    ):
        raise _invalid(f"{label} is not a canonical portable URI.")
    return value
def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
    ):
        raise _invalid(f"{label} is invalid or unbounded.")
    return value
def _portable_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or _PORTABLE_ID.fullmatch(value) is None:
        raise _invalid(f"{label} is not a canonical portable identifier.")
    return value
def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise _invalid(f"{label} is not a canonical sha256 digest.")
    return value
def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8"),
    ).hexdigest()
def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid("Clean-process receipt must be finite JSON.") from exc
def _invalid(message: str) -> CleanProcessQualificationError:
    return CleanProcessQualificationError("HOCUS993", message)
def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run installed HS8 acceptance in two isolated fresh Houdini "
            "processes on the same host and compare deterministic receipts."
        ),
    )
    parser.add_argument("--hython", required=True, type=Path)
    parser.add_argument("--installed-root", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=sorted(QUALIFICATION_MODES),
        default="technical",
        help=(
            "technical requires package stability with review pending; release "
            "requires --visual-review and host-attested publish."
        ),
    )
    parser.add_argument("--visual-review", type=Path)
    parser.add_argument(
        "--trust-policy",
        type=Path,
        help="External policy containing the visualReviewer role.",
    )
    parser.add_argument(
        "--harness",
        type=Path,
        help=(
            "Optional installed harness override; it must resolve to "
            "<installed-root>/scripts/smoke_hocusscript_hs8.py."
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--temporary-parent", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    return parser.parse_args(argv)
def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _arguments(argv)
        receipt = qualify_two_clean_processes(
            hython=arguments.hython,
            installed_root=arguments.installed_root,
            harness=arguments.harness,
            mode=arguments.mode,
            timeout_seconds=arguments.timeout_seconds,
            visual_review=arguments.visual_review,
            trust_policy=arguments.trust_policy,
            temporary_parent=arguments.temporary_parent,
            evidence_root=arguments.evidence_root,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except CleanProcessQualificationError as exc:
        print(json.dumps({
            "accepted": False,
            "errorCode": exc.code,
            "message": exc.message,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
if __name__ == "__main__":
    raise SystemExit(main())
