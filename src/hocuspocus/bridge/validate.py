"""A small stdlib JSON-Schema-subset validator for tool arguments.

MCP SDK v2 does not validate ``tools/call`` arguments (BIBLE §3.3 rule 2), so the bridge
does. Supported keywords: ``type``, ``properties``, ``required``, ``additionalProperties``,
``enum``, ``const``, ``items``, ``prefixItems``, ``minItems``/``maxItems``, ``uniqueItems``,
``minimum``/``maximum``/``exclusiveMinimum``/``exclusiveMaximum``, ``minLength``/``maxLength``,
``pattern``, ``minProperties``, ``oneOf``/``anyOf``/``allOf``/``not`` and local ``$ref``
(``#/$defs/...``). Unknown keywords are ignored, never fatal.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any

MAX_VIOLATIONS = 20

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
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _label(path: str) -> str:
    return path or "(arguments)"


class _Validator:
    def __init__(self, root: dict[str, Any]) -> None:
        self.root = root
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

        if "const" in schema and value != schema["const"]:
            self.errors.append(f"{_label(path)}: must be {_short(schema['const'])}")
        if "enum" in schema and value not in schema["enum"]:
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
                close = difflib.get_close_matches(key, list(props), n=3, cutoff=0.6)
                if close:
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


def validate(value: Any, schema: dict[str, Any] | None) -> list[str]:
    """Return human-readable violations (empty when ``value`` conforms to ``schema``)."""
    if not schema:
        return []
    validator = _Validator(schema)
    validator.check(value, schema, "")
    return validator.errors[:MAX_VIOLATIONS]
