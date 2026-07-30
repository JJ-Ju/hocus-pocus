"""Stable live-revision envelope handling for graph-store upserts."""

from __future__ import annotations

import json


def live_revision_fields(
    latest_payload_json: str | None,
    *,
    changed: bool,
    previous: int,
    current: int,
) -> dict[str, int]:
    if changed:
        baseline = previous if previous > 0 else current
    else:
        latest = json.loads(latest_payload_json or "{}")
        retained = latest.get("baselineLiveRevision")
        baseline = retained if type(retained) is int and retained >= 0 else previous
    return {
        "baselineLiveRevision": baseline,
        "lastSyncedLiveRevision": current,
    }
