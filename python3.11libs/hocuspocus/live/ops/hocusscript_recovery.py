"""Pure result construction for durable HocusScript apply recovery."""

from __future__ import annotations

import copy
from typing import Any


def recovered_apply_result(
    *,
    plan: dict[str, Any],
    plan_commit_id: str,
    document: dict[str, Any],
    classification: str,
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Build the same terminal result shape used by normal apply replay."""

    common = {
        "stage": "document_apply",
        "planVersion": plan["planVersion"],
        "planId": plan["planId"],
        "planHash": plan["planHash"],
        "applyCommitId": plan_commit_id,
        "rootPath": plan["rootPath"],
        "recovered": True,
        "classification": classification,
        "executedOperationsAvailable": False,
        "idempotentReplay": False,
    }
    if classification == "target":
        return {
            **common,
            "applied": True,
            "verified": True,
            "state": "committed",
            "document": copy.deepcopy(document),
            "verification": copy.deepcopy(verification),
        }
    if classification != "baseline":
        raise ValueError(f"Unsupported recovery classification: {classification}")
    return {
        **common,
        "applied": False,
        "verified": False,
        "state": "aborted",
        "rolledBack": True,
        "rollbackVerification": copy.deepcopy(verification),
        "diagnosticCode": "HOCUS755",
        "errorFamily": "runtime",
        "message": "Recovered durable apply classified at the stored baseline.",
    }
