"""Node type discovery: ``node_type_search`` and ``node_type_info``.

See docs/BIBLE.md §4.7 and §5 items 4 and 15. The search index covers all 18 node type
categories, is built lazily on the first call (tens of milliseconds) and is cached for
the process; it is rebuilt when an HDA library is installed or removed, or when the
number of node types changes. Descriptions and tags come from the help headers in
``$HFS/houdini/help/nodes.zip`` (``embeddedHelp()`` is empty for built-in types).

Other tool families use :func:`resolve_type` (createNode-style resolution) and
:func:`suggest_types` (candidates for ``node_type_not_found``).
"""

from __future__ import annotations

import contextlib
import difflib
import functools
import json
import os
import re
import threading
import time
import zipfile
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.budget import clip, utf8_head
from hocuspocus.tools.catalog import CATEGORIES
from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.migration import hint_tool

from ._common import arg_bool, dynamic_menu_note, int_arg, menu_is_dynamic
from .parms import menu_label
from .registry import HostContext

# -- help archive -----------------------------------------------------------------

HELP_DIRS = {
    "Sop": "sop", "Object": "obj", "Driver": "out", "Cop": "cop", "Cop2": "cop2",
    "Chop": "chop", "Dop": "dop", "Lop": "lop", "Shop": "shop", "Top": "top", "Vop": "vop",
    "Manager": "manager", "Data": "apex", "ChopNet": "chopnet", "CopNet": "copnet",
    "TopNet": "topnet", "VopNet": "vopnet", "Director": "director",
}  # fmt: skip
"""Category name → directory inside nodes.zip."""

HELP_HEAD_BYTES = 1500
HELP_TEXT_CHARS = 2000
DESCRIPTION_CHARS = 120
"""Search rows clip descriptions here (review 11 B6); node_type_info keeps them whole."""


class _HelpArchive:
    """Lazily opened ``nodes.zip``; reads are serialised (ZipFile is not thread-safe)."""

    def __init__(self) -> None:
        self._zip: zipfile.ZipFile | None = None
        self._names: frozenset[str] = frozenset()
        self._opened = False
        self._lock = threading.Lock()
        self.path: str | None = None

    def _open(self) -> None:
        if self._opened:
            return
        self._opened = True
        try:
            import hou

            hfs = hou.text.expandString("$HFS")
        except Exception:
            hfs = os.environ.get("HFS", "")
        path = os.path.join(hfs, "houdini", "help", "nodes.zip") if hfs else ""
        if path and os.path.isfile(path):
            try:
                self._zip = zipfile.ZipFile(path)
                self._names = frozenset(self._zip.namelist())
                self.path = path.replace("\\", "/")
            except (OSError, zipfile.BadZipFile):
                self._zip = None

    def has(self, entry: str) -> bool:
        with self._lock:
            self._open()
            return entry in self._names

    def read(self, entry: str, limit: int | None = None) -> str | None:
        with self._lock:
            self._open()
            if self._zip is None or entry not in self._names:
                return None
            try:
                with self._zip.open(entry) as handle:
                    data = handle.read(limit) if limit else handle.read()
            except (OSError, zipfile.BadZipFile, KeyError):
                return None
        # A head read can stop inside a character: drop it rather than decode it as U+FFFD.
        return utf8_head(data) if limit else data.decode("utf-8", "replace")


_HELP = _HelpArchive()


def help_entry(category: str, components: tuple[str, ...]) -> str | None:
    """The nodes.zip entry documenting a type, e.g. ``sop/scatter.txt``.

    The plain file documents the current version; older versions live in
    ``<name>-<version>.txt`` (``scatter-.txt`` is the unversioned ``scatter``).
    Namespaces map ``::`` to ``--`` (``kinefx--motionclip.txt``).
    """
    _scope, namespace, base, version = (tuple(components) + ("", "", "", ""))[:4]
    folder = HELP_DIRS.get(category, category.lower())
    stem = f"{namespace}--{base}" if namespace else base
    for entry in (f"{folder}/{stem}-{version}.txt", f"{folder}/{stem}.txt"):
        if _HELP.has(entry):
            return entry
    return None


_SUMMARY_RE = re.compile(r'"""(.*?)"""', re.S)


def parse_help_header(text: str) -> dict[str, Any]:
    """``{summary, tags, bestbet, version}`` from the head of a help file."""
    out: dict[str, Any] = {"summary": "", "tags": [], "bestbet": [], "version": ""}
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#tags:"):
            out["tags"] = [t.strip().lower() for t in stripped[6:].split(",") if t.strip()]
        elif stripped.startswith("#bestbet:"):
            out["bestbet"] = [t.strip().lower() for t in stripped[9:].split(",") if t.strip()]
        elif stripped.startswith("#version:"):
            out["version"] = stripped[9:].strip()
    match = _SUMMARY_RE.search(text)
    if match:
        out["summary"] = " ".join(match.group(1).split())
    return out


_LINK_RE = re.compile(r"\[([^\]|\[]+)\|[^\]]+\]")
_BARE_LINK_RE = re.compile(r"\[(?:Node|Hom|Vex|Exp|Cmd):([^\]]+)\]", re.I)
_PATH_LINK_RE = re.compile(r"\[(/[^\]]+)\]")
_HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*=+\s*(\([^)]*\))?\s*$")


def help_to_text(raw: str, limit: int = HELP_TEXT_CHARS) -> tuple[str, bool]:
    """Strip Houdini wiki markup lightly and cap the text. Returns ``(text, truncated)``."""
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") and ":" in stripped.split()[0]:
            continue  # #type:, #tags:, #id: metadata
        if stripped.startswith((":include", ":load_example:", ":video:", "<!--")):
            continue
        if stripped.startswith(":") and ":" in stripped[1:]:
            stripped = stripped[1:].split(":", 1)[1].strip()  # :task: Title -> Title
            line = stripped
        heading = _HEADING_RE.match(stripped)
        if heading:
            lines.append("")
            lines.append(heading.group(2))
            continue
        if stripped.startswith("@"):
            lines.append("")
            lines.append(stripped[1:].replace("_", " ").title())
            continue
        if stripped.startswith('"""') or stripped.endswith('"""'):
            line = line.replace('"""', "")
        line = _LINK_RE.sub(r"\1", line)
        line = _BARE_LINK_RE.sub(lambda m: m.group(1).rsplit("/", 1)[-1], line)
        line = _PATH_LINK_RE.sub(lambda m: m.group(1).rsplit("/", 1)[-1], line)
        line = line.replace("'''", "").replace("''", "").replace("__", "")
        line = line.strip()
        if line.startswith("# "):
            line = "- " + line[2:]
        lines.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(text) <= limit:
        return text, False
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = limit
    return text[:cut].rstrip() + "\n…", True


def parse_parm_help(raw: str) -> dict[str, str]:
    """Map parm label (lower case) → first sentence of its description in ``@parameters``."""
    out: dict[str, str] = {}
    in_parms = False
    label: str | None = None
    label_indent = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("@"):
            in_parms = stripped.lower().startswith("@parameters")
            label = None
            continue
        if not in_parms:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.endswith(":") and not stripped.startswith(("#", ":", "NOTE", "TIP")):
            label = stripped[:-1].strip().lower()
            label_indent = indent
            continue
        if label and indent > label_indent and label not in out and not stripped.startswith("#"):
            text = _LINK_RE.sub(r"\1", stripped)
            text = _BARE_LINK_RE.sub(lambda m: m.group(1).rsplit("/", 1)[-1], text)
            sentence = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
            out[label] = sentence[:160]
    return out


# -- index --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return [_stem(w) for w in _WORD_RE.findall(text.lower())]


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _compact(text: str) -> str:
    return "".join(_WORD_RE.findall(text.lower()))


class _Index:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] | None = None
        self.type_count = -1
        self.dirty = True
        self.callback_installed = False
        self.callback_ok = False
        self.build_ms = 0.0
        self.builds = 0
        self.lock = threading.Lock()


_INDEX = _Index()


def _on_hda_event(**_kwargs: Any) -> None:
    _INDEX.dirty = True


def _install_hda_callback() -> bool:
    """Install the HDA event callback once. Returns whether it is in place."""
    if _INDEX.callback_installed:
        return _INDEX.callback_ok
    _INDEX.callback_installed = True
    try:
        import hou

        events = tuple(
            getattr(hou.hdaEventType, name)
            for name in ("LibraryInstalled", "LibraryUninstalled", "AssetCreated", "AssetDeleted")
            if hasattr(hou.hdaEventType, name)
        )
        hou.hda.addEventCallback(events, _on_hda_event)
        _INDEX.callback_ok = True
    except Exception:
        _INDEX.callback_ok = False  # fall back to counting types on every call
    return _INDEX.callback_ok


def _type_count() -> int:
    import hou

    return sum(len(cat.nodeTypes()) for cat in hou.nodeTypeCategories().values())


def _build_rows() -> list[dict[str, Any]]:
    import hou

    rows: list[dict[str, Any]] = []
    for cat_name, category in hou.nodeTypeCategories().items():
        for name, node_type in category.nodeTypes().items():
            try:
                scope, namespace, base, version = node_type.nameComponents()
                label = node_type.description()
                order = node_type.namespaceOrder()
                row: dict[str, Any] = {
                    "name": name,
                    "label": label,
                    "category": cat_name,
                    "version": version,
                    "is_current_version": not order or order[0] == name,
                    "min_inputs": node_type.minNumInputs(),
                    "max_inputs": node_type.maxNumInputs(),
                    "hidden": bool(node_type.hidden()) or bool(scope),
                    "deprecated": bool(node_type.deprecated()),
                    "current": order[0] if order else name,
                    "_order": tuple(order),
                }
            except Exception:
                continue
            entry = help_entry(cat_name, (scope, namespace, base, version))
            header = parse_help_header(_HELP.read(entry, HELP_HEAD_BYTES) or "") if entry else None
            row["description"] = header["summary"] if header else ""
            if not version or not row["description"]:
                asset = asset_fields(node_type)
                row["version"] = version or asset.get("version", "")
                row["description"] = row["description"] or asset.get("description", "")
            row["_help"] = entry
            row["_base"] = base.lower()
            row["_basec"] = _compact(base)
            row["_name"] = name.lower()
            row["_label"] = label.lower().strip()
            row["_labelc"] = _compact(label)
            row["_labelw"] = _words(label)
            row["_descw"] = set(_words(row["description"]))
            row["_tags"] = set(header["tags"]) if header else set()
            row["_tagw"] = {w for t in row["_tags"] for w in _words(t)}
            row["_bestbet"] = set(header["bestbet"]) if header else set()
            with contextlib.suppress(Exception):
                child = node_type.childTypeCategory()
                if child is not None:
                    row["child_category"] = child.name()
            if cat_name in MENU_LABEL_CATEGORIES:
                labels = _menu_labels(node_type)
                row["_menul"] = {label.lower() for label in labels}
                row["_menuw"] = {w for label in labels for w in _words(label)}
            rows.append(row)
    return rows


MENU_LABEL_CATEGORIES = frozenset({"Cop"})
"""Categories whose types are also found by the labels of their menus: Copernicus names
its verbs as modes (remap's Threshold, blend's Over; review 18 papercut 5)."""


def _menu_labels(node_type: Any) -> list[str]:
    """Labels of the menus at the top level and one folder down (icon markup stripped)."""
    import hou

    labels: list[str] = []
    folders = (hou.parmTemplateType.Folder, hou.parmTemplateType.FolderSet)

    def visit(templates: Any, depth: int) -> None:
        for template in templates:
            kind = template.type()
            if kind in folders:
                if depth < 1:
                    visit(template.parmTemplates(), depth + 1)
            elif kind == hou.parmTemplateType.Menu:
                with contextlib.suppress(Exception):
                    labels.extend(menu_label(label) for label in template.menuLabels())

    with contextlib.suppress(Exception):
        visit(node_type.parmTemplateGroup().entries(), 0)
    return labels


def type_path(node_type: Any) -> str:
    """``Category/name``. ``nameWithCategory()`` puts a namespace in front of the
    category (``hp::Sop/meteors``), unlike every other type string the tools use."""
    return f"{node_type.category().name()}/{node_type.name()}"


@functools.cache
def _hfs_prefixes() -> tuple[str, ...]:
    hfs = os.environ.get("HFS")
    if not hfs:
        return ()
    forms = {hfs, os.path.realpath(hfs)}
    return tuple(os.path.normcase(os.path.normpath(f)) + os.sep for f in forms)


def asset_fields(node_type: Any) -> dict[str, str]:
    """A digital asset's version and description where its name and help have none:
    ``hda create {version}`` stores the version on the definition, not in the type name,
    and the label is what Houdini calls the asset's description."""
    try:
        definition = node_type.definition()
    except Exception:
        definition = None
    if definition is None:
        return {}
    out: dict[str, str] = {}
    try:
        if definition.version():
            out["version"] = str(definition.version())
        library = os.path.normcase(os.path.normpath(definition.libraryFilePath() or ""))
        builtin = any(library.startswith(prefix) for prefix in _hfs_prefixes())
        # Houdini's own assets keep "" rather than repeat their label.
        description = definition.comment() or ("" if builtin else definition.description())
        if description:
            out["description"] = str(description)
    except Exception:
        pass
    return out


def get_index() -> list[dict[str, Any]]:
    """The cached type index (main thread). Rebuilt when HDA libraries change."""
    with _INDEX.lock:
        # The HDA event callback sets the dirty flag; counting every type of every
        # category on each call is only the fallback when the callback is missing.
        count = _INDEX.type_count if _install_hda_callback() else _type_count()
        if _INDEX.rows is None or _INDEX.dirty or count != _INDEX.type_count:
            started = time.perf_counter()
            _INDEX.rows = _build_rows()
            _INDEX.type_count = count
            _INDEX.dirty = False
            _INDEX.build_ms = round((time.perf_counter() - started) * 1000, 1)
            _INDEX.builds += 1
        return _INDEX.rows


# -- ranking --------------------------------------------------------------------------

CATEGORY_RANK = {
    name: i
    for i, name in enumerate(
        ("Sop", "Lop", "Object", "Dop", "Vop", "Cop", "Top", "Driver", "Chop", "Cop2", "Shop")
    )
}


STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "on",
        "onto",
        "of",
        "to",
        "in",
        "into",
        "for",
        "with",
        "by",
        "from",
        "and",
        "or",
        "at",
        "as",
        "its",
        "it",
        "is",
        "are",
        "be",
        "some",
        "all",
        "each",
        "every",
        "my",
        "this",
        "that",
    ]
)
"""Words a plain-language query carries that say nothing about the node type."""

TOKEN_WEIGHTS = {
    "name": 4.0, "label": 3.0, "in_name": 2.0, "menu": 2.0, "tag": 1.5, "description": 1.0,
}  # fmt: skip

SYNONYMS = {
    "surface": ("geometry", "mesh", "polygon", "point"),
    "mesh": ("geometry", "polygon", "surface"),
    "geometry": ("mesh", "polygon", "surface"),
    "object": ("geometry",),
    "transform": ("xform",),
    "move": ("transform", "xform", "translate"),
    "image": ("texture", "picture"),
    "particle": ("point",),
}
"""Houdini wording for words agents use; a synonym hit counts half."""


def _token_weight(row: dict[str, Any], word: str) -> float:
    """How strongly one query word points at ``row``: the type name or a whole word of
    the label outranks a keyword, which outranks a word of the description."""
    if word in (row["_basec"], _stem(row["_basec"])):
        return TOKEN_WEIGHTS["name"]
    if word in row["_labelw"]:
        return TOKEN_WEIGHTS["label"]
    if len(word) >= 4 and word in row["_basec"]:
        return TOKEN_WEIGHTS["in_name"]
    if word in row.get("_menuw", ()):
        return TOKEN_WEIGHTS["menu"]
    if word in row["_tagw"] or word in row["_tags"] or word in row["_bestbet"]:
        return TOKEN_WEIGHTS["tag"]
    if word in row["_descw"]:
        return TOKEN_WEIGHTS["description"]
    return 0.0


def _token_score(row: dict[str, Any], qwords: list[str]) -> float:
    """Score a multi-word, plain-language query ("scatter points on a surface") word by
    word, ignoring stop words. 0 when fewer than half the words match."""
    words = [w for w in qwords if w not in STOP_WORDS] or qwords
    weights = [
        _token_weight(row, w)
        or 0.5 * max((_token_weight(row, s) for s in SYNONYMS.get(w, ())), default=0.0)
        for w in words
    ]
    hits = sum(1 for w in weights if w)
    if not hits or hits * 2 < len(words):
        return 0.0
    strength = sum(weights) / (TOKEN_WEIGHTS["name"] * len(words))
    if hits == len(words):
        return 20 + 25 * strength
    return 5 + 20 * strength * hits / len(words)


def score_row(row: dict[str, Any], query: str) -> float:
    """Rank one index row against ``query`` (bible §4.7). 0 means no match."""
    q = " ".join(query.lower().split())
    qc = _compact(q)
    qwords = _words(q)
    if not qc:
        return 0.0
    base, label = row["_base"], row["_label"]
    score = 0.0
    if q in (row["_name"], base) or qc in (row["_basec"], _compact(row["_name"])):
        score = 100
    elif q == label:
        score = 95
    elif qc == row["_labelc"]:
        score = 94
    elif q in row["_bestbet"]:
        score = 90
    elif row["_basec"].startswith(qc):
        score = max(70.0, 85 - (len(row["_basec"]) - len(qc)))
    elif label.startswith(q) or row["_labelc"].startswith(qc):
        score = max(65.0, 80 - (len(row["_labelc"]) - len(qc)))
    else:
        labelw = row["_labelw"]
        if qwords and all(w in labelw for w in qwords):
            score = 70
        elif qwords and all(any(lw.startswith(w) for lw in labelw) for w in qwords):
            score = 62
        elif len(qc) >= 3 and qc in row["_basec"]:
            score = 55
        elif len(q) >= 3 and q in label:
            score = 50
        elif q in row.get("_menul", ()):
            score = 60  # a mode menu item: remap's "Threshold", blend's "Over"
        elif qwords:
            score = _token_score(row, qwords)
    if not score:
        return 0.0
    if row["deprecated"]:
        score -= 40
    if row["hidden"]:
        score -= 30
    if not row["is_current_version"]:
        score -= 15
    return max(score, 1.0)


COP_SYNONYMS = {
    "threshold": ("remap",),
    "step": ("remap",),
    "gradient": ("ramp",),
    "composite": ("blend",),
    "comp": ("blend",),
    "over": ("blend",),
    "merge": ("blend",),
    "text": ("font",),
    "title": ("font",),
    "write": ("rop_image",),
    "save": ("rop_image",),
    "output": ("rop_image",),
}
"""Compositing words → the Copernicus type that does it (review 18 papercut 5: threshold
and gradient found nothing, composite found zcomp)."""
SYNONYM_SCORE = 88
COP2_NOTE = (
    "Cop2 is the legacy compositor (COP Network - Old); Houdini 22's Copernicus nodes are "
    "category Cop."
)
TYPICAL_PARENTS = {
    "Object": ["/obj"],
    "Driver": ["/out"],
    "CopNet": ["/img"],
    "Lop": ["/stage", "a LOP network"],
    "Sop": ["a geo object such as /obj/geo1"],
    "Top": ["/tasks", "a TOP network"],
    "TopNet": ["/tasks"],
    "Chop": ["/ch", "a CHOP network"],
    "ChopNet": ["/ch"],
    "Dop": ["a DOP network"],
    "Cop": ["a COP network"],
    "Vop": ["a VOP network or material builder"],
    "VopNet": ["/mat"],
    "Shop": ["/shop"],
}
"""Where a container type is created, by its own category (review 18 papercut 6)."""


def _synonym_targets(query: str, category: str | None) -> set[str]:
    if category not in (None, "Cop"):
        return set()
    return set(COP_SYNONYMS.get(" ".join(query.lower().split()), ()))


def public_row(row: dict[str, Any], *, fold_versions: bool = False) -> dict[str, Any]:
    """The search row an agent sees. With ``fold_versions`` a current row names the
    type's other versions (``other_versions``) instead of listing them as rows."""
    out: dict[str, Any] = {
        "name": row["name"],
        "label": row["label"],
        "category": row["category"],
        "version": row["version"],
        "is_current_version": row["is_current_version"],
        "description": _clip(row["description"], DESCRIPTION_CHARS),
        "inputs": {"min": row["min_inputs"], "max": row["max_inputs"]},
        "deprecated": row["deprecated"],
    }
    if not row["is_current_version"]:
        out["current"] = row["current"]
    elif fold_versions:
        others = [name for name in row["_order"] if name != row["name"]]
        if others:
            out["other_versions"] = others
    if row["hidden"]:
        out["hidden"] = True
    if row.get("child_category"):
        out["child_category"] = row["child_category"]
        out["typical_parents"] = TYPICAL_PARENTS.get(row["category"], [])
    return out


def shared_fields(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    """Hoist ``keys`` out of ``rows`` when at least two rows carry them and every row has
    the same values (review 23 papercut 6: 37 Vellum rows repeated ``child_category`` and
    ``typical_parents``, 4.4 KB). Returns the hoisted fields; ``rows`` lose them."""
    if len(rows) < 2 or any(key not in row for row in rows for key in keys):
        return {}
    first = {key: rows[0][key] for key in keys}
    if any(row[key] != first[key] for row in rows for key in keys):
        return {}
    for row in rows:
        for key in keys:
            del row[key]
    return first


def _clip(text: str, limit: int) -> str:
    return clip(text, limit)


def search(
    query: str,
    category: str | None = None,
    limit: int = 20,
    include_hidden: bool = False,
    current_only: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Ranked index rows (main thread). Returns ``(rows, total_matches)``.

    ``current_only`` folds every version of a type into its current version's row,
    ranked by the best-scoring version (an old version's label can be the one that
    matches).
    """
    rows = get_index()
    current: dict[tuple[str, str], dict[str, Any]] = {}
    if current_only:
        current = {(r["category"], r["name"]): r for r in rows if r["is_current_version"]}
    best: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
    synonyms = _synonym_targets(query, category)
    for row in rows:
        if category and row["category"] != category:
            continue
        if row["hidden"] and not include_hidden:
            continue
        score = score_row(row, query)
        if synonyms and row["category"] == "Cop" and row["_base"] in synonyms:
            score = max(score, SYNONYM_SCORE if row["is_current_version"] else 1.0)
        if score <= 0:
            continue
        key = (row["category"], row["name"])
        if current_only and not row["is_current_version"]:
            head = current.get((row["category"], row["current"]))
            if head is not None and (include_hidden or not head["hidden"]):
                key, row = (head["category"], head["name"]), head
        if key not in best or score > best[key][0]:
            best[key] = (score, row)
    scored = [
        (-score, CATEGORY_RANK.get(row["category"], len(CATEGORY_RANK)), len(row["name"]),
         row["name"], row)
        for score, row in best.values()
    ]  # fmt: skip
    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored[:limit]], len(scored)


def suggest_types(query: str, category: str | None = None, limit: int = 5) -> list[str]:
    """``Category/name`` candidates for a type name that did not resolve (main thread).

    Known other names come first (``distantlight`` is ``hlight`` in /obj, through
    ``nodes.type_synonym``), then ranked search rows; a query nothing matches falls back
    to ``nodes.type_candidates`` (close names and labels) or close index keys.
    """
    import hou

    from .nodes import type_candidates, type_synonym

    categories = hou.nodeTypeCategories()
    scope = [category] if category else list(categories)
    named: list[str] = []
    for cat_name in scope:
        cat = categories.get(cat_name)
        synonym = type_synonym(cat, query) if cat is not None else None
        if synonym is not None:
            named.append(synonym[0] if category else f"{cat_name}/{synonym[0]}")
    rows, _ = search(query, category, limit, current_only=True)
    extra: list[str] = []
    if not rows:
        # Typos ("scater"): fall back to close matches on base names and labels.
        pool = [
            row
            for row in get_index()
            if (not category or row["category"] == category) and not row["hidden"]
        ]
        keys = {}
        for row in pool:
            for key in (row["_base"], row["_label"]):
                keys.setdefault(key, []).append(row)
        close = difflib.get_close_matches(query.lower().strip(), list(keys), n=limit, cutoff=0.6)
        seen: set[int] = set()
        for key in close:
            for row in sorted(keys[key], key=lambda r: not r["is_current_version"]):
                if id(row) not in seen:
                    seen.add(id(row))
                    rows.append(row)
        rows = rows[:limit]
        if category and categories.get(category) is not None:
            # Labels inside the query ("spot_light" -> Light), as node_create suggests.
            extra = type_candidates(categories[category], query, limit)
    found = [row["name"] if category else f"{row['category']}/{row['name']}" for row in rows]
    return list(dict.fromkeys([*named, *found, *extra]))[:limit]


# -- resolution -----------------------------------------------------------------------


def _category(name: str) -> Any:
    import hou

    categories = hou.nodeTypeCategories()
    if name in categories:
        return categories[name]
    for key, value in categories.items():
        if key.lower() == name.lower():
            return value
    raise ToolError(
        "invalid_argument",
        f"Unknown node type category {name!r}.",
        candidates=list(CATEGORIES),
    )


def resolve_type(type_name: str, category: str | None = None) -> Any:
    """Resolve ``Sop/scatter``, ``scatter`` + category, or a bare name like ``createNode``.

    Bare names resolve through the namespace order (``scatter`` → ``scatter::2.0``); an
    explicit version (``scatter::2.0``) is kept. Raises ``node_type_not_found`` with
    candidates, or ``invalid_argument`` when a bare name exists in several categories.
    """
    import hou

    if not isinstance(type_name, str) or not type_name.strip():
        raise ToolError("invalid_argument", "'type' must be a non-empty string.")
    raw = type_name.strip()
    cat_name = category
    name = raw
    if "/" in raw:
        prefix, rest = raw.split("/", 1)
        if prefix.lower() in {c.lower() for c in CATEGORIES}:
            cat_name, name = prefix, rest
    if cat_name:
        cat = _category(cat_name)
        node_type = _preferred(cat, name)
        if node_type is None:
            raise ToolError(
                "node_type_not_found",
                f"No {cat.name()} node type named {name!r}.",
                hint=f"{hint_tool('node_type_search', query=name, category=cat.name())} finds "
                "the type by name or label.",
                candidates=suggest_types(name, cat.name()),
            )
        return node_type
    found = []
    for cat in hou.nodeTypeCategories().values():
        node_type = _preferred(cat, name)
        if node_type is not None:
            found.append(node_type)
    if len(found) == 1:
        return found[0]
    if not found:
        raise ToolError(
            "node_type_not_found",
            f"No node type named {name!r} in any category.",
            hint=f"{hint_tool('node_type_search', query=name)} finds the type by name or label.",
            candidates=suggest_types(name),
        )
    found.sort(key=lambda t: CATEGORY_RANK.get(t.category().name(), 99))
    names = [type_path(t) for t in found]
    raise ToolError(
        "invalid_argument",
        f"{name!r} exists in several categories: {', '.join(names)}.",
        hint="Pass category, or a category/name type such as " + names[0] + ".",
        candidates=names,
    )


def _preferred(category: Any, name: str) -> Any:
    import hou

    types = category.nodeTypes()
    if name not in types:
        lowered = {k.lower(): k for k in types}
        if name.lower() not in lowered:
            return None
        name = lowered[name.lower()]
    if "::" in name and types[name].nameComponents()[3]:
        return types[name]  # an explicit version stays exact
    try:
        preferred = hou.preferredNodeType(f"{category.name()}/{name}")
    except Exception:
        preferred = None
    return preferred if preferred is not None else types[name]


# -- inputs from a temporary instance -------------------------------------------------

_ROOTS = ("/obj", "/out", "/stage", "/mat", "/shop", "/tasks", "/ch", "/img")
_CONTAINERS = {
    "Sop": ("/obj", "geo"),
    "Dop": ("/obj", "dopnet"),
    "Chop": ("/obj", "chopnet"),
    "Top": ("/obj", "topnet"),
    "Cop": ("/obj", "copnet"),
    "Cop2": ("/img", "img"),
    "VopNet": ("/obj", "vopnet"),
}
_IO_CACHE: dict[str, dict[str, Any]] = {}
TMP_NAME = "__hocuspocus_type_probe__"


def _probe_parent(cat_name: str) -> tuple[Any, Any]:
    """``(parent_to_create_in, node_to_destroy_after_or_None)``."""
    import hou

    for root_path in _ROOTS:
        root = hou.node(root_path)
        if root is not None and root.childTypeCategory().name() == cat_name:
            return root, None
    spec = _CONTAINERS.get(cat_name)
    if spec is None:
        return None, None
    root = hou.node(spec[0])
    if root is None:
        return None, None
    container = root.createNode(spec[1], TMP_NAME, run_init_scripts=False)
    _mark_internal(container)
    return container, container


def _mark_internal(node: Any) -> None:
    from .visual import INTERNAL_KEY

    with contextlib.suppress(Exception):
        node.setUserData(INTERNAL_KEY, "1")


@contextlib.contextmanager
def probe_instance(node_type: Any) -> Iterator[Any]:
    """A throwaway instance of ``node_type``, or None when the category has no creatable
    parent. Created with undo disabled and events muted, so it never shows in ``events``
    or the undo stack, and destroyed (with its temporary container) when the block ends."""
    import hou

    from .events import muted

    with hou.undos.disabler(), muted():
        parent, cleanup = _probe_parent(node_type.category().name())
        if parent is None:
            yield None
            return
        node = None
        try:
            # load_contents: an HDA's outputs come from its contents (a
            # multi-output asset reports one output without them).
            node = parent.createNode(
                node_type.name(), TMP_NAME if cleanup is None else None,
                run_init_scripts=False, load_contents=True,
            )  # fmt: skip
            _mark_internal(node)
            yield node
        finally:
            target = cleanup if cleanup is not None else node
            if target is not None:
                with contextlib.suppress(Exception):
                    target.destroy()


def type_io(node_type: Any) -> dict[str, Any]:
    """Named inputs/outputs of a type, read from a throwaway instance (cached per type).

    Falls back to generic ``inputN`` names when the category has no creatable parent.
    """
    key = node_type.nameWithCategory()
    cached = _IO_CACHE.get(key)
    if cached is not None:
        return cached
    data: dict[str, Any] | None = None
    try:
        with probe_instance(node_type) as node:
            if node is not None:
                data = {
                    "inputs": _io_rows(node.inputNames(), node.inputLabels()),
                    "outputs": _io_rows(node.outputNames(), node.outputLabels()),
                    "source": "instance",
                }
    except Exception:
        data = None
    if data is None:
        count = min(node_type.maxNumInputs(), max(node_type.minNumInputs(), 1), 8)
        data = {
            "inputs": [{"index": i, "name": f"input{i + 1}"} for i in range(count)],
            "outputs": [
                {"index": i, "name": f"output{i + 1}"} for i in range(node_type.maxNumOutputs())
            ][:8],
            "source": "generic",
        }
        if node_type.maxNumInputs() == 0:
            data["inputs"] = []
    _IO_CACHE[key] = data
    return data


def _io_rows(names: tuple[str, ...], labels: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for index, name in enumerate(names):
        row: dict[str, Any] = {"index": index, "name": name}
        if index < len(labels) and labels[index]:
            row["label"] = labels[index]
        rows.append(row)
    return rows


# -- parm templates -------------------------------------------------------------------

MENU_CAP = 20
PARM_HELP_CHARS = 160
_SCHEME_SUFFIXES = {
    "XYZW": "xyzw",
    "XYWH": ("x", "y", "w", "h"),
    "UVW": "uvw",
    "RGBA": "rgba",
    "MinMax": ("min", "max"),
    "MaxMin": ("max", "min"),
    "StartEnd": ("start", "end"),
    "BeginEnd": ("begin", "end"),
}


def component_names(template: Any) -> list[str]:
    """Parm names of a tuple template (``t`` → ``tx ty tz``; Base1 → ``divrate1..3``)."""
    name = template.name()
    size = template.numComponents()
    if size <= 1:
        return [name]
    try:
        scheme = template.namingScheme().name()
    except Exception:
        scheme = "Base1"
    suffixes = _SCHEME_SUFFIXES.get(scheme)
    if suffixes is not None and size <= len(suffixes):
        return [name + suffixes[i] for i in range(size)]
    return [f"{name}{i + 1}" for i in range(size)]


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return [_json_value(v) for v in value]
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    return str(value)


def parm_template_rows(
    group: Any, *, folder: str | None = None, parm_help: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Flatten a ParmTemplateGroup into parm rows in folder order. Returns ``(rows, folders)``.

    ``folder`` keeps the rows in that folder (a label or a ``A / B`` path, any case); ``""``
    keeps the top-level rows, the ones ``detail: folders`` lists as ``(no folder)``."""
    import hou

    folder_kinds = (hou.parmTemplateType.Folder, hou.parmTemplateType.FolderSet)
    skip_kinds = (hou.parmTemplateType.Separator, hou.parmTemplateType.Label)
    multiparm_kinds = {
        getattr(hou.folderType, n)
        for n in ("MultiparmBlock", "ScrollingMultiparmBlock", "TabbedMultiparmBlock")
        if hasattr(hou.folderType, n)
    }
    rows: list[dict[str, Any]] = []
    folders: list[str] = []
    wanted = folder.strip().lower() if folder is not None else None

    def visit(templates: Any, path: list[str]) -> None:
        for template in templates:
            kind = template.type()
            if kind in folder_kinds:
                label = template.label() or template.name()
                if kind == hou.parmTemplateType.Folder and template.folderType() in multiparm_kinds:
                    row = _template_row(template, path, parm_help)
                    row["type"] = "multiparm"
                    _maybe_add(row, path)
                    visit(template.parmTemplates(), [*path, f"{label}[]"])
                    continue
                folder_path = " / ".join([*path, label])
                if folder_path not in folders:
                    folders.append(folder_path)
                visit(template.parmTemplates(), [*path, label])
                continue
            if kind in skip_kinds:
                continue
            _maybe_add(_template_row(template, path, parm_help), path)

    def _maybe_add(row: dict[str, Any], path: list[str]) -> None:
        if wanted == "":
            if not path:
                rows.append(row)
            return
        if (
            wanted is not None
            and not any(wanted == p.lower().rstrip("[]") for p in path)
            and not (path and wanted == " / ".join(path).lower())
        ):
            return
        rows.append(row)

    visit(group.entries(), [])
    return rows, folders


def _template_row(
    template: Any, path: list[str], parm_help: dict[str, str] | None
) -> dict[str, Any]:
    import hou

    kind = template.type()
    row: dict[str, Any] = {
        "name": template.name(),
        "label": template.label(),
        "type": kind.name().lower(),
    }
    size = template.numComponents()
    if size > 1:
        row["size"] = size
        row["components"] = component_names(template)
    try:
        default = template.defaultValue()
        if isinstance(default, tuple) and len(default) == 1:
            default = default[0]
        row["default"] = _json_value(default)
    except Exception:
        pass
    try:
        exprs = template.defaultExpression()
        if isinstance(exprs, str):
            exprs = (exprs,)
        if any(exprs):
            row["default_expression"] = exprs[0] if len(exprs) == 1 else list(exprs)
    except Exception:
        pass
    if kind in (hou.parmTemplateType.Float, hou.parmTemplateType.Int):
        row["min"] = template.minValue()
        row["max"] = template.maxValue()
        if template.minIsStrict():
            row["min_strict"] = True
        if template.maxIsStrict():
            row["max_strict"] = True
    if kind == hou.parmTemplateType.String:
        string_type = template.stringType().name()
        if string_type != "Regular":
            row["string_type"] = re.sub(r"(?<!^)(?=[A-Z])", "_", string_type).lower()
    try:
        items = template.menuItems()
        labels = template.menuLabels()
    except Exception:
        items = ()
        labels = ()
    if items:
        menu: dict[str, Any] = {
            "items": [
                [tok, menu_label(labels[i]) if i < len(labels) else tok]
                for i, tok in enumerate(items[:MENU_CAP])
            ]
        }
        if len(items) > MENU_CAP:
            menu["total"] = len(items)
        if kind == hou.parmTemplateType.Menu and isinstance(row.get("default"), int):
            index = row["default"]
            if 0 <= index < len(items):
                row["default_token"] = items[index]
        row["menu"] = menu
    elif menu_is_dynamic(template):
        row["menu"] = {"dynamic": True, "items": []}  # evaluate_dynamic_menus fills it
    elif _maybe_node_menu(template):
        # A string menu only the node builds (a Copernicus signature; review 18 papercut 4):
        # evaluate_dynamic_menus keeps it when the instance has items.
        row["menu"] = {"dynamic": True, "items": [], "_maybe": True}
    help_text = (template.help() or "").strip()
    if not help_text and parm_help:
        help_text = parm_help.get((template.label() or "").strip().lower(), "")
    if help_text:
        row["help"] = _clip(" ".join(help_text.split()), PARM_HELP_CHARS)
    if template.isHidden():
        row["is_hidden"] = True
    if path:
        row["folder"] = " / ".join(path)
    return row


def _maybe_node_menu(template: Any) -> bool:
    """A plain string parm (no items, no script, a normal menu type) whose node may still
    give it menu items."""
    import hou

    try:
        return (
            template.type() == hou.parmTemplateType.String
            and template.stringType() == hou.stringParmType.Regular
            and template.menuType() == hou.menuType.Normal
            and template.numComponents() == 1
        )
    except Exception:
        return False


def evaluate_dynamic_menus(node_type: Any, rows: list[dict[str, Any]]) -> None:
    """Fill the ``menu`` of rows whose menu Houdini computes on an instance (a menu
    script such as ``pdg_cachemode``, or a SOP ``group`` menu; review 14 papercut 10) from
    one throwaway instance: ``{items, dynamic: true, total?}``, and ``default_token`` for a
    menu default. A menu that evaluates empty or fails keeps ``items: []`` with a ``note``."""
    pending = [row for row in rows if (row.get("menu") or {}).get("dynamic")]
    if not pending:
        return
    evaluated: dict[str, tuple[list[str], list[str]]] = {}
    with contextlib.suppress(Exception), probe_instance(node_type) as node:
        for row in pending if node is not None else ():
            parm = node.parm(row["name"])
            if parm is None:
                continue
            with contextlib.suppress(Exception):
                evaluated[row["name"]] = (list(parm.menuItems()), list(parm.menuLabels()))
    for row in pending:
        items, labels = evaluated.get(row["name"], ([], []))
        if not items and row["menu"].get("_maybe"):
            del row["menu"]  # a plain string parm after all
            continue
        if not items:
            row["menu"] = {"dynamic": True, "items": [], "note": dynamic_menu_note()}
            continue
        menu: dict[str, Any] = {
            "items": [
                [tok, menu_label(labels[i]) if i < len(labels) else tok]
                for i, tok in enumerate(items[:MENU_CAP])
            ],
            "dynamic": True,
        }
        if len(items) > MENU_CAP:
            menu["total"] = len(items)
        index = row.get("default")
        if row["type"] == "menu" and isinstance(index, int) and 0 <= index < len(items):
            row["default_token"] = items[index]
        row["menu"] = menu


# -- tools ------------------------------------------------------------------------------


def _category_arg(args: dict[str, Any]) -> str | None:
    category = args.get("category")
    if category is None or category == "":
        return None
    if not isinstance(category, str):
        raise ToolError("invalid_argument", "'category' must be a string.")
    for name in CATEGORIES:
        if name.lower() == category.lower():
            return name
    raise ToolError(
        "invalid_argument", f"Unknown category {category!r}.", candidates=list(CATEGORIES)
    )


def node_type_search(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("invalid_argument", "'query' must be a non-empty string.")
    category = _category_arg(args)
    limit = int_arg(args, "limit", 20, 1, 1000)
    include_hidden = arg_bool(args, "include_hidden", False)
    current_only = arg_bool(args, "current_only", True)
    rows, total = search(query, category, limit, include_hidden, current_only)
    public = [public_row(r, fold_versions=current_only) for r in rows]
    result: dict[str, Any] = {"results": public, "total": total}
    if current_only:
        for row in public:  # every row is a current version (review 23 papercut 6)
            row.pop("is_current_version", None)
    common = shared_fields(public, ("child_category", "typical_parents"))
    if common:
        result["common"] = common
    if not rows:
        result["hint"] = (
            "No match. Try a shorter word, the node's label (e.g. 'copy to points'), "
            "include_hidden, or no category."
        )
    if any(r["category"] == "Cop2" for r in rows):
        result["notes"] = [COP2_NOTE]
    return result


DETAILS = ("compact", "full", "folders")
NO_FOLDER = "(no folder)"
COMPACT_HINT = "detail: full adds menus, ranges, hidden parms and per-parm help."


PARM_COLUMNS = ["name", "label", "type", "default", "components"]
"""Columns of a compact parm row; ``components`` only on tuples."""


def _variants_note(variants: dict[str, int], rows: list[dict[str, Any]]) -> str:
    defaults = {r["name"]: r.get("default_token", r.get("default")) for r in rows}
    parts = ", ".join(f"{n} by {menu} ({defaults.get(menu)!s})" for menu, n in variants.items())
    return (
        f"Left out the parms the menus hide at their defaults: {parts}. Pass parms with a glob "
        "for another choice (such as <token>_*), or detail full, to list them."
    )


def filter_parms(rows: list[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    """Rows whose name or label matches the glob ``pattern`` (case-insensitive); a
    pattern without wildcards matches the whole name or label, and ``a|b`` matches
    either glob (review 12 papercut 2).

    Review 23 papercut 7: ``*pin*`` also matched eight ``*damping*`` parms. Rows where a
    wildcard pattern's text starts a word of the label or name (``Pin Type``, ``pin_group``)
    come first; the others matched only inside a word and get ``matched_by:
    "substring"``. Review 24 N2: an alternative without wildcards is an exact match, so
    the rows it matches rank with the word-start matches and are never marked, whatever
    the other alternatives are (``*pin*|group`` listed ``group`` as a substring match)."""
    import fnmatch

    pats = [p.strip().lower() for p in pattern.split("|") if p.strip()]

    def matches(row: dict[str, Any], pat: str) -> bool:
        return fnmatch.fnmatchcase(row["name"].lower(), pat) or fnmatch.fnmatchcase(
            (row.get("label") or "").lower(), pat
        )

    words, inside = [], []
    for row in rows:
        hit = [pat for pat in pats if matches(row, pat)]
        if not hit:
            continue
        # An exact alternative, or a glob with wildcards inside its text (p*n*), has no
        # word to start: never marked.
        cores = [_glob_core(pat) for pat in hit]
        if any(core is None for core in cores) or _starts_a_word(row, cores):
            words.append(row)
        else:
            inside.append(dict(row, matched_by="substring"))
    return words + inside


def _has_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def _glob_core(pattern: str) -> str | None:
    """The literal text of a wildcard glob such as ``*pin*`` or ``pin*``; None for an
    exact name (no wildcard) or a glob with wildcards inside its text."""
    if not _has_wildcard(pattern):
        return None
    core = pattern.strip("*")
    return core if core and not any(ch in core for ch in "*?[]") else None


def _starts_a_word(row: dict[str, Any], cores: list[str]) -> bool:
    import re

    text = f"{row['name']} {row.get('label') or ''}".lower()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    return any(word.startswith(core) for word in words for core in cores)


def folder_counts(rows: list[dict[str, Any]], folders: list[str]) -> list[dict[str, Any]]:
    """``[{folder, parms}]`` in folder order: visible parms directly in each folder."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("is_hidden"):
            continue
        key = row.get("folder") or NO_FOLDER
        counts[key] = counts.get(key, 0) + 1
    ordered = [NO_FOLDER, *folders] if NO_FOLDER in counts else list(folders)
    for key in counts:  # multiparm instance folders ("Points[]") are not in folders
        if key not in ordered:
            ordered.append(key)
    return [{"folder": f, "parms": counts.get(f, 0)} for f in ordered]


def compact_parms(rows: list[dict[str, Any]]) -> dict[str, list[list[Any]]]:
    """``{folder: [[name, label, type, default, components?]]}`` from full parm rows: what
    an agent needs to set parms, without menus, ranges, help or hidden parms. A menu's
    default is its token."""
    grouped: dict[str, list[list[Any]]] = {}
    for row in rows:
        if row.get("is_hidden"):
            continue
        default = row.get("default_token", row.get("default"))
        out = [row["name"], row["label"], row["type"], default]
        if "components" in row:
            out.append(row["components"])
        grouped.setdefault(row.get("folder") or NO_FOLDER, []).append(out)
    return grouped


COMPACT_COLLAPSE_BYTES = 8000
"""A compact listing over this many bytes leaves out the parms its menus hide at their
defaults (review 18 papercut 9: Cop/tilepattern listed 16 patterns' parms, 14.7 KB)."""
_COND_GROUP = re.compile(r"\{([^}]*)\}")
_COND_TERM = re.compile(r"(\w+)\s*(==|!=|<=|>=|<|>)\s*(\"[^\"]*\"|'[^']*'|[^\s}]+)")


def _term_true(value: Any, op: str, raw: str) -> bool:
    want = raw.strip("\"'")
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            other: Any = float(want)
            left: Any = float(value)
        except ValueError:
            left, other = str(value), want
    else:
        left, other = str(value), want
    try:
        return {
            "==": left == other,
            "!=": left != other,
            "<": left < other,
            ">": left > other,
            "<=": left <= other,
            ">=": left >= other,
        }[op]
    except TypeError:
        return False


def hidden_by(condition: str, defaults: dict[str, Any], menus: set[str]) -> str | None:
    """The menu parm whose default value hides a parm under ``condition`` (a ``HideWhen``:
    ``{ a != x } { b == y }``, terms in braces all true, any braces), or None when the parm
    shows at the defaults or the hiding group names no menu parm."""
    for group in _COND_GROUP.findall(condition):
        terms = _COND_TERM.findall(group)
        if not terms or any(name not in defaults for name, _op, _raw in terms):
            continue
        if all(_term_true(defaults[name], op, raw) for name, op, raw in terms):
            menu = next((name for name, _op, _raw in terms if name in menus), None)
            if menu is not None:
                return menu
    return None


def collapse_variants(
    group: Any, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rows without the parms a menu hides at its default (per-pattern parms of the other
    patterns), and ``{menu parm: parms left out}``."""
    import hou

    defaults = {r["name"]: r.get("default_token", r.get("default")) for r in rows}
    menus = {r["name"] for r in rows if r["type"] == "menu"}
    kept: list[dict[str, Any]] = []
    variants: dict[str, int] = {}
    for row in rows:
        menu = None
        with contextlib.suppress(Exception):
            template = group.find(row["name"])
            condition = template.conditionals().get(hou.parmCondType.HideWhen) if template else None
            if condition:
                menu = hidden_by(condition, defaults, menus)
        if menu is None:
            kept.append(row)
        else:
            variants[menu] = variants.get(menu, 0) + 1
    return kept, variants


def node_type_info(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    category = _category_arg(args)
    node_type = resolve_type(args.get("type"), category)
    include_parms = bool(args.get("include_parms", True))
    include_help = bool(args.get("include_help", False))
    detail = args.get("detail") or "compact"
    if detail not in DETAILS:
        raise ToolError("invalid_argument", f"'detail' must be one of {', '.join(DETAILS)}.")
    folder = args.get("folder")
    if folder is not None and not isinstance(folder, str):
        raise ToolError("invalid_argument", "'folder' must be a string.")
    if folder is not None and folder.strip().lower() in ("", NO_FOLDER):
        folder = ""  # the top-level parms, listed by detail: folders as "(no folder)"
    parm_glob = args.get("parms")
    if parm_glob is not None and (
        not isinstance(parm_glob, str) or not parm_glob.replace("|", "").strip()
    ):
        raise ToolError(
            "invalid_argument", "'parms' must be a non-empty glob such as *seed* or dist|inset."
        )

    cat_name = node_type.category().name()
    components = node_type.nameComponents()
    order = node_type.namespaceOrder()
    entry = help_entry(cat_name, components)
    raw_help = _HELP.read(entry) if entry else None
    header = parse_help_header(raw_help or "")
    asset = asset_fields(node_type) if not components[3] or not header["summary"] else {}
    result: dict[str, Any] = {
        "name": node_type.name(),
        "type": type_path(node_type),
        "label": node_type.description(),
        "category": cat_name,
        "version": components[3] or asset.get("version", ""),
        "is_current_version": not order or order[0] == node_type.name(),
        "description": header["summary"] or asset.get("description", ""),
        "help_url": node_type.helpUrl() or node_type.defaultHelpUrl(),
    }
    if order and order[0] != node_type.name():
        result["current"] = order[0]
    if len(order) > 1:
        result["versions"] = list(order)
    if node_type.hidden():
        result["hidden"] = True
    if node_type.deprecated():
        result["deprecated"] = True
        try:
            info = node_type.deprecationInfo() or {}
            if info.get("reason"):
                result["deprecation_reason"] = info["reason"]
        except Exception:
            pass
    if header["tags"]:
        result["tags"] = header["tags"]
    io = type_io(node_type)
    result["min_inputs"] = node_type.minNumInputs()
    result["max_inputs"] = node_type.maxNumInputs()
    narrowed = include_parms and (folder is not None or parm_glob is not None)
    if narrowed:  # a parm lookup: the input list is noise (42 rows on mtlx; review 13)
        result["inputs_count"] = len(io["inputs"])
    else:
        result["inputs"] = io["inputs"]
    if node_type.hasUnorderedInputs():
        result["unordered_inputs"] = True
    result["outputs"] = io["outputs"]
    if include_parms:
        wants_parm_help = include_help and raw_help and detail == "full"
        parm_help = parse_parm_help(raw_help) if wants_parm_help else None
        group = node_type.parmTemplateGroup()
        rows, folders = parm_template_rows(group, folder=folder, parm_help=parm_help)
        if folder is not None and not rows:
            every, _ = parm_template_rows(group)
            label = args.get("folder")
            raise ToolError(
                "invalid_argument",
                f"No folder {label!r} on {type_path(node_type)}.",
                hint="Pass one folder from candidates, or a single segment of one.",
                candidates=[row["folder"] for row in folder_counts(every, folders)],
            )
        if parm_glob is not None:
            rows = filter_parms(rows, parm_glob)
            inside = [row["name"] for row in rows if row.get("matched_by") == "substring"]
            if inside:
                result["substring_matches"] = inside
                result.setdefault("notes", []).append(
                    f"{len(inside)} parm(s) matched {parm_glob!r} only inside a word "
                    "(substring_matches, listed after the word-start matches)."
                )
            if not rows:
                result["hint"] = (
                    f"No parm name or label matches {parm_glob!r}; globs are case-insensitive, "
                    "e.g. *seed* or dist|inset."
                )
        if detail == "folders":
            result["folders"] = folder_counts(rows, folders)
            result["hint"] = "Pass folder with one of these to list its parms."
        elif detail == "full":
            if not narrowed:
                result["folders"] = folders
            evaluate_dynamic_menus(node_type, rows)
            result["parms"] = rows
        else:
            for key in ("help_url", "tags"):  # rarely needed to build with the type
                result.pop(key, None)
            result["parm_columns"] = PARM_COLUMNS
            result["parms"] = compact_parms(rows)
            size = len(json.dumps(result["parms"], separators=(",", ":"), default=str))
            if not narrowed and size > COMPACT_COLLAPSE_BYTES:
                kept, variants = collapse_variants(group, rows)
                if variants:
                    result["parms"] = compact_parms(kept)
                    result["variants"] = variants
                    result["notes"] = [_variants_note(variants, rows)]
            result["detail"] = "compact"
            result.setdefault("hint", COMPACT_HINT)
    if include_help:
        if raw_help:
            text, truncated = help_to_text(raw_help)
            result["help_text"] = text
            if truncated:
                result["help_truncated"] = True
            result["help_source"] = f"nodes.zip:{entry}"
        else:
            result["help_text"] = None
            result["help_note"] = "No help found for this type in $HFS/houdini/help/nodes.zip."
    return result
