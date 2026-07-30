"""Static and pure-receipt coverage for the HS8 two-process CI gate."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

from tests.hocusscript_hs8_build_transaction_helpers import (
    assert_build_transaction_edges,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hocuspocus.hocusscript.build_comparison import (
    VisualComparison,
    compare_visual_baseline,
)
from hocuspocus.hocusscript.build_metrics import BuildMetrics, PlatformBudget
from hocuspocus.hocusscript.build_provenance import (
    canonical_digest,
    component_from_content,
    create_build_provenance,
)
from hocuspocus.live.context import RequestContext
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.production import ProductionOperationsMixin
from tests.hocusscript_hs8_asset_contract_helpers import _contract, _observation
from tests.hocusscript_hs8_release_authority_helpers import (
    _policy,
    _visual_approval,
)


ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = ROOT / "scripts" / "qualify_hocusscript_hs8_clean_process.py"
CLEAN_IMAGE = ROOT / "scripts" / "qualify_hocusscript_hs8_clean_image.py"


class _ProductionTools(OperationBaseMixin, ProductionOperationsMixin):
    pass


def assert_hs8_clean_process_orchestrator(testcase: Any) -> None:
    """Prove isolation/static limits and timing-independent receipt projection."""

    source = ORCHESTRATOR.read_text(encoding="utf-8")
    testcase.assertLessEqual(len(source.splitlines()), 1200)
    compile(source, str(ORCHESTRATOR), "exec")
    testcase.assertNotIn("dict(os.environ)", source)
    testcase.assertIn("same_host_clean_process", source)
    testcase.assertIn("hs8_install_manifest.py", source)
    testcase.assertIn('"releaseAuthorized": False', source)
    for environment_name in (
        "HOUDINI_USER_PREF_DIR", "HOUDINI_TEMP_DIR", "TEMP", "TMP",
        "PYTHONPYCACHEPREFIX", "XDG_CACHE_HOME", "HOUDINI_PACKAGE_DIR",
    ):
        testcase.assertIn(environment_name, source)
    testcase.assertIn("houdini__HVER__", source)
    harness_source = (
        ROOT / "scripts" / "smoke_hocusscript_hs8.py"
    ).read_text(encoding="utf-8")
    testcase.assertNotIn("HOCUSPOCUS_HS8_VISUAL_REVIEW_PATH", harness_source)
    testcase.assertNotIn("FIXTURE_ROOT / \"visual-review.json\"", harness_source)
    testcase.assertIn("HOCUSPOCUS_HS8_VISUAL_REVIEW_CONTENT", harness_source)
    testcase.assertIn("HOCUSPOCUS_HS8_VISUAL_REVIEW_DIGEST", harness_source)
    module = _load_orchestrator()
    _assert_installed_payload_preflight(testcase, module)
    _assert_detached_visual_review(testcase, module)
    _assert_child_process_lifecycle(testcase)
    _assert_retained_failure_evidence(testcase, module)
    _assert_build_transaction(testcase)
    _assert_clean_image_contract(testcase)
    first = _child_receipt(cook_duration_ms=100.0, mode="release")
    second = _child_receipt(cook_duration_ms=999.0, mode="release")
    first_projection, first_receipt = module.project_portable_receipt(
        first, mode="release",
    )
    second_projection, second_receipt = module.project_portable_receipt(
        second, mode="release",
    )
    testcase.assertEqual(
        first["productionQualification"]["authority"]["mode"],
        "content_only",
    )
    testcase.assertIsNone(first_receipt["attestationDigest"])
    testcase.assertNotIn("visualVersionReviewEvidence", first_projection)
    testcase.assertEqual(
        first_projection["visualVersionReviewEvidenceDigest"],
        first["productionQualification"]["buildReport"][
            "visualVersionReviewEvidenceDigest"
        ],
    )
    testcase.assertNotIn("hocus-principal://", json.dumps(first_projection))
    testcase.assertEqual(first_projection, second_projection)
    testcase.assertNotEqual(
        first_receipt["qualificationDigest"],
        second_receipt["qualificationDigest"],
    )
    testcase.assertEqual(
        first_receipt["attestationDigest"], second_receipt["attestationDigest"],
    )
    testcase.assertEqual(module._differing_fields(first_projection, second_projection), [])
    technical = _child_receipt(cook_duration_ms=100.0, mode="technical")
    technical_projection, technical_receipt = module.project_portable_receipt(
        technical, mode="technical",
    )
    testcase.assertEqual(
        technical_projection["reviewStatus"], "review_pending",
    )
    testcase.assertNotIn("visualVersionReviewEvidence", technical_projection)
    testcase.assertIsNone(technical_receipt["attestationDigest"])
    with testcase.assertRaises(module.CleanProcessQualificationError):
        module.project_portable_receipt(technical, mode="release")
    with testcase.assertRaises(module.CleanProcessQualificationError):
        module.project_portable_receipt(first, mode="technical")
    changed = dict(second_projection)
    changed["outputSetDigest"] = _digest(b"changed")
    testcase.assertEqual(
        module._differing_fields(first_projection, changed),
        ["outputSetDigest"],
    )
    malformed_attestation = copy.deepcopy(first)
    malformed_qualification = malformed_attestation["productionQualification"]
    malformed_qualification["authority"]["attestationDigest"] = "not-a-digest"
    malformed_qualification["qualificationDigest"] = module._canonical_digest({
        key: value
        for key, value in malformed_qualification.items()
        if key != "qualificationDigest"
    })
    with testcase.assertRaises(module.CleanProcessQualificationError):
        module.project_portable_receipt(
            malformed_attestation, mode="release",
        )
    incomplete_qualification = copy.deepcopy(first)
    incomplete_qualification["productionQualification"].pop(
        "qualificationDigest",
    )
    with testcase.assertRaises(module.CleanProcessQualificationError):
        module.project_portable_receipt(
            incomplete_qualification, mode="release",
        )
    with testcase.assertRaises(module.CleanProcessQualificationError):
        module._timeout(module.MAX_TIMEOUT_SECONDS + 1)


def _child_receipt(
    *,
    cook_duration_ms: float,
    mode: str,
) -> dict[str, Any]:
    contact = b"deterministic-contact-sheet"
    baseline = _manifest(contact)
    candidate = _manifest(contact)
    metrics = BuildMetrics(
        cook_duration_ms=cook_duration_ms,
        peak_memory_bytes=4096,
        polygon_count=128,
        texture_count=0,
        texture_bytes=0,
        output_bytes=(
            len(contact) + len(b"numeric-report") + len(b"usd-output")
        ),
    )
    budget = PlatformBudget(
        target_platform="houdini",
        max_cook_duration_ms=2000.0,
        max_peak_memory_bytes=8192,
        max_polygon_count=256,
        max_texture_count=0,
        max_texture_bytes=0,
        max_output_bytes=1024,
    )
    digest = _digest(b"artist")
    visual_comparison = VisualComparison(
        "hocus-output://hs8.fixture/contact-sheet.png",
        _digest(contact),
        _digest(contact),
        "exact-png-sha256",
        0.0,
        0.0,
    )
    visual = visual_comparison.to_dict()
    visual.pop("passed")
    review_evidence = {
        "kind": "hocus_visual_version_review_evidence",
        "reviewVersion": 1,
        "assetUri": candidate.to_dict()["assetUri"],
        "candidateProvenanceManifestDigest": candidate.manifest_digest,
        "candidateOutputSetDigest": candidate.output_set_digest,
        "visualComparisonDigest": canonical_digest(
            compare_visual_baseline((visual_comparison,)),
        ),
        "candidateVersionId": "rock-family-v1",
        "reviewPolicyId": "hs8-visual-review-v1",
        "reviewerPrincipalId": "hocus-principal://hs8-reviewer",
        "decision": "approved",
        "notesDigest": None,
    }
    evidence = {
        "contract": _contract(),
        "observation": _observation(),
        "baselineProvenance": baseline.to_dict(),
        "candidateProvenance": candidate.to_dict(),
        "metrics": metrics.to_dict(),
        "budget": budget.to_dict(),
        "numericBaseline": dict(metrics.to_dict()),
        "numericCandidate": dict(metrics.to_dict()),
        "numericTolerances": {
            key: 0 for key in metrics.to_dict()
        },
        "visualComparisons": [visual],
        "artistOverrideEvidence": {
            "kind": "artist_override_evidence",
            "protectedRegionCount": 1,
            "beforeDigest": digest,
            "afterDigest": digest,
            "passed": True,
        },
        "visualVersionReviewEvidence": (
            review_evidence if mode == "release" else None
        ),
    }
    operations = _ProductionTools()
    context = RequestContext(
        caller_id="hs8-clean-process",
        principal_id="hocus-principal://hs8-reviewer",
        session_id="hs8-clean-process-session",
        permissions=("observe",),
        metadata={
            "policy_revision": "hs8-ci-v1",
            "production_review_policy_id": "hs8-visual-review-v1",
        },
    )
    payload = operations.production_asset_qualify(
        dict(evidence), context,
    )["structuredContent"]
    observation_digest = _digest(b"production-observation")
    return {
        "accepted": True,
        "readyForPublish": False,
        "reviewStatus": (
            "approved" if mode == "release" else "review_pending"
        ),
        "installedAlignment": {
            "packageSearch": {
                "receiptDigest": _digest(b"effective-package-search"),
            },
            "modules": [{
                "module": "hocuspocus.hocusscript.production_pipeline",
                "relativePath": (
                    "python3.11libs/hocuspocus/hocusscript/"
                    "production_pipeline.py"
                ),
                "digest": _digest(b"installed-module"),
            }],
        },
        "observation": {"deterministicDigest": observation_digest},
        "cleanRebuild": {"observationDigest": observation_digest},
        "visualEvidence": {
            "contactSheet": {"digest": _digest(contact)},
        },
        "productionQualification": payload,
        "buildManifestDigest": candidate.manifest_digest,
        "contractDigest": payload["contractReport"]["contractDigest"],
    }


def _manifest(contact: bytes):
    outputs = {
        "contact-sheet.png": contact,
        "numeric-report.json": b"numeric-report",
        "rock-family.usda": b"usd-output",
    }
    return create_build_provenance(
        asset_uri="hocus-asset://hs8.fixture/rock-family",
        target_platform="houdini",
        recipe=component_from_content(
            "recipe", "hocus-recipe://hs8.fixture/production-v1", b"recipe",
        ),
        sources=(
            component_from_content(
                "source", "hocus-project://hs8.fixture/rock.hocus", b"source",
            ),
        ),
        compiler=component_from_content(
            "compiler", "hocus-compiler://hs8.fixture/installed",
            b"compiler", version="0.9.0",
        ),
        catalog=component_from_content(
            "catalog", "hocus-catalog://hs8.fixture/live-v2",
            b"catalog", fingerprint=_digest(b"catalog"),
        ),
        modules=(
            component_from_content(
                "module", "hocus-module://hs8.fixture/runtime", b"module",
            ),
        ),
        hdas=(
            component_from_content(
                "hda", "hocus-hda://hs8.fixture/rock", b"hda",
            ),
        ),
        inputs=(
            component_from_content(
                "input", "hocus-input://hs8.fixture/seed", b"input",
            ),
        ),
        outputs=tuple(
            component_from_content(
                "output", f"hocus-output://hs8.fixture/{name}", content,
                role=name, media_type=(
                    "image/png" if name.endswith(".png")
                    else "model/vnd.usd" if name.endswith(".usda")
                    else "application/json"
                ),
            )
            for name, content in sorted(outputs.items())
        ),
    )


def _load_orchestrator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hocuspocus_hs8_clean_process_orchestrator",
        ORCHESTRATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load HS8 clean-process orchestrator.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_installed_payload_preflight(
    testcase: Any,
    module: ModuleType,
) -> None:
    with tempfile.TemporaryDirectory(prefix="hs8-installed-payload-") as value:
        installed = Path(value)
        helper = _load_module(
            "hocuspocus_hs8_manifest_test",
            ROOT / "scripts" / "hs8_install_manifest.py",
        )
        output_guard = _load_module(
            "hocuspocus_hs8_output_guard_test",
            ROOT / "scripts" / "hs8_output_guard.py",
        )
        output_test = installed / "output-test"
        output_test.mkdir()
        output_source = output_test / "source.bin"
        output_target = output_test / "target.bin"
        output_source.write_bytes(b"candidate")
        testcase.assertEqual(
            output_guard.copy_exclusive(
                output_source, output_target, max_bytes=1024,
            ),
            len(b"candidate"),
        )
        with testcase.assertRaises(output_guard.OutputGuardError):
            output_guard.copy_exclusive(
                output_source, output_target, max_bytes=1024,
            )
        testcase.assertEqual(
            output_guard.copy_exclusive_or_identical(
                output_source, output_target, max_bytes=1024,
            ),
            len(b"candidate"),
        )
        output_source.write_bytes(b"different")
        with testcase.assertRaises(output_guard.OutputGuardError):
            output_guard.copy_exclusive_or_identical(
                output_source, output_target, max_bytes=1024,
        )
        testcase.assertEqual(output_target.read_bytes(), b"candidate")
        for relative in helper.GOVERNED_ROOTS:
            shutil.copytree(ROOT / relative, installed / relative)
        _remove_python_bytecode(installed)
        helper.write_manifest(installed)
        with testcase.assertRaises(helper.InstallManifestError):
            helper.audit_loaded_modules(
                installed,
                {"hocuspocus.fileless": ModuleType("hocuspocus.fileless")},
            )
        receipt = module._verify_installed_payload(ROOT, installed)
        testcase.assertEqual(
            receipt["artifactCount"], len(helper.create_manifest(ROOT)["files"]),
        )
        testcase.assertRegex(
            receipt["manifestDigest"], r"^sha256:[0-9a-f]{64}$",
        )
        bytecode = installed / "python3.11libs/hocuspocus/undeclared.pyc"
        bytecode.write_bytes(b"not governed")
        with testcase.assertRaises(helper.InstallManifestError):
            helper.verify_manifest(installed)
        bytecode.unlink()
        helper.verify_manifest(installed)
        stale = installed / "python3.11libs/hocuspocus/live/catalog_provider.py"
        stale.write_bytes(stale.read_bytes() + b"\n# stale\n")
        with testcase.assertRaises(module.CleanProcessQualificationError):
            module._verify_installed_payload(ROOT, installed)
        packages = installed / "active-pointer"
        version = packages / "HocusPocus.0123456789ab.01234567"
        version.mkdir(parents=True)
        package_file = packages / "hocuspocus.json"
        canonical_pointer = _package_pointer(
            "HocusPocus.0123456789ab.01234567",
        )
        package_file.write_text(
            json.dumps(canonical_pointer),
            encoding="utf-8",
        )
        testcase.assertEqual(module._active_package_root(package_file), version)
        conditioned_pointer = copy.deepcopy(canonical_pointer)
        conditioned_pointer["enable"] = False
        package_file.write_text(json.dumps(conditioned_pointer), encoding="utf-8")
        with testcase.assertRaises(module.CleanProcessQualificationError):
            module._active_package_root(package_file)
        shadowed_pointer = copy.deepcopy(canonical_pointer)
        shadowed_pointer["env"].insert(1, {
            "PYTHONPATH": {"method": "prepend", "value": "C:/shadow"},
        })
        package_file.write_text(json.dumps(shadowed_pointer), encoding="utf-8")
        with testcase.assertRaises(module.CleanProcessQualificationError):
            module._active_package_root(package_file)
        reordered_pointer = copy.deepcopy(canonical_pointer)
        reordered_pointer["env"].reverse()
        package_file.write_text(json.dumps(reordered_pointer), encoding="utf-8")
        with testcase.assertRaises(module.CleanProcessQualificationError):
            module._active_package_root(package_file)
        package_file.write_text(
            json.dumps(_package_pointer("HocusPocus.aaaaaaaaaaaa.aaaaaaaa")),
            encoding="utf-8",
        )
        testcase.assertNotEqual(module._active_package_root(package_file), version)
        technical_environment = module._isolated_environment(
            installed,
            installed / "technical-run",
            mode="technical",
            visual_review=None,
        )
        release_environment = module._isolated_environment(
            installed,
            installed / "release-run",
            mode="release",
            visual_review=None,
        )
        testcase.assertIn(
            "HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT", technical_environment,
        )
        testcase.assertNotIn(
            "HOCUSPOCUS_HS8_DIAGNOSTIC_OUTPUT_ROOT", release_environment,
        )


def _assert_detached_visual_review(
    testcase: Any,
    module: ModuleType,
) -> None:
    manifest_helper = _load_module(
        "hocuspocus_hs8_detached_review_manifest",
        ROOT / "scripts" / "hs8_install_manifest.py",
    )
    review_helper = module._visual_review_helper()
    source_before = manifest_helper.create_manifest(ROOT)
    testcase.assertFalse(
        (ROOT / "scripts/fixtures/hs8/visual-review.json").exists()
    )
    with tempfile.TemporaryDirectory(prefix="hs8-detached-review-") as value:
        root = Path(value)
        installed = root / "installed"
        for relative in manifest_helper.GOVERNED_ROOTS:
            shutil.copytree(ROOT / relative, installed / relative)
        manifest_helper.write_manifest(installed)
        installed_before = manifest_helper.create_manifest(installed)
        request = json.loads((
            installed / review_helper.REQUEST_RELATIVE_PATH
        ).read_text(encoding="utf-8"))
        review = {
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
        policy = _policy(
            Ed25519PrivateKey.generate(),
            visual_key := Ed25519PrivateKey.generate(),
            Ed25519PrivateKey.generate(),
        )
        approval = _visual_approval(policy, request, review, visual_key)
        external = root / "external-visual-review.json"
        external.write_text(json.dumps(approval), encoding="utf-8")
        policy_path = root / "external-trust-policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        payload = review_helper.select_detached_visual_review(
            external,
            trust_policy=policy_path,
            installed_root=installed,
            source_root=ROOT,
            mode="release",
        )
        testcase.assertEqual(json.loads(payload["content"]), review)
        testcase.assertRegex(payload["digest"], r"^sha256:[0-9a-f]{64}$")
        testcase.assertNotIn(str(external), json.dumps(payload))
        environment = module._isolated_environment(
            installed,
            root / "release-run",
            mode="release",
            visual_review=payload,
        )
        testcase.assertEqual(
            environment["HOCUSPOCUS_HS8_VISUAL_REVIEW_DIGEST"],
            payload["digest"],
        )
        testcase.assertNotIn("HOCUSPOCUS_HS8_VISUAL_REVIEW_PATH", environment)
        with testcase.assertRaises(review_helper.VisualReviewError):
            review_helper.select_detached_visual_review(
                external,
                trust_policy=policy_path,
                installed_root=installed,
                source_root=ROOT,
                mode="technical",
            )
        with testcase.assertRaises(review_helper.VisualReviewError):
            review_helper.select_detached_visual_review(
                None,
                trust_policy=policy_path,
                installed_root=installed,
                source_root=ROOT,
                mode="release",
            )
        mismatched = copy.deepcopy(approval)
        mismatched["payload"]["reviewEvidence"][
            "candidateOutputSetDigest"
        ] = _digest(b"wrong-output")
        external.write_text(json.dumps(mismatched), encoding="utf-8")
        with testcase.assertRaises(review_helper.VisualReviewError):
            review_helper.select_detached_visual_review(
                external,
                trust_policy=policy_path,
                installed_root=installed,
                source_root=ROOT,
                mode="release",
            )
        testcase.assertEqual(
            manifest_helper.create_manifest(installed),
            installed_before,
        )
    testcase.assertEqual(manifest_helper.create_manifest(ROOT), source_before)


def _assert_build_transaction(testcase: Any) -> None:
    build = ROOT / "scripts" / "build.ps1"
    protected = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(build), "-Clean", "-OutputDir", str(ROOT),
            "-PythonExe", sys.executable,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    testcase.assertNotEqual(protected.returncode, 0)
    testcase.assertIn("protected", protected.stderr + protected.stdout)
    with tempfile.TemporaryDirectory(prefix="hs8-build-transaction-") as value:
        root = Path(value)
        source = root / "source"
        helper = _load_module(
            "hocuspocus_hs8_manifest_build_test",
            ROOT / "scripts" / "hs8_install_manifest.py",
        )
        for relative in helper.GOVERNED_ROOTS:
            shutil.copytree(ROOT / relative, source / relative)
        build = source / "scripts" / "build.ps1"
        output = root / "output"
        preferences = root / "houdini"
        command = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(build),
            "-OutputDir", str(output),
            "-HoudiniUserPrefDir", str(preferences),
            "-PythonExe", sys.executable,
            "-Install", "-SkipUserEnvironment",
        ]
        first = subprocess.run(
            [*command, "-Clean"],
            cwd=source, capture_output=True, text=True,
            timeout=120, check=False,
        )
        testcase.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        package = preferences / "packages" / "hocuspocus.json"
        first_package = package.read_bytes()
        first_config = _active_config(preferences, first_package)
        first_token = _configured_token(first_config)
        installed_root = first_config.parents[1]
        testcase.assertFalse(_python_bytecode(output / "HocusPocus"))
        testcase.assertFalse(_python_bytecode(installed_root))
        undeclared = installed_root / "python3.11libs/hocuspocus/undeclared.pyc"
        undeclared.write_bytes(b"not governed")
        with testcase.assertRaises(helper.InstallManifestError):
            helper.verify_manifest(installed_root)
        undeclared.unlink()
        helper.verify_manifest(installed_root)
        staged_pointer = output / "hocuspocus.json"
        pointer_victim = root / "package-pointer-victim.txt"
        pointer_victim.write_text("must survive", encoding="utf-8")
        staged_pointer.unlink()
        try:
            os.link(pointer_victim, staged_pointer)
        except OSError:
            with testcase.subTest(package_pointer_hardlink_supported=False):
                pass
        second = subprocess.run(
            command, cwd=source, capture_output=True, text=True,
            timeout=120, check=False,
        )
        testcase.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        testcase.assertEqual(
            pointer_victim.read_text(encoding="utf-8"),
            "must survive",
        )
        testcase.assertFalse(os.path.samefile(pointer_victim, staged_pointer))
        testcase.assertEqual(package.read_bytes(), first_package)
        testcase.assertEqual(
            _configured_token(_active_config(preferences, package.read_bytes())),
            first_token,
        )
        assert_build_transaction_edges(
            testcase, command=command, source=source, root=root,
        )
        staging = output / "HocusPocus"
        shutil.rmtree(staging)
        junction_target = root / "junction-target"
        junction_target.mkdir()
        sentinel = junction_target / "must-survive.txt"
        sentinel.write_text("protected", encoding="utf-8")
        _create_directory_link(testcase, staging, junction_target)
        rejected_clean = subprocess.run(
            [*command, "-Clean"],
            cwd=source, capture_output=True, text=True,
            timeout=120, check=False,
        )
        testcase.assertNotEqual(rejected_clean.returncode, 0)
        testcase.assertIn(
            "reparse point",
            (rejected_clean.stdout + rejected_clean.stderr).casefold(),
        )
        testcase.assertEqual(sentinel.read_text(encoding="utf-8"), "protected")
        ancestor_target = root / "ancestor-target"
        ancestor_target.mkdir()
        ancestor_link = root / "ancestor-link"
        _create_directory_link(testcase, ancestor_link, ancestor_target)
        unsafe_output = list(command)
        unsafe_output[unsafe_output.index("-OutputDir") + 1] = str(
            ancestor_link / "nested",
        )
        rejected_ancestor = subprocess.run(
            unsafe_output,
            cwd=source, capture_output=True, text=True,
            timeout=30, check=False,
        )
        testcase.assertNotEqual(rejected_ancestor.returncode, 0)
        testcase.assertIn(
            "reparse point",
            (rejected_ancestor.stdout + rejected_ancestor.stderr).casefold(),
        )
        testcase.assertFalse((ancestor_target / "nested").exists())
        _assert_concurrent_build_install(
            testcase, command, source, root, helper,
        )


def _assert_concurrent_build_install(
    testcase: Any,
    command: list[str],
    source: Path,
    root: Path,
    manifest_helper: ModuleType,
) -> None:
    preferences = root / "concurrent-houdini"
    processes = []
    for ordinal in (1, 2):
        selected = list(command)
        selected[selected.index("-OutputDir") + 1] = str(
            root / f"concurrent-output-{ordinal}",
        )
        selected[selected.index("-HoudiniUserPrefDir") + 1] = str(preferences)
        processes.append(subprocess.Popen(
            selected,
            cwd=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ))
    results = [process.communicate(timeout=180) for process in processes]
    for process, (stdout, stderr) in zip(processes, results, strict=True):
        testcase.assertEqual(process.returncode, 0, stderr + stdout)
    package = preferences / "packages" / "hocuspocus.json"
    installed_root = _active_config(preferences, package.read_bytes()).parents[1]
    manifest_helper.verify_manifest(installed_root)
    testcase.assertFalse(
        any(
            path.name.startswith((
                ".HocusPocus.install.",
                ".hocuspocus.json.candidate.",
                "hocuspocus.json.backup.",
                "hocuspocus.json.failed.",
            ))
            for path in (preferences / "packages").iterdir()
        ),
    )


def _assert_child_process_lifecycle(testcase: Any) -> None:
    helper = _load_module(
        "hocuspocus_hs8_child_process_test",
        ROOT / "scripts" / "hs8_child_process.py",
    )
    source = (ROOT / "scripts" / "hs8_child_process.py").read_text(
        encoding="utf-8",
    )
    testcase.assertIn("CREATE_SUSPENDED", source)
    testcase.assertLess(
        source.index("_WindowsJob.assign(process)"),
        source.index("_resume_windows_process(process)"),
    )
    with tempfile.TemporaryDirectory(prefix="hs8-child-lifecycle-") as value:
        run_root = Path(value)
        parent_pid = run_root / "parent.pid"
        child_pid = run_root / "child.pid"
        grandchild = (
            "import os,time,pathlib;"
            f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()));"
            "time.sleep(60)"
        )
        parent = (
            "import os,subprocess,sys,time,pathlib;"
            f"pathlib.Path({str(parent_pid)!r}).write_text(str(os.getpid()));"
            f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]);"
            "time.sleep(60)"
        )
        with testcase.assertRaisesRegex(
            helper.ChildProcessError, "timeout",
        ):
            helper.run_child(
                [sys.executable, "-c", parent],
                cwd=ROOT,
                environment=os.environ,
                run_root=run_root,
                timeout_seconds=1.0,
                max_stdout_bytes=1024,
                max_stderr_bytes=1024,
            )
        testcase.assertLessEqual((run_root / "stdout.json").stat().st_size, 1024)
        testcase.assertLessEqual((run_root / "stderr.log").stat().st_size, 1024)
        testcase.assertFalse(_process_exists(int(parent_pid.read_text())))
        testcase.assertFalse(_process_exists(int(child_pid.read_text())))
    with tempfile.TemporaryDirectory(prefix="hs8-child-output-") as value:
        run_root = Path(value)
        with testcase.assertRaisesRegex(
            helper.ChildProcessError, "output limit",
        ):
            helper.run_child(
                [
                    sys.executable, "-c",
                    "import sys,time;sys.stdout.write('x'*8192);"
                    "sys.stdout.flush();time.sleep(60)",
                ],
                cwd=ROOT,
                environment=os.environ,
                run_root=run_root,
                timeout_seconds=5.0,
                max_stdout_bytes=1024,
                max_stderr_bytes=1024,
            )
        testcase.assertLessEqual((run_root / "stdout.json").stat().st_size, 1024)
        testcase.assertLessEqual((run_root / "stderr.log").stat().st_size, 1024)
    with tempfile.TemporaryDirectory(prefix="hs8-child-exited-parent-") as value:
        run_root = Path(value)
        child_pid = run_root / "child.pid"
        grandchild = (
            "import os,time,pathlib;"
            f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()));"
            "time.sleep(60)"
        )
        parent = (
            "import subprocess,sys,time,pathlib;"
            f"pid_path=pathlib.Path({str(child_pid)!r});"
            f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]);"
            "deadline=time.monotonic()+2;"
            "\nwhile not pid_path.exists() and time.monotonic()<deadline: time.sleep(.01);"
            "\nprint('{}')"
        )
        result = helper.run_child(
            [sys.executable, "-c", parent],
            cwd=ROOT,
            environment=os.environ,
            run_root=run_root,
            timeout_seconds=5.0,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
        )
        testcase.assertEqual(result.returncode, 0, result.stderr)
        testcase.assertTrue(child_pid.is_file())
        testcase.assertFalse(_process_exists(int(child_pid.read_text())))


def _assert_retained_failure_evidence(
    testcase: Any,
    module: ModuleType,
) -> None:
    with tempfile.TemporaryDirectory(prefix="hs8-failure-evidence-") as value:
        root = Path(value)
        run = root / "run-1"
        run.mkdir()
        (run / "stdout.json").write_bytes(b"s" * (2 * 1024 * 1024))
        (run / "stderr.log").write_bytes(b"e" * (2 * 1024 * 1024))
        diagnostics = run / "diagnostics"
        diagnostics.mkdir()
        stage = diagnostics / "first-rock-family.usda"
        stage.write_bytes(b"#usda 1.0\n")
        secondary = diagnostics / "failure-evidence-diagnostic.json"
        secondary.write_bytes(b'{"code":"HS8_DIAGNOSTIC_PRESERVATION_FAILED"}\n')
        junk = root / "unbounded-cache.bin"
        junk.write_bytes(b"j" * (6 * 1024 * 1024))
        error = module.CleanProcessQualificationError("HOCUS991", "x" * 10_000)
        module._retain_failure_evidence(root, error)
        evidence = (root / "failure.json").read_bytes()
        testcase.assertLessEqual(len(evidence), 5 * 1024)
        testcase.assertIn(f"Failure evidence retained at {root}.", str(error))
        testcase.assertEqual(
            json.loads(evidence)["message"], "x" * 4096,
        )
        testcase.assertFalse(junk.exists())
        testcase.assertEqual(
            (root / "run-1/diagnostics/first-rock-family.usda").read_bytes(),
            b"#usda 1.0\n",
        )
        testcase.assertEqual(
            (
                root
                / "run-1/diagnostics/failure-evidence-diagnostic.json"
            ).read_bytes(),
            b'{"code":"HS8_DIAGNOSTIC_PRESERVATION_FAILED"}\n',
        )
        testcase.assertLessEqual(
            sum(
                path.stat().st_size
                for path in root.rglob("*")
                if path.is_file()
            ),
            module.MAX_RETAINED_EVIDENCE_BYTES,
        )
        retained = {
            row["relativePath"]: row
            for row in json.loads(evidence)["retainedFiles"]
        }
        testcase.assertTrue(retained["run-1/stdout.json"]["truncated"])
        testcase.assertTrue(retained["run-1/stderr.log"]["truncated"])
        testcase.assertFalse(
            retained["run-1/diagnostics/first-rock-family.usda"]["truncated"],
        )


def _process_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
                "{ exit 0 } else { exit 1 }",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _python_bytecode(root: Path) -> list[Path]:
    return [
        path for path in root.rglob("*")
        if path.name == "__pycache__"
        or path.suffix.casefold() in {".pyc", ".pyo"}
    ]


def _remove_python_bytecode(root: Path) -> None:
    for path in _python_bytecode(root):
        if path.is_file():
            path.unlink()
    caches = sorted(
        (path for path in root.rglob("__pycache__") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for cache in caches:
        shutil.rmtree(cache)


def _create_directory_link(testcase: Any, link: Path, target: Path) -> None:
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    junction = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            (
                "& { param($link,$target) "
                "New-Item -ItemType Junction -Path $link -Target $target "
                "| Out-Null }"
            ),
            str(link), str(target),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    testcase.assertEqual(junction.returncode, 0, junction.stderr)


def _active_config(preferences: Path, package: bytes) -> Path:
    match = re.search(rb"HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}", package)
    if match is None:
        raise AssertionError("Versioned package root is absent.")
    return (
        preferences / "packages" / match.group().decode()
        / "config" / "default.toml"
    )


def _package_pointer(root_name: str) -> dict[str, Any]:
    return {
        "env": [
            {
                "HOCUSPOCUS_ROOT": (
                    f"$HOUDINI_PACKAGE_PATH/{root_name}"
                ),
            },
            {
                "PYTHONPATH": {
                    "method": "prepend",
                    "value": "$HOCUSPOCUS_ROOT/python3.11libs",
                },
            },
        ],
        "hpath": "$HOCUSPOCUS_ROOT",
    }


def _configured_token(path: Path) -> str:
    match = re.search(
        r'(?m)^token\s*=\s*"([A-Za-z0-9_-]{32,128})"\s*$',
        path.read_text(encoding="utf-8"),
    )
    if match is None:
        raise AssertionError("Installed token is absent.")
    return match.group(1)


def _assert_clean_image_contract(testcase: Any) -> None:
    source = CLEAN_IMAGE.read_text(encoding="utf-8")
    testcase.assertLessEqual(len(source.splitlines()), 1200)
    compile(source, str(CLEAN_IMAGE), "exec")
    module = _load_module("hocuspocus_hs8_clean_image_contract", CLEAN_IMAGE)
    digest = _digest(b"clean-image")
    unsigned = {
        "$schema": module.ENVIRONMENT_SCHEMA,
        "kind": "hocus_hs8_clean_image_environment",
        "schemaVersion": 1,
        "isolationBoundary": "clean_image_or_vm",
        "ephemeral": True,
        "imageDigest": digest,
        "runnerDigest": digest,
        "sourceSnapshotDigest": digest,
        "installedPayloadManifestDigest": digest,
    }
    receipt = {
        **unsigned,
        "receiptDigest": module._canonical_digest(unsigned),
    }
    testcase.assertEqual(
        module._normalize_environment_receipt(receipt), receipt,
    )
    testcase.assertIn("HOCUSPOCUS_HS8_CLEAN_IMAGE", source)
    same_host = {
        "qualificationMode": "release",
        "releaseAuthorized": True,
        "receiptDigest": digest,
        "visualReviewEvidenceDigest": digest,
        "visualApprovalDigest": digest,
        "installedPayload": {"manifestDigest": digest},
    }
    forwarded = {}

    def qualify(**kwargs):
        forwarded.update(kwargs)
        return same_host

    qualifier = type("_Qualifier", (), {
        "CleanProcessQualificationError": RuntimeError,
        "qualify_two_clean_processes": staticmethod(qualify),
    })
    with tempfile.TemporaryDirectory(prefix="hs8-clean-image-receipt-") as value:
        receipt_path = Path(value) / "environment.json"
        receipt_path.write_text(
            json.dumps(receipt), encoding="utf-8",
        )
        review_path = Path(value) / "external-review.json"
        review_path.write_text("{}", encoding="utf-8")
        with (
            mock.patch.dict(
                os.environ, {"HOCUSPOCUS_HS8_CLEAN_IMAGE": "1"},
            ),
            mock.patch.object(
                module, "_same_host_qualifier", return_value=qualifier,
            ),
        ):
            evidence_only = module.qualify_clean_image(
                environment_receipt_path=receipt_path,
                hython=Path("unused-hython"),
                installed_root=Path("unused-install"),
                harness=None,
                mode="release",
                timeout_seconds=1.0,
                temporary_parent=None,
                visual_review=review_path,
                trust_policy=review_path,
            )
    testcase.assertTrue(evidence_only["passed"])
    testcase.assertEqual(
        evidence_only["isolationBoundary"],
        "caller_declared_clean_image_or_vm",
    )
    testcase.assertFalse(evidence_only["releaseAuthorized"])
    testcase.assertEqual(evidence_only["visualReviewEvidenceDigest"], digest)
    testcase.assertEqual(forwarded["visual_review"], review_path)
    schema = json.loads((
        ROOT / "docs" / "schemas"
        / "hs8-clean-image-environment-v1.schema.json"
    ).read_text(encoding="utf-8"))
    testcase.assertEqual(schema["$id"], module.ENVIRONMENT_SCHEMA)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


__all__ = ["assert_hs8_clean_process_orchestrator"]
