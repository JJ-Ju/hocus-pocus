"""Parm tools: ``parm_get``, ``parm_set`` and the shared parm value engine.

See docs/BIBLE.md §4.5, §5 items 1, 2, 5, 6 and D10. Verified against Houdini 22.0.466:

- ``node.parm("t")`` is None; ``parmTuple("t")`` works. Paths resolve to a parm first,
  then to a tuple; a tuple path reads/writes every component.
- ``set()`` on a keyed or expression parm adds a key (and leaves an expression in
  charge). ``animation: replace`` deletes the keys first so the value sticks.
- ``setKeyframe`` on an expression channel copies the expression onto the new key.
- ``revertToDefaults()`` keeps keyframes; ``revert_to_default`` deletes them first.
- Menus: ``eval()`` is the index, ``evalAsString()`` the token; ``set(token)`` works,
  ``set(label)`` raises and an out-of-range ``set(index)`` is silently ignored.
- Strict template ranges are clamped silently by Houdini; they are refused here.
- ``unexpandedString()`` raises on a string parm with keyframes (use ``rawValue()``).
- ``parm.set(other_parm)`` writes ``ch("relative/path")``.
- ``hou.Keyframe(value, time)`` takes *seconds*; frames are always set with ``setFrame``.
- Edits inside a locked HDA raise ``hou.PermissionError`` before changing anything.
"""

from __future__ import annotations

import contextlib
import difflib
import math
import os
import re
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import BARE, hint_tool

from ._common import (
    arg_bool,
    dynamic_menu_note,
    elide_string,
    hou_exception_text,
    hou_message,
    menu_is_dynamic,
    require_node,
)
from ._diag import cheap_cook_problems
from .registry import HostContext, tool

INCLUDE_KEYS = ("keys", "menu", "template", "ramp", "multiparm")
VALUE_FIELDS = (
    "value",
    "expression",
    "keyframe",
    "keyframes",
    "channel_ref",
    "ramp",
    "multiparm_count",
    "revert_to_default",
    "press",
    "patch",
    "value_file",
)
ITEM_KEYS = frozenset((*VALUE_FIELDS, "path", "language", "animation"))
_FLAG_FIELDS = ("revert_to_default", "press")
"""Value fields that act only when ``true``; ``false``, ``0`` or null mean "not given"."""
ANIMATION_MODES = ("replace", "key", "keep")
LANGUAGES = ("hscript", "python")
VALUE_FILE_MAX_BYTES = 8 * 1024 * 1024
"""The largest ``value_file`` a set reads (a VEX or Python snippet is kilobytes)."""
PATCH_KEYS = frozenset(("find", "replace", "all"))
MENU_ITEMS_LIMIT = 50
MULTIPARM_INSTANCES_LIMIT = 20
CANDIDATES_LIMIT = 8
_SEGMENT_FUNCTION = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\(\s*\)\s*$")
"""``bezier()``, ``linear()``, ``constant()``...: a keyframe's interpolation, not an expression."""

_RAMP_BASIS_ALIASES = {
    "linear": "Linear",
    "constant": "Constant",
    "catmullrom": "CatmullRom",
    "catmull-rom": "CatmullRom",
    "catmull_rom": "CatmullRom",
    "monotonecubic": "MonotoneCubic",
    "monotone-cubic": "MonotoneCubic",
    "monotone_cubic": "MonotoneCubic",
    "bezier": "Bezier",
    "bspline": "BSpline",
    "b-spline": "BSpline",
    "hermite": "Hermite",
}
RAMP_BASES = ("linear", "constant", "catmullrom", "monotonecubic", "bezier", "bspline", "hermite")


# -- small helpers ----------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


FLOAT_DIGITS = 12
"""Significant digits for evaluated floats: 2.4000000000000004 reads as 2.4."""


def _json_number(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return float(f"{value:.{FLOAT_DIGITS}g}")
    return value


def _frame_arg(value: Any, field: str = "frame") -> float | None:
    if value is None:
        return None
    if not _is_number(value) or not math.isfinite(value):
        raise ToolError("invalid_argument", f"'{field}' must be a number.")
    return float(value)


def _language_name(language: Any) -> str:
    return "python" if "python" in str(language).lower() else "hscript"


def _hou_language(name: str) -> Any:
    import hou

    return hou.exprLanguage.Python if name == "python" else hou.exprLanguage.Hscript


@contextlib.contextmanager
def _at_frame(frame: float | None) -> Iterator[None]:
    """Temporarily move the global frame (for ``set()``, which acts at the current time)."""
    if frame is None:
        yield
        return
    import hou

    old = hou.frame()
    if old == frame:
        yield
        return
    hou.setFrame(frame)
    try:
        yield
    finally:
        hou.setFrame(old)


def _is_tuple(target: Any) -> bool:
    import hou

    return isinstance(target, hou.ParmTuple)


def _components(target: Any) -> list[Any]:
    return list(target) if _is_tuple(target) else [target]


def _target_path(target: Any) -> str:
    if _is_tuple(target):
        return f"{target.node().path()}/{target.name()}"
    return target.path()


def _normalize(target: Any) -> Any:
    """A one-component tuple is treated as its parm."""
    if _is_tuple(target) and len(target) == 1:
        return target[0]
    return target


# -- templates --------------------------------------------------------------------


def _kind(template: Any) -> str:
    """Houdini parm template type as a lowercase word; multiparm folders are ``multiparm``."""
    import hou

    ptype = template.type()
    types = hou.parmTemplateType
    if ptype == types.Folder:
        try:
            folder_type = template.folderType()
            if folder_type in (
                hou.folderType.MultiparmBlock,
                hou.folderType.ScrollingMultiparmBlock,
                hou.folderType.TabbedMultiparmBlock,
            ):
                return "multiparm"
        except Exception:
            pass
        return "folder"
    for name in ("Float", "Int", "String", "Toggle", "Menu", "Button", "Ramp", "Data", "Label"):
        if ptype == getattr(types, name):
            return name.lower()
    return str(ptype).rsplit(".", 1)[-1].lower()


def _menu_mode(template: Any, kind: str, parm: Any = None) -> str | None:
    """``strict`` for ordinal menus (value must be an item), ``free`` for string
    replace/toggle menus (any text allowed), None when the parm has no menu. With
    ``parm``, a string parm whose menu only the node builds (a Copernicus ``signature``:
    no template items, no script, a normal menu) counts as a strict menu (review 18
    papercut 4)."""
    import hou

    if kind == "menu":
        return "strict"
    if kind not in ("string", "int"):
        return None
    try:
        if not template.menuItems() and not menu_is_dynamic(template):
            if kind == "string" and parm is not None and _node_built_menu(parm):
                return "strict"
            return None
    except Exception:
        return None
    try:
        menu_type = template.menuType()
    except Exception:
        return "strict"
    if menu_type in (hou.menuType.StringReplace, hou.menuType.StringToggle):
        return "free"
    return "strict"


def _node_built_menu(parm: Any) -> bool:
    """Whether the node gives this string parm menu items its template does not list."""
    try:
        return bool(parm.menuItems())
    except Exception:
        return False


ICON_MARKUP = re.compile(r"^!\[[^\]]*\]\s*")
"""A leading ``![BUTTONS_blendmode_over]`` icon reference in a menu label (Copernicus)."""


def menu_label(label: str) -> str:
    """A menu label without its leading icon markup (review 18 papercut 9)."""
    return ICON_MARKUP.sub("", label) if label.startswith("![") else label


def _range(template: Any, kind: str) -> dict[str, Any]:
    if kind not in ("float", "int"):
        return {}
    try:
        return {
            "min": template.minValue(),
            "max": template.maxValue(),
            "min_strict": bool(template.minIsStrict()),
            "max_strict": bool(template.maxIsStrict()),
        }
    except Exception:
        return {}


def _unwrap(values: Any, size: int) -> Any:
    if isinstance(values, tuple | list):
        values = [_json_number(v) for v in values]
        return values[0] if size == 1 and len(values) == 1 else values
    return _json_number(values)


def _template_dict(template: Any, kind: str, parm: Any | None) -> dict[str, Any]:
    out: dict[str, Any] = {"label": template.label(), "type": kind}
    try:
        size = template.numComponents()
    except Exception:
        size = 1
    out["size"] = size
    try:
        default = _unwrap(template.defaultValue(), size)
        if kind == "menu" and parm is not None and isinstance(default, int):
            items = parm.menuItems()
            if 0 <= default < len(items):
                default = items[default]
        out["default"] = default
    except Exception:
        out["default"] = None
    out.update(_range(template, kind))
    try:
        out["help"] = template.help() or None
    except Exception:
        out["help"] = None
    if kind == "string":
        with contextlib.suppress(Exception):
            out["string_type"] = str(template.stringType()).rsplit(".", 1)[-1]
    return out


# -- reading ----------------------------------------------------------------------


def _key_info(parm: Any) -> dict[str, Any]:
    """``{count, first, last, expression?, language?, keyed}`` from the parm's keyframes."""
    try:
        keys = parm.keyframes()
    except Exception:
        keys = ()
    if not keys:
        return {}
    info: dict[str, Any] = {
        "count": len(keys),
        "first": keys[0].frame(),
        "last": keys[-1].frame(),
    }
    expressions = set()
    for key in keys:
        try:
            expressions.add(key.expression())
        except Exception:
            expressions.add(None)
    expression = next(iter(expressions)) if len(expressions) == 1 else None
    segment = bool(expression) and bool(_SEGMENT_FUNCTION.match(expression))
    if expression and not segment:
        info["expression"] = expression
        try:
            language = keys[0].expressionLanguage()
        except Exception:
            language = parm.expressionLanguage() if len(keys) == 1 else None
        info["language"] = _language_name(language)
    info["keyed"] = len(keys) > 1 or segment or not expression
    return info


def _ramp_number(value: Any) -> Any:
    """A ramp key or value at 6 significant digits: ramps store float32, and
    ``0.550000011921`` reads as noise (review 18 papercut 10)."""
    if isinstance(value, float) and math.isfinite(value):
        return _json_number(float(f"{value:.6g}"))
    return _json_number(value)


def _ramp_dict(ramp: Any) -> dict[str, Any]:
    values = [
        [_ramp_number(c) for c in v] if isinstance(v, tuple | list) else _ramp_number(v)
        for v in ramp.values()
    ]
    return {
        "basis": [str(b).rsplit(".", 1)[-1].lower() for b in ramp.basis()],
        "keys": [_ramp_number(k) for k in ramp.keys()],  # noqa: SIM118 (hou.Ramp)
        "values": values,
        "is_color": bool(ramp.isColor()),
    }


def _eval(parm: Any, kind: str, menu_mode: str | None, frame: float | None) -> Any:
    if kind in ("button", "folder", "label"):
        return None
    try:
        if kind == "ramp":
            return _ramp_dict(parm.eval() if frame is None else parm.evalAtFrame(frame))
        if kind in ("string", "data") or (menu_mode == "strict" and kind != "int"):
            return parm.evalAsString() if frame is None else parm.evalAsStringAtFrame(frame)
        value = parm.eval() if frame is None else parm.evalAtFrame(frame)
    except Exception:
        return None
    if kind == "toggle":
        return bool(value)
    return _json_number(value)


def _int_menu_token(parm: Any, value: Any) -> Any:
    """An int parm with a menu stores the item index: its token is ``menuItems()[value]``
    (``evalAsString`` would give the number)."""
    try:
        items = parm.menuItems()
        if isinstance(value, int) and 0 <= value < len(items):
            return items[value]
    except Exception:
        pass
    return value


def _raw(parm: Any, kind: str) -> Any:
    if kind == "ramp":
        return None  # rawValue() is the key count as text; value says it (review 18)
    if kind == "string":
        try:
            return parm.unexpandedString()
        except Exception:  # keyframed string parms: rawValue() is the expression
            pass
    try:
        return parm.rawValue()
    except Exception:
        return None


def _holds(parm: Any, value: Any) -> bool:
    """Whether ``parm`` already evaluates to ``value`` (numbers within float noise)."""
    try:
        current = parm.eval()
    except Exception:
        return False
    if _is_number(current) and _is_number(value):
        return abs(current - value) <= 1e-6 * max(1.0, abs(value))
    return current == value


def _parm_locked(parm: Any) -> bool:
    """The parm's own lock (``locked``; BIBLE §4.1)."""
    try:
        return bool(parm.isLocked())
    except Exception:
        return False


def _hda_locked(parm: Any) -> bool:
    """The parm's node is inside a locked asset and not editable (``hda_locked``)."""
    try:
        node = parm.node()
        return bool(node.isInsideLockedHDA()) and not bool(node.isEditableInsideLockedHDA())
    except Exception:
        return False


def _menu_items(parm: Any) -> tuple[list[str], list[str]] | None:
    try:
        return _read_menu(parm)
    except Exception:
        return None


def _read_menu(parm: Any) -> tuple[list[str], list[str]]:
    """``(tokens, labels)`` of ``parm``'s menu: a VOP asset's signatures from its
    definition (:func:`vop_signatures`), else what Houdini evaluates. Raises when the
    menu cannot be read."""
    signatures = vop_signatures(parm)
    if signatures is not None:
        return signatures
    return list(parm.menuItems()), [menu_label(label) for label in parm.menuLabels()]


_SIGNATURE_LINE = re.compile(r'^\s*signature\s+"((?:[^"\\]|\\.)*)"\s+(\S+)', re.MULTILINE)
_SIGNATURES: dict[tuple[str, str, float], tuple[list[str], list[str]] | None] = {}


def vop_signatures(parm: Any) -> tuple[list[str], list[str]] | None:
    """``(tokens, labels)`` of an asset's ``signature`` parm as its definition's
    DialogScript lists them (``signature "Color (FA)" color3FA { ... }``), or None for any
    other parm. The menu Houdini evaluates on a MaterialX VOP holds only ``default`` and
    the signatures already chosen on the node (review 26 P2 friction 7), and Houdini sets
    any text silently, so the definition is the list to check a value against (D68)."""
    try:
        if parm.name() != "signature":
            return None
        node_type = parm.node().type()
    except Exception:
        return None
    return type_signatures(node_type)


def type_signatures(node_type: Any) -> tuple[list[str], list[str]] | None:
    """:func:`vop_signatures` for a node type: what ``inspect {what: "type"}`` lists for the
    ``signature`` menu, so the reference and the check of a value agree. None when the
    type has no asset definition or its DialogScript lists no signature."""
    try:
        definition = node_type.definition()
        if definition is None:
            return None
        key = (
            node_type.nameWithCategory(),
            str(definition.libraryFilePath()),
            float(definition.modificationTime()),
        )
    except Exception:
        return None
    if key not in _SIGNATURES:
        found: tuple[list[str], list[str]] | None = None
        with contextlib.suppress(Exception):
            text = definition.sections()["DialogScript"].contents()
            pairs = _SIGNATURE_LINE.findall(text)
            if pairs:
                found = [token for _label, token in pairs], [label for label, _ in pairs]
        _SIGNATURES[key] = found
    return _SIGNATURES[key]


def _menu_dict(parm: Any, token: Any) -> dict[str, Any] | None:
    """``{token, label, index?, items, item_count, truncated?}``. A dynamic menu (a menu
    script, or one Houdini builds from the input geometry; review 14 papercut 10) is
    evaluated on this parm and adds ``dynamic: true``; when it is still empty after a
    cook of the node, or cannot be evaluated, ``items`` is ``[]`` with a ``note``."""
    try:
        dynamic = menu_is_dynamic(parm.parmTemplate())
    except Exception:
        dynamic = False
    read = _menu_items(parm)
    if dynamic and not (read and read[0]):
        import hou

        node = parm.node()
        if isinstance(node, hou.SopNode):  # a group or attribute menu reads the cooked input
            with contextlib.suppress(Exception):
                node.cook()
            read = _menu_items(parm) or read
    if read is None and not dynamic:
        return None
    items, labels = read or ([], [])
    out: dict[str, Any] = {"token": token, "label": None}
    if token in items:
        index = items.index(token)
        out["index"] = index
        out["label"] = labels[index] if index < len(labels) else None
    out["items"] = [
        {"token": t, "label": labels[i] if i < len(labels) else t}
        for i, t in enumerate(items[:MENU_ITEMS_LIMIT])
    ]
    out["item_count"] = len(items)
    if len(items) > MENU_ITEMS_LIMIT:
        out["truncated"] = True
    if dynamic:
        out["dynamic"] = True
        if not items:
            out["note"] = dynamic_menu_note()
    return out


def _multiparm_dict(parm: Any) -> dict[str, Any] | None:
    try:
        if not parm.isMultiParmParent():
            return None
        count = int(parm.evalAsInt())
        instances = parm.multiParmInstances()
        per = max(1, int(parm.multiParmInstancesPerItem()))
        start = int(parm.multiParmStartOffset())
    except Exception:
        return None
    groups: list[list[str]] = []
    for index in range(min(count, MULTIPARM_INSTANCES_LIMIT)):
        names: list[str] = []
        for inst in instances[index * per : (index + 1) * per]:
            name = inst.tuple().name()
            if name not in names:
                names.append(name)
        groups.append(names)
    out: dict[str, Any] = {"count": count, "start_offset": start, "instances": groups}
    if count > MULTIPARM_INSTANCES_LIMIT:
        out["truncated"] = True
    return out


def raw_equals(raw: Any, value: Any) -> bool:
    """Whether ``raw`` says nothing ``value`` does not: equal, or a plain number written
    as text (``rawValue()`` of a numeric parm is ``"1.8"`` for ``1.8``; review 13 and 16).
    Tuples compare per component."""
    if raw == value:
        return True
    if isinstance(raw, list | tuple) and isinstance(value, list | tuple):
        return len(raw) == len(value) and all(map(raw_equals, raw, value))
    if isinstance(raw, str) and _is_number(value):
        text = raw.strip()
        if text in (str(value), f"{value:g}", repr(value)):
            return True
        try:
            number = float(text)
        except ValueError:
            return False
        return abs(number - value) <= 1e-11 * max(1.0, abs(value))
    return False


def _value_and_raw(out: dict[str, Any], value: Any, raw: Any, full_strings: bool) -> None:
    """``value``, then ``raw`` only when it differs (unexpanded text, an expression's
    source); strings over 200 characters become ``{elided, head}`` unless
    ``full_strings`` (review 12 papercut 1: a 5 KB snippet was echoed twice)."""
    shape = (lambda v: v) if full_strings else elide_string
    out["value"] = shape(value)
    if raw is not None and not raw_equals(raw, value):
        out["raw"] = shape(raw)


def _describe_parm(
    parm: Any,
    *,
    frame: float | None,
    include: frozenset[str] | None,
    full_strings: bool = False,
) -> dict[str, Any]:
    """Compact summary (``include is None``) or the full ``parm_get`` shape."""
    template = parm.parmTemplate()
    kind = _kind(template)
    menu_mode = _menu_mode(template, kind, parm)
    keys = _key_info(parm)
    value = _eval(parm, kind, menu_mode, frame)
    locked = _parm_locked(parm)
    full = include is not None
    out: dict[str, Any] = {}
    if full:
        out["path"] = parm.path()
        out["name"] = parm.name()
        out["kind"] = "parm"
        out["tuple"] = parm.tuple().name()
        out["type"] = kind
    else:
        out["name"] = parm.name()
    _value_and_raw(out, value, _raw(parm, kind), full_strings)
    if "expression" in keys:
        out["expression"] = keys["expression"]
        out["language"] = keys["language"]
    if keys.get("keyed"):
        out["keyed"] = True
    token = _int_menu_token(parm, value) if kind == "int" and menu_mode else value
    if menu_mode == "strict":
        out["menu_token"] = token
    try:
        out["is_default"] = bool(parm.isAtDefault())
    except Exception:
        out["is_default"] = False
    if full:
        out["locked"] = locked
        out["hda_locked"] = _hda_locked(parm)
        if "keys" in include:
            out["keyframes"] = (
                {"count": keys["count"], "first": keys["first"], "last": keys["last"]}
                if keys
                else {"count": 0, "first": None, "last": None}
            )
        if "menu" in include and menu_mode is not None:
            menu = _menu_dict(parm, token)
            if menu is not None:
                out["menu"] = menu
        if "template" in include:
            out["template"] = _template_dict(template, kind, parm)
        if "ramp" in include and kind == "ramp" and isinstance(value, dict):
            # value already is the ramp: say it once (review 18 papercut 10).
            out["ramp"] = {"count": len(value["keys"])}
        if "multiparm" in include:
            multiparm = _multiparm_dict(parm)
            if multiparm is not None:
                out["multiparm"] = multiparm
    elif locked:
        out["locked"] = True
    return out


def _describe_tuple(
    ptuple: Any,
    *,
    frame: float | None,
    include: frozenset[str] | None,
    full_strings: bool = False,
) -> dict[str, Any]:
    template = ptuple.parmTemplate()
    kind = _kind(template)
    menu_mode = _menu_mode(template, kind)
    parms = list(ptuple)
    full = include is not None
    out: dict[str, Any] = {}
    if full:
        out["path"] = _target_path(ptuple)
        out["name"] = ptuple.name()
        out["kind"] = "tuple"
        out["tuple"] = ptuple.name()
        out["component_names"] = [p.name() for p in parms]
        out["type"] = kind
    else:
        out["name"] = ptuple.name()
    _value_and_raw(
        out,
        [_eval(p, kind, menu_mode, frame) for p in parms],
        [_raw(p, kind) for p in parms],
        full_strings,
    )
    expressions: dict[str, Any] = {}
    keyed: list[str] = []
    key_infos: dict[str, Any] = {}
    for parm in parms:
        info = _key_info(parm)
        if not info:
            continue
        key_infos[parm.name()] = info
        if "expression" in info:
            expressions[parm.name()] = {
                "expression": info["expression"],
                "language": info["language"],
            }
        if info.get("keyed"):
            keyed.append(parm.name())
    if expressions:
        out["expressions"] = expressions
    if keyed:
        out["keyed"] = keyed
    try:
        out["is_default"] = bool(ptuple.isAtDefault())
    except Exception:
        out["is_default"] = False
    locked = any(_parm_locked(p) for p in parms)
    if full:
        out["locked"] = locked
        out["hda_locked"] = _hda_locked(parms[0])
        if "keys" in include:
            out["keyframes"] = {
                name: {"count": i["count"], "first": i["first"], "last": i["last"]}
                for name, i in key_infos.items()
            }
        if "template" in include:
            out["template"] = _template_dict(template, kind, None)
    elif locked:
        out["locked"] = True
    return out


def summarize_parm(
    parm_or_tuple: Any, *, frame: float | None = None, full_strings: bool = False
) -> dict[str, Any]:
    """Compact ``{name, value, raw?, expression?, language?, keyed?, locked?, menu_token?,
    is_default}`` for a ``hou.Parm`` or ``hou.ParmTuple``.

    A tuple gives lists for ``value``/``raw``, ``expressions: {component: {expression,
    language}}`` and ``keyed: [component names]``. ``raw`` is left out when it equals
    ``value``; strings over 200 characters are ``{elided, head}`` unless
    ``full_strings`` (``inspect what: node``, 2.1).
    """
    target = _normalize(parm_or_tuple)
    if _is_tuple(target):
        return _describe_tuple(target, frame=frame, include=None, full_strings=full_strings)
    return _describe_parm(target, frame=frame, include=None, full_strings=full_strings)


# -- resolving --------------------------------------------------------------------


def _candidates(node: Any, name: str) -> list[str]:
    names: list[str] = []
    label_hits: list[str] = []
    lowered = name.lower()
    try:
        tuples = node.parmTuples()
    except Exception:
        tuples = ()
    for ptuple in tuples:
        tname = ptuple.name()
        names.append(tname)
        if len(ptuple) > 1:
            names.extend(p.name() for p in ptuple)
        try:
            label = ptuple.description().lower()
        except Exception:
            label = ""
        if label and (label == lowered or (len(lowered) >= 3 and lowered in label.split())):
            label_hits.append(tname)
    prefix = [n for n in names if n.lower().startswith(lowered) and n != name] if lowered else []
    close = difflib.get_close_matches(name, names, n=CANDIDATES_LIMIT, cutoff=0.6)
    ordered: list[str] = []
    for candidate in [*label_hits, *close, *prefix]:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered[:CANDIDATES_LIMIT]


def parm_not_found(node: Any, name: str) -> ToolError:
    candidates = _candidates(node, name)
    if candidates:
        first = candidates[0]
        try:
            first_tuple = node.parmTuple(first)
        except Exception:
            first_tuple = None
        if first_tuple is not None and len(first_tuple) > 1:
            comps = "/".join(p.name() for p in first_tuple)
            hint = (
                f"Did you mean {first}? It is a tuple: use {node.path()}/{first} with a list "
                f"of {len(first_tuple)} values, or a component ({comps}) with a scalar."
            )
        else:
            hint = f"Did you mean {first}?"
    else:
        hint = (
            f"{hint_tool('node_info', paths=[node.path()], include=['parms'])} lists the "
            "node's parm names."
        )
    with contextlib.suppress(Exception):
        if node.type().nameComponents()[2] in CONTROL_NODE_TYPES:
            hint = f"{hint} {spare_parms_hint()}"
    return ToolError(
        "parm_not_found",
        f"No parm or parm tuple '{name}' on {node.path()}.",
        hint=hint,
        candidates=candidates,
    )


def resolve_name(node: Any, name: str) -> Any:
    """``node.parm(name)`` then ``node.parmTuple(name)``, then on a LOP the parm a USD
    attribute name encodes to (``inputs:intensity``); ``parm_not_found`` otherwise."""
    if not isinstance(name, str) or not name:
        raise ToolError("invalid_argument", "Parm names must be non-empty strings.")
    parm = node.parm(name)
    if parm is not None:
        return parm
    ptuple = node.parmTuple(name)
    if ptuple is not None:
        return _normalize(ptuple)
    from .usd import usd_parm_name

    alias = usd_parm_name(node, name)
    if alias is not None and (node.parm(alias) or node.parmTuple(alias)) is not None:
        return resolve_name(node, alias)
    raise parm_not_found(node, name)


def resolve_path(path: Any) -> tuple[Any, Any]:
    """Resolve an absolute parm/tuple path to ``(node, hou.Parm | hou.ParmTuple)``."""

    if not isinstance(path, str) or not path.strip():
        raise ToolError("invalid_argument", "Parm paths must be non-empty strings.")
    text = path.strip().rstrip("/")
    if not text.startswith("/") or text.count("/") < 2:
        raise ToolError(
            "invalid_argument",
            f"{path!r} is not an absolute parm path.",
            hint="Use <node path>/<parm name>, e.g. /obj/geo1/box1/size or /obj/geo1/box1/sizex.",
        )
    node_path, _, name = text.rpartition("/")
    try:
        node = require_node(node_path)
    except ToolError as exc:
        if exc.code == "node_not_found":
            exc.hint = (
                f"{exc.hint} Parm paths are <node path>/<parm name>, e.g. "
                f"/obj/geo1/box1/sizex; {hint_tool('node_find', root=BARE, type=BARE)} "
                "locates the node."
            )
        raise
    return node, resolve_name(node, name)


# -- writing ----------------------------------------------------------------------


def _key_signature(parm: Any) -> set[tuple[Any, ...]]:
    sig: set[tuple[Any, ...]] = set()
    try:
        keys = parm.keyframes()
    except Exception:
        return sig
    for key in keys:
        try:
            value = key.value() if key.isValueSet() else None
        except Exception:
            value = None
        try:
            expression = key.expression()
        except Exception:
            expression = None
        sig.add((round(key.frame(), 6), value, expression))
    return sig


def _pure_expression(parm: Any) -> bool:
    """True when the parm is driven by one expression (not keyframed animation)."""
    info = _key_info(parm)
    return bool(info) and "expression" in info and info["count"] == 1


def _invalid(
    parm: Any, kind: str, message: str, hint: str | None = None, **extra: Any
) -> ToolError:
    detail: dict[str, Any] = {"type": kind}
    with contextlib.suppress(Exception):
        detail.update(_range(parm.parmTemplate(), kind))
    detail.update(extra.pop("detail", {}) or {})
    if hint is None and "min" in detail:
        hint = _range_text(detail)
    return ToolError("invalid_value", message, hint=hint, detail=detail, **extra)


def _range_text(rng: dict[str, Any]) -> str:
    low = "[" if rng.get("min_strict") else "(soft "
    high = "]" if rng.get("max_strict") else " soft)"
    return f"Template range {low}{rng.get('min')}, {rng.get('max')}{high}; only strict bounds are enforced."


def _check_range(parm: Any, kind: str, value: float) -> None:
    rng = _range(parm.parmTemplate(), kind)
    if not rng:
        return
    if rng["min_strict"] and value < rng["min"]:
        raise _invalid(
            parm,
            kind,
            f"{value} is below the minimum {rng['min']} of {parm.path()}.",
            hint=f"{parm.name()} accepts values >= {rng['min']}"
            + (f" and <= {rng['max']}." if rng["max_strict"] else "."),
        )
    if rng["max_strict"] and value > rng["max"]:
        raise _invalid(
            parm,
            kind,
            f"{value} is above the maximum {rng['max']} of {parm.path()}.",
            hint=f"{parm.name()} accepts values <= {rng['max']}"
            + (f" and >= {rng['min']}." if rng["min_strict"] else "."),
        )


MENU_ALL_ITEMS = 50
"""A menu with at most this many items gives every token as ``candidates`` (2.1, D72:
``subnetconnector``'s ``parmtype`` has 44, and the 20 listed missed the one meant)."""
MENU_CANDIDATES = 20
"""Tokens a larger menu gives, the nearest to the value first."""
MENU_HINT_ITEMS = 10
"""``token (label)`` pairs the hint shows, the nearest first."""
_WORDS = re.compile(r"[^a-z0-9]+")


def _similarity(value: str, text: str) -> float:
    """How close ``text`` (a menu token or label) is to ``value``, 0..1: equal, a whole
    word of it, a word's prefix, a substring, then the edit-distance ratio."""
    text = text.lower().strip()
    if not text or not value:
        return 0.0
    if text == value:
        return 1.0
    words = [w for w in _WORDS.split(text) if w]
    if value in words:
        return 0.95
    if any(w.startswith(value) for w in words):
        return 0.9
    if value in text:
        return 0.85
    ratio = 0.8 * difflib.SequenceMatcher(None, value, text).ratio()
    if len(text) >= 3 and text in value:  # "poly" in "polymsh": by how much it covers
        return max(ratio, 0.6 + 0.2 * len(text) / len(value))
    return ratio


def rank_menu(value: Any, items: list[str], labels: list[str]) -> list[int]:
    """Indices of ``items``, the nearest to ``value`` by token or label first (2.1, D72):
    ``volume`` puts ``atmosphere`` (``Volume (shader)``) first. Ties keep menu order. No
    ``hou``."""
    wanted = str(value).lower().strip()

    def score(i: int) -> float:
        label = labels[i] if i < len(labels) else ""
        return max(_similarity(wanted, items[i]), _similarity(wanted, label))

    return sorted(range(len(items)), key=lambda i: (-score(i), i))


def menu_choices(value: Any, items: list[str], labels: list[str]) -> tuple[list[str], str]:
    """``(candidates, shown)`` for a value a menu does not hold: every token when the menu
    has at most :data:`MENU_ALL_ITEMS`, else the :data:`MENU_CANDIDATES` nearest, ranked by
    :func:`rank_menu` either way; ``shown`` the nearest ``token (label)`` pairs for the
    hint, with the item count when it shows fewer. No ``hou``."""
    order = rank_menu(value, items, labels) if isinstance(value, str) else list(range(len(items)))
    keep = order if len(items) <= MENU_ALL_ITEMS else order[:MENU_CANDIDATES]
    pairs = [
        f"{items[i]} ({labels[i]})" if i < len(labels) and labels[i] != items[i] else items[i]
        for i in keep[:MENU_HINT_ITEMS]
    ]
    shown = ", ".join(pairs)
    if len(items) > len(pairs):
        nearest = "nearest first" if isinstance(value, str) else "in menu order"
        listed = "all" if len(keep) == len(items) else f"the {len(keep)} nearest"
        shown += f" ({nearest}; {len(items)} items, candidates lists {listed})"
    return [items[i] for i in keep], shown


def _resolve_menu(parm: Any, kind: str, value: Any, notes: list[str]) -> tuple[str, int]:
    """Return ``(token, index)`` for a token, label or index on a strict menu."""
    try:
        items, labels = _read_menu(parm)
    except Exception as exc:
        raise _invalid(parm, kind, f"Cannot read the menu of {parm.path()}.") from exc
    candidates, shown = menu_choices(value, items, labels)
    if isinstance(value, str):
        if value in items:
            return value, items.index(value)
        for matcher in (
            lambda s: s in labels and labels.index(s),
            lambda s: next((i for i, lab in enumerate(labels) if lab.lower() == s.lower()), False),
            lambda s: next((i for i, tok in enumerate(items) if tok.lower() == s.lower()), False),
        ):
            index = matcher(value)
            if index is not False and index is not None and index < len(items):
                token = items[index]
                notes.append(f"'{value}' matched menu label/token '{token}'; set token '{token}'.")
                return token, index
        raise _invalid(
            parm,
            kind,
            f"'{value}' is not a menu item of {parm.path()}.",
            hint=f"Use a token or label: {shown}",
            candidates=candidates,
        )
    if _is_number(value) and float(value).is_integer():
        index = int(value)
        if 0 <= index < len(items):
            notes.append(f"Menu index {index} is token '{items[index]}'.")
            return items[index], index
        raise _invalid(
            parm,
            kind,
            f"Menu index {index} is out of range for {parm.path()} ({len(items)} items).",
            hint=f"Use a token or label: {shown}",
            candidates=candidates,
        )
    raise _invalid(
        parm,
        kind,
        f"{parm.path()} is a menu; pass a token, label or index.",
        hint=f"Items: {shown}",
    )


def _coerce(parm: Any, value: Any, notes: list[str], *, for_key: bool = False) -> Any:
    """Convert a JSON value to what ``parm.set()`` (or a keyframe) takes, validating it."""
    template = parm.parmTemplate()
    kind = _kind(template)
    path = parm.path()
    if kind == "button":
        raise _invalid(parm, kind, f"{path} is a button.", hint="Use press: true to press it.")
    if kind == "ramp":
        raise _invalid(
            parm,
            kind,
            f"{path} is a ramp.",
            hint="Use ramp: {basis, keys, values}, or multiparm_count for the key count.",
        )
    if kind in ("folder", "label", "data"):
        raise _invalid(parm, kind, f"{path} is a {kind} parm and cannot be set to a value.")
    if isinstance(value, list | tuple | dict):
        raise _invalid(
            parm,
            kind,
            f"{path} is a single parm; got a {type(value).__name__}.",
            hint="Pass a scalar, or use the tuple path to set every component with a list.",
        )
    menu_mode = _menu_mode(template, kind, parm)
    if menu_mode == "strict":
        token, index = _resolve_menu(parm, kind, value, notes)
        if for_key and kind == "string":
            raise _invalid(
                parm, kind, f"{path} is a string menu; string parms are not keyed by value."
            )
        if for_key or kind == "int":
            return index
        return token
    if kind == "string":
        if isinstance(value, bool):
            raise _invalid(parm, kind, f"{path} is a string parm; got a boolean.")
        if for_key:
            raise _invalid(
                parm,
                kind,
                f"{path} is a string parm; string parms are not keyed by value.",
                hint="Use expression (optionally with animation: key), or animation: replace.",
            )
        return value if isinstance(value, str) else str(value)
    if kind == "toggle":
        if isinstance(value, bool):
            return int(value)
        if _is_number(value) and value in (0, 1):
            return int(value)
        raise _invalid(parm, kind, f"{path} is a toggle; pass true or false.")
    if kind in ("int", "float", "multiparm"):
        if not _is_number(value):
            hint = expression_hint() if isinstance(value, str) else None
            raise _invalid(parm, kind, f"{path} is a {kind} parm; got {value!r}.", hint=hint)
        if not math.isfinite(value):
            raise _invalid(parm, kind, f"{path} cannot be set to {value}.")
        if kind in ("int", "multiparm"):
            if not float(value).is_integer():
                raise _invalid(parm, kind, f"{path} is an integer parm; got {value}.")
            value = int(value)
            if kind == "multiparm" and value < 0:
                raise _invalid(parm, kind, f"{path} is a multiparm count; got {value}.")
        else:
            value = float(value)
        _check_range(parm, kind, value)
        return value
    raise _invalid(parm, kind, f"{path} ({kind}) cannot be set by value.")


def _add_key(
    parm: Any,
    frame: float,
    *,
    value: Any = None,
    expression: str | None = None,
    language: str = "hscript",
) -> None:
    import hou

    kind = _kind(parm.parmTemplate())
    key = hou.StringKeyframe() if kind == "string" else hou.Keyframe()
    key.setFrame(frame)
    if expression is not None:
        key.setExpression(expression, _hou_language(language))
    else:
        key.setValue(float(value))
    parm.setKeyframe(key)


def _note_override(parm: Any, wanted: Any, frame: float | None, notes: list[str]) -> None:
    """Report when an animation/expression keeps the parm from showing ``wanted``."""
    if not _is_number(wanted):
        return
    try:
        actual = parm.eval() if frame is None else parm.evalAtFrame(frame)
    except Exception:
        return
    if _is_number(actual) and not math.isclose(
        float(actual), float(wanted), rel_tol=1e-6, abs_tol=1e-9
    ):
        notes.append(
            f"{parm.name()} evaluates to {actual} at frame {frame if frame is not None else 'current'}, "
            f"not {wanted}: its existing animation/expression still drives it. "
            "Use animation: replace to make the value stick."
        )


def _delete_keys(parm: Any) -> bool:
    try:
        keys = parm.keyframes()
    except Exception:
        return False
    if keys:
        parm.deleteAllKeyframes()
        return True
    return False


def _require_single(target: Any, field: str, path: str) -> Any:
    if _is_tuple(target):
        comps = "/".join(p.name() for p in target)
        raise ToolError(
            "invalid_argument",
            f"{field} takes a single parm; {path} is a tuple ({comps}).",
            hint=f"Use a component path such as {target.node().path()}/{target[0].name()}.",
        )
    return target


def _ramp_from(parm: Any, spec: Any) -> Any:
    import hou

    path = parm.path()
    if not isinstance(spec, dict):
        raise ToolError("invalid_argument", "ramp must be an object {basis, keys, values}.")
    keys = spec.get("keys")
    values = spec.get("values")
    if not isinstance(keys, list) or not isinstance(values, list) or not keys:
        raise ToolError("invalid_argument", "ramp needs non-empty 'keys' and 'values' lists.")
    if len(keys) != len(values):
        raise _invalid(parm, "ramp", f"ramp has {len(keys)} keys and {len(values)} values.")
    if not all(_is_number(k) for k in keys):
        raise _invalid(parm, "ramp", "ramp keys must be numbers (positions 0..1).")
    basis = spec.get("basis", "linear")
    bases = basis if isinstance(basis, list) else [basis] * len(keys)
    if len(bases) != len(keys):
        raise _invalid(parm, "ramp", f"ramp has {len(keys)} keys and {len(bases)} bases.")
    hou_bases = []
    for name in bases:
        attr = _RAMP_BASIS_ALIASES.get(str(name).lower()) if isinstance(name, str) else None
        if attr is None:
            raise _invalid(
                parm,
                "ramp",
                f"Unknown ramp basis {name!r}.",
                hint="Bases: " + ", ".join(RAMP_BASES),
                candidates=list(RAMP_BASES),
            )
        hou_bases.append(getattr(hou.rampBasis, attr))
    try:
        is_color = parm.parmTemplate().parmType() == hou.rampParmType.Color
    except Exception:
        is_color = False
    if is_color:
        if not all(
            isinstance(v, list) and len(v) == 3 and all(_is_number(c) for c in v) for v in values
        ):
            raise _invalid(parm, "ramp", f"{path} is a color ramp; values must be [r, g, b] lists.")
        hou_values = [tuple(float(c) for c in v) for v in values]
    else:
        if not all(_is_number(v) for v in values):
            raise _invalid(parm, "ramp", f"{path} is a float ramp; values must be numbers.")
        hou_values = [float(v) for v in values]
    return hou.Ramp(tuple(hou_bases), tuple(float(k) for k in keys), tuple(hou_values))


def _resolve_ref(node: Any, ref: Any) -> Any:
    import hou

    if not isinstance(ref, str) or not ref.strip():
        raise ToolError("invalid_argument", "channel_ref must be a parm path.")
    ref = ref.strip()
    if ref.startswith("/"):
        target = hou.parm(ref) or hou.parmTuple(ref)
        if target is None:
            # Normalises a trailing slash; raises node_not_found / parm_not_found otherwise.
            target = resolve_path(ref)[1]
    else:
        target = node.parm(ref) or node.parmTuple(ref)
        if target is None:
            raise ToolError(
                "parm_not_found",
                f"channel_ref {ref!r} does not resolve from {node.path()}.",
                hint="Pass an absolute parm path such as /obj/geo1/box1/sizex.",
            )
    return _normalize(target)


def has_callback(parm: Any) -> bool:
    """Whether the parm runs a callback script when the user changes it in the UI."""
    try:
        return bool(parm.parmTemplate().scriptCallback().strip())
    except Exception:
        return False


def skips_callback(parm: Any) -> bool:
    """Whether a plain set of ``parm`` leaves a callback unrun that clicking it in Houdini
    would run: a toggle or a menu with a callback script (review 20 N2)."""
    if not has_callback(parm):
        return False
    template = parm.parmTemplate()
    kind = _kind(template)
    return kind == "toggle" or bool(_menu_mode(template, kind))


CALLBACK_NOTE = (
    "{name} has a callback script that a plain set does not run (clicking the parm in "
    "Houdini would); pass press: true with the value to run it."
)
CREATE_CALLBACK_NOTE = (
    "{name} has a callback script that a plain set does not run (clicking the parm in "
    'Houdini would); pass parms {{"{name}": {{"value": ..., "press": true}}}} to run it.'
)
"""The same note on ``node_create``, whose parms spell the item without ``path`` (review 20
N2)."""
NETWORK_CALLBACK_NOTE = (
    "{path} has a callback script that a build does not run (clicking the parm in "
    'Houdini would); pass press {{"{key}": ["{name}"]}} to run it after the build.'
)
"""The same note on ``network_build``, whose ``press`` maps a node in data to parm names
(1.4)."""
NO_CALLBACK = (
    "{path} is a {kind} parm with no callback script; press clicks a button, or runs the "
    "callback of a parm that has one (with or without a value)."
)


def _press(node: Any, parm: Any) -> dict[str, Any] | None:
    """Press ``parm`` (run its callback), except in an ``edit`` check (a dry run, or the
    ops after a failing one: BIBLE D56), where nothing that compensation cannot take back
    may run; the checks before the press (a callback exists) have passed by then."""
    from ..tx import checking

    if checking():
        return None
    from .visual import press_button  # lazy: visual imports hou-heavy helpers

    return press_button(node, parm)


def _apply(
    node: Any,
    target: Any,
    item: dict[str, Any],
    *,
    frame: float | None,
    callback_note: str = CALLBACK_NOTE,
    ctx: Any = None,
) -> dict[str, Any]:
    """Apply one ``parm_set`` item. Returns the item result (without node problems).
    ``callback_note`` is the note for a plain set of a callback menu or toggle; ``ctx``
    (the host context) checks a ``value_file`` against ``approved_roots``."""
    import hou

    from .events import note_explicit  # lazy: events imports nodes, which imports this

    path = _target_path(target)
    note_explicit(target)  # its events are the agent's; Houdini's own writes are not
    # press next to a value sets the value, then runs the parm's callback (review 17 P1-4).
    press_after = item.get("press") is True and item.get("value") is not None
    present = [
        f
        for f in VALUE_FIELDS
        if (item.get(f) is True if f in _FLAG_FIELDS else item.get(f) is not None)
        and not (press_after and f == "press")
    ]
    if len(present) != 1:
        got = ", ".join(present) if present else "none"
        raise ToolError(
            "invalid_argument",
            f"Each item takes exactly one of {', '.join(VALUE_FIELDS)}; got {got} for {path}.",
        )
    field = present[0]
    animation = item.get("animation") or "replace"
    if animation not in ANIMATION_MODES:
        raise ToolError(
            "invalid_argument", f"animation must be one of {', '.join(ANIMATION_MODES)}."
        )
    language = item.get("language") or "hscript"
    if language not in LANGUAGES:
        raise ToolError("invalid_argument", "language must be hscript or python.")
    parms = _components(target)
    notes: list[str] = []
    before = [_key_signature(p) for p in parms]
    key_frame = frame if frame is not None else hou.frame()
    count_keys_as_written = True
    pressed: dict[str, Any] | None = None
    text_from: dict[str, Any] = {}
    if press_after:
        single = _require_single(target, "press", path)
        if not has_callback(single):
            raise _invalid(
                single,
                _kind(single.parmTemplate()),
                NO_CALLBACK.format(path=path, kind=_kind(single.parmTemplate())),
            )
    try:
        if field == "value":
            value = item["value"]
            if _is_tuple(target):
                if not isinstance(value, list):
                    raise _invalid(
                        parms[0],
                        _kind(target.parmTemplate()),
                        f"{path} is a tuple of {len(parms)}; got a scalar.",
                        hint=f"Pass a list of {len(parms)} values, or set one component "
                        f"({'/'.join(p.name() for p in parms)}).",
                    )
                if len(value) != len(parms):
                    raise _invalid(
                        parms[0],
                        _kind(target.parmTemplate()),
                        f"{path} has {len(parms)} components; got {len(value)} values.",
                        hint=f"Components: {', '.join(p.name() for p in parms)}.",
                    )
                values = value
            else:
                values = [value]
            converted = [
                _coerce(p, v, notes, for_key=animation == "key")
                for p, v in zip(parms, values, strict=True)
            ]
            for parm, raw_value, new in zip(parms, values, converted, strict=True):
                if animation != "key" and _parm_locked(parm) and _holds(parm, new):
                    continue  # a computed (locked) component already at the value (review 13)
                if animation == "replace":
                    _delete_keys(parm)
                    parm.set(new)
                elif animation == "key":
                    _add_key(parm, key_frame, value=new)
                    _note_override(parm, new, key_frame, notes)
                else:
                    with _at_frame(frame):
                        parm.set(new)
                    if _is_number(raw_value):
                        _note_override(parm, new, frame, notes)
            if press_after:
                pressed = _press(node, parms[0])
            elif len(parms) == 1 and skips_callback(parms[0]):
                notes.append(callback_note.format(name=parms[0].name()))
        elif field in ("patch", "value_file"):
            parm = string_target(target, field, path)
            if field == "patch":
                text, lines = apply_patch(parm.unexpandedString(), item["patch"], path)
                text_from = {"patched_lines": lines}
            else:
                source, text = read_value_file(item["value_file"], ctx)
                text_from = {"value_file": source}
            parm.set(text)
            count_keys_as_written = False
        elif field == "expression":
            parm = _require_single(target, "expression", path)
            expression = item["expression"]
            if not isinstance(expression, str) or not expression.strip():
                raise ToolError("invalid_argument", "expression must be a non-empty string.")
            kind = _kind(parm.parmTemplate())
            if kind in ("button", "ramp", "folder", "label", "multiparm", "data"):
                raise _invalid(parm, kind, f"{path} ({kind}) cannot take an expression.")
            if animation == "replace":
                _delete_keys(parm)
                parm.setExpression(expression, _hou_language(language), True)
                count_keys_as_written = False
            elif animation == "key":
                _add_key(parm, key_frame, expression=expression, language=language)
            else:
                with _at_frame(frame):
                    parm.setExpression(expression, _hou_language(language), True)
                count_keys_as_written = False
        elif field in ("keyframe", "keyframes"):
            parm = _require_single(target, field, path)
            raw_keys = item[field] if field == "keyframes" else [item[field]]
            if not isinstance(raw_keys, list) or not raw_keys:
                raise ToolError(
                    "invalid_argument", f"{field} must be a non-empty list of {{frame, value}}."
                )
            planned: list[tuple[float, Any]] = []
            for key in raw_keys:
                if not isinstance(key, dict) or "value" not in key:
                    raise ToolError("invalid_argument", "Each keyframe is {frame, value}.")
                if field == "keyframes" and key.get("frame") is None:
                    raise ToolError("invalid_argument", "Each entry of keyframes needs a frame.")
                kf = _frame_arg(key.get("frame"), "keyframe.frame")
                planned.append(
                    (
                        key_frame if kf is None else kf,
                        _coerce(parm, key["value"], notes, for_key=True),
                    )
                )
            frames = [f for f, _ in planned]
            if len(set(frames)) != len(frames):
                raise ToolError("invalid_argument", f"{field} lists the same frame twice.")
            if field == "keyframes" and animation == "replace":
                _delete_keys(parm)
            elif _pure_expression(parm) and animation == "replace":
                notes.append(
                    f"Removed the expression {parm.expression()!r} so the keyframe drives {parm.name()}."
                )
                _delete_keys(parm)
            for key_at, value in planned:
                _add_key(parm, key_at, value=value)
            for key_at, value in planned:
                _note_override(parm, value, key_at, notes)
        elif field == "channel_ref":
            source = _resolve_ref(node, item["channel_ref"])
            if _is_tuple(target) != _is_tuple(source) or (
                _is_tuple(target) and len(target) != len(source)
            ):
                raise _invalid(
                    parms[0],
                    _kind(parms[0].parmTemplate()),
                    f"Cannot reference {_target_path(source)} from {path}: tuple sizes differ.",
                    hint="Reference a parm from a parm, or a tuple from a tuple of the same size.",
                )
            sources = _components(source)
            for parm, src in zip(parms, sources, strict=True):
                if parm.path() == src.path():
                    raise _invalid(
                        parm, _kind(parm.parmTemplate()), f"{path} cannot reference itself."
                    )
            for parm, src in zip(parms, sources, strict=True):
                if animation == "replace":
                    _delete_keys(parm)
                if language == "python":
                    parm.set(src, hou.exprLanguage.Python)
                else:
                    parm.set(src)
            count_keys_as_written = False
        elif field == "ramp":
            parm = _require_single(target, "ramp", path)
            kind = _kind(parm.parmTemplate())
            if kind != "ramp":
                raise _invalid(parm, kind, f"{path} is not a ramp parm ({kind}).")
            parm.set(_ramp_from(parm, item["ramp"]))
            count_keys_as_written = False
        elif field == "multiparm_count":
            parm = _require_single(target, "multiparm_count", path)
            count = item["multiparm_count"]
            if not _is_number(count) or not float(count).is_integer() or count < 0:
                raise ToolError("invalid_argument", "multiparm_count must be an integer >= 0.")
            if not parm.isMultiParmParent():
                raise _invalid(
                    parm,
                    _kind(parm.parmTemplate()),
                    f"{path} is not a multiparm.",
                    hint="multiparm_count applies to multiparm count parms (e.g. attribcreate numattr) and ramps.",
                )
            if animation == "replace":
                _delete_keys(parm)
            parm.set(int(count))
            count_keys_as_written = False
        elif field == "revert_to_default":
            for parm in parms:
                _delete_keys(parm)
            target.revertToDefaults()
            count_keys_as_written = False
        elif field == "press":
            parm = _require_single(target, "press", path)
            kind = _kind(parm.parmTemplate())
            if kind != "button" and not has_callback(parm):
                raise _invalid(parm, kind, NO_CALLBACK.format(path=path, kind=kind))
            pressed = _press(node, parm)  # verifies a save button's files (review 17)
            count_keys_as_written = False
    except ToolError:
        raise
    except hou.PermissionError as exc:
        raise locked_error(node, target, exc) from exc
    except hou.Error as exc:  # any other Houdini refusal is about the value, not a bug
        kind = _kind(parms[0].parmTemplate())
        raise _invalid(
            parms[0],
            kind,
            f"Houdini refused {field} for {path}: {hou_message(exc)}",
            hou_exception=hou_exception_text(exc),
        ) from exc
    wrote = False
    if count_keys_as_written or (field == "expression" and animation == "key"):
        wrote = any(_key_signature(p) - b for p, b in zip(parms, before, strict=True))
    result = {"path": path, **summarize_parm(target, frame=frame)}
    if pressed is not None:
        if _kind(_components(target)[0].parmTemplate()) == "button":
            for key in ("value", "raw", "is_default"):  # a button has no value (review 17)
                result.pop(key, None)
        result.update(pressed)
    result.update(text_from)
    result["wrote_keyframe"] = wrote
    if notes:
        result["notes"] = notes
    return result


# -- long strings: patch and value_file (review 26 P1 friction 2) --------------------------


def string_target(target: Any, field: str, path: str) -> Any:
    """The single string parm ``patch`` or ``value_file`` writes, holding plain text."""
    parm = _require_single(target, field, path)
    kind = _kind(parm.parmTemplate())
    if kind != "string":
        raise _invalid(parm, kind, f"{path} is a {kind} parm; {field} writes string parms.")
    if parm.keyframes():
        raise _invalid(
            parm,
            kind,
            f"{path} has keyframes or an expression; {field} edits plain text.",
            hint="Replace it with value (animation: replace) first.",
        )
    return parm


def patch_edits(spec: Any) -> list[dict[str, Any]]:
    """``patch`` as a list of ``{find, replace, all?}``; one object is a list of one."""
    edits = [spec] if isinstance(spec, dict) else spec
    if not isinstance(edits, list) or not edits:
        raise ToolError(
            "invalid_argument",
            "patch is {find, replace} or a list of them.",
            hint="Each find must occur exactly once (all: true replaces every occurrence); "
            "edits apply in order.",
        )
    for i, edit in enumerate(edits):
        where = f"patch[{i}]" if isinstance(spec, list) else "patch"
        if not isinstance(edit, dict) or set(edit) - PATCH_KEYS or "find" not in edit:
            raise ToolError(
                "invalid_argument", f"{where} is {{find, replace, all?}}; got {edit!r:.120}."
            )
        if not isinstance(edit["find"], str) or not edit["find"]:
            raise ToolError("invalid_argument", f"{where}.find must be non-empty text.")
        if not isinstance(edit.get("replace", ""), str):
            raise ToolError("invalid_argument", f"{where}.replace must be text.")
        if not isinstance(edit.get("all", False), bool):
            raise ToolError("invalid_argument", f"{where}.all is true or false.")
    return edits


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _clip_line(line: str, limit: int = 120) -> str:
    line = line.strip()
    return line if len(line) <= limit else line[: limit - 3] + "..."


def apply_patch(text: str, spec: Any, path: str) -> tuple[str, list[int]]:
    """``text`` with every edit of ``patch`` applied in order, and the line each edit
    starts on. A ``find`` that does not occur exactly once (or at all, with ``all``) is
    ``invalid_value`` naming the nearest lines as candidates, and nothing is written."""
    edits = patch_edits(spec)
    lines: list[int] = []
    for i, edit in enumerate(edits):
        where = f"patch[{i}]" if isinstance(spec, list) else "patch"
        find, replace = edit["find"], edit.get("replace", "")
        count = text.count(find)
        if count == 1 or (count > 1 and edit.get("all")):
            lines.append(_line_of(text, text.index(find)))
            text = (
                text.replace(find, replace) if edit.get("all") else text.replace(find, replace, 1)
            )
            continue
        raise _patch_mismatch(text, find, count, where, path)
    return text, lines


def _patch_mismatch(text: str, find: str, count: int, where: str, path: str) -> ToolError:
    if count > 1:
        starts, at = [], text.find(find)
        while at >= 0 and len(starts) < 10:
            starts.append(_line_of(text, at))
            at = text.find(find, at + 1)
        return ToolError(
            "invalid_value",
            f"{where}.find occurs {count} times in {path} (lines "
            f"{', '.join(map(str, starts))}{', ...' if count > len(starts) else ''}).",
            hint="Add surrounding text so find occurs once, or pass all: true to replace "
            "every occurrence.",
            detail={"occurrences": count, "lines": starts},
        )
    rows = text.split("\n")
    first = next((ln.strip() for ln in find.split("\n") if ln.strip()), find.strip())
    stripped = [ln.strip() for ln in rows]
    close = difflib.get_close_matches(first, stripped, n=3, cutoff=0.5)
    candidates = []
    for line in close:
        number = stripped.index(line) + 1
        candidates.append(f"line {number}: {_clip_line(rows[number - 1])}")
    squash = re.compile(r"\s+")
    hint = (
        "find matches when whitespace is ignored: copy the text exactly (tabs, spaces, line ends)."
        if squash.sub(" ", find).strip() in squash.sub(" ", text)
        else "find must be the parm's current text, exactly; read it with full_strings."
    )
    return ToolError(
        "invalid_value",
        f"{where}.find does not occur in {path} ({len(text)} characters, {len(rows)} lines).",
        hint=hint,
        candidates=candidates,
    )


def read_value_file(raw: Any, ctx: Any) -> tuple[str, str]:
    """``(path, text)`` of a ``value_file``: ``$HIP`` and ``~`` expanded, checked against
    ``approved_roots``, read as UTF-8 text (universal newlines)."""
    from .hip import check_allowed
    from .hip import resolve_path as resolve_file

    path = resolve_file(raw, field="value_file")
    if ctx is not None:
        check_allowed(path, ctx)
    if not os.path.isfile(path):
        raise ToolError(
            "file_not_found",
            f"No file at {path} (value_file).",
            hint="value_file is a text file on the machine Houdini runs on; $HIP and ~ expand.",
        )
    size = os.path.getsize(path)
    if size > VALUE_FILE_MAX_BYTES:
        raise ToolError(
            "invalid_value",
            f"{path} is {size} bytes; value_file reads at most {VALUE_FILE_MAX_BYTES}.",
        )
    try:
        with open(path, encoding="utf-8") as handle:
            return path, handle.read()
    except UnicodeDecodeError as exc:
        raise ToolError(
            "invalid_value", f"{path} is not UTF-8 text ({exc.reason} at byte {exc.start})."
        ) from exc


def _snapshot(target: Any) -> Any:
    """Capture each component's keys, expression or value; returns a restore function.

    A failed item puts its own earlier components back (say, component 2 of a tuple is
    locked), and a failed batch restores every earlier item, newest first, so the error's
    ``rolled_back`` says what actually happened (the dispatcher's undo group is undone too).
    """
    saved = []
    for parm in _components(target):
        try:
            kind = _kind(parm.parmTemplate())
            keys = tuple(parm.keyframes())
            value = None
            if not keys and kind == "ramp":
                value = parm.evalAsRamp()
            elif not keys and kind == "string":
                value = parm.unexpandedString()
            elif not keys and kind not in ("button", "folder", "label", "data"):
                value = parm.eval()
        except Exception:
            continue
        saved.append((parm, keys, value))

    def restore() -> bool:
        """Put every component back; False when one could not be restored."""
        ok = True
        for parm, keys, value in saved:
            try:
                if parm.keyframes():
                    parm.deleteAllKeyframes()
                if keys:
                    parm.setKeyframes(keys)
                elif value is not None:
                    parm.set(value)
            except Exception:
                ok = False
        return ok

    return restore


def locked_error(node: Any, target: Any, exc: BaseException | None = None) -> ToolError:
    path = _target_path(target)
    hou_exc = hou_exception_text(exc) if exc is not None else None
    try:
        inside = bool(node.isInsideLockedHDA())
    except Exception:
        inside = False
    if inside:
        asset = None
        current = node.parent()
        while current is not None and current.path() != "/":
            with contextlib.suppress(Exception):
                if current.isLockedHDA():
                    asset = current.path()
            current = current.parent()
        asset = asset or "the enclosing asset"
        return ToolError(
            "locked",
            f"{path} is inside the locked HDA {asset}.",
            hint=f"Call {hint_tool('node_edit', path=asset, lock=False)} "
            "(allowEditingOfContents) to allow editing its "
            f"contents{' (or use the hda tool)' if hint_tool('hda') else ''}, then retry.",
            hou_exception=hou_exc,
        )
    locked = [p for p in _components(target) if _parm_locked(p)]
    if locked:
        first = locked[0]
        message = (
            f"{path} is locked." if first.path() == path else f"{path}: {first.name()} is locked"
        )
        with contextlib.suppress(Exception):
            message = (
                f"{message.rstrip('.')} and computed by the expression {first.expression()!r} "
                f"(now {_json_number(first.eval())})."
            )
        message = message if message.endswith(".") else message + "."
        others = [p.name() for p in _components(target) if p not in locked]
        unlock = f"hou.parm('{first.path()}').lock(False)"
        python = hint_tool("houdini_python", code=unlock)
        hint = (
            f"Set {', '.join(others)} only (a locked component that already holds the value is "
            f"skipped), or change what computes {first.name()}, such as a mode menu on the node."
            + (f" Last resort: {python}." if python else "")
            if others
            else "Unlock it in Houdini" + (f", or with {python}." if python else ".")
        )
        return ToolError("locked", message, hint=hint, hou_exception=hou_exc)
    return ToolError(
        "locked",
        f"Houdini refused to modify {path} (permission error).",
        hint="Possible causes: a locked asset, a take that does not include this parm, or permissions.",
        hou_exception=hou_exc,
    )


def _with_context(exc: ToolError, prefix: str | None, extra: dict[str, Any]) -> ToolError:
    detail = (
        exc.detail
        if isinstance(exc.detail, dict)
        else ({} if exc.detail is None else {"detail": exc.detail})
    )
    return ToolError(
        exc.code,
        f"{prefix}: {exc.message}" if prefix else exc.message,
        hint=exc.hint,
        candidates=exc.candidates,
        hou_exception=exc.hou_exception,
        detail={**detail, **extra},
    )


EXPRESSION_SPELLINGS = "{expression, language} (or the short {expr, lang})"


def _item_from_spec(name: str, spec: Any, animation: str) -> dict[str, Any]:
    if isinstance(spec, dict):
        if "expr" in spec:
            extra = set(spec) - {"expr", "lang"}
            if extra:
                raise ToolError(
                    "invalid_argument",
                    f"parms.{name}: an expression object is {EXPRESSION_SPELLINGS}; "
                    f"unexpected {sorted(extra)} next to expr.",
                    hint="Use expression with language, or expr with lang; do not mix them.",
                )
            return {
                "expression": spec["expr"],
                "language": spec.get("lang") or "hscript",
                "animation": animation,
            }
        extra = set(spec) - (ITEM_KEYS - {"path"})
        if extra:
            raise ToolError(
                "invalid_argument",
                f"parms.{name}: unexpected keys {sorted(extra)}.",
                hint=f"Pass a value, a list for a tuple, an expression as {EXPRESSION_SPELLINGS}, "
                "or one parm_set item field (value, keyframes, channel_ref, ramp, "
                "multiparm_count, ...).",
            )
        return {"animation": animation, **spec}
    return {"value": spec, "animation": animation}


def set_parm_items(
    node: Any,
    parms: dict[str, Any],
    ctx: Any,
    *,
    animation: str = "replace",
    callback_note: str = CALLBACK_NOTE,
    rollback: Any = None,
    frame: float | None = None,
) -> list[dict[str, Any]]:
    """Apply ``{parm_name: value | {expression, language} | {expr, lang}}`` to ``node`` and return per-parm results.

    Used by ``node_create`` (``items[].parms``) and ``network_build``. Same semantics as
    one ``parm_set`` item per entry; raises ToolError on the first failure. A dict value
    other than ``{expr, lang}`` (including ``{expression, language}``) is treated as a ``parm_set`` item without ``path`` (e.g.
    ``{"ramp": {...}}``, ``{"channel_ref": "/obj/..."}``). Results are the compact
    summary plus ``path`` and ``wrote_keyframe`` (no node errors: callers report those),
    with ``notes`` and, for a pressed entry, ``pressed`` and ``side_effects``, as
    ``parm_set`` returns them.

    With ``rollback`` (a ``tx.Rollback``; the ``edit`` set op on an existing node) each
    parm's keys, expression or value are snapshotted before it is set and restored when
    the call fails; ``frame`` is ``parm_set``'s.
    """
    if not isinstance(parms, dict):
        raise ToolError("invalid_argument", "parms must be an object {name: value}.")
    results: list[dict[str, Any]] = []
    for name, spec in parms.items():
        try:
            target = resolve_name(node, name)
            item = _item_from_spec(name, spec, animation)
            if rollback is not None:
                from ..tx import _checked

                rollback.add(_checked(_snapshot(target)))
            results.append(
                _apply(node, target, item, frame=frame, callback_note=callback_note, ctx=ctx)
            )
        except ToolError as exc:
            if exc.message.startswith(f"parms.{name}:"):
                raise
            where = (
                f"parms.{name}"
                if exc.message.startswith(node.path())
                else f"parms.{name} on {node.path()}"
            )
            raise _with_context(exc, where, {"parm": name, "node": node.path()}) from exc
    return results


# -- tools ------------------------------------------------------------------------


def _paths_arg(args: dict[str, Any]) -> list[str]:
    paths = args.get("paths")
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise ToolError("invalid_argument", "'paths' must be a non-empty list of parm paths.")
    return paths


def parm_get(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = _paths_arg(args)
    frame = _frame_arg(args.get("frame"))
    include = args.get("include") or []
    if not isinstance(include, list) or any(i not in INCLUDE_KEYS for i in include):
        raise ToolError(
            "invalid_argument", f"'include' entries must be among {', '.join(INCLUDE_KEYS)}."
        )
    wanted = frozenset(include)
    full_strings = arg_bool(args, "full_strings", False)
    out: list[dict[str, Any]] = []
    for path in paths:
        _node, target = resolve_path(path)
        describe = _describe_tuple if _is_tuple(target) else _describe_parm
        out.append(describe(target, frame=frame, include=wanted, full_strings=full_strings))
    result: dict[str, Any] = {"parms": out}
    if frame is not None:
        result["frame"] = frame
    return result


@tool("parm_set")
def parm_set(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    """A plan of ``set`` ops over the transaction engine (``host/tx.py``): each item is
    snapshotted before it is applied, so a failing item restores its own components and,
    without ``partial``, every earlier item (newest first)."""
    items = args.get("items")
    if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
        raise ToolError("invalid_argument", "'items' must be a non-empty list of objects.")
    frame = _frame_arg(args.get("frame"))
    partial = args.get("partial", False)
    if not isinstance(partial, bool):
        raise ToolError("invalid_argument", "'partial' must be a boolean.")
    from .. import tx  # lazy: tx imports the tool families
    from .nodes import watch_nodes

    ops = [tx.Op("set", item, opts={"frame": frame}) for item in items]
    # 1.4: only a ToolError is an item's failure; anything else ends the call as internal.
    plan = tx.Plan(ops, partial=partial, tool_errors_only=True)
    result = tx.execute(plan, ctx)
    nodes: dict[str, Any] = {}
    for res in result.done():
        nodes.setdefault(res.node.path(), res.node)
    problems = {path: cheap_cook_problems(node) for path, node in nodes.items()}
    watch_nodes(nodes.values())
    results: list[dict[str, Any]] = []
    for res in result.results:
        if res.error is not None:
            path = res.args.get("path") if isinstance(res.args, dict) else None
            results.append({"path": path, "wrote_keyframe": False, "error": res.error})
            continue
        row = res.data
        diag = problems[res.node.path()]
        row["errors"] = diag["errors"]
        row["warnings"] = diag["warnings"]
        row["cook_state"] = diag["cook_state"]
        if "hint" in diag:
            row["hint"] = diag["hint"]
        results.append(row)
    out: dict[str, Any] = {"results": results}
    if partial:
        out["failed"] = len(result.failures)
    return out


# -- hints (the spare parm engine is spare.py) -------------------------------------------


def spare_parms_hint() -> str:
    """How to add a control parm, as the call's profile names it."""
    return f"To add a control parm, use {hint_tool('node_edit', path=BARE, spare_parms=BARE)}."


def expression_hint() -> str:
    """How to pass an expression where a number was expected (``invalid_value``), as the
    call's profile names it: the ``expression`` field of a ``set`` op (review 25 papercut
    1)."""
    return (
        "For an expression pass the expression field of a set op ("
        f"{hint_tool('parm_set', path=BARE, expression=BARE)}), or {EXPRESSION_SPELLINGS} "
        "as the value in a create op's parms."
    )


"""Appended to ``parm_not_found`` on nodes that hold controls (null, subnet, geo)."""
CONTROL_NODE_TYPES = frozenset(("null", "subnet", "geo"))
