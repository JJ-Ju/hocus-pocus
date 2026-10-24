"""``hocuspocus`` command line: install the Houdini package, launch Houdini, diagnose, print
client config.

See docs/BIBLE.md §10.2. Stdlib only (the bridge modules imported here are stdlib too),
so ``hocuspocus doctor`` works even when the MCP SDK is broken.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bridge import licence
from .tools import catalog
from .version import __version__

PACKAGE_JSON_NAME = "hocuspocus.json"
INSTALL_DIR_NAME = "hocuspocus"
TESTED_HOUDINI = ("22.0.466",)
HYTHON_QUERY_TIMEOUT_S = 90.0
HYTHON_VERSION_TIMEOUT_S = 60.0

CLAUDE_SNIPPET = "claude mcp add -s user hocuspocus -- hocuspocus-mcp"
"""User scope: the server is available in every project, not only the current directory."""
CODEX_SNIPPET = '[mcp_servers.hocuspocus]\ncommand = "hocuspocus-mcp"\nargs = []'


# -- locations ---------------------------------------------------------------------------


def package_dir() -> Path:
    """The installed/checked-out ``hocuspocus`` package directory."""
    return Path(__file__).resolve().parent


def checkout_root() -> Path | None:
    """The repo root when running from a source checkout (``<root>/src/hocuspocus``)."""
    pkg = package_dir()
    root = pkg.parent.parent
    if pkg.parent.name == "src" and (root / "pyproject.toml").is_file():
        return root
    return None


def payload_source() -> Path | None:
    """The Houdini package payload (``houdini/``): the checkout's, or one shipped in the package."""
    root = checkout_root()
    candidates = [root / "houdini"] if root else []
    candidates.append(package_dir() / "_houdini")
    for cand in candidates:
        if cand.is_dir():
            return cand
    return None


def template_source() -> Path | None:
    payload = payload_source()
    if payload and (payload / "hocuspocus.json.template").is_file():
        return payload / "hocuspocus.json.template"
    return None


def _posix(path: Path) -> str:
    return str(path).replace("\\", "/")


# -- Houdini discovery ---------------------------------------------------------------------


def _detect_hfs(explicit: str | None) -> Path | None:
    from .bridge.launch import detect_hfs

    return detect_hfs(explicit)


def _hython(hfs: Path) -> Path:
    from .bridge.launch import hython_path

    return hython_path(hfs)


def run_hython(
    hfs: Path,
    code: str,
    timeout_s: float,
    *,
    environ: Mapping[str, str] | None = None,
    failure: list[str] | None = None,
) -> str | None:
    """Run ``hython -c code`` from a neutral cwd; return the last stdout line or ``None``.

    On a non-zero exit, ``failure`` (when given) receives hython's stderr and stdout, so a
    caller can tell a licence refusal from other failures."""
    env = dict(os.environ if environ is None else environ)
    env.pop("PYTHONPATH", None)
    try:
        with tempfile.TemporaryDirectory(prefix="hocuspocus-") as cwd:
            proc = subprocess.run(
                [str(_hython(hfs)), "-c", code],
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        if failure is not None:
            failure.append(f"{proc.stderr or ''}\n{proc.stdout or ''}")
        return None
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


@dataclass(frozen=True, slots=True)
class PrefDir:
    path: Path
    source: str


HythonQuery = Callable[[Path, Mapping[str, str]], "str | None"]
"""``(hfs, environment) -> hou.homeHoudiniDirectory()`` as hython reports it, or ``None``."""


def query_home_houdini_dir(hfs: Path, environ: Mapping[str, str]) -> str | None:
    return run_hython(
        hfs,
        "import hou; print(hou.homeHoudiniDirectory())",
        HYTHON_QUERY_TIMEOUT_S,
        environ=environ,
    )


def without_home(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` without ``HOME``: what a Houdini started from the Start menu sees."""
    return {k: v for k, v in environ.items() if k.upper() != "HOME"}


def _major_minor(answers: Sequence[str | None], hfs: Path | None) -> str:
    """The Houdini ``major.minor``: from hython's pref dir name, else the HFS name."""
    from .bridge.config import HOUDINI_MAJOR_MINOR

    for answer in answers:
        if answer:
            m = re.search(r"(\d+\.\d+)$", Path(answer).name)
            if m:
                return m.group(1)
    if hfs is not None:
        m = re.search(r"(\d+\.\d+)", hfs.name)
        if m:
            return m.group(1)
    return HOUDINI_MAJOR_MINOR


def platform_default_pref_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The first existing default pref dir, in the bridge's order (``%USERPROFILE%`` then
    ``Documents`` on Windows), else the first: install and bridge must agree on it."""
    from .bridge.config import default_pref_dirs

    candidates = default_pref_dirs(environ)
    return next((path for path in candidates if path.is_dir()), candidates[0])


def pref_dir_candidates(
    flag: str | None,
    *,
    hfs: str | None = None,
    environ: Mapping[str, str] | None = None,
    hython_query: HythonQuery | None = None,
    platform: str | None = None,
) -> list[PrefDir]:
    """Every pref dir a Houdini on this machine may use, deduplicated by real path.

    In order: ``--prefs``; ``$HOUDINI_USER_PREF_DIR`` (``__HVER__`` expanded); what hython
    reports for ``hou.homeHoudiniDirectory()`` with this environment; on Windows, what it
    reports without ``HOME`` (a Houdini started from the Start menu has none, one started
    from Git Bash has one, and the two use different pref dirs); then each existing
    default location (``<home>/houdiniX.Y``, ``<home>/Documents/houdiniX.Y``). Only the
    defaults are filtered by existence; when nothing at all is found the first default is
    returned, so there is always a candidate.
    """
    from .bridge.config import default_pref_dirs, same_dir_key

    env = os.environ if environ is None else environ
    platform = platform or sys.platform
    found: list[PrefDir] = []
    index: dict[str, int] = {}

    def add(path: Path, source: str) -> None:
        key = same_dir_key(path)
        if key in index:
            known = found[index[key]]
            found[index[key]] = PrefDir(known.path, f"{known.source}, {source}")
        else:
            index[key] = len(found)
            found.append(PrefDir(path, source))

    if flag:
        add(Path(flag).expanduser(), "--prefs")
    answers: list[tuple[str | None, str]] = []
    hfs_dir = _detect_hfs(hfs)
    if hfs_dir is not None:
        query = hython_query or query_home_houdini_dir
        answers.append((query(hfs_dir, env), f"hython ({hfs_dir})"))
        if platform == "win32" and any(k.upper() == "HOME" for k in env):
            answers.append((query(hfs_dir, without_home(env)), f"hython without HOME ({hfs_dir})"))
    major_minor = _major_minor([answer for answer, _ in answers], hfs_dir)
    from_env = env.get("HOUDINI_USER_PREF_DIR", "").strip()
    if from_env:
        add(Path(from_env.replace("__HVER__", major_minor)).expanduser(), "HOUDINI_USER_PREF_DIR")
    for answer, source in answers:
        if answer:
            add(Path(answer), source)
    defaults = default_pref_dirs(env, major_minor=major_minor, platform=platform)
    for path in defaults:
        if path.is_dir():
            add(path, "default location")
    if not found:
        add(defaults[0], "platform default")
    return found


def resolve_pref_dir(
    flag: str | None,
    *,
    hfs: str | None = None,
    environ: Mapping[str, str] | None = None,
    hython_query: HythonQuery | None = None,
    platform: str | None = None,
) -> PrefDir:
    """The first of :func:`pref_dir_candidates`."""
    return pref_dir_candidates(
        flag, hfs=hfs, environ=environ, hython_query=hython_query, platform=platform
    )[0]


def install_targets(candidates: Sequence[PrefDir]) -> list[PrefDir]:
    """The candidates ``install-houdini`` writes to: ``--prefs`` (created if missing) and
    every other candidate that already exists. When none exists, the first is created (a
    machine where Houdini never ran has no pref dir yet)."""
    targets = [c for c in candidates if c.source.startswith("--prefs") or c.path.is_dir()]
    return targets or list(candidates[:1])


# -- package JSON ------------------------------------------------------------------------


def render_package_json(
    python_dir: Path, payload_dir: Path | None, template: Path | None = None
) -> tuple[str, str]:
    """Return ``(json_text, template_used)``.

    The template (``houdini/hocuspocus.json.template``) may use ``{{PYTHON_DIR}}``,
    ``{{PAYLOAD_DIR}}`` and ``{{VERSION}}`` placeholders. Whatever it says, the result
    prepends ``python_dir`` to ``PYTHONPATH``, sets ``HOCUSPOCUS_VERSION`` and, when there
    is a payload, points ``hpath`` at it. An unreadable or invalid template falls back to
    the equivalent inline package.
    """
    values = {
        "VERSION": __version__,
        "PYTHON_DIR": _posix(python_dir),
        "PAYLOAD_DIR": _posix(payload_dir) if payload_dir else "",
    }
    used = "inline"
    data: dict[str, Any] | None = None
    if template is not None:
        try:
            text = template.read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace("{{" + key + "}}", value)
            if re.search(r"\{\{[A-Z_]+\}\}", text) is None:
                loaded = json.loads(text)
                if isinstance(loaded, dict):
                    data, used = loaded, str(template)
        except (OSError, ValueError):
            data = None
    if data is None:
        data = {"enable": True, "load_package_once": True, "env": []}
    env = data.get("env")
    if not isinstance(env, list):
        env = [env] if isinstance(env, dict) else []
    env = [
        e
        for e in env
        if not (isinstance(e, dict) and ("PYTHONPATH" in e or "HOCUSPOCUS_VERSION" in e))
    ]
    data["env"] = [
        {"HOCUSPOCUS_VERSION": __version__},
        {"PYTHONPATH": {"value": values["PYTHON_DIR"], "method": "prepend"}},
        *env,
    ]
    if payload_dir is not None:
        data["hpath"] = values["PAYLOAD_DIR"]
    elif not data.get("hpath"):
        data.pop("hpath", None)
    return json.dumps(data, indent=4) + "\n", used


def package_python_dir(data: Any) -> Path | None:
    """The PYTHONPATH entry a HocusPocus package JSON adds."""
    if not isinstance(data, dict):
        return None
    env = data.get("env") or []
    entries = env if isinstance(env, list) else [env]
    for entry in entries:
        if isinstance(entry, dict) and "PYTHONPATH" in entry:
            value = entry["PYTHONPATH"]
            if isinstance(value, dict):
                value = value.get("value")
            if isinstance(value, list):
                value = value[0] if value else None
            if isinstance(value, str) and value:
                # Houdini package values use ';' between entries on every platform.
                return Path(value.split(";")[0])
    return None


def _ignore_build_junk(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))}


def _write_atomic(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` through a temp file and ``os.replace``."""
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, target)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def copied_installs(prefs: Path) -> list[Path]:
    """Version directories a non-dev ``install-houdini`` copied into ``<prefs>/hocuspocus``."""
    root = prefs / INSTALL_DIR_NAME
    try:
        return sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []


def _copy_package(
    prefs: Path, payload: Path | None, out: Callable[[str], None]
) -> tuple[Path, Path | None]:
    """Copy this version into ``<prefs>/hocuspocus/<version>/``; ``(python_dir, payload_dir)``."""
    install_root = prefs / INSTALL_DIR_NAME
    version_dir = install_root / __version__
    python_dir = version_dir / "python"
    if install_root.is_dir():
        for old in install_root.iterdir():
            if old.is_dir() and old.name != __version__:
                shutil.rmtree(old, ignore_errors=True)
                out(f"removed older install {old}")
    if version_dir.exists():
        shutil.rmtree(version_dir)
    shutil.copytree(package_dir(), python_dir / "hocuspocus", ignore=_ignore_build_junk)
    out(f"copied hocuspocus {__version__} to {python_dir / 'hocuspocus'}")
    payload_dir = None
    if payload is not None:
        payload_dir = version_dir / "houdini"
        shutil.copytree(payload, payload_dir, ignore=_ignore_build_junk)
        out(f"copied the Houdini payload to {payload_dir}")
    return python_dir, payload_dir


def install(prefs: Path | Sequence[Path], *, dev: bool, out: Callable[[str], None] = print) -> int:
    """Install into every pref dir in ``prefs``. Each gets its own package JSON and, without
    ``--dev``, its own copy, so removing one pref dir never breaks another."""
    targets = [prefs] if isinstance(prefs, Path) else list(prefs)
    payload = payload_source()
    dev_python_dir: Path | None = None
    if dev:
        root = checkout_root()
        if root is None:
            out("error: --dev needs a source checkout (src/hocuspocus next to pyproject.toml).")
            return 2
        dev_python_dir = root / "src"
        out(f"dev install: Houdini will import hocuspocus from {dev_python_dir}")
    if payload is None:
        out("warning: no Houdini payload (houdini/) found; GUI autostart will not be installed.")
    template = template_source()
    python_dirs: list[Path] = []
    written: list[Path] = []
    for target in targets:
        if dev_python_dir is not None:
            python_dir, payload_dir = dev_python_dir, payload
            for old in copied_installs(target):
                # A copy from an earlier non-dev install would only confuse doctor and users.
                shutil.rmtree(old, ignore_errors=True)
                out(f"removed copied install {old} (the dev install uses the checkout)")
        else:
            python_dir, payload_dir = _copy_package(target, payload, out)
        text, used = render_package_json(python_dir, payload_dir, template)
        packages = target / "packages"
        packages.mkdir(parents=True, exist_ok=True)
        json_path = packages / PACKAGE_JSON_NAME
        _write_atomic(json_path, text)
        out(f"wrote {json_path} (template: {used})")
        python_dirs.append(python_dir)
        written.append(json_path)
    if len(written) > 1:
        out(f"installed into {len(written)} pref dirs (Houdini may use any of them):")
        for json_path in written:
            out(f"  {json_path}")
    record = write_install_state(targets, python_dirs[0], dev=dev)
    if record is not None:
        out(f"recorded the pref dirs in {record} (the bridge reads hocuspocus.toml from there)")
    out("Restart Houdini to load HocusPocus.")
    out(f"Then register the MCP server with your client, e.g.: {CLAUDE_SNIPPET}")
    return 0


def write_install_state(
    prefs: Path | Sequence[Path], python_dir: Path, *, dev: bool
) -> Path | None:
    """Record the pref dirs in ``<state_dir>/install.json`` for the bridge (BIBLE §3.7).

    The bridge starts on every MCP client launch and cannot afford a hython query to find
    the pref dir, so ``install-houdini`` remembers where it installed: ``pref_dirs`` (all
    of them, in order) and ``prefs`` (the first; the only key before 1.2.1). Best effort.
    """
    from .bridge.config import INSTALL_STATE_FILE
    from .tools.paths import ensure_private_dir, state_dir

    dirs = [_posix(p.resolve()) for p in ([prefs] if isinstance(prefs, Path) else prefs)]
    data = {
        "prefs": dirs[0],
        "pref_dirs": dirs,
        "python_dir": _posix(python_dir),
        "version": __version__,
        "dev": dev,
    }
    try:
        target = ensure_private_dir(state_dir()) / INSTALL_STATE_FILE
        _write_atomic(target, json.dumps(data, indent=2) + "\n")
    except OSError:
        return None
    return target


def _forget_install_state() -> None:
    from .bridge.config import INSTALL_STATE_FILE
    from .tools.paths import state_dir

    with contextlib.suppress(OSError):
        (state_dir() / INSTALL_STATE_FILE).unlink()


def _remove_from(prefs: Path, out: Callable[[str], None]) -> tuple[bool, bool]:
    """Remove the package from one pref dir; ``(removed_something, failed)``."""
    removed = False
    target = prefs / "packages" / PACKAGE_JSON_NAME
    if target.is_file():
        target.unlink()
        out(f"removed {target}")
        removed = True
    install_root = prefs / INSTALL_DIR_NAME
    if install_root.is_dir():
        try:
            shutil.rmtree(install_root)
        except OSError as exc:
            out(
                f"error: cannot remove {install_root} ({exc}). A running Houdini may hold its "
                "files open: close Houdini and run uninstall-houdini again."
            )
            return removed, True
        out(f"removed {install_root}")
        removed = True
    return removed, False


def uninstall(prefs: Path | Sequence[Path], *, out: Callable[[str], None] = print) -> int:
    """Remove the package from ``prefs`` and from every pref dir ``install.json`` recorded."""
    from .bridge.config import dedupe_dirs, installed_pref_dirs

    given = [prefs] if isinstance(prefs, Path) else list(prefs)
    targets = dedupe_dirs(given + installed_pref_dirs())
    removed = failed = False
    for target in targets:
        did, err = _remove_from(target, out)
        removed, failed = removed or did, failed or err
    if failed:
        return 1  # keep install.json: it still lists where the rest is
    _forget_install_state()
    if not removed:
        out(f"nothing to remove under {', '.join(str(t) for t in targets)}")
    else:
        out("Restart Houdini to unload HocusPocus.")
    return 0


def install_houdini(
    flag: str | None,
    *,
    dev: bool,
    hfs: str | None = None,
    environ: Mapping[str, str] | None = None,
    hython_query: HythonQuery | None = None,
    platform: str | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """``hocuspocus install-houdini``: install into every pref dir Houdini may use."""
    candidates = pref_dir_candidates(
        flag, hfs=hfs, environ=environ, hython_query=hython_query, platform=platform
    )
    targets = install_targets(candidates)
    for cand in candidates:
        note = "" if cand in targets else "; does not exist, skipped"
        out(f"Houdini pref dir: {cand.path} (from {cand.source}{note})")
    return install([t.path for t in targets], dev=dev, out=out)


def uninstall_houdini(
    flag: str | None,
    *,
    hfs: str | None = None,
    environ: Mapping[str, str] | None = None,
    hython_query: HythonQuery | None = None,
    platform: str | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """``hocuspocus uninstall-houdini``: remove from every candidate and recorded pref dir."""
    candidates = pref_dir_candidates(
        flag, hfs=hfs, environ=environ, hython_query=hython_query, platform=platform
    )
    return uninstall([c.path for c in candidates], out=out)


# -- doctor ------------------------------------------------------------------------------


class Report:
    def __init__(self, out: Callable[[str], None]) -> None:
        self.out = out
        self.failures = 0

    def ok(self, label: str, detail: str = "") -> None:
        self.out(f"[ok]   {label}{': ' + detail if detail else ''}")

    def warn(self, label: str, detail: str = "") -> None:
        self.out(f"[warn] {label}{': ' + detail if detail else ''}")

    def fail(self, label: str, detail: str = "") -> None:
        self.failures += 1
        self.out(f"[FAIL] {label}{': ' + detail if detail else ''}")

    def info(self, label: str, detail: str = "") -> None:
        self.out(f"[--]   {label}{': ' + detail if detail else ''}")


def _read_version(pkg_dir: Path) -> str | None:
    try:
        text = (pkg_dir / "version.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


def literal_hver_dirs(pref_dir: Path, environ: Mapping[str, str] | None = None) -> list[Path]:
    """Folders literally named ``houdini__HVER__`` next to the resolved pref dir (or the
    unexpanded ``HOUDINI_USER_PREF_DIR`` itself). Houdini expands the token, so nothing in
    them is read (reviews 13 and 16)."""
    env = os.environ if environ is None else environ
    candidates = [pref_dir.parent / "houdini__HVER__"]
    raw = env.get("HOUDINI_USER_PREF_DIR", "")
    if "__HVER__" in raw:
        candidates.append(Path(raw).expanduser())
    found: list[Path] = []
    for path in candidates:
        try:
            same = path.resolve() == pref_dir.resolve()
        except OSError:
            same = False
        if path.is_dir() and not same and path not in found:
            found.append(path)
    return found


def _check_literal_hver(report: Report, pref_dir: Path) -> None:
    for path in literal_hver_dirs(pref_dir):
        moved = [n for n in ("hocuspocus.toml", "packages") if (path / n).exists()]
        report.warn(
            "literal __HVER__ folder",
            f"{path} exists, but Houdini expands __HVER__ and reads {pref_dir}"
            + (f"; move {' and '.join(moved)} there" if moved else "; nothing in it is read"),
        )


@dataclass(frozen=True, slots=True)
class PackageState:
    """What one pref dir holds: ``status`` is ``no-dir``, ``missing``, ``invalid``,
    ``no-python``, ``stale`` or ``current``."""

    pref: PrefDir
    status: str
    detail: str
    python_dir: Path | None = None
    host_version: str | None = None


def package_state(pref: PrefDir) -> PackageState:
    if not pref.path.is_dir():
        return PackageState(pref, "no-dir", "directory does not exist")
    pkg_json = pref.path / "packages" / PACKAGE_JSON_NAME
    if not pkg_json.is_file():
        return PackageState(pref, "missing", "no package JSON")
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return PackageState(pref, "invalid", f"{pkg_json} is not valid JSON ({exc})")
    python_dir = package_python_dir(data)
    if python_dir is None:
        return PackageState(pref, "invalid", f"{pkg_json} has no PYTHONPATH entry")
    if not (python_dir / "hocuspocus").is_dir():
        return PackageState(
            pref, "no-python", f"PYTHONPATH {python_dir} has no hocuspocus package", python_dir
        )
    host_version = _read_version(python_dir / "hocuspocus")
    if host_version != __version__:
        return PackageState(
            pref,
            "stale",
            f"package JSON -> {python_dir} has {host_version or 'unknown'}",
            python_dir,
            host_version,
        )
    return PackageState(
        pref, "current", f"package JSON -> {python_dir} ({host_version})", python_dir, host_version
    )


def _is_dev_python_dir(python_dir: Path | None) -> bool:
    root = checkout_root()
    if python_dir is None or root is None:
        return False
    from .bridge.config import same_dir_key

    return same_dir_key(python_dir) == same_dir_key(root / "src")


def _check_pref_dirs(report: Report, states: Sequence[PackageState]) -> None:
    """One line per candidate, and a warning when existing candidates disagree."""
    for state in states:
        line = f"{state.pref.path} (from {state.pref.source}): {state.detail}"
        if state.status == "current":
            report.ok("pref dir", line)
        else:
            report.info("pref dir", line)
    existing = [s for s in states if s.status != "no-dir"]
    have = [s for s in existing if s.status == "current"]
    lacking = [s for s in existing if s.status != "current"]
    if have and lacking:
        dev = " --dev" if _is_dev_python_dir(have[0].python_dir) else ""
        report.warn(
            "pref dirs disagree",
            f"HocusPocus {__version__} is installed in "
            f"{', '.join(str(s.pref.path) for s in have)} but not in "
            f"{', '.join(str(s.pref.path) for s in lacking)}, so a Houdini that uses the "
            f"latter (started from the Start menu, or from a shell that sets HOME) will not "
            f"load it; run `hocuspocus install-houdini{dev}` to install into all of them",
        )


def licence_state(hfs: Path) -> Any:
    """``sesictrl diagnostic`` / ``hserver -l`` next to ``hfs``, parsed (tests replace it)."""
    return licence.licence_state(hfs)


def _check_licence(report: Report, hfs: Path) -> None:
    """A licence line for doctor: ok, a warning, or info; never a failure (2.1)."""
    try:
        level, text = licence.verdict(licence_state(hfs))
    except Exception as exc:  # a diagnostic must never break doctor
        level, text = "info", f"not checked ({exc})"
    {"ok": report.ok, "warn": report.warn}.get(level, report.info)("licence", text)


def doctor(
    args: argparse.Namespace,
    out: Callable[[str], None] = print,
    *,
    environ: Mapping[str, str] | None = None,
    hython_query: HythonQuery | None = None,
    platform: str | None = None,
) -> int:
    report = Report(out)
    out(f"hocuspocus {__version__} (bridge, hp/v{catalog.HP_RPC_VERSION})")

    hfs = _detect_hfs(args.hfs)
    if hfs is None:
        report.fail(
            "Houdini install", "not found; set HFS or pass --hfs (needed to launch Houdini)"
        )
    else:
        report.ok("Houdini install", str(hfs))
        failure: list[str] = []
        version = run_hython(
            hfs,
            "import hou; print(hou.applicationVersionString())",
            HYTHON_VERSION_TIMEOUT_S,
            failure=failure,
        )
        refused = licence.log_excerpt("\n".join(failure))
        if version is None and refused:
            report.warn("Houdini version", f'hython could not get a licence: "{refused}"')
        elif version is None:
            report.warn("Houdini version", "hython did not answer (licence or startup problem?)")
        else:
            parts = tuple(int(n) for n in re.findall(r"\d+", version)[:2])
            if parts < (22, 0):
                report.fail("Houdini version", f"{version}; HocusPocus needs 22.0 or newer")
            elif version not in TESTED_HOUDINI:
                report.warn(
                    "Houdini version",
                    f"{version} (supported, but tested on {', '.join(TESTED_HOUDINI)})",
                )
            else:
                report.ok("Houdini version", version)
        _check_licence(report, hfs)

    from .bridge.config import dedupe_dirs, find_config_file, installed_pref_dirs, same_dir_key

    candidates = pref_dir_candidates(
        args.prefs, hfs=args.hfs, environ=environ, hython_query=hython_query, platform=platform
    )
    known = {same_dir_key(c.path) for c in candidates}
    for recorded in dedupe_dirs(installed_pref_dirs()):
        if same_dir_key(recorded) not in known:
            candidates.append(PrefDir(recorded, "install.json"))
    states = [package_state(c) for c in candidates]
    _check_pref_dirs(report, states)
    # The detailed checks use the first candidate with a current package, else the first
    # with any package JSON, else the first that exists.
    ranked = (
        [s for s in states if s.status == "current"]
        + [s for s in states if s.status not in ("no-dir", "missing")]
        + [s for s in states if s.status != "no-dir"]
        + states
    )
    primary = ranked[0]
    prefs = primary.pref

    toml = find_config_file(environ)
    beside = [
        c.path / "hocuspocus.toml" for c in candidates if (c.path / "hocuspocus.toml").is_file()
    ]
    if toml is None and beside:
        report.warn(
            "hocuspocus.toml",
            f"{beside[0]} exists but the bridge cannot find it; run `hocuspocus install-houdini` "
            "or set HOUDINI_USER_PREF_DIR for the MCP client",
        )
    else:
        report.ok(
            "hocuspocus.toml",
            f"{toml} (host and bridge; HOCUSPOCUS_* env overrides)" if toml else "none (defaults)",
        )
    _check_literal_hver(report, prefs.path)
    pkg_json = prefs.path / "packages" / PACKAGE_JSON_NAME
    if primary.status in ("no-dir", "missing"):
        report.fail("package JSON", f"{pkg_json} missing; run `hocuspocus install-houdini`")
    elif primary.status == "invalid":
        report.fail("package JSON", primary.detail)
    elif primary.status == "no-python":
        report.fail("package JSON", f"{primary.detail}; reinstall")
    else:
        python_dir = primary.python_dir
        assert python_dir is not None
        report.ok("package JSON", f"{pkg_json} -> {python_dir}")
        leftovers = [p for p in copied_installs(prefs.path) if p not in python_dir.parents]
        if leftovers:
            report.warn(
                "copied installs",
                f"{', '.join(str(p) for p in leftovers)} not used by the package "
                "JSON (left by an earlier install); run `hocuspocus install-houdini` "
                "(with --dev for a checkout) to remove them",
            )
        if primary.status == "current":
            report.ok("host/bridge version", __version__)
        else:
            report.fail(
                "host/bridge version",
                f"Houdini has {primary.host_version or 'unknown'}, bridge is {__version__}; "
                "run `hocuspocus install-houdini` and restart Houdini",
            )

    from .bridge import instances as registry
    from .bridge.client import HostClient
    from .tools import paths
    from .tools.errors import ToolError

    live = registry.scan()
    if not live:
        report.warn(
            "live instances",
            f"none in {paths.instances_dir()} (start Houdini, or houdini_connect launch)",
        )
    for inst in live:
        where = f"pid {inst.pid} port {inst.port} {'GUI' if inst.ui else 'headless'} {inst.hip or '(untitled)'}"
        try:
            health = registry.check_identity(inst, HostClient(inst.port, inst.token))
        except registry.StaleEntry as exc:
            # The pid is alive but is not that host (reused after a crash): review 10 1.4.
            registry.forget(inst)
            report.warn("instance", f"{exc}; removed the stale registry entry")
            continue
        except ToolError as exc:
            report.fail("instance", f"{where}: {exc.code}: {exc.message}")
            continue
        report.ok("instance /health", f"{where} Houdini {health.get('houdini', '?')}")

    out("")
    out("Register with Claude Code:")
    out(f"  {CLAUDE_SNIPPET}")
    out("Register with Codex (~/.codex/config.toml):")
    out("  " + CODEX_SNIPPET.replace("\n", "\n  "))
    out("")
    out(
        "doctor: all checks passed"
        if report.failures == 0
        else f"doctor: {report.failures} problem(s)"
    )
    return 0 if report.failures == 0 else 1


# -- other commands ----------------------------------------------------------------------


def _launcher(hfs: str | None) -> Any:
    from .bridge.config import BridgeConfig
    from .bridge.launch import Launcher

    return Launcher(hfs or BridgeConfig.load().hfs or None, owned=False)


def launch_houdini(
    mode: str,
    hip: str | None,
    wait_s: float,
    *,
    hfs: str | None = None,
    work_dir: str | None = None,
    out: Callable[[str], None] = print,
    err: Callable[[str], None] | None = None,
) -> int:
    """``hocuspocus launch``: start a Houdini that belongs to no MCP server.

    Houdini starts in ``work_dir`` (default: the directory the command runs in), which is
    the untitled scene's ``$HIP`` and ``$JOB`` (review 12). ``houdini_connect {launch}``
    keeps its own rule: ``HOCUSPOCUS_WORK_DIR``, else home.

    The Houdini is started detached from this process, which exits once its host has
    registered (or at once with ``--wait 0``), so it outlives every MCP client. stdout
    gets one JSON object: the registry entry (no token), the mode and, headless, the log.
    """
    from .tools.errors import ToolError

    err = err or (lambda text: print(text, file=sys.stderr))
    launcher = _launcher(hfs)
    where = Path(work_dir) if work_dir else Path.cwd()
    try:
        spawned = launcher.spawn(mode, hip, work_dir=where)
        if wait_s <= 0:
            out(json.dumps({"pid": spawned.proc.pid, "mode": mode, "log": spawned.log}))
            err("Started without waiting; houdini_status lists it once its host registers.")
            return 0
        result = launcher.wait(spawned, wait_s)
    except ToolError as exc:
        err(f"error: {exc.message}")
        if exc.hint:
            err(f"hint: {exc.hint}")
        return 1
    entry = dict(result.instance.public(), mode=result.mode)
    if result.log:
        entry["log"] = result.log
    out(json.dumps(entry))
    # With --hip the scene is that file and $HIP its folder: no untitled scene (review 16 N6).
    scene = (
        f"It loaded {Path(hip).resolve()}."
        if hip
        else f"$HIP of the untitled scene is {where.resolve()}."
    )
    err(
        f"Houdini pid {result.instance.pid} is running and outlives this command; attach "
        f'from an MCP client with houdini_connect {{"pid": {result.instance.pid}}}. {scene}'
    )
    return 0


def client_config(client: str, out: Callable[[str], None] = print) -> int:
    if client == "claude":
        out(CLAUDE_SNIPPET)
    else:
        out("# ~/.codex/config.toml")
        out(CODEX_SNIPPET)
    exe = shutil.which("hocuspocus-mcp")
    if exe is None:
        out(
            "# note: hocuspocus-mcp is not on PATH; use its absolute path (e.g. from `uv tool install`)."
        )
    return 0


def docs_tools(output: str | None, out: Callable[[str], None] = print) -> int:
    try:
        from .tools import docs
    except ImportError:
        out("hocuspocus.tools.docs is not available in this build; cannot render docs/tools.md.")
        return 1
    text = docs.render_tools_markdown(catalog.TOOLS)
    if output == "-":
        sys.stdout.write(text)
        return 0
    if output:
        target = Path(output)
    elif hasattr(docs, "default_output_path"):
        target = Path(docs.default_output_path())
    else:
        sys.stdout.write(text)
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    out(f"wrote {target}")
    return 0


def version(out: Callable[[str], None] = print) -> int:
    try:
        from importlib.metadata import version as dist_version

        mcp_version = dist_version("mcp")
    except Exception:  # noqa: BLE001
        mcp_version = "not installed"
    out(
        f"hocuspocus {__version__} (hp/v{catalog.HP_RPC_VERSION}, mcp {mcp_version}, Python {sys.version.split()[0]})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hocuspocus", description="HocusPocus: AI agents drive Houdini over MCP."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "install-houdini", help="install the Houdini package into your Houdini pref dir"
    )
    p.add_argument(
        "--prefs",
        help="Houdini user pref dir to install into (created if missing), in addition to every "
        "existing pref dir Houdini may use: HOUDINI_USER_PREF_DIR, what hython reports with "
        "and without HOME, and the default locations",
    )
    p.add_argument(
        "--dev",
        action="store_true",
        help="point Houdini at this checkout's src/ instead of copying",
    )
    p.add_argument("--hfs", help="Houdini install dir used to locate hython")

    p = sub.add_parser("uninstall-houdini", help="remove the Houdini package")
    p.add_argument("--prefs")
    p.add_argument("--hfs")

    p = sub.add_parser("doctor", help="check the installation and running Houdini instances")
    p.add_argument("--prefs")
    p.add_argument("--hfs")

    p = sub.add_parser("client-config", help="print MCP client configuration")
    p.add_argument("client", choices=["claude", "codex"])

    p = sub.add_parser("docs", help="generate documentation")
    p.add_argument("what", choices=["tools"])
    p.add_argument("--output", "-o", help="output path ('-' for stdout; default docs/tools.md)")

    p = sub.add_parser(
        "launch",
        help="start a Houdini with HocusPocus that outlives any MCP client",
        description="Start GUI Houdini (or headless hython with --headless) with the "
        "HocusPocus host, wait for it to register, print its registry entry as JSON and "
        "exit. The Houdini keeps running; attach to it with houdini_connect {pid}. It starts "
        "in the current directory (or --work-dir), which is the untitled scene's $HIP and "
        "$JOB; Houdini also searches that directory for scripts and assets, as when you run "
        "houdini there yourself. houdini_connect {launch} instead starts in "
        "HOCUSPOCUS_WORK_DIR, else your home directory.",
    )
    p.add_argument("--headless", action="store_true", help="run hython -m hocuspocus.host")
    p.add_argument("--hip", help="hip file to open")
    p.add_argument(
        "--wait",
        type=float,
        default=90.0,
        metavar="N",
        help="seconds to wait for the host to register (default 90; 0 returns at once)",
    )
    p.add_argument("--hfs", help="Houdini install dir (default: HOCUSPOCUS_HFS, HFS, newest 22.x)")
    p.add_argument(
        "--work-dir",
        metavar="DIR",
        help="directory Houdini starts in: $HIP and $JOB of the untitled scene "
        "(default: the current directory; created if missing)",
    )

    sub.add_parser("version", help="print versions")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install-houdini":
        return install_houdini(args.prefs, dev=args.dev, hfs=args.hfs)
    if args.command == "uninstall-houdini":
        return uninstall_houdini(args.prefs, hfs=args.hfs)
    if args.command == "doctor":
        return doctor(args)
    if args.command == "client-config":
        return client_config(args.client)
    if args.command == "docs":
        return docs_tools(args.output)
    if args.command == "launch":
        return launch_houdini(
            "headless" if args.headless else "gui",
            args.hip,
            args.wait,
            hfs=args.hfs,
            work_dir=args.work_dir,
        )
    if args.command == "version":
        return version()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
