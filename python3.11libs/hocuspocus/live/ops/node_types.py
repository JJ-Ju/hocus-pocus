"""Node type discovery and authoring metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError

from ..context import RequestContext


@dataclass(frozen=True, slots=True)
class _NodeTypeGroup:
    group_id: str
    label: str
    category: str
    description: str
    priority: int
    predicate: Callable[[str, str, set[str]], bool]


_NODE_TYPE_TAG_RULES: dict[str, tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = {
    "Sop": (
        (("box", "tube", "sphere", "grid", "line", "circle", "add", "poly"), ("geometry", "primitive")),
        (("xform", "transform", "align", "matchsize", "bound", "clip", "bend"), ("transform", "alignment")),
        (("copy", "foreach", "block_begin", "block_end"), ("copy", "repeat")),
        (("instance",), ("instance", "copy")),
        (("scatter", "pointsfrom", "point", "pack", "assemble"), ("scatter", "points")),
        (("attrib", "attribute"), ("attribute",)),
        (("wrangle", "vop"), ("vex",)),
        (("group", "blast", "delete", "connectivity", "name"), ("group", "selection")),
        (("boolean", "fuse", "clean", "convert", "bridge", "bevel"), ("boolean", "cleanup")),
        (("vdb", "volume", "cloud", "fog"), ("volume", "vdb")),
        (("constraint", "vellum", "rbd", "collision"), ("constraint", "sim_prep")),
        (("agent", "capture", "armature", "bone", "apex", "kinefx", "character"), ("agent", "character", "apex")),
    ),
    "Object": (
        (("geo", "subnet", "instance", "extractgeo"), ("geometry", "container")),
        (("cam", "camera", "vrcam", "stereo"), ("camera",)),
        (("light", "hlight", "envlight", "ambient"), ("light",)),
        (("alembic", "lopimport", "fetch", "gltf", "import"), ("import", "bridge")),
        (
            ("lopnet", "topnet", "dopnet", "ropnet", "matnet", "shopnet", "copnet", "chopnet"),
            ("network_container",),
        ),
        (("bone", "rig", "mocap", "character"), ("rigging", "character")),
        (("hair", "groom", "guide"), ("hair", "groom")),
        (("path", "handle", "sticky", "sound", "null"), ("utility",)),
    ),
    "Lop": (
        (("reference", "sublayer", "layer", "merge", "stage", "graft"), ("composition", "layering", "usd")),
        (("cube", "sphere", "mesh", "capsule", "cone", "cylinder", "xform", "point", "prim"), ("prim", "transform")),
        (("material", "assignmaterial", "editmaterial"), ("material", "assignment")),
        (("karma", "render", "rendervar", "renderproduct", "rendersettings"), ("render", "karma")),
        (("light", "domelight", "distantlight", "geometrylight", "sky", "portal"), ("light", "environment")),
        (("variant", "component", "asset", "payload"), ("variant", "asset")),
        (("sopimport", "sopmodify", "sopcreate", "sceneimport"), ("sop_bridge", "bridge")),
        (("constraint", "followpath", "lookat", "animation"), ("constraint", "animation")),
    ),
    "Top": (
        (("generator", "wedge", "merge", "null", "genericgenerator"), ("graph_core", "generator")),
        (("python", "script", "mapper", "processor", "partitioner"), ("python", "custom")),
        (("rop", "render", "fetch", "geometryoutput"), ("rop", "submission")),
        (("file", "makedir", "copy", "rename", "remove", "range"), ("file_ops", "filesystem")),
        (("filter", "partition", "sort", "split"), ("filter", "partition")),
        (("json", "csv", "sql", "text"), ("data_io", "io")),
        (("scheduler", "deadline", "tractor", "hqueue", "localscheduler", "inprocessscheduler"), ("scheduler",)),
        (("usd",), ("usd",)),
    ),
}


class NodeTypeOperationsMixin:
    _DISCOVERY_CATEGORY_ALIASES = {
        "obj": "Object",
        "object": "Object",
        "sop": "Sop",
        "lop": "Lop",
        "top": "Top",
    }

    _COMMON_ALIASES = {
        "attribwrangle": ["wrangle", "attribute wrangle"],
        "copytopoints": ["copy to points", "instance to points"],
        "copyxform": ["copy and transform", "repeat transform"],
        "boolean::2.0": ["boolean"],
        "genericgenerator": ["generator"],
        "assignmaterial": ["assign material"],
        "reference": ["usd reference"],
        "geo": ["geometry object"],
        "hlight::2.0": ["light"],
        "cam": ["camera"],
    }

    _COMPATIBILITY_TASKS = {
        "copying": {"copy", "repeat"},
        "instancing": {"instance", "copy"},
        "scatter": {"scatter"},
        "booleans": {"boolean"},
        "attributes": {"attribute"},
        "vex": {"vex"},
        "lighting": {"light"},
        "materials": {"material"},
        "render_export": {"render", "rop", "submission"},
        "usd_composition": {"composition", "layering", "usd"},
        "rbd_setup": {"constraint", "sim_prep"},
    }

    _DISCOVERY_GROUPS = (
        _NodeTypeGroup("sop_geometry_core", "SOP Geometry Core", "Sop", "Core SOP geometry generators and primitive-building nodes.", 10, lambda name, label, tags: bool({"geometry", "primitive"} & tags)),
        _NodeTypeGroup("sop_transforms_alignment", "SOP Transforms and Alignment", "Sop", "Transform, alignment, and bounding-shape helpers.", 20, lambda name, label, tags: "transform" in tags or "alignment" in tags),
        _NodeTypeGroup("sop_copy_instance_repeat", "SOP Copy, Instance, and Repeat", "Sop", "Copying, instancing, and repetition nodes.", 30, lambda name, label, tags: bool({"copy", "instance", "repeat"} & tags)),
        _NodeTypeGroup("sop_attributes_vex", "SOP Attributes and VEX", "Sop", "Attribute manipulation, wrangles, and VEX-oriented SOPs.", 40, lambda name, label, tags: bool({"attribute", "vex"} & tags)),
        _NodeTypeGroup("sop_groups_selection", "SOP Groups and Selection", "Sop", "Grouping, naming, connectivity, and selection logic.", 50, lambda name, label, tags: bool({"group", "selection"} & tags)),
        _NodeTypeGroup("sop_boolean_mesh_cleanup", "SOP Booleans and Cleanup", "Sop", "Boolean, fuse, clean, and mesh-construction tools.", 60, lambda name, label, tags: bool({"boolean", "cleanup"} & tags)),
        _NodeTypeGroup("sop_scatter_points", "SOP Scatter and Points", "Sop", "Scatter, points, packing, and point-prep workflows.", 70, lambda name, label, tags: bool({"scatter", "points"} & tags)),
        _NodeTypeGroup("sop_volumes_vdb", "SOP Volumes and VDB", "Sop", "Volume, cloud, fog, and VDB workflows.", 80, lambda name, label, tags: bool({"volume", "vdb"} & tags)),
        _NodeTypeGroup("sop_sim_prep_constraints", "SOP Sim Prep and Constraints", "Sop", "RBD, vellum, collision, and constraint-prep SOPs.", 90, lambda name, label, tags: bool({"constraint", "sim_prep"} & tags)),
        _NodeTypeGroup("sop_characters_agents_apex", "SOP Characters, Agents, and APEX", "Sop", "Character, crowd, rigging, and APEX graph SOPs.", 100, lambda name, label, tags: bool({"agent", "character", "apex"} & tags)),
        _NodeTypeGroup("obj_geometry_containers", "OBJ Geometry Containers", "Object", "Geometry containers, subnets, instances, and scene structure objects.", 10, lambda name, label, tags: bool({"geometry", "container"} & tags)),
        _NodeTypeGroup("obj_cameras", "OBJ Cameras", "Object", "Camera and stereo-camera objects.", 20, lambda name, label, tags: "camera" in tags),
        _NodeTypeGroup("obj_lights", "OBJ Lights", "Object", "Object-level light nodes and environment lights.", 30, lambda name, label, tags: "light" in tags),
        _NodeTypeGroup("obj_imports_bridges", "OBJ Imports and Bridges", "Object", "Alembic, LOP, and external-scene bridge objects.", 40, lambda name, label, tags: bool({"import", "bridge"} & tags)),
        _NodeTypeGroup("obj_network_containers", "OBJ Network Containers", "Object", "Nested network containers such as `lopnet`, `topnet`, and `dopnet`.", 50, lambda name, label, tags: "network_container" in tags),
        _NodeTypeGroup("obj_rigging_characters", "OBJ Rigging and Characters", "Object", "Bone, autorig, mocap, and deform-rig objects.", 60, lambda name, label, tags: bool({"rigging", "character"} & tags)),
        _NodeTypeGroup("obj_groom_hair", "OBJ Groom and Hair", "Object", "Hair generation, guides, and grooming objects.", 70, lambda name, label, tags: bool({"hair", "groom"} & tags)),
        _NodeTypeGroup("obj_scene_utilities", "OBJ Scene Utilities", "Object", "Paths, handles, sounds, sticky notes, and miscellaneous scene objects.", 80, lambda name, label, tags: "utility" in tags),
        _NodeTypeGroup("lop_stage_composition", "LOP Stage Composition", "Lop", "Layering, referencing, and stage-composition nodes.", 10, lambda name, label, tags: bool({"composition", "layering"} & tags)),
        _NodeTypeGroup("lop_prims_transforms", "LOP Prims and Transforms", "Lop", "Primitive creation and transform authoring nodes.", 20, lambda name, label, tags: bool({"prim", "transform"} & tags)),
        _NodeTypeGroup("lop_materials_assignments", "LOP Materials and Assignments", "Lop", "Material libraries, material edits, and assignments.", 30, lambda name, label, tags: bool({"material", "assignment"} & tags)),
        _NodeTypeGroup("lop_render_products", "LOP Render Products", "Lop", "Render settings, products, vars, and Karma output authoring.", 40, lambda name, label, tags: bool({"render", "karma"} & tags)),
        _NodeTypeGroup("lop_lights_environment", "LOP Lights and Environment", "Lop", "Lights, domes, skies, and environment authoring.", 50, lambda name, label, tags: bool({"light", "environment"} & tags)),
        _NodeTypeGroup("lop_variants_assets", "LOP Variants and Assets", "Lop", "Variants, components, payloads, and asset-level authoring.", 60, lambda name, label, tags: bool({"variant", "asset"} & tags)),
        _NodeTypeGroup("lop_sop_bridges", "LOP SOP Bridges", "Lop", "SOP import/modify/create bridges for Solaris workflows.", 70, lambda name, label, tags: bool({"sop_bridge", "bridge"} & tags)),
        _NodeTypeGroup("lop_constraints_animation", "LOP Constraints and Animation", "Lop", "Constraint and animation helper LOPs.", 80, lambda name, label, tags: bool({"constraint", "animation"} & tags)),
        _NodeTypeGroup("top_graph_core", "TOP Graph Core", "Top", "Core TOP graph structure, generators, wedges, and null/merge nodes.", 10, lambda name, label, tags: bool({"graph_core", "generator"} & tags)),
        _NodeTypeGroup("top_python_custom", "TOP Python and Custom Logic", "Top", "Python processors, scripts, mappers, and custom logic nodes.", 20, lambda name, label, tags: bool({"python", "custom"} & tags)),
        _NodeTypeGroup("top_rop_submission", "TOP ROP Submission", "Top", "ROP submission, fetch, and render/export orchestration nodes.", 30, lambda name, label, tags: bool({"rop", "submission"} & tags)),
        _NodeTypeGroup("top_file_ops", "TOP File Operations", "Top", "File copy, remove, rename, range, and filesystem utilities.", 40, lambda name, label, tags: bool({"file_ops", "filesystem"} & tags)),
        _NodeTypeGroup("top_filter_partition", "TOP Filter and Partition", "Top", "Filtering, partitioning, sorting, and splitting nodes.", 50, lambda name, label, tags: bool({"filter", "partition"} & tags)),
        _NodeTypeGroup("top_data_io", "TOP Data IO", "Top", "JSON, CSV, SQL, and text-processing TOP nodes.", 60, lambda name, label, tags: bool({"data_io", "io"} & tags)),
        _NodeTypeGroup("top_schedulers", "TOP Schedulers", "Top", "Local, in-process, farm, and remote scheduler nodes.", 70, lambda name, label, tags: "scheduler" in tags),
        _NodeTypeGroup("top_usd_workflows", "TOP USD Workflows", "Top", "USD import, render, and USD-specific TOP workflows.", 80, lambda name, label, tags: "usd" in tags),
    )

    def _supported_discovery_categories(self) -> dict[str, Any]:
        hou_module = self._require_hou()
        categories: dict[str, Any] = {}
        for category_name in sorted(set(self._DISCOVERY_CATEGORY_ALIASES.values())):
            category = next(
                (item for item in hou_module.nodeTypeCategories().values() if item.name() == category_name),
                None,
            )
            if category is not None:
                categories[category_name] = category
        return categories

    def _normalize_discovery_category(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if not normalized:
            return None
        if normalized in self._DISCOVERY_CATEGORY_ALIASES:
            return self._DISCOVERY_CATEGORY_ALIASES[normalized]
        if value in self._supported_discovery_categories():
            return value
        return None

    @staticmethod
    def _node_type_sort_key(record: dict[str, Any]) -> tuple[int, str]:
        return (int(record.get("priority", 999)), str(record.get("typeName", "")))

    def _infer_node_type_tags(self, category_name: str, type_name: str, label: str) -> set[str]:
        lower_name = type_name.lower()
        lower_label = label.lower()
        tags: set[str] = set()
        for needles, inferred in _NODE_TYPE_TAG_RULES.get(category_name, ()):
            if any(needle in lower_name or needle in lower_label for needle in needles):
                tags.update(inferred)
        return tags

    def _all_node_type_groups(self) -> list[_NodeTypeGroup]:
        return list(self._DISCOVERY_GROUPS)

    def _node_type_group_for(self, category_name: str, type_name: str, label: str, tags: set[str]) -> _NodeTypeGroup | None:
        candidates = [group for group in self._DISCOVERY_GROUPS if group.category == category_name]
        for group in sorted(candidates, key=lambda item: item.priority):
            if group.predicate(type_name, label, tags):
                return group
        return None

    def _node_type_summary(self, category_name: str, node_type: Any) -> dict[str, Any]:
        type_name = str(node_type.name())
        label = self._safe_value(node_type.description, type_name) or type_name
        tags = self._infer_node_type_tags(category_name, type_name, label)
        group = self._node_type_group_for(category_name, type_name, label, tags)
        aliases = list(self._COMMON_ALIASES.get(type_name, []))
        if not aliases and "wrangle" in type_name.lower():
            aliases = ["wrangle"]
        return {
            "typeName": type_name,
            "label": label,
            "category": category_name,
            "groupId": group.group_id if group is not None else None,
            "aliases": aliases,
            "tags": sorted(tags),
            "descriptionShort": label,
            "inputCountMin": self._safe_value(node_type.minNumInputs, None),
            "inputCountMax": self._safe_value(node_type.maxNumInputs, None),
            "isLabs": type_name.startswith("labs::"),
            "isLegacy": category_name == "Shop" or type_name.startswith("ri_") or type_name.startswith("v_"),
            "priority": group.priority if group is not None else 999,
        }

    def _parm_template_records(self, node_type: Any) -> list[dict[str, Any]]:
        hou_module = self._require_hou()
        group = self._safe_value(node_type.parmTemplateGroup, None)
        if group is None:
            return []

        records: list[dict[str, Any]] = []

        def walk(entries: tuple[Any, ...] | list[Any]) -> None:
            for entry in entries:
                if isinstance(entry, hou_module.FolderParmTemplate):
                    walk(entry.parmTemplates())
                    continue
                parm_type = self._safe_value(lambda entry=entry: str(entry.type().name()), type(entry).__name__)
                record = {
                    "name": self._safe_value(entry.name, ""),
                    "label": self._safe_value(entry.label, ""),
                    "templateType": parm_type,
                    "numComponents": self._safe_value(entry.numComponents, 1),
                }
                default_value = self._safe_value(entry.defaultValue, None)
                if default_value is not None:
                    record["default"] = list(default_value) if isinstance(default_value, tuple) else default_value
                menu_items = self._safe_value(lambda entry=entry: entry.menuItems(), ())
                menu_labels = self._safe_value(lambda entry=entry: entry.menuLabels(), ())
                if menu_items:
                    record["menuItems"] = list(menu_items[:12])
                    if menu_labels:
                        record["menuLabels"] = list(menu_labels[:12])
                records.append(record)

        walk(group.entries())
        return records

    @staticmethod
    def _key_parm_priority(name: str) -> int:
        priorities = [
            ("snippet", 0),
            ("class", 1),
            ("group", 2),
            ("type", 3),
            ("xform", 4),
            ("tx", 5),
            ("ty", 5),
            ("tz", 5),
            ("rx", 6),
            ("ry", 6),
            ("rz", 6),
            ("sx", 7),
            ("sy", 7),
            ("sz", 7),
            ("size", 8),
            ("scale", 9),
            ("seed", 10),
            ("count", 11),
            ("npts", 12),
            ("density", 13),
            ("path", 14),
            ("material", 15),
            ("render", 16),
        ]
        lower = name.lower()
        for needle, priority in priorities:
            if needle in lower:
                return priority
        return 100

    def _resolve_node_type(self, type_name: str, category_name: str | None = None) -> tuple[str, Any]:
        categories = self._supported_discovery_categories()
        if category_name is not None:
            category = categories.get(category_name)
            if category is None:
                raise JsonRpcError(INVALID_PARAMS, f"Unsupported discovery category: {category_name}")
            node_type = category.nodeTypes().get(type_name)
            if node_type is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Node type not found in category {category_name}: {type_name}",
                    {"category": category_name, "typeName": type_name},
                )
            return category_name, node_type

        matches: list[tuple[str, Any]] = []
        for current_name, category in categories.items():
            node_type = category.nodeTypes().get(type_name)
            if node_type is not None:
                matches.append((current_name, node_type))
        if not matches:
            raise JsonRpcError(INVALID_PARAMS, f"Node type not found: {type_name}", {"typeName": type_name})
        if len(matches) > 1:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Node type name is ambiguous without a category: {type_name}",
                {"typeName": type_name, "categories": [item[0] for item in matches]},
            )
        return matches[0]

    def _node_types_list_groups_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        category_name = self._normalize_discovery_category(arguments.get("category"))
        categories = self._supported_discovery_categories()
        groups_payload: list[dict[str, Any]] = []
        for group in self._all_node_type_groups():
            if category_name is not None and group.category != category_name:
                continue
            category = categories.get(group.category)
            estimated_count = 0
            if category is not None:
                for node_type in category.nodeTypes().values():
                    summary = self._node_type_summary(group.category, node_type)
                    if summary["groupId"] == group.group_id:
                        estimated_count += 1
            groups_payload.append(
                {
                    "groupId": group.group_id,
                    "label": group.label,
                    "category": group.category,
                    "description": group.description,
                    "estimatedNodeCount": estimated_count,
                    "priority": group.priority,
                }
            )
        groups_payload.sort(key=lambda item: (item["category"], item["priority"], item["label"]))
        return {"count": len(groups_payload), "groups": groups_payload}

    def node_types_list_groups(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_types_list_groups_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} node-type groups.", data)

    def _node_types_list_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        category_name = self._normalize_discovery_category(arguments.get("category"))
        if arguments.get("category") is not None and category_name is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Unsupported discovery category: {arguments.get('category')}",
                {"supportedCategories": sorted(self._supported_discovery_categories().keys())},
            )
        group_id = str(arguments.get("group_id", "")).strip()
        query = str(arguments.get("query", "")).strip().lower()
        tags_filter = {str(item).strip().lower() for item in arguments.get("tags", []) if str(item).strip()}
        include_labs = bool(arguments.get("include_labs", True))
        include_legacy = bool(arguments.get("include_legacy", True))
        limit = int(arguments.get("limit", 100))
        offset = int(arguments.get("offset", 0))
        if limit <= 0:
            raise JsonRpcError(INVALID_PARAMS, "limit must be greater than 0")
        if offset < 0:
            raise JsonRpcError(INVALID_PARAMS, "offset must be greater than or equal to 0")

        categories = self._supported_discovery_categories()
        category_items = (
            [(category_name, categories[category_name])]
            if category_name is not None
            else sorted(categories.items(), key=lambda item: item[0])
        )
        records: list[dict[str, Any]] = []
        for current_name, category in category_items:
            for node_type in category.nodeTypes().values():
                record = self._node_type_summary(current_name, node_type)
                if not include_labs and record["isLabs"]:
                    continue
                if not include_legacy and record["isLegacy"]:
                    continue
                if group_id and record["groupId"] != group_id:
                    continue
                haystacks = [
                    record["typeName"].lower(),
                    str(record["label"]).lower(),
                    " ".join(str(item).lower() for item in record["aliases"]),
                    " ".join(str(item).lower() for item in record["tags"]),
                ]
                if query and not any(query in item for item in haystacks):
                    continue
                if tags_filter and not tags_filter.issubset(set(record["tags"])):
                    continue
                records.append(record)

        records.sort(key=self._node_type_sort_key)
        total_count = len(records)
        window = records[offset: offset + limit]
        for item in window:
            item.pop("priority", None)
        return {
            "count": len(window),
            "totalCount": total_count,
            "offset": offset,
            "limit": limit,
            "hasMore": (offset + len(window)) < total_count,
            "items": window,
        }

    def node_types_list(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_types_list_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} node types.", data)

    def _node_types_get_info_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        type_name = str(arguments.get("type_name", "")).strip()
        if not type_name:
            raise JsonRpcError(INVALID_PARAMS, "type_name is required")
        category_name = self._normalize_discovery_category(arguments.get("category"))
        detail_level = str(arguments.get("detail_level", "summary")).strip().lower() or "summary"
        if detail_level not in {"summary", "key_parms", "full_parms"}:
            raise JsonRpcError(INVALID_PARAMS, "detail_level must be one of: summary, key_parms, full_parms")

        resolved_category, node_type = self._resolve_node_type(type_name, category_name)
        summary = self._node_type_summary(resolved_category, node_type)
        parm_records = self._parm_template_records(node_type)
        key_parms = sorted(parm_records, key=lambda item: (self._key_parm_priority(str(item["name"])), str(item["name"])))[:12]
        result = {
            "typeName": summary["typeName"],
            "label": summary["label"],
            "category": summary["category"],
            "groupId": summary["groupId"],
            "aliases": summary["aliases"],
            "tags": summary["tags"],
            "descriptionShort": summary["descriptionShort"],
            "inputInfo": {
                "minInputs": summary["inputCountMin"],
                "maxInputs": summary["inputCountMax"],
            },
            "keyParms": key_parms,
            "examples": [
                {"description": f"Create `{summary['typeName']}` under a valid {summary['category']} network and set its key parms."}
            ],
            "commonPatterns": list(summary["tags"][:6]),
            "relatedTypes": [],
        }
        if detail_level == "full_parms":
            result["allParms"] = parm_records
        return result

    def node_types_get_info(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_types_get_info_impl(arguments), context)
        return self._tool_response(f"Returned node-type info for {data['typeName']}.", data)

    def _node_types_list_compatible_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task = str(arguments.get("task", "")).strip().lower()
        if not task:
            raise JsonRpcError(INVALID_PARAMS, "task is required")
        category_name = self._normalize_discovery_category(arguments.get("category"))
        desired_tags = self._COMPATIBILITY_TASKS.get(task)
        if desired_tags is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Unknown compatibility task: {task}",
                {"knownTasks": sorted(self._COMPATIBILITY_TASKS.keys())},
            )
        data = self._node_types_list_impl(
            {
                "category": category_name,
                "tags": sorted(desired_tags),
                "limit": int(arguments.get("limit", 40)),
                "offset": int(arguments.get("offset", 0)),
                "include_labs": bool(arguments.get("include_labs", True)),
                "include_legacy": bool(arguments.get("include_legacy", True)),
            }
        )
        items: list[dict[str, Any]] = []
        for record in data["items"]:
            enriched = dict(record)
            matching_tags = sorted(desired_tags & set(record["tags"]))
            enriched["why"] = f"Matches task `{task}` through tags: {', '.join(matching_tags) if matching_tags else 'none'}"
            enriched["preferredFor"] = task
            items.append(enriched)
        data["items"] = items
        data["task"] = task
        return data

    def node_types_list_compatible(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._node_types_list_compatible_impl(arguments), context)
        return self._tool_response(
            f"Listed {data['count']} node types compatible with task {data['task']}.",
            data,
        )
