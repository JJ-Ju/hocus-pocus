"""HDA and asset-library operations."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from hocuspocus.core.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class HdaOperationsMixin:
    _HDA_PARM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    _HDA_EMBEDDED_LIBRARY = "Embedded"

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

    @staticmethod
    def _hda_tuple_values(parm: Any, parm_tuple: Any) -> tuple[Any, ...]:
        parms = list(parm_tuple) if parm_tuple is not None else [parm]
        return tuple(item.eval() for item in parms)

    @staticmethod
    def _hda_normalize_values(value: Any, size: int, label: str) -> tuple[Any, ...]:
        if isinstance(value, (list, tuple)):
            values = tuple(value)
        elif size == 1:
            values = (value,)
        else:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} must be an array with exactly {size} values.",
                {"diagnosticCode": "hda.interface.arity", "expectedTupleSize": size},
            )
        if len(values) != size:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} must contain exactly {size} values.",
                {
                    "diagnosticCode": "hda.interface.arity",
                    "expectedTupleSize": size,
                    "actualTupleSize": len(values),
                },
            )
        return values

    @staticmethod
    def _hda_set_parm_values(parm: Any, parm_tuple: Any, values: tuple[Any, ...]) -> None:
        if parm_tuple is not None:
            parm_tuple.set(values)
        else:
            parm.set(values[0])

    @staticmethod
    def _hda_capture_parm_state(parm: Any, parm_tuple: Any) -> list[dict[str, Any]]:
        parms = list(parm_tuple) if parm_tuple is not None else [parm]
        return [
            {
                "parm": item,
                "path": item.path(),
                "value": item.eval(),
                "keyframes": tuple(item.keyframes()),
            }
            for item in parms
        ]

    @staticmethod
    def _hda_validate_value_types(
        template: Any, values: tuple[Any, ...], label: str,
    ) -> str:
        try:
            template_type = str(template.type().name())
        except Exception as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} targets an interface entry with no supported value type.",
                {"diagnosticCode": "hda.interface.value_type_unknown"},
            ) from exc
        numeric = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
        predicates = {
            "Float": numeric,
            "Int": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "Toggle": lambda value: isinstance(value, bool) or value in (0, 1),
            "String": lambda value: isinstance(value, str),
            "Menu": lambda value: isinstance(value, (str, int)) and not isinstance(value, bool),
        }
        predicate = predicates.get(template_type)
        if predicate is None or not all(predicate(value) for value in values):
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} is incompatible with the HDA interface parameter type.",
                {
                    "diagnosticCode": "hda.interface.value_type",
                    "templateType": template_type,
                },
            )
        return template_type

    @staticmethod
    def _hda_canonicalize_values(
        template: Any,
        template_type: str,
        values: tuple[Any, ...],
        label: str,
    ) -> tuple[Any, ...]:
        """Return the representation produced by HOM after setting a value."""
        if template_type != "Menu":
            return values
        try:
            menu_items = tuple(template.menuItems())
        except Exception as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} targets a menu whose items could not be inspected.",
                {"diagnosticCode": "hda.interface.menu_token"},
            ) from exc
        if len(values) != 1 or not menu_items:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} targets an invalid ordered menu parameter.",
                {"diagnosticCode": "hda.interface.menu_token"},
            )
        menu_value = values[0]
        if isinstance(menu_value, str):
            matches = [
                index for index, token in enumerate(menu_items)
                if token == menu_value
            ]
            if len(matches) != 1:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"{label} is not an unambiguous token in the ordered menu parameter.",
                    {"diagnosticCode": "hda.interface.menu_token"},
                )
            menu_value = matches[0]
        if not isinstance(menu_value, int) or isinstance(menu_value, bool):
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} is incompatible with the ordered menu parameter.",
                {"diagnosticCode": "hda.interface.menu_token"},
            )
        if not 0 <= menu_value < len(menu_items):
            raise JsonRpcError(
                INVALID_PARAMS,
                f"{label} is outside the ordered menu parameter.",
                {"diagnosticCode": "hda.interface.menu_token"},
            )
        return (menu_value,)

    @staticmethod
    def _hda_default_payload(
        template: Any, template_type: str, values: tuple[Any, ...], label: str,
    ) -> tuple[Any, tuple[Any, ...]]:
        if template_type == "Toggle":
            value = bool(values[0])
            return value, (value,)
        if template_type != "Menu":
            return values, values
        try:
            canonical = HdaOperationsMixin._hda_canonicalize_values(
                template, template_type, values, label,
            )
        except JsonRpcError as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                exc.message,
                {"diagnosticCode": "hda.interface.menu_default"},
            ) from exc
        return canonical[0], canonical

    def _hda_definition_library_identity(self, definition: Any) -> dict[str, Any]:
        library_path = str(definition.libraryFilePath()).strip()
        node_type_name = str(definition.nodeTypeName()).strip()
        if library_path == self._HDA_EMBEDDED_LIBRARY:
            return {
                "kind": "embedded",
                "libraryFilePath": self._HDA_EMBEDDED_LIBRARY,
                "nodeTypeName": node_type_name,
            }
        if not library_path:
            raise JsonRpcError(
                INVALID_PARAMS,
                "The HDA definition has no writable library identity.",
                {"diagnosticCode": "hda.definition.library_identity"},
            )
        resolved = ensure_path_allowed(library_path, self._settings)
        return {
            "kind": "external_library",
            "libraryFilePath": str(resolved),
            "nodeTypeName": node_type_name,
        }

    @staticmethod
    def _hda_require_current_locked_instance(instance: Any) -> None:
        if not bool(instance.isLockedHDA()) or not bool(instance.matchesCurrentDefinition()):
            raise JsonRpcError(
                INVALID_PARAMS,
                "HDA definition mutation requires a locked instance matching its current definition.",
                {"diagnosticCode": "hda.instance.not_current_locked"},
            )

    @staticmethod
    def _hda_require_static_source_channels(parm: Any, parm_tuple: Any) -> None:
        parms = list(parm_tuple) if parm_tuple is not None else [parm]
        for item in parms:
            try:
                keyframes = tuple(item.keyframes())
            except Exception as exc:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "The source channel state could not be inspected safely.",
                    {"diagnosticCode": "hda.promotion.source_state_unknown"},
                ) from exc
            if keyframes:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Parameters with expressions or keyframes cannot be promoted safely in v1.",
                    {
                        "diagnosticCode": "hda.promotion.authored_channel",
                        "parmPath": item.path(),
                    },
                )
            expression = getattr(item, "expression", None)
            if not callable(expression):
                continue
            try:
                authored_expression = expression()
            except Exception as exc:
                if type(exc).__name__ == "OperationFailed":
                    continue
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "The source expression state could not be inspected safely.",
                    {"diagnosticCode": "hda.promotion.source_state_unknown"},
                ) from exc
            if authored_expression:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Parameters with expressions or keyframes cannot be promoted safely in v1.",
                    {
                        "diagnosticCode": "hda.promotion.authored_channel",
                        "parmPath": item.path(),
                    },
                )

    def _hda_restore_parm_state(self, states: list[dict[str, Any]]) -> None:
        for state in states:
            parm = self._require_parm_by_path(state["path"])
            parm.deleteAllKeyframes()
            keyframes = state["keyframes"]
            if keyframes:
                parm.setKeyframes(keyframes)
            else:
                parm.set(state["value"])

    @staticmethod
    def _hda_template_default_values(template: Any) -> tuple[Any, ...]:
        getter = getattr(template, "defaultValue", None)
        if not callable(getter):
            raise RuntimeError("The installed HDA template has no readable default value.")
        value = getter()
        return tuple(value) if isinstance(value, (list, tuple)) else (value,)

    def _hda_verify_promotion(
        self,
        instance: Any,
        definition: Any,
        prepared: dict[str, Any],
        promoted_parm: Any,
        promoted_tuple: Any,
        source_parm_path: str,
        create_reference: bool,
    ) -> tuple[Any, ...]:
        promoted_values = self._hda_tuple_values(promoted_parm, promoted_tuple)
        expected = prepared["initialValues"]
        if expected is not None and promoted_values != expected:
            raise RuntimeError("Promoted parameter did not retain its requested value.")
        source_parm = self._require_parm_by_path(source_parm_path)
        source_values = self._hda_tuple_values(source_parm, source_parm.tuple())
        if create_reference and source_values != promoted_values:
            raise RuntimeError("Promoted reference did not preserve the source value.")
        default_values = prepared["defaultValues"]
        installed = definition.parmTemplateGroup().find(prepared["name"])
        if installed is None:
            raise RuntimeError("Promoted parameter is absent from the HDA definition.")
        if (
            default_values is not None
            and self._hda_template_default_values(installed) != default_values
        ):
            raise RuntimeError("Promoted parameter default was not retained by the definition.")
        if not instance.isLockedHDA():
            raise RuntimeError("HDA instance did not return to its locked definition state.")
        return promoted_values

    def _hda_rollback_promotion(
        self,
        definition: Any,
        instance: Any,
        original_group: Any,
        source_states: list[dict[str, Any]],
        definition_updated: bool,
        promoted_name: str,
    ) -> None:
        definition.setParmTemplateGroup(
            original_group, rename_conflicting_parms=False, create_backup=True,
        )
        if definition_updated:
            instance.allowEditingOfContents()
            self._hda_restore_parm_state(source_states)
            definition.updateFromNode(instance)
        instance.matchCurrentDefinition()
        if definition.parmTemplateGroup().find(promoted_name) is not None:
            raise RuntimeError("The promoted interface entry survived rollback.")
        restored = tuple(
            self._require_parm_by_path(state["path"]).eval() for state in source_states
        )
        expected = tuple(state["value"] for state in source_states)
        if restored != expected:
            raise RuntimeError("The source parameter value was not restored.")
        if not instance.isLockedHDA():
            raise RuntimeError("The HDA instance did not relock after rollback.")

    def _hda_prepare_promoted_template(
        self,
        arguments: dict[str, Any],
        source_parm: Any,
        source_tuple: Any,
        definition: Any,
    ) -> dict[str, Any]:
        promoted_name = str(arguments.get("promoted_name", "")).strip() or source_parm.name()
        if self._HDA_PARM_NAME.fullmatch(promoted_name) is None:
            raise JsonRpcError(INVALID_PARAMS, "promoted_name is not a valid Houdini parameter name.")
        if definition.parmTemplateGroup().find(promoted_name) is not None:
            raise JsonRpcError(
                INVALID_PARAMS, f"The HDA interface already contains {promoted_name}.",
            )
        source_values = self._hda_tuple_values(source_parm, source_tuple)
        preserve = arguments.get("preserve_source_value", True)
        if not isinstance(preserve, bool):
            raise JsonRpcError(INVALID_PARAMS, "preserve_source_value must be a boolean.")
        template_source = (
            source_tuple.parmTemplate() if source_tuple is not None
            else source_parm.parmTemplate()
        )
        template = template_source.clone()
        template.setName(promoted_name)
        template.setLabel(
            str(arguments.get("promoted_label", "")).strip()
            or source_parm.parmTemplate().label()
        )
        default_values = None
        if "default_value" in arguments:
            default_values = self._hda_normalize_values(
                arguments["default_value"], len(source_values), "default_value",
            )
        elif preserve:
            default_values = source_values
        if default_values is not None:
            template_type = self._hda_validate_value_types(
                template, default_values, "default_value",
            )
            default_payload, default_values = self._hda_default_payload(
                template, template_type, default_values, "default_value",
            )
            setter = getattr(template, "setDefaultValue", None)
            if not callable(setter):
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "This parameter template cannot carry a promoted default value.",
                )
            try:
                setter(default_payload)
            except (TypeError, ValueError) as exc:
                raise JsonRpcError(
                    INVALID_PARAMS, "default_value is incompatible with the source parameter.",
                ) from exc
        initial_values = None
        if "initial_value" in arguments:
            initial_values = self._hda_normalize_values(
                arguments["initial_value"], len(source_values), "initial_value",
            )
        elif preserve:
            initial_values = source_values
        if initial_values is not None:
            template_type = self._hda_validate_value_types(
                template, initial_values, "initial_value",
            )
            initial_values = self._hda_canonicalize_values(
                template, template_type, initial_values, "initial_value",
            )
        return {
            "name": promoted_name,
            "template": template,
            "sourceValues": source_values,
            "defaultValues": default_values,
            "initialValues": initial_values,
            "preserve": preserve,
        }

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
        created.matchCurrentDefinition()
        return {
            "node": self._hda_instance_summary(created),
            "definition": self._hda_definition_summary(definition),
            "libraryIdentity": self._hda_definition_library_identity(definition),
        }

    def hda_create_from_subnet(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_create_from_subnet_impl(arguments), context)
        return self._tool_response(f"Created digital asset {data['definition']['nodeTypeName']}.", data)

    def _hda_resolve_promotion_source(
        self, instance_path: str, source_parm_path: str,
    ) -> tuple[Any, Any, Any, Any, dict[str, Any]]:
        instance = self._require_node_by_path(instance_path, label="instance_path")
        definition = self._safe_value(lambda: instance.type().definition(), None)
        if definition is None:
            raise JsonRpcError(
                INVALID_PARAMS, f"Node is not backed by an HDA definition: {instance_path}",
            )
        self._hda_require_current_locked_instance(instance)
        library_identity = self._hda_definition_library_identity(definition)
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
        self._hda_require_static_source_channels(source_parm, source_tuple)
        return instance, definition, source_parm, source_tuple, library_identity

    def _hda_materialize_promotion(
        self,
        hou_module: Any,
        instance: Any,
        definition: Any,
        prepared: dict[str, Any],
        folder_label: str | None,
        source_parm_path: str,
        source_tuple: Any,
        source_index: int,
        create_reference: bool,
        transaction: dict[str, bool],
    ) -> dict[str, Any]:
        name = prepared["name"]
        self._hda_append_promoted_template(
            hou_module, definition, prepared["template"], folder_label,
        )
        instance.matchCurrentDefinition()
        component_path, paths, tuple_name = self._hda_promoted_paths(
            instance, name, source_index,
        )
        if component_path is None:
            raise RuntimeError("Promoted parameter was not materialized on the HDA instance.")
        promoted_parm = self._require_parm_by_path(component_path)
        promoted_tuple = instance.parmTuple(tuple_name) if tuple_name else None
        if prepared["initialValues"] is not None:
            self._hda_set_parm_values(
                promoted_parm, promoted_tuple, prepared["initialValues"],
            )
        if create_reference:
            self._hda_create_promoted_reference(
                instance, source_parm_path, source_tuple, component_path, tuple_name,
            )
            definition.updateFromNode(instance)
            transaction["definitionUpdated"] = True
            instance.matchCurrentDefinition()
            component_path, paths, tuple_name = self._hda_promoted_paths(
                instance, name, source_index,
            )
            promoted_parm = self._require_parm_by_path(component_path)
            promoted_tuple = instance.parmTuple(tuple_name) if tuple_name else None
            if prepared["initialValues"] is not None:
                self._hda_set_parm_values(
                    promoted_parm, promoted_tuple, prepared["initialValues"],
                )
        instance.cook(force=True)
        promoted_values = self._hda_verify_promotion(
            instance, definition, prepared, promoted_parm, promoted_tuple,
            source_parm_path, create_reference,
        )
        return {
            "componentPath": component_path,
            "paths": paths,
            "tupleName": tuple_name,
            "values": promoted_values,
        }

    def _hda_promote_parm_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        instance_path = str(arguments.get("instance_path", "")).strip()
        source_parm_path = str(arguments.get("source_parm_path", "")).strip()
        if not instance_path or not source_parm_path:
            raise JsonRpcError(INVALID_PARAMS, "instance_path and source_parm_path are required")
        instance, definition, source_parm, source_tuple, library_identity = (
            self._hda_resolve_promotion_source(instance_path, source_parm_path)
        )
        prepared = self._hda_prepare_promoted_template(
            arguments, source_parm, source_tuple, definition,
        )
        promoted_name = prepared["name"]
        folder_label = str(arguments.get("folder_label", "")).strip() or None
        create_reference = bool(arguments.get("create_reference", True))
        source_parms = list(source_tuple) if source_tuple is not None else []
        source_index = source_parms.index(source_parm) if source_parm in source_parms else 0
        original_group = definition.parmTemplateGroup()
        source_states = self._hda_capture_parm_state(source_parm, source_tuple)
        transaction = {"definitionUpdated": False}
        try:
            with hou_module.undos.group(f"HocusPocus: promote {promoted_name}"):
                outcome = self._hda_materialize_promotion(
                    hou_module, instance, definition, prepared, folder_label,
                    source_parm_path, source_tuple, source_index, create_reference,
                    transaction,
                )
        except Exception as exc:
            try:
                self._hda_rollback_promotion(
                    definition, instance, original_group, source_states,
                    transaction["definitionUpdated"], promoted_name,
                )
            except Exception as rollback_exc:
                raise JsonRpcError(
                    INTERNAL_ERROR,
                    "HDA promotion failed and rollback could not be verified.",
                    {"failureType": type(exc).__name__, "rollbackType": type(rollback_exc).__name__},
                ) from exc
            if isinstance(exc, JsonRpcError):
                raise
            raise JsonRpcError(
                INTERNAL_ERROR,
                "HDA promotion failed and was rolled back.",
                {"failureType": type(exc).__name__},
            ) from exc

        return {
            "instance": self._hda_instance_summary(instance),
            "promotedParmPath": outcome["componentPath"],
            "promotedParmPaths": outcome["paths"],
            "promotedParmTupleName": outcome["tupleName"],
            "sourceParmPath": source_parm.path(),
            "createReference": create_reference,
            "preserveSourceValue": prepared["preserve"],
            "capturedSourceValue": list(prepared["sourceValues"]),
            "definitionDefaultValue": (
                list(prepared["defaultValues"])
                if prepared["defaultValues"] is not None else None
            ),
            "instanceInitialValue": list(outcome["values"]),
            "verified": True,
            "libraryIdentity": library_identity,
        }

    def hda_promote_parm(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_promote_parm_impl(arguments), context)
        return self._tool_response(f"Promoted parm {data['sourceParmPath']}.", data)

    def _hda_prepare_instance_assignments(
        self, instance: Any, assignments: list[Any],
    ) -> list[dict[str, Any]]:
        group = instance.parmTemplateGroup()
        spare_names = set()
        for parm in instance.spareParms():
            spare_names.add(str(parm.name()))
            spare_names.add(str(parm.parmTemplate().name()))
        seen = set()
        prepared = []
        for index, assignment in enumerate(assignments):
            if not isinstance(assignment, dict):
                raise JsonRpcError(
                    INVALID_PARAMS, "Each assignment must be an object.", {"index": index},
                )
            name = str(assignment.get("name", "")).strip()
            template = group.find(name)
            if self._HDA_PARM_NAME.fullmatch(name) is None or template is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Assignments may target only named parameters in the public HDA interface.",
                    {
                        "diagnosticCode": "hda.interface.name",
                        "index": index,
                        "name": name or None,
                    },
                )
            if name in seen:
                raise JsonRpcError(
                    INVALID_PARAMS, "An HDA interface parameter may be assigned only once.",
                    {"diagnosticCode": "hda.interface.duplicate", "index": index, "name": name},
                )
            if name in spare_names:
                raise JsonRpcError(
                    INVALID_PARAMS, "Spare parameters are not part of the managed HDA interface lane.",
                    {"diagnosticCode": "hda.interface.spare", "index": index, "name": name},
                )
            seen.add(name)
            parm_tuple = instance.parmTuple(name)
            parm = instance.parm(name)
            parms = list(parm_tuple) if parm_tuple is not None else [parm]
            if not parms or parm is None:
                parm = parms[0] if parms else None
            if parm is None:
                raise JsonRpcError(
                    INVALID_PARAMS, "The selected HDA interface entry is not value-settable.",
                    {
                        "diagnosticCode": "hda.interface.non_value",
                        "index": index,
                        "name": name,
                    },
                )
            values = self._hda_normalize_values(
                assignment.get("value"), len(parms), f"assignments[{index}].value",
            )
            template_type = self._hda_validate_value_types(
                template, values, f"assignments[{index}].value",
            )
            values = self._hda_canonicalize_values(
                template, template_type, values, f"assignments[{index}].value",
            )
            prepared.append({
                "name": name,
                "parm": parm,
                "tuple": parm_tuple,
                "values": values,
                "templateType": template_type,
                "state": self._hda_capture_parm_state(parm, parm_tuple),
            })
        return prepared

    def _hda_set_instance_parms_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hou_module = self._require_hou()
        instance_path = str(arguments.get("instance_path", "")).strip()
        assignments = arguments.get("assignments")
        if not instance_path:
            raise JsonRpcError(INVALID_PARAMS, "instance_path is required.")
        if not isinstance(assignments, list) or not assignments:
            raise JsonRpcError(INVALID_PARAMS, "assignments must be a non-empty array.")
        instance = self._require_node_by_path(instance_path, label="instance_path")
        if self._safe_value(lambda: instance.type().definition(), None) is None:
            raise JsonRpcError(INVALID_PARAMS, f"Node is not an HDA instance: {instance_path}")
        prepared = self._hda_prepare_instance_assignments(instance, assignments)
        try:
            with hou_module.undos.group(f"HocusPocus: set HDA interface {instance_path}"):
                for item in prepared:
                    self._hda_set_parm_values(item["parm"], item["tuple"], item["values"])
                instance.cook(force=True)
                if any(
                    self._hda_tuple_values(item["parm"], item["tuple"])
                    != item["values"]
                    for item in prepared
                ):
                    raise RuntimeError("An HDA interface parameter did not retain its requested value.")
        except Exception as exc:
            try:
                for item in prepared:
                    self._hda_restore_parm_state(item["state"])
                instance.cook(force=True)
                if any(
                    tuple(
                        self._require_parm_by_path(state["path"]).eval()
                        for state in item["state"]
                    )
                    != tuple(state["value"] for state in item["state"])
                    for item in prepared
                ):
                    raise RuntimeError("HDA interface rollback did not restore the prior values.")
            except Exception as rollback_exc:
                raise JsonRpcError(
                    INTERNAL_ERROR,
                    "HDA interface update failed and rollback could not be verified.",
                    {"failureType": type(exc).__name__, "rollbackType": type(rollback_exc).__name__},
                ) from exc
            raise JsonRpcError(
                INTERNAL_ERROR,
                "HDA interface update failed and was rolled back.",
                {"failureType": type(exc).__name__},
            ) from exc
        updated = [
            {
                "name": item["name"],
                "parmPaths": [state["parm"].path() for state in item["state"]],
                "value": list(self._hda_tuple_values(item["parm"], item["tuple"])),
                "templateType": item["templateType"],
            }
            for item in prepared
        ]
        return {
            "instancePath": instance.path(),
            "locked": bool(instance.isLockedHDA()),
            "count": len(updated),
            "assignments": updated,
        }

    def hda_set_instance_parms(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_set_instance_parms_impl(arguments), context)
        return self._tool_response(f"Set {data['count']} public HDA parameter(s).", data)

    def _hda_set_definition_version_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        version = str(arguments.get("version", "")).strip()
        if not version:
            raise JsonRpcError(INVALID_PARAMS, "version is required")
        library_file_path = str(arguments.get("library_file_path", "")).strip() or None
        if (
            library_file_path is not None
            and library_file_path != self._HDA_EMBEDDED_LIBRARY
        ):
            library_file_path = str(ensure_path_allowed(library_file_path, self._settings))
        definition = self._resolve_definition(
            node_type_name=str(arguments.get("node_type_name", "")).strip() or None,
            library_file_path=library_file_path,
            node_path=str(arguments.get("node_path", "")).strip() or None,
        )
        library_identity = self._hda_definition_library_identity(definition)
        definition.setVersion(version)
        return {
            **self._hda_definition_summary(definition),
            "libraryIdentity": library_identity,
        }

    def hda_set_definition_version(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._hda_set_definition_version_impl(arguments), context)
        return self._tool_response(f"Updated HDA definition version to {data['version']}.", data)
