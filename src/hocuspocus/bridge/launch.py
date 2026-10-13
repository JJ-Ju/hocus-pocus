"""Find a Houdini install and launch GUI or headless Houdini. See docs/BIBLE.md §3.3 rule 6.

Launching is detached: the child never inherits the bridge's stdio (which carries MCP).
After spawning, the launcher polls the instance registry until the new host registers.
Tests inject ``spawner``/``scan``/``sleep`` so nothing is actually launched.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ..tools import paths
from ..tools.errors import ToolError
from . import instances as registry

EXE = ".exe" if sys.platform == "win32" else ""
DEFAULT_WAIT_S = 90.0
POLL_INTERVAL_S = 0.5
LAUNCHED_BY_ENV = "HOCUSPOCUS_LAUNCHED_BY"
"""Set in a launched Houdini's environment to this bridge's pid; the host copies it into
its registry entry as ``launched_by`` (shown in ``houdini_status.instances[]``)."""


# -- HFS detection -------------------------------------------------------------------------


def _version_key(path: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", Path(path).name)
    return tuple(int(n) for n in nums)


def _candidate_globs() -> list[tuple[str, str]]:
    """(glob, suffix-to-HFS) pairs for standard install locations, newest wins."""
    if sys.platform == "win32":
        roots = {os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"C:\Program Files"}
        return [(str(Path(r) / "Side Effects Software" / "Houdini 22.*"), "") for r in roots]
    if sys.platform == "darwin":
        return [
            (
                "/Applications/Houdini/Houdini22.*",
                "Frameworks/Houdini.framework/Versions/Current/Resources",
            )
        ]
    return [("/opt/hfs22.*", "")]


def hython_path(hfs: Path) -> Path:
    return hfs / "bin" / f"hython{EXE}"


def is_hfs(path: Path) -> bool:
    return hython_path(path).is_file()


def detect_hfs(
    config_hfs: str | None = None, environ: Mapping[str, str] | None = None
) -> Path | None:
    """``config.hfs`` → ``$HFS`` → the newest standard ``Houdini 22.*`` install."""
    env = os.environ if environ is None else environ
    for explicit in (config_hfs, env.get("HOCUSPOCUS_HFS"), env.get("HFS")):
        if explicit:
            candidate = Path(explicit)
            if is_hfs(candidate):
                return candidate
    found: list[tuple[tuple[int, ...], Path]] = []
    for pattern, suffix in _candidate_globs():
        for match in glob.glob(pattern):
            candidate = Path(match) / suffix if suffix else Path(match)
            if is_hfs(candidate):
                found.append((_version_key(match), candidate))
    if not found:
        return None
    return max(found)[1]


def gui_executable(hfs: Path) -> Path | None:
    for name in ("houdinifx", "houdini"):
        exe = hfs / "bin" / f"{name}{EXE}"
        if exe.is_file():
            return exe
    return None


def package_root() -> Path:
    """The directory that contains the running ``hocuspocus`` package."""
    return Path(__file__).resolve().parents[2]


LAUNCH_PKG_DIR = "launch-pkg"
_HOST_SIDE_SKIP = frozenset({"bridge", "cli.py", "_houdini", "__pycache__"})


def _read_version(pkg_dir: Path) -> str | None:
    try:
        text = (pkg_dir / "version.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else None


def _usable(python_dir: Path | None, version: str) -> bool:
    """A dir to put on hython's PYTHONPATH: it holds this version's ``hocuspocus`` and is not
    a site-packages directory (which would shadow Houdini's own attrs, click, pydantic...)."""
    if python_dir is None:
        return False
    if any(part.lower() in ("site-packages", "dist-packages") for part in python_dir.parts):
        return False
    return _read_version(python_dir / "hocuspocus") == version


def _installed_python_dir(state: Path) -> Path | None:
    from .config import INSTALL_STATE_FILE

    try:
        data = json.loads((state / INSTALL_STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("python_dir") if isinstance(data, dict) else None
    return Path(value) if isinstance(value, str) and value else None


def _package_json_python_dir(environ: Mapping[str, str] | None) -> Path | None:
    from ..cli import PACKAGE_JSON_NAME, package_python_dir
    from .config import pref_dir_candidates

    for prefs in pref_dir_candidates(environ):
        try:
            data = json.loads((prefs / "packages" / PACKAGE_JSON_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found = package_python_dir(data)
        if found is not None:
            return found
    return None


def _checkout_src(root: Path) -> Path | None:
    """``<checkout>/src`` when the running package is a source checkout (editable install)."""
    if root.name == "src" and (root.parent / "pyproject.toml").is_file():
        return root
    return None


def _copy_host_package(root: Path, state: Path, version: str) -> Path:
    """Copy ``hocuspocus`` without the bridge into ``<state>/launch-pkg/<version>/``."""
    target = state / LAUNCH_PKG_DIR / version
    if _read_version(target / "hocuspocus") == version:
        return target
    staging = state / LAUNCH_PKG_DIR / f".{version}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(
        root / "hocuspocus",
        staging / "hocuspocus",
        ignore=lambda _dir, names: {
            n for n in names if n in _HOST_SIDE_SKIP or n.endswith((".pyc", ".pyo"))
        },
    )
    shutil.rmtree(target, ignore_errors=True)
    try:
        staging.rename(target)
    except OSError:  # another bridge won the race; use its copy
        shutil.rmtree(staging, ignore_errors=True)
    return target


def host_python_dir(
    environ: Mapping[str, str] | None = None,
    *,
    state: Path | None = None,
    root: Path | None = None,
    version: str | None = None,
) -> tuple[Path, str]:
    """The directory a headless hython gets on ``PYTHONPATH``, and where it came from.

    Order: the ``python_dir`` ``install-houdini`` recorded in ``install.json`` -> the
    ``PYTHONPATH`` entry of ``<prefs>/packages/hocuspocus.json`` -> the checkout's ``src/``
    for an editable install -> a host-only copy under ``<state_dir>/launch-pkg/<version>``.
    Each candidate must hold this version's package; a site-packages directory never
    qualifies, because it would shadow SideFX's own packages (BIBLE §3.1).
    """
    from ..version import __version__

    version = version or __version__
    state = state if state is not None else paths.state_dir()
    root = root if root is not None else package_root()
    for source, candidate in (
        ("install.json", _installed_python_dir(state)),
        ("package json", _package_json_python_dir(environ)),
        ("checkout", _checkout_src(root)),
    ):
        if _usable(candidate, version):
            return candidate, source
    return _copy_host_package(root, state, version), LAUNCH_PKG_DIR


# -- spawning ------------------------------------------------------------------------------


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...


Spawner = Callable[[list[str], dict[str, str], Path, Path | None], ProcessHandle]


def default_spawner(argv: list[str], env: dict[str, str], cwd: Path, log_path: Path | None) -> Any:
    """Start ``argv`` detached from the bridge's console and stdio."""
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(log_path, "ab")  # noqa: SIM115 - handed to the child; closed below
    else:
        out = subprocess.DEVNULL
    kwargs["stdout"] = out
    kwargs["stderr"] = subprocess.STDOUT if log_path is not None else subprocess.DEVNULL
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        try:
            proc = subprocess.Popen(argv, **kwargs)
        except OSError:
            if sys.platform == "win32" and kwargs["creationflags"] & getattr(
                subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0
            ):
                # Breakaway is refused inside some job objects; launch without it (and
                # report it: the child then shares the bridge's job and its fate).
                kwargs["creationflags"] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB
                proc = subprocess.Popen(argv, **kwargs)
                proc.hp_breakaway = False  # type: ignore[attr-defined]
                return proc
            raise
        proc.hp_breakaway = sys.platform == "win32" and bool(  # type: ignore[attr-defined]
            kwargs["creationflags"] & getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )
        return proc
    finally:
        if log_path is not None:
            out.close()


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


def child_outlives_server(proc: Any) -> bool:
    """Whether a launched child should survive this bridge process exiting.

    POSIX: the child runs in its own session, so the bridge's exit (and signals to its
    process group) do not reach it. Windows: the child survives unless it shares a job
    object that kills its processes when the job closes (breakaway refused). Neither can
    see a client that kills the bridge's whole process tree, hence "should".
    """
    if sys.platform != "win32":
        return True
    try:
        in_job = _process_in_job(proc._handle)
    except Exception:
        return bool(getattr(proc, "hp_breakaway", False))
    if not in_job:
        return True
    try:
        return not _own_job_kills_on_close()
    except Exception:
        return False


def _process_in_job(handle: Any) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.IsProcessInJob.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    )
    result = wintypes.BOOL()
    if not kernel32.IsProcessInJob(wintypes.HANDLE(int(handle)), None, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), "IsProcessInJob failed")
    return bool(result.value)


def _own_job_kills_on_close() -> bool:
    """True when the job this process runs in kills every member when it closes."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = ExtendedLimits()
    job_object_extended_limit_information = 9
    if not kernel32.QueryInformationJobObject(
        None,
        job_object_extended_limit_information,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    ):
        raise OSError(ctypes.get_last_error(), "QueryInformationJobObject failed")
    return bool(info.BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)


@dataclass(frozen=True, slots=True)
class LaunchResult:
    instance: registry.Instance
    mode: str
    argv: tuple[str, ...]
    log: str | None
    outlives_server: bool = False
    """Whether the child should survive this bridge's exit (:func:`child_outlives_server`)."""


@dataclass(frozen=True, slots=True)
class Spawned:
    """A started Houdini that may not have registered yet."""

    proc: Any
    mode: str
    argv: tuple[str, ...]
    log: str | None
    outlives: bool
    before: frozenset[int]
    """Pids registered before the spawn (a GUI hand-off registers under a new pid)."""


class Launcher:
    def __init__(
        self,
        config_hfs: str | None = None,
        *,
        spawner: Spawner = default_spawner,
        scan: Callable[[], list[registry.Instance]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
        outlives: Callable[[Any], bool] = child_outlives_server,
        launches: registry.LaunchLog | None = None,
        python_dir: Callable[[Mapping[str, str] | None], tuple[Path, str]] = host_python_dir,
        owned: bool = True,
    ) -> None:
        self.config_hfs = config_hfs
        self.owned = owned
        """True for a bridge launch: the child is tagged with ``HOCUSPOCUS_LAUNCHED_BY`` and
        recorded in the launch log. False for ``hocuspocus launch``, whose Houdini belongs
        to no server (the CLI exits at once)."""
        self.spawner = spawner
        self.python_dir = python_dir
        self.outlives = outlives
        self._launches = launches
        self.scan = scan or (lambda: registry.scan())
        self.sleep = sleep
        self.clock = clock
        self.environ = environ

    def _env(self) -> dict[str, str]:
        return dict(os.environ if self.environ is None else self.environ)

    @property
    def launches(self) -> registry.LaunchLog:
        return self._launches or registry.LaunchLog()

    def build(
        self, mode: str, hip: str | None, work_dir: Path | None = None
    ) -> tuple[list[str], dict[str, str], Path, Path | None]:
        """argv, environment, cwd and log path for one launch. ``work_dir`` is the
        untitled scene's ``$HIP``/``$JOB``: ``hocuspocus launch`` passes the directory it
        ran in (or ``--work-dir``); ``None`` (``houdini_connect {launch}``) keeps
        ``HOCUSPOCUS_WORK_DIR``, else home."""
        hfs = detect_hfs(self.config_hfs, self.environ)
        if hfs is None:
            raise ToolError(
                "houdini_offline",
                "Cannot launch Houdini: no Houdini 22 install was found.",
                hint="set HOCUSPOCUS_HFS (or HFS) in the MCP server's environment to the Houdini install dir",
            )
        env = self._env()
        env.setdefault("HFS", str(hfs))
        if self.owned:
            env[LAUNCHED_BY_ENV] = str(os.getpid())
        else:
            env.pop(LAUNCHED_BY_ENV, None)
        # The untitled scene's $HIP/$JOB: renders to $HIP/... must not land in the state
        # dir next to instances/ and logs/ (review 07 papercut 3).
        cwd = paths.work_dir() if work_dir is None else Path(work_dir)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        if mode == "gui":
            exe = gui_executable(hfs)
            if exe is None:
                raise ToolError(
                    "houdini_offline",
                    f"Cannot launch Houdini: no houdinifx/houdini executable under {hfs / 'bin'}.",
                    hint="use launch mode 'headless', or point HOCUSPOCUS_HFS at a full install",
                )
            argv = [str(exe)]
            if hip:
                argv.append(hip)
            return argv, env, cwd, None
        if mode == "headless":
            argv = [str(hython_path(hfs)), "-m", "hocuspocus.host"]
            if hip:
                argv += ["--hip", hip]
            if work_dir is not None:
                # The host moves to its work dir at start (HOCUSPOCUS_WORK_DIR, else home)
                # unless told which one; a GUI's $HIP simply follows its cwd.
                argv += ["--work-dir", str(cwd)]
            python_dir, _source = self.python_dir(self.environ)
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(python_dir) + (os.pathsep + existing if existing else "")
            log_path = paths.logs_dir() / f"launch-headless-{stamp}.log"
            return argv, env, cwd, log_path
        raise ToolError(
            "invalid_argument", f"Unknown launch mode {mode!r}.", hint="use 'gui' or 'headless'"
        )

    def spawn(
        self, mode: str, hip: str | None = None, *, work_dir: str | Path | None = None
    ) -> Spawned:
        """Start Houdini without waiting for it to register (``work_dir``: see ``build``)."""
        if hip:
            # Resolved here: the child starts in the work dir, not this process's cwd.
            hip = str(Path(hip).expanduser().resolve())
            if not Path(hip).is_file():
                raise ToolError(
                    "file_not_found",
                    f"Hip file not found: {hip}",
                    hint="pass an existing .hip path or omit hip",
                )
        if work_dir is not None:
            work_dir = Path(work_dir).expanduser().resolve()
            try:
                work_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ToolError(
                    "invalid_argument",
                    f"Cannot use {work_dir} as the work directory: {exc}",
                    hint="pass an existing or creatable directory",
                ) from exc
        argv, env, cwd, log_path = self.build(mode, hip, work_dir)
        before = frozenset(inst.pid for inst in self.scan())
        try:
            proc = self.spawner(argv, env, cwd, log_path)
        except OSError as exc:
            raise ToolError(
                "houdini_offline",
                f"Failed to start {argv[0]}: {exc}",
                hint="check the Houdini install and licence",
            ) from exc
        try:
            outlives = bool(self.outlives(proc))
        except Exception:
            outlives = False
        return Spawned(
            proc, mode, tuple(argv), str(log_path) if log_path else None, outlives, before
        )

    def wait(self, spawned: Spawned, wait_s: float = DEFAULT_WAIT_S) -> LaunchResult:
        """Poll the registry until the spawned Houdini's host registers."""
        proc, mode, log_text = spawned.proc, spawned.mode, spawned.log
        deadline = self.clock() + max(0.0, float(wait_s))
        while True:
            live = self.scan()
            found = next((inst for inst in live if inst.pid == proc.pid), None)
            if found is None and mode == "gui":
                # GUI launchers can hand off to a child process: accept a new registration.
                # Headless hython never does, so only its own pid counts there.
                found = next((inst for inst in live if inst.pid not in spawned.before), None)
            if found is not None:
                if self.owned:
                    self.launches.record(found, mode=mode, outlives_server=spawned.outlives)
                return LaunchResult(found, mode, spawned.argv, log_text, spawned.outlives)
            code = proc.poll()
            if code is not None:
                raise ToolError(
                    "houdini_offline",
                    f"Houdini (pid {proc.pid}) exited with code {code} before HocusPocus registered.",
                    hint=_failure_hint(mode, log_text),
                    detail={"argv": list(spawned.argv), "log": log_text},
                )
            if self.clock() >= deadline:
                raise ToolError(
                    "houdini_offline",
                    f"Started Houdini (pid {proc.pid}) but its HocusPocus host did not register within "
                    f"{wait_s:g}s. It may still be starting (licence check, large hip).",
                    hint=_failure_hint(mode, log_text),
                    detail={"pid": proc.pid, "argv": list(spawned.argv), "log": log_text},
                )
            self.sleep(POLL_INTERVAL_S)

    def launch(
        self, mode: str, hip: str | None = None, wait_s: float = DEFAULT_WAIT_S
    ) -> LaunchResult:
        return self.wait(self.spawn(mode, hip), wait_s)


def _failure_hint(mode: str, log_path: str | None) -> str:
    if mode == "gui":
        return (
            "call houdini_status again in a little while; if it never appears, run "
            "`hocuspocus install-houdini` (the GUI needs the package to autostart the host) "
            "and `hocuspocus doctor`"
        )
    where = f" (log: {log_path})" if log_path else ""
    return f"read the hython output{where}; `hocuspocus doctor` checks the setup"
