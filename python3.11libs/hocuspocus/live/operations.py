"""Live Houdini-backed tools and resources."""

from __future__ import annotations

import logging

from hocuspocus.core.mcp_types import (
    ResourceDefinition,
    ResourceRegistry,
    ToolDefinition,
    ToolRegistry,
)
from hocuspocus.core.settings import ServerSettings

from .dispatcher import LiveCommandDispatcher
from .document_service import LiveDocumentService
from .graph_cache import LiveSceneGraphCache
from .graph_store import LiveGraphStore
from .monitor import SceneEventMonitor
from .ops.base import OperationBaseMixin
from .ops.building_ops import BuildingOperationsMixin
from .ops.dependency_ops import DependencyOperationsMixin
from .ops.document import DocumentOperationsMixin
from .ops.export import ExportOperationsMixin
from .ops.graph import GraphOperationsMixin
from .ops.hda_ops import HdaOperationsMixin
from .ops.high_level import HighLevelOperationsMixin
from .ops.hocusscript import HocusScriptOperationsMixin
from .ops.material import MaterialOperationsMixin
from .ops.node import NodeOperationsMixin
from .ops.node_types import NodeTypeOperationsMixin
from .ops.parm import ParmOperationsMixin
from .ops.package_ops import PackageOperationsMixin
from .ops.pdg_prod_ops import PdgProductionOperationsMixin
from .ops.pdg_ops import PdgOperationsMixin
from .ops.production import ProductionOperationsMixin
from .ops.render_ops import RenderOperationsMixin
from .ops.resources import ResourceOperationsMixin
from .ops.scene import SceneOperationsMixin
from .ops.session import SessionOperationsMixin
from .ops.source_resources import SourceResourceOperationsMixin
from .ops.source_workspace import SourceWorkspaceOperationsMixin
from .ops.tasks_ops import TaskExecutionOperationsMixin
from .ops.usd_ops import UsdOperationsMixin
from .ops.usd_stage_ops import UsdStageOperationsMixin
from .ops.validation import ValidationOperationsMixin
from .ops.viewport import ViewportOperationsMixin
from .tasks import LiveTaskManager


class LiveOperations(
    OperationBaseMixin,
    BuildingOperationsMixin,
    DependencyOperationsMixin,
    DocumentOperationsMixin,
    HocusScriptOperationsMixin,
    SessionOperationsMixin,
    SceneOperationsMixin,
    NodeOperationsMixin,
    NodeTypeOperationsMixin,
    ParmOperationsMixin,
    MaterialOperationsMixin,
    TaskExecutionOperationsMixin,
    ExportOperationsMixin,
    GraphOperationsMixin,
    HdaOperationsMixin,
    PackageOperationsMixin,
    PdgOperationsMixin,
    PdgProductionOperationsMixin,
    UsdOperationsMixin,
    UsdStageOperationsMixin,
    ValidationOperationsMixin,
    ViewportOperationsMixin,
    RenderOperationsMixin,
    HighLevelOperationsMixin,
    ProductionOperationsMixin,
    SourceWorkspaceOperationsMixin,
    SourceResourceOperationsMixin,
    ResourceOperationsMixin,
):
    def __init__(
        self,
        dispatcher: LiveCommandDispatcher,
        monitor: SceneEventMonitor,
        tasks: LiveTaskManager,
        settings: ServerSettings,
        logger: logging.Logger,
    ):
        self._dispatcher = dispatcher
        self._monitor = monitor
        self._tasks = tasks
        self._settings = settings
        self._graph = LiveSceneGraphCache(logger)
        self._graph_store = LiveGraphStore(logger)
        self._documents = LiveDocumentService(logger, self._graph_store)
        self._monitor.add_listener(self._graph_store.on_monitor_event)
        self._logger = logger.getChild("live.operations")
        self._source_workspace_authority = getattr(
            settings, "source_workspace_authority", None,
        )
        self._source_workspace_factory = getattr(
            settings, "source_workspace_factory", None,
        )
        self._source_workspace_service = None

    def register(self, tools: ToolRegistry, resources: ResourceRegistry) -> None:
        document_input_schema = {
            "type": "object",
            "description": (
                "A network document conforming to the canonical resources "
                "hocuspocus://schemas/network-document/v1 or "
                "hocuspocus://schemas/network-document/v2; document.validate also accepts "
                "the scene-document checkout shape."
            ),
            "x-schemaResources": [
                "hocuspocus://schemas/network-document/v1",
                "hocuspocus://schemas/network-document/v2",
            ],
            "oneOf": [
                {
                    "title": "Network Document v1",
                    "properties": {"$schema": {"const": "hocuspocus://schemas/network-document/v1"}},
                    "required": ["$schema"],
                },
                {
                    "title": "Network Document v2",
                    "properties": {"$schema": {"const": "hocuspocus://schemas/network-document/v2"}},
                    "required": ["$schema"],
                },
                {
                    "title": "Scene Document v1",
                    "properties": {"kind": {"const": "scene_document"}},
                    "required": ["kind"],
                },
            ],
        }
        tool_specs = [
            ("session.info", "Session Info", "Return Houdini session state, server version, active operations, recent tasks, and orientation conventions. Use this as the top-level status read before mutating the scene.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_info),
            ("session.list_operations", "List Operations", "List recent live dispatcher operations, including request ids, states, and cancellation flags. This reflects request-scoped work rather than long-running task records.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.session_list_operations),
            ("session.get_operation", "Get Operation Result", "Reconcile one admitted operation by its stable identity without replaying its mutation. Returns bounded terminal result or error only to the authenticated principal that submitted it.", {"type": "object", "additionalProperties": False, "properties": {"operation_id": {"type": "string", "pattern": "^op:[0-9a-f]{32}$"}}, "required": ["operation_id"]}, {"readOnlyHint": True, "idempotentHint": True}, self.session_get_operation),
            ("session.cancel_operation", "Cancel Operation", "Request cancellation for a queued or running dispatcher operation by operation id. Prefer `task.cancel` for long-running cook or render tasks.", {"type": "object", "properties": {"operation_id": {"type": "string"}}, "required": ["operation_id"]}, {"destructiveHint": True}, self.session_cancel_operation),
            ("task.list", "List Tasks", "List recent non-blocking task records such as cooks and renders. Use this to discover task ids for follow-up polling or cancellation.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}}, {"readOnlyHint": True, "idempotentHint": True}, self.task_list),
            ("task.cancel", "Cancel Task", "Request cancellation for a queued or running long-running task by task id. Cancelled render tasks may leave partial output files on disk.", {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}, {"destructiveHint": True}, self.task_cancel),
            ("scene.get_summary", "Scene Summary", "Return a compact scene summary with hip path, dirty state, frame information, selection, and orientation conventions. Use this for a quick read before planning scene edits.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_get_summary),
            ("scene.new", "New Scene", "Start a new empty Houdini scene in the current session. This mutates the current session immediately and clears existing scene content.", {"type": "object", "properties": {}}, {"destructiveHint": True}, self.scene_new),
            ("scene.open_hip", "Open Hip", "Load a hip file into the current Houdini session. This replaces the current scene and is destructive unless the scene is already disposable.", {"type": "object", "properties": {"path": {"type": "string"}, "suppress_save_prompt": {"type": "boolean", "default": True}, "ignore_load_warnings": {"type": "boolean", "default": False}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_open_hip),
            ("scene.merge_hip", "Merge Hip", "Merge a hip file into the current scene without replacing the session. Use this when you want incoming content added on top of the current graph.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, {"destructiveHint": True}, self.scene_merge_hip),
            ("scene.save_hip", "Save Hip", "Save the current scene to the existing hip path or to a new explicit path. Output paths are validated against server write policy and approved roots before saving.", {"type": "object", "properties": {"path": {"type": "string"}, "save_to_recent_files": {"type": "boolean", "default": True}}}, {"destructiveHint": True}, self.scene_save_hip),
            ("scene.undo", "Undo", "Undo the last Houdini operation in the current session. Supply expected_label to guard the exact operation; omit it for backward-compatible top-of-stack behavior.", {"type": "object", "properties": {"expected_label": {"type": "string", "minLength": 1, "maxLength": 512}}}, {"destructiveHint": True}, self.scene_undo),
            ("scene.redo", "Redo", "Redo the last undone Houdini operation in the current session. Supply expected_label to guard the exact operation; omit it for backward-compatible top-of-stack behavior.", {"type": "object", "properties": {"expected_label": {"type": "string", "minLength": 1, "maxLength": 512}}}, {"destructiveHint": True}, self.scene_redo),
            ("scene.create_turntable_camera", "Create Turntable Camera", "Create a target null, rig null, and camera for a simple orbit shot under `/obj`. If `target_path` resolves to geometry, the orbit distance is derived from shared bbox-fit logic so camera and light helpers target assets consistently.", {"type": "object", "properties": {"target_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "camera_name": {"type": "string", "default": "turntable_cam"}, "distance_multiplier": {"type": "number", "default": 2.5}, "activate_viewport_camera": {"type": "boolean", "default": False}}}, {"destructiveHint": True}, self.scene_create_turntable_camera),
            ("hda.list_libraries", "List HDA Libraries", "List installed HDA library files and the first set of definitions they contain. Use this as the top-level discovery read for HDA workflows.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.hda_list_libraries),
            ("hda.list_definitions", "List HDA Definitions", "List HDA definitions from a specific library file or from all currently loaded HDA libraries.", {"type": "object", "properties": {"library_file_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.hda_list_definitions),
            ("hda.get_definition", "Get HDA Definition", "Return metadata, sections, and parm-interface structure for a specific HDA definition resolved by node type name, library file, or HDA instance path.", {"type": "object", "properties": {"node_type_name": {"type": "string"}, "library_file_path": {"type": "string"}, "node_path": {"type": "string"}, "include_sections": {"type": "boolean", "default": True}}}, {"readOnlyHint": True, "idempotentHint": True}, self.hda_get_definition),
            ("hda.get_instance", "Get HDA Instance", "Return HDA instance metadata, current-definition status, spare-parm count, and the effective parm interface for a live node instance.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.hda_get_instance),
            ("hda.get_interface", "Get HDA Interface", "Return the parm interface for either a live HDA instance or a resolved HDA definition.", {"type": "object", "properties": {"node_path": {"type": "string"}, "node_type_name": {"type": "string"}, "library_file_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.hda_get_interface),
            ("hda.install_library", "Install HDA Library", "Install an HDA library file into the current Houdini session from a policy-approved path.", {"type": "object", "properties": {"library_file_path": {"type": "string"}, "force_use_assets": {"type": "boolean", "default": False}}, "required": ["library_file_path"]}, {"destructiveHint": True}, self.hda_install_library),
            ("hda.uninstall_library", "Uninstall HDA Library", "Uninstall an HDA library file from the current Houdini session.", {"type": "object", "properties": {"library_file_path": {"type": "string"}}, "required": ["library_file_path"]}, {"destructiveHint": True}, self.hda_uninstall_library),
            ("hda.reload_library", "Reload HDA Library", "Reload an installed HDA library file from disk.", {"type": "object", "properties": {"library_file_path": {"type": "string"}}, "required": ["library_file_path"]}, {"destructiveHint": True}, self.hda_reload_library),
            ("hda.create_from_subnet", "Create HDA From Subnet", "Turn a subnet-like node into a digital asset saved to a policy-approved HDA file path and return both the new instance and definition summaries.", {"type": "object", "properties": {"node_path": {"type": "string"}, "asset_name": {"type": "string"}, "hda_file_path": {"type": "string"}, "description": {"type": "string"}, "version": {"type": "string"}, "install_path": {"type": "string"}}, "required": ["node_path", "asset_name", "hda_file_path"]}, {"destructiveHint": True}, self.hda_create_from_subnet),
            ("hda.promote_parm", "Promote HDA Parm", "Promote one static internal parm into a locked, current HDA definition without losing its value. Expressions/keyframes are rejected; external libraries must be inside approved write roots. Optional default_value and initial_value override preservation explicitly.", {"type": "object", "additionalProperties": False, "properties": {"instance_path": {"type": "string"}, "source_parm_path": {"type": "string"}, "promoted_name": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}, "promoted_label": {"type": "string"}, "folder_label": {"type": "string"}, "create_reference": {"type": "boolean", "default": True}, "preserve_source_value": {"type": "boolean", "default": True}, "default_value": {}, "initial_value": {}}, "required": ["instance_path", "source_parm_path"]}, {"destructiveHint": True}, self.hda_promote_parm),
            ("hda.set_instance_parms", "Set HDA Instance Parameters", "Set only public interface parameters on an HDA instance, including a locked instance, without unlocking or editing its internal network.", {"type": "object", "additionalProperties": False, "properties": {"instance_path": {"type": "string"}, "assignments": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}, "value": {}}, "required": ["name", "value"]}}}, "required": ["instance_path", "assignments"]}, {"destructiveHint": True}, self.hda_set_instance_parms),
            ("hda.set_definition_version", "Set HDA Definition Version", "Update the version on an embedded definition or an external HDA library inside approved write roots, returning its library identity.", {"type": "object", "properties": {"node_type_name": {"type": "string"}, "library_file_path": {"type": "string"}, "node_path": {"type": "string"}, "version": {"type": "string"}}, "required": ["version"]}, {"destructiveHint": True}, self.hda_set_definition_version),
            ("dependency.scan_scene", "Scan Scene Dependencies", "Scan scene file references and classify them as input, output, USD, or cache dependencies. Missing files and policy issues are reported explicitly.", {"type": "object", "properties": {"root_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.dependency_scan_scene),
            ("dependency.repath", "Repath Dependencies", "Rewrite file-reference parm values by exact match or prefix match. Use `dry_run = true` to preview changes before mutating the scene.", {"type": "object", "properties": {"old_path": {"type": "string"}, "new_path": {"type": "string"}, "match_mode": {"type": "string", "enum": ["exact", "prefix"], "default": "exact"}, "root_path": {"type": "string"}, "dry_run": {"type": "boolean", "default": False}}, "required": ["old_path", "new_path"]}, {"destructiveHint": True}, self.dependency_repath),
            ("cache.get_topology", "Get Cache Topology", "Summarize common cache-producing or cache-consuming nodes such as File Cache, file, and geometry-output nodes. Use this before packaging or publish work.", {"type": "object", "properties": {"root_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.cache_get_topology),
            ("package.preview_scene", "Preview Scene Package", "Preview which files would be collected into a scene package or archive. This reuses the dependency-scan surface and reports both collected and skipped files.", {"type": "object", "properties": {"root_path": {"type": "string"}, "include_hip": {"type": "boolean", "default": True}, "include_outputs": {"type": "boolean", "default": False}, "existing_only": {"type": "boolean", "default": True}, "dependency_scan": {"type": "object"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.package_preview_scene),
            ("package.create_scene_package", "Create Scene Package", "Create a scene package as a zip archive or directory tree at a validated destination. Set `dry_run = true` to preview the package without writing files.", {"type": "object", "properties": {"destination_path": {"type": "string"}, "package_name": {"type": "string"}, "mode": {"type": "string", "enum": ["zip", "directory"], "default": "zip"}, "dry_run": {"type": "boolean", "default": False}, "root_path": {"type": "string"}, "include_hip": {"type": "boolean", "default": True}, "include_outputs": {"type": "boolean", "default": False}, "existing_only": {"type": "boolean", "default": True}, "dependency_scan": {"type": "object"}}}, {"destructiveHint": True}, self.package_create_scene_package),
            ("node_types.list_groups", "List Node Type Groups", "List curated node-type discovery groups for the supported Houdini categories. Use this to browse a smaller conceptual map before searching individual node types.", {"type": "object", "properties": {"category": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.node_types_list_groups),
            ("node_types.list", "List Node Types", "List discoverable node types for supported categories such as SOP, OBJ, LOP, and TOP. This returns compact records with labels, groups, aliases, tags, and input-count hints so agents can discover valid type names without guessing.", {"type": "object", "properties": {"category": {"type": "string"}, "group_id": {"type": "string"}, "query": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "default": 100}, "offset": {"type": "integer", "default": 0}, "include_labs": {"type": "boolean", "default": True}, "include_legacy": {"type": "boolean", "default": True}}}, {"readOnlyHint": True, "idempotentHint": True}, self.node_types_list),
            ("node_types.get_info", "Get Node Type Info", "Return focused metadata for one node type selected by its stable typeId or by type name and optional category. Use `detail_level = full_parms` only when you need the entire surfaced parm list.", {"type": "object", "additionalProperties": False, "properties": {"type_id": {"type": "string"}, "type_name": {"type": "string"}, "category": {"type": "string"}, "detail_level": {"type": "string", "enum": ["summary", "key_parms", "full_parms"], "default": "summary"}}, "oneOf": [{"required": ["type_id"], "not": {"required": ["type_name"]}}, {"required": ["type_name"], "not": {"required": ["type_id"]}}]}, {"readOnlyHint": True, "idempotentHint": True}, self.node_types_get_info),
            ("node_types.list_compatible", "List Compatible Node Types", "Suggest node types using exactly one canonical task or a bounded natural-language intent. Ambiguous intent is rejected with deterministic candidates instead of being guessed.", {"type": "object", "properties": {"task": {"type": "string", "enum": ["copying", "instancing", "scatter", "booleans", "attributes", "vex", "lighting", "materials", "render_export", "usd_composition", "rbd_setup"]}, "intent": {"type": "string", "minLength": 1, "maxLength": 256}, "category": {"type": "string"}, "limit": {"type": "integer", "default": 40}, "offset": {"type": "integer", "default": 0}, "include_labs": {"type": "boolean", "default": True}, "include_legacy": {"type": "boolean", "default": True}}, "oneOf": [{"required": ["task"]}, {"required": ["intent"]}]}, {"readOnlyHint": True, "idempotentHint": True}, self.node_types_list_compatible),
            ("node.list", "List Nodes", "List child nodes under a network path, optionally recursively. Use this for graph discovery when you know the parent network but not the child names.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "recursive": {"type": "boolean", "default": False}, "max_items": {"type": "integer", "default": 200}}}, {"readOnlyHint": True, "idempotentHint": True}, self.node_list),
            ("node.get", "Get Node", "Return summary information for a single node, including flags, inputs, display/render/output node pointers, and optionally parameter summaries. This is the primary structured node read tool.", {"type": "object", "properties": {"path": {"type": "string"}, "include_parms": {"type": "boolean", "default": False}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.node_get),
            ("node.create", "Create Node", "Create a Houdini node under a parent network and return the created node summary. The result includes the final resolved node path, which may differ from the requested name if Houdini renames it.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "node_type_name": {"type": "string"}, "node_name": {"type": "string"}, "run_init_scripts": {"type": "boolean", "default": True}, "load_contents": {"type": "boolean", "default": True}}, "required": ["node_type_name"]}, {"destructiveHint": True}, self.node_create),
            ("object.create_geometry", "Create Geometry Object", "Create one Geometry object under `/obj` and immediately return a document-centric checkout of its editable SOP network. Use this to bootstrap an empty scene before authoring the SOP graph through the document workflow.", {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}, "unique_name": {"type": "boolean", "default": False}}}, {"destructiveHint": True}, self.object_create_geometry),
            ("node.delete", "Delete Node", "Delete one or more nodes by explicit path. Provide either `path` or `paths`; set `ignore_missing = true` for idempotent cleanup behavior.", {"type": "object", "properties": {"path": {"type": "string"}, "paths": {"type": "array", "items": {"type": "string"}}, "ignore_missing": {"type": "boolean", "default": False}}}, {"destructiveHint": True}, self.node_delete),
            ("node.rename", "Rename Node", "Rename a node and return the updated node summary. Use `unique_name` when the requested name may already exist under the same parent.", {"type": "object", "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}, "unique_name": {"type": "boolean", "default": False}}, "required": ["path", "new_name"]}, {"destructiveHint": True}, self.node_rename),
            ("node.connect", "Connect Nodes", "Connect a source node output to a destination node input and return the destination node summary. This mutates only the destination input slot you specify.", {"type": "object", "properties": {"source_node_path": {"type": "string"}, "dest_node_path": {"type": "string"}, "dest_input_index": {"type": "integer", "default": 0}, "source_output_index": {"type": "integer", "default": 0}}, "required": ["source_node_path", "dest_node_path"]}, {"destructiveHint": True}, self.node_connect),
            ("node.disconnect", "Disconnect Node", "Disconnect one input or all inputs from a node and return the updated node summary. If `input_index` is omitted, all current inputs are cleared.", {"type": "object", "properties": {"path": {"type": "string"}, "input_index": {"type": "integer"}}, "required": ["path"]}, {"destructiveHint": True}, self.node_disconnect),
            ("node.move", "Move Node", "Move a node in network-editor space by setting its graph position. This changes the node tile position, not the 3D transform.", {"type": "object", "properties": {"path": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}, "required": ["path", "x", "y"]}, {"destructiveHint": True}, self.node_move),
            ("node.layout", "Layout Nodes", "Auto-layout child nodes under a network and return the resulting child listing. If `child_paths` is omitted, all child nodes under the parent are laid out.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/obj"}, "child_paths": {"type": "array", "items": {"type": "string"}}}}, {"destructiveHint": True}, self.node_layout),
            ("node.set_flags", "Set Node Flags", "Set common node flags such as bypass, display, render, and template, then return the updated node summary. Flag support depends on the underlying Houdini node type.", {"type": "object", "properties": {"path": {"type": "string"}, "bypass": {"type": "boolean"}, "display": {"type": "boolean"}, "render": {"type": "boolean"}, "template": {"type": "boolean"}}, "required": ["path"]}, {"destructiveHint": True}, self.node_set_flags),
            ("graph.query", "Query Graph", "Query the indexed scene graph by path prefix, root path, node type, category, flag, name fragment, or material assignment. This is the main structured graph search tool for agents.", {"type": "object", "properties": {"root_path": {"type": "string"}, "path_prefix": {"type": "string"}, "node_type_name": {"type": "string"}, "category": {"type": "string"}, "name_contains": {"type": "string"}, "material_path": {"type": "string"}, "flag_name": {"type": "string"}, "flag_value": {"type": "boolean"}, "limit": {"type": "integer", "default": 200}}}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_query),
            ("graph.find_upstream", "Find Upstream", "Traverse upstream structural input edges from a starting node path using the indexed scene graph. Use this to understand what feeds a node.", {"type": "object", "properties": {"path": {"type": "string"}, "max_depth": {"type": "integer", "default": 20}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_upstream),
            ("graph.find_downstream", "Find Downstream", "Traverse downstream structural input edges from a starting node path using the indexed scene graph. Use this to understand what a node drives.", {"type": "object", "properties": {"path": {"type": "string"}, "max_depth": {"type": "integer", "default": 20}}, "required": ["path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_downstream),
            ("graph.find_by_type", "Find Nodes By Type", "Return indexed graph nodes that match a Houdini node type name, optionally under a root path.", {"type": "object", "properties": {"node_type_name": {"type": "string"}, "root_path": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, "required": ["node_type_name"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_by_type),
            ("graph.find_by_flag", "Find Nodes By Flag", "Return indexed graph nodes that match a named Houdini flag such as `display`, `render`, `bypass`, or `template`.", {"type": "object", "properties": {"flag_name": {"type": "string"}, "flag_value": {"type": "boolean", "default": True}, "root_path": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, "required": ["flag_name"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_find_by_flag),
            ("graph.batch_edit", "Batch Graph Edit", "Apply a grouped set of node, parm, flag, move, connect, and layout operations in one live request and one undo block. Later operations may reference earlier results via `$ref:<id>` and `$ref:<id>/suffix`; set `transactional = true` to roll back the whole batch on failure.", {"type": "object", "properties": {"label": {"type": "string"}, "transactional": {"type": "boolean", "default": False}, "operations": {"type": "array", "items": {"type": "object"}}}, "required": ["operations"]}, {"destructiveHint": True}, self.graph_batch_edit),
            ("scene.diff", "Diff Scene Graph", "Diff the current indexed scene graph against a previously captured baseline graph snapshot. Use this to compare before and after states outside the live undo stack.", {"type": "object", "properties": {"baseline": {"type": "object"}}, "required": ["baseline"]}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_diff),
            ("graph.diff_subgraph", "Diff Subgraph", "Diff a current rooted subgraph against a previously captured baseline subgraph snapshot.", {"type": "object", "properties": {"root_path": {"type": "string"}, "baseline": {"type": "object"}}, "required": ["root_path", "baseline"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_diff_subgraph),
            ("graph.plan_edit", "Plan Graph Edit", "Simulate a grouped graph patch against the current indexed scene graph and return the predicted diff without mutating Houdini. This uses the same operation shapes as `graph.batch_edit`.", {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object"}}}, "required": ["operations"]}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_plan_edit),
            ("graph.apply_patch", "Apply Graph Patch", "Apply a graph patch using the current batch-edit execution path. Set `dry_run = true` to return only the predicted plan and diff.", {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object"}}, "patch": {"type": "object"}, "transactional": {"type": "boolean", "default": True}, "dry_run": {"type": "boolean", "default": False}, "label": {"type": "string"}}, "required": []}, {"destructiveHint": True}, self.graph_apply_patch),
            ("document.checkout", "Checkout Document", "Create a working copy for a network or scene document. The exact working document is returned inline when it fits the bounded response; larger documents retain a resource URI for retrieval.", {"type": "object", "properties": {"scope": {"type": "string", "enum": ["network", "scene"], "default": "network"}, "root_path": {"type": "string"}}}, {"readOnlyHint": True}, self.document_checkout),
            ("document.validate", "Validate Document", "Validate a supplied canonical network document (discoverable at hocuspocus://schemas/network-document/v1 or /v2), scene document, or existing checkout against document-level graph rules.", {"type": "object", "properties": {"checkout_id": {"type": "string"}, "document": document_input_schema}}, {"readOnlyHint": True, "idempotentHint": True}, self.document_validate),
            ("document.diff", "Diff Document", "Diff a supplied canonical network document (hocuspocus://schemas/network-document/v1 or /v2) or checkout against its baseline.", {"type": "object", "properties": {"checkout_id": {"type": "string"}, "document": document_input_schema}}, {"readOnlyHint": True, "idempotentHint": True}, self.document_diff),
            ("document.apply", "Apply Document", "Apply a canonical network document (hocuspocus://schemas/network-document/v1 or /v2) or checkout using reconcile, merge, or validate-only mode.", {"type": "object", "properties": {"checkout_id": {"type": "string"}, "document": document_input_schema, "expected_document_revision": {"type": "integer"}, "mode": {"type": "string", "enum": ["reconcile", "merge", "validate_only"], "default": "reconcile"}, "label": {"type": "string"}}}, {"destructiveHint": True}, self.document_apply),
            ("document.discard_checkout", "Discard Document Checkout", "Delete a working copy that is no longer needed.", {"type": "object", "properties": {"checkout_id": {"type": "string"}}, "required": ["checkout_id"]}, {"destructiveHint": True}, self.document_discard_checkout),
            ("document.query", "Query Documents", "Query the current document-backed graph surface without materializing a full network document.", {"type": "object", "properties": {"root_path": {"type": "string"}, "path_prefix": {"type": "string"}, "node_type_name": {"type": "string"}, "category": {"type": "string"}, "name_contains": {"type": "string"}, "material_path": {"type": "string"}, "flag_name": {"type": "string"}, "flag_value": {"type": "boolean"}, "limit": {"type": "integer", "default": 200}}}, {"readOnlyHint": True, "idempotentHint": True}, self.document_query),
            ("document.sync_from_houdini", "Sync Documents From Houdini", "Force a document refresh from the live Houdini scene for a network root or for the whole scene manifest.", {"type": "object", "properties": {"root_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.document_sync_from_houdini),
            ("document.compile_source", "Compile HocusScript Source", "Parse, structurally validate, and canonically format unsaved HocusScript without mutating Houdini. This compatibility endpoint returns a span-bearing structural GraphSpec only. For the live guarded path, compile an ordinary project .hocus file with source.project.build, then pass its exact Bundle to document.preview_bundle and document.plan_bundle before document.apply_plan; apply never rereads this source.", {"type": "object", "additionalProperties": False, "properties": {"source": {"type": "string", "maxLength": 1048576}, "source_name": {"type": "string", "maxLength": 1024, "default": "<mcp-source>"}, "strict": {"type": "boolean", "default": True}}, "required": ["source"]}, {"readOnlyHint": True, "idempotentHint": True}, self.document_compile_source),
            ("document.format_source", "Format HocusScript Source", "Validate and canonically format unsaved HocusScript text without reading or writing project files. Invalid source returns exact diagnostics and no formatted text.", {"type": "object", "additionalProperties": False, "properties": {"source": {"type": "string", "maxLength": 1048576}, "source_name": {"type": "string", "maxLength": 1024, "default": "<mcp-source>"}, "strict": {"type": "boolean", "default": True}}, "required": ["source"]}, {"readOnlyHint": True, "idempotentHint": True}, self.document_format_source),
            ("document.complete_source", "Complete HocusScript Source", "Return bounded, deterministic completions for an unsaved HocusScript buffer using the current live Houdini operator catalog. Offsets are Python/Unicode character offsets.", {"type": "object", "additionalProperties": False, "properties": {"source": {"type": "string", "maxLength": 1048576}, "offset": {"type": "integer", "minimum": 0}, "source_name": {"type": "string", "maxLength": 1024, "default": "<mcp-source>"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100}}, "required": ["source", "offset"]}, {"readOnlyHint": True, "idempotentHint": True}, self.document_complete_source),
            ("document.export_source", "Export Network as HocusScript", "Export one supported flat direct-child live SOP, fixed-port material/VOP, LOP, or TOP network as canonical HocusScript plus durable provenance. Emitted source is structurally recompiled and passes exact-catalog semantic and connector validation, but this observational operation neither proves network reconstruction nor publishes a DSL file. Network-document v2 emits language 0.4; unsupported families, locked HDA contents, direct USD state, and dynamic or incomplete connector evidence fail closed with bounded blockers.", {"type": "object", "additionalProperties": False, "properties": {"root_path": {"type": "string"}, "graph_name": {"type": "string", "maxLength": 256}}, "required": ["root_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.document_export_source),
            ("document.preview_bundle", "Preview HocusScript Bundle", "Strictly decode an exact flat Bundle 0.2, frozen module Bundle 0.3, control Bundle 0.4, or value Bundle 0.5, freshly revalidate its authenticated carrier semantics and provenance pins, including catalog/HDA selections, against live Houdini, lower it over the current network-document baseline, and return the candidate document, deterministic diff, destructive summary, and preview-only plan without mutating Houdini or reading DSL project files.", {"type": "object", "additionalProperties": False, "properties": {"bundle": {"type": "object", "properties": {"bundleVersion": {"type": "string", "enum": ["0.2", "0.3", "0.4", "0.5"]}}, "required": ["bundleVersion"]}}, "required": ["bundle"]}, {"readOnlyHint": True, "idempotentHint": True}, self.document_preview_bundle),
            ("document.plan_bundle", "Plan HocusScript Bundle", "Rerun the exact-version live validation of an authenticated flat Bundle 0.2, module Bundle 0.3, control Bundle 0.4, or value Bundle 0.5, including carrier semantics and provenance pins, then persist a versioned immutable apply plan bound to the current session, policy, catalog, capabilities, ownership, revisions, and exact target network.", {"type": "object", "additionalProperties": False, "properties": {"bundle": {"type": "object", "properties": {"bundleVersion": {"type": "string", "enum": ["0.2", "0.3", "0.4", "0.5"]}}, "required": ["bundleVersion"]}, "ttlSeconds": {"type": "integer", "minimum": 30, "maximum": 1800, "default": 900}}, "required": ["bundle"]}, {"readOnlyHint": True}, self.document_plan_bundle),
            ("document.apply_plan", "Apply HocusScript Plan", "Validate immutable plan identity plus live session, policy, catalog, capability, revision, ownership, target, confirmation, lease, idempotency, and cancellation drift gates, then apply only the stored plan without rereading or recompiling HocusScript source.", {"type": "object", "additionalProperties": False, "properties": {"planId": {"type": "string"}, "planHash": {"type": "string"}, "expectedDocumentRevision": {"type": "integer", "minimum": 0}, "expectedLiveRevision": {"type": "integer", "minimum": 0}, "confirmationToken": {"type": "string"}, "idempotencyKey": {"type": "string", "minLength": 8, "maxLength": 256}}, "required": ["planId", "planHash", "expectedDocumentRevision", "expectedLiveRevision", "idempotencyKey"]}, {"destructiveHint": True, "idempotentHint": True}, self.document_apply_plan),
            ("document.discard_plan", "Discard HocusScript Plan", "Revoke an immutable HocusScript apply plan by exact plan ID and hash without mutating Houdini.", {"type": "object", "additionalProperties": False, "properties": {"planId": {"type": "string"}, "planHash": {"type": "string"}}, "required": ["planId", "planHash"]}, {"readOnlyHint": True, "idempotentHint": True}, self.document_discard_plan),
            ("document.apply_quarantines", "List Apply Quarantines", "List network scopes blocked after an apply whose rollback could not be verified.", {"type": "object", "additionalProperties": False, "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.document_apply_quarantines),
            ("document.recover_scope", "Recover Apply Scope", "Force-reimport and validate a quarantined network scope, then release its quarantine only when the canonical document is valid.", {"type": "object", "additionalProperties": False, "properties": {"rootPath": {"type": "string"}}, "required": ["rootPath"]}, {"destructiveHint": True}, self.document_recover_scope),
            ("parm.list", "List Parameters", "List parameters on a node and return normalized parameter summaries. Use filters and pagination for heavy nodes so introspection stays bounded.", {"type": "object", "properties": {"node_path": {"type": "string"}, "name_prefix": {"type": "string"}, "name_contains": {"type": "string"}, "limit": {"type": "integer", "default": 250}, "offset": {"type": "integer", "default": 0}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_list),
            ("parm.get", "Get Parameter", "Return metadata and value information for a single parameter path. This is the primary structured parameter read tool.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_get),
            ("parm.set", "Set Parameter", "Set a parameter value and return the updated parameter summary. This works for standard value assignment, not expression assignment.", {"type": "object", "properties": {"parm_path": {"type": "string"}, "value": {}}, "required": ["parm_path", "value"]}, {"destructiveHint": True}, self.parm_set),
            ("parm.set_many", "Set Many Parameters", "Set many parameter values in one request and one undo group. Use this when creating or configuring a node would otherwise require a long sequence of separate `parm.set` calls.", {"type": "object", "properties": {"assignments": {"type": "array", "items": {"type": "object", "properties": {"parm_path": {"type": "string"}, "value": {}}, "required": ["parm_path", "value"]}}}, "required": ["assignments"]}, {"destructiveHint": True}, self.parm_set_many),
            ("parm.set_expression", "Set Parameter Expression", "Set an HScript or Python expression on a parameter and return the updated parameter summary. Use `language = python` to force Python expression mode.", {"type": "object", "properties": {"parm_path": {"type": "string"}, "expression": {"type": "string"}, "language": {"type": "string", "default": "hscript"}}, "required": ["parm_path", "expression"]}, {"destructiveHint": True}, self.parm_set_expression),
            ("parm.press_button", "Press Button", "Press a button parameter and return the resulting parameter summary. Use this for operator actions implemented as button parms.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"destructiveHint": True}, self.parm_press_button),
            ("parm.revert_to_default", "Revert Parameter", "Revert a parameter to its default value and return the updated parameter summary. This is useful for clearing previous edits or expressions.", {"type": "object", "properties": {"parm_path": {"type": "string"}}, "required": ["parm_path"]}, {"destructiveHint": True}, self.parm_revert_to_default),
            ("material.create", "Create Material", "Create a material node, defaulting to a Principled Shader under `/mat`, and optionally apply common lookdev properties such as base color, roughness, and metallic. This is the quickest way to create a usable material without manually building the network.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/mat"}, "material_type_name": {"type": "string"}, "node_name": {"type": "string"}, "base_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "roughness": {"type": "number"}, "metallic": {"type": "number"}, "emission_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "emission_intensity": {"type": "number"}, "opacity": {"type": "number"}}}, {"destructiveHint": True}, self.material_create),
            ("material.update", "Update Material", "Update common lookdev properties on an existing material node and return the updated material summary. Unsupported properties are reported as skipped rather than causing a silent partial write.", {"type": "object", "properties": {"material_path": {"type": "string"}, "base_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "roughness": {"type": "number"}, "metallic": {"type": "number"}, "emission_color": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}, "emission_intensity": {"type": "number"}, "opacity": {"type": "number"}}, "required": ["material_path"]}, {"destructiveHint": True}, self.material_update),
            ("material.assign", "Assign Material", "Assign a material to a target node by resolving the nearest owner with a `shop_materialpath` parameter. For SOP targets inside a geometry object, this assigns at the object-material level and returns the affected owner node.", {"type": "object", "properties": {"target_node_path": {"type": "string"}, "material_path": {"type": "string"}}, "required": ["target_node_path", "material_path"]}, {"destructiveHint": True}, self.material_assign),
            ("selection.get", "Get Selection", "Return the currently selected node paths in the live Houdini session. This reads scene state only and does not affect the selection.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.selection_get),
            ("selection.set", "Set Selection", "Set the selected node paths in the live Houdini session. If `clear_existing` is true, the previous node selection is cleared first.", {"type": "object", "properties": {"paths": {"type": "array", "items": {"type": "string"}}, "clear_existing": {"type": "boolean", "default": True}}, "required": ["paths"]}, {"destructiveHint": True}, self.selection_set),
            ("playbar.get_state", "Get Playbar State", "Return current frame, FPS, and playbar ranges from the live Houdini session. This is useful for frame-aware task planning.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.playbar_get_state),
            ("playbar.set_frame", "Set Frame", "Set the current Houdini frame and return the updated playbar state. This mutates the live session time.", {"type": "object", "properties": {"frame": {"type": "number"}}, "required": ["frame"]}, {"destructiveHint": True}, self.playbar_set_frame),
            ("pdg.list_graphs", "List PDG Graphs", "List TOP networks and summarize their cook state, graph size, and work-item state counts. Use this to discover PDG graphs before cooking or inspecting them.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.pdg_list_graphs),
            ("pdg.cook", "Cook PDG Graph", "Start a non-blocking PDG graph cook task for a TOP network. Poll the returned task resource for progress, final work-item states, and results.", {"type": "object", "properties": {"graph_path": {"type": "string"}, "dirty_before": {"type": "boolean", "default": False}, "generate_only": {"type": "boolean", "default": False}, "tops_only": {"type": "boolean", "default": False}}, "required": ["graph_path"]}, {"destructiveHint": True}, self.pdg_cook),
            ("pdg.get_workitems", "Get PDG Work Items", "Return work-item state, attributes, and result metadata for a TOP graph or a specific TOP node inside that graph.", {"type": "object", "properties": {"graph_path": {"type": "string"}, "node_path": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, "required": ["graph_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.pdg_get_workitems),
            ("pdg.cancel", "Cancel PDG Cook", "Request cancellation for an active PDG graph cook on a TOP network.", {"type": "object", "properties": {"graph_path": {"type": "string"}}, "required": ["graph_path"]}, {"destructiveHint": True}, self.pdg_cancel),
            ("pdg.get_results", "Get PDG Results", "Return result-data records for cooked PDG work items on a TOP graph or specific TOP node.", {"type": "object", "properties": {"graph_path": {"type": "string"}, "node_path": {"type": "string"}, "limit": {"type": "integer", "default": 200}}, "required": ["graph_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.pdg_get_results),
            ("cook.node", "Cook Node", "Start a non-blocking cook task for a Houdini node and return a task handle immediately. Poll `houdini://tasks/{task_id}` and `houdini://tasks/{task_id}/log` for progress and result data.", {"type": "object", "properties": {"node_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "force": {"type": "boolean", "default": False}}, "required": ["node_path"]}, {"destructiveHint": True}, self.cook_node),
            ("render.rop", "Render ROP", "Start a non-blocking render task for a ROP node and return a task handle immediately. Output paths are validated against server write policy before the render starts.", {"type": "object", "properties": {"node_path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "ignore_inputs": {"type": "boolean", "default": False}, "verbose": {"type": "boolean", "default": True}}, "required": ["node_path"]}, {"destructiveHint": True}, self.render_rop),
            ("export.alembic", "Export Alembic", "Start a non-blocking Alembic export task for a SOP node or a geometry object with a display SOP. If `path` is omitted, HocusPocus writes to a managed export path under its output directory.", {"type": "object", "properties": {"source_node_path": {"type": "string"}, "path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}, "root_path": {"type": "string", "default": "/obj"}}, "required": ["source_node_path"]}, {"destructiveHint": True}, self.export_alembic),
            ("export.usd", "Export USD", "Start a non-blocking USD export task for a LOP node. If `path` is omitted, HocusPocus writes to a managed export path under its output directory.", {"type": "object", "properties": {"node_path": {"type": "string"}, "path": {"type": "string"}, "frame_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3}}, "required": ["node_path"]}, {"destructiveHint": True}, self.export_usd),
            ("lop.create_node", "Create LOP Node", "Create a Solaris LOP node under `/stage` or another LOP network and optionally wire an input node into it.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/stage"}, "node_type_name": {"type": "string"}, "node_name": {"type": "string"}, "input_node_path": {"type": "string"}, "input_index": {"type": "integer", "default": 0}}, "required": ["node_type_name"]}, {"destructiveHint": True}, self.lop_create_node),
            ("usd.assign_material", "Assign USD Material", "Create an Assign Material LOP and author a material binding for a prim pattern. This is intended for Solaris material assignment workflows.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/stage"}, "input_node_path": {"type": "string"}, "prim_pattern": {"type": "string"}, "material_path": {"type": "string"}, "node_name": {"type": "string", "default": "assignmaterial1"}}, "required": ["prim_pattern", "material_path"]}, {"destructiveHint": True}, self.usd_assign_material),
            ("usd.set_variant", "Set USD Variant", "Create a Set Variant LOP for a prim pattern, variant set, and variant name.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/stage"}, "input_node_path": {"type": "string"}, "prim_pattern": {"type": "string"}, "variant_set": {"type": "string"}, "variant_name": {"type": "string"}, "node_name": {"type": "string", "default": "setvariant1"}}, "required": ["prim_pattern", "variant_set", "variant_name"]}, {"destructiveHint": True}, self.usd_set_variant),
            ("usd.add_reference", "Add USD Reference", "Create a Reference LOP and author a file reference at a prim path.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/stage"}, "input_node_path": {"type": "string"}, "prim_path": {"type": "string"}, "file_path": {"type": "string"}, "reference_prim_path": {"type": "string"}, "node_name": {"type": "string", "default": "reference1"}}, "required": ["prim_path", "file_path"]}, {"destructiveHint": True}, self.usd_add_reference),
            ("usd.create_layer_break", "Create USD Layer Break", "Create a Layer Break LOP and, when `save_path` is provided, a Configure Layer LOP with an authored save path.", {"type": "object", "properties": {"parent_path": {"type": "string", "default": "/stage"}, "input_node_path": {"type": "string"}, "save_path": {"type": "string"}, "node_name": {"type": "string", "default": "layerbreak1"}}}, {"destructiveHint": True}, self.usd_create_layer_break),
            ("usd.stage_summary", "USD Stage Summary", "Inspect the composed USD stage at a LOP node, including root/session layers, used layers, default prim, and a prim-path sample.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.usd_stage_summary),
            ("usd.inspect_prim", "Inspect USD Prim", "Inspect a single USD prim at a LOP node, including references, variant sets, child prims, and bound material information.", {"type": "object", "properties": {"node_path": {"type": "string"}, "prim_path": {"type": "string"}}, "required": ["node_path", "prim_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.usd_inspect_prim),
            ("usd.inspect_material_bindings", "Inspect USD Material Bindings", "Inspect bound USD materials under a root prim path on a composed stage.", {"type": "object", "properties": {"node_path": {"type": "string"}, "root_prim_path": {"type": "string", "default": "/"}} , "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.usd_inspect_material_bindings),
            ("usd.validate_stage", "Validate USD Stage", "Validate composed USD stage references and Solaris save-path policy issues for a LOP node.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.usd_validate_stage),
            ("geometry.get_summary", "Geometry Summary", "Return geometry facts for a node with cooked geometry, including counts, bbox, groups, attributes, and discovered material paths. This is the fastest geometry-level reasoning tool for agents.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.geometry_get_summary),
            ("render.inspect_graph", "Inspect Render Graph", "Inspect a ROP node and its upstream ROP input chain, including output paths, frame-range parms, and node-reference parms. Use this before render preflight or task launch.", {"type": "object", "properties": {"node_path": {"type": "string"}, "max_depth": {"type": "integer", "default": 20}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.render_inspect_graph),
            ("render.inspect_outputs", "Inspect Render Outputs", "Inspect a render node's file-output parms and AOV or image-plane parms where the node type exposes them. This is the main output-introspection read tool for renders.", {"type": "object", "properties": {"node_path": {"type": "string"}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.render_inspect_outputs),
            ("render.preflight", "Preflight Render", "Run a render preflight over a ROP chain, checking output-path policy, missing file dependencies, and broken node-reference parms before render launch.", {"type": "object", "properties": {"node_path": {"type": "string"}, "max_depth": {"type": "integer", "default": 20}}, "required": ["node_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.render_preflight),
            ("lookdev.create_three_point_light_rig", "Create Three Point Light Rig", "Create a scale-aware three-point light rig under `/obj`. If `target_path` resolves to geometry, the helper reuses the same bbox-fit logic as the turntable camera and defaults to distant-style lighting for large exterior assets.", {"type": "object", "properties": {"target_path": {"type": "string"}, "rig_name": {"type": "string", "default": "lookdev_rig"}, "target_name": {"type": "string"}, "key_name": {"type": "string"}, "fill_name": {"type": "string"}, "rim_name": {"type": "string"}}}, {"destructiveHint": True}, self.lookdev_create_three_point_light_rig),
            ("pdg.inspect_schedulers", "Inspect PDG Schedulers", "Inspect scheduler nodes under a TOP network, including working directory and scheduler type information.", {"type": "object", "properties": {"graph_path": {"type": "string"}}, "required": ["graph_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.pdg_inspect_schedulers),
            ("pdg.get_workitem_logs", "Get PDG Work Item Logs", "Return stored log messages for PDG work items on a TOP graph or a specific TOP node.", {"type": "object", "properties": {"graph_path": {"type": "string"}, "node_path": {"type": "string"}, "work_item_ids": {"type": "array", "items": {"type": "integer"}}, "limit": {"type": "integer", "default": 200}}, "required": ["graph_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.pdg_get_workitem_logs),
            ("pdg.retry_workitems", "Retry PDG Work", "Dirty a PDG graph or specific TOP node so work can be retried, and optionally restart graph execution.", {"type": "object", "properties": {"graph_path": {"type": "string"}, "node_path": {"type": "string"}, "execute": {"type": "boolean", "default": False}}, "required": ["graph_path"]}, {"destructiveHint": True}, self.pdg_retry_workitems),
            ("pdg.get_graph_state", "Get PDG Graph State", "Return graph summary plus expanded work-item state for a TOP network.", {"type": "object", "properties": {"graph_path": {"type": "string"}, "limit": {"type": "integer", "default": 500}}, "required": ["graph_path"]}, {"readOnlyHint": True, "idempotentHint": True}, self.pdg_get_graph_state),
            ("scene.validate", "Validate Scene", "Run a high-signal validation pass over broken parameter references, USD save-path policy issues, and output-path policy issues.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_validate),
            ("graph.check_errors", "Check Graph Errors", "Check the indexed scene graph for broken parameter references and missing material assignments, optionally within a root path.", {"type": "object", "properties": {"root_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.graph_check_errors),
            ("parm.find_broken_refs", "Find Broken Parameter References", "Return broken absolute parameter references discovered in parameter expressions and channel references.", {"type": "object", "properties": {"root_path": {"type": "string"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.parm_find_broken_refs),
            ("scene.events_recent", "Recent Scene Events", "Return recent monitor events from the live Houdini session, optionally filtered by sequence number.", {"type": "object", "properties": {"limit": {"type": "integer", "default": 100}, "after_sequence": {"type": "integer"}}}, {"readOnlyHint": True, "idempotentHint": True}, self.scene_events_recent),
            ("viewport.get_state", "Get Viewport State", "Return scene viewer, viewport, and current camera information for the active viewport. Use this before snapshot or camera-sensitive operations.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.viewport_get_state),
            ("camera.get_active", "Get Active Camera", "Return the active viewport camera path, or indicate that the viewport is in perspective mode. This is a read-only camera-context check for snapshot and turntable workflows.", {"type": "object", "properties": {}}, {"readOnlyHint": True, "idempotentHint": True}, self.camera_get_active),
            ("viewport.capture", "Capture Viewport", "Capture the current scene viewer viewport to an image file. If `path` is omitted, HocusPocus writes to a managed snapshot path and returns it.", {"type": "object", "properties": {"path": {"type": "string"}}}, {"destructiveHint": True}, self.viewport_capture),
            ("snapshot.capture_viewport", "Capture Viewport Snapshot", "Capture the current scene viewer viewport to an explicit path or a managed snapshot path. Managed snapshots are written under the server snapshot output directory and returned in the result.", {"type": "object", "properties": {"path": {"type": "string"}}}, {"destructiveHint": True}, self.snapshot_capture_viewport),
        ]
        for name, title, description, input_schema, tool_annotations, handler in tool_specs:
            tools.register(
                ToolDefinition(
                    name=name,
                    title=title,
                    description=description,
                    input_schema=input_schema,
                    annotations=tool_annotations,
                    required_capabilities=self._tool_capabilities(name),
                    handler=handler,
                    output_summary=self._tool_output_summary(name),
                    execution_hint=self._tool_execution_hint(name),
                    failure_notes=self._tool_failure_notes(name),
                    examples=self._tool_examples(name),
                )
            )
        self.register_source_tools(tools)
        self.register_production_surface(tools, resources)
        for legacy_name in {
            "graph.query",
            "graph.find_upstream",
            "graph.find_downstream",
            "graph.find_by_type",
            "graph.find_by_flag",
            "graph.batch_edit",
            "scene.diff",
            "graph.diff_subgraph",
            "graph.plan_edit",
            "graph.apply_patch",
            "node.list",
            "node.get",
            "node.create",
            "node.delete",
            "node.rename",
            "node.connect",
            "node.disconnect",
            "node.move",
            "node.layout",
            "node.set_flags",
            "parm.list",
            "parm.get",
            "parm.set",
            "parm.set_many",
            "parm.set_expression",
            "parm.press_button",
            "parm.revert_to_default",
        }:
            tools.set_listed(legacy_name, False)

        resource_specs = [
            ("houdini://session/info", "Session Info", "Current session metadata and server state.", self.read_session_info),
            ("houdini://session/health", "Session Health", "Current dispatcher and monitor status.", self.read_session_health),
            ("houdini://session/policy", "Session Policy", "Active policy profile, effective permissions, and profile presets.", self.read_session_policy),
            ("houdini://session/conventions", "Session Conventions", "Houdini coordinate-system and snapshot conventions for this server.", self.read_session_conventions),
            ("houdini://session/scene-summary", "Scene Summary", "Current scene summary.", self.read_scene_summary),
            ("houdini://documents/scene", "Scene Document", "Scene manifest over root document-capable Houdini networks.", self.read_document_scene),
            ("houdini://documents/hocusscript/fidelity/hs7", "HocusScript HS7 Fidelity Matrix", "Static build policy for supported, preserved-opaque, read-only, and rejected HS7 surfaces.", self.read_hs7_fidelity_matrix),
            ("houdini://documents/schema/network-document/v1", "Network Document Schema v1", "Locked machine-readable schema for the first-wave network document contract.", self.read_document_schema),
            ("houdini://documents/schema/network-document/v2", "Network Document Schema v2", "Strict typed-value network-document contract for the HocusScript 0.4 lane.", self.read_document_schema_v2),
            ("hocuspocus://schemas/network-document/v1", "Network Document Schema v1", "Locked machine-readable schema for the first-wave network document contract.", lambda _context: self._document_resource_response(self._NETWORK_DOCUMENT_SCHEMA_URI, self._document_schema_payload())),
            ("hocuspocus://schemas/network-document/v2", "Network Document Schema v2", "Strict typed-value network-document contract for the HocusScript 0.4 lane.", lambda _context: self._document_resource_response(self._NETWORK_DOCUMENT_SCHEMA_URI_V2, self._document_schema_payload(2))),
            ("houdini://documents/schema/graph-spec/v0.2", "GraphSpec Schema v0.2", "Machine-readable schema for the current HocusScript GraphSpec contract.", self.read_graph_spec_schema),
            ("houdini://documents/schema/graph-spec/v0.3", "GraphSpec Schema v0.3", "Reserved module-expansion GraphSpec contract for HocusScript 0.2.", self.read_module_graph_spec_schema),
            ("houdini://documents/schema/expansion-map/v1", "Expansion Map Schema v1", "Interned module-expansion origin and stack contract referenced by GraphSpec v0.3.", self.read_expansion_map_schema),
            ("houdini://documents/schema/resolved-module-set/v1", "Resolved Module Set Schema v1", "Portable resolved-module, resolver-policy, and expansion-limit contract for HocusScript 0.2.", self.read_resolved_module_set_schema),
            ("houdini://documents/schema/graph-spec/v0.4", "GraphSpec Schema v0.4", "Strict control-language GraphSpec contract in the HocusScript 0.3 compatibility unit.", self.read_control_graph_spec_schema),
            ("houdini://documents/schema/expansion-map/v2", "Expansion Map Schema v2", "Bounded control-expansion origin and stack contract in the HocusScript 0.3 compatibility unit.", self.read_control_expansion_map_schema),
            ("houdini://documents/schema/resolved-module-set/v2", "Resolved Module Set Schema v2", "Portable control-module resolution contract in the HocusScript 0.3 compatibility unit.", self.read_control_resolved_module_set_schema),
            ("houdini://documents/schema/compiled-bundle/v0.4", "Compiled Bundle Schema v0.4", "Portable compiled carrier contract for the HocusScript 0.3 live preview, planning, and guarded-apply lane.", self.read_control_compiled_bundle_schema),
            ("houdini://documents/schema/graph-spec/v0.5", "GraphSpec Schema v0.5", "Strict value-language GraphSpec contract for HocusScript 0.4.", self.read_value_graph_spec_schema),
            ("houdini://documents/schema/expansion-map/v3", "Expansion Map Schema v3", "Bounded value-language expansion origin and stack contract for HocusScript 0.4.", self.read_value_expansion_map_schema),
            ("houdini://documents/schema/resolved-module-set/v3", "Resolved Module Set Schema v3", "Portable value-language module resolution contract for HocusScript 0.4.", self.read_value_resolved_module_set_schema),
            ("houdini://documents/schema/compiled-bundle/v0.5", "Compiled Bundle Schema v0.5", "Portable HocusScript 0.4 carrier admitted by preview, planning, and guarded apply.", self.read_value_compiled_bundle_schema),
            ("houdini://documents/schema/graph-spec/v0.1", "GraphSpec Schema v0.1", "Legacy machine-readable schema retained for safe bundle decoding.", self.read_legacy_graph_spec_schema),
            ("houdini://documents/schema/format-source-output/v1", "Format Source Output Schema v1", "Machine-readable output schema for document.format_source.", self.read_format_source_output_schema),
            ("houdini://documents/schema/complete-source-output/v1", "Complete Source Output Schema v1", "Machine-readable output schema for document.complete_source.", self.read_complete_source_output_schema),
            ("houdini://documents/schema/export-source-output/v1", "Export Source Output Schema v1", "Machine-readable output schema for document.export_source.", self.read_export_source_output_schema),
            ("houdini://documents/schema/preview-bundle-input/v1", "Document Preview Bundle Input Schema v1", "Machine-readable input schema for document.preview_bundle.", self.read_preview_bundle_input_schema),
            ("houdini://documents/schema/preview-bundle-output/v1", "Document Preview Bundle Output Schema v1", "Machine-readable output schema for document.preview_bundle.", self.read_preview_bundle_output_schema),
            ("houdini://documents/schema/plan-bundle-input/v1", "Document Plan Bundle Input Schema v1", "Machine-readable input schema for document.plan_bundle.", self.read_plan_bundle_input_schema),
            ("houdini://documents/schema/plan-bundle-output/v1", "Document Plan Bundle Output Schema v1", "Machine-readable output schema for document.plan_bundle.", self.read_plan_bundle_output_schema),
            ("houdini://documents/schema/apply-plan/v1", "Immutable Apply Plan Schema v1", "Machine-readable schema for stored HocusScript apply plans.", self.read_apply_plan_schema),
            ("houdini://documents/schema/apply-plan-input/v1", "Document Apply Plan Input Schema v1", "Machine-readable input schema for document.apply_plan.", self.read_apply_plan_input_schema),
            ("houdini://graph/scene", "Scene Graph", "Indexed whole-scene graph snapshot.", self.read_graph_scene),
            ("houdini://graph/index", "Graph Index", "Indexed scene-graph cache metadata and revision state.", self.read_graph_index),
            ("houdini://dependencies/scene", "Scene Dependencies", "Whole-scene dependency scan across file parms.", self.read_scene_dependencies),
            ("houdini://caches/topology", "Cache Topology", "Current cache-node topology summary.", self.read_cache_topology),
            ("houdini://packages/preview", "Scene Package Preview", "Default whole-scene package preview.", self.read_package_preview),
            ("houdini://scene/events", "Scene Events", "Recent scene monitor events and revision history.", self.read_scene_events),
            ("houdini://session/selection", "Selection", "Current node selection.", self.read_selection),
            ("houdini://session/playbar", "Playbar", "Current playbar state.", self.read_playbar),
            ("houdini://session/operations", "Operations", "Recent dispatcher operations and cancellation state.", self.read_operations),
            ("houdini://tasks/recent", "Recent Tasks", "Recent task records and progress state.", self.read_tasks_recent),
        ]
        for uri, name, description, reader in resource_specs:
            resources.register(
                ResourceDefinition(
                    uri=uri,
                    name=name,
                    description=description,
                    mime_type="application/json",
                    reader=reader,
                    payload_summary=self._resource_payload_summary(uri),
                    examples=self._resource_examples(uri),
                )
            )

    @staticmethod
    def _tool_output_summary(name: str) -> str:
        summaries = {
            "session.info": "Structured session status with version, hip state, active operations, recent tasks, and conventions.",
            "task.list": "List of task records with ids, states, progress, and metadata.",
            "task.cancel": "Task cancellation acknowledgement plus the latest known task snapshot.",
            "pdg.list_graphs": "List of TOP networks with cook state, work-item counts, and work-item state counts.",
            "pdg.cook": "Immediate task handle for a non-blocking PDG cook plus task resource URIs.",
            "pdg.get_workitems": "List of PDG work-item summaries for a graph or TOP node.",
            "pdg.cancel": "Cancellation acknowledgement plus the latest PDG graph state summary.",
            "pdg.get_results": "List of PDG result-data records grouped by work item.",
            "hda.list_libraries": "List of loaded HDA library files and the first set of definition names they contain.",
            "hda.list_definitions": "List of HDA definitions with library path, version, section counts, and interface summary.",
            "hda.get_definition": "Single HDA definition summary with library path, sections, and parm interface data.",
            "hda.get_instance": "HDA instance summary with node data, definition linkage, and effective interface data.",
            "hda.get_interface": "Parm interface summary for an HDA instance or definition.",
            "hda.install_library": "Installed-library acknowledgement with resolved library path.",
            "hda.uninstall_library": "Uninstalled-library acknowledgement with resolved library path.",
            "hda.reload_library": "Reloaded-library acknowledgement with resolved library path.",
            "hda.create_from_subnet": "Created HDA instance summary plus the new HDA definition summary.",
            "hda.promote_parm": "Updated HDA instance summary plus the promoted parm path and source parm path.",
            "hda.set_definition_version": "Updated HDA definition summary with the new version string.",
            "dependency.scan_scene": "Dependency list plus summary counts for missing files, policy issues, outputs, and caches.",
            "dependency.repath": "Changed, failed, and skipped dependency repath records.",
            "cache.get_topology": "Cache node summaries with mode, file paths, and existing cache outputs.",
            "package.preview_scene": "Package preview with collected entries, skipped entries, and dependency summary reuse.",
            "package.create_scene_package": "Created or dry-run scene package result with destination, written paths, and collected entries.",
            "node.get": "Single normalized node summary, optionally including parameter summaries.",
            "node.create": "Created node summary with final resolved path and flag state.",
            "object.create_geometry": "Created Geometry object summary, resolved SOP root path, checkout metadata, and the exact inline working document when it fits the bounded response.",
            "node.delete": "Counts plus separate deleted and skipped path arrays.",
            "graph.query": "List of indexed graph nodes that match structural filters.",
            "graph.find_upstream": "Traversal result with the starting node, upstream nodes, and traversed edges.",
            "graph.find_downstream": "Traversal result with the starting node, downstream nodes, and traversed edges.",
            "graph.find_by_type": "List of indexed graph nodes that match a type name.",
            "graph.find_by_flag": "List of indexed graph nodes that match a flag value.",
            "graph.batch_edit": "Batch result with refs, per-step results, and failure metadata when the batch errors.",
            "scene.diff": "Graph diff between a baseline scene snapshot and the current scene graph.",
            "graph.diff_subgraph": "Graph diff between a baseline subgraph snapshot and the current rooted subgraph.",
            "graph.plan_edit": "Predicted graph diff, planned refs, and simulated results for a patch without mutation.",
            "graph.apply_patch": "Predicted plan plus actual batch execution result and post-apply revision.",
            "document.checkout": "Checkout metadata plus the exact working document, digest, and byte length inline when the bounded payload fits; larger documents retain their resource URI fallback.",
            "document.validate": "Document validity flag, diagnostic list, and document revision metadata.",
            "document.diff": "Document-level diff payload between a baseline and target network document.",
            "document.apply": "Apply mode result with diagnostics, compiled plan, executed operations, and the refreshed document.",
            "document.discard_checkout": "Discard acknowledgement for a working document checkout.",
            "document.query": "Matched document-oriented graph nodes with their owning network-document URIs.",
            "document.sync_from_houdini": "Refreshed scene or network document projected from the current live Houdini state.",
            "document.compile_source": "Compiler and GraphSpec versions, source digest, structured diagnostics, canonical formatting, and a span-bearing GraphSpec preview.",
            "document.format_source": "Canonical source, input digest, changed flag, and exact diagnostics; invalid source is never recovery-formatted.",
            "document.complete_source": "Live-catalog fingerprint, completion context, replacement span, and bounded deterministic completion items.",
            "document.export_source": "Canonical source text or fail-closed diagnostics, plus durable entity, ownership, managed-field, catalog, revision, and digest provenance.",
            "document.preview_bundle": "Live catalog resolution, canonical target document, deterministic diff and destructive summary, preview-only candidate plan, diagnostics, and a content-addressed preview resource.",
            "node_types.list_groups": "Curated node-type discovery groups for the supported Houdini categories, including counts and priorities.",
            "node_types.list": "Compact node-type records with labels, groups, aliases, tags, and input-count hints.",
            "node_types.get_info": "Focused node-type metadata with category, aliases, tags, input info, and key parameter summaries.",
            "node_types.list_compatible": "Ranked node-type suggestions with the canonical resolved task, exact-task or intent-alias resolution mode, and matched intent terms.",
            "parm.get": "Single normalized parameter summary including raw value, evaluated value, and expression.",
            "parm.set_many": "Count plus normalized summaries for all parameter assignments applied in one undo group.",
            "material.create": "Created material summary plus applied and skipped material property names.",
            "material.update": "Updated material summary plus applied and skipped material property names.",
            "material.assign": "Assignment result with target node, assignment owner node, material summary, and geometry summary when available.",
            "cook.node": "Immediate task handle for a non-blocking cook plus task resource URIs.",
            "render.rop": "Immediate task handle for a non-blocking render plus task resource URIs.",
            "export.alembic": "Immediate task handle for a non-blocking Alembic export plus task resource URIs.",
            "export.usd": "Immediate task handle for a non-blocking USD export plus task resource URIs.",
            "lop.create_node": "Created Solaris node summary with authored prim or layer parameters when available.",
            "usd.assign_material": "Created Assign Material LOP summary with authored prim pattern and material path.",
            "usd.set_variant": "Created Set Variant LOP summary with authored prim pattern, variant set, and variant name.",
            "usd.add_reference": "Created Reference LOP summary with authored prim path, file path, and referenced prim path.",
            "usd.create_layer_break": "Created Layer Break LOP summary and optional Configure Layer summary.",
            "usd.stage_summary": "Composed USD stage summary with layers, default prim, prim count, and prim-path sample.",
            "usd.inspect_prim": "Single USD prim summary with references, variants, child prims, and bound material info.",
            "usd.inspect_material_bindings": "List of composed material bindings under a USD prim subtree.",
            "usd.validate_stage": "USD stage diagnostics covering missing reference files and save-path policy issues.",
            "geometry.get_summary": "Geometry counts, bbox, groups, attributes, discovered material paths, and object-level material path when present.",
            "scene.create_turntable_camera": "Camera, rig, and target node summaries plus frame range, target-fit data, and whether the viewport camera was activated.",
            "render.inspect_graph": "Render-chain nodes, edges, output paths, frame-range parms, and node-reference summaries.",
            "render.inspect_outputs": "File-output parm details, validated output paths, and AOV or image-plane data when supported.",
            "render.preflight": "Render readiness result with blocking issues, graph snapshot, and per-issue details.",
            "lookdev.create_three_point_light_rig": "Target node summary plus authored light types, target-fit data, distances, placement mode, and warnings for the created key, fill, and rim lights.",
            "pdg.inspect_schedulers": "Scheduler node summaries with working directory and scheduler type info.",
            "pdg.get_workitem_logs": "PDG work-item log payloads grouped by work item.",
            "pdg.retry_workitems": "PDG dirty/retry acknowledgement plus refreshed graph summary.",
            "pdg.get_graph_state": "Graph summary plus expanded work-item state for a TOP network.",
            "scene.validate": "Validation summary plus issues for broken parm refs, USD save-path issues, and output-path policy issues.",
            "graph.check_errors": "Indexed graph issues such as broken parameter references and missing material assignments.",
            "parm.find_broken_refs": "Broken absolute parameter references grouped by parm path.",
            "scene.events_recent": "Recent monitor events with sequence numbers, revisions, and timestamps.",
            "snapshot.capture_viewport": "Viewport image path, viewport name, and whether the output path was managed by the server.",
        }
        return summaries.get(name, "")

    @staticmethod
    def _tool_execution_hint(name: str) -> str:
        if name in {"cook.node", "render.rop", "export.alembic", "export.usd", "pdg.cook"}:
            return "non_blocking_task"
        return "blocking"

    @staticmethod
    def _tool_failure_notes(name: str) -> list[str]:
        notes = {
            "graph.batch_edit": [
                "Validation failures return `errorFamily = validation` with the failing operation index.",
                "Transactional mode reports `rolledBack` and may still fail if Houdini rejects rollback steps.",
            ],
            "graph.apply_patch": [
                "Transactional mode reports rollback state when apply fails after partial progress.",
                "Validation errors in referenced paths or parms return `errorFamily = validation`.",
            ],
            "document.checkout": [
                "Use `scope = network` with `root_path` for the first implementation slice; scene checkouts are read-oriented and not intended for live apply.",
            ],
            "document.apply": [
                "This first implementation slice applies network documents by compiling against the current live graph snapshot.",
                "Verification compares the refreshed live document against the requested target document and reports residual differences in-band.",
            ],
            "document.preview_bundle": [
                "The bundle must pass its exact flat Bundle 0.2, module Bundle 0.3, control Bundle 0.4, or value Bundle 0.5 decoder and carry portable project provenance; versions are never coerced.",
                "Catalog, document-revision, ownership, collision, or schema drift blocks the candidate plan without mutating Houdini.",
                "Large preview payloads are returned through a content-addressed resource URI instead of being duplicated inline.",
            ],
            "node.create": [
                "Creation may fail with `errorFamily = validation` when the parent path is not a network.",
                "The returned path may differ from the requested name if Houdini resolves a naming conflict.",
            ],
            "object.create_geometry": [
                "Without `unique_name = true`, an existing object with the requested name is rejected before mutation.",
                "Ordinary synchronization, checkout, or delivery failure removes the new checkout, object, and graph admission before returning the original error.",
                "If checkout or graph retirement fails, or the live object cannot be removed, a typed internal recovery error retains a coherent recoverable state and reports only portable identities and exact retained-state flags.",
            ],
            "node.delete": [
                "Missing nodes return `errorFamily = validation` unless `ignore_missing = true`.",
            ],
            "node_types.get_info": [
                "Use `detail_level = full_parms` only when you need the full surfaced parm list for a specific node type.",
            ],
            "parm.list": [
                "Use `name_prefix`, `name_contains`, `limit`, and `offset` to keep heavy parm listings bounded.",
            ],
            "parm.set_many": [
                "Each assignment requires `parm_path` and `value`; the batch fails on the first invalid assignment.",
            ],
            "scene.save_hip": [
                "Blocked save paths return `errorFamily = policy` when file writes are disabled or outside approved roots.",
            ],
            "scene.create_turntable_camera": [
                "The helper does not activate the viewport camera unless `activate_viewport_camera = true` is requested.",
            ],
            "snapshot.capture_viewport": [
                "Viewport capture can fail with `errorFamily = runtime` if no compatible Scene Viewer is available in the current UI context.",
            ],
            "render.rop": [
                "Returns a task immediately; render-time failures appear on the task resource with `errorFamily = runtime`.",
                "Cancelled renders may leave partial outputs on disk.",
            ],
            "export.alembic": [
                "Policy-blocked output paths return `errorFamily = policy` before task launch.",
            ],
            "export.usd": [
                "Some Solaris graphs can still fail at export time if authored layers resolve to invalid or unavailable paths.",
            ],
            "dependency.repath": [
                "Set `dry_run = true` first when repathing broad prefixes to avoid unintended mass edits.",
            ],
            "package.create_scene_package": [
                "Destination and collected output paths are validated against write policy before packaging begins.",
            ],
            "usd.inspect_material_bindings": [
                "Invalid prim roots return `errorFamily = validation` when the requested prim path is not present on the composed stage.",
            ],
            "usd.validate_stage": [
                "Validation reports issues in-band; only stage-access failures should surface as request errors.",
            ],
            "pdg.retry_workitems": [
                "The tool dirties supported PDG work; actual re-execution depends on the `execute` flag and scheduler state.",
            ],
            "hda.promote_parm": [
                "Parm promotion on locked or unsupported assets may fail with `errorFamily = runtime` if Houdini refuses definition edits.",
            ],
            "lookdev.create_three_point_light_rig": [
                "The helper chooses light type from inferred asset scale; inspect `placementMode` and `lights[].lightType` in the response.",
                "Large exterior assets default to distant-style lighting instead of point lights.",
            ],
        }
        return notes.get(name, [])

    @staticmethod
    def _tool_examples(name: str) -> list[dict[str, object]]:
        examples = {
            "graph.batch_edit": [
                {
                    "description": "Create and wire a small SOP chain with transactional rollback.",
                    "arguments": {
                        "transactional": True,
                        "operations": [
                            {"type": "create_node", "id": "geo", "parent_path": "/obj", "node_type_name": "geo", "node_name": "batch_geo1"},
                            {"type": "create_node", "id": "box", "parent_path": "$ref:geo", "node_type_name": "box", "node_name": "box1"},
                            {"type": "create_node", "id": "out", "parent_path": "$ref:geo", "node_type_name": "null", "node_name": "OUT"},
                            {"type": "connect", "source_node_path": "$ref:box", "dest_node_path": "$ref:out"},
                            {"type": "set_flags", "path": "$ref:out", "display": True, "render": True},
                        ],
                    },
                }
            ],
            "graph.query": [
                {
                    "description": "Find display-flagged null nodes under a geometry object.",
                    "arguments": {"root_path": "/obj/geo1", "node_type_name": "null", "flag_name": "display", "flag_value": True},
                }
            ],
            "node_types.list_groups": [
                {
                    "description": "Browse the curated SOP discovery groups before searching individual node types.",
                    "arguments": {"category": "Sop"},
                }
            ],
            "node_types.list": [
                {
                    "description": "Find SOP node types related to instancing and repetition.",
                    "arguments": {"category": "Sop", "group_id": "sop_copy_instance_repeat", "limit": 25},
                }
            ],
            "node_types.get_info": [
                {
                    "description": "Inspect the key parameter surface for Attribute Wrangle.",
                    "arguments": {"category": "Sop", "type_name": "attribwrangle", "detail_level": "key_parms"},
                }
            ],
            "node_types.list_compatible": [
                {
                    "description": "Ask for SOP node types that match the scattering task.",
                    "arguments": {"task": "scatter", "category": "Sop", "limit": 20},
                },
                {
                    "description": "Resolve a bounded natural-language intent before ranking compatible SOPs.",
                    "arguments": {"intent": "copy geometry onto points", "category": "Sop", "limit": 20},
                },
            ],
            "object.create_geometry": [
                {
                    "description": "Bootstrap an empty scene with one Geometry object and receive its editable SOP checkout inline.",
                    "arguments": {"name": "asset_geo", "unique_name": False},
                }
            ],
            "parm.list": [
                {
                    "description": "Inspect only light-related parms on a heavy light object.",
                    "arguments": {"node_path": "/obj/lookdev_rig_key", "name_prefix": "light_", "limit": 80, "offset": 0},
                }
            ],
            "parm.set_many": [
                {
                    "description": "Configure several key parms on a node in one request.",
                    "arguments": {
                        "assignments": [
                            {"parm_path": "/obj/geo1/box1/sizex", "value": 2.0},
                            {"parm_path": "/obj/geo1/box1/sizey", "value": 5.0},
                            {"parm_path": "/obj/geo1/box1/sizez", "value": 3.0},
                        ]
                    },
                }
            ],
            "graph.plan_edit": [
                {
                    "description": "Preview a simple SOP chain before applying it.",
                    "arguments": {
                        "operations": [
                            {"type": "create_node", "id": "geo", "parent_path": "/obj", "node_type_name": "geo", "node_name": "planned_geo1"},
                            {"type": "create_node", "id": "box", "parent_path": "$ref:geo", "node_type_name": "box", "node_name": "box1"},
                            {"type": "create_node", "id": "out", "parent_path": "$ref:geo", "node_type_name": "null", "node_name": "OUT"},
                            {"type": "connect", "source_node_path": "$ref:box", "dest_node_path": "$ref:out"},
                        ],
                    },
                }
            ],
            "graph.apply_patch": [
                {
                    "description": "Apply a transactional graph patch after previewing it.",
                    "arguments": {
                        "transactional": True,
                        "operations": [
                            {"type": "create_node", "id": "geo", "parent_path": "/obj", "node_type_name": "geo", "node_name": "patched_geo1"},
                            {"type": "create_node", "id": "box", "parent_path": "$ref:geo", "node_type_name": "box", "node_name": "box1"},
                        ],
                    },
                }
            ],
            "document.checkout": [
                {
                    "description": "Create a working copy for a SOP network document.",
                    "arguments": {"scope": "network", "root_path": "/obj/geo1"},
                }
            ],
            "document.validate": [
                {
                    "description": "Validate a checkout after editing its document resource.",
                    "arguments": {"checkout_id": "01234567-89ab-cdef-0123-456789abcdef"},
                }
            ],
            "document.diff": [
                {
                    "description": "Diff a checkout against its baseline network document.",
                    "arguments": {"checkout_id": "01234567-89ab-cdef-0123-456789abcdef"},
                }
            ],
            "document.apply": [
                {
                    "description": "Apply a checked-out SOP network document back into Houdini.",
                    "arguments": {"checkout_id": "01234567-89ab-cdef-0123-456789abcdef", "mode": "reconcile"},
                }
            ],
            "document.discard_checkout": [
                {
                    "description": "Discard a working copy once it is no longer needed.",
                    "arguments": {"checkout_id": "01234567-89ab-cdef-0123-456789abcdef"},
                }
            ],
            "document.query": [
                {
                    "description": "Find display-flagged null nodes and return their owning network-document URIs.",
                    "arguments": {"root_path": "/obj/geo1", "node_type_name": "null", "flag_name": "display", "flag_value": True},
                }
            ],
            "document.sync_from_houdini": [
                {
                    "description": "Force a fresh document projection for a live SOP network.",
                    "arguments": {"root_path": "/obj/geo1"},
                }
            ],
            "document.preview_bundle": [
                {
                    "description": "Preview an offline-compiled, content-addressed HocusScript bundle against the current live network baseline.",
                    "arguments": {"bundle": {"kind": "hocus_compiled_bundle", "bundleVersion": "0.4", "bundleDigest": "sha256:..."}},
                }
            ],
            "document.plan_bundle": [
                {
                    "description": "Persist a guarded immutable plan from one exact authenticated bundle after fresh live semantic resolution.",
                    "arguments": {"bundle": {"kind": "hocus_compiled_bundle", "bundleVersion": "0.3", "bundleDigest": "sha256:..."}, "ttlSeconds": 900},
                }
            ],
            "cook.node": [
                {
                    "description": "Cook a displayable SOP output over a single frame.",
                    "arguments": {"node_path": "/obj/geo1/OUT", "frame_range": [1, 1], "force": True},
                }
            ],
            "render.rop": [
                {
                    "description": "Render a Geometry ROP over a frame range.",
                    "arguments": {"node_path": "/out/geo_rop1", "frame_range": [1, 24], "ignore_inputs": False, "verbose": True},
                }
            ],
            "pdg.cook": [
                {
                    "description": "Cook a TOP network non-blockingly.",
                    "arguments": {"graph_path": "/obj/topnet1", "dirty_before": True},
                }
            ],
            "pdg.get_workitems": [
                {
                    "description": "Inspect work items on a TOP graph.",
                    "arguments": {"graph_path": "/obj/topnet1", "limit": 50},
                }
            ],
            "hda.get_definition": [
                {
                    "description": "Inspect an installed definition by type name.",
                    "arguments": {"node_type_name": "alembicarchive", "include_sections": True},
                }
            ],
            "hda.create_from_subnet": [
                {
                    "description": "Create a test digital asset from a subnet.",
                    "arguments": {"node_path": "/obj/subnet1", "asset_name": "test::asset::1.0", "hda_file_path": "C:/tmp/test_asset.hda"},
                }
            ],
            "dependency.scan_scene": [
                {
                    "description": "Scan the whole scene for file and cache dependencies.",
                    "arguments": {},
                }
            ],
            "dependency.repath": [
                {
                    "description": "Preview a prefix-based texture repath under `/obj/asset1`.",
                    "arguments": {"old_path": "C:/show/tex", "new_path": "D:/mirror/tex", "match_mode": "prefix", "root_path": "/obj/asset1", "dry_run": True},
                }
            ],
            "package.preview_scene": [
                {
                    "description": "Preview a package for the whole scene without collecting output files.",
                    "arguments": {"include_hip": True, "include_outputs": False, "existing_only": True},
                }
            ],
            "package.create_scene_package": [
                {
                    "description": "Create a zip package for the current scene under the managed package output directory.",
                    "arguments": {"package_name": "scene_package", "mode": "zip", "include_hip": True, "include_outputs": False},
                }
            ],
            "export.alembic": [
                {
                    "description": "Export a SOP output to Alembic using a managed export path.",
                    "arguments": {"source_node_path": "/obj/geo1/OUT", "frame_range": [1, 24]},
                }
            ],
            "export.usd": [
                {
                    "description": "Export a LOP node to USD using a managed export path.",
                    "arguments": {"node_path": "/stage/usd_rop_source1", "frame_range": [1, 24]},
                }
            ],
            "material.create": [
                {
                    "description": "Create a principled material with a warm base color.",
                    "arguments": {"node_name": "wall_mat", "base_color": [0.8, 0.7, 0.6], "roughness": 0.45},
                }
            ],
            "lop.create_node": [
                {
                    "description": "Create a Solaris primitive node in `/stage`.",
                    "arguments": {"parent_path": "/stage", "node_type_name": "cube", "node_name": "cube1"},
                }
            ],
            "usd.assign_material": [
                {
                    "description": "Assign a USD material to a prim pattern.",
                    "arguments": {"parent_path": "/stage", "input_node_path": "/stage/cube1", "prim_pattern": "/World/cube1", "material_path": "/Materials/wall_mat"},
                }
            ],
            "usd.add_reference": [
                {
                    "description": "Create a file reference in Solaris.",
                    "arguments": {"parent_path": "/stage", "prim_path": "/World/ref1", "file_path": "C:/tmp/example.usd"},
                }
            ],
            "usd.stage_summary": [
                {
                    "description": "Inspect the composed stage at a LOP output node.",
                    "arguments": {"node_path": "/stage/layerbreak1"},
                }
            ],
            "usd.inspect_prim": [
                {
                    "description": "Inspect a single prim on a composed stage.",
                    "arguments": {"node_path": "/stage/layerbreak1", "prim_path": "/World/cube1"},
                }
            ],
            "usd.inspect_material_bindings": [
                {
                    "description": "Inspect composed material bindings under `/World`.",
                    "arguments": {"node_path": "/stage/layerbreak1", "root_prim_path": "/World"},
                }
            ],
            "usd.validate_stage": [
                {
                    "description": "Validate reference files and save-path policy on a Solaris stage.",
                    "arguments": {"node_path": "/stage/layerbreak1"},
                }
            ],
            "scene.validate": [
                {
                    "description": "Run a full scene validation pass.",
                    "arguments": {},
                }
            ],
            "material.assign": [
                {
                    "description": "Assign a material to a geometry object or SOP-owned object material parm.",
                    "arguments": {"target_node_path": "/obj/geo1/OUT", "material_path": "/mat/wall_mat"},
                }
            ],
            "snapshot.capture_viewport": [
                {
                    "description": "Capture the current viewport to a managed output path.",
                    "arguments": {},
                }
            ],
            "scene.create_turntable_camera": [
                {
                    "description": "Create a turntable rig around a displayable SOP output.",
                    "arguments": {"target_path": "/obj/geo1/OUT", "camera_name": "turntable_cam", "frame_range": [1, 120], "activate_viewport_camera": True},
                }
            ],
            "render.inspect_graph": [
                {
                    "description": "Inspect the ROP input chain feeding a render node.",
                    "arguments": {"node_path": "/out/geo_rop1", "max_depth": 10},
                }
            ],
            "render.preflight": [
                {
                    "description": "Preflight a render node before launching a render task.",
                    "arguments": {"node_path": "/out/geo_rop1"},
                }
            ],
            "pdg.inspect_schedulers": [
                {
                    "description": "Inspect schedulers under a TOP network.",
                    "arguments": {"graph_path": "/tasks/topnet1"},
                }
            ],
            "pdg.get_workitem_logs": [
                {
                    "description": "Inspect work-item logs for a TOP network.",
                    "arguments": {"graph_path": "/tasks/topnet1", "limit": 50},
                }
            ],
            "pdg.retry_workitems": [
                {
                    "description": "Dirty a TOP network so its work can be retried, and restart execution.",
                    "arguments": {"graph_path": "/tasks/topnet1", "execute": True},
                }
            ],
            "pdg.get_graph_state": [
                {
                    "description": "Read graph summary plus work-item state for a TOP network.",
                    "arguments": {"graph_path": "/tasks/topnet1", "limit": 200},
                }
            ],
            "lookdev.create_three_point_light_rig": [
                {
                    "description": "Create a scale-aware three-point light setup for a large exterior asset.",
                    "arguments": {"rig_name": "lookdev_rig", "target_path": "/obj/tower1/OUT"},
                }
            ],
        }
        return examples.get(name, [])

    @staticmethod
    def _resource_payload_summary(uri: str) -> str:
        summaries = {
            "houdini://session/info": "Session-wide status payload with version, active operations, recent tasks, and conventions.",
            "houdini://session/health": "Dispatcher, monitor, and recent-task health snapshot.",
            "houdini://session/policy": "Active policy profile, effective permissions, approved roots, and available profiles.",
            "houdini://session/conventions": "Coordinate-system and snapshot behavior notes for agent planning.",
            "houdini://session/scene-summary": "Compact scene summary with hip state, frame, and selection.",
            "houdini://documents/scene": "Scene manifest over root network documents plus hip and graph metadata.",
            "houdini://documents/hocusscript/fidelity/hs7": "Static path-free HS7 support policy for this server build; no source-workspace grant is required.",
            "houdini://documents/schema/network-document/v1": "Locked machine-readable schema for the first-wave network document contract.",
            "houdini://documents/schema/network-document/v2": "Strict typed-value network-document contract for HocusScript 0.4.",
            "hocuspocus://schemas/network-document/v1": "Locked machine-readable schema for the first-wave network document contract.",
            "hocuspocus://schemas/network-document/v2": "Strict typed-value network-document contract for HocusScript 0.4.",
            "houdini://documents/schema/graph-spec/v0.4": "Strict GraphSpec 0.4 contract for HocusScript 0.3 control-language output.",
            "houdini://documents/schema/expansion-map/v2": "Bounded expansion-map v2 contract paired with GraphSpec 0.4.",
            "houdini://documents/schema/resolved-module-set/v2": "Portable resolved-module-set v2 contract paired with GraphSpec 0.4.",
            "houdini://documents/schema/compiled-bundle/v0.4": "Offline compiled-bundle v0.4 contract for the exact HocusScript 0.3 carrier unit.",
            "houdini://documents/schema/graph-spec/v0.5": "Strict GraphSpec 0.5 contract for HocusScript 0.4 value-language output.",
            "houdini://documents/schema/expansion-map/v3": "Bounded expansion-map v3 contract paired with GraphSpec 0.5.",
            "houdini://documents/schema/resolved-module-set/v3": "Portable resolved-module-set v3 contract paired with GraphSpec 0.5.",
            "houdini://documents/schema/compiled-bundle/v0.5": "Offline compiled-bundle v0.5 contract for the exact HocusScript 0.4 carrier unit.",
            "houdini://documents/schema/format-source-output/v1": "Strict versioned output contract for canonical formatting and exact diagnostics.",
            "houdini://documents/schema/complete-source-output/v1": "Strict versioned output contract for bounded catalog-backed completion.",
            "houdini://documents/schema/export-source-output/v1": "Strict fail-closed source export and durable provenance contract.",
            "houdini://documents/schema/preview-bundle-input/v1": "Strict MCP input contract for document.preview_bundle.",
            "houdini://documents/schema/preview-bundle-output/v1": "Structured preview result contract including catalog resolution, diagnostics, and artifact references.",
            "houdini://documents/schema/plan-bundle-input/v1": "Strict exact-version input contract for document.plan_bundle.",
            "houdini://documents/schema/apply-plan/v1": "Immutable HocusScript plan contract, including guarded new-lane carrier pins.",
            "houdini://graph/scene": "Whole-scene graph snapshot with indexed nodes, parms, edges, and material assignments.",
            "houdini://graph/index": "Graph-cache metadata including revision, counts, and refresh timing.",
            "houdini://dependencies/scene": "Whole-scene dependency scan across file-reference parms with missing-file and policy flags.",
            "houdini://caches/topology": "Cache topology summary for common cache-producing or cache-consuming nodes.",
            "houdini://packages/preview": "Scene-package preview with collected and skipped files using default packaging rules.",
            "houdini://usd/stage/index": "Dynamic USD stage summaries are available through the usd stage resources.",
            "houdini://pdg/graph/index": "Dynamic PDG graph state resources are available through the pdg graph resources.",
            "houdini://scene/events": "Recent monitor events with sequence numbers, revisions, and timestamps.",
            "houdini://session/selection": "Current selected node paths.",
            "houdini://session/playbar": "Current frame, FPS, and playbar ranges.",
            "houdini://session/operations": "Recent request-scoped operation records.",
            "houdini://tasks/recent": "Recent task records for cooks, renders, and other long-running work.",
        }
        return summaries.get(uri, "")

    @staticmethod
    def _resource_examples(uri: str) -> list[dict[str, object]]:
        examples = {
            "houdini://tasks/recent": [
                {"description": "Inspect recent cook and render task state after launching non-blocking work."}
            ],
            "houdini://session/info": [
                {"description": "Read top-level session state before planning graph edits or viewport captures."}
            ],
            "houdini://session/policy": [
                {"description": "Inspect the active policy profile and effective write or edit permissions."}
            ],
            "houdini://documents/scene": [
                {"description": "Read the scene manifest that links to document-capable root networks."}
            ],
            "houdini://documents/hocusscript/fidelity/hs7": [
                {"description": "Inspect exact HS7 support and rejection boundaries before authoring or applying a graph."}
            ],
            "houdini://documents/schema/network-document/v1": [
                {"description": "Read the locked network-document JSON schema used by the document resources and tools."}
            ],
            "houdini://documents/schema/network-document/v2": [
                {"description": "Read the strict typed-value network-document schema used by HocusScript 0.4 preview and apply."}
            ],
            "houdini://documents/schema/graph-spec/v0.4": [
                {"description": "Inspect the strict HocusScript 0.3 graph carrier before consuming offline control output."}
            ],
            "houdini://documents/schema/expansion-map/v2": [
                {"description": "Inspect the exact bounded origin and expansion-stack contract paired with GraphSpec 0.4."}
            ],
            "houdini://documents/schema/resolved-module-set/v2": [
                {"description": "Inspect the portable control-module resolution carrier paired with GraphSpec 0.4."}
            ],
            "houdini://documents/schema/compiled-bundle/v0.4": [
                {"description": "Inspect the exact HocusScript 0.3 bundle carrier admitted by live preview, planning, and guarded apply."}
            ],
            "houdini://documents/schema/graph-spec/v0.5": [
                {"description": "Inspect the strict HocusScript 0.4 graph carrier before consuming value-language output."}
            ],
            "houdini://documents/schema/expansion-map/v3": [
                {"description": "Inspect bounded value-language origins and expansion stacks paired with GraphSpec 0.5."}
            ],
            "houdini://documents/schema/resolved-module-set/v3": [
                {"description": "Inspect the portable HocusScript 0.4 module-resolution carrier."}
            ],
            "houdini://documents/schema/compiled-bundle/v0.5": [
                {"description": "Inspect the HocusScript 0.4 bundle admitted by live preview, planning, and guarded apply."}
            ],
            "houdini://documents/schema/preview-bundle-input/v1": [
                {"description": "Inspect the exact input boundary before passing an offline compiled bundle to Houdini."}
            ],
            "houdini://documents/schema/preview-bundle-output/v1": [
                {"description": "Inspect the preview result and content-addressed artifact-reference contract."}
            ],
            "houdini://documents/schema/plan-bundle-input/v1": [
                {"description": "Inspect the exact admitted Bundle 0.2, 0.3, 0.4, and 0.5 planning boundary."}
            ],
            "houdini://documents/schema/apply-plan/v1": [
                {"description": "Inspect immutable plan identity, revision, capability, policy, carrier, and rollback pins."}
            ],
            "houdini://graph/scene": [
                {"description": "Load the current indexed scene graph as a single resource snapshot."}
            ],
            "houdini://dependencies/scene": [
                {"description": "Read the latest whole-scene dependency scan without rescanning manually."}
            ],
            "houdini://caches/topology": [
                {"description": "Inspect common cache nodes and their file paths."}
            ],
            "houdini://packages/preview": [
                {"description": "Inspect what would be packaged before writing an archive or directory package."}
            ],
            "houdini://usd/stage/index": [
                {"description": "Use the dynamic USD stage resources to inspect Solaris stage state."}
            ],
            "houdini://pdg/graph/index": [
                {"description": "Use the dynamic PDG graph resources to inspect scheduler and work-item state."}
            ],
            "houdini://scene/events": [
                {"description": "Read recent scene monitor events without polling individual state resources."}
            ],
        }
        return examples.get(uri, [])
