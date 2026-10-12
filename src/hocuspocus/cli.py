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


def run_hython(hfs: Path, code: str, timeout_s: float) -> str | None:
    """Run ``hython -c code`` from a neutral cwd; return the last stdout line or ``None``."""
    env = dict(os.environ)
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
        return None
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None


@dataclass(frozen=True, slots=True)
class PrefDir:
    path: Path
    source: str


def platform_default_pref_dir(environ: Mapping[str, str] | None = None) -> Path:
    """The first existing default pref dir, in the bridge's order (``%USERPROFILE%`` then
    ``Documents`` on Windows), else the first: install and bridge must agree on it."""
    from .bridge.config import default_pref_dirs

    candidates = default_pref_dirs(environ)
    return next((path for path in candidates if path.is_dir()), candidates[0])


def resolve_pref_dir(
    flag: str | None,
    *,
    hfs: str | None = None,
    environ: Mapping[str, str] | None = None,
    hython_query: Callable[[Path], str | None] | None = None,
) -> PrefDir:
    """``--prefs`` → ``$HOUDINI_USER_PREF_DIR`` → hython's ``homeHoudiniDirectory()`` → default."""
    env = os.environ if environ is None else environ
    if flag:
        return PrefDir(Path(flag).expanduser(), "--prefs")
    from_env = env.get("HOUDINI_USER_PREF_DIR", "")
    if from_env and "__HVER__" not in from_env:
        return PrefDir(Path(from_env).expanduser(), "HOUDINI_USER_PREF_DIR")
    found = _detect_hfs(hfs)
    if found is not None:
        query = hython_query or (
            lambda h: run_hython(
                h, "import hou; print(hou.homeHoudiniDirectory())", HYTHON_QUERY_TIMEOUT_S
            )
        )
        answer = query(found)
        if answer:
            return PrefDir(Path(answer), f"hython ({found})")
    return PrefDir(platform_default_pref_dir(env), "platform default")


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


def install(prefs: Path, *, dev: bool, out: Callable[[str], None] = print) -> int:
    install_root = prefs / INSTALL_DIR_NAME
    payload = payload_source()
    if dev:
        root = checkout_root()
        if root is None:
            out("error: --dev needs a source checkout (src/hocuspocus next to pyproject.toml).")
            return 2
        python_dir = root / "src"
        payload_dir = payload
        out(f"dev install: Houdini will import hocuspocus from {python_dir}")
        for old in copied_installs(prefs):
            # A copy from an earlier non-dev install would only confuse doctor and users.
            shutil.rmtree(old, ignore_errors=True)
            out(f"removed copied install {old} (the dev install uses the checkout)")
    else:
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
    if payload_dir is None:
        out("warning: no Houdini payload (houdini/) found; GUI autostart will not be installed.")
    text, used = render_package_json(python_dir, payload_dir, template_source())
    packages = prefs / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    target = packages / PACKAGE_JSON_NAME
    _write_atomic(target, text)
    out(f"wrote {target} (template: {used})")
    record = write_install_state(prefs, python_dir, dev=dev)
    if record is not None:
        out(f"recorded the pref dir in {record} (the bridge reads hocuspocus.toml from there)")
    out("Restart Houdini to load HocusPocus.")
    out(f"Then register the MCP server with your client, e.g.: {CLAUDE_SNIPPET}")
    return 0


def write_install_state(prefs: Path, python_dir: Path, *, dev: bool) -> Path | None:
    """Record ``prefs`` in ``<state_dir>/install.json`` for the bridge (BIBLE §3.7).

    The bridge starts on every MCP client launch and cannot afford a hython query to find
    the pref dir, so ``install-houdini`` remembers where it installed. Best effort.
    """
    from .bridge.config import INSTALL_STATE_FILE
    from .tools.paths import ensure_private_dir, state_dir

    data = {
        "prefs": _posix(prefs.resolve()),
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


def _forget_install_state(prefs: Path) -> None:
    from .bridge.config import INSTALL_STATE_FILE, installed_pref_dir
    from .tools.paths import state_dir

    recorded = installed_pref_dir()
    if recorded is not None and recorded.resolve() == prefs.resolve():
        with contextlib.suppress(OSError):
            (state_dir() / INSTALL_STATE_FILE).unlink()


def uninstall(prefs: Path, *, out: Callable[[str], None] = print) -> int:
    _forget_install_state(prefs)
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
            return 1
        out(f"removed {install_root}")
        removed = True
    if not removed:
        out(f"nothing to remove under {prefs}")
    else:
        out("Restart Houdini to unload HocusPocus.")
    return 0


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


def _read_version(pkg_dir: Path) -> str | None:
    try:
        text = (pkg_dir / "version.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


def doctor(args: argparse.Namespace, out: Callable[[str], None] = print) -> int:
    report = Report(out)
    out(f"hocuspocus {__version__} (bridge, hp/v{catalog.HP_RPC_VERSION})")

    hfs = _detect_hfs(args.hfs)
    if hfs is None:
        report.fail(
            "Houdini install", "not found; set HFS or pass --hfs (needed to launch Houdini)"
        )
    else:
        report.ok("Houdini install", str(hfs))
        version = run_hython(
            hfs, "import hou; print(hou.applicationVersionString())", HYTHON_VERSION_TIMEOUT_S
        )
        if version is None:
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

    prefs = resolve_pref_dir(args.prefs, hfs=args.hfs)
    report.ok("Houdini pref dir", f"{prefs.path} (from {prefs.source})")
    from .bridge.config import find_config_file

    toml = find_config_file()
    expected = prefs.path / "hocuspocus.toml"
    if toml is None and expected.is_file():
        report.warn(
            "hocuspocus.toml",
            f"{expected} exists but the bridge cannot find it; run `hocuspocus install-houdini` "
            "or set HOUDINI_USER_PREF_DIR for the MCP client",
        )
    else:
        report.ok(
            "hocuspocus.toml",
            f"{toml} (host and bridge; HOCUSPOCUS_* env overrides)" if toml else "none (defaults)",
        )
    pkg_json = prefs.path / "packages" / PACKAGE_JSON_NAME
    if not pkg_json.is_file():
        report.fail("package JSON", f"{pkg_json} missing; run `hocuspocus install-houdini`")
    else:
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report.fail("package JSON", f"{pkg_json} is not valid JSON ({exc})")
        else:
            python_dir = package_python_dir(data)
            if python_dir is None:
                report.fail("package JSON", f"{pkg_json} has no PYTHONPATH entry")
            elif not (python_dir / "hocuspocus").is_dir():
                report.fail(
                    "package JSON", f"PYTHONPATH {python_dir} has no hocuspocus package; reinstall"
                )
            else:
                report.ok("package JSON", f"{pkg_json} -> {python_dir}")
                leftovers = [p for p in copied_installs(prefs.path) if p not in python_dir.parents]
                if leftovers:
                    report.warn(
                        "copied installs",
                        f"{', '.join(str(p) for p in leftovers)} not used by the package "
                        "JSON (left by an earlier install); run `hocuspocus install-houdini` "
                        "(with --dev for a checkout) to remove them",
                    )
                host_version = _read_version(python_dir / "hocuspocus")
                if host_version == __version__:
                    report.ok("host/bridge version", host_version)
                else:
                    report.fail(
                        "host/bridge version",
                        f"Houdini has {host_version or 'unknown'}, bridge is {__version__}; "
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
    out: Callable[[str], None] = print,
    err: Callable[[str], None] | None = None,
) -> int:
    """``hocuspocus launch``: start a Houdini that belongs to no MCP server.

    The Houdini is started detached from this process, which exits once its host has
    registered (or at once with ``--wait 0``), so it outlives every MCP client. stdout
    gets one JSON object: the registry entry (no token), the mode and, headless, the log.
    """
    from .tools.errors import ToolError

    err = err or (lambda text: print(text, file=sys.stderr))
    launcher = _launcher(hfs)
    try:
        spawned = launcher.spawn(mode, hip)
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
    err(
        f"Houdini pid {result.instance.pid} is running and outlives this command; attach "
        f'from an MCP client with houdini_connect {{"pid": {result.instance.pid}}}.'
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
        "--prefs", help="Houdini user pref dir (default: HOUDINI_USER_PREF_DIR, then ask hython)"
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
        "exit. The Houdini keeps running; attach to it with houdini_connect {pid}.",
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

    sub.add_parser("version", help="print versions")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install-houdini":
        prefs = resolve_pref_dir(args.prefs, hfs=args.hfs)
        print(f"Houdini pref dir: {prefs.path} (from {prefs.source})")
        return install(prefs.path, dev=args.dev)
    if args.command == "uninstall-houdini":
        prefs = resolve_pref_dir(args.prefs, hfs=args.hfs)
        return uninstall(prefs.path)
    if args.command == "doctor":
        return doctor(args)
    if args.command == "client-config":
        return client_config(args.client)
    if args.command == "docs":
        return docs_tools(args.output)
    if args.command == "launch":
        return launch_houdini(
            "headless" if args.headless else "gui", args.hip, args.wait, hfs=args.hfs
        )
    if args.command == "version":
        return version()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
