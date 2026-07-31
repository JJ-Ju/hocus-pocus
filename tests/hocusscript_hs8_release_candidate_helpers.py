"""Focused RC2 immutable release-candidate manifest assertions."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from unittest import mock
from pathlib import Path
from types import ModuleType
from typing import Any

from hocuspocus.hocusscript.release_candidate import (
    SCHEMA,
    ReleaseCandidateError,
    create_release_candidate_manifest,
    verify_release_candidate_manifest,
)
from hocuspocus.hocusscript.release_evidence import create_rc1_evidence_set


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "schemas" / "release-candidate-manifest-v1.schema.json"
RC1_SCHEMA_PATH = ROOT / "docs" / "schemas" / "rc1-evidence-set-v1.schema.json"
CLI = ROOT / "scripts" / "manage_hocusscript_release_candidate.py"
RC1_CLI = ROOT / "scripts" / "manage_hocusscript_rc1_evidence.py"
MANIFEST_HELPER = ROOT / "scripts" / "hs8_install_manifest.py"
RECEIPT_HELPER = ROOT / "scripts" / "release_evidence_support.py"
REQUIREMENTS = ROOT / "requirements-release.txt"


def assert_hs8_release_candidate_manifest(testcase: Any) -> None:
    """Prove exact RC2 identity, non-authority, offline I/O, and packaging."""

    evidence = _rc1_evidence()
    inputs = _inputs(evidence)
    manifest = create_release_candidate_manifest(inputs, evidence)
    with testcase.subTest("schema and canonical identity"):
        _assert_schema(testcase, manifest, evidence)
        result = verify_release_candidate_manifest(manifest, inputs, evidence)
        testcase.assertTrue(result["immutableCandidateIdentified"])
        testcase.assertFalse(result["releaseAuthorized"])
        testcase.assertEqual(result["manifestDigest"], manifest["manifestDigest"])
    with testcase.subTest("every operator identity is exact"):
        _assert_exact_inputs(testcase, manifest, inputs, evidence)
    with testcase.subTest("RC1 evidence is decoded and cross-bound"):
        _assert_rc1_binding(testcase, inputs, evidence)
        _assert_rc1_package_source_binding(testcase)
    with testcase.subTest("offline receipt publication is immutable"):
        _assert_offline_receipt_publication(testcase)
    with testcase.subTest("self digest grants no authority"):
        _assert_self_digest_boundary(testcase, manifest, inputs, evidence)
    with testcase.subTest("offline create and verify"):
        _assert_cli(testcase, inputs, evidence)
    with testcase.subTest("shipped surface and pinned dependency"):
        _assert_packaging(testcase)


def _assert_schema(
    testcase: Any,
    manifest: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(manifest)
    testcase.assertEqual(schema["$id"], SCHEMA)
    testcase.assertFalse(schema["additionalProperties"])
    rc1_schema = json.loads(RC1_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(rc1_schema)
    jsonschema.Draft202012Validator(rc1_schema).validate(evidence)
    module = (
        ROOT
        / "python3.11libs"
        / "hocuspocus"
        / "hocusscript"
        / "release_candidate.py"
    )
    testcase.assertLessEqual(len(module.read_text(encoding="utf-8").splitlines()), 1200)


def _assert_exact_inputs(
    testcase: Any,
    manifest: dict[str, Any],
    inputs: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    for section, values in inputs.items():
        for field in values:
            with testcase.subTest(section=section, identity=field):
                changed = copy.deepcopy(inputs)
                changed[section][field] = _other_identity(field)
                with testcase.assertRaises(ReleaseCandidateError):
                    verify_release_candidate_manifest(manifest, changed, evidence)


def _assert_self_digest_boundary(
    testcase: Any,
    manifest: dict[str, Any],
    inputs: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    testcase.assertNotIn("signature", manifest)
    testcase.assertNotIn("authority", manifest)
    changed = copy.deepcopy(manifest)
    changed["inputs"]["releaseAssets"]["baselineSetDigest"] = _digest(b"changed")
    with testcase.assertRaises(ReleaseCandidateError):
        verify_release_candidate_manifest(changed, inputs, evidence)
    extra = copy.deepcopy(manifest)
    extra["releaseAuthorized"] = True
    with testcase.assertRaises(ReleaseCandidateError):
        verify_release_candidate_manifest(extra, inputs, evidence)
    boolean_version = copy.deepcopy(manifest)
    boolean_version["schemaVersion"] = True
    with testcase.assertRaises(ReleaseCandidateError):
        verify_release_candidate_manifest(boolean_version, inputs, evidence)


def _assert_rc1_binding(
    testcase: Any,
    inputs: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(evidence)
    tampered["receipts"]["performance"]["fileDigest"] = _digest(b"tampered")
    with testcase.assertRaises(ReleaseCandidateError):
        create_release_candidate_manifest(inputs, tampered)
    other_receipts = copy.deepcopy(evidence["receipts"])
    other_receipts["performance"]["fileDigest"] = _digest(b"other-file")
    other = create_rc1_evidence_set(evidence["candidate"], other_receipts)
    with testcase.assertRaises(ReleaseCandidateError):
        create_release_candidate_manifest(inputs, other)


def _assert_rc1_package_source_binding(testcase: Any) -> None:
    rc1 = _load_script_helper("hocuspocus_rc1_cli_contract", RC1_CLI)
    helper = _load_manifest_helper()
    source = helper.create_manifest(ROOT)
    package = {
        "installedPayload": {
            "manifestDigest": source["manifestDigest"],
            "artifactCount": len(source["files"]),
        },
    }
    rc1._verify_current_installed_payload(package, source)
    stale = copy.deepcopy(package)
    stale["installedPayload"]["manifestDigest"] = _digest(b"stale-install")
    with testcase.assertRaises(rc1.ReleaseEvidenceError):
        rc1._verify_current_installed_payload(stale, source)
    wrong_count = copy.deepcopy(package)
    wrong_count["installedPayload"]["artifactCount"] += 1
    with testcase.assertRaises(rc1.ReleaseEvidenceError):
        rc1._verify_current_installed_payload(wrong_count, source)


def _assert_offline_receipt_publication(testcase: Any) -> None:
    support = _load_script_helper(
        "hocuspocus_release_evidence_output_contract",
        RECEIPT_HELPER,
    )
    rc1 = _load_script_helper("hocuspocus_rc1_output_contract", RC1_CLI)
    rc2 = _load_script_helper("hocuspocus_rc2_output_contract", CLI)
    publishers = (
        ("rc1", rc1._output, rc1.ReleaseEvidenceError),
        ("rc2", rc2._output, rc2.ReleaseCandidateError),
    )
    value = {"kind": "test_receipt", "passed": True}
    with tempfile.TemporaryDirectory(prefix="hocus-release-output-") as raw:
        root = Path(raw)
        target = root / "receipt.json"
        support.write_receipt(target, value)
        original = target.read_bytes()
        with testcase.assertRaises(ValueError):
            support.write_receipt(target, {"kind": "replacement"})
        testcase.assertEqual(target.read_bytes(), original)
        failed = root / "failed.json"
        with (
            mock.patch.object(support.os, "link", side_effect=OSError("fail")),
            testcase.assertRaises(ValueError),
        ):
            support.write_receipt(failed, value)
        testcase.assertFalse(failed.exists())
        testcase.assertFalse(any(root.glob(".failed.json.candidate.*")))
        reparse = mock.Mock(
            st_mode=support.stat.S_IFLNK,
            st_file_attributes=0,
        )
        with (
            mock.patch.object(support.os, "lstat", return_value=reparse),
            testcase.assertRaises(ValueError),
        ):
            support.write_receipt(root / "linked.json", value)
        for name, publish, error in publishers:
            with testcase.subTest(publisher=name, boundary="no-clobber"):
                with testcase.assertRaises(error):
                    publish(target, {"kind": "replacement"})
                testcase.assertEqual(target.read_bytes(), original)
        _assert_reparse_parent_rejected(
            testcase, root, value, publishers,
        )
    with testcase.assertRaises(ValueError):
        support.write_receipt(ROOT / ".forbidden-release-receipt.json", value)


def _assert_reparse_parent_rejected(
    testcase: Any,
    root: Path,
    value: dict[str, Any],
    publishers: tuple[tuple[str, Any, type[Exception]], ...],
) -> None:
    target = root / "reparse-target"
    target.mkdir()
    links: list[tuple[str, Path]] = []
    symlink = root / "symlink-parent"
    try:
        symlink.symlink_to(target, target_is_directory=True)
    except OSError:
        pass
    else:
        links.append(("symlink", symlink))
    if sys.platform == "win32":
        junction = root / "junction-parent"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        testcase.assertEqual(created.returncode, 0, created.stderr)
        links.append(("junction", junction))
    try:
        for link_kind, link in links:
            for publisher, publish, error in publishers:
                with testcase.subTest(
                    publisher=publisher, boundary=link_kind,
                ):
                    with testcase.assertRaises(error):
                        publish(link / f"{publisher}.json", value)
    finally:
        for _, link in reversed(links):
            if link.is_symlink():
                link.unlink()
            elif link.exists():
                link.rmdir()


def _assert_cli(
    testcase: Any,
    inputs: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    with tempfile.TemporaryDirectory(prefix="hocus-rc2-") as value:
        root = Path(value)
        inputs_path = root / "candidate-inputs.json"
        evidence_path = root / "rc1-evidence-set.json"
        output_path = root / "candidate-manifest.json"
        inputs_path.write_text(json.dumps(inputs), encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        created = _run(
            "create",
            "--inputs",
            str(inputs_path),
            "--rc1-evidence-set",
            str(evidence_path),
            "--output",
            str(output_path),
        )
        testcase.assertEqual(created.returncode, 0, created.stderr)
        created_result = json.loads(created.stdout)
        testcase.assertFalse(created_result["releaseAuthorized"])
        testcase.assertTrue(output_path.is_file())
        verified = _run(
            "verify",
            "--manifest",
            str(output_path),
            "--expected-inputs",
            str(inputs_path),
            "--rc1-evidence-set",
            str(evidence_path),
        )
        testcase.assertEqual(verified.returncode, 0, verified.stderr)
        testcase.assertTrue(json.loads(verified.stdout)["verified"])
        duplicate = _run(
            "create",
            "--inputs",
            str(inputs_path),
            "--rc1-evidence-set",
            str(evidence_path),
            "--output",
            str(output_path),
        )
        testcase.assertNotEqual(duplicate.returncode, 0)
        forbidden = ROOT / ".forbidden-release-candidate-test.json"
        rejected = _run(
            "create",
            "--inputs",
            str(inputs_path),
            "--rc1-evidence-set",
            str(evidence_path),
            "--output",
            str(forbidden),
        )
        testcase.assertNotEqual(rejected.returncode, 0)
        testcase.assertFalse(forbidden.exists())


def _assert_packaging(testcase: Any) -> None:
    helper = _load_manifest_helper()
    payload = helper.create_manifest(ROOT)
    governed = {item["relativePath"] for item in payload["files"]}
    for relative in (
        "docs/schemas/release-candidate-manifest-v1.schema.json",
        "docs/schemas/rc1-evidence-set-v1.schema.json",
        "python3.11libs/hocuspocus/hocusscript/release_candidate.py",
        "python3.11libs/hocuspocus/hocusscript/release_evidence.py",
        "scripts/manage_hocusscript_rc1_evidence.py",
        "scripts/manage_hocusscript_release_candidate.py",
    ):
        testcase.assertIn(relative, governed)
    requirements = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    testcase.assertEqual(requirements, ["cryptography==45.0.3"])


def _inputs(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": {
            "commitDigest": evidence["candidate"]["commitDigest"],
            "treeDigest": evidence["candidate"]["treeDigest"],
            "sourceArchiveDigest": _digest(b"source-archive"),
        },
        "execution": {
            "runnerSetDigest": _digest(b"runners"),
            "dependencySetDigest": _digest(b"dependencies"),
        },
        "releaseAssets": {
            "fixtureSetDigest": _digest(b"fixtures"),
            "baselineSetDigest": _digest(b"baselines"),
            "reviewRequestDigest": _digest(b"review-request"),
            "schemaSetDigest": _digest(b"schemas"),
        },
        "installedCandidate": {
            "installManifestDigest": evidence["installedPayloadManifestDigest"],
            "activePointerDigest": _digest(b"active-pointer"),
            "runtimeDigest": evidence["runtimeDigest"],
        },
        "evidence": {
            "technicalQualificationReceiptDigest": _digest(b"technical"),
            "packageProvenanceReceiptDigest": evidence["receipts"][
                "packageSearch"
            ]["receiptDigest"],
            "rc1EvidenceDigest": evidence["evidenceSetDigest"],
        },
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
        "schema": (
            "hocuspocus://schemas/effective-package-search-provenance/v1"
        ),
        "kind": "hocus_effective_package_search_provenance",
        "receiptDigest": _digest(b"package-receipt"),
        "fileDigest": _digest(b"package-file"),
        "installedPayloadManifestDigest": _digest(b"install-manifest"),
        "runtimeDigest": _digest(b"runtime"),
    }
    candidate = {
        "commitDigest": "git-sha1:" + "1" * 40,
        "treeDigest": "git-sha1:" + "2" * 40,
        "workspaceSnapshotDigest": _digest(b"workspace"),
        "fileCount": 1,
        "clean": True,
    }
    return create_rc1_evidence_set(candidate, receipts)


def _other_identity(field: str) -> str:
    if field in {"commitDigest", "treeDigest"}:
        return "git-sha1:" + "f" * 40
    return _digest(f"other-{field}".encode("ascii"))


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _load_manifest_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_rc2_install_manifest",
        MANIFEST_HELPER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the install-manifest helper.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_script_helper(name: str, path: Path) -> ModuleType:
    scripts = str(ROOT / "scripts")
    inserted = scripts not in sys.path
    if inserted:
        sys.path.insert(0, scripts)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path.name}.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(scripts)


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = ["assert_hs8_release_candidate_manifest"]
