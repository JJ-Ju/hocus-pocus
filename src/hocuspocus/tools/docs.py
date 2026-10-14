"""Docs generation and catalogue checks. Stdlib only (importable inside Houdini).

- ``render_tools_markdown(tools)`` renders ``docs/tools.md``.
- ``tools_list_text_size(tools)`` measures model-visible ``tools/list`` text.
- ``validate_examples(tools)`` checks every example (and every schema default) against
  its input schema with a small JSON Schema subset validator.
- ``tools_reference(tools)`` is the ``hocuspocus://tools`` resource the bridge serves (the
  same text as ``docs/tools.md``).
- ``update_budget_markdown(path)`` writes ``docs/redesign/budget.md`` (spec-2.0 §5.1): the
  serialised ``tools/list`` bytes per profile × ``result_content`` mode, one dated history
  row per run, and the tools that contribute most.

All of them render the same objects, the ``SPEC`` of each module in
``hocuspocus/tools/spec/`` as :data:`hocuspocus.tools.catalog.TOOLS` loads them.

Regenerate the docs with ``python -m hocuspocus.tools.docs [OUTPUT]`` and the budget report
with ``python -m hocuspocus.tools.docs --budget [OUTPUT]``. The budget report measures what
the bridge really sends, so it imports the bridge and the ``mcp`` SDK when it runs: it needs
the dev install, never Houdini, and nothing else in this module imports them.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from hocuspocus.tools.catalog import TOOLS, ToolSpec, get, profile_of, v2_spec
from hocuspocus.tools.migration import REPLACEMENTS
from hocuspocus.tools.profiles import COMPAT_1X

__all__ = [
    "SchemaError",
    "measure_budget",
    "render_budget_markdown",
    "render_tools_markdown",
    "tools_list_text_size",
    "tools_list_wire",
    "tools_reference",
    "update_budget_markdown",
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
    bounds = (
        ("minimum", "min"),
        ("maximum", "max"),
        ("minItems", "min items"),
        ("maxItems", "max items"),
    )
    for key, label in bounds:
        if key in schema:
            parts.append(f"{label} {schema[key]}")
    items = schema.get("items")
    for target, label in ((schema, ""), (items, "each item: ")):
        if isinstance(target, dict) and "oneOf" in target and "type" in target:
            alternatives = [" + ".join(b.get("required", [])) for b in target["oneOf"]]
            parts.append(label + "exactly one of " + ", ".join(a for a in alternatives if a))
    return "; ".join(parts)


def _argument_rows(
    schema: dict[str, Any], prefix: str = ""
) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    required = set(schema.get("required", ()))
    for name, sub in schema.get("properties", {}).items():
        full = f"{prefix}{name}"
        description = sub.get("description", "")
        extra = _constraints(sub)
        if extra:
            description = f"{description} ({extra})" if description else extra
        default = f"`{_compact(sub['default'])}`" if "default" in sub else ""
        rows.append(
            (f"`{full}`", _type_label(sub), "yes" if name in required else "", default, description)
        )
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


V2_MARK = "*(not in compat_1x)*"
"""Marks an argument or result key a 1.4 tool gains in the 2.0 profiles (``v2_extra``), which
``compat_1x`` does not list."""


def _v2_names(spec: ToolSpec, part: str) -> set[str]:
    """Top-level names ``spec.v2_extra[part]`` adds to the 1.x spec of that name (not the
    ones it only changes, such as ``houdini_status``'s ``profile`` enum)."""
    added = set(((spec.v2_extra or {}).get(part) or {}).get("properties") or {})
    base = get(spec.name) or spec
    schema = base.input_schema if part == "input" else (base.output_schema or {})
    return added - set(schema.get("properties") or {})


def _profiles_line(spec: ToolSpec) -> str:
    """The profiles that list ``spec`` and, for a removed 1.4 tool, its replacement."""
    line = "profiles " + ", ".join(f"`{name}`" for name in spec.profiles)
    if spec.name in REPLACEMENTS:
        line += f" · 2.0: {REPLACEMENTS[spec.name]}"
    return line


def render_tools_markdown(tools: Sequence[ToolSpec]) -> str:
    """Render the full ``docs/tools.md`` text (LF line endings, trailing newline)."""
    counts = {p: sum(1 for spec in tools if p in spec.profiles) for p in ("minimal", "core")}
    full = sum(1 for spec in tools if "full" in spec.profiles)
    compat = sum(1 for spec in tools if COMPAT_1X in spec.profiles)
    compat_only = sum(1 for spec in tools if profile_of(spec) == COMPAT_1X)
    compat_part = (
        f" `compat_1x` lists the {compat} 1.4 tools with their 1.4 schemas, {compat_only} of "
        "them only there (each names its 2.0 replacement)."
        if compat
        else ""
    )
    out: list[str] = [
        "# HocusPocus tools",
        "",
        "<!-- Generated from src/hocuspocus/tools/spec/ by `python -m hocuspocus.tools.docs`."
        " Do not edit by hand. -->",
        "",
        f"{len(tools)} tools. The 2.0 profiles nest: {counts['minimal']} in `minimal`, "
        f"{counts['core']} in `core` (the default), {full} in `full`.{compat_part} "
        f"Model-visible `tools/list` text: {tools_list_text_size(tools):,} bytes. "
        "See `docs/BIBLE.md` §4 for the design.",
        "",
        "## Contents",
        "",
    ]
    for spec in tools:
        suffix = {
            "full": " *(full)*",
            "minimal": " *(minimal)*",
            COMPAT_1X: " *(compat_1x)*",
        }.get(profile_of(spec), "")
        out.append(f"- [`{spec.name}`](#{spec.name}){suffix}")
    for spec in tools:
        out += [
            "",
            f"## {spec.name}",
            "",
            f"{_badges(spec)} · {_profiles_line(spec)}",
            "",
            spec.description,
            "",
        ]
        if spec.notes:
            out += [f"**Notes.** {spec.notes}", ""]
        # A 1.x tool's v2_extra arguments (spec-2.0 §7 M2) are listed, marked as v2 only.
        full_spec = v2_spec(spec)
        v2_args = {f"`{name}`" for name in _v2_names(spec, "input")}
        rows = [
            (*row[:4], f"{row[4]} {V2_MARK}".strip()) if row[0] in v2_args else row
            for row in _argument_rows(full_spec.input_schema)
        ]
        out += ["### Arguments", ""]
        if rows:
            out += ["| Name | Type | Required | Default | Description |", "|---|---|---|---|---|"]
            out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
        else:
            out.append("None.")
        out.append("")
        if full_spec.output_schema:
            v2_keys = _v2_names(spec, "output")
            out += ["### Returns", ""]
            out += [
                f"{line} {V2_MARK}" if line.split("`")[1] in v2_keys else line
                for line in _returns_lines(full_spec.output_schema)
            ]
            out.append("")
        if spec.examples:
            out += ["### Examples", ""]
            for example in spec.examples:
                out += ["```json", json.dumps(example, ensure_ascii=False), "```", ""]
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def tools_reference(tools: Sequence[ToolSpec] | None = None) -> str:
    """``hocuspocus://tools``: the per-tool reference the bridge serves, the same text as
    ``docs/tools.md`` (including each tool's ``notes``, which ``tools/list`` leaves out;
    BIBLE §4.1). ``tools`` defaults to the whole catalogue; the bridge passes its profile's."""
    return render_tools_markdown(tuple(tools) if tools is not None else TOOLS)


def write_tools_markdown(path: str | Path, tools: Sequence[ToolSpec] = TOOLS) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_tools_markdown(tools))
    return target


def default_output_path() -> Path:
    """``docs/tools.md`` of the checkout this module lives in."""
    return Path(__file__).resolve().parents[3] / "docs" / "tools.md"


# ---------------------------------------------------------------------------
# Budget report (docs/redesign/budget.md)
# ---------------------------------------------------------------------------

BUDGET_PROFILES: tuple[str, ...] = ("minimal", "core", "full", COMPAT_1X)
BUDGET_MODES: tuple[str, ...] = ("text", "both")
TOOLS_LIST_CAPS: dict[str, int] = {"text": 24_000, "both": 34_000}
"""spec-2.0 §7 M3 caps on the 2.0 ``full`` profile's serialised ``tools/list`` per
``result_content`` mode; ``test_tools_list_budget`` enforces them."""
COMPAT_TOOLS_LIST_CAPS: dict[str, int] = {"text": 32_000, "both": 44_000}
"""BIBLE §4.1 (1.4) caps, kept by ``compat_1x`` (1.4's ``full`` catalogue)."""
BUDGET_TOP = 10
BUDGET_COLUMNS: tuple[str, ...] = tuple(f"{p} {m}" for m in BUDGET_MODES for p in BUDGET_PROFILES)
"""What one run measures, ``"<profile> <mode>"``: the four profiles in ``text``, then in
``both``."""
HISTORY_COLUMNS: tuple[str, ...] = tuple(
    f"{p} {m}" for m in BUDGET_MODES for p in ("minimal", "core", "full", "v2", COMPAT_1X)
)
"""The history table's columns: :data:`BUDGET_COLUMNS` plus ``v2``, the M1-M2 preview
profile measured before the 2.0 cut-over (rows show ``—`` where a profile did not exist)."""
LEGACY_BUDGET_COLUMNS: tuple[str, ...] = tuple(
    f"{p} {m}" for m in BUDGET_MODES for p in ("minimal", "core", "full")
)
"""Columns of a 1.4 row read without a header."""
_HISTORY_HEADING = "## History"
_CONTRIBUTION_HEADING = "## Per-tool contribution"
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def tools_list_wire(profile: str, result_content: str = "text") -> dict[str, Any]:
    """The ``tools/list`` result the bridge sends for ``profile`` in ``result_content`` mode,
    as the JSON object the MCP SDK serialises. Imports the bridge (dev install only)."""
    import mcp_types as types

    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge

    bridge = Bridge(BridgeConfig(profile=profile, result_content=result_content), scan=lambda: [])
    result = types.ListToolsResult(tools=bridge.list_tools())
    return result.model_dump(by_alias=True, mode="json", exclude_none=True)


def _wire_size(value: Any) -> int:
    return len(_compact(value).encode("utf-8"))


def measure_budget() -> dict[str, Any]:
    """Bytes of the serialised ``tools/list`` result per profile × mode (``sizes``, keyed as
    :data:`BUDGET_COLUMNS`) and each tool's part of the full profile's result (``tools``:
    name -> ``{mode: bytes}``, the tool's entry plus its separating comma)."""
    sizes: dict[str, int] = {}
    per_tool: dict[str, dict[str, int]] = {}
    for mode in BUDGET_MODES:
        for profile in BUDGET_PROFILES:
            payload = tools_list_wire(profile, mode)
            sizes[f"{profile} {mode}"] = _wire_size(payload)
            if profile == "full":
                for entry in payload["tools"]:
                    per_tool.setdefault(entry["name"], {})[mode] = _wire_size(entry) + 1
    return {"sizes": sizes, "tools": per_tool}


def _budget_row(row: dict[str, Any]) -> str:
    sizes = row["sizes"]
    cells = [
        row["date"],
        row["version"],
        *(f"{sizes[c]:,}" if c in sizes else "—" for c in HISTORY_COLUMNS),
    ]
    return "| " + " | ".join(cells) + " |"


def parse_budget_history(text: str) -> list[dict[str, Any]]:
    """The history rows of a budget report as ``{date, version, sizes}``, oldest first."""
    rows: list[dict[str, Any]] = []
    if _HISTORY_HEADING not in text:
        return rows
    section = text.split(_HISTORY_HEADING, 1)[1].split("\n## ", 1)[0]
    header: tuple[str, ...] | None = None
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[:2] == ["Date", "Version"]:
            header = tuple(cells[2:])  # the table names its columns
            continue
        if not _DATE.fullmatch(cells[0]):
            continue
        if header is not None and len(cells) == 2 + len(header):
            columns = header
        elif len(cells) == 2 + len(LEGACY_BUDGET_COLUMNS):
            columns = LEGACY_BUDGET_COLUMNS
        else:
            continue
        sizes = {
            column: int(cell.replace(",", ""))
            for column, cell in zip(columns, cells[2:], strict=True)
            if cell != "—"
        }
        rows.append({"date": cells[0], "version": cells[1], "sizes": sizes})
    return rows


def render_budget_markdown(history: Sequence[dict[str, Any]], measured: dict[str, Any]) -> str:
    """The whole report: the history table (``history``, oldest first; its last row is the
    current measurement) and the :data:`BUDGET_TOP` largest tools of ``measured``."""
    full = {mode: measured["sizes"][f"full {mode}"] for mode in BUDGET_MODES}

    def cells(label: str, by_mode: dict[str, int]) -> str:
        parts = [label]
        for mode in BUDGET_MODES:
            parts += [f"{by_mode[mode]:,}", f"{100 * by_mode[mode] / full[mode]:.1f} %"]
        return "| " + " | ".join(parts) + " |"

    out = [
        "# tools/list budget",
        "",
        "<!-- Generated by `python -m hocuspocus.tools.docs --budget`, which appends a dated "
        "row to the history on every run. Do not edit by hand. -->",
        "",
        "Bytes of the serialised `tools/list` result the bridge sends (compact JSON, as the "
        "MCP SDK writes it), per profile and `result_content` mode (BIBLE §4.1, spec-2.0 "
        "§5.1). `text` is what clients see by default (no output schemas); `both` declares "
        f"them. Caps on the 2.0 `full` profile (spec-2.0 §7 M3): `text` ≤ "
        f"{TOOLS_LIST_CAPS['text']:,} B, `both` ≤ {TOOLS_LIST_CAPS['both']:,} B; `compat_1x` "
        f"(1.4's `full` catalogue) keeps the 1.4 caps, `text` ≤ "
        f"{COMPAT_TOOLS_LIST_CAPS['text']:,} B, `both` ≤ {COMPAT_TOOLS_LIST_CAPS['both']:,} B. "
        "Rows before the 2.0 cut-over measure the 1.4 profiles under `minimal`, `core` and "
        "`full`, and `v2` (1.4's full plus the 2.0 tools, spec-2.0 §7 M1-M2); from the "
        "cut-over those three are the 2.0 profiles and 1.4's full is `compat_1x`. `—` marks "
        "a profile that did not exist. A change that raises a number says why in its commit.",
        "",
        _HISTORY_HEADING,
        "",
        "| Date | Version | " + " | ".join(HISTORY_COLUMNS) + " |",
        "|---|---|" + "---:|" * len(HISTORY_COLUMNS),
        *(_budget_row(row) for row in history),
        "",
        _CONTRIBUTION_HEADING,
        "",
        f"The {BUDGET_TOP} largest tools in the latest run, by the bytes of their entry in the "
        "full profile's `tools/list` (name, description, input schema and annotations, plus "
        "the output schema in `both`). Notes and examples are never in `tools/list`.",
        "",
        "| Tool | text | of full text | both | of full both |",
        "|---|---:|---:|---:|---:|",
    ]
    ranked = sorted(measured["tools"].items(), key=lambda item: (-item[1]["text"], item[0]))
    top, rest = ranked[:BUDGET_TOP], ranked[BUDGET_TOP:]
    out += [cells(f"`{name}`", by_mode) for name, by_mode in top]
    others = {mode: sum(by_mode[mode] for _, by_mode in rest) for mode in BUDGET_MODES}
    out.append(cells(f"{len(rest)} other tools", others))
    listed = {mode: sum(by_mode[mode] for by_mode in measured["tools"].values()) for mode in full}
    out.append(cells("result envelope", {mode: full[mode] - listed[mode] for mode in full}))
    return "\n".join(out) + "\n"


def default_budget_path() -> Path:
    """``docs/redesign/budget.md`` of the checkout this module lives in."""
    return Path(__file__).resolve().parents[3] / "docs" / "redesign" / "budget.md"


def update_budget_markdown(
    path: str | Path | None = None, date: str | None = None
) -> tuple[Path, dict[str, Any]]:
    """Measure, append a dated row to the history kept in ``path`` and rewrite the report.
    A run that would repeat the last row exactly (same date, version and sizes) adds none."""
    from hocuspocus.version import __version__

    target = Path(path) if path is not None else default_budget_path()
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    history = parse_budget_history(existing)
    measured = measure_budget()
    row = {
        "date": date or datetime.date.today().isoformat(),
        "version": __version__,
        "sizes": measured["sizes"],
    }
    if not history or history[-1] != row:
        history.append(row)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_budget_markdown(history, measured))
    return target, measured


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--budget"]:
        target, measured = update_budget_markdown(args[1] if len(args) > 1 else None)
        sizes = ", ".join(f"{key} {value:,} B" for key, value in measured["sizes"].items())
        print(f"wrote {target} ({sizes})")
        return 0
    target = write_tools_markdown(args[0] if args else default_output_path())
    print(f"wrote {target} ({tools_list_text_size(TOOLS)} bytes of tools/list text)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
