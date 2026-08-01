"""Prove one stdio MCP session survives a Houdini-host restart."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPOSITORY_ROOT / "python3.11libs"
OFFLINE_CODE = -32099
OFFLINE_MESSAGE = "Houdini host is offline."
AMBIGUOUS_MESSAGE = "Houdini host delivery is ambiguous."


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fake", "h22"), default="fake")
    parser.add_argument(
        "--hython",
        type=Path,
        default=Path(
            r"C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe"
        ),
    )
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--client-config", type=Path)
    parser.add_argument("--houdini-preference-root", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _OutputDrain:
    def __init__(self, stream: Any, limit: int = 64 * 1024) -> None:
        self._stream = stream
        self._limit = limit
        self._chunks: list[str] = []
        self._size = 0
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        for line in self._stream:
            encoded = (
                line
                if isinstance(line, bytes)
                else line.encode("utf-8", errors="replace")
            )
            remaining = self._limit - self._size
            if remaining <= 0:
                continue
            self._chunks.append(encoded[:remaining].decode("utf-8", errors="replace"))
            self._size += min(len(encoded), remaining)

    def text(self) -> str:
        return "".join(self._chunks)


class _BrokerClient:
    def __init__(
        self,
        url: str,
        *,
        command: list[str] | None = None,
        configured_environment: dict[str, str] | None = None,
        token: str = "",
        acceptance_environment: dict[str, str] | None = None,
        inject_setup_failure: bool = False,
    ) -> None:
        environment = os.environ.copy()
        if command is None:
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(PYTHON_ROOT), environment.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            environment.update({
                "HOCUSPOCUS_HTTP_URL": url,
                "HOCUSPOCUS_CONNECT_TIMEOUT_SECONDS": "0.5",
                "HOCUSPOCUS_REQUEST_TIMEOUT_SECONDS": "5.0",
            })
            command = [
                sys.executable,
                "-m",
                "hocuspocus.core.stdio_bridge",
            ]
        else:
            environment.pop("PYTHONPATH", None)
            environment.update(configured_environment or {})
            if environment.get("HOCUSPOCUS_HTTP_URL") != url:
                raise RuntimeError("Generated client URL does not match the host.")
        environment.update(acceptance_environment or {})
        environment["HOCUSPOCUS_TOKEN"] = token
        self.process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=_creation_flags(),
        )
        try:
            if inject_setup_failure:
                raise RuntimeError("Injected broker-client setup failure.")
            if (
                self.process.stdin is None
                or self.process.stdout is None
                or self.process.stderr is None
            ):
                raise RuntimeError("Broker stdio pipes are unavailable.")
            self._responses: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
            self._reader = threading.Thread(target=self._read, daemon=True)
            self._reader.start()
            self.stderr = _OutputDrain(self.process.stderr)
        except BaseException as exc:
            terminated = _terminate_process(self.process)
            raise _ClientStartFailure(self.process.pid, terminated) from exc

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    return
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1].strip())
                    while self.process.stdout.readline() not in {b"\n", b"\r\n", b""}:
                        pass
                    raw = self.process.stdout.read(length)
                else:
                    raw = line.strip()
                if raw:
                    self._responses.put(json.loads(raw.decode("utf-8")))
        except BaseException as exc:
            self._responses.put(exc)

    def request(
        self,
        request_id: int,
        method: str,
        params: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError(
                f"Broker exited early: {self.process.returncode}; {self.stderr.text()}"
            )
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        assert self.process.stdin is not None
        self.process.stdin.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        )
        self.process.stdin.flush()
        response = self._responses.get(timeout=timeout)
        if isinstance(response, BaseException):
            raise response
        if response.get("id") != request_id:
            raise RuntimeError(f"Broker returned an unexpected response: {response!r}")
        return response

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


class _ClientStartFailure(RuntimeError):
    def __init__(self, pid: int, terminated: bool) -> None:
        super().__init__("Broker client failed after process creation.")
        self.pid = pid
        self.terminated = terminated


class _ReusableHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class _FakeHandler(BaseHTTPRequestHandler):
    server_version = "HocusPocusDurabilityFake/1"

    def _identity_headers(self) -> None:
        self.send_header(
            "HocusPocus-Host-Instance-Id",
            self.server.host_instance_id,  # type: ignore[attr-defined]
        )
        self.send_header(
            "HocusPocus-Host-Generation",
            str(self.server.host_generation),  # type: ignore[attr-defined]
        )

    def do_GET(self) -> None:  # noqa: N802
        payload = {
            "running": True,
            "hostInstanceId": self.server.host_instance_id,  # type: ignore[attr-defined]
            "hostGeneration": self.server.host_generation,  # type: ignore[attr-defined]
        }
        self._write(payload)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        method = request.get("method")
        self._response_session = (
            self.headers.get("Mcp-Session-Id")
            or self.headers.get("HocusPocus-Broker-Session-Id")
            or self.server.session_id  # type: ignore[attr-defined]
        )
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "hocuspocus-houdini", "version": "test"},
                "capabilities": {"tools": {"listChanged": False}},
            }
        elif method == "tools/call":
            result = {
                "content": [{"type": "text", "text": "Disposable host is online."}],
                "structuredContent": {
                    "hostPid": self.server.host_pid,  # type: ignore[attr-defined]
                    "hostInstanceId": self.server.host_instance_id,  # type: ignore[attr-defined]
                },
                "isError": False,
            }
        else:
            result = {}
        self._write({"jsonrpc": "2.0", "id": request.get("id"), "result": result})

    def _write(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if self._response_session:
            self.send_header("Mcp-Session-Id", self._response_session)
            self.send_header(
                "HocusPocus-Broker-Session-Id",
                self._response_session,
            )
        self._identity_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_arguments: Any) -> None:
        return


class _FakeHost:
    def __init__(self, port: int, generation: int) -> None:
        self.server = _ReusableHTTPServer(("127.0.0.1", port), _FakeHandler)
        self.server.host_instance_id = str(uuid4())
        self.server.host_generation = generation
        self.server.host_pid = 10000 + generation
        self.server.session_id = "hws_" + uuid4().hex
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def receipt(self) -> dict[str, Any]:
        return {
            "pid": self.server.host_pid,
            "hostInstanceId": self.server.host_instance_id,
            "hostGeneration": self.server.host_generation,
        }

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class _HostStartFailure(RuntimeError):
    def __init__(self, pid: int, terminated: bool) -> None:
        super().__init__("Disposable H22 host failed before readiness.")
        self.pid = pid
        self.terminated = terminated


class _H22Host:
    def __init__(
        self,
        hython: Path,
        port: int,
        generation: int,
        root: Path,
        timeout: float,
        installed_root: Path,
        preference_root: Path,
        token: str,
        *,
        inject_readiness_failure: bool = False,
    ) -> None:
        ready_file = root / f"host-{generation}.json"
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["HOUDINI_USER_PREF_DIR"] = str(
            preference_root.with_name("houdini__HVER__")
        )
        environment["HOUDINI_NO_ENV_FILE"] = "1"
        environment["HOCUSPOCUS_AUTO_START"] = "0"
        environment["HOCUSPOCUS_TOKEN"] = token
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        helper = installed_root / "scripts" / "durable_h22_host.py"
        self.process = subprocess.Popen(
            [
                str(hython),
                str(helper),
                "--port",
                str(port),
                "--ready-file",
                str(ready_file),
                "--launch-generation",
                str(generation),
                "--installed-root",
                str(installed_root),
            ],
            cwd=installed_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=_creation_flags(),
        )
        try:
            self.stdout = _OutputDrain(self.process.stdout)
            self.stderr = _OutputDrain(self.process.stderr)
            if inject_readiness_failure:
                raise RuntimeError("Injected readiness failure.")
            self.receipt = _wait_ready(
                ready_file,
                self.process,
                timeout,
                self.stderr,
            )
        except BaseException as exc:
            terminated = self._terminate()
            try:
                ready_file.unlink()
            except FileNotFoundError:
                pass
            raise _HostStartFailure(self.process.pid, terminated) from exc

    def _terminate(self) -> bool:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        return self.process.poll() is not None

    def stop(self) -> None:
        if self.process.poll() is None and self.process.stdin is not None:
            self.process.stdin.write("stop\n")
            self.process.stdin.flush()
            self.process.stdin.close()
        try:
            if self.process.poll() is None:
                self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self._terminate()
        if self.process.returncode != 0:
            raise RuntimeError(
                f"Disposable H22 host failed: {self.process.returncode}; "
                f"{self.stderr.text()}"
            )


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _terminate_process(process: subprocess.Popen) -> bool:
    try:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        return process.poll() is not None
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
    return process.poll() is not None


def _wait_ready(
    path: Path,
    process: subprocess.Popen,
    timeout: float,
    stderr: _OutputDrain,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Disposable host exited before readiness: {process.returncode}; "
                f"{stderr.text()}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        if payload.get("pid") != process.pid:
            raise RuntimeError("Disposable host readiness PID is invalid.")
        return payload
    raise RuntimeError(f"Disposable host readiness timed out: {stderr.text()}")


def _assert_success(response: dict[str, Any], label: str) -> dict[str, Any]:
    if "error" in response:
        raise RuntimeError(f"{label} failed: {response['error']!r}")
    return response["result"]


def _assert_offline(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if not isinstance(error, dict):
        raise RuntimeError(f"Offline call unexpectedly succeeded: {response!r}")
    data = error.get("data")
    if (
        error.get("code") != OFFLINE_CODE
        or error.get("message") != OFFLINE_MESSAGE
        or not isinstance(data, dict)
        or data.get("hocusCode") != "HOCUS999"
        or data.get("kind") != "host_offline"
        or data.get("retryable") is not True
    ):
        raise RuntimeError(f"Offline response is not the typed contract: {error!r}")
    return error


def _assert_ambiguous(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    data = error.get("data") if isinstance(error, dict) else None
    if (
        not isinstance(error, dict)
        or error.get("code") != OFFLINE_CODE
        or error.get("message") != AMBIGUOUS_MESSAGE
        or not isinstance(data, dict)
        or data.get("hocusCode") != "HOCUS999"
        or data.get("kind") != "ambiguous_delivery"
        or data.get("retryable") is not False
    ):
        raise RuntimeError(f"Ambiguous response is not the typed contract: {error!r}")
    return error


def _call_summary(client: _BrokerClient, request_id: int, timeout: float) -> dict[str, Any]:
    response = client.request(
        request_id,
        "tools/call",
        {"name": "scene.get_summary", "arguments": {}},
        timeout,
    )
    return _assert_success(response, "scene.get_summary")


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _installed_context(arguments: argparse.Namespace) -> dict[str, Any]:
    from hs8_install_manifest import create_manifest, verify_manifest

    if (
        arguments.installed_root is None
        or arguments.client_config is None
        or arguments.houdini_preference_root is None
    ):
        raise RuntimeError(
            "Installed H22 acceptance requires installed root, client config, "
            "and Houdini preference root."
        )
    installed_root = arguments.installed_root.resolve(strict=True)
    preference_root = arguments.houdini_preference_root.resolve(strict=True)
    packages = (preference_root / "packages").resolve(strict=True)
    if (
        preference_root.name.lower() != "houdini22.0"
        or installed_root.parent != packages
    ):
        raise RuntimeError("Installed root is not owned by the isolated H22 preferences.")
    source_manifest = create_manifest(REPOSITORY_ROOT)
    installed_manifest = verify_manifest(installed_root, source_manifest)
    config_path = installed_root / "config" / "default.toml"
    config_bytes = config_path.read_bytes()
    config_digest = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
    pointer = json.loads((packages / "hocuspocus.json").read_text(encoding="utf-8"))
    authority = pointer.get("hocuspocus")
    root_entries = pointer.get("env")
    expected_root = "$HOUDINI_PACKAGE_PATH/" + installed_root.name
    if (
        not isinstance(authority, dict)
        or set(authority) != {
            "schemaVersion",
            "activeConfigDigest",
            "installManifestDigest",
        }
        or authority.get("schemaVersion") != 1
        or authority.get("activeConfigDigest") != config_digest
        or authority.get("installManifestDigest")
        != installed_manifest["manifestDigest"]
        or not isinstance(root_entries, list)
        or not root_entries
        or not isinstance(root_entries[0], dict)
        or root_entries[0].get("HOCUSPOCUS_ROOT") != expected_root
    ):
        raise RuntimeError("Active package credential authority is stale.")
    config_path = arguments.client_config.resolve(strict=True)
    if config_path.parent != packages:
        raise RuntimeError("Generated Codex configuration escapes the package directory.")
    client_payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    client = client_payload.get("mcp_servers", {}).get("hocuspocus")
    if not isinstance(client, dict):
        raise RuntimeError("Generated Codex client configuration is invalid.")
    command = client.get("command")
    command_args = client.get("args")
    configured_environment = client.get("env")
    if (
        not isinstance(command, str)
        or not isinstance(command_args, list)
        or not all(isinstance(item, str) for item in command_args)
        or command_args[:2] != ["-I", "-B"]
        or len(command_args) != 3
        or not isinstance(configured_environment, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in configured_environment.items()
        )
        or "HOCUSPOCUS_TOKEN" in configured_environment
    ):
        raise RuntimeError("Generated Codex command or environment is invalid.")
    launcher = Path(command_args[-1]).resolve(strict=True)
    governed_launcher = installed_root / "scripts" / "hocuspocus-mcp-stdio.py"
    if launcher.read_bytes() != governed_launcher.read_bytes():
        raise RuntimeError("Stable launcher differs from its governed installed source.")
    installed_config = tomllib.loads(config_bytes.decode("utf-8"))
    token = installed_config.get("token")
    if (
        installed_config.get("token_mode") == "disabled"
        or not isinstance(token, str)
        or len(token) < 32
    ):
        raise RuntimeError("Installed bearer authentication is not configured.")
    url = configured_environment["HOCUSPOCUS_HTTP_URL"]
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.path != "/hocuspocus/mcp"
    ):
        raise RuntimeError("Generated Codex URL is not the isolated loopback host.")
    files = {
        row["relativePath"]: row["contentDigest"]
        for row in installed_manifest["files"]
    }
    required = {
        "python3.11libs/hocuspocus/core/stdio_bridge.py",
        "python3.11libs/hocuspocus/core/stdio_runtime.py",
        "scripts/hocuspocus-mcp-stdio.py",
        "scripts/durable_h22_host.py",
    }
    if not required.issubset(files):
        raise RuntimeError("Installed manifest omits the durable runtime closure.")
    return {
        "installedRoot": installed_root,
        "preferenceRoot": preference_root,
        "manifest": installed_manifest,
        "command": [command, *command_args],
        "environment": configured_environment,
        "token": token,
        "url": url,
        "port": parsed.port,
        "clientConfigDigest": _sha256(config_path),
        "launcherDigest": files["scripts/hocuspocus-mcp-stdio.py"],
        "brokerDigest": files[
            "python3.11libs/hocuspocus/core/stdio_bridge.py"
        ],
    }


def _validate_host_alignment(
    receipt: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if (
        receipt.get("authRequired") is not True
        or receipt.get("installManifestDigest") != manifest["manifestDigest"]
    ):
        raise RuntimeError("Running host is not aligned to the authenticated install.")
    governed = {
        row["relativePath"]: row["contentDigest"]
        for row in manifest["files"]
    }
    module_receipts = receipt.pop("moduleReceipts", None)
    if not isinstance(module_receipts, list) or not module_receipts:
        raise RuntimeError("Running host module receipts are absent.")
    for row in module_receipts:
        if (
            not isinstance(row, dict)
            or governed.get(row.get("relativePath")) != row.get("digest")
        ):
            raise RuntimeError("Running host module bytes differ from the install.")
    required = {
        "python3.11libs/hocuspocus/core/server.py",
        "python3.11libs/hocuspocus/core/host_identity.py",
    }
    observed = {row["relativePath"] for row in module_receipts}
    if not required.issubset(observed):
        raise RuntimeError("Running host closure omits a required runtime module.")
    receipt["runningModuleCount"] = len(module_receipts)
    return receipt


def _read_broker_attestation(
    path: Path,
    client: _BrokerClient,
    timeout: float,
) -> tuple[bytes, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.process.poll() is not None:
            raise RuntimeError(
                "Installed broker exited before runtime attestation: "
                f"{client.process.returncode}; {client.stderr.text()}"
            )
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            time.sleep(0.02)
            continue
        if len(raw) > 1024 * 1024:
            raise RuntimeError("Broker runtime attestation exceeds its bound.")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Broker runtime attestation is invalid.") from exc
        finally:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return raw, envelope
    else:
        raise RuntimeError("Broker runtime attestation timed out.")


def _validate_broker_attestation(
    raw: bytes,
    envelope: dict[str, Any],
    nonce: str,
    client: _BrokerClient,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise RuntimeError("Broker runtime attestation is not an object.")
    signature = envelope.pop("hmacSha256", None)
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected = hmac.new(bytes.fromhex(nonce), encoded, hashlib.sha256).hexdigest()
    if (
        not isinstance(signature, str)
        or not hmac.compare_digest(signature, expected)
        or set(envelope) != {
            "schemaVersion",
            "kind",
            "pid",
            "installManifestDigest",
            "moduleReceipts",
        }
        or envelope.get("schemaVersion") != 1
        or envelope.get("kind") != "hocuspocus_broker_runtime_attestation"
        or envelope.get("pid") != client.pid
        or envelope.get("installManifestDigest") != manifest["manifestDigest"]
    ):
        raise RuntimeError("Broker runtime attestation failed authentication.")
    governed = {
        row["relativePath"]: row["contentDigest"]
        for row in manifest["files"]
    }
    receipts = envelope.get("moduleReceipts")
    if not isinstance(receipts, list) or not receipts:
        raise RuntimeError("Broker runtime module receipts are absent.")
    for row in receipts:
        if (
            not isinstance(row, dict)
            or set(row) != {"module", "relativePath", "digest"}
            or governed.get(row.get("relativePath")) != row.get("digest")
        ):
            raise RuntimeError("Broker runtime module receipt is invalid.")
    required = {
        "python3.11libs/hocuspocus/core/stdio_bridge.py",
        "python3.11libs/hocuspocus/core/stdio_runtime.py",
    }
    observed = {row["relativePath"] for row in receipts}
    if not required.issubset(observed):
        raise RuntimeError("Broker runtime closure omits a required module.")
    return {
        "attestationDigest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "moduleCount": len(receipts),
    }


def _wait_broker_attestation(
    path: Path,
    nonce: str,
    client: _BrokerClient,
    manifest: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    raw, envelope = _read_broker_attestation(path, client, timeout)
    return _validate_broker_attestation(
        raw,
        envelope,
        nonce,
        client,
        manifest,
    )


def _new_host(
    arguments: argparse.Namespace,
    installed: dict[str, Any] | None,
    port: int,
    generation: int,
    root: Path,
    *,
    inject_readiness_failure: bool = False,
) -> _FakeHost | _H22Host:
    if installed is None:
        return _FakeHost(port, generation)
    return _H22Host(
        arguments.hython,
        port,
        generation,
        root,
        arguments.timeout_seconds,
        installed["installedRoot"],
        installed["preferenceRoot"],
        installed["token"],
        inject_readiness_failure=inject_readiness_failure,
    )


def _wait_for_exit(process: subprocess.Popen, timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def _verify_cleanup_failures(
    arguments: argparse.Namespace,
    installed: dict[str, Any],
    port: int,
    root: Path,
) -> dict[str, bool]:
    try:
        _new_host(
            arguments,
            installed,
            port,
            0,
            root,
            inject_readiness_failure=True,
        )
    except _HostStartFailure as exc:
        if not exc.terminated:
            raise RuntimeError("Injected readiness failure left Hython running.") from exc
    else:
        raise RuntimeError("Injected readiness failure unexpectedly succeeded.")

    try:
        _BrokerClient(
            installed["url"],
            command=installed["command"],
            configured_environment=installed["environment"],
            token=installed["token"],
            inject_setup_failure=True,
        )
    except _ClientStartFailure as exc:
        if not exc.terminated:
            raise RuntimeError(
                "Injected broker-client setup failure left the process running."
            ) from exc
    else:
        raise RuntimeError("Injected broker-client setup failure unexpectedly succeeded.")

    host = _new_host(arguments, installed, port, 0, root)
    client: _BrokerClient | None = None
    occupied = root / "occupied-attestation.json"
    try:
        occupied.write_text("{}\n", encoding="utf-8")
        client = _BrokerClient(
            installed["url"],
            command=installed["command"],
            configured_environment=installed["environment"],
            token=installed["token"],
            acceptance_environment={
                "HOCUSPOCUS_BROKER_ATTESTATION_PATH": str(occupied),
                "HOCUSPOCUS_BROKER_ATTESTATION_NONCE": secrets.token_hex(32),
            },
        )
        if not _wait_for_exit(client.process, arguments.timeout_seconds):
            raise RuntimeError("Injected launcher failure did not stop the broker.")
        if client.process.returncode == 0:
            raise RuntimeError("Injected launcher failure unexpectedly succeeded.")
    finally:
        if client is not None:
            client.close()
        host.stop()
        try:
            occupied.unlink()
        except FileNotFoundError:
            pass
    if host.process.poll() is None:
        raise RuntimeError("Injected launcher failure left Hython running.")
    return {
        "readinessFailureTerminatedHython": True,
        "clientSetupFailureTerminatedBroker": True,
        "launcherFailureTerminatedHython": True,
    }


def _new_client(
    installed: dict[str, Any] | None,
    url: str,
    root: Path,
) -> tuple[_BrokerClient, str, Path]:
    attestation_path = root / "broker-attestation.json"
    if installed is None:
        return _BrokerClient(url), "", attestation_path
    nonce = secrets.token_hex(32)
    client = _BrokerClient(
        url,
        command=installed["command"],
        configured_environment=installed["environment"],
        token=installed["token"],
        acceptance_environment={
            "HOCUSPOCUS_BROKER_ATTESTATION_PATH": str(attestation_path),
            "HOCUSPOCUS_BROKER_ATTESTATION_NONCE": nonce,
        },
    )
    return client, nonce, attestation_path


def _broker_runtime_receipt(
    installed: dict[str, Any] | None,
    client: _BrokerClient,
    nonce: str,
    path: Path,
    timeout: float,
) -> dict[str, Any] | None:
    if installed is None:
        return None
    return _wait_broker_attestation(
        path,
        nonce,
        client,
        installed["manifest"],
        timeout,
    )


def _host_receipt(
    host: _FakeHost | _H22Host,
    installed: dict[str, Any] | None,
) -> dict[str, Any]:
    receipt = dict(host.receipt)
    if installed is None:
        return receipt
    return _validate_host_alignment(receipt, installed["manifest"])


def _probe_ambiguous_delivery(
    arguments: argparse.Namespace,
    client: _BrokerClient,
    request_id: int,
) -> tuple[dict[str, Any] | None, int]:
    if arguments.mode != "fake":
        return None, request_id
    ambiguous = _assert_ambiguous(
        client.request(
            request_id,
            "tools/call",
            {"name": "scene.get_summary", "arguments": {}},
            arguments.timeout_seconds,
        )
    )
    return ambiguous, request_id + 1


def _alignment_receipt(
    installed: dict[str, Any] | None,
    broker_attestation: dict[str, Any] | None,
    cleanup_proof: dict[str, bool] | None,
) -> dict[str, Any] | None:
    if installed is None:
        return None
    return {
        "authRequired": True,
        "manifestDigest": installed["manifest"]["manifestDigest"],
        "artifactCount": len(installed["manifest"]["files"]),
        "clientConfigDigest": installed["clientConfigDigest"],
        "launcherDigest": installed["launcherDigest"],
        "brokerDigest": installed["brokerDigest"],
        "launcherVerifiedOnBrokerStart": True,
        "runningBrokerClosureVerified": True,
        "brokerRuntimeAttestation": broker_attestation,
        "cleanupProof": cleanup_proof,
        "sourceInstallAligned": True,
        "tokenDisclosed": False,
    }


def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    installed = _installed_context(arguments) if arguments.mode == "h22" else None
    port = installed["port"] if installed is not None else _free_port()
    url = (
        installed["url"]
        if installed is not None
        else f"http://127.0.0.1:{port}/hocuspocus/mcp"
    )
    with tempfile.TemporaryDirectory(prefix="hocuspocus-durable-") as temp:
        root = Path(temp)
        cleanup_proof = (
            _verify_cleanup_failures(arguments, installed, port, root)
            if installed is not None
            else None
        )
        host_one: _FakeHost | _H22Host | None = None
        host_two: _FakeHost | _H22Host | None = None
        client: _BrokerClient | None = None
        try:
            host_one = _new_host(arguments, installed, port, 1, root)
            client, nonce, attestation_path = _new_client(installed, url, root)
            broker_pid = client.pid
            broker_attestation = _broker_runtime_receipt(
                installed,
                client,
                nonce,
                attestation_path,
                arguments.timeout_seconds,
            )
            _assert_success(
                client.request(
                    1,
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "hocuspocus-durability-acceptance",
                            "version": "1",
                        },
                    },
                    arguments.timeout_seconds,
                ),
                "initialize",
            )
            first = _call_summary(client, 2, arguments.timeout_seconds)
            first_host = _host_receipt(host_one, installed)
            host_one.stop()
            host_one = None
            next_request_id = 3
            ambiguous, next_request_id = _probe_ambiguous_delivery(
                arguments,
                client,
                next_request_id,
            )
            offline = _assert_offline(
                client.request(
                    next_request_id,
                    "ping",
                    {},
                    arguments.timeout_seconds,
                )
            )
            next_request_id += 1
            if str(offline["data"]["hostGeneration"]) != str(
                first_host["hostGeneration"]
            ):
                raise RuntimeError("Offline response lost the last host generation.")
            if client.pid != broker_pid or client.process.poll() is not None:
                raise RuntimeError("Broker process did not survive the offline interval.")
            host_two = _new_host(arguments, installed, port, 2, root)
            time.sleep(0.6)
            second = _call_summary(
                client, next_request_id, arguments.timeout_seconds
            )
            second_host = _host_receipt(host_two, installed)
            if client.pid != broker_pid:
                raise RuntimeError("Broker PID changed across host restart.")
            if first_host["pid"] == second_host["pid"]:
                raise RuntimeError("Disposable host PID did not change.")
            if first_host["hostInstanceId"] == second_host["hostInstanceId"]:
                raise RuntimeError("Disposable host identity did not change.")
            if (
                first_host["hostInstanceId"],
                first_host["hostGeneration"],
            ) == (
                second_host["hostInstanceId"],
                second_host["hostGeneration"],
            ):
                raise RuntimeError("Disposable host generation pair did not change.")
            receipt = {
                "schemaVersion": 1,
                "kind": "hocuspocus_stdio_restart_acceptance",
                "mode": arguments.mode,
                "brokerPid": broker_pid,
                "brokerSessionReused": True,
                "firstHost": first_host,
                "secondHost": second_host,
                "offlineError": offline,
                "ambiguousDeliveryError": ambiguous,
                "firstCall": first,
                "secondCall": second,
            }
            alignment = _alignment_receipt(
                installed,
                broker_attestation,
                cleanup_proof,
            )
            if alignment is not None:
                receipt["installedAlignment"] = alignment
            return receipt
        finally:
            if client is not None:
                client.close()
            if host_two is not None:
                host_two.stop()
            if host_one is not None:
                host_one.stop()


def main() -> int:
    arguments = _arguments()
    if arguments.mode == "h22" and not arguments.hython.is_file():
        raise RuntimeError(f"Houdini 22 hython not found: {arguments.hython}")
    print(json.dumps(_run(arguments), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
