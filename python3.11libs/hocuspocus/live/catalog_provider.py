"""Live Houdini catalog extraction with no import-time dependency on ``hou``."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform as host_platform
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hocuspocus.hocusscript.catalog import (
    CATALOG_VERSION,
    VALUE_CATALOG_VERSION,
    CatalogSnapshot,
    CategoryDefinition,
    ConnectorDefinition,
    DefinitionSource,
    HdaLibrary,
    HoudiniBuild,
    MenuItem,
    OperatorDefinition,
    PackageDefinition,
    ParameterDefinition,
    ParmRange,
    decode_catalog_snapshot,
)
from hocuspocus.live.hda_library_identity import (
    HdaLibraryIdentityError,
    hda_library_content_digest,
)

_VERSION = re.compile(r"^\d+(?:\.\d+)*$")
_IDENTIFIER = re.compile(r"[^a-z0-9]+")
_MAX_CONNECTORS = 64


class LiveCatalogExtractionError(RuntimeError):
    """Raised when HOM metadata cannot be represented without guessing."""


def _safe_call(target: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(target, name)
        return value() if callable(value) else value
    except Exception:
        return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    result = str(value).strip()
    return result or default


def _enum_name(value: Any) -> str:
    return _text(_safe_call(value, "name", value))


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return hda_library_content_digest(path)
    except HdaLibraryIdentityError as exc:
        raise LiveCatalogExtractionError(
            "HDA library has no bounded stable byte identity."
        ) from exc


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    name = _safe_call(value, "name", None)
    return _text(name) or None


def _identifier(value: str) -> str:
    normalized = _IDENTIFIER.sub("-", value.lower()).strip("-")
    return normalized or "package"


def _category_family(name: str) -> str:
    return {
        "Object": "object",
        "Obj": "object",
        "Vop": "mat",
        "Shop": "mat",
        "Mat": "mat",
        "Driver": "rop",
        "Rop": "rop",
        "Cop2": "cop",
    }.get(name, name.lower())


def _type_components(raw_name: str, node_type: Any) -> tuple[str | None, str, str | None]:
    components = _safe_call(node_type, "nameComponents", None)
    if isinstance(components, (tuple, list)) and len(components) >= 4:
        namespace = _text(components[-3]) or None
        core_name = _text(components[-2], raw_name)
        version = _text(components[-1]) or None
        return namespace, core_name, version

    parts = [part for part in raw_name.split("::") if part]
    if len(parts) >= 3 and _VERSION.fullmatch(parts[-1]):
        return "::".join(parts[:-2]) or None, parts[-2], parts[-1]
    if len(parts) == 2 and _VERSION.fullmatch(parts[-1]):
        return None, parts[0], parts[1]
    if len(parts) >= 2:
        return "::".join(parts[:-1]), parts[-1], None
    return None, raw_name, None


def _tuple_names(token: str, size: int, template: Any) -> tuple[str, ...]:
    if size <= 1:
        return ()
    scheme = _enum_name(_safe_call(template, "namingScheme", "")).lower()
    suffixes: Sequence[str]
    if "minmax" in scheme:
        suffixes = ("min", "max")
    elif "maxmin" in scheme:
        suffixes = ("max", "min")
    elif "startend" in scheme:
        suffixes = ("start", "end")
    elif "beginend" in scheme:
        suffixes = ("begin", "end")
    elif "xywh" in scheme:
        suffixes = ("x", "y", "w", "h")
    elif "rgba" in scheme:
        suffixes = ("r", "g", "b", "a")
    elif "uvw" in scheme:
        suffixes = ("u", "v", "w")
    elif "xyzw" in scheme or "xyz" in scheme:
        suffixes = ("x", "y", "z", "w")
    else:
        suffixes = tuple(str(index + 1) for index in range(size))
    return tuple(
        token + (suffixes[index] if index < len(suffixes) else str(index + 1))
        for index in range(size)
    )


def _parameter_tags(template: Any) -> dict[str, str]:
    raw = _safe_call(template, "tags", {})
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, value in raw.items():
        name = _text(key)
        tag_value = _text(value)
        if name and tag_value:
            if len(tag_value) > 512:
                tag_value = _digest(tag_value.encode("utf-8", errors="surrogatepass"))
            result[name] = tag_value
    return result


def _code_surface(token: str, label: str, tags: Mapping[str, str], operator_name: str) -> str:
    editor_evidence = " ".join(
        value for key, value in tags.items() if key.lower() == "editorlang"
    ).lower()
    if "python" in editor_evidence:
        return "python"
    if "vex" in editor_evidence:
        return "vex"
    if "hscript" in editor_evidence:
        return "hscript"
    token_language = {
        "snippet": "vex",
        "vexcode": "vex",
        "vexscript": "vex",
        "python": "python",
        "pythoncode": "python",
        "pythonscript": "python",
        "hscript": "hscript",
        "hscriptcode": "hscript",
    }.get(token.casefold().replace("_", ""))
    if not editor_evidence and token_language is not None:
        return token_language
    if token.casefold() == "script":
        operator_evidence = operator_name.casefold()
        for marker, language in (("python", "python"), ("vex", "vex"), ("hscript", "hscript")):
            if marker in operator_evidence:
                return language
    token_lower = token.lower()
    label_words = set(re.findall(r"[a-z0-9]+", label.lower()))
    suspicious = (
        "snippet" in token_lower
        or "snippet" in label_words
        or token_lower.endswith(("code", "script"))
        or bool(label_words & {"code", "script"})
    )
    if editor_evidence or suspicious:
        return "unsupported"
    return "none"


def _parameter_type(
    template_type: str,
    token: str,
    tags: Mapping[str, str],
    menu: tuple[MenuItem, ...],
    code_surface: str,
) -> str | None:
    kind = template_type.lower()
    evidence = " ".join((token, *tags.keys(), *tags.values())).lower()
    if "button" in kind:
        result = "button"
    elif menu:
        result = "menu"
    elif code_surface != "none":
        result = "code"
    elif "toggle" in kind:
        result = "bool"
    elif "ramp" in kind:
        result = "ramp"
    elif "multiparm" in kind:
        result = "multiparm"
    elif "float" in kind:
        result = "float"
    elif "int" in kind:
        result = "int"
    elif "string" in kind:
        result = _string_parameter_type(evidence)
    else:
        result = None
    return result


def _string_parameter_type(evidence: str) -> str:
    if "filereference" in evidence or "filechooser" in evidence or "file path" in evidence:
        return "file_path"
    if "nodereference" in evidence or "opfilter" in evidence or "node path" in evidence:
        return "node_path"
    if "usd" in evidence and ("prim" in evidence or "path" in evidence):
        return "usd_prim_path"
    if "parm path" in evidence:
        return "parm_path"
    return "string"


def _parameter_range(template: Any) -> ParmRange | None:
    minimum = _safe_call(template, "minValue", None)
    maximum = _safe_call(template, "maxValue", None)
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum):
        minimum = None
    if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum):
        maximum = None
    if not bool(_safe_call(template, "minIsStrict", False)):
        minimum = None
    if not bool(_safe_call(template, "maxIsStrict", False)):
        maximum = None
    if minimum is None and maximum is None:
        return None
    return ParmRange(minimum, maximum)


def _template_type(template: Any) -> str:
    if type(template).__name__ == "RampParmTemplate":
        return "Ramp"
    template_type = _enum_name(_safe_call(template, "type", ""))
    folder_type = _enum_name(_safe_call(template, "folderType", ""))
    if "multiparm" in folder_type.lower():
        return "MultiparmBlock"
    return template_type


def _parameter_menu(template: Any) -> tuple[MenuItem, ...]:
    tokens = tuple(_text(item) for item in (_safe_call(template, "menuItems", ()) or ()))
    labels = tuple(_text(item) for item in (_safe_call(template, "menuLabels", ()) or ()))
    items: list[MenuItem] = []
    seen: set[str] = set()
    for index, token in enumerate(tokens):
        if not token or token in seen:
            continue
        seen.add(token)
        label = labels[index] if index < len(labels) and labels[index] else token
        items.append(MenuItem(token, label))
    return tuple(items)


def _parameter_tags_with_bounds(template: Any) -> dict[str, str]:
    tags = _parameter_tags(template)
    string_type = _enum_name(_safe_call(template, "stringType", ""))
    if string_type:
        tags["houdini.stringType"] = string_type
    for method, strict_method, tag_name in (
        ("minValue", "minIsStrict", "houdini.uiMin"),
        ("maxValue", "maxIsStrict", "houdini.uiMax"),
    ):
        bound = _safe_call(template, method, None)
        valid = (
            isinstance(bound, (int, float))
            and not isinstance(bound, bool)
            and math.isfinite(bound)
            and not bool(_safe_call(template, strict_method, False))
        )
        if valid:
            tags[tag_name] = str(bound)
    return tags


def _normalize_menu_default(
    default: Any,
    menu: tuple[MenuItem, ...],
    size: int,
    tags: dict[str, str],
) -> Any:
    if not menu:
        return default
    tokens = {item.token for item in menu}
    defaults = default if size > 1 and isinstance(default, list) else [default]
    if size > 1 and len(defaults) != size:
        defaults = []
    normalized: list[str] = []
    for value in defaults:
        if isinstance(value, str) and value in tokens:
            normalized.append(value)
        elif isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(menu):
            normalized.append(menu[value].token)
        else:
            normalized = []
            break
    if normalized and len(normalized) == size:
        return normalized if size > 1 else normalized[0]
    tags["hocus.defaultStatus"] = "unresolved-menu-default"
    return None


def _parameter_value_contract(
    template: Any, value_type: str, tags: Mapping[str, str],
) -> dict[str, Any] | None:
    if value_type == "ramp":
        ramp_type = _enum_name(_safe_call(template, "parmType", None)).lower()
        if ramp_type not in {"float", "color"}:
            return None
        return {
            "kind": "ramp",
            "rampKind": ramp_type,
            "allowedBases": [
                "bezier", "bspline", "catmullrom", "constant", "hermite",
                "linear", "monotonecubic",
            ],
        }
    if value_type == "multiparm":
        return _multiparm_value_contract(template)
    return _quantity_value_contract(value_type, tags)


def _quantity_value_contract(
    value_type: str, tags: Mapping[str, str],
) -> dict[str, Any] | None:
    if value_type not in {"int", "float", "tuple"}:
        return None
    dimension = tags.get("hocus.unitDimension")
    canonical = tags.get("hocus.canonicalUnit")
    encoded = tags.get("hocus.units")
    if not dimension or not canonical or not encoded:
        return None
    try:
        units = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    if not isinstance(units, list):
        return None
    return {
        "kind": "quantity",
        "dimension": dimension,
        "canonicalUnit": canonical,
        "units": units,
    }


def _multiparm_value_contract(template: Any) -> dict[str, Any] | None:
    instance_start = _multiparm_instance_start(template)
    if instance_start is None:
        return None
    children = _safe_call(template, "parmTemplates", None)
    if not isinstance(children, (tuple, list)):
        return None
    fields = []
    for child in children:
        token = _text(_safe_call(child, "name", None))
        if token.count("#") != 1:
            return None
        child_type = _parameter_type(
            _template_type(child),
            token,
            _parameter_tags_with_bounds(child),
            _parameter_menu(child),
            "none",
        )
        size = _safe_call(child, "numComponents", 1)
        size = size if type(size) is int and 1 <= size <= 1024 else 1
        element_type = child_type if size > 1 else None
        if size > 1 and child_type in {"bool", "int", "float", "string"}:
            child_type = "tuple"
        if child_type in {None, "button", "ramp", "multiparm"}:
            return None
        field_name = token.replace("#", "")
        fields.append({
            "name": field_name,
            "tokenTemplate": token,
            "valueType": child_type,
            "tupleSize": size,
            "elementType": element_type,
        })
    return {
        "kind": "multiparm",
        "instanceStart": instance_start,
        "minInstances": 0,
        "maxInstances": 4096,
        "fields": fields,
    }


def _multiparm_instance_start(template: Any) -> int | None:
    candidates: list[int] = []
    method = getattr(template, "multiParmStartOffset", None)
    if callable(method):
        try:
            value = method()
        except Exception:
            return None
        if type(value) is not int or not 0 <= value <= 4096:
            return None
        candidates.append(value)
    tags = _safe_call(template, "tags", None)
    if isinstance(tags, Mapping) and "multistartoffset" in tags:
        encoded = tags["multistartoffset"]
        if (
            not isinstance(encoded, str)
            or re.fullmatch(r"0|[1-9]\d*", encoded) is None
        ):
            return None
        value = int(encoded)
        if value > 4096:
            return None
        candidates.append(value)
    if not candidates or any(value != candidates[0] for value in candidates):
        return None
    return candidates[0]


def _instance_network_shape(node_type: Any) -> bool:
    method = getattr(node_type, "childTypeCategory", None)
    if not callable(method):
        raise LiveCatalogExtractionError(
            "Houdini did not expose exact operator instance network shape."
        )
    try:
        return method() is not None
    except Exception as exc:
        raise LiveCatalogExtractionError(
            "Houdini operator instance network shape could not be inspected."
        ) from exc


def _parameter(
    template: Any, operator_name: str, catalog_version: int = CATALOG_VERSION,
) -> ParameterDefinition | None:
    token = _text(_safe_call(template, "name", None))
    if not token:
        return None
    label = _text(_safe_call(template, "label", None), token)
    template_type = _template_type(template)
    size = _safe_call(template, "numComponents", 1)
    size = int(size) if isinstance(size, int) and not isinstance(size, bool) and size > 0 else 1
    menu = _parameter_menu(template)
    tags = _parameter_tags_with_bounds(template)
    value_type = _parameter_type(template_type, token, tags, menu, "none")
    if value_type is None:
        return None
    code_surface = (
        _code_surface(token, label, tags, operator_name)
        if value_type == "string"
        else "none"
    )
    if code_surface == "unsupported":
        tags["hocus.codeSurfaceStatus"] = "unsupported-or-unknown-language"
    if code_surface != "none":
        value_type = "code"
    if size > 1 and value_type in {"bool", "int", "float", "string"}:
        tags["elementType"] = value_type
        value_type = "tuple"
    if value_type != "code":
        code_surface = "none"
    default = _json_safe(_safe_call(template, "defaultValue", None))
    if isinstance(default, list) and size == 1 and len(default) == 1:
        default = default[0]
    default = _normalize_menu_default(default, menu, size, tags)
    if value_type == "tuple":
        if not isinstance(default, list) or len(default) != size:
            default = None
            tags["hocus.defaultStatus"] = "unresolved-tuple-default"
    value_contract = (
        _parameter_value_contract(template, value_type, tags)
        if catalog_version == VALUE_CATALOG_VERSION else None
    )
    return ParameterDefinition(
        token=token,
        label=label,
        value_type=value_type,
        tuple_size=size,
        tuple_names=_tuple_names(token, size, template),
        default=default,
        range=_parameter_range(template),
        menu=menu,
        tags=tags,
        code_surface=code_surface,
        assignable=value_type not in {"button", "ramp", "multiparm"},
        value_contract=value_contract,
    )


def _parameters(
    node_type: Any, catalog_version: int = CATALOG_VERSION,
) -> tuple[ParameterDefinition, ...]:
    operator_name = _text(_safe_call(node_type, "name", None), "<unknown>")
    group = _safe_call(node_type, "parmTemplateGroup", None)
    entries = _safe_call(group, "entries", ()) if group is not None else ()
    result: list[ParameterDefinition] = []

    def visit(items: Iterable[Any]) -> None:
        for item in items:
            template_type = _template_type(item).lower()
            children = _safe_call(item, "parmTemplates", None)
            if isinstance(children, (tuple, list)):
                if template_type in {"multiparmblock", "ramp"}:
                    parameter = _parameter(item, operator_name, catalog_version)
                    if parameter is not None:
                        result.append(parameter)
                    continue
                visit(children)
                continue
            parameter = _parameter(item, operator_name, catalog_version)
            if parameter is not None:
                result.append(parameter)

    visit(entries or ())
    return tuple(sorted(result, key=lambda item: item.token))


def _connector_values(node_type: Any, prefix: str, suffix: str) -> tuple[Any, ...]:
    value = _safe_call(node_type, prefix + suffix, ())
    return tuple(value) if isinstance(value, (tuple, list)) else ()


def _connectors(node_type: Any, category: str, prefix: str) -> tuple[ConnectorDefinition, ...]:
    minimum = _safe_call(node_type, "minNum" + prefix + "s", 0)
    maximum = _safe_call(node_type, "maxNum" + prefix + "s", minimum)
    minimum = minimum if isinstance(minimum, int) and minimum >= 0 else 0
    maximum = maximum if isinstance(maximum, int) and maximum >= minimum else minimum
    names = _connector_values(node_type, prefix.lower(), "Names")
    labels = _connector_values(node_type, prefix.lower(), "Labels")
    data_types = _connector_values(node_type, prefix.lower(), "DataTypes")
    if maximum > _MAX_CONNECTORS:
        count = min(max(minimum, len(names), len(labels)), 16)
    else:
        count = maximum
    result = []
    for index in range(count):
        name = _text(names[index]) if index < len(names) else ""
        label = _text(labels[index]) if index < len(labels) else name or f"{prefix} {index}"
        raw_types = data_types[index] if index < len(data_types) else ()
        if not isinstance(raw_types, (tuple, list)):
            raw_types = (raw_types,) if raw_types else ()
        result.append(
            ConnectorDefinition(
                index=index,
                name=name or None,
                label=label,
                cardinality="one" if index < minimum else "optional",
                data_types=tuple(sorted({_text(item) for item in raw_types if _text(item)})),
                categories=(category,),
            )
        )
    if maximum > _MAX_CONNECTORS:
        result.append(
            ConnectorDefinition(
                index=None,
                name="variadic",
                label=f"Additional {prefix}s",
                cardinality="many",
                categories=(category,),
            )
        )
    return tuple(result)


def _definition_digest(definition: Any, raw_type_name: str) -> str:
    library_path = _text(_safe_call(definition, "libraryFilePath", None))
    if library_path and library_path != "Embedded":
        return _file_digest(Path(library_path))
    version = _text(_safe_call(definition, "version", None))
    parts = [raw_type_name.encode("utf-8"), b"\0", version.encode("utf-8"), b"\0"]
    sections = _safe_call(definition, "sections", {})
    if isinstance(sections, Mapping):
        for name, section in sorted(sections.items(), key=lambda item: str(item[0])):
            content = _safe_call(section, "contents", b"")
            if isinstance(content, str):
                content = content.encode("utf-8", errors="surrogatepass")
            if not isinstance(content, bytes):
                raise LiveCatalogExtractionError(
                    "HDA section contents are not byte-addressable."
                )
            size = _safe_call(section, "size", len(content))
            size = size if isinstance(size, int) and size >= 0 else len(content)
            if size != len(content):
                raise LiveCatalogExtractionError(
                    "HDA section size disagrees with its backing bytes."
                )
            parts.extend(
                (
                    str(name).encode("utf-8"),
                    b"\0",
                    str(size).encode("ascii"),
                    b"\0",
                    content,
                    b"\0",
                )
            )
    return _digest(b"".join(parts))


def definition_content_digest(definition: Any, raw_type_name: str) -> str:
    """Return the exact content identity used by live catalog HDA sources."""

    return _definition_digest(definition, raw_type_name)


def _aliases(node_type: Any, raw_name: str) -> tuple[str, ...]:
    raw = _safe_call(node_type, "aliases", ())
    if isinstance(raw, Mapping):
        values = (*raw.keys(), *raw.values())
    elif isinstance(raw, (tuple, list, set)):
        values = tuple(raw)
    else:
        values = ()
    return tuple(sorted({_text(value) for value in values if _text(value) and _text(value) != raw_name}))


def _package_version(payload: Any) -> str | None:
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, Mapping):
            for key, value in item.items():
                if "version" in str(key).lower() and isinstance(value, (str, int, float)) and _text(value):
                    return _text(value)
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return None


class LiveHoudiniCatalogProvider:
    """Extract an immutable catalog from one injected Houdini Python module."""

    def __init__(
        self,
        hou_module: Any,
        *,
        package_directories: Sequence[str | Path] | None = None,
        catalog_version: int = CATALOG_VERSION,
    ):
        if hou_module is None:
            raise ValueError("hou_module is required")
        self._hou = hou_module
        self._package_directories = tuple(Path(item) for item in package_directories) if package_directories is not None else None
        if catalog_version not in {CATALOG_VERSION, VALUE_CATALOG_VERSION}:
            raise ValueError("catalog_version must be 1 or 2")
        self._catalog_version = catalog_version

    def _build(self) -> HoudiniBuild:
        version_tuple = _safe_call(self._hou, "applicationVersion", ())
        if isinstance(version_tuple, (tuple, list)) and len(version_tuple) >= 2:
            version = ".".join(str(item) for item in version_tuple[:2])
            build = ".".join(str(item) for item in version_tuple)
        else:
            build = _text(_safe_call(self._hou, "applicationVersionString", None), "unknown")
            version = ".".join(build.split(".")[:2]) or build
        platform = _text(
            _safe_call(self._hou, "applicationPlatformInfo", None),
            f"{host_platform.system().lower()}-{host_platform.machine().lower()}",
        )
        flags = []
        category_names = set(self._category_map())
        for category, flag in (("Apex", "apex"), ("Lop", "solaris"), ("Top", "pdg")):
            if category in category_names:
                flags.append(flag)
        license_name = _enum_name(_safe_call(self._hou, "licenseCategory", None)).lower()
        if license_name:
            flags.append("license:" + license_name)
        return HoudiniBuild(
            product=_text(_safe_call(self._hou, "applicationName", None), "Houdini"),
            version=version,
            build=build,
            platform=platform,
            feature_flags=tuple(sorted(flags)),
        )

    def _category_map(self) -> dict[str, Any]:
        raw = _safe_call(self._hou, "nodeTypeCategories", {})
        categories = raw.values() if isinstance(raw, Mapping) else raw or ()
        return {
            _text(_safe_call(category, "name", None)): category
            for category in categories
            if _text(_safe_call(category, "name", None))
        }

    def _package_dirs(self) -> tuple[Path, ...]:
        if self._package_directories is not None:
            return self._package_directories

        def environment(name: str) -> str:
            try:
                return _text(self._hou.getenv(name))
            except Exception:
                return _text(os.environ.get(name))

        def split_paths(value: str) -> list[Path]:
            if not value:
                return []
            separator = ";" if ";" in value else os.pathsep
            return [Path(item) for item in value.split(separator) if item.strip()]

        candidates: list[Path] = []
        user_preferences = environment("HOUDINI_USER_PREF_DIR")
        if user_preferences:
            candidates.append(Path(user_preferences) / "packages")
        hsite = environment("HSITE")
        version_tuple = _safe_call(self._hou, "applicationVersion", ())
        if hsite:
            site = Path(hsite)
            if isinstance(version_tuple, (tuple, list)) and len(version_tuple) >= 2:
                candidates.append(site / f"houdini{version_tuple[0]}.{version_tuple[1]}" / "packages")
        candidates.extend(split_paths(environment("HOUDINI_PACKAGE_DIR")))
        hfs = environment("HFS")
        if hfs:
            candidates.append(Path(hfs) / "packages")
        unique: dict[str, Path] = {}
        for candidate in candidates:
            key = str(candidate).replace("\\", "/").casefold()
            unique.setdefault(key, candidate)
        return tuple(unique.values())

    def package_directories(self) -> tuple[Path, ...]:
        """Return Houdini package directories in effective startup precedence."""

        return self._package_dirs()

    def _packages(self, has_labs: bool) -> tuple[PackageDefinition, ...]:
        packages: dict[str, PackageDefinition] = {}
        for directory in self._package_dirs():
            try:
                files = sorted(directory.glob("*.json"), key=lambda item: item.name.lower())
            except OSError:
                continue
            for path in files:
                try:
                    content = path.read_bytes()
                    payload = json.loads(content.decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                name = _text(payload.get("name") if isinstance(payload, Mapping) else None, path.stem)
                identifier = _identifier(name)
                if "sidefx" in identifier and "labs" in identifier:
                    identifier = "sidefx-labs"
                kind = "labs" if identifier == "sidefx-labs" else "package"
                candidate = PackageDefinition(
                    identifier=identifier,
                    name=name,
                    version=_package_version(payload) or "unknown",
                    kind=kind,
                    content_digest=_digest(content),
                    tags={"evidence": "houdini-package-json"},
                )
                existing = packages.get(identifier)
                if existing is not None and existing != candidate:
                    raise LiveCatalogExtractionError(
                        f"Multiple Houdini package files normalize to conflicting ID {identifier!r}."
                    )
                packages[identifier] = candidate
        if has_labs and "sidefx-labs" not in packages:
            evidence = b"sidefx-labs:loaded-operator"
            packages["sidefx-labs"] = PackageDefinition(
                identifier="sidefx-labs",
                name="SideFX Labs",
                version="unknown",
                kind="labs",
                content_digest=_digest(evidence),
                tags={"evidence": "loaded-labs-operator"},
            )
        return tuple(sorted(packages.values(), key=lambda item: item.identifier))

    def build_catalog(self) -> CatalogSnapshot:
        """Extract a snapshot before the strict serialization-boundary round trip."""
        category_map = self._category_map()
        categories = tuple(
            CategoryDefinition(
                name=name,
                label=_text(_safe_call(category, "label", None), name),
                network_family=_category_family(name),
            )
            for name, category in sorted(category_map.items())
        )
        pending: list[tuple[str, Any]] = []
        has_labs = False
        for category_name, category in sorted(category_map.items()):
            node_types = _safe_call(category, "nodeTypes", {})
            values = node_types.values() if isinstance(node_types, Mapping) else node_types or ()
            for node_type in values:
                raw_name = _text(_safe_call(node_type, "name", None))
                if raw_name:
                    pending.append((category_name, node_type))
                    has_labs = has_labs or raw_name.lower().startswith("labs::")
        packages = self._packages(has_labs)
        package_ids = {item.identifier for item in packages}
        operators: dict[tuple[str, str], OperatorDefinition] = {}
        for category_name, node_type in pending:
            raw_name = _text(_safe_call(node_type, "name", None))
            namespace, name, version = _type_components(raw_name, node_type)
            definition = _safe_call(node_type, "definition", None)
            package_id = "sidefx-labs" if (namespace or "").lower() == "labs" and "sidefx-labs" in package_ids else None
            if definition is not None:
                content_digest = _definition_digest(definition, raw_name)
                source = DefinitionSource(
                    kind="hda",
                    package_id=package_id,
                    hda_library=HdaLibrary(
                        identity="hda:" + content_digest.removeprefix("sha256:"),
                        content_digest=content_digest,
                        asset_name=raw_name,
                        asset_version=_text(_safe_call(definition, "version", None)) or version,
                    ),
                )
            elif package_id:
                source = DefinitionSource(kind="labs", package_id=package_id)
            else:
                source = DefinitionSource(kind="builtin")
            operators[(category_name, raw_name)] = OperatorDefinition(
                qualified_name=raw_name,
                name=name,
                namespace=namespace,
                version=version,
                category=category_name,
                aliases=_aliases(node_type, raw_name),
                source=source,
                parameters=_parameters(node_type, self._catalog_version),
                inputs=_connectors(node_type, category_name, "Input"),
                outputs=_connectors(node_type, category_name, "Output"),
                spare_parameter_policy=(
                    "declared_only"
                    if definition is not None
                    else (
                        "allowed"
                        if self._catalog_version == VALUE_CATALOG_VERSION
                        else "forbidden"
                    )
                ),
                locked=definition is not None,
                editable=definition is None,
                network_families=(_category_family(category_name),),
                instance_network=(
                    _instance_network_shape(node_type)
                    if self._catalog_version == VALUE_CATALOG_VERSION else None
                ),
            )
        snapshot = CatalogSnapshot(
            houdini=self._build(),
            categories=categories,
            operators=tuple(
                sorted(operators.values(), key=lambda item: (item.qualified_name, item.category))
            ),
            packages=packages,
            catalog_version=self._catalog_version,
        )
        return snapshot

    def get_catalog(self) -> CatalogSnapshot:
        return decode_catalog_snapshot(self.build_catalog().to_dict())
