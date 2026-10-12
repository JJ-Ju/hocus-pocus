"""Hip file tools: ``hip_new``, ``hip_open``, ``hip_save``, ``hip_merge``.

See docs/BIBLE.md §4.3, §5 items 8–9 and §6. Nothing discards unsaved work without
``on_unsaved: "discard"``; load warnings are reported, not thrown; paths are never redacted.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from hocuspocus.tools.errors import ToolError

from .registry import HostContext, tool
from .session import scene_dirty

ON_UNSAVED = ("fail", "save", "discard")
UNSAVED_HINT = (
    "Pass on_unsaved: 'save' to save first, 'discard' to drop the changes, or call "
    "hip_save (with path for an untitled scene) first."
)
MERGED_LIST_LIMIT = 200


# -- helpers --------------------------------------------------------------------


def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


def resolve_path(raw: Any, *, field: str = "path") -> str:
    """Expand ``$HIP``-style variables and ``~`` and return an absolute forward-slash path."""
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("invalid_argument", f"'{field}' must be a non-empty string.")
    import hou

    expanded = hou.text.expandString(raw.strip())
    return _norm(os.path.expanduser(expanded))


def _real(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def expand_root(root: str) -> str:
    """An ``approved_roots`` entry with ``$VAR``/``${VAR}`` and ``~`` expanded. An unknown
    variable stays literal, so the root then matches nothing rather than widening."""
    return os.path.expanduser(os.path.expandvars(root))


def is_under(path: str, root: str) -> bool:
    """``path`` is ``root`` or inside it, comparing real paths (links resolved) on both
    sides, so a link inside a root cannot point out of it."""
    path_n = _real(path)
    root_n = _real(expand_root(root))
    try:
        return os.path.commonpath([path_n, root_n]) == root_n
    except ValueError:  # different drives on Windows
        return False


def check_allowed(path: str, ctx: HostContext) -> None:
    roots = [r for r in (ctx.config.approved_roots or []) if r]
    if not roots:
        return
    if any(is_under(path, root) for root in roots):
        return
    shown = [_norm(expand_root(r)) for r in roots]
    raise ToolError(
        "path_not_allowed",
        f"{path} is outside the approved roots.",
        hint="Allowed roots: " + ", ".join(shown),
        detail={"approved_roots": shown},
    )


def _backup_dir() -> str:
    """Where ``hou.hipFile.saveAndBackup`` writes: ``$HOUDINI_BACKUP_DIR`` (relative to
    the hip's directory when relative), else ``backup`` next to the hip file."""
    import hou

    hip_dir = os.path.dirname(hou.hipFile.path())
    raw = hou.getenv("HOUDINI_BACKUP_DIR") or ""
    target = hou.text.expandString(raw) if raw else ""
    if not target:
        target = "backup"
    if not os.path.isabs(target):
        target = os.path.join(hip_dir, target)
    return _norm(target)


def require_file(path: str) -> None:
    if os.path.isfile(path):
        return
    parent = os.path.dirname(path)
    candidates: list[str] = []
    if os.path.isdir(parent):
        names = [n for n in os.listdir(parent) if n.lower().endswith((".hip", ".hiplc", ".hipnc"))]
        candidates = [
            f"{parent}/{n}"
            for n in difflib.get_close_matches(os.path.basename(path), names, n=5, cutoff=0.5)
        ]
        hint = "Check the file name." if candidates else f"No similar hip files in {parent}."
    else:
        hint = f"The directory {parent} does not exist."
    raise ToolError("file_not_found", f"No file at {path}.", hint=hint, candidates=candidates)


def parse_load_warnings(text: str) -> list[str]:
    """Turn ``hou.LoadWarning`` text into one string per warning, with node context."""
    warnings: list[str] = []
    context = ""
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("error loading:"):
            continue
        if line.startswith("/") and line.endswith(":"):
            context = line[:-1]
            continue
        for prefix in ("Warning:", "Error:", "Message:"):
            if line.startswith(prefix):
                line = line[len(prefix) :].strip()
                break
        if not line:
            continue
        warnings.append(f"{context}: {line}" if context else line)
    return warnings


def _load_message(exc: BaseException) -> str:
    getter = getattr(exc, "instanceMessage", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    return str(exc)


def handle_unsaved(on_unsaved: Any, ctx: HostContext, action: str) -> bool:
    """Apply the ``on_unsaved`` policy. Returns True when it saved the scene."""
    if on_unsaved is None:
        on_unsaved = "fail"
    if on_unsaved not in ON_UNSAVED:
        raise ToolError(
            "invalid_argument",
            f"on_unsaved must be one of {', '.join(ON_UNSAVED)}; got {on_unsaved!r}.",
        )
    if not scene_dirty(ctx) or on_unsaved == "discard":
        return False
    import hou

    if on_unsaved == "fail":
        raise ToolError(
            "unsaved_changes",
            f"The scene {hou.hipFile.path()} has unsaved changes; refusing to {action}.",
            hint=UNSAVED_HINT,
        )
    if hou.hipFile.isNewFile():
        raise ToolError(
            "unsaved_changes",
            "The scene is untitled, so on_unsaved: 'save' has nowhere to save it.",
            hint="Use hip_save with path first, or on_unsaved: 'discard'.",
        )
    check_allowed(_norm(hou.hipFile.path()), ctx)
    hou.hipFile.save()
    return True


def _scene_result(ctx: HostContext) -> dict[str, Any]:
    import hou

    return {
        "path": hou.hipFile.path(),
        "name": hou.hipFile.basename(),
        "dirty": scene_dirty(ctx),
        "is_new": bool(hou.hipFile.isNewFile()),
        "scene_generation": ctx.scene.generation,
    }


def _bool_arg(args: dict[str, Any], key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError("invalid_argument", f"'{key}' must be a boolean.")
    return value


# -- tools ----------------------------------------------------------------------


@tool("hip_new")
def hip_new(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    saved = handle_unsaved(args.get("on_unsaved"), ctx, "clear it")
    hou.hipFile.clear(suppress_save_prompt=True)
    result = _scene_result(ctx)
    result["saved_first"] = saved
    return result


@tool("hip_open")
def hip_open(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    path = resolve_path(args.get("path"))
    ignore_warnings = _bool_arg(args, "ignore_load_warnings", True)
    check_allowed(path, ctx)
    require_file(path)
    saved = handle_unsaved(args.get("on_unsaved"), ctx, f"open {path}")
    warnings: list[str] = []
    try:
        # Never pass ignore_load_warnings=True to Houdini: it would swallow the warnings
        # we report. LoadWarning is raised after the scene has loaded.
        hou.hipFile.load(path, suppress_save_prompt=True, ignore_load_warnings=False)
    except hou.LoadWarning as exc:
        warnings = parse_load_warnings(_load_message(exc)) or [_load_message(exc).strip()]
    except hou.OperationFailed as exc:
        raise ToolError(
            "invalid_value",
            f"Houdini could not load {path}.",
            hint="The file may be corrupt, from a newer Houdini, or not a hip file.",
            hou_exception=f"hou.OperationFailed: {_load_message(exc).strip()}",
        ) from exc
    result = _scene_result(ctx)
    result["warnings"] = warnings
    result["saved_first"] = saved
    if warnings and not ignore_warnings:
        raise ToolError(
            "invalid_value",
            f"{path} loaded with {len(warnings)} warning(s) and ignore_load_warnings is false.",
            hint="The scene IS loaded; inspect it, or pass ignore_load_warnings: true to treat warnings as reports.",
            detail=result,
        )
    return result


@tool("hip_save")
def hip_save(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    increment = _bool_arg(args, "increment", False)
    backup = _bool_arg(args, "backup", False)
    raw_path = args.get("path")
    if increment and backup:
        raise ToolError("invalid_argument", "Pass at most one of increment and backup.")
    if raw_path is not None and (increment or backup):
        raise ToolError(
            "invalid_argument",
            "path cannot be combined with increment or backup.",
            hint="Save as with path first, then call hip_save with increment or backup.",
        )
    backup_path: str | None = None
    if raw_path is not None:
        path = resolve_path(raw_path)
        check_allowed(path, ctx)
        if os.path.isdir(path):
            raise ToolError("invalid_argument", f"{path} is a directory; pass a file path.")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        hou.hipFile.save(file_name=path)
    else:
        if hou.hipFile.isNewFile():
            raise ToolError(
                "invalid_argument",
                "The scene is untitled; there is no file to save to.",
                hint="Use hip_save with path.",
            )
        check_allowed(_norm(hou.hipFile.path()), ctx)
        if increment:
            # The incremented file goes next to the current one, checked above.
            hou.hipFile.saveAndIncrementFileName()
        elif backup:
            # Check the backup directory before anything is written.
            check_allowed(_backup_dir() + "/" + os.path.basename(hou.hipFile.path()), ctx)
            made = hou.hipFile.saveAndBackup()
            backup_path = _norm(made) if made else None
        else:
            hou.hipFile.save()
    saved_path = hou.hipFile.path()
    result = _scene_result(ctx)
    try:
        result["bytes"] = os.path.getsize(saved_path)
    except OSError:
        result["bytes"] = None
    if backup_path:
        result["backup_path"] = backup_path
    return result


@tool("hip_merge")
def hip_merge(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    import hou

    path = resolve_path(args.get("path"))
    pattern = args.get("node_pattern", "*")
    if not isinstance(pattern, str) or not pattern:
        raise ToolError("invalid_argument", "'node_pattern' must be a non-empty string.")
    overwrite = _bool_arg(args, "overwrite_on_conflict", False)
    dry_run = _bool_arg(args, "dry_run", False)
    check_allowed(path, ctx)
    require_file(path)
    collisions = [node.path() for node in hou.hipFile.collisionNodesIfMerged(path, pattern)]
    if dry_run:
        # _changed: false tells the dispatcher this call changed nothing: no undo label,
        # no dirty flag, and it is allowed in read-only mode.
        return {
            "path": path,
            "dry_run": True,
            "collisions": collisions,
            "scene_generation": ctx.scene.generation,
            "_changed": False,
        }
    before = {node.path() for node in hou.node("/").allSubChildren(recurse_in_locked_nodes=False)}
    warnings: list[str] = []
    try:
        hou.hipFile.merge(
            path, node_pattern=pattern, overwrite_on_conflict=overwrite, ignore_load_warnings=False
        )
    except hou.LoadWarning as exc:
        warnings = parse_load_warnings(_load_message(exc)) or [_load_message(exc).strip()]
    except hou.OperationFailed as exc:
        raise ToolError(
            "invalid_value",
            f"Houdini could not merge {path}.",
            hou_exception=f"hou.OperationFailed: {_load_message(exc).strip()}",
        ) from exc
    after = [node.path() for node in hou.node("/").allSubChildren(recurse_in_locked_nodes=False)]
    created = [p for p in after if p not in before]
    created_set = set(created)
    # Report only top-most new nodes (children of new networks are implied).
    top = [p for p in created if p.rsplit("/", 1)[0] not in created_set]
    result: dict[str, Any] = {
        "path": path,
        "dry_run": False,
        "merged": top[:MERGED_LIST_LIMIT],
        "merged_count": len(top),
        "collisions": collisions,
        "overwrote": collisions if overwrite else [],
        "warnings": warnings,
        "scene_generation": ctx.scene.generation,
    }
    if len(top) > MERGED_LIST_LIMIT:
        result["truncated"] = True
    return result
