"""The advertised surface does not move (spec-2.0 §5.1): the serialised ``tools/list`` of
every profile × ``result_content`` mode is byte-identical to its golden, recorded at the
2.0 M3 cut-over. (2.1 removed ``compat_1x`` and its goldens, 1.4's ``full`` ones; folding
the 2.0 overlays into the specs left these bytes unchanged.)

A change to the catalogue that changes ``tools/list`` must update the goldens in the same
commit and say why. Regenerate them with
``python tests/unit/test_catalog_goldens.py --write``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GOLDENS = Path(__file__).resolve().parent / "goldens"
PROFILES = ("minimal", "core", "full")
MODES = ("text", "both")

pytestmark = pytest.mark.unit


def golden_path(profile: str, mode: str) -> Path:
    return GOLDENS / f"tools_list.{profile}.{mode}.json"


def tools_list_wire_bytes(profile: str, result_content: str) -> bytes:
    """The ``ListToolsResult`` the bridge sends, serialised as the SDK does (compact JSON)."""
    import mcp_types as types

    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile, result_content=result_content), scan=lambda: [])
    result = types.ListToolsResult(tools=bridge.list_tools())
    payload = result.model_dump(by_alias=True, mode="json", exclude_none=True)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("profile", PROFILES)
def test_tools_list_matches_golden(profile: str, mode: str) -> None:
    path = golden_path(profile, mode)
    assert path.exists(), "run `python tests/unit/test_catalog_goldens.py --write`"
    golden = path.read_bytes()
    current = tools_list_wire_bytes(profile, mode)
    assert len(current) == len(golden), (
        f"tools/list ({profile}, {mode}) is {len(current):,} B, golden {len(golden):,} B"
    )
    assert current == golden, f"tools/list ({profile}, {mode}) changed bytes"


def test_every_golden_is_a_profile() -> None:
    """No golden is left for a profile that no longer exists."""
    names = {path.name for path in GOLDENS.glob("tools_list.*.json")}
    assert names == {golden_path(p, m).name for p in PROFILES for m in MODES}


def _write() -> None:
    GOLDENS.mkdir(exist_ok=True)
    for profile in PROFILES:
        for mode in MODES:
            data = tools_list_wire_bytes(profile, mode)
            golden_path(profile, mode).write_bytes(data)
            print(f"{profile} {mode}: {len(data):,} B")


if __name__ == "__main__":
    sys.path.insert(0, str(REPO / "src"))
    if sys.argv[1:] != ["--write"]:
        raise SystemExit("usage: python tests/unit/test_catalog_goldens.py --write")
    _write()
