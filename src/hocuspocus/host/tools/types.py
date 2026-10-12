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
import os
import re
import threading
import time
import zipfile
from typing import Any

from hocuspocus.tools.catalog import CATEGORIES
from hocuspocus.tools.errors import ToolError

from .registry import HostContext, tool

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
DESCRIPTION_CHARS = 160


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
        return data.decode("utf-8", "replace")


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
        self.build_ms = 0.0
        self.builds = 0
        self.lock = threading.Lock()


_INDEX = _Index()


def _on_hda_event(**_kwargs: Any) -> None:
    _INDEX.dirty = True


def _install_hda_callback() -> None:
    if _INDEX.callback_installed:
        return
    _INDEX.callback_installed = True
    try:
        import hou

        events = tuple(
            getattr(hou.hdaEventType, name)
            for name in ("LibraryInstalled", "LibraryUninstalled", "AssetCreated", "AssetDeleted")
            if hasattr(hou.hdaEventType, name)
        )
        hou.hda.addEventCallback(events, _on_hda_event)
    except Exception:
        pass  # the type-count check still catches most changes


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
                }
            except Exception:
                continue
            entry = help_entry(cat_name, (scope, namespace, base, version))
            header = parse_help_header(_HELP.read(entry, HELP_HEAD_BYTES) or "") if entry else None
            row["description"] = header["summary"] if header else ""
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
            rows.append(row)
    return rows


def get_index() -> list[dict[str, Any]]:
    """The cached type index (main thread). Rebuilt when HDA libraries change."""
    with _INDEX.lock:
        _install_hda_callback()
        count = _type_count()
        if _INDEX.rows is None or _INDEX.dirty or count != _INDEX.type_count:
            started = time.perf_counter()
            _INDEX.rows = _build_rows()
            _INDEX.type_count = count
            _INDEX.dirty = False
            _INDEX.build_ms = round((time.perf_counter() - started) * 1000, 1)
            _INDEX.builds += 1
        return _INDEX.rows


def index_stats() -> dict[str, Any]:
    return {
        "types": len(_INDEX.rows or ()),
        "build_ms": _INDEX.build_ms,
        "builds": _INDEX.builds,
        "help_archive": _HELP.path,
    }


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

TOKEN_WEIGHTS = {"name": 4.0, "label": 3.0, "in_name": 2.0, "tag": 1.5, "description": 1.0}

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


def public_row(row: dict[str, Any]) -> dict[str, Any]:
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
    if row["hidden"]:
        out["hidden"] = True
    return out


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def search(
    query: str, category: str | None = None, limit: int = 20, include_hidden: bool = False
) -> tuple[list[dict[str, Any]], int]:
    """Ranked index rows (main thread). Returns ``(rows, total_matches)``."""
    scored: list[tuple[float, int, int, str, dict[str, Any]]] = []
    for row in get_index():
        if category and row["category"] != category:
            continue
        if row["hidden"] and not include_hidden:
            continue
        score = score_row(row, query)
        if score > 0:
            rank = CATEGORY_RANK.get(row["category"], len(CATEGORY_RANK))
            scored.append((-score, rank, len(row["name"]), row["name"], row))
    scored.sort(key=lambda item: item[:4])
    return [item[4] for item in scored[:limit]], len(scored)


def suggest_types(query: str, category: str | None = None, limit: int = 5) -> list[str]:
    """``Category/name`` candidates for a type name that did not resolve (main thread)."""
    rows, _ = search(query, category, limit)
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
    if category:
        return [row["name"] for row in rows]
    return [f"{row['category']}/{row['name']}" for row in rows]


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
                hint="Use node_type_search to find the type by name or label.",
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
            hint="Use node_type_search to find the type by name or label.",
            candidates=suggest_types(name),
        )
    found.sort(key=lambda t: CATEGORY_RANK.get(t.category().name(), 99))
    names = [t.nameWithCategory() for t in found]
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
    return container, container


def type_io(node_type: Any) -> dict[str, Any]:
    """Named inputs/outputs of a type, read from a throwaway instance (cached per type).

    The instance is created with undo disabled and destroyed immediately. Falls back to
    generic ``inputN`` names when the category has no creatable parent.
    """
    key = node_type.nameWithCategory()
    cached = _IO_CACHE.get(key)
    if cached is not None:
        return cached
    import hou

    data: dict[str, Any] | None = None
    try:
        with hou.undos.disabler():
            parent, cleanup = _probe_parent(node_type.category().name())
            if parent is not None:
                node = None
                try:
                    node = parent.createNode(
                        node_type.name(), TMP_NAME if cleanup is None else None,
                        run_init_scripts=False, load_contents=False,
                    )  # fmt: skip
                    data = {
                        "inputs": _io_rows(node.inputNames(), node.inputLabels()),
                        "outputs": _io_rows(node.outputNames(), node.outputLabels()),
                        "source": "instance",
                    }
                finally:
                    target = cleanup if cleanup is not None else node
                    if target is not None:
                        with contextlib.suppress(Exception):
                            target.destroy()
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
    """Flatten a ParmTemplateGroup into parm rows in folder order. Returns ``(rows, folders)``."""
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
    wanted = folder.strip().lower() if folder else None

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
                [tok, labels[i] if i < len(labels) else tok]
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


# -- tools ------------------------------------------------------------------------------


def _int_arg(args: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    value = args.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ToolError("invalid_argument", f"'{key}' must be an integer from {lo} to {hi}.")
    return value


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


@tool("node_type_search")
def node_type_search(args: dict[str, Any], ctx: HostContext) -> dict[str, Any]:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("invalid_argument", "'query' must be a non-empty string.")
    category = _category_arg(args)
    limit = _int_arg(args, "limit", 20, 1, 1000)
    include_hidden = bool(args.get("include_hidden", False))
    rows, total = search(query, category, limit, include_hidden)
    result: dict[str, Any] = {"results": [public_row(r) for r in rows], "total": total}
    if not rows:
        result["hint"] = (
            "No match. Try a shorter word, the node's label (e.g. 'copy to points'), "
            "include_hidden, or no category."
        )
    return result


DETAILS = ("compact", "full")
NO_FOLDER = "(no folder)"
COMPACT_HINT = "detail: full adds menus, ranges, hidden parms and per-parm help."


PARM_COLUMNS = ["name", "label", "type", "default", "components"]
"""Columns of a compact parm row; ``components`` only on tuples."""


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


@tool("node_type_info")
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

    cat_name = node_type.category().name()
    components = node_type.nameComponents()
    order = node_type.namespaceOrder()
    entry = help_entry(cat_name, components)
    raw_help = _HELP.read(entry) if entry else None
    header = parse_help_header(raw_help or "")
    result: dict[str, Any] = {
        "name": node_type.name(),
        "type": node_type.nameWithCategory(),
        "label": node_type.description(),
        "category": cat_name,
        "version": components[3],
        "is_current_version": not order or order[0] == node_type.name(),
        "description": header["summary"],
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
    result["inputs"] = io["inputs"]
    if node_type.hasUnorderedInputs():
        result["unordered_inputs"] = True
    result["outputs"] = io["outputs"]
    if include_parms:
        wants_parm_help = include_help and raw_help and detail == "full"
        parm_help = parse_parm_help(raw_help) if wants_parm_help else None
        rows, folders = parm_template_rows(
            node_type.parmTemplateGroup(), folder=folder, parm_help=parm_help
        )
        if folder and not rows:
            raise ToolError(
                "invalid_argument",
                f"No folder {folder!r} on {node_type.nameWithCategory()}.",
                hint="Pass one folder label from candidates (a single segment).",
                candidates=folders,
            )
        if detail == "full":
            result["folders"] = folders
            result["parms"] = rows
        else:
            for key in ("help_url", "tags"):  # rarely needed to build with the type
                result.pop(key, None)
            result["parm_columns"] = PARM_COLUMNS
            result["parms"] = compact_parms(rows)
            result["detail"] = "compact"
            result["hint"] = COMPACT_HINT
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
