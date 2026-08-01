"""Private hostile schedules for the HS8 build/install transaction."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Iterator


def assert_build_transaction_edges(
    testcase: Any,
    *,
    command: list[str],
    source: Path,
    root: Path,
) -> None:
    """Exercise the five transaction-authority regressions."""

    _assert_output_lock_through_install_snapshot(
        testcase, command, source, root,
    )
    _assert_manifest_identity_idempotent_recovery(
        testcase, command, source, root,
    )
    _assert_package_pointer_identity_digest_cas(
        testcase, command, source, root,
    )
    _assert_complete_dpapi_journal_and_authority_root(
        testcase, command, source, root,
    )
    _assert_cleanup_preserves_transaction_outcome(
        testcase, command, source, root,
    )


def _assert_output_lock_through_install_snapshot(
    testcase: Any,
    command: list[str],
    source: Path,
    root: Path,
) -> None:
    transaction = source / "scripts/build_transaction.ps1"
    hook = root / "install-snapshot-hook"
    governed = source / "python3.11libs/hocuspocus/__init__.py"
    original_governed = governed.read_bytes()
    marker = b"\n# output-lock-install-snapshot-probe\n"
    anchor = "            Copy-Item -LiteralPath $StagedRoot `"
    injection = (
        "            [System.IO.File]::WriteAllText("
        f"'{hook}.entered', 'entered')\n"
        f"            while (-not (Test-Path -LiteralPath '{hook}.release')) {{\n"
        "                Start-Sleep -Milliseconds 20\n"
        "            }\n"
        + anchor
    )
    with _patched(transaction, anchor, injection):
        first = subprocess.Popen(
            command,
            cwd=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _wait_for(testcase, Path(f"{hook}.entered"), first)
            governed.write_bytes(original_governed + marker)
            build_only = [item for item in command if item != "-Install"]
            second = subprocess.Popen(
                build_only,
                cwd=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.4)
            testcase.assertIsNone(
                second.poll(),
                "A build overtook the install snapshot under the output lock.",
            )
            Path(f"{hook}.release").write_text("release", encoding="utf-8")
            first_out, first_err = first.communicate(timeout=240)
            second_out, second_err = second.communicate(timeout=240)
            testcase.assertEqual(
                first.returncode, 0, first_err + first_out,
            )
            testcase.assertEqual(
                second.returncode, 0, second_err + second_out,
            )
            installed = _active_root(command)
            relative = governed.relative_to(source)
            testcase.assertNotIn(marker, (installed / relative).read_bytes())
            output = _output(command)
            testcase.assertIn(
                marker, (output / "HocusPocus" / relative).read_bytes(),
            )
        finally:
            governed.write_bytes(original_governed)
            if first.poll() is None:
                Path(f"{hook}.release").write_text("release", encoding="utf-8")
                first.kill()
                first.communicate(timeout=30)


def _assert_manifest_identity_idempotent_recovery(
    testcase: Any,
    command: list[str],
    source: Path,
    root: Path,
) -> None:
    transaction = source / "scripts/build_transaction.ps1"
    hook = root / "output-recovery-hook"
    anchor = (
        "        Move-Item -LiteralPath $candidate -Destination $ActiveTree"
    )
    injection = (
        anchor
        + "\n        [System.IO.File]::WriteAllText("
        + f"'{hook}.entered', 'entered')"
        + f"\n        while (-not (Test-Path -LiteralPath '{hook}.release')) {{"
        + "\n            Start-Sleep -Milliseconds 20\n        }"
    )
    build_only = [item for item in command if item != "-Install"]
    with _patched(transaction, anchor, injection):
        killed = subprocess.Popen(
            build_only,
            cwd=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for(testcase, Path(f"{hook}.entered"), killed)
        killed.kill()
        killed.communicate(timeout=30)
    output = _output(command)
    journal = output / ".hocuspocus-output-transaction.json"
    testcase.assertTrue(journal.is_file())
    active = output / "HocusPocus"
    config = active / "config/default.toml"
    manifest = active / "package/install-manifest-v1.json"
    original_config = config.read_bytes()
    original_manifest = manifest.read_bytes()
    config.write_bytes(original_config + b"\n# identity-tamper\n")
    create = subprocess.run(
        [
            os.fspath(Path(sys.executable)),
            os.fspath(source / "scripts/hs8_install_manifest.py"),
            "create",
            "--root",
            os.fspath(active),
        ],
        cwd=source,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    testcase.assertEqual(create.returncode, 0, create.stderr + create.stdout)
    rejected = _run(build_only, source)
    testcase.assertNotEqual(rejected.returncode, 0)
    testcase.assertTrue(journal.is_file())
    config.write_bytes(original_config)
    manifest.write_bytes(original_manifest)
    recovered = _run(build_only, source)
    testcase.assertEqual(
        recovered.returncode, 0, recovered.stderr + recovered.stdout,
    )
    first_manifest = manifest.read_bytes()
    first_digest = _manifest_digest(manifest)
    replayed = _run(build_only, source)
    testcase.assertEqual(
        replayed.returncode, 0, replayed.stderr + replayed.stdout,
    )
    testcase.assertEqual(manifest.read_bytes(), first_manifest)
    testcase.assertEqual(_manifest_digest(manifest), first_digest)
    testcase.assertFalse(journal.exists())


def _assert_package_pointer_identity_digest_cas(
    testcase: Any,
    command: list[str],
    source: Path,
    root: Path,
) -> None:
    output = _output(command)
    pointer = output / "hocuspocus.json"
    authority_link = root / "captured-pointer-authority.json"
    if authority_link.exists():
        authority_link.unlink()
    os.link(pointer, authority_link)
    transaction = source / "scripts/build_transaction.ps1"
    hook = root / "pointer-cas-hook"
    anchor = (
        "    Publish-PackageCandidate `\n"
        "        -Path $ActivePointer -Candidate $pointerCandidate `"
    )
    injection = (
        "    [System.IO.File]::WriteAllText("
        f"'{hook}.entered', 'entered')\n"
        f"    while (-not (Test-Path -LiteralPath '{hook}.release')) {{\n"
        "        Start-Sleep -Milliseconds 20\n"
        "    }\n"
        + anchor
    )
    build_only = [item for item in command if item != "-Install"]
    with _patched(transaction, anchor, injection):
        process = subprocess.Popen(
            build_only,
            cwd=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for(testcase, Path(f"{hook}.entered"), process)
        exact_bytes = pointer.read_bytes()
        pointer.unlink()
        pointer.write_bytes(exact_bytes)
        competitor_identity = os.stat(pointer).st_ino
        Path(f"{hook}.release").write_text("release", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=240)
    testcase.assertNotEqual(process.returncode, 0, stderr + stdout)
    testcase.assertEqual(pointer.read_bytes(), exact_bytes)
    testcase.assertEqual(os.stat(pointer).st_ino, competitor_identity)
    testcase.assertFalse(os.path.samefile(pointer, authority_link))
    pointer.unlink()
    os.link(authority_link, pointer)
    recovered = _run(build_only, source)
    testcase.assertEqual(
        recovered.returncode, 0, recovered.stderr + recovered.stdout,
    )


def _assert_complete_dpapi_journal_and_authority_root(
    testcase: Any,
    command: list[str],
    source: Path,
    root: Path,
) -> None:
    authority = root / "complete-token-authority"
    environment = _authority_environment(authority)
    transaction = source / "scripts/build_transaction.ps1"
    hook = root / "token-journal-hook"
    anchor = (
        "            Write-TokenJournal `\n"
        "                -Path $tokenJournal -AuthorityRoot $AuthorityRoot `\n"
        "                -Envelope $envelope\n"
        "            $journalWritten = $true"
    )
    injection = (
        anchor
        + "\n            [System.IO.File]::WriteAllText("
        + f"'{hook}.entered', 'entered')"
        + f"\n            while (-not (Test-Path -LiteralPath '{hook}.release')) {{"
        + "\n                Start-Sleep -Milliseconds 20\n            }"
    )
    with _patched(transaction, anchor, injection):
        rotating = subprocess.Popen(
            [*command, "-RotateToken"],
            cwd=source,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for(testcase, Path(f"{hook}.entered"), rotating)
        journal = authority / "token-activation.json"
        raw = journal.read_bytes()
        versions = [
            path
            for path in (_preferences(command) / "packages").iterdir()
            if path.is_dir() and path.name.startswith("HocusPocus.")
        ]
        newest = max(versions, key=lambda path: path.stat().st_mtime_ns)
        token = _configured_token(newest / "config/default.toml")
        testcase.assertNotIn(token.encode(), raw)
        testcase.assertNotIn(os.fspath(newest).encode(), raw)
        rotating.kill()
        rotating.communicate(timeout=30)
    outer = json.loads(raw)
    testcase.assertEqual(set(outer), {"schemaVersion", "protectedEnvelope"})
    outer["unexpectedAuthority"] = "rejected"
    journal.write_text(json.dumps(outer), encoding="utf-8")
    rejected = _run(command, source, environment)
    testcase.assertNotEqual(rejected.returncode, 0)
    testcase.assertTrue(journal.is_file())
    journal.write_bytes(raw)
    recovered = _run(command, source, environment)
    testcase.assertEqual(
        recovered.returncode, 0, recovered.stderr + recovered.stdout,
    )
    testcase.assertFalse(journal.exists())

    sentinel = root / "authority-overlap-victim.txt"
    sentinel.write_text("survive", encoding="utf-8")
    for protected in (source, _output(command), _preferences(command)):
        rejected_environment = _authority_environment(protected)
        attempt = _run(command, source, rejected_environment)
        testcase.assertNotEqual(attempt.returncode, 0)
        testcase.assertIn(
            "overlaps a protected path",
            (attempt.stderr + attempt.stdout).casefold(),
        )
        testcase.assertEqual(sentinel.read_text(encoding="utf-8"), "survive")

    junction_target = root / "authority-junction-target"
    junction_target.mkdir()
    junction = root / "authority-junction"
    _create_junction(testcase, junction, junction_target)
    rejected_environment = _authority_environment(junction)
    attempt = _run(command, source, rejected_environment)
    testcase.assertNotEqual(attempt.returncode, 0)
    testcase.assertIn(
        "reparse point", (attempt.stderr + attempt.stdout).casefold(),
    )
    testcase.assertEqual(sentinel.read_text(encoding="utf-8"), "survive")


def _assert_cleanup_preserves_transaction_outcome(
    testcase: Any,
    command: list[str],
    source: Path,
    root: Path,
) -> None:
    output = _output(command)
    active = output / "HocusPocus"
    sentinel = active / "config/default.toml"
    governed = source / "python3.11libs/hocuspocus/__init__.py"
    original_governed = governed.read_bytes()
    governed.write_bytes(
        original_governed + b"\n# committed-cleanup-probe\n",
    )
    transaction = source / "scripts/build_transaction.ps1"
    anchor = '$State.phase = "committed"'
    hook = root / "committed-cleanup-hook"
    injection = (
        anchor
        + "\n    [System.IO.File]::WriteAllText("
        + f"'{hook}.entered', 'entered')"
        + f"\n    while (-not (Test-Path -LiteralPath '{hook}.release')) {{"
        + "\n        Start-Sleep -Milliseconds 20\n    }"
    )
    build_only = [item for item in command if item != "-Install"]
    try:
        with _patched(transaction, anchor, injection):
            process = subprocess.Popen(
                build_only,
                cwd=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _wait_for(testcase, Path(f"{hook}.entered"), process)
            previous = next(output.glob(".HocusPocus.previous.*"))
            locked = (previous / sentinel.relative_to(active)).open("rb")
            Path(f"{hook}.release").write_text("release", encoding="utf-8")
            stdout, stderr = process.communicate(timeout=240)
            testcase.assertEqual(process.returncode, 0, stderr + stdout)
            testcase.assertIn(
                "cleanup deferred", (stderr + stdout).casefold(),
            )
            journal = output / ".hocuspocus-output-transaction.json"
            testcase.assertTrue(journal.is_file())
            testcase.assertTrue(previous.is_dir())
            locked.close()
        swap_target = root / "cleanup-root-swap/target"
        shutil.copytree(active, swap_target)
        authority = json.loads(journal.read_text(encoding="utf-8"))
        rejected_swap = subprocess.run(
            [
                sys.executable,
                os.fspath(source / "scripts/hs8_install_manifest.py"),
                "cleanup-governed",
                "--root",
                os.fspath(swap_target),
                "--expected-digest",
                _manifest_digest(
                    swap_target / "package/install-manifest-v1.json",
                ),
                "--output-root-identity",
                authority["outputRootIdentity"],
            ],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        testcase.assertNotEqual(rejected_swap.returncode, 0)
        testcase.assertTrue(
            (swap_target / "package/install-manifest-v1.json").is_file(),
        )
        extra = previous / "config/cleanup-intruder.txt"
        extra.write_text("reject", encoding="utf-8")
        rejected_extra = _run(build_only, source)
        testcase.assertNotEqual(rejected_extra.returncode, 0)
        testcase.assertTrue(journal.is_file())
        testcase.assertTrue(extra.is_file())
        extra.unlink()
        survivor = previous / "scripts/build.ps1"
        survivor_bytes = survivor.read_bytes()
        survivor.write_bytes(survivor_bytes + b"\n# cleanup-tamper\n")
        rejected_change = _run(build_only, source)
        testcase.assertNotEqual(rejected_change.returncode, 0)
        testcase.assertTrue(journal.is_file())
        survivor.write_bytes(survivor_bytes)
        recovered = _run(build_only, source)
        testcase.assertEqual(
            recovered.returncode, 0, recovered.stderr + recovered.stdout,
        )
        testcase.assertFalse(journal.exists())
        testcase.assertFalse(previous.exists())

        governed.write_bytes(
            original_governed + b"\n# governed-journal-crash-probe\n",
        )
        crash_anchor = "        # HS8_TEST_CRASH_AFTER_GOVERNED_JOURNAL"
        crash_injection = crash_anchor + "\n        Stop-Process -Id $PID -Force"
        with _patched(transaction, crash_anchor, crash_injection):
            crashed = _run(build_only, source)
        testcase.assertNotEqual(crashed.returncode, 0)
        testcase.assertTrue(journal.is_file())
        crash_state = json.loads(journal.read_text(encoding="utf-8"))
        testcase.assertEqual(crash_state["phase"], "cleanup_terminal")
        crash_residue = output / crash_state["cleanupTargetName"]
        testcase.assertTrue(
            (crash_residue / "package/install-manifest-v1.json").is_file(),
        )
        crash_recovered = _run(build_only, source)
        testcase.assertEqual(
            crash_recovered.returncode,
            0,
            crash_recovered.stderr + crash_recovered.stdout,
        )
        testcase.assertFalse(journal.exists())
        testcase.assertFalse(crash_residue.exists())

        governed.write_bytes(
            original_governed + b"\n# manifestless-terminal-probe\n",
        )
        native_cleanup = source / "scripts/hs8_windows_manifest_cleanup.py"
        native_anchor = "    finally:\n        _close(manifest_handle)"
        native_injection = native_anchor + "\n        os._exit(91)"
        with _patched(native_cleanup, native_anchor, native_injection):
            manifestless = _run(build_only, source)
        testcase.assertEqual(
            manifestless.returncode,
            0,
            manifestless.stderr + manifestless.stdout,
        )
        testcase.assertIn(
            "cleanup deferred",
            (manifestless.stderr + manifestless.stdout).casefold(),
        )
        testcase.assertTrue(journal.is_file())
        terminal_state = json.loads(journal.read_text(encoding="utf-8"))
        testcase.assertEqual(terminal_state["phase"], "cleanup_terminal")
        terminal_residue = output / terminal_state["cleanupTargetName"]
        terminal_package = terminal_residue / "package"
        testcase.assertTrue(terminal_package.is_dir())
        testcase.assertFalse(
            (terminal_package / "install-manifest-v1.json").exists(),
        )

        terminal_extra = terminal_package / "cleanup-intruder.txt"
        terminal_extra.write_text("reject", encoding="utf-8")
        blocked_terminal = _run(build_only, source)
        testcase.assertNotEqual(blocked_terminal.returncode, 0)
        testcase.assertTrue(journal.is_file())
        testcase.assertTrue(terminal_extra.is_file())
        testcase.assertEqual(
            json.loads(journal.read_text(encoding="utf-8")),
            terminal_state,
        )
        terminal_extra.unlink()
        terminal_recovered = _run(build_only, source)
        testcase.assertEqual(
            terminal_recovered.returncode,
            0,
            terminal_recovered.stderr + terminal_recovered.stdout,
        )
        testcase.assertFalse(journal.exists())
        testcase.assertFalse(terminal_residue.exists())
    finally:
        governed.write_bytes(original_governed)


@contextmanager
def _patched(path: Path, anchor: str, replacement: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    if original.count(anchor) != 1:
        raise AssertionError(f"Expected one transaction anchor: {anchor}")
    path.write_text(original.replace(anchor, replacement, 1), encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _wait_for(testcase: Any, path: Path, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if path.is_file():
            return
        testcase.assertIsNone(
            process.poll(), "Transaction exited before its hostile boundary.",
        )
        time.sleep(0.02)
    testcase.fail(f"Transaction did not reach hostile boundary: {path.name}")


def _run(
    command: list[str],
    source: Path,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=source,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def _output(command: list[str]) -> Path:
    return Path(command[command.index("-OutputDir") + 1])


def _preferences(command: list[str]) -> Path:
    return Path(command[command.index("-HoudiniUserPrefDir") + 1])


def _active_root(command: list[str]) -> Path:
    preferences = _preferences(command)
    pointer = (preferences / "packages/hocuspocus.json").read_bytes()
    match = re.search(rb"HocusPocus\.[0-9a-f]{12}\.[0-9a-f]{8}", pointer)
    if match is None:
        raise AssertionError("Versioned package pointer is absent.")
    return preferences / "packages" / match.group().decode()


def _configured_token(path: Path) -> str:
    match = re.search(
        r'(?m)^token\s*=\s*"([A-Za-z0-9_-]{32,128})"\s*$',
        path.read_text(encoding="utf-8"),
    )
    if match is None:
        raise AssertionError("Installed token is absent.")
    return match.group(1)


def _manifest_digest(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["manifestDigest"]


def _authority_environment(authority: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOCUSPOCUS_BUILD_AUTHORITY_ROOT": os.fspath(authority),
        "HOCUSPOCUS_BUILD_USER_TOKEN_FILE": os.fspath(
            authority / "user-token.txt",
        ),
    }


def _create_junction(testcase: Any, link: Path, target: Path) -> None:
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", os.fspath(link), os.fspath(target)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    testcase.assertEqual(created.returncode, 0, created.stderr + created.stdout)
