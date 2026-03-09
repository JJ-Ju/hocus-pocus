"""stdio to HTTP bridge for MCP clients that prefer stdio."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        header_line = line.decode("utf-8").strip()
        if ":" not in header_line:
            continue
        key, value = header_line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None
    body = sys.stdin.buffer.read(content_length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _proxy(url: str, token: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    if not content:
        return None
    return json.loads(content.decode("utf-8"))


def main() -> int:
    url = os.environ.get("HOCUSPOCUS_HTTP_URL", "http://127.0.0.1:37219/hocuspocus/mcp")
    token = os.environ.get("HOCUSPOCUS_TOKEN", "")

    while True:
        message = _read_message()
        if message is None:
            return 0
        try:
            response = _proxy(url, token, message)
        except urllib.error.HTTPError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32000,
                    "message": f"Bridge HTTP error: {exc.code}",
                },
            }
        except Exception as exc:  # pragma: no cover - exercised via runtime use
            response = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": -32001,
                    "message": f"Bridge transport error: {exc}",
                },
            }

        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
