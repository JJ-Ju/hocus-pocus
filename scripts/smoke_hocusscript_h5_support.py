"""Project and durable-store helpers for the installed H5E acceptance harness."""

from __future__ import annotations

import copy
import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from hocuspocus.hocusscript import (
    compile_project_control_program,
    compile_project_mixed_control_program,
    compile_project_module_bundle,
    update_project_control_lock,
    update_project_lock,
    update_project_mixed_control_lock,
    update_project_module_lock,
    verify_project_lock,
)
from hocuspocus.core.jsonrpc import JsonRpcError
from hocuspocus.live.graph_store import LiveGraphStore


MODULE_V03 = """hocus 0.2;
module Root() exports (result: node_output) {
  node seed @id("seed"): "null" {}
  export result = seed.output[0];
}
"""
ENTRY_V03 = """hocus 0.2;
import { Root } from "root.hocus";
graph Main {
  target "/obj/h5e_module_v03";
  category Sop;
  mode merge;
  ownership "studio.h5e.module";
  use terrain @id("terrain") = Root();
  node out @id("out"): "null" { input[0] = terrain.result; }
  display = out;
  render = out;
  output = out;
}
"""


def apply_checkpoint_count(plan: dict[str, Any]) -> int:
    """Count the real document executor checkpoints in fixed apply order."""

    count = sum(
        len(plan.get(key, []))
        for key in (
            "identityUpdates",
            "identityClears",
            "replaceNodes",
            "createNetworkContainers",
            "createNodes",
            "renameNodes",
            "reparentNodes",
            "connectionChanges",
            "parameterResets",
            "typedValueUpdates",
            "expressionUpdates",
            "codeBlobInstalls",
            "animationClears",
            "animationUpdates",
            "nodeUpdates",
            "deleteNodes",
        )
    )
    if plan.get("parameterAssignments"):
        count += 1
    spare_changes = plan.get("spareParameterChanges", [])
    for action in ("upsert", "remove"):
        count += len({
            str(item.get("nodeUid", ""))
            for item in spare_changes
            if isinstance(item, dict) and item.get("action") == action
        })
    editor_change = plan.get("editorEntityChange")
    if isinstance(editor_change, dict):
        operations = editor_change.get("plan", {}).get("operations", [])
        count += 1 + len(operations)
        count += sum(
            1 for item in operations
            if (
                isinstance(item, dict)
                and item.get("action") == "create"
                and item.get("kind")
                not in {"node_comment", "layout_constraint"}
            )
        )
    for key in (
        "rootEditorEntityChange",
        "rootProvenanceChange",
        "rootEntityProvenanceChange",
        "rootTypedBindingChange",
        "outputChange",
        "rootNodeGuard",
    ):
        if isinstance(plan.get(key), dict):
            count += 1
    return count + 1
CONTROL_MODULE_V04 = """hocus 0.3;
module Root() exports (result: node_output) {
  node seed @id("seed"): "null" {}
  export result = seed.output[0];
}
"""
CONTROL_EXTERNAL_V04 = """hocus 0.3;
module Terrain() exports (result: node_output) {
  node seed @id("seed"): "null" {}
  export result = seed.output[0];
}
"""


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _control_entry(
    target: str,
    import_path: str,
    imported_name: str,
    mode: str,
    *,
    fold_count: int = 2,
) -> str:
    return f"""hocus 0.3;
import {{ {imported_name} }} from "{import_path}";
graph Main {{
  target "{target}";
  category Sop;
  mode {mode};
  ownership "studio.h5e.{mode}";
  use terrain @id("terrain") = {imported_name}();
  if selected @id("selected") (true) outputs (result: node_output) {{
    for chain @id("chain") (i in range({fold_count}))
        carry (result: node_output = terrain.result) {{
      node step @id("step"): "null" {{ input[0] = carry.result; }}
      yield result = step.output[0];
    }}
    yield result = chain.result;
  }} else {{
    yield result = terrain.result;
  }}
  node out @id("out"): "null" {{ input[0] = selected.result; }}
  display = out;
  render = out;
  output = out;
}}
"""


def _write_project_manifest(
    root: Path,
    *,
    schema_version: int,
    uid: str,
    language_version: str,
    external_table: str = "",
) -> None:
    _write_text(
        root / "hocus.project.toml",
        f"""schema_version = {schema_version}
[project]
uid = "{uid}"
source_directories = ["src"]
module_directories = ["modules"]
[language]
version = "{language_version}"
[lock]
policy = "required"
path = "pins/hocus.lock.json"
[catalog]
path = "catalog/catalog.json"
{external_table}""",
    )


def _seed_project(root: Path, catalog_json: str) -> None:
    for directory in ("src", "modules", "pins", "catalog"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    _write_text(root / "catalog" / "catalog.json", catalog_json + "\n")


def _build_module_v03(base: Path, catalog_json: str) -> dict[str, Any]:
    project = base / "module-v03"
    _seed_project(project, catalog_json)
    _write_project_manifest(
        project,
        schema_version=3,
        uid="h5e-module-v03",
        language_version="0.2",
    )
    _write_text(project / "src" / "main.hocus", ENTRY_V03)
    _write_text(project / "modules" / "root.hocus", MODULE_V03)
    update_project_lock(project, (), allow_write=True)
    update_project_module_lock(
        project,
        ("src/main.hocus",),
        expected_lock_digest=verify_project_lock(project).lock_digest,
        allow_write=True,
    )
    return compile_project_module_bundle(project, "src/main.hocus").to_dict()


def build_control_local_v04(
    base: Path,
    catalog_json: str,
    *,
    target: str,
    project_name: str,
    project_uid: str,
    fold_count: int = 2,
) -> dict[str, Any]:
    project = base / project_name
    _seed_project(project, catalog_json)
    _write_project_manifest(
        project,
        schema_version=4,
        uid=project_uid,
        language_version="0.3",
    )
    _write_text(
        project / "src" / "main.hocus",
        _control_entry(
            target,
            "root.hocus",
            "Root",
            "merge",
            fold_count=fold_count,
        ),
    )
    _write_text(project / "modules" / "root.hocus", CONTROL_MODULE_V04)
    update_project_control_lock(
        project,
        ("src/main.hocus",),
        allow_write=True,
    )
    return compile_project_control_program(
        project, "src/main.hocus"
    ).bundle.to_dict()


def _external_manifest() -> bytes:
    return b"""schema_version = 2
entry_modules = ["modules/main.hocus"]
[library]
uid = "h5e-control-library"
version = "1.0.0"
[language]
version = "0.3"
"""


def build_control_mixed_v04(
    base: Path,
    catalog_json: str,
    *,
    target: str,
    project_name: str,
    project_uid: str,
    fold_count: int = 2,
) -> dict[str, Any]:
    project = base / project_name
    library = base / f"{project_name}-external"
    manifest = _external_manifest()
    _seed_project(project, catalog_json)
    library.mkdir(parents=True)
    (library / "hocus.module.toml").write_bytes(manifest)
    _write_text(library / "modules" / "main.hocus", CONTROL_EXTERNAL_V04)
    external_table = f"""[external_aliases.terrain]
library_uid = "h5e-control-library"
version = "1.0.0"
module_manifest_digest = "{_sha256_bytes(manifest)}"
"""
    _write_project_manifest(
        project,
        schema_version=4,
        uid=project_uid,
        language_version="0.3",
        external_table=external_table,
    )
    _write_text(
        project / "src" / "main.hocus",
        _control_entry(
            target,
            "@terrain/modules/main.hocus",
            "Terrain",
            "reconcile",
            fold_count=fold_count,
        ),
    )
    empty = update_project_lock(project, (), allow_write=True)
    update_project_mixed_control_lock(
        project,
        ("src/main.hocus",),
        {"terrain": library},
        expected_lock_digest=empty.lock_digest,
        allow_write=True,
    )
    return compile_project_mixed_control_program(
        project,
        "src/main.hocus",
        {"terrain": library},
    ).bundle.to_dict()


def build_primary_bundles(
    base: Path,
    catalog,
    targets: dict[str, str],
) -> dict[str, dict[str, Any]]:
    catalog_json = catalog.to_json()
    return {
        "module_v03": _build_module_v03(base, catalog_json),
        "control_local_v04": build_control_local_v04(
            base,
            catalog_json,
            target=targets["control_local_v04"],
            project_name="control-local-v04",
            project_uid="h5e-control-local-v04",
        ),
        "control_mixed_v04": build_control_mixed_v04(
            base,
            catalog_json,
            target=targets["control_mixed_v04"],
            project_name="control-mixed-v04",
            project_uid="h5e-control-mixed-v04",
        ),
    }


def build_acceptance_bundles(
    base: Path,
    catalog,
    targets: dict[str, str],
    *,
    rollback_target: str,
    recovery_target: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    primary = build_primary_bundles(base, catalog, targets)
    catalog_json = catalog.to_json()
    variants = {
        "rollback": build_control_local_v04(
            base,
            catalog_json,
            target=rollback_target,
            project_name="control-rollback-v04",
            project_uid="h5e-control-rollback-v04",
        ),
        "recovery": build_control_local_v04(
            base,
            catalog_json,
            target=recovery_target,
            project_name="control-recovery-v04",
            project_uid="h5e-control-recovery-v04",
        ),
        "second_merge": build_control_local_v04(
            base,
            catalog_json,
            target=targets["control_local_v04"],
            project_name="control-local-v04-second",
            project_uid="h5e-control-local-v04",
            fold_count=3,
        ),
        "second_reconcile": build_control_mixed_v04(
            base,
            catalog_json,
            target=targets["control_mixed_v04"],
            project_name="control-mixed-v04-second",
            project_uid="h5e-control-mixed-v04",
            fold_count=1,
        ),
    }
    return primary, variants


def _retention_plan(
    operations,
    template: dict[str, Any],
    plan_id: str,
    created_at: float,
    expires_at: float,
) -> dict[str, Any]:
    plan = copy.deepcopy(template)
    plan.update(
        planId=plan_id,
        createdAt=created_at,
        expiresAt=expires_at,
        rootPath=f"/obj/{plan_id}",
    )
    plan["baseline"]["documentId"] = f"network:/obj/{plan_id}"
    plan.pop("planHash", None)
    plan["planHash"] = operations._hocus_canonical_digest(plan)
    return plan


def _retention_history(
    store: LiveGraphStore,
    operations,
    template: dict[str, Any],
    plan_id: str,
    now: float,
    *,
    state: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    plan = _retention_plan(
        operations,
        template,
        plan_id,
        now - 100,
        now + 100,
    )
    store.store_immutable_plan(payload=plan, now=now - 99)
    store.begin_plan_commit(
        plan_commit_id=f"commit:{plan_id}",
        plan_id=plan_id,
        plan_hash=plan["planHash"],
        session_id=plan["sessionId"],
        idempotency_key=f"request:{plan_id}",
        pre_apply_snapshot={"documentRevision": 1},
        inverse_plan={"operations": []},
        now=now - 90,
    )
    if state is not None:
        store.finish_plan_commit(
            plan_commit_id=f"commit:{plan_id}",
            state=state,
            result=result or {"fixture": plan_id},
            error=None,
            now=now - 80,
        )


def _retention_store(
    temporary_root: Path,
    name: str,
) -> LiveGraphStore:
    return LiveGraphStore(
        logging.getLogger(f"hocus.h5.retention.{name}"),
        temporary_root / f"retention-{name}.sqlite3",
    )


def _retention_expiry_age_gate(
    operations,
    template: dict[str, Any],
    temporary_root: Path,
    now: float,
) -> dict[str, Any]:
    store = _retention_store(temporary_root, "age")
    _retention_history(
        store, operations, template, "h5e-retain-pending", now
    )
    _retention_history(
        store,
        operations,
        template,
        "h5e-retain-partial",
        now,
        state="partial_or_unknown",
    )
    expired = _retention_plan(
        operations, template, "h5e-expired-unclaimed", now - 100, now + 1
    )
    store.store_immutable_plan(payload=expired, now=now)
    aged = _retention_plan(
        operations, template, "h5e-aged-terminal", now - 90_000, now + 100
    )
    store.store_immutable_plan(payload=aged, now=now - 90_000)
    store.begin_plan_commit(
        plan_commit_id="commit:h5e-aged-terminal",
        plan_id=aged["planId"],
        plan_hash=aged["planHash"],
        session_id=aged["sessionId"],
        idempotency_key="request:h5e-aged-terminal",
        pre_apply_snapshot={},
        inverse_plan={},
        now=now - 86_500,
    )
    store.finish_plan_commit(
        plan_commit_id="commit:h5e-aged-terminal",
        state="aborted",
        result={"fixture": "aged"},
        error=None,
        now=now - 86_401,
    )
    receipt = store.prune_durable_plan_history(now=now + 2)
    retained = {
        plan_id: store.load_immutable_plan(plan_id) is not None
        for plan_id in (
            "h5e-retain-pending",
            "h5e-retain-partial",
            "h5e-expired-unclaimed",
            "h5e-aged-terminal",
        )
    }
    expected = {
        "h5e-retain-pending": True,
        "h5e-retain-partial": True,
        "h5e-expired-unclaimed": False,
        "h5e-aged-terminal": False,
    }
    if retained != expected:
        raise RuntimeError(
            f"Durable pruning violated recovery retention: {retained}"
        )
    return {**receipt, "retained": retained}


def _retention_count_gate(
    operations,
    template: dict[str, Any],
    temporary_root: Path,
    now: float,
) -> dict[str, Any]:
    store = _retention_store(temporary_root, "count")
    store_type = type(store)
    previous = store_type._MAX_DURABLE_PLAN_HISTORIES
    store_type._MAX_DURABLE_PLAN_HISTORIES = 4
    try:
        _retention_history(store, operations, template, "count-pending", now)
        _retention_history(
            store, operations, template, "count-partial", now,
            state="partial_or_unknown",
        )
        for suffix in ("a", "b", "c"):
            _retention_history(
                store,
                operations,
                template,
                f"count-terminal-{suffix}",
                now + ord(suffix),
                state="committed",
            )
        receipt = store.prune_durable_plan_history(now=now + 1_000)
        retained = {
            plan_id: store.load_immutable_plan(plan_id) is not None
            for plan_id in (
                "count-pending",
                "count-partial",
                "count-terminal-a",
                "count-terminal-b",
                "count-terminal-c",
            )
        }
    finally:
        store_type._MAX_DURABLE_PLAN_HISTORIES = previous
    if (
        not retained["count-pending"]
        or not retained["count-partial"]
        or retained["count-terminal-a"]
        or receipt["historyCount"] > 4
    ):
        raise RuntimeError(
            f"Count pruning violated protected retention: {retained}"
        )
    return {**receipt, "retained": retained}


def _retention_byte_gate(
    operations,
    template: dict[str, Any],
    temporary_root: Path,
    now: float,
) -> dict[str, Any]:
    store = _retention_store(temporary_root, "bytes")
    store_type = type(store)
    previous = store_type._MAX_DURABLE_PLAN_HISTORY_BYTES
    try:
        _retention_history(store, operations, template, "bytes-pending", now)
        _retention_history(
            store, operations, template, "bytes-partial", now,
            state="partial_or_unknown",
        )
        for suffix in ("a", "b"):
            _retention_history(
                store,
                operations,
                template,
                f"bytes-terminal-{suffix}",
                now + ord(suffix),
                state="committed",
                result={"blob": suffix * (1024 * 1024)},
            )
        store_type._MAX_DURABLE_PLAN_HISTORY_BYTES = 66 * 1024 * 1024
        receipt = store.prune_durable_plan_history(now=now + 1_000)
        retained = {
            plan_id: store.load_immutable_plan(plan_id) is not None
            for plan_id in (
                "bytes-pending",
                "bytes-partial",
                "bytes-terminal-a",
                "bytes-terminal-b",
            )
        }
        store_type._MAX_DURABLE_PLAN_HISTORY_BYTES = 63 * 1024 * 1024
        exhausted_plan = _retention_plan(
            operations,
            template,
            "bytes-protected-exhaustion",
            now,
            now + 100,
        )
        try:
            operations._hocus_store_call(
                lambda: store.store_immutable_plan(
                    payload=exhausted_plan,
                    now=now + 1,
                )
            )
        except JsonRpcError as exc:
            diagnostic_code = (
                exc.data.get("diagnosticCode")
                if isinstance(exc.data, dict)
                else None
            )
        else:
            diagnostic_code = None
    finally:
        store_type._MAX_DURABLE_PLAN_HISTORY_BYTES = previous
    if (
        not retained["bytes-pending"]
        or not retained["bytes-partial"]
        or all(
            retained[key]
            for key in ("bytes-terminal-a", "bytes-terminal-b")
        )
        or receipt["pressurePruned"] < 1
        or diagnostic_code != "HOCUS759"
    ):
        raise RuntimeError(
            "Byte pruning violated protected retention: "
            f"retained={retained} diagnosticCode={diagnostic_code!r}"
        )
    return {
        **receipt,
        "retained": retained,
        "protectedExhaustionRejected": True,
        "protectedExhaustionDiagnosticCode": diagnostic_code,
    }


def durable_pruning_gate(
    operations,
    template: dict[str, Any],
    temporary_root: Path,
) -> dict[str, Any]:
    now = time.time()
    return {
        "expiryAndAge": _retention_expiry_age_gate(
            operations, template, temporary_root, now
        ),
        "count": _retention_count_gate(
            operations, template, temporary_root, now
        ),
        "bytes": _retention_byte_gate(
            operations, template, temporary_root, now
        ),
    }
