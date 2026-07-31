"""HDA and asset-library operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class HdaOperationsMixin:
    @staticmethod
    def _hda_append_promoted_template(
        hou_module: Any,
        definition: Any,
        template: Any,
        folder_label: str | None,
    ) -> None:
        group = definition.parmTemplateGroup()
        folder = group.findFolder(folder_label) if folder_label else None
        if folder is not None:
            group.appendToFolder(folder, template)
        elif folder_label:
            folder_template = hou_module.FolderParmTemplate(
                folder_label.lower().replace(" ", "_"), folder_label
            )
            folder_template.addParmTemplate(template)
            group.append(folder_template)
        else:
            group.append(template)
        definition.setParmTemplateGroup(
            group, rename_conflicting_parms=True, create_backup=True
        )

    @staticmethod
    def _hda_promoted_paths(instance: Any, promoted_name: str, source_index: int):
        promoted_parm = instance.parm(promoted_name)
        promoted_tuple = instance.parmTuple(promoted_name)
        if promoted_tuple is not None:
            paths = [parm.path() for parm in promoted_tuple]
            component = (
                promoted_tuple[source_index].path()
                if source_index < len(promoted_tuple)
                else None
            )
            return component, paths, promoted_name
        component = promoted_parm.path() if promoted_parm is not None else None
        return component, [component] if component is not None else [], None

    def _hda_create_promoted_reference(
        self,
        instance: Any,
        definition: Any,
        source_parm_path: str,
        source_tuple: Any,
        promoted_component_path: str,
        promoted_tuple_name: str | None,
    ) -> None:
        instance.allowEditingOfContents()
        source_parm = self._require_parm_by_path(source_parm_path)
        promoted_component = self._require_parm_by_path(promoted_component_path)
        live_source_tuple = self._safe_value(source_parm.tuple, None)
        live_source_tuple = live_source_tuple() if callable(live_source_tuple) else live_source_tuple
        live_promoted_tuple = (
            instance.parmTuple(promoted_tuple_name) if promoted_tuple_name else None
        )
        if source_tuple is not None and live_source_tuple is not None and live_promoted_tuple is not None:
            live_source_tuple.set(live_promoted_tuple)
        else:
            source_parm.set(promoted_component)
        definition.updateFromNode(instance)
        instance.matchCurrentDefinition()

    def _hda_definition_summary(self, definition: Any, *, include_sections: bool = True) -> dict[str, Any]:
        sections_payload = []
        if include_sections:
            for name, section in dict(self._safe_value(definition.sections, {}) or {}).items():
                sections_payload.append(
                    {
                        "name": str(name),
                        "size": self._safe_value(section.size, None),
                    }
                )
        ptg = self._safe_value(definition.parmTemplateGroup, None)
        interface = self._parm_template_group_summary(ptg() if callable(ptg) else ptg)
        return {
            "nodeTypeName": self._safe_value(definition.nodeTypeName, None),
            "description": self._safe_value(definition.description, None),
            "libraryFilePath": self._safe_value(definition.libraryFilePath, None),
            "version": self._safe_value(definition.version, None),
            "nodeTypeCategory": self._safe_value(lambda: definition.nodeTypeCategory().name(), None),
            "isInstalled": bool(self._safe_value(definition.isInstalled, False)),
            "modificationTime": self._safe_value(definition.modificationTime, None),
            "icon": self._safe_value(definition.icon, None),
            "sectionCount": len(sections_payload),
            "sections": sections_payload,
            "interface": interface,
        }

    def _parm_template_entry_summary(self, template: Any) -> dict[str, Any]:
        entry = {
            "name": self._safe_value(template.name, None),
            "label": self._safe_value(template.label, None),
            "type": self._safe_value(lambda: template.type().name(), None),
            "isHidden": bool(self._safe_value(template.isHidden, False)),
        }
        folder_type = self._safe_value(getattr(template, "folderType", None), None)
        if folder_type is not None:
            entry["folderType"] = self._safe_value(lambda folder_type=folder_type: folder_type().name(), str(folder_type))
        child_templates = self._safe_value(getattr(template, "parmTemplates", None), None)
        if callable(child_templates):
            children = list(child_templates() or [])
            entry["children"] = [self._parm_template_entry_summary(child) for child in children]
        return entry

    def _parm_template_group_summary(self, group: Any) -> dict[str, Any]:
        if group is None:
            return {"count": 0, "entries": []}
        entries = list(self._safe_value(group.entries, []) or [])
        return {
            "count": len(entries),
            "entries": [self._parm_template_entry_summary(entry) for entry in entries],
        }

    def _hda_instance_summary(self, node: Any) -> dict[str, Any]:
        definition = self._safe_value(lambda: node.type().definition(), None)
        return {
            "node": self._node_summary(node, include_parms=False),
            "matchesCurrentDefinition": bool(self._safe_value(node.matchesCurrentDefinition, False)),
            "isLockedHDA": bool(self._safe_value(node.isLockedHDA, False)),
            "definition": self._hda_definition_summary(definition, include_sections=False) if definition is not None else None,
            "spareParmCount": len(self._safe_value(node.spareParms, []) or []),
            "interface": self._parm_template_group_summary(self._safe_value(node.parmTemplateGroup, None)),
        }

    def _resolve_definition(
        self,
        *,
        node_type_name: str | None = None,
        library_file_path: str | None = None,
        node_path: str | None = None,
    ) -> Any:
        hou_module = self._require_hou()
        if node_path:
            node = self._require_node_by_path(node_path, label="node_path")
            definition = self._safe_value(lambda: node.type().definition(), None)
            if definition is None:
                raise JsonRpcError(INVALID_PARAMS, f"Node is not backed by an HDA definition: {node_path}")
            return definition
        if library_file_path:
            for definition in hou_module.hda.definitionsInFile(library_file_path):
                if node_type_name is None or definition.nodeTypeName() == node_type_name:
                    return definition
            raise JsonRpcError(
                INVALID_PARAMS,
                "No matching HDA definition found in the requested library.",
                {"nodeTypeName": node_type_name, "libraryFilePath": library_file_path},
            )
        if node_type_name:
            for category in (
                hou_module.objNodeTypeCategory(),
                hou_module.sopNodeTypeCategory(),
                hou_module.ropNodeTypeCategory(),
                hou_module.vopNodeTypeCategory(),
                hou_module.topNodeTypeCategory(),
            ):
                node_type = category.nodeTypes().get(node_type_name)
                if node_type is None:
                    continue
                definition = self._safe_value(node_type.definition, None)
                if definition is not None:
                    return definition
        raise JsonRpcError(INVALID_PARAMS, "Could not resolve an HDA definition from the provided arguments.")

    def _hda_list_libraries_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        libraries = []
        for library_path in hou_module.hda.loadedFiles():
            definitions = list(hou_module.hda.definitionsInFile(library_path))
            libraries.append(
                {
                    "libraryFilePath": library_path,
                    "definitionCount": len(definitions),
                    "nodeTypeNames": [definition.nodeTypeName() for definition in definitions[:100]],
                }
            )
        return {"count": len(libraries), "libraries": libraries}

    def hda_list_libraries(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_list_libraries_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} HDA library file(s).", data)

    def _hda_list_definitions_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        library_file_path = str(arguments.get("library_file_path", "")).strip() or None
        definitions = []
        if library_file_path:
            defs = list(hou_module.hda.definitionsInFile(library_file_path))
        else:
            defs = []
            seen = set()
            for library_path in hou_module.hda.loadedFiles():
                for definition in hou_module.hda.definitionsInFile(library_path):
                    key = (definition.nodeTypeName(), definition.libraryFilePath())
                    if key in seen:
                        continue
                    seen.add(key)
                    defs.append(definition)
        for definition in defs:
            definitions.append(self._hda_definition_summary(definition, include_sections=False))
        return {"count": len(definitions), "definitions": definitions}

    def hda_list_definitions(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_list_definitions_impl(arguments), context)
        return self._tool_response(f"Listed {data['count']} HDA definition(s).", data)

    def _hda_get_definition_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        definition = self._resolve_definition(
            node_type_name=str(arguments.get("node_type_name", "")).strip() or None,
            library_file_path=str(arguments.get("library_file_path", "")).strip() or None,
            node_path=str(arguments.get("node_path", "")).strip() or None,
        )
        return self._hda_definition_summary(definition, include_sections=bool(arguments.get("include_sections", True)))

    def hda_get_definition(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_get_definition_impl(arguments), context)
        return self._tool_response(f"Returned HDA definition {data['nodeTypeName']}.", data)

    def _hda_get_instance_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        if not node_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path is required")
        node = self._require_node_by_path(node_path, label="node_path")
        definition = self._safe_value(lambda: node.type().definition(), None)
        if definition is None:
            raise JsonRpcError(INVALID_PARAMS, f"Node is not an HDA instance: {node_path}")
        return self._hda_instance_summary(node)

    def hda_get_instance(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_get_instance_impl(arguments), context)
        return self._tool_response(f"Returned HDA instance data for {data['node']['path']}.", data)

    def _hda_get_interface_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip() or None
        if node_path:
            node = self._require_node_by_path(node_path, label="node_path")
            return {
                "source": "instance",
                "nodePath": node.path(),
                "interface": self._parm_template_group_summary(node.parmTemplateGroup()),
            }
        definition = self._resolve_definition(
            node_type_name=str(arguments.get("node_type_name", "")).strip() or None,
            library_file_path=str(arguments.get("library_file_path", "")).strip() or None,
        )
        return {
            "source": "definition",
            "nodeTypeName": definition.nodeTypeName(),
            "libraryFilePath": definition.libraryFilePath(),
            "interface": self._parm_template_group_summary(definition.parmTemplateGroup()),
        }

    def hda_get_interface(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_get_interface_impl(arguments), context)
        return self._tool_response("Returned HDA parm interface.", data)

    def _hda_install_library_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        library_file_path = str(arguments.get("library_file_path", "")).strip()
        if not library_file_path:
            raise JsonRpcError(INVALID_PARAMS, "library_file_path is required")
        resolved = ensure_path_allowed(library_file_path, self._settings)
        hou_module.hda.installFile(str(resolved), force_use_assets=bool(arguments.get("force_use_assets", False)))
        return {"libraryFilePath": str(resolved), "installed": True}

    def hda_install_library(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_install_library_impl(arguments), context)
        return self._tool_response(f"Installed HDA library {data['libraryFilePath']}.", data)

    def _hda_uninstall_library_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        library_file_path = str(arguments.get("library_file_path", "")).strip()
        if not library_file_path:
            raise JsonRpcError(INVALID_PARAMS, "library_file_path is required")
        resolved = Path(library_file_path).expanduser().resolve(strict=False)
        hou_module.hda.uninstallFile(str(resolved))
        return {"libraryFilePath": str(resolved), "installed": False}

    def hda_uninstall_library(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_uninstall_library_impl(arguments), context)
        return self._tool_response(f"Uninstalled HDA library {data['libraryFilePath']}.", data)

    def _hda_reload_library_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        library_file_path = str(arguments.get("library_file_path", "")).strip()
        if not library_file_path:
            raise JsonRpcError(INVALID_PARAMS, "library_file_path is required")
        resolved = Path(library_file_path).expanduser().resolve(strict=False)
        hou_module.hda.reloadFile(str(resolved))
        return {"libraryFilePath": str(resolved), "reloaded": True}

    def hda_reload_library(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_reload_library_impl(arguments), context)
        return self._tool_response(f"Reloaded HDA library {data['libraryFilePath']}.", data)

    def _hda_create_from_subnet_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        node_path = str(arguments.get("node_path", "")).strip()
        asset_name = str(arguments.get("asset_name", "")).strip()
        hda_file_path = str(arguments.get("hda_file_path", "")).strip()
        if not node_path or not asset_name or not hda_file_path:
            raise JsonRpcError(INVALID_PARAMS, "node_path, asset_name, and hda_file_path are required")
        node = self._require_node_by_path(node_path, label="node_path")
        resolved_path = ensure_path_allowed(hda_file_path, self._settings)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        created = node.createDigitalAsset(
            name=asset_name,
            hda_file_name=str(resolved_path),
            description=str(arguments.get("description", "")).strip() or None,
            version=str(arguments.get("version", "")).strip() or None,
            install_path=str(arguments.get("install_path", "")).strip() or None,
            create_backup=True,
        )
        definition = created.type().definition()
        return {
            "node": self._hda_instance_summary(created),
            "definition": self._hda_definition_summary(definition),
        }

    def hda_create_from_subnet(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_create_from_subnet_impl(arguments), context)
        return self._tool_response(f"Created digital asset {data['definition']['nodeTypeName']}.", data)

    def _hda_promote_parm_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        instance_path = str(arguments.get("instance_path", "")).strip()
        source_parm_path = str(arguments.get("source_parm_path", "")).strip()
        if not instance_path or not source_parm_path:
            raise JsonRpcError(INVALID_PARAMS, "instance_path and source_parm_path are required")
        instance = self._require_node_by_path(instance_path, label="instance_path")
        definition = self._safe_value(lambda: instance.type().definition(), None)
        if definition is None:
            raise JsonRpcError(INVALID_PARAMS, f"Node is not backed by an HDA definition: {instance_path}")
        source_parm = self._require_parm_by_path(source_parm_path)
        source_node = self._safe_value(source_parm.node, None)
        if source_node is None or not source_node.path().startswith(f"{instance.path()}/"):
            raise JsonRpcError(
                INVALID_PARAMS,
                "source_parm_path must point to an internal parm under the target HDA instance.",
                {"instancePath": instance.path(), "sourceParmPath": source_parm_path},
            )
        source_tuple = self._safe_value(source_parm.tuple, None)
        source_tuple = source_tuple() if callable(source_tuple) else source_tuple

        promoted_name = str(arguments.get("promoted_name", "")).strip() or source_parm.name()
        promoted_label = str(arguments.get("promoted_label", "")).strip() or self._safe_value(lambda: source_parm.parmTemplate().label(), source_parm.name())
        folder_label = str(arguments.get("folder_label", "")).strip() or None
        create_reference = bool(arguments.get("create_reference", True))

        template_source = source_tuple.parmTemplate() if source_tuple is not None else source_parm.parmTemplate()
        template = template_source.clone()
        template.setName(promoted_name)
        template.setLabel(promoted_label)
        self._hda_append_promoted_template(hou_module, definition, template, folder_label)
        instance.matchCurrentDefinition()

        source_parms = list(source_tuple) if source_tuple is not None else []
        source_index = source_parms.index(source_parm) if source_parm in source_parms else 0
        promoted_component_path, promoted_paths, promoted_tuple_name = (
            self._hda_promoted_paths(instance, promoted_name, source_index)
        )

        if create_reference and promoted_component_path is not None:
            self._hda_create_promoted_reference(
                instance,
                definition,
                source_parm_path,
                source_tuple,
                promoted_component_path,
                promoted_tuple_name,
            )
            source_parm = self._require_parm_by_path(source_parm_path)
            promoted_component_path, promoted_paths, promoted_tuple_name = (
                self._hda_promoted_paths(instance, promoted_name, source_index)
            )

        return {
            "instance": self._hda_instance_summary(instance),
            "promotedParmPath": promoted_component_path,
            "promotedParmPaths": promoted_paths,
            "promotedParmTupleName": promoted_tuple_name,
            "sourceParmPath": source_parm.path(),
            "createReference": create_reference,
        }

    def hda_promote_parm(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_promote_parm_impl(arguments), context)
        return self._tool_response(f"Promoted parm {data['sourceParmPath']}.", data)

    def _hda_set_definition_version_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        version = str(arguments.get("version", "")).strip()
        if not version:
            raise JsonRpcError(INVALID_PARAMS, "version is required")
        definition = self._resolve_definition(
            node_type_name=str(arguments.get("node_type_name", "")).strip() or None,
            library_file_path=str(arguments.get("library_file_path", "")).strip() or None,
            node_path=str(arguments.get("node_path", "")).strip() or None,
        )
        definition.setVersion(version)
        return self._hda_definition_summary(definition)

    def hda_set_definition_version(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_set_definition_version_impl(arguments), context)
        return self._tool_response(f"Updated HDA definition version to {data['version']}.", data)
