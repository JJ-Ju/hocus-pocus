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
import re
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError

from ._diag import cheap_cook_problems, require_node
from .nodes import hou_exception_text, hou_message
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
)
ITEM_KEYS = frozenset((*VALUE_FIELDS, "path", "language", "animation"))
_FLAG_FIELDS = ("revert_to_default", "press")
"""Value fields that act only when ``true``; ``false``, ``0`` or null mean "not given"."""
ANIMATION_MODES = ("replace", "key", "keep")
LANGUAGES = ("hscript", "python")
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


def _menu_mode(template: Any, kind: str) -> str | None:
    """``strict`` for ordinal menus (value must be an item), ``free`` for string
    replace/toggle menus (any text allowed), None when the parm has no menu."""
    import hou

    if kind == "menu":
        return "strict"
    if kind not in ("string", "int"):
        return None
    try:
        if not template.menuItems() and not template.itemGeneratorScript():
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


def _ramp_dict(ramp: Any) -> dict[str, Any]:
    values = [list(v) if isinstance(v, tuple | list) else _json_number(v) for v in ramp.values()]
    return {
        "basis": [str(b).rsplit(".", 1)[-1].lower() for b in ramp.basis()],
        "keys": [_json_number(k) for k in ramp.keys()],  # noqa: SIM118 (hou.Ramp)
        "values": values,
        "is_color": bool(ramp.isColor()),
    }


def _eval(parm: Any, kind: str, menu_mode: str | None, frame: float | None) -> Any:
    if kind in ("button", "folder", "label"):
        return None
    try:
        if kind == "ramp":
            return _ramp_dict(parm.eval() if frame is None else parm.evalAtFrame(frame))
        if kind in ("string", "data") or menu_mode == "strict":
            return parm.evalAsString() if frame is None else parm.evalAsStringAtFrame(frame)
        value = parm.eval() if frame is None else parm.evalAtFrame(frame)
    except Exception:
        return None
    if kind == "toggle":
        return bool(value)
    return _json_number(value)


def _raw(parm: Any, kind: str) -> Any:
    if kind == "string":
        try:
            return parm.unexpandedString()
        except Exception:  # keyframed string parms: rawValue() is the expression
            pass
    try:
        return parm.rawValue()
    except Exception:
        return None


def _parm_locked(parm: Any) -> bool:
    try:
        if parm.isLocked():
            return True
    except Exception:
        pass
    try:
        node = parm.node()
        return bool(node.isInsideLockedHDA()) and not bool(node.isEditableInsideLockedHDA())
    except Exception:
        return False


def _menu_dict(parm: Any, token: Any) -> dict[str, Any] | None:
    try:
        items = list(parm.menuItems())
        labels = list(parm.menuLabels())
    except Exception:
        return None
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


def _describe_parm(
    parm: Any, *, frame: float | None, include: frozenset[str] | None
) -> dict[str, Any]:
    """Compact summary (``include is None``) or the full ``parm_get`` shape."""
    template = parm.parmTemplate()
    kind = _kind(template)
    menu_mode = _menu_mode(template, kind)
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
    out["value"] = value
    out["raw"] = _raw(parm, kind)
    if "expression" in keys:
        out["expression"] = keys["expression"]
        out["language"] = keys["language"]
    if keys.get("keyed"):
        out["keyed"] = True
    if menu_mode == "strict":
        out["menu_token"] = value
    try:
        out["is_default"] = bool(parm.isAtDefault())
    except Exception:
        out["is_default"] = False
    if full:
        out["locked"] = locked
        if "keys" in include:
            out["keyframes"] = (
                {"count": keys["count"], "first": keys["first"], "last": keys["last"]}
                if keys
                else {"count": 0, "first": None, "last": None}
            )
        if "menu" in include and menu_mode is not None:
            menu = _menu_dict(parm, value)
            if menu is not None:
                out["menu"] = menu
        if "template" in include:
            out["template"] = _template_dict(template, kind, parm)
        if "ramp" in include and kind == "ramp" and isinstance(value, dict):
            out["ramp"] = {**value, "count": len(value["keys"])}
        if "multiparm" in include:
            multiparm = _multiparm_dict(parm)
            if multiparm is not None:
                out["multiparm"] = multiparm
    elif locked:
        out["locked"] = True
    return out


def _describe_tuple(
    ptuple: Any, *, frame: float | None, include: frozenset[str] | None
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
    out["value"] = [_eval(p, kind, menu_mode, frame) for p in parms]
    out["raw"] = [_raw(p, kind) for p in parms]
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
    parm_or_tuple: Any, *, frame: float | None = None, detail: str = "compact"
) -> dict[str, Any]:
    """Compact ``{name, value, raw, expression?, language?, keyed?, locked?, menu_token?,
    is_default}`` for a ``hou.Parm`` or ``hou.ParmTuple``.

    A tuple gives lists for ``value``/``raw``, ``expressions: {component: {expression,
    language}}`` and ``keyed: [component names]``. ``detail="full"`` returns the
    ``parm_get`` shape with every include section.
    """
    if detail not in ("compact", "full"):
        raise ValueError(f"detail must be 'compact' or 'full', not {detail!r}")
    include = frozenset(INCLUDE_KEYS) if detail == "full" else None
    target = _normalize(parm_or_tuple)
    if _is_tuple(target):
        return _describe_tuple(target, frame=frame, include=include)
    return _describe_parm(target, frame=frame, include=include)


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
        hint = "List the node's parm names with node_info (include_defaults: true)."
    return ToolError(
        "parm_not_found",
        f"No parm or parm tuple '{name}' on {node.path()}.",
        hint=hint,
        candidates=candidates,
    )


def resolve_name(node: Any, name: str) -> Any:
    """``node.parm(name)`` then ``node.parmTuple(name)``; ``parm_not_found`` otherwise."""
    if not isinstance(name, str) or not name:
        raise ToolError("invalid_argument", "Parm names must be non-empty strings.")
    parm = node.parm(name)
    if parm is not None:
        return parm
    ptuple = node.parmTuple(name)
    if ptuple is not None:
        return _normalize(ptuple)
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
                "/obj/geo1/box1/sizex; node_find locates the node."
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


def _resolve_menu(parm: Any, kind: str, value: Any, notes: list[str]) -> tuple[str, int]:
    """Return ``(token, index)`` for a token, label or index on a strict menu."""
    try:
        items = list(parm.menuItems())
        labels = list(parm.menuLabels())
    except Exception as exc:
        raise _invalid(parm, kind, f"Cannot read the menu of {parm.path()}.") from exc
    shown = ", ".join(
        f"{t} ({labels[i]})" if i < len(labels) else t for i, t in enumerate(items[:20])
    )
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
            candidates=items[:20],
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
            candidates=items[:20],
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
    menu_mode = _menu_mode(template, kind)
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
            hint = (
                "For an expression use the expression field in parm_set, or "
                f"{EXPRESSION_SPELLINGS} as the value in node_create parms."
                if isinstance(value, str)
                else None
            )
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


def _apply(node: Any, target: Any, item: dict[str, Any], *, frame: float | None) -> dict[str, Any]:
    """Apply one ``parm_set`` item. Returns the item result (without node problems)."""
    import hou

    path = _target_path(target)
    present = [
        f
        for f in VALUE_FIELDS
        if (item.get(f) is True if f in _FLAG_FIELDS else item.get(f) is not None)
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
            if kind != "button":
                raise _invalid(parm, kind, f"{path} is a {kind} parm, not a button.")
            parm.pressButton()
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
    result["wrote_keyframe"] = wrote
    if notes:
        result["notes"] = notes
    return result


def _snapshot(target: Any) -> Any:
    """Capture each component's keys, expression or value; returns a restore function.

    ``partial: true`` keeps the call's undo group, so an item that fails half-way (say,
    component 2 of a tuple is locked) must put its own earlier components back.
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

    def restore() -> None:
        for parm, keys, value in saved:
            with contextlib.suppress(Exception):
                if parm.keyframes():
                    parm.deleteAllKeyframes()
                if keys:
                    parm.setKeyframes(keys)
                elif value is not None:
                    parm.set(value)

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
            hint=f"Call node_edit with lock: false on {asset} to allow editing its contents "
            "(or use the hda tool), then retry.",
            hou_exception=hou_exc,
        )
    if any(_parm_locked(p) for p in _components(target)):
        return ToolError(
            "locked",
            f"{path} is locked.",
            hint=f"Unlock it in Houdini, or with houdini_python: hou.parm('{_components(target)[0].path()}').lock(False).",
            hou_exception=hou_exc,
        )
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
    node: Any, parms: dict[str, Any], ctx: Any, *, animation: str = "replace"
) -> list[dict[str, Any]]:
    """Apply ``{parm_name: value | {expression, language} | {expr, lang}}`` to ``node`` and return per-parm results.

    Used by ``node_create`` (``items[].parms``) and ``network_build``. Same semantics as
    one ``parm_set`` item per entry; raises ToolError on the first failure. A dict value
    other than ``{expr, lang}`` (including ``{expression, language}``) is treated as a ``parm_set`` item without ``path`` (e.g.
    ``{"ramp": {...}}``, ``{"channel_ref": "/obj/..."}``). Results are the compact
    summary plus ``path`` and ``wrote_keyframe`` (no node errors: callers report those).
    """
    del ctx  # part of the shared signature; nothing here needs host state
    if not isinstance(parms, dict):
        raise ToolError("invalid_argument", "parms must be an object {name: value}.")
    results: list[dict[str, Any]] = []
    for name, spec in parms.items():
        try:
            target = resolve_name(node, name)
            item = _item_from_spec(name, spec, animation)
            results.append(_apply(node, target, item, frame=None))
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


@tool("parm_get")
def parm_get(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    paths = _paths_arg(args)
    frame = _frame_arg(args.get("frame"))
    include = args.get("include") or []
    if not isinstance(include, list) or any(i not in INCLUDE_KEYS for i in include):
        raise ToolError(
            "invalid_argument", f"'include' entries must be among {', '.join(INCLUDE_KEYS)}."
        )
    wanted = frozenset(include)
    out: list[dict[str, Any]] = []
    for path in paths:
        _node, target = resolve_path(path)
        if _is_tuple(target):
            out.append(_describe_tuple(target, frame=frame, include=wanted))
        else:
            out.append(_describe_parm(target, frame=frame, include=wanted))
    result: dict[str, Any] = {"parms": out}
    if frame is not None:
        result["frame"] = frame
    return result


@tool("parm_set")
def parm_set(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    items = args.get("items")
    if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
        raise ToolError("invalid_argument", "'items' must be a non-empty list of objects.")
    frame = _frame_arg(args.get("frame"))
    partial = args.get("partial", False)
    if not isinstance(partial, bool):
        raise ToolError("invalid_argument", "'partial' must be a boolean.")
    rows: list[tuple[Any, dict[str, Any]]] = []
    nodes: dict[str, Any] = {}
    failed = 0
    for index, item in enumerate(items):
        path = item.get("path")
        try:
            unknown = set(item) - ITEM_KEYS
            if unknown:
                raise ToolError("invalid_argument", f"Unexpected item keys {sorted(unknown)}.")
            node, target = resolve_path(path)
            restore = _snapshot(target) if partial else None
            try:
                result = _apply(node, target, item, frame=frame)
            except ToolError:
                if restore is not None:
                    restore()  # leave a failed item as it was, not half-applied
                raise
            nodes.setdefault(node.path(), node)
            rows.append((node.path(), result))
        except ToolError as exc:
            if not partial:
                # Messages usually start with the parm path already; do not repeat it.
                named = isinstance(path, str) and exc.message.startswith(path)
                if len(items) > 1:
                    prefix = f"items[{index}]" if named else f"items[{index}] ({path})"
                else:
                    prefix = None if named else str(path)
                extra = {"item": index, "path": path}
                if len(items) > 1:
                    extra["rolled_back"] = True
                raise _with_context(exc, prefix, extra) from exc
            failed += 1
            rows.append((None, {"path": path, "wrote_keyframe": False, "error": exc.to_dict()}))
    problems = {path: cheap_cook_problems(node) for path, node in nodes.items()}
    from .nodes import watch_nodes  # lazy: nodes imports this module lazily too

    watch_nodes(nodes.values())
    results: list[dict[str, Any]] = []
    for node_path, result in rows:
        if node_path is not None:
            diag = problems[node_path]
            result["errors"] = diag["errors"]
            result["warnings"] = diag["warnings"]
            result["cook_state"] = diag["cook_state"]
            if "hint" in diag:
                result["hint"] = diag["hint"]
        results.append(result)
    out: dict[str, Any] = {"results": results}
    if partial:
        out["failed"] = failed
    return out
