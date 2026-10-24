"""The parm interface engine: ``edit`` ``node`` op ``spare_parms`` and ``hda``
``interface`` (BIBLE §4.5, §4.7; review 11 B9, review 26 P1 friction 7).

One spec shape, ``{add: [...], change: [...], remove: [names]}``, applied to a
``hou.ParmTemplateGroup``:

* on a node (``spare_parms``): only its spare parms (and spare folders) may be changed or
  removed, and the group goes back with ``setParmTemplateGroup``;
* on an asset (``interface``, ``hda create`` and ``save``): any parm of the asset's
  interface, and the group becomes the definition's.

``add`` entries are ``{name, type, ...}``; ``change`` entries ``{name, ...}`` set the same
attributes on an existing template (its value stays). Attributes are Houdini's template
fields, named as the readers report them (``min_strict``, ``max_strict``):
``label, default, size, min, max, min_strict, max_strict, menu_items, value_type, help,
disable_when, hide_when, join_next, tags, callback, hidden, folder_type``; placement is
``folder`` (a label, or a list of labels for nested folders; missing folders are made as
tabs), ``before`` or ``after`` (a parm name). Conditions use Houdini's syntax
(``{ interior == 0 }``) and every parm they name must exist once the spec is applied.

Verified on 22.0.466: ``createDigitalAsset`` leaves a subnet's spare parms on the instance
(the definition's group is empty until ``setParmTemplateGroup``); conditionals, tags,
``joinsWithNext`` and strict ranges survive the promotion; ``ParmTemplateGroup.find``
returns a copy, so a change is ``replace``.
"""

from __future__ import annotations

import contextlib
import difflib
import re
from collections.abc import Iterable, Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import hint_tool

from ._common import hou_exception_text, hou_message

SPARE_TYPES = (
    "float", "int", "string", "toggle", "menu", "button", "vector", "color", "file",
    "folder", "separator", "label",
)  # fmt: skip
FOLDER_TYPES = ("tabs", "collapsible", "simple", "radio")
ATTRS = frozenset(
    (
        "label", "default", "min", "max", "min_strict", "max_strict", "menu_items", "help",
        "disable_when", "hide_when", "join_next", "tags", "callback", "hidden", "folder_type",
    )
)  # fmt: skip
PLACEMENT = frozenset(("folder", "before", "after"))
ADD_KEYS = frozenset(("name", "type", "size", "value_type")) | ATTRS | PLACEMENT
CHANGE_KEYS = frozenset(("name",)) | ATTRS | PLACEMENT
MENU_VALUE_TYPES = ("string", "int")
"""``value_type`` of a spare ``menu`` (review 12 papercut 3). ``string`` (default) is a
``hou.MenuParmTemplate``: ``chs()`` gives the token and ``ch()`` the item index. ``int`` is a
``hou.IntParmTemplate`` with the menu: ``ch()``/``chi()`` give the item index and
``parm_get`` reports the index as the value (``chs()`` gives the index as text, not the
token). Verified on 22.0.466."""
_PARM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COND_NAME = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:==|!=|<=|>=|=~|<|>)")
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
SPARE_HINT = (
    "spare_parms is {add: [{name, type: " + "|".join(SPARE_TYPES) + ", label?, default?, "
    "size?, min?, max?, min_strict?, max_strict?, menu_items?: [{token, label}], value_type?: "
    "string|int (menus), help?, disable_when?, hide_when?: '{ parm == 1 }', join_next?, "
    "tags?, callback?, hidden?, folder_type?: " + "|".join(FOLDER_TYPES) + " (folders), "
    "folder?: label or [labels], before?, after?}], change: [{name, ...the same fields}], "
    "remove: [names]}."
)
COMPONENT_LETTERS = {"XYZW": "xyzw", "RGBA": "rgba", "UVW": "uvw", "XYWH": "xywh"}


def _bad(message: str, *, field: str = "spare_parms") -> ToolError:
    hint = (
        SPARE_HINT
        if field == "spare_parms"
        else SPARE_HINT.replace("spare_parms is", f"{field} is", 1)
    )
    return ToolError("invalid_argument", message, hint=hint)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def folder_name(label: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_]", "_", label).strip("_").lower() or "folder"
    return f"hp_{stem}"


# -- templates -----------------------------------------------------------------------


def walk(entries: Iterable[Any]) -> Iterator[Any]:
    """Every template of a group's ``entries()``, folder contents included."""
    import hou

    for template in entries:
        yield template
        if template.type() == hou.parmTemplateType.Folder:
            yield from walk(template.parmTemplates())


def template_kind(template: Any) -> str:
    """What a template is in this module's vocabulary (``int-menu`` for an int with a menu)."""
    import hou

    types = hou.parmTemplateType
    ptype = template.type()
    if ptype == types.Float:
        return "float"
    if ptype == types.Int:
        with contextlib.suppress(Exception):
            if template.menuItems():
                return "int-menu"
        return "int"
    for name in ("String", "Toggle", "Menu", "Button", "Folder", "Separator", "Label", "Ramp"):
        if ptype == getattr(types, name):
            return name.lower()
    return str(ptype).rsplit(".", 1)[-1].lower()


def component_names(template: Any) -> set[str]:
    """The parm names a template makes: its name, plus one per component of a tuple."""
    name = template.name()
    names = {name}
    try:
        size = int(template.numComponents())
    except Exception:
        size = 1
    if size > 1:
        scheme = str(getattr(template, "namingScheme", lambda: "")()).rsplit(".", 1)[-1]
        letters = COMPONENT_LETTERS.get(scheme)
        if letters:
            names.update(name + letters[i] for i in range(min(size, len(letters))))
        else:
            names.update(f"{name}{i + 1}" for i in range(size))
    return names


def _values(default: Any, kind: str, size: int, where: str) -> tuple[Any, ...]:
    """Default values of a float/int/string parm, one per component."""
    if default is None:
        fill: Any = "" if kind == "string" else 0
        values = [fill] * size
    else:
        values = default if isinstance(default, list) else [default]
        if len(values) == 1 and size > 1:
            values = values * size
    if len(values) != size:
        raise ToolError(
            "invalid_value", f"{where}: default has {len(values)} values; size is {size}."
        )
    if kind == "string":
        if not all(isinstance(v, str) for v in values):
            raise ToolError("invalid_value", f"{where}: a string default must be text.")
        return tuple(values)
    if not all(_is_number(v) for v in values):
        raise ToolError("invalid_value", f"{where}: a {kind} default must be numbers.")
    if kind == "int":
        if not all(float(v).is_integer() for v in values):
            raise ToolError("invalid_value", f"{where}: an int default must be whole numbers.")
        return tuple(int(v) for v in values)
    return tuple(float(v) for v in values)


def _menu_index(default: Any, tokens: list[str], where: str) -> int:
    """The item index a menu default names: a token, or a number. A whole number is the
    index; one that is no index but equals a token's text (``-1`` for token ``"-1"``) is
    that token."""
    if default is None:
        return 0
    if isinstance(default, str) and default in tokens:
        return tokens.index(default)
    if _is_number(default) and float(default).is_integer():
        if 0 <= default < len(tokens):
            return int(default)
        if str(int(default)) in tokens:
            return tokens.index(str(int(default)))
    raise ToolError(
        "invalid_value",
        f"{where}: default {default!r} is neither a menu token nor an item index.",
        hint=f"Tokens: {', '.join(tokens)}; or an index from 0 to {len(tokens) - 1}.",
    )


def _menu_items(items: Any, where: str, field: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(i, dict) and isinstance(i.get("token"), str) for i in items)
        or not all(set(i) <= {"token", "label"} for i in items)
    ):
        raise _bad(f"{where}: menu_items is a list of {{token, label}}.", field=field)
    tokens = tuple(i["token"] for i in items)
    if len(set(tokens)) != len(tokens):
        raise _bad(f"{where}: menu_items repeats a token.", field=field)
    return tokens, tuple(str(i.get("label") or i["token"]) for i in items)


def _condition(text: Any, where: str, key: str, field: str) -> str:
    if not isinstance(text, str):
        raise _bad(f"{where}: {key} must be a string such as '{{ parm == 1 }}'.", field=field)
    stripped = text.strip()
    if stripped and (
        not stripped.startswith("{")
        or not stripped.endswith("}")
        or stripped.count("{") != stripped.count("}")
    ):
        raise ToolError(
            "invalid_value",
            f"{where}: {key} {text!r} is not a Houdini condition.",
            hint="Houdini's syntax is { parm == value }: comparisons in one brace all hold "
            "(and); several braces mean or. An empty string clears the condition.",
            candidates=[f"{{ {stripped} }}"] if stripped and "{" not in stripped else [],
        )
    return stripped


def condition_names(text: str) -> set[str]:
    """The parm names a condition compares (the left side of each comparison)."""
    return set(_COND_NAME.findall(_QUOTED.sub('""', text)))


def _folder_path(value: Any, where: str, field: str) -> tuple[str, ...]:
    labels = [value] if isinstance(value, str) else value
    if (
        not isinstance(labels, list)
        or not labels
        or not all(isinstance(label, str) and label.strip() for label in labels)
    ):
        raise _bad(
            f"{where}: folder is a label, or a list of labels for nested folders.", field=field
        )
    return tuple(labels)


def _set_attrs(template: Any, kind: str, spec: dict[str, Any], where: str, field: str) -> None:
    """Apply the :data:`ATTRS` in ``spec`` to ``template`` (a new or cloned one)."""
    import hou

    for key in ("label", "help", "callback"):
        value = spec.get(key)
        if value is not None and not isinstance(value, str):
            raise _bad(f"{where}: {key} must be a string.", field=field)
    for key in ("min_strict", "max_strict", "join_next", "hidden"):
        value = spec.get(key)
        if value is not None and not isinstance(value, bool):
            raise _bad(f"{where}: {key} is true or false.", field=field)
    if spec.get("label") is not None:
        template.setLabel(spec["label"])
    if spec.get("help") is not None:
        template.setHelp(spec["help"])
    if spec.get("hidden") is not None:
        template.hide(spec["hidden"])
    if spec.get("join_next") is not None:
        template.setJoinWithNext(spec["join_next"])
    for key, cond in (("disable_when", "DisableWhen"), ("hide_when", "HideWhen")):
        if key in spec:
            text = _condition(spec[key], where, key, field)
            template.setConditional(getattr(hou.parmCondType, cond), text)
    tags = spec.get("tags")
    if tags is not None:
        if not isinstance(tags, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in tags.items()
        ):
            raise _bad(f"{where}: tags is an object of strings.", field=field)
        merged = dict(template.tags())
        merged.update(tags)
        template.setTags(merged)
    if spec.get("callback") is not None:
        if kind in ("folder", "separator", "label"):
            raise _bad(f"{where}: a {kind} takes no callback.", field=field)
        template.setScriptCallback(spec["callback"])
        template.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    ranged = kind in ("float", "int")
    for key in ("min", "max"):
        value = spec.get(key)
        if value is not None and (not ranged or not _is_number(value)):
            raise _bad(f"{where}: {key} is a number, for float, int and vector parms.", field=field)
    for key in ("min_strict", "max_strict"):
        if spec.get(key) is not None and not ranged:
            raise _bad(f"{where}: {key} is for float, int and vector parms.", field=field)
    if ranged:
        cast = int if kind == "int" else float
        low, high = spec.get("min"), spec.get("max")
        if low is not None and high is not None and low > high:
            raise _bad(f"{where}: min {low} is above max {high}.", field=field)
        width = template.maxValue() - template.minValue()
        if low is not None:
            template.setMinValue(cast(low))
            if high is None and template.maxValue() < low:
                # Only min given, above the default range: keep the range's width.
                template.setMaxValue(cast(low + (width if width > 0 else 1)))
        if high is not None:
            template.setMaxValue(cast(high))
            if low is None and template.minValue() > high:
                template.setMinValue(cast(high - (width if width > 0 else 1)))
        if spec.get("min_strict") is not None:
            template.setMinIsStrict(spec["min_strict"])
        if spec.get("max_strict") is not None:
            template.setMaxIsStrict(spec["max_strict"])
    if spec.get("menu_items") is not None:
        if kind not in ("menu", "int-menu", "string"):
            raise _bad(f"{where}: menu_items is for menu and string parms.", field=field)
        tokens, labels = _menu_items(spec["menu_items"], where, field)
        template.setMenuItems(tokens)
        template.setMenuLabels(labels)
        if kind == "string" and template.menuType() == hou.menuType.Normal:
            template.setMenuType(hou.menuType.StringReplace)
    if spec.get("folder_type") is not None:
        if kind != "folder":
            raise _bad(f"{where}: folder_type is for folders.", field=field)
        if spec["folder_type"] not in FOLDER_TYPES:
            raise _bad(
                f"{where}: folder_type must be one of {', '.join(FOLDER_TYPES)}.", field=field
            )
        template.setFolderType(_folder_type(spec["folder_type"]))
    if "default" in spec:
        _set_default(template, kind, spec["default"], where, field)


def _folder_type(name: str) -> Any:
    import hou

    return {
        "tabs": hou.folderType.Tabs,
        "collapsible": hou.folderType.Collapsible,
        "simple": hou.folderType.Simple,
        "radio": hou.folderType.RadioButtons,
    }[name]


def _set_default(template: Any, kind: str, default: Any, where: str, field: str) -> None:
    if kind in ("button", "folder", "separator", "label", "ramp"):
        if default is not None:
            raise _bad(f"{where}: a {kind} takes no default.", field=field)
        return
    if kind == "toggle":
        if default is not None and not isinstance(default, bool):
            raise ToolError("invalid_value", f"{where}: a toggle default is true or false.")
        template.setDefaultValue(bool(default))
        return
    if kind in ("menu", "int-menu"):
        index = _menu_index(default, list(template.menuItems()), where)
        template.setDefaultValue(index if kind == "menu" else (index,))
        return
    size = int(template.numComponents())
    values = _values(default, "string" if kind == "string" else kind, size, where)
    if kind == "float" and default is None and template.look() == _color_look():
        values = (1.0,) * size
    template.setDefaultValue(values)


def _color_look() -> Any:
    import hou

    return hou.parmLook.ColorSquare


def _new_template(spec: dict[str, Any], where: str, field: str) -> tuple[Any, str]:
    """A bare template for an ``add`` entry (name, type, size, menu); attributes after."""
    import hou

    name = spec.get("name")
    kind = spec.get("type")
    if kind not in SPARE_TYPES:
        raise _bad(
            f"{where}: type must be one of {', '.join(SPARE_TYPES)}; got {kind!r}.", field=field
        )
    label = spec.get("label")
    if kind == "folder":
        if not isinstance(label, str) or not label.strip():
            raise _bad(f"{where}: a folder needs a label.", field=field)
        name = name if name is not None else folder_name(label)
    if not isinstance(name, str) or not _PARM_NAME.match(name):
        raise _bad(f"{where}: {name!r} is not a parm name (letters, digits and _).", field=field)
    if label is not None and not isinstance(label, str):
        raise _bad(f"{where}: label must be a string.", field=field)
    label = name if label is None else label
    size = spec.get("size", 3 if kind in ("vector", "color") else 1)
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 4:
        raise _bad(f"{where}: size must be an integer from 1 to 4.", field=field)
    if size != 1 and kind in ("toggle", "menu", "button", "folder", "separator", "label"):
        raise _bad(f"{where}: a {kind} has size 1.", field=field)
    value_type = spec.get("value_type", "string")
    if kind != "menu" and "value_type" in spec:
        raise _bad(f"{where}: value_type is for type menu.", field=field)
    if value_type not in MENU_VALUE_TYPES:
        raise _bad(f"{where}: value_type must be string or int; got {value_type!r}.", field=field)
    if kind == "menu" and spec.get("menu_items") is None:
        raise _bad(f"{where}: a menu needs menu_items: [{{token, label}}, ...].", field=field)
    if kind in ("float", "vector", "color"):
        extra: dict[str, Any] = {}
        if kind == "vector":
            extra["naming_scheme"] = hou.parmNamingScheme.XYZW
        elif kind == "color":
            extra["naming_scheme"] = hou.parmNamingScheme.RGBA
            extra["look"] = hou.parmLook.ColorSquare
        template = hou.FloatParmTemplate(
            name,
            label,
            size,
            default_value=(1.0 if kind == "color" else 0.0,) * size,
            min=0.0,
            max=10.0 if kind == "vector" else 1.0,
            **extra,
        )
        return template, "float"
    if kind == "int":
        return hou.IntParmTemplate(
            name, label, size, default_value=(0,) * size, min=0, max=10
        ), "int"
    if kind in ("string", "file"):
        string_type = (
            hou.stringParmType.FileReference if kind == "file" else hou.stringParmType.Regular
        )
        template = hou.StringParmTemplate(
            name, label, size, default_value=("",) * size, string_type=string_type
        )
        return template, "string"
    if kind == "toggle":
        return hou.ToggleParmTemplate(name, label, default_value=False), "toggle"
    if kind == "menu":
        tokens, labels = _menu_items(spec["menu_items"], where, field)
        if value_type == "int":
            template = hou.IntParmTemplate(
                name, label, 1, default_value=(0,), menu_items=tokens, menu_labels=labels
            )
            return template, "int-menu"
        return hou.MenuParmTemplate(name, label, tokens, menu_labels=labels), "menu"
    if kind == "button":
        return hou.ButtonParmTemplate(name, label), "button"
    if kind == "folder":
        return hou.FolderParmTemplate(name, label, folder_type=hou.folderType.Tabs), "folder"
    if kind == "separator":
        return hou.SeparatorParmTemplate(name), "separator"
    return hou.LabelParmTemplate(name, label), "label"


def _placement(spec: dict[str, Any], where: str, field: str) -> dict[str, Any] | None:
    given = [key for key in ("folder", "before", "after") if spec.get(key) is not None]
    if len(given) > 1:
        raise _bad(f"{where}: pass one of folder, before and after.", field=field)
    if not given:
        return None
    key = given[0]
    if key == "folder":
        return {"folder": _folder_path(spec["folder"], where, field)}
    if not isinstance(spec[key], str) or not spec[key]:
        raise _bad(f"{where}: {key} names a parm.", field=field)
    return {key: spec[key]}


# -- planning --------------------------------------------------------------------------


class Interface:
    """What a spec may touch: the group's templates by name (``None`` for a parm a new
    node's type has but no template is known for), the names that may be changed or
    removed (``None``: all), and the parm names conditions may name."""

    def __init__(
        self,
        templates: dict[str, Any],
        editable: set[str] | None,
        parm_names: set[str],
        *,
        owner: str,
        field: str,
        folders: dict[str, Any] | None = None,
    ) -> None:
        self.templates = templates
        self.editable = editable
        self.parm_names = parm_names
        self.owner = owner
        self.field = field
        self.folders = folders or {}
        """Folder label -> template, for ``change`` by label."""

    @classmethod
    def of_group(
        cls,
        group: Any,
        *,
        owner: str,
        field: str,
        editable: set[str] | None = None,
        parm_names: set[str] | None = None,
    ) -> Interface:
        import hou

        templates: dict[str, Any] = {}
        folders: dict[str, Any] = {}
        names: set[str] = set()
        for template in walk(group.entries()):
            templates[template.name()] = template
            names |= component_names(template)
            if template.type() == hou.parmTemplateType.Folder:
                folders.setdefault(template.label(), template)
        return cls(
            templates,
            editable,
            names | (parm_names or set()),
            owner=owner,
            field=field,
            folders=folders,
        )

    def resolve(self, name: Any, where: str, action: str) -> str:
        """The template name ``name`` (a parm or folder name, or a folder label) refers to,
        refused when it may not be changed."""
        if not isinstance(name, str) or not name:
            raise _bad(f"{where}: name must be a parm name.", field=self.field)
        if name not in self.templates and name in self.folders:
            name = self.folders[name].name()
        if name not in self.templates:
            raise ToolError(
                "parm_not_found",
                f"{where}: {self.owner} has no parm {name!r} to {action}.",
                candidates=difflib.get_close_matches(name, sorted(self.templates), n=5, cutoff=0.6),
            )
        if self.editable is not None and name not in self.editable:
            raise _bad(
                f"{where}: {self.owner}/{name} belongs to the node's type; only spare parms can "
                f"be {action}d.",
                field=self.field,
            )
        return name


def plan(spec: Any, iface: Interface) -> dict[str, Any]:
    """Validate a spec against ``iface`` without changing anything; returns what
    :func:`apply_to_group` applies: ``remove`` (template names), ``change`` and ``add``
    (``(name, template, placement)``)."""
    field = iface.field
    if not isinstance(spec, dict) or not spec or set(spec) - {"add", "change", "remove"}:
        raise _bad(f"{field} must be an object with add, change and/or remove.", field=field)
    adds = spec.get("add") or []
    changes = spec.get("change") or []
    removes = spec.get("remove") or []
    if not all(isinstance(x, list) for x in (adds, changes, removes)):
        raise _bad(f"{field} add, change and remove must be lists.", field=field)
    if not all(isinstance(n, str) and n for n in removes):
        raise _bad(f"{field}.remove lists parm names.", field=field)
    names = set(iface.parm_names)
    present = set(iface.templates)
    removed: list[str] = []
    for i, name in enumerate(removes):
        resolved = iface.resolve(name, f"{field}.remove[{i}]", "remove")
        if resolved not in removed:
            removed.append(resolved)
            present.discard(resolved)
            template = iface.templates.get(resolved)
            names -= component_names(template) if template is not None else {resolved}
    conditions: list[tuple[str, str]] = []
    changed: list[tuple[str, Any, dict[str, Any] | None]] = []
    change_entries: list[tuple[dict[str, Any], str]] = []
    for i, entry in enumerate(changes):
        where = f"{field}.change[{i}]"
        if not isinstance(entry, dict):
            raise _bad(f"{where} must be an object.", field=field)
        unknown = set(entry) - CHANGE_KEYS
        if unknown:
            raise _bad(f"{where}: unexpected keys {sorted(unknown)}.", field=field)
        name = iface.resolve(entry.get("name"), where, "change")
        if name in removed:
            raise _bad(f"{where}: {name!r} is also removed.", field=field)
        placement = _placement(entry, where, field)
        _check_anchor(placement, present, where)
        conditions += [(where, entry[k]) for k in ("disable_when", "hide_when") if entry.get(k)]
        change_entries.append((entry, where))
        current = iface.templates.get(name)
        if current is None:
            # A spare parm an earlier op of a plan adds to a node the plan creates: its
            # template exists only once that op runs, which checks the fields.
            changed.append((name, None, placement))
            continue
        template = current.clone()
        _set_attrs(template, template_kind(template), entry, where, field)
        changed.append((name, template, placement))
    added: list[tuple[str, Any, dict[str, Any] | None]] = []
    seen: set[str] = set()
    for i, entry in enumerate(adds):
        where = f"{field}.add[{i}]"
        if not isinstance(entry, dict):
            raise _bad(f"{where} must be an object.", field=field)
        unknown = set(entry) - ADD_KEYS
        if unknown:
            raise _bad(f"{where}: unexpected keys {sorted(unknown)}.", field=field)
        template, kind = _new_template(entry, where, field)
        name = template.name()
        _set_attrs(template, kind, {k: v for k, v in entry.items() if k != "label"}, where, field)
        if name in seen:
            raise _bad(f"{where}: {name!r} is added twice.", field=field)
        if name in present or (component_names(template) & names - set(removed)):
            raise ToolError(
                "name_collision",
                f"{where}: {iface.owner} already has a parm {name!r}.",
                hint="Pick another name, change the existing parm, or remove it in the same call.",
            )
        placement = _placement(entry, where, field)
        _check_anchor(placement, present | seen, where)
        seen.add(name)
        names |= component_names(template)
        conditions += [(where, entry[k]) for k in ("disable_when", "hide_when") if entry.get(k)]
        added.append((name, template, placement))
    for where, text in conditions:
        missing = sorted(condition_names(text) - names)
        if missing:
            raise ToolError(
                "invalid_value",
                f"{where}: the condition {text!r} names {', '.join(missing)}, which "
                f"{'is' if len(missing) == 1 else 'are'} not a parm of {iface.owner}.",
                hint="A condition compares parms of the same node: { parm == value }.",
                candidates=difflib.get_close_matches(missing[0], sorted(names), n=5, cutoff=0.6),
            )
    return {
        "remove": removed,
        "change": changed,
        "add": added,
        "change_entries": change_entries,
        "field": field,
    }


def _check_anchor(placement: dict[str, Any] | None, names: set[str], where: str) -> None:
    """A ``before``/``after`` names a parm that exists when the entry is placed (changes
    run before adds, adds in order)."""
    anchor = (placement or {}).get("before") or (placement or {}).get("after")
    if anchor is not None and anchor not in names:
        raise ToolError(
            "parm_not_found",
            f"{where}: no parm {anchor!r} to place it next to.",
            candidates=difflib.get_close_matches(anchor, sorted(names), n=5, cutoff=0.6),
        )


def _ensure_folder(group: Any, labels: tuple[str, ...]) -> Any:
    """The folder at ``labels`` (nested), made as tabs where missing."""
    import hou

    for depth in range(1, len(labels) + 1):
        path = labels[:depth]
        key = path[0] if depth == 1 else path
        if group.findFolder(key) is None:
            folder = hou.FolderParmTemplate(folder_name(path[-1]), path[-1])
            if depth == 1:
                group.append(folder)
            else:
                parent = path[:-1]
                group.appendToFolder(parent[0] if len(parent) == 1 else parent, folder)
    return labels[0] if len(labels) == 1 else labels


def _place(group: Any, template: Any, placement: dict[str, Any] | None) -> None:
    if placement is None:
        group.append(template)
    elif "before" in placement:
        group.insertBefore(placement["before"], template)
    elif "after" in placement:
        group.insertAfter(placement["after"], template)
    else:
        group.appendToFolder(_ensure_folder(group, placement["folder"]), template)


def apply_to_group(group: Any, planned: dict[str, Any]) -> None:
    """Apply a :func:`plan` to ``group`` in place: removes, then changes, then adds."""
    for name in planned["remove"]:
        group.remove(name)
    entries = planned.get("change_entries") or []
    for i, (name, template, placement) in enumerate(planned["change"]):
        if i < len(entries):
            # From the group as the removes and earlier changes left it: a folder's clone
            # taken when planning would put back the children those removed or moved.
            entry, where = entries[i]
            template = group.find(name).clone()
            _set_attrs(template, template_kind(template), entry, where, planned["field"])
        if placement is None:
            group.replace(name, template)
        else:
            group.remove(name)
            _place(group, template, placement)
    for _name, template, placement in planned["add"]:
        _place(group, template, placement)


# -- on a node (spare_parms) -------------------------------------------------------------


def node_interface(node: Any, field: str = "spare_parms") -> Interface:
    """The interface a ``spare_parms`` spec sees on ``node``: everything may be named by a
    condition or a placement, only the spare parms (not the type's) changed or removed."""
    group = node.parmTemplateGroup()
    try:
        own = node.type().parmTemplateGroup()
        own_names = {t.name() for t in walk(own.entries())}
    except Exception:
        own_names = set()
    names = set()
    with contextlib.suppress(Exception):
        names = {p.name() for p in node.parms()} | {t.name() for t in node.parmTuples()}
    iface = Interface.of_group(group, owner=node.path(), field=field, parm_names=names)
    iface.editable = set(iface.templates) - own_names
    return iface


def plan_spare_parms(node: Any, spec: Any) -> dict[str, Any]:
    """Validate ``spare_parms`` against ``node`` without changing it. A removed or
    changed name may be a component (``tx``): it names its tuple."""

    def tuple_name(name: Any) -> Any:
        target = node.parm(name) if isinstance(name, str) and name else None
        if target is not None and target.tuple().name() != name:
            return target.tuple().name()
        return name

    if isinstance(spec, dict) and isinstance(spec.get("remove"), list):
        spec = {**spec, "remove": [tuple_name(name) for name in spec["remove"]]}
    if isinstance(spec, dict) and isinstance(spec.get("change"), list):
        spec = {
            **spec,
            "change": [
                {**entry, "name": tuple_name(entry.get("name"))}
                if isinstance(entry, dict)
                else entry
                for entry in spec["change"]
            ],
        }
    planned = plan(spec, node_interface(node))
    planned["tuples"] = [node.parmTuple(name) for name in planned["remove"]]
    return planned


def apply_spare_parms(node: Any, planned: dict[str, Any], rollback: Any) -> dict[str, Any]:
    """Apply a :func:`plan_spare_parms` plan with ``setParmTemplateGroup``. On rollback the
    old template group comes back, and so do the removed parms' values."""
    import hou

    before = node.parmTemplateGroup()
    saved = []
    for ptuple in planned.get("tuples") or ():
        for parm in ptuple or ():
            with contextlib.suppress(Exception):
                keys = tuple(parm.keyframes())
                saved.append((parm.name(), keys, None if keys else _plain_value(parm)))

    def restore() -> None:
        node.setParmTemplateGroup(before)
        for name, keys, value in saved:
            parm = node.parm(name)
            if parm is not None and keys:
                parm.setKeyframes(keys)
            elif parm is not None and value is not None:
                parm.set(value)

    group = node.parmTemplateGroup()
    apply_to_group(group, planned)
    try:
        node.setParmTemplateGroup(group)
    except hou.PermissionError as exc:
        raise ToolError(
            "locked",
            f"Cannot change the parms of {node.path()}: {hou_message(exc)}",
            hint=f"Unlock the asset with "
            f"{hint_tool('node_edit', path=node.path(), lock=False)} first.",
            hou_exception=hou_exception_text(exc),
        ) from exc
    except hou.Error as exc:
        raise ToolError(
            "invalid_argument",
            f"Houdini refused the spare parms on {node.path()}: {hou_message(exc)}",
            hint=SPARE_HINT,
            hou_exception=hou_exception_text(exc),
        ) from exc
    rollback.add(restore)
    out: dict[str, Any] = {
        "added": [f"{node.path()}/{name}" for name, _t, _p in planned["add"]],
        "removed": [f"{node.path()}/{name}" for name in planned["remove"]],
    }
    if planned["change"]:
        out["changed"] = [f"{node.path()}/{name}" for name, _t, _p in planned["change"]]
    return out


def _plain_value(parm: Any) -> Any:
    from .parms import _kind

    kind = _kind(parm.parmTemplate())
    if kind in ("button", "folder", "label", "data"):
        return None
    if kind == "string":
        return parm.unexpandedString()
    if kind == "ramp":
        return parm.evalAsRamp()
    return parm.eval()


# -- on a node a plan creates (dry_run) ---------------------------------------------------


def check_new_node(node_type: Any, path: str, spare: set[str], spec: Any) -> set[str]:
    """Validate a ``spare_parms`` spec for a node an earlier op of the same plan creates
    (``dry_run`` and the up-front validation): the shapes, the conditions and the names
    against ``node_type``'s parms and the spare parms earlier ops add (``spare``). Returns
    the names it adds."""
    import hou

    templates: dict[str, Any] = {}
    names: set[str] = set(spare)
    with contextlib.suppress(Exception):
        for template in walk(node_type.parmTemplateGroup().entries()):
            templates[template.name()] = template
            names |= component_names(template)
    for name in spare:
        templates.setdefault(name, None)
    iface = Interface(templates, set(spare), names, owner=path, field="spare_parms")
    with contextlib.suppress(Exception):
        iface.folders = {
            t.label(): t
            for t in templates.values()
            if t is not None and t.type() == hou.parmTemplateType.Folder
        }
    planned = plan(spec, iface)
    return {name for name, _t, _p in planned["add"]}


def add_names(spec: Any) -> set[str]:
    """The names a spec's ``add`` entries would make (no validation)."""
    if not isinstance(spec, dict):
        return set()
    out = set()
    for entry in spec.get("add") or []:
        if isinstance(entry, dict):
            if isinstance(entry.get("name"), str):
                out.add(entry["name"])
            elif entry.get("type") == "folder" and isinstance(entry.get("label"), str):
                out.add(folder_name(entry["label"]))
    return out
