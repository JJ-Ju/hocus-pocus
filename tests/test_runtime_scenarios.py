from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import ApplyPlanError, LiveDocumentService
from hocuspocus.live.graph_store import LiveGraphStore
import hocuspocus.live.monitor as monitor_module
from hocuspocus.live.monitor import SceneEventMonitor
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin


class _InlineDispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _DocumentTools(OperationBaseMixin, DocumentOperationsMixin):
    def __init__(self):
        self._dispatcher = _InlineDispatcher()


def _network_document() -> dict:
    return {
        "$schema": "hocuspocus://schemas/network-document/v1",
        "kind": "network_document",
        "documentId": "network:/obj/geo1",
        "documentRevision": 1,
        "rootPath": "/obj/geo1",
        "category": "Object",
        "nodes": [
            {
                "uid": "root",
                "name": "geo1",
                "typeName": "geo",
                "category": "Object",
                "path": "/obj/geo1",
                "parentPath": "/obj",
                "isNetwork": True,
                "position": [0.0, 0.0],
                "flags": {
                    "display": False,
                    "render": False,
                    "bypass": False,
                    "template": False,
                },
                "metadata": {},
            }
        ],
        "edges": [],
        "parameterBindings": [],
        "codeBlobs": [],
        "diagnostics": [],
    }


def _apply_plan(marker: str = "a") -> dict:
    plan = {
        "kind": "hocus_apply_plan",
        "planVersion": "1.0",
        "sessionId": "session:test",
        "scope": "/obj/geo1",
        "operations": [{"sequence": 0, "action": "create_node", "marker": marker}],
    }
    encoded = json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    plan["planHash"] = f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"
    return plan


def _persistent_plan() -> dict:
    plan = {
        "kind": "hocus_apply_plan",
        "planVersion": "1.0",
        "planId": "plan-1",
        "sessionId": "session-1",
        "createdAt": 100.0,
        "expiresAt": 200.0,
        "sourceDigest": "sha256:source",
        "catalogFingerprint": "sha256:catalog",
        "catalogContentDigest": "sha256:catalog-content",
        "ownership": "studio.terrain",
        "rootPath": "/obj/geo1",
        "baseline": {
            "documentId": "network:/obj/geo1",
            "documentRevision": 4,
            "liveRevision": 9,
        },
        "requiredCapabilities": ["edit_scene"],
        "executionPlan": {
            "operations": [
                {"operationId": "op:000000", "action": "create_node", "label": "create"}
            ]
        },
    }
    encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    plan["planHash"] = f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"
    return plan


class _CatalogDefinition:
    def __init__(self, path: Path):
        self._path = path

    def libraryFilePath(self):
        return str(self._path)

    def version(self):
        return "1.0"


class _CatalogNodeType:
    def __init__(self, definition: _CatalogDefinition):
        self._definition = definition

    def name(self):
        return "studio::asset::1.0"

    def nameComponents(self):
        return ("Sop", "studio", "asset", "1.0")

    def aliases(self):
        return ()

    def definition(self):
        return self._definition

    def parmTemplateGroup(self):
        return SimpleNamespace(entries=lambda: ())

    def minNumInputs(self):
        return 1

    def maxNumInputs(self):
        return 1

    def inputNames(self):
        return ("geometry",)

    def inputLabels(self):
        return ("Geometry",)

    def inputDataTypes(self):
        return (("geometry",),)

    def minNumOutputs(self):
        return 1

    def maxNumOutputs(self):
        return 1

    def outputNames(self):
        return ("result",)

    def outputLabels(self):
        return ("Result",)


class _CatalogCategory:
    def __init__(self, node_type: _CatalogNodeType):
        self._node_type = node_type

    def name(self):
        return "Sop"

    def label(self):
        return "Geometry"

    def nodeTypes(self):
        return {self._node_type.name(): self._node_type}


class _CatalogHou:
    def __init__(self, hda_path: Path):
        category = _CatalogCategory(_CatalogNodeType(_CatalogDefinition(hda_path)))
        self._categories = {"Sop": category}

    def nodeTypeCategories(self):
        return self._categories

    def applicationName(self):
        return "Houdini FX"

    def applicationVersion(self):
        return (21, 0, 321)

    def applicationPlatformInfo(self):
        return "windows-x86_64"

    def licenseCategory(self):
        return SimpleNamespace(name=lambda: "Commercial")


class _Event:
    def __init__(self, name: str):
        self._name = name

    def name(self):
        return self._name

    def __str__(self):
        return f"nodeEventType.{self._name}"


class _SceneNode:
    _next_id = 1

    def __init__(self, path: str, children=()):
        self._path = path
        self._children = list(children)
        self._callbacks = []
        self._id = _SceneNode._next_id
        _SceneNode._next_id += 1

    def path(self):
        return self._path

    def sessionId(self):
        return self._id

    def allSubChildren(self):
        return tuple(
            child
            for direct_child in self._children
            for child in (direct_child, *direct_child.allSubChildren())
        )

    def addEventCallback(self, event_types, callback):
        self._callbacks.append((tuple(event_types), callback))

    def removeEventCallback(self, callback):
        self._callbacks = [item for item in self._callbacks if item[1] != callback]

    def emit(self, event, **kwargs):
        for event_types, callback in list(self._callbacks):
            if event in event_types:
                callback(self, event_type=event, **kwargs)


class _CallbackHost:
    def addEventCallback(self, callback):
        self.callback = callback

    def removeEventCallback(self, _callback):
        pass


class _ExportSnapshot:
    operators = (object(),)
    fingerprint = "sha256:" + "a" * 64

    def to_json(self):
        return json.dumps({"catalogFingerprint": self.fingerprint})


class _ExportProvider:
    def __init__(self, _hou_module):
        pass

    def get_catalog(self):
        return _ExportSnapshot()


class RuntimeScenarios(unittest.TestCase):
    def test_document_validation_accepts_a_network_and_rejects_an_ambiguous_edge(self):
        tools = _DocumentTools()
        valid = tools.document_validate({"document": _network_document()}, RequestContext())
        self.assertTrue(valid["structuredContent"]["valid"])

        invalid_document = _network_document()
        invalid_document["edges"] = [
            {
                "uid": "edge:a",
                "kind": "data",
                "from": {"nodeUid": "root"},
                "to": {"nodeUid": "root", "portIndex": 0},
            }
        ]
        invalid = tools.document_validate({"document": invalid_document}, RequestContext())
        self.assertFalse(invalid["structuredContent"]["valid"])
        self.assertIn(
            "edge.port_index.missing",
            {item["code"] for item in invalid["structuredContent"]["diagnostics"]},
        )

    def test_document_artifacts_and_apply_plans_are_content_addressed_and_detached(self):
        service = LiveDocumentService(logging.getLogger("test.documents"))
        preview_payload = {
            "kind": "hocus_document_preview",
            "document": {"nodes": [{"uid": "node:a"}]},
        }
        preview = service.store_preview_artifact(preview_payload)
        self.assertEqual(preview, service.store_preview_artifact(preview_payload))
        preview_payload["document"]["nodes"].clear()
        self.assertEqual(len(service.preview_artifact(preview["previewId"])["document"]["nodes"]), 1)

        plan_payload = _apply_plan()
        plan = service.store_apply_plan(plan_payload)
        plan_payload["operations"].clear()
        loaded = service.apply_plan(plan["planId"], expected_hash=plan["planHash"])
        self.assertEqual(len(loaded["operations"]), 1)

    def test_document_apply_replays_results_and_excludes_overlapping_writes(self):
        service = LiveDocumentService(logging.getLogger("test.documents"))
        plan = service.store_apply_plan(_apply_plan())
        reserved = service.reserve_apply_result(
            "request-1", plan_id=plan["planId"], plan_hash=plan["planHash"]
        )
        service.commit_apply_result(reserved["reservationId"], {"status": "applied"})
        replay = service.reserve_apply_result(
            "request-1", plan_id=plan["planId"], plan_hash=plan["planHash"]
        )
        self.assertEqual(replay["state"], "committed")

        lease = service.acquire_scope_write_lease("/obj/geo1", holder_id="apply:a")
        with self.assertRaisesRegex(ApplyPlanError, "overlaps"):
            service.acquire_scope_write_lease("/obj/geo1/subnet")
        self.assertTrue(service.release_scope_write_lease("/obj/geo1", lease["leaseId"]))

    def test_catalog_export_writes_only_to_the_project_manifest_destination(self):
        script = ROOT / "scripts" / "export_houdini_catalog.py"
        spec = importlib.util.spec_from_file_location("runtime_catalog_exporter", script)
        assert spec is not None and spec.loader is not None
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)

        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            (project / "hocus.project.toml").write_text(
                'schema_version = 2\n[project]\nuid = "export-test"\n'
                '[lock]\npolicy = "required"\npath = "hocus.lock.json"\n'
                '[catalog]\npath = "artifacts/catalog-v1.json"\n',
                encoding="utf-8",
            )
            fake_hou = types.ModuleType("hou")
            with (
                mock.patch.dict(sys.modules, {"hou": fake_hou}),
                mock.patch.object(exporter, "LiveHoudiniCatalogProvider", _ExportProvider),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(exporter.main(["--project", str(project)]), 0)

            output = project / "artifacts" / "catalog-v1.json"
            self.assertEqual(output.read_text(encoding="utf-8"), _ExportSnapshot().to_json() + "\n")
            self.assertFalse((project / "catalog-v1.json").exists())

    def test_graph_store_upgrades_existing_documents_without_data_loss(self):
        fixture = ROOT / "tests" / "fixtures" / "graph_store" / "v1.sql"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "graph.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript(fixture.read_text(encoding="utf-8"))
                connection.commit()

            store = LiveGraphStore(logging.getLogger("test.store"), db_path=path)
            self.assertEqual(
                store.get_document_by_id("fixture:/geo"),
                {"documentId": "fixture:/geo", "kind": "network"},
            )

    def test_graph_store_persists_an_idempotent_plan_commit_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LiveGraphStore(
                logging.getLogger("test.store"), db_path=Path(temp_dir) / "graph.sqlite3"
            )
            plan = _persistent_plan()
            store.store_immutable_plan(
                plan_id="plan-1",
                session_id="session-1",
                root_path="/obj/geo1",
                expires_at=200.0,
                created_at=100.0,
                payload=plan,
            )
            pending = store.begin_plan_commit(
                plan_commit_id="commit-1",
                plan_id="plan-1",
                plan_hash=plan["planHash"],
                session_id="session-1",
                idempotency_key="request-1",
                pre_apply_snapshot={"documentRevision": 4},
                inverse_plan={"operations": []},
                now=150.0,
            )
            replay = store.begin_plan_commit(
                plan_commit_id="ignored",
                plan_id="plan-1",
                plan_hash=plan["planHash"],
                session_id="session-1",
                idempotency_key="request-1",
                pre_apply_snapshot={},
                inverse_plan=None,
                now=151.0,
            )
            self.assertEqual(pending, replay)
            committed = store.finish_plan_commit(
                plan_commit_id="commit-1",
                state="committed",
                result={"verified": True},
                error=None,
                now=160.0,
            )
            self.assertEqual(
                store.load_plan_commit(idempotency_key="request-1")["state"], "committed"
            )
            self.assertEqual(committed["result"], {"verified": True})

    def test_live_catalog_is_portable_stable_and_changes_with_the_hda(self):
        snapshots = []
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            for directory in (first_dir, second_dir):
                hda = Path(directory) / "asset.hda"
                hda.write_bytes(b"same definition")
                snapshots.append(
                    LiveHoudiniCatalogProvider(_CatalogHou(hda), package_directories=()).get_catalog()
                )

            self.assertEqual(snapshots[0].fingerprint, snapshots[1].fingerprint)
            self.assertNotIn(first_dir, snapshots[0].to_json())
            changed_hda = Path(second_dir) / "asset.hda"
            changed_hda.write_bytes(b"changed definition")
            changed = LiveHoudiniCatalogProvider(
                _CatalogHou(changed_hda), package_directories=()
            ).get_catalog()
            self.assertNotEqual(snapshots[1].fingerprint, changed.fingerprint)

    def test_scene_monitor_coalesces_network_edits_and_observes_new_children(self):
        names = (
            "AppearanceChanged",
            "BeingDeleted",
            "ChildCreated",
            "ChildDeleted",
            "ChildReordered",
            "CustomDataChanged",
            "FlagChanged",
            "IndirectInputCreated",
            "IndirectInputDeleted",
            "IndirectInputRewired",
            "InputRewired",
            "NameChanged",
            "ParmTupleAnimated",
            "ParmTupleChanged",
            "ParmTupleChannelChanged",
            "PositionChanged",
            "SpareParmTemplatesChanged",
        )
        events = {name: _Event(name) for name in names}
        sop = _SceneNode("/obj/geo1/box1")
        geo = _SceneNode("/obj/geo1", [sop])
        root = _SceneNode("/", [geo])
        fake_hou = SimpleNamespace(
            nodeEventType=SimpleNamespace(**events),
            node=lambda path: root if path == "/" else None,
            hipFile=_CallbackHost(),
            playbar=_CallbackHost(),
            isUIAvailable=lambda: False,
        )
        original_hou = monitor_module.hou
        monitor_module.hou = fake_hou
        try:
            monitor = SceneEventMonitor(logging.getLogger("test.monitor"))
            monitor.start()
            sop.emit(events["ParmTupleChanged"])
            sop.emit(events["InputRewired"])
            child = _SceneNode("/obj/geo1/new1")
            geo.emit(events["ChildCreated"], child_node=child)
            child.emit(events["FlagChanged"])

            snapshot = monitor.snapshot()
            self.assertEqual(set(snapshot["dirtyScopes"]), {"/obj/geo1"})
            self.assertEqual(snapshot["observedNodeCount"], 4)
            self.assertEqual(monitor.recent_events(limit=1)["events"][0]["event"], "node:FlagChanged")
        finally:
            monitor_module.hou = original_hou


if __name__ == "__main__":
    unittest.main()
