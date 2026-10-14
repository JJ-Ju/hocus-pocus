"""A small stdlib JSON-Schema-subset validator for tool arguments.

MCP SDK v2 does not validate ``tools/call`` arguments (BIBLE §3.3 rule 2), so the bridge
does. Supported keywords: ``type``, ``properties``, ``required``, ``additionalProperties``,
``enum``, ``const``, ``items``, ``prefixItems``, ``minItems``/``maxItems``, ``uniqueItems``,
``minimum``/``maximum``/``exclusiveMinimum``/``exclusiveMaximum``, ``minLength``/``maxLength``,
``pattern``, ``minProperties``, ``oneOf``/``anyOf``/``allOf``/``not`` and local ``$ref``
(``#/$defs/...``). Unknown keywords are ignored, never fatal.

``enum`` and ``const`` compare JSON values, not Python ones: ``true`` is not ``1``.
:func:`coerce_integers` turns integral floats (``50.0``) into ints where the schema says
``integer``, so the host's ``isinstance(x, int)`` checks agree with the validator.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

from ..tools.budget import clip

MAX_VIOLATIONS = 20

ARG_RENAMES: dict[str, dict[str, str]] = {
    "inspect": {
        "path": "target",
        "node_path": "target",
        "root": "target",
        "lop_path": "target",
        "type": "target",
        "rop_path": "target",
        "cop_path": "target",
    },
}
"""Per tool, a 1.4 argument name -> the 2.0 argument that replaced it (review 25 papercut
2: ``inspect {path}`` was answered "did you mean paths, depth?"). An unknown top-level
property in this table is reported as the rename, before any edit-distance suggestion, and
:func:`rename_hint` shows the corrected call. ``paths`` given as one string is the same
mistake (:func:`rename_hint`)."""

_KNOWN_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _json_equal(a: Any, b: Any) -> bool:
    """JSON equality: booleans never equal numbers (``True == 1`` in Python)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_json_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_json_equal(a[k], b[k]) for k in a)
    return a == b


def _matches_type(value: Any, expected: str) -> bool:
    actual = _type_of(value)
    if expected == "number":
        return actual in ("integer", "number")
    return actual == expected


def _short(value: Any, limit: int = 60) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(value)
    return clip(text, limit)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _label(path: str) -> str:
    return path or "(arguments)"


class _Validator:
    def __init__(self, root: dict[str, Any], renames: dict[str, str] | None = None) -> None:
        self.root = root
        self.renames = renames or {}
        self.errors: list[str] = []

    def _resolve(self, schema: Any) -> dict[str, Any]:
        hops = 0
        while isinstance(schema, dict) and "$ref" in schema and hops < 32:
            ref = schema["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#"):
                return {}
            target: Any = self.root
            for part in ref[1:].strip("/").split("/"):
                if not part:
                    continue
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or part not in target:
                    return {}
                target = target[part]
            schema = target
            hops += 1
        return schema if isinstance(schema, dict) else {}

    def check(self, value: Any, schema: Any, path: str) -> None:
        if schema is True or schema is None:
            return
        if schema is False:
            self.errors.append(f"{_label(path)}: not allowed")
            return
        schema = self._resolve(schema)
        if not schema:
            return

        expected = schema.get("type")
        if expected is not None:
            types = [
                t
                for t in (expected if isinstance(expected, list) else [expected])
                if t in _KNOWN_TYPES
            ]
            if types and not any(_matches_type(value, t) for t in types):
                self.errors.append(
                    f"{_label(path)}: expected {' or '.join(types)}, got {_type_of(value)} {_short(value)}"
                )
                return

        if "const" in schema and not _json_equal(value, schema["const"]):
            self.errors.append(f"{_label(path)}: must be {_short(schema['const'])}")
        if "enum" in schema and not any(_json_equal(value, m) for m in schema["enum"]):
            allowed = ", ".join(_short(v) for v in schema["enum"])
            self.errors.append(f"{_label(path)}: {_short(value)} is not one of [{allowed}]")

        if isinstance(value, dict):
            self._object(value, schema, path)
        elif isinstance(value, list):
            self._array(value, schema, path)
        elif isinstance(value, str):
            self._string(value, schema, path)
        elif isinstance(value, int | float) and not isinstance(value, bool):
            self._number(value, schema, path)

        for sub in schema.get("allOf") or []:
            self.check(value, sub, path)
        if "anyOf" in schema:
            self._any_of(value, schema["anyOf"], path)
        if "oneOf" in schema:
            self._one_of(value, schema["oneOf"], path)
        if "not" in schema and not self._sub_errors(value, schema["not"], path):
            self.errors.append(f"{_label(path)}: matches a forbidden schema")

    def _sub_errors(self, value: Any, schema: Any, path: str) -> list[str]:
        sub = _Validator(self.root)
        sub.check(value, schema, path)
        return sub.errors

    def _any_of(self, value: Any, options: list[Any], path: str) -> None:
        results = [self._sub_errors(value, opt, path) for opt in options]
        if not results or any(not errs for errs in results):
            return
        message = self._best_branch(results, path, "anyOf")
        if isinstance(value, dict):
            # Name every object form the caller could have meant (e.g. both expression
            # spellings in node_create parms).
            forms = [
                "{" + ", ".join(opt["properties"]) + "}"
                for opt in options
                if isinstance(opt, dict) and isinstance(opt.get("properties"), dict)
            ]
            if forms:
                message += f"; object forms: {' or '.join(forms)}"
        self.errors.append(message)

    def _one_of(self, value: Any, options: list[Any], path: str) -> None:
        results = [self._sub_errors(value, opt, path) for opt in options]
        passing = sum(1 for errs in results if not errs)
        if passing == 1 or not results:
            return
        if passing > 1:
            self.errors.append(
                f"{_label(path)}: matches more than one alternative (oneOf); be more specific"
            )
            return
        self.errors.append(self._best_branch(results, path, "oneOf"))

    @staticmethod
    def _best_branch(results: list[list[str]], path: str, keyword: str) -> str:
        # The alternative with the fewest violations is usually the one the caller meant,
        # but one of the value's own type (an object for an object branch) beats a bare
        # "expected string, got object": its errors name the properties that are wrong.
        wrong_type = f"{_label(path)}: expected "
        same_type = [errs for errs in results if not errs[0].startswith(wrong_type)]
        best = min(same_type or results, key=len)
        return f"{best[0]} (no alternative of {keyword} matched)"

    def _object(self, value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
        props: dict[str, Any] = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                self.errors.append(f"{_join(path, name)}: required property is missing")
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child = _join(path, key)
            if key in props:
                self.check(item, props[key], child)
            elif additional is False:
                renamed = self.renames.get(key) if not path else None
                close = difflib.get_close_matches(key, list(props), n=3, cutoff=0.6)
                if renamed in props:
                    self.errors.append(f"{child}: unknown property; 2.0 renamed it {renamed}")
                elif close:
                    self.errors.append(
                        f"{child}: unknown property; did you mean {', '.join(close)}?"
                    )
                elif props:
                    self.errors.append(f"{child}: unknown property (allowed: {', '.join(props)})")
                else:
                    self.errors.append(
                        f"{child}: unknown property (this object takes no properties)"
                    )
            elif isinstance(additional, dict):
                self.check(item, additional, child)
        min_props = schema.get("minProperties")
        if isinstance(min_props, int) and len(value) < min_props:
            self.errors.append(f"{_label(path)}: needs at least {min_props} property(ies)")

    def _array(self, value: list[Any], schema: dict[str, Any], path: str) -> None:
        lo, hi = schema.get("minItems"), schema.get("maxItems")
        if isinstance(lo, int) and len(value) < lo:
            self.errors.append(f"{_label(path)}: needs at least {lo} item(s), got {len(value)}")
        if isinstance(hi, int) and len(value) > hi:
            self.errors.append(f"{_label(path)}: allows at most {hi} item(s), got {len(value)}")
        start = 0
        prefix = schema.get("prefixItems")
        if isinstance(prefix, list):
            for i, (item, sub) in enumerate(zip(value, prefix, strict=False)):
                self.check(item, sub, f"{path}[{i}]")
            start = len(prefix)
        items = schema.get("items")
        if isinstance(items, list):  # draft-07 tuple form
            for i, (item, sub) in enumerate(zip(value, items, strict=False)):
                self.check(item, sub, f"{path}[{i}]")
        elif items is not None:
            for i in range(start, len(value)):
                self.check(value[i], items, f"{path}[{i}]")
                if len(self.errors) >= MAX_VIOLATIONS:
                    return
        if schema.get("uniqueItems"):
            seen: set[str] = set()
            for item in value:
                key = json.dumps(item, sort_keys=True, default=str)
                if key in seen:
                    self.errors.append(
                        f"{_label(path)}: items must be unique ({_short(item)} repeats)"
                    )
                    break
                seen.add(key)

    def _string(self, value: str, schema: dict[str, Any], path: str) -> None:
        lo, hi = schema.get("minLength"), schema.get("maxLength")
        if isinstance(lo, int) and len(value) < lo:
            self.errors.append(f"{_label(path)}: must be at least {lo} character(s)")
        if isinstance(hi, int) and len(value) > hi:
            self.errors.append(f"{_label(path)}: must be at most {hi} character(s)")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    self.errors.append(
                        f"{_label(path)}: {_short(value)} does not match pattern {pattern!r}"
                    )
            except re.error:
                pass

    def _number(self, value: float, schema: dict[str, Any], path: str) -> None:
        checks = (
            ("minimum", lambda b: value < b, ">="),
            ("maximum", lambda b: value > b, "<="),
            ("exclusiveMinimum", lambda b: value <= b, ">"),
            ("exclusiveMaximum", lambda b: value >= b, "<"),
        )
        for keyword, fails, op in checks:
            bound = schema.get(keyword)
            if isinstance(bound, int | float) and not isinstance(bound, bool) and fails(bound):
                self.errors.append(f"{_label(path)}: must be {op} {bound}, got {value}")


def coerce_integers(value: Any, schema: dict[str, Any] | None) -> Any:
    """A copy of ``value`` with integral floats made ints where ``schema`` says
    ``integer`` (through properties, items, prefixItems, additionalProperties and local
    ``$ref``). Call it on arguments that already validated."""
    if not schema:
        return value
    return _Coercer(schema).walk(value, schema)


class _Coercer(_Validator):
    def walk(self, value: Any, schema: Any) -> Any:
        schema = self._resolve(schema) if isinstance(schema, dict) else {}
        if not schema:
            return value
        expected = schema.get("type")
        if (
            isinstance(value, float)
            and value.is_integer()
            and (expected == "integer" or (isinstance(expected, list) and "integer" in expected))
            and "number" not in (expected if isinstance(expected, list) else [expected])
        ):
            return int(value)
        if isinstance(value, dict):
            props = schema.get("properties") or {}
            additional = schema.get("additionalProperties")
            out = {}
            for key, item in value.items():
                sub = props.get(key, additional if isinstance(additional, dict) else None)
                out[key] = self.walk(item, sub) if isinstance(sub, dict) else item
            return out
        if isinstance(value, list):
            prefix = schema.get("prefixItems")
            prefix = prefix if isinstance(prefix, list) else []
            items = schema.get("items")
            out_list = []
            for i, item in enumerate(value):
                sub = prefix[i] if i < len(prefix) else items
                out_list.append(self.walk(item, sub) if isinstance(sub, dict) else item)
            return out_list
        return value


def validate(
    value: Any, schema: dict[str, Any] | None, renames: dict[str, str] | None = None
) -> list[str]:
    """Return human-readable violations (empty when ``value`` conforms to ``schema``).
    ``renames`` (a tool's :data:`ARG_RENAMES`) names the 2.0 argument for a 1.4 one."""
    if not schema:
        return []
    validator = _Validator(schema, renames)
    validator.check(value, schema, "")
    return validator.errors[:MAX_VIOLATIONS]


SHAPE_HINT_MAX_CHARS = 400


def rename_hint(tool: str, value: Any, schema: dict[str, Any] | None) -> str | None:
    """The corrected call when ``value`` uses a 1.4 argument name :data:`ARG_RENAMES`
    maps for ``tool`` (``inspect {what: "geo", path}`` -> ``inspect {what: "geo",
    target}``), or passes ``paths`` as one string; None otherwise. A one-item list becomes
    the string; with ``target`` already given the old argument is dropped."""
    renames = ARG_RENAMES.get(tool)
    if not renames or not isinstance(value, dict) or not schema:
        return None
    props = schema.get("properties") or {}
    fixed: dict[str, Any] = {}
    changed = False
    for key, item in value.items():
        new = renames.get(key) if key not in props else None
        if key == "paths" and isinstance(item, str):
            new = "target"
        if new is None or new not in props:
            fixed.setdefault(key, item)
            continue
        changed = True
        if isinstance(item, list) and len(item) == 1:
            item = item[0]
        if new in value or new in fixed:
            continue  # target was given too: drop the 1.4 spelling
        fixed[new] = item
    if not changed:
        return None
    shown = {k: fixed[k] for k in ("what", "kind", "target") if k in fixed}
    shown.update({k: v for k, v in fixed.items() if k not in shown})
    text = json.dumps(_elided(shown), ensure_ascii=False)
    if len(text) > SHAPE_HINT_MAX_CHARS:
        text = text[: SHAPE_HINT_MAX_CHARS - 1] + "…"
    return f"{tool} takes the path as target: {tool} {text}"


def _elided(value: Any) -> Any:
    """``value`` with long strings and lists shortened, for a hint that echoes it."""
    if isinstance(value, str) and len(value) > 80:
        return clip(value, 80)
    if isinstance(value, list):
        return [_elided(v) for v in value[:4]] + (["..."] if len(value) > 4 else [])
    if isinstance(value, dict):
        return {k: _elided(v) for k, v in value.items()}
    return value


def shape_hint(value: Any, schema: dict[str, Any] | None) -> str | None:
    """The corrected call when ``value`` is one flat item of a batch tool (review 21
    papercut 1): ``parm_set {path, value}`` instead of ``{items: [{path, value}]}``.

    Returns ``wrap it: {"items": [{...the caller's own item fields...}], ...}`` when the
    schema requires an ``items`` array of objects, ``value`` has no ``items``, and every
    key that is not a top-level property is a property of an item; else None."""
    if not isinstance(value, dict) or not schema or "items" in value:
        return None
    validator = _Validator(schema)
    root = validator._resolve(schema)
    props = root.get("properties") or {}
    if "items" not in props or "items" not in (root.get("required") or ()):
        return None
    array = validator._resolve(props["items"]) if isinstance(props["items"], dict) else {}
    item = validator._resolve(array.get("items")) if isinstance(array.get("items"), dict) else {}
    item_props = item.get("properties") or {}
    flat = {k: v for k, v in value.items() if k not in props}
    if not flat or not item_props or any(k not in item_props for k in flat):
        return None
    outer = {k: v for k, v in value.items() if k in props}
    fixed = json.dumps(_elided({"items": [flat], **outer}), ensure_ascii=False)
    if len(fixed) > SHAPE_HINT_MAX_CHARS:
        fixed = fixed[: SHAPE_HINT_MAX_CHARS - 1] + "…"
    return f"this tool takes a batch; pass the item inside items: {fixed}"
