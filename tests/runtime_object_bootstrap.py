"""Focused runtime coverage for document-centric OBJ bootstrapping."""

from __future__ import annotations

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path

from hocuspocus.core.jsonrpc import INTERNAL_ERROR, JsonRpcError
from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.core.policy import EDIT_SCENE
from hocuspocus.live.context import RequestContext
from hocuspocus.live.document_service import LiveDocumentService
from hocuspocus.live.graph_store import LiveGraphStore
from hocuspocus.live.operations import LiveOperations
from hocuspocus.live.ops.base import OperationBaseMixin
from hocuspocus.live.ops.document import DocumentOperationsMixin
from hocuspocus.live.ops.node import NodeOperationsMixin


class _InlineDispatcher:
    @staticmethod
    def call(callback, _context):
        return callback()


class _Node:
    def __init__(self, parent, name: str):
        self.parent = parent
        self.name = name
        self.user_data: dict[str, str] = {}
        self.destroyed = False

    def path(self) -> str:
        return f"/obj/{self.name}"

    def setUserData(self, key: str, value: str) -> None:
        self.user_data[key] = value

    def destroy(self) -> None:
        if self.parent.fail_destroy:
            raise RuntimeError("injected node destruction failure")
        self.destroyed = True
        self.parent.children.pop(self.name, None)


class _ObjectNetwork:
    def __init__(self):
        self.children: dict[str, _Node] = {}
        self.fail_destroy = False

    def node(self, name: str):
        return self.children.get(name)

    def createNode(self, node_type: str, *, node_name=None, **_kwargs):
        assert node_type == "geo"
        base = node_name or "geo1"
        name = base
        suffix = 1
        while name in self.children:
            name = f"{base}{suffix}"
            suffix += 1
        node = _Node(self, name)
        self.children[name] = node
        return node


class _Undos:
    @contextmanager
    def group(self, _label):
        yield


class _Hou:
    def __init__(self, objects: _ObjectNetwork):
        self.objects = objects
        self.undos = _Undos()

    def node(self, path: str):
        return self.objects if path == "/obj" else None


class _BootstrapTools(
    OperationBaseMixin,
    DocumentOperationsMixin,
    NodeOperationsMixin,
):
    def __init__(self, db_path: Path):
        self._dispatcher = _InlineDispatcher()
        self._objects = _ObjectNetwork()
        self._hou = _Hou(self._objects)
        self._graph_store = LiveGraphStore(
            logging.getLogger("test.bootstrap"), db_path=db_path
        )
        self._documents = LiveDocumentService(
            logging.getLogger("test.bootstrap"), self._graph_store
        )
        self._fail_sync = False
        self._fail_delivery = False

    def _require_hou(self):
        return self._hou

    @staticmethod
    def _node_summary(node):
        return {
            "path": node.path(),
            "name": node.name,
            "typeName": "geo",
            "category": "Object",
            "isNetwork": True,
        }

    @staticmethod
    def _place_node_on_grid(_parent, node):
        node.user_data["placed"] = "true"

    @staticmethod
    def _clear_node_grid_cell(_node):
        return None

    @staticmethod
    def _sync_grid_state_for_parent(_parent):
        return {}

    def _scene_graph_snapshot_build_impl(self):
        if self._fail_sync:
            raise RuntimeError("injected sync failure")
        return {"revision": 1}

    @staticmethod
    def _document_live_network_payload(_snapshot, root_path: str):
        return {
            "$schema": "hocuspocus://schemas/network-document/v1",
            "kind": "network_document",
            "documentId": f"network:{root_path}",
            "documentRevision": 1,
            "rootPath": root_path,
            "category": "Object",
            "nodes": [
                {
                    "uid": f"node:{root_path}",
                    "name": root_path.rsplit("/", 1)[-1],
                    "typeName": "geo",
                    "category": "Object",
                    "path": root_path,
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
            "metadata": {},
        }

    def _document_current_network_payload(
        self, root_path: str, *, force_sync: bool = False
    ):
        del force_sync
        return self._graph_store.get_document_by_root_path(root_path)

    def _document_checkout_delivery(self, checkout, *, additional_payload=None):
        if self._fail_delivery:
            raise RuntimeError("injected delivery failure")
        return super()._document_checkout_delivery(
            checkout, additional_payload=additional_payload
        )


def _assert_retained_state(testcase, tools, retained, *, checkout: bool) -> None:
    testcase.assertEqual(
        retained["retainedState"],
        {"object": True, "graphDocument": True, "checkout": checkout},
    )
    checkout_snapshot = tools._documents.snapshot(retained["checkoutId"])
    testcase.assertEqual(checkout_snapshot is not None, checkout)
    testcase.assertIsNotNone(tools._objects.node("retained"))
    testcase.assertIsNotNone(
        tools._graph_store.get_document_by_root_path("/obj/retained")
    )


def _assert_retirement_failures(testcase, root: Path) -> None:
    retirement_failure = _BootstrapTools(root / "retirement.sqlite3")
    retirement_failure._fail_delivery = True

    def fail_retirement(_checkout_id):
        raise RuntimeError("injected checkout retirement failure")

    retirement_failure._graph_store.delete_checkout_record = fail_retirement
    with testcase.assertRaises(JsonRpcError) as raised:
        retirement_failure._object_create_geometry_impl({"name": "retained"})
    testcase.assertEqual(raised.exception.code, INTERNAL_ERROR)
    testcase.assertEqual(raised.exception.data["rootPath"], "/obj/retained")
    _assert_retained_state(
        testcase, retirement_failure, raised.exception.data, checkout=True
    )

    unconfirmed = _BootstrapTools(root / "unconfirmed-retirement.sqlite3")
    unconfirmed._fail_delivery = True
    unconfirmed._documents.discard = lambda _checkout_id: False
    with testcase.assertRaises(JsonRpcError) as raised:
        unconfirmed._object_create_geometry_impl({"name": "retained"})
    _assert_retained_state(
        testcase, unconfirmed, raised.exception.data, checkout=True
    )

    graph_failure = _BootstrapTools(root / "graph-retirement.sqlite3")
    graph_failure._fail_delivery = True

    def fail_graph_retirement(_admitted):
        raise RuntimeError("injected graph retirement failure")

    graph_failure._graph_store.discard_document_admission = fail_graph_retirement
    with testcase.assertRaises(JsonRpcError) as raised:
        graph_failure._object_create_geometry_impl({"name": "retained"})
    _assert_retained_state(
        testcase, graph_failure, raised.exception.data, checkout=False
    )

    node_failure = _BootstrapTools(root / "node-retirement.sqlite3")
    node_failure._fail_delivery = True
    node_failure._objects.fail_destroy = True
    with testcase.assertRaises(JsonRpcError) as raised:
        node_failure._object_create_geometry_impl({"name": "retained"})
    _assert_retained_state(
        testcase, node_failure, raised.exception.data, checkout=False
    )


def assert_object_geometry_bootstrap(testcase) -> None:
    registered_tools = ToolRegistry()
    LiveOperations.__new__(LiveOperations).register(
        registered_tools, ResourceRegistry()
    )
    definition = registered_tools.get("object.create_geometry")
    testcase.assertIsNotNone(definition)
    testcase.assertTrue(definition.listed)
    testcase.assertEqual(definition.required_capabilities, (EDIT_SCENE,))
    testcase.assertFalse(definition.input_schema["additionalProperties"])
    testcase.assertEqual(
        definition.input_schema["properties"]["name"]["maxLength"], 128
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        tools = _BootstrapTools(root / "success.sqlite3")
        result = tools.object_create_geometry(
            {"name": "asset", "unique_name": False}, RequestContext()
        )["structuredContent"]
        testcase.assertEqual(result["rootPath"], "/obj/asset")
        testcase.assertEqual(result["node"]["typeName"], "geo")
        testcase.assertEqual(result["document"]["rootPath"], "/obj/asset")
        testcase.assertEqual(
            result["document"],
            tools._documents.working_document(result["checkoutId"]),
        )
        current = tools._graph_store.get_document_by_root_path("/obj/asset")
        testcase.assertEqual(
            result["document"]["documentRevision"],
            current["documentRevision"],
        )
        tools._document_assert_expected_revision(
            {}, result["document"], current, "/obj/asset"
        )
        planning = tools._document_apply_impl(
            {"checkout_id": result["checkoutId"], "mode": "validate_only"},
            RequestContext(),
        )
        testcase.assertEqual(planning["mode"], "validate_only")
        testcase.assertTrue(planning["valid"])
        testcase.assertEqual(result["documentDelivery"]["mode"], "inline")
        testcase.assertEqual(
            tools._objects.node("asset").user_data["hpmcp.operation_id"],
            "tool:object.create_geometry",
        )
        testcase.assertEqual(
            tools._tool_capabilities("object.create_geometry"), (EDIT_SCENE,)
        )

        with testcase.assertRaises(JsonRpcError):
            tools._object_create_geometry_impl({"name": "asset"})
        unique = tools._object_create_geometry_impl(
            {"name": "asset", "unique_name": True}
        )
        testcase.assertEqual(unique["rootPath"], "/obj/asset1")
        with testcase.assertRaises(JsonRpcError):
            tools._object_create_geometry_impl({"name": "../unsafe"})

        sync_failure = _BootstrapTools(root / "sync.sqlite3")
        sync_failure._fail_sync = True
        with testcase.assertRaisesRegex(RuntimeError, "sync failure"):
            sync_failure._object_create_geometry_impl(
                {"name": "rolled_back"}
            )
        testcase.assertIsNone(sync_failure._objects.node("rolled_back"))

        delivery_failure = _BootstrapTools(root / "delivery.sqlite3")
        delivery_failure._fail_delivery = True
        with testcase.assertRaisesRegex(RuntimeError, "delivery failure"):
            delivery_failure._object_create_geometry_impl(
                {"name": "rolled_back"}
            )
        testcase.assertIsNone(delivery_failure._objects.node("rolled_back"))
        testcase.assertEqual(delivery_failure._documents._checkouts, {})
        testcase.assertIsNone(
            delivery_failure._graph_store.get_document_by_root_path(
                "/obj/rolled_back"
            )
        )
        with delivery_failure._graph_store._connect() as connection:
            prior_revision = (
                delivery_failure._graph_store._historical_document_revision(
                    connection, "network:/obj/rolled_back"
                )
            )
        delivery_failure._fail_delivery = False
        recreated = delivery_failure._object_create_geometry_impl(
            {"name": "rolled_back"}
        )
        testcase.assertGreater(
            recreated["document"]["documentRevision"], prior_revision
        )

        persistence_failure = _BootstrapTools(root / "persist.sqlite3")

        def fail_persist(_record):
            raise RuntimeError("injected checkout persistence failure")

        persistence_failure._graph_store.save_checkout_record = fail_persist
        with testcase.assertRaisesRegex(RuntimeError, "persistence failure"):
            persistence_failure._object_create_geometry_impl(
                {"name": "rolled_back"}
            )
        testcase.assertEqual(persistence_failure._documents._checkouts, {})
        testcase.assertIsNone(
            persistence_failure._graph_store.get_document_by_root_path(
                "/obj/rolled_back"
            )
        )

        _assert_retirement_failures(testcase, root)

        cas_store = LiveGraphStore(
            logging.getLogger("test.bootstrap.cas"),
            db_path=root / "cas.sqlite3",
        )
        observed = _BootstrapTools._document_live_network_payload(
            {"revision": 1}, "/obj/cas"
        )
        first = cas_store.upsert_document_from_live(
            observed,
            live_revision=1,
            source="test:first",
            force_new_revision=True,
        )
        second = cas_store.upsert_document_from_live(
            observed,
            live_revision=2,
            source="test:second",
            force_new_revision=True,
        )
        testcase.assertGreater(
            second["documentRevision"], first["documentRevision"]
        )
        testcase.assertFalse(cas_store.discard_document_admission(first))
        testcase.assertEqual(
            cas_store.get_document_by_root_path("/obj/cas"), second
        )


__all__ = ["assert_object_geometry_bootstrap"]
