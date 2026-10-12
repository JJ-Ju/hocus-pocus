"""Docs generation and catalogue checks. Stdlib only (importable inside Houdini).

- ``render_tools_markdown(tools)`` renders ``docs/tools.md``.
- ``tools_list_text_size(tools)`` measures model-visible ``tools/list`` text.
- ``validate_examples(tools)`` checks every example (and every schema default) against
  its input schema with a small JSON Schema subset validator.

Regenerate the docs with ``python -m hocuspocus.tools.docs [OUTPUT]``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from hocuspocus.tools.catalog import TOOLS, ToolSpec

__all__ = [
    "SchemaError",
    "render_tools_markdown",
    "tools_list_text_size",
    "validate",
    "validate_examples",
    "write_tools_markdown",
]

# ---------------------------------------------------------------------------
# Size budget
# ---------------------------------------------------------------------------


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def tools_list_text_size(tools: Iterable[ToolSpec]) -> int:
    """UTF-8 byte size of names + descriptions + compact input schemas (bible §4.1 budget)."""
    total = 0
    for spec in tools:
        total += len(spec.name.encode("utf-8"))
        total += len(spec.description.encode("utf-8"))
        total += len(_compact(spec.input_schema).encode("utf-8"))
    return total


# ---------------------------------------------------------------------------
# JSON Schema subset validator
# ---------------------------------------------------------------------------

SUPPORTED_KEYWORDS = frozenset(
    {
        # assertions
        "type", "enum", "const", "required", "properties", "additionalProperties", "items",
        "oneOf", "anyOf", "minimum", "maximum", "minItems", "maxItems", "minLength",
        # annotations (ignored by validation)
        "description", "default", "title", "examples", "$schema",
    }
)  # fmt: skip


class SchemaError(ValueError):
    """An instance failed validation, or a schema uses an unsupported keyword."""


def _is_type(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer()
        )
    if type_name == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list | tuple)
    if type_name == "object":
        return isinstance(value, dict)
    raise SchemaError(f"unsupported type {type_name!r}")


def validate(instance: Any, schema: dict[str, Any] | bool, path: str = "$") -> None:
    """Raise :class:`SchemaError` if ``instance`` does not satisfy ``schema``.

    Supports the subset listed in :data:`SUPPORTED_KEYWORDS`; any other keyword raises,
    so a catalogue schema cannot silently rely on something this validator ignores.
    """
    if schema is True:
        return
    if schema is False:
        raise SchemaError(f"{path}: not allowed")
    unknown = set(schema) - SUPPORTED_KEYWORDS
    if unknown:
        raise SchemaError(f"{path}: unsupported schema keywords {sorted(unknown)}")
    for check in (_check_value, _check_bounds, _check_array, _check_object, _check_combinators):
        check(instance, schema, path)


def _check_value(instance: Any, schema: dict[str, Any], path: str) -> None:
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(instance, t) for t in types):
            got = type(instance).__name__
            raise SchemaError(f"{path}: expected {'|'.join(types)}, got {got}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: {instance!r} not in {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"{path}: expected {schema['const']!r}")


def _check_bounds(instance: Any, schema: dict[str, Any], path: str) -> None:
    if _is_type(instance, "number"):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaError(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaError(f"{path}: {instance} > maximum {schema['maximum']}")
    if isinstance(instance, str) and len(instance) < schema.get("minLength", 0):
        raise SchemaError(f"{path}: shorter than {schema['minLength']}")


def _check_array(instance: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(instance, list | tuple):
        return
    if len(instance) < schema.get("minItems", 0):
        raise SchemaError(f"{path}: fewer than {schema['minItems']} items")
    if "maxItems" in schema and len(instance) > schema["maxItems"]:
        raise SchemaError(f"{path}: more than {schema['maxItems']} items")
    if "items" in schema:
        for index, item in enumerate(instance):
            validate(item, schema["items"], f"{path}[{index}]")


def _check_object(instance: Any, schema: dict[str, Any], path: str) -> None:
    if not isinstance(instance, dict):
        return
    for key in schema.get("required", ()):
        if key not in instance:
            raise SchemaError(f"{path}: missing required {key!r}")
    properties = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    for key, value in instance.items():
        if key in properties:
            validate(value, properties[key], f"{path}.{key}")
        elif additional is False:
            raise SchemaError(f"{path}: unexpected property {key!r}")
        elif isinstance(additional, dict):
            validate(value, additional, f"{path}.{key}")


def _check_combinators(instance: Any, schema: dict[str, Any], path: str) -> None:
    if "anyOf" in schema:
        errors = _branch_errors(instance, schema["anyOf"], path)
        if len(errors) == len(schema["anyOf"]):
            raise SchemaError(f"{path}: matches no anyOf branch ({'; '.join(errors)})")
    if "oneOf" in schema:
        errors = _branch_errors(instance, schema["oneOf"], path)
        matched = len(schema["oneOf"]) - len(errors)
        if matched != 1:
            raise SchemaError(f"{path}: matches {matched} oneOf branches, expected exactly 1")


def _branch_errors(instance: Any, branches: Sequence[dict[str, Any]], path: str) -> list[str]:
    errors = []
    for branch in branches:
        try:
            validate(instance, branch, path)
        except SchemaError as exc:
            errors.append(str(exc))
    return errors


def _walk_defaults(schema: Any, path: str) -> Iterable[tuple[str, Any, dict[str, Any]]]:
    """Yield ``(path, default, schema)`` for every subschema that declares a default."""
    if not isinstance(schema, dict):
        return
    if "default" in schema:
        yield path, schema["default"], schema
    for key, sub in schema.get("properties", {}).items():
        yield from _walk_defaults(sub, f"{path}.{key}")
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            yield from _walk_defaults(schema[key], f"{path}.{key}")
    for key in ("anyOf", "oneOf"):
        for index, sub in enumerate(schema.get(key, ())):
            yield from _walk_defaults(sub, f"{path}.{key}[{index}]")


def validate_examples(tools: Iterable[ToolSpec]) -> list[str]:
    """Validate every example and every declared default; return failure messages.

    An empty list means all examples are valid. Tools without examples are reported.
    """
    failures: list[str] = []
    for spec in tools:
        if not spec.examples:
            failures.append(f"{spec.name}: no examples")
        for index, example in enumerate(spec.examples):
            try:
                validate(example, spec.input_schema)
            except SchemaError as exc:
                failures.append(f"{spec.name} example {index}: {exc}")
        for where, default, sub in _walk_defaults(spec.input_schema, "$"):
            stripped = {k: v for k, v in sub.items() if k != "default"}
            try:
                validate(default, stripped, where)
            except SchemaError as exc:
                failures.append(f"{spec.name} default: {exc}")
    return failures


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _type_label(schema: Any) -> str:
    if not isinstance(schema, dict) or not schema:
        return "any"
    for key in ("anyOf", "oneOf"):
        if key in schema and "type" not in schema:
            return " | ".join(_type_label(branch) for branch in schema[key])
    type_ = schema.get("type", "any")
    types = type_ if isinstance(type_, list) else [type_]
    labels = []
    for name in types:
        if name == "array" and isinstance(schema.get("items"), dict):
            labels.append(f"array<{_type_label(schema['items'])}>")
        elif name == "string" and "enum" in schema:
            labels.append(" | ".join(f"`{v}`" for v in schema["enum"]))
        elif name == "object" and isinstance(schema.get("additionalProperties"), dict):
            labels.append(f"object<string, {_type_label(schema['additionalProperties'])}>")
        else:
            labels.append(name)
    return " | ".join(labels)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _constraints(schema: dict[str, Any]) -> str:
    parts = []
    bounds = (("minimum", "min"), ("maximum", "max"), ("minItems", "min items"), ("maxItems", "max items"))
    for key, label in bounds:
        if key in schema:
            parts.append(f"{label} {schema[key]}")
    items = schema.get("items")
    for target, label in ((schema, ""), (items, "each item: ")):
        if isinstance(target, dict) and "oneOf" in target and "type" in target:
            alternatives = [" + ".join(b.get("required", [])) for b in target["oneOf"]]
            parts.append(label + "exactly one of " + ", ".join(a for a in alternatives if a))
    return "; ".join(parts)


def _argument_rows(schema: dict[str, Any], prefix: str = "") -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    required = set(schema.get("required", ()))
    for name, sub in schema.get("properties", {}).items():
        full = f"{prefix}{name}"
        description = sub.get("description", "")
        extra = _constraints(sub)
        if extra:
            description = f"{description} ({extra})" if description else extra
        default = f"`{_compact(sub['default'])}`" if "default" in sub else ""
        rows.append((f"`{full}`", _type_label(sub), "yes" if name in required else "", default, description))
        if sub.get("type") == "object" and sub.get("properties"):
            rows.extend(_argument_rows(sub, f"{full}."))
        items = sub.get("items")
        if sub.get("type") == "array" and isinstance(items, dict) and items.get("properties"):
            rows.extend(_argument_rows(items, f"{full}[]."))
    return rows


def _returns_lines(schema: dict[str, Any]) -> list[str]:
    required = set(schema.get("required", ()))
    lines = []
    for name, sub in schema.get("properties", {}).items():
        line = f"- `{name}` ({_type_label(sub)})"
        nested = sub.get("properties") or (sub.get("items") or {}).get("properties")
        if not nested and "anyOf" in sub:
            for branch in sub["anyOf"]:
                nested = nested or branch.get("properties")
        if nested:
            line += ": " + ", ".join(f"`{key}`" for key in nested)
        if name in required:
            line += " — always present"
        if sub.get("description"):
            line += f" — {sub['description']}"
        lines.append(line)
    return lines


def _badges(spec: ToolSpec) -> str:
    badges = []
    if spec.read_only:
        badges.append("read-only")
    if spec.destructive and not spec.read_only:
        badges.append("destructive")
    if spec.idempotent:
        badges.append("idempotent")
    if spec.bridge_local:
        badges.append("bridge-local")
    badges.append("headless ok" if spec.headless_ok else "GUI only")
    return " ".join(f"`{badge}`" for badge in badges)


def render_tools_markdown(tools: Sequence[ToolSpec]) -> str:
    """Render the full ``docs/tools.md`` text (LF line endings, trailing newline)."""
    core = sum(1 for spec in tools if spec.profile == "core")
    out: list[str] = [
        "# HocusPocus tools",
        "",
        "<!-- Generated from src/hocuspocus/tools/catalog.py by `python -m hocuspocus.tools.docs`."
        " Do not edit by hand. -->",
        "",
        f"{len(tools)} tools: {core} in the `core` profile, {len(tools) - core} more in `full`. "
        f"Model-visible `tools/list` text: {tools_list_text_size(tools):,} bytes. "
        "See `docs/BIBLE.md` §4 for the design.",
        "",
        "## Contents",
        "",
    ]
    for spec in tools:
        suffix = " *(full)*" if spec.profile == "full" else ""
        out.append(f"- [`{spec.name}`](#{spec.name}){suffix}")
    for spec in tools:
        out += ["", f"## {spec.name}", "", f"{_badges(spec)} · profile `{spec.profile}`", "", spec.description, ""]
        rows = _argument_rows(spec.input_schema)
        out += ["### Arguments", ""]
        if rows:
            out += ["| Name | Type | Required | Default | Description |", "|---|---|---|---|---|"]
            out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
        else:
            out.append("None.")
        out.append("")
        if spec.output_schema:
            out += ["### Returns", ""]
            out += _returns_lines(spec.output_schema)
            out.append("")
        if spec.examples:
            out += ["### Examples", ""]
            for example in spec.examples:
                out += ["```json", json.dumps(example, ensure_ascii=False), "```", ""]
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def write_tools_markdown(path: str | Path, tools: Sequence[ToolSpec] = TOOLS) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_tools_markdown(tools))
    return target


def default_output_path() -> Path:
    """``docs/tools.md`` of the checkout this module lives in."""
    return Path(__file__).resolve().parents[3] / "docs" / "tools.md"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    target = write_tools_markdown(args[0] if args else default_output_path())
    print(f"wrote {target} ({tools_list_text_size(TOOLS)} bytes of tools/list text)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
