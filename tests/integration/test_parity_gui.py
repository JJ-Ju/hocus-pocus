"""The GUI column of docs/parity.md: a scripted ``houdinifx`` session (spec-2.0 §5.3).

Runs in the dev venv's Python, not in hython::

    .venv/Scripts/python -m pytest tests/integration/test_parity_gui.py --rungui -q

One session fixture launches ``houdinifx`` through :mod:`hocuspocus.bridge.launch` with an
isolated ``HOUDINI_USER_PREF_DIR`` (the dev package JSON and a ``profile = "full"`` toml
in it; the rows the 1.4 tools had call their 2.0 forms since 2.1), an
isolated ``HOCUSPOCUS_STATE_DIR`` and an ephemeral port, waits for the registry entry
and drives the host over ``POST /hp/v1/call`` with the bridge's own
:class:`~hocuspocus.bridge.client.HostClient`. The tests assert the ``mode`` rows of the
matrix: what a GUI session does differently from a headless one. A GUI window appears on
the desktop; ``test_quit_closes_the_gui`` (last) closes it with ``houdini_connect {quit}``
and the fixture kills whatever it started if that failed.

A "manual" edit is code scheduled with ``hdefereval.executeDeferred`` from
``houdini_python``: it runs on the next idle tick, after the call returned, outside every
HocusPocus undo group and outside the executor, so Houdini and the host see it as the
user's (review 15 §1). ``hdefereval`` imports only in a graphical Houdini.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.gui]

REPO = Path(__file__).resolve().parents[2]
DEV_PACKAGE = Path.home() / "houdini22.0" / "packages" / "hocuspocus.json"
"""The dev package ``install-houdini --dev`` writes; copied into the isolated prefs."""
ON_CREATED = """\
node = kwargs["node"]
if node.name().startswith("dialog_made"):
    hou.ui.displayMessage("HocusPocus G5 test: a creation script dialog")
"""
LOAD_SCRIPT = """\
import hou
if hou.hipFile.basename().startswith("dialog_456"):
    hou.ui.displayMessage("HocusPocus G5 test: a load script dialog")
"""
LAUNCH_WAIT_S = 240.0
CALL_TIMEOUT_S = 60.0
FORBIDDEN_PORT = 37219

VIEW_STATE = """
viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
viewport = viewer.curViewport()
view = viewport.defaultCamera()
camera = viewport.camera()
result = {
    "camera": camera.path() if camera is not None else None,
    "translation": [round(v, 4) for v in view.translation()],
    "rotation": [round(v, 4) for v in view.rotation().asTuple()],
    "pivot": [round(v, 4) for v in view.pivot()],
}
"""
PANES = """
kinds = (hou.paneTabType.SceneViewer, hou.paneTabType.NetworkEditor)
result = {t.name(): t.pwd().path() for t in hou.ui.paneTabs() if t.type() in kinds}
"""
PANES_TO_OBJ = """
kinds = (hou.paneTabType.SceneViewer, hou.paneTabType.NetworkEditor)
for t in hou.ui.paneTabs():
    if t.type() in kinds:
        t.setPwd(hou.node('/obj'))
hou.clearAllSelected()
"""


def _check_output_schema(tool: str, result: Any) -> None:
    """As ``conftest.check_output_schema``: results satisfy the catalogue's outputSchema."""
    from hocuspocus.tools.catalog import get
    from hocuspocus.tools.docs import validate

    spec = get(tool)
    if spec is None or spec.bridge_local or spec.output_schema is None:
        return
    validate(result, spec.output_schema, tool)


class GuiClient:
    """``/hp/v1/call`` against the GUI host, with the integration client's ``ok``/``error``."""

    def __init__(self, port: int, token: str) -> None:
        from hocuspocus.bridge.client import HostClient

        self.http = HostClient(port, token)

    def call(
        self, tool: str, args: dict[str, Any] | None = None, timeout_s: float = CALL_TIMEOUT_S
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        return self.http.call(tool, args or {}, timeout_s)

    def ok(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        ok, result, _meta = self.call(tool, args, **kw)
        assert ok is True, result
        _check_output_schema(tool, result)
        return result

    def error(self, tool: str, args: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
        ok, result, _meta = self.call(tool, args, **kw)
        assert ok is False, result
        return result

    def python(self, code: str) -> Any:
        return self.ok("houdini_python", {"code": code})["result"]

    def view_state(self) -> dict[str, Any]:
        return self.python(VIEW_STATE)

    def user_edit(self, code: str) -> None:
        """Run ``code`` (with ``hou`` bound) as the user would: deferred to Houdini's next
        idle tick, outside this call's undo group and outside the executor."""
        body = "".join(f"    {line}\n" for line in code.strip().splitlines())
        self.python(
            f"import hdefereval\ndef _user_edit():\n{body}hdefereval.executeDeferred(_user_edit)\n"
        )

    def user_edit_after_save(self, code: str, hip_name: str) -> None:
        """:meth:`user_edit`, held back until the scene is saved as ``hip_name``: the
        ``houdini_python`` call that schedules it is itself an agent mutation (tracked
        dirty), so the test saves after it and the user's edit lands on a clean scene."""
        body = "".join(f"    {line}\n" for line in code.strip().splitlines())
        self.python(
            "import hdefereval\n"
            "def _user_edit():\n"
            f"    if not hou.hipFile.path().endswith({hip_name!r}):\n"
            "        hdefereval.executeDeferredAfterWaiting(_user_edit, 5)\n"
            "        return\n"
            f"{body}"
            "hdefereval.executeDeferred(_user_edit)\n"
        )


@dataclass
class GuiSession:
    client: GuiClient
    instance: Any
    proc: Any
    state_dir: Path
    work_dir: Path


def _pid_alive(pid: int) -> bool:
    from hocuspocus.host.registry import pid_alive

    return pid_alive(pid)


def _kill(pid: int) -> None:
    """Kill a process this fixture started (and its children), if it is still running."""
    if not _pid_alive(pid):
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    else:  # pragma: no cover - the GUI runner is Windows today
        import signal

        os.kill(pid, signal.SIGKILL)


def _houdini_version(hfs: Path) -> str:
    match = re.search(r"(\d+)\.(\d+)", hfs.name)
    return f"{match.group(1)}.{match.group(2)}" if match else "22.0"


def _package_json() -> str:
    """The dev package: the user's own ``--dev`` package JSON when it points at this
    checkout, else the same content rendered for it."""
    try:
        text = DEV_PACKAGE.read_text(encoding="utf-8")
        data = json.loads(text)
        if Path(str(data.get("hpath", ""))).resolve() == (REPO / "houdini").resolve():
            return text
    except (OSError, ValueError):
        pass
    from hocuspocus.version import __version__

    return json.dumps(
        {
            "load_package_once": True,
            "env": [
                {"HOCUSPOCUS_VERSION": __version__},
                {"PYTHONPATH": {"value": (REPO / "src").as_posix(), "method": "prepend"}},
            ],
            "hpath": (REPO / "houdini").as_posix(),
        },
        indent=4,
    )


@dataclass
class Isolated:
    """An isolated pref dir, state dir and work dir for one ``houdinifx`` launch."""

    launcher: Any
    state: Path
    work: Path
    prefs: Path
    """The expanded pref dir (``houdini22.0``) Houdini reads."""


def _isolated(base: Path, *, extra_env: dict[str, str] | None = None) -> Isolated:
    """A launcher for ``houdinifx`` with its own prefs (the dev package JSON and a
    ``profile = "full"`` toml), state and work dirs under ``base``."""
    from hocuspocus.bridge import instances as registry
    from hocuspocus.bridge.launch import Launcher, detect_hfs, gui_executable

    hfs = detect_hfs(None)
    if hfs is None or gui_executable(hfs) is None:
        pytest.skip("no Houdini 22 install with houdinifx found (set HOCUSPOCUS_HFS or HFS)")
    state, work, prefs = base / "state", base / "work", base / "prefs"
    expanded = prefs / f"houdini{_houdini_version(hfs)}"
    (expanded / "packages").mkdir(parents=True)
    state.mkdir()
    work.mkdir()
    (expanded / "packages" / "hocuspocus.json").write_text(_package_json(), encoding="utf-8")
    (expanded / "hocuspocus.toml").write_text('profile = "full"\n', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOCUSPOCUS_")}
    env.pop("PYTHONHOME", None)
    env.update(
        HOUDINI_USER_PREF_DIR=(prefs / "houdini__HVER__").as_posix(),
        HOCUSPOCUS_STATE_DIR=str(state),
        HOCUSPOCUS_WORK_DIR=str(work),
        HOUDINI_NO_START_PAGE_SPLASH="1",
        HOUDINI_ANONYMOUS_STATISTICS="0",
        **(extra_env or {}),
    )
    instances_dir = state / "instances"
    launcher = Launcher(
        str(hfs), environ=env, owned=False, scan=lambda: registry.scan(instances_dir)
    )
    return Isolated(launcher, state, work, expanded)


@pytest.fixture(scope="session")
def gui(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GuiSession]:
    iso = _isolated(tmp_path_factory.mktemp("hp-gui"))
    # G5: a creation script and a load script that open a dialog, each only for the one
    # node or hip file its test makes (Houdini reads the script paths at start-up).
    (iso.prefs / "scripts" / "obj").mkdir(parents=True)
    (iso.prefs / "scripts" / "obj" / "null_OnCreated.py").write_text(ON_CREATED, encoding="utf-8")
    (iso.prefs / "scripts" / "456.py").write_text(LOAD_SCRIPT, encoding="utf-8")
    spawned = iso.launcher.spawn("gui", work_dir=iso.work)
    started = {spawned.proc.pid}
    session: GuiSession | None = None
    try:
        launched = iso.launcher.wait(spawned, LAUNCH_WAIT_S)
        inst = launched.instance
        started.add(inst.pid)
        assert inst.port != FORBIDDEN_PORT
        session = GuiSession(
            GuiClient(inst.port, inst.token), inst, spawned.proc, iso.state, iso.work
        )
        yield session
    finally:
        if session is not None and _pid_alive(session.instance.pid):
            try:
                session.client.http.quit("discard", timeout_s=30.0)
                deadline = time.monotonic() + 30.0
                while _pid_alive(session.instance.pid) and time.monotonic() < deadline:
                    time.sleep(0.5)
            except Exception:
                pass
        for pid in started:
            _kill(pid)


def _wait_for(probe: Any, timeout_s: float = 15.0, interval_s: float = 0.25) -> Any:
    """Call ``probe`` until it returns something truthy (a deferred edit has run)."""
    deadline = time.monotonic() + timeout_s
    while True:
        value = probe()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(interval_s)


def _scene(client: GuiClient) -> None:
    """A fresh untitled scene with one displayed box."""
    client.ok("hip_new", {"on_unsaved": "discard"})
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "box_geo"},
                {
                    "parent": "/obj/box_geo",
                    "type": "box",
                    "name": "box1",
                    "flags": {"display": True, "render": True},
                },
            ]
        },
    )


# -- launches that cannot register (D60), before the session's Houdini starts ------------

STARTUP_DIALOG = """\
import hou
hou.ui.displayMessage("HocusPocus D60 test: a startup dialog")
"""


def _launch_fails(iso: Isolated, wait_s: float) -> tuple[Any, float, Any]:
    """Launch, expect the wait to fail, and kill the Houdini. ``(error, seconds, proc)``."""
    from hocuspocus.tools.errors import ToolError

    spawned = iso.launcher.spawn("gui", work_dir=iso.work)
    started = time.monotonic()
    try:
        with pytest.raises(ToolError) as info:
            iso.launcher.wait(spawned, wait_s)
        return info.value, time.monotonic() - started, spawned.proc
    finally:
        _kill(spawned.proc.pid)


def test_a_launch_stuck_on_a_startup_dialog_says_so(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """D60: a startup script's dialog holds Houdini before its UI is ready, so the host
    never starts. The launch names the window soon after it appears, not at ``wait_s``."""
    from hocuspocus.bridge import startup

    iso = _isolated(tmp_path_factory.mktemp("hp-dialog"))
    (iso.prefs / "scripts").mkdir()
    (iso.prefs / "scripts" / "123.py").write_text(STARTUP_DIALOG, encoding="utf-8")
    error, waited, _proc = _launch_fails(iso, LAUNCH_WAIT_S)
    assert error.code == "houdini_offline" and error.retryable is False, error
    assert error.detail["reason"] == "dialog", error.detail
    assert error.detail["windows"] == ["Houdini"]
    assert "waiting on a window titled 'Houdini'" in error.message
    assert waited < startup.DIALOG_GRACE_S + 30, waited


def test_a_launch_whose_host_fails_to_start_says_why(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """D60: a host that cannot start (here its configured port is taken) writes a
    ``failed`` startup record, and the launch answers with its error at once."""
    import socket

    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen(1)
    port = taken.getsockname()[1]
    assert port != FORBIDDEN_PORT
    try:
        iso = _isolated(
            tmp_path_factory.mktemp("hp-hostfail"), extra_env={"HOCUSPOCUS_PORT": str(port)}
        )
        error, waited, proc = _launch_fails(iso, LAUNCH_WAIT_S)
    finally:
        taken.close()
    assert error.code == "houdini_offline" and error.retryable is False, error
    assert error.detail["reason"] == "host_failed", error.detail
    assert "its HocusPocus host failed to start" in error.message
    assert error.detail["log"].endswith(f"host-{proc.pid}.log")
    assert waited < 60, waited


# -- the session -------------------------------------------------------------------------


def test_host_runs_the_gui_backend(gui: GuiSession) -> None:
    health = gui.client.http.health()
    assert health["ui"] is True
    assert gui.instance.ui is True
    assert gui.instance.label.startswith("houdini")  # houdinifx, not hython
    assert gui.client.python("hou.isUIAvailable()") is True
    status = gui.client.python(
        "import hocuspocus.host as h\ns = h.status()\n"
        "result = {'backend': s['backend'], 'port': s['port']}"
    )
    assert status["backend"] == "gui"
    assert status["port"] == gui.instance.port


def test_viewer_capture_fits_and_restores_the_view(gui: GuiSession) -> None:
    client = gui.client
    _scene(client)
    before = client.view_state()
    assert before["camera"] is None  # the free perspective view

    # source viewer in the GUI, /obj, no camera: the Scene Viewer as it is (parity: mode).
    as_is = client.ok("look", {"source": "viewer", "resolution": [320, 240]})
    assert as_is["backend_used"] == "viewer"
    assert as_is["fit_used"] == "none"
    assert as_is["image"]["png_base64"]
    assert client.view_state() == before

    # An explicit fit frames the free view for the grab only.
    fitted = client.ok("look", {"source": "viewer", "fit": "all", "resolution": [320, 240]})
    assert fitted["backend_used"] == "viewer"
    assert fitted["fit_used"] == "all"
    assert fitted["image"]["png_base64"] != as_is["image"]["png_base64"]
    assert client.view_state() == before

    # A camera: looked through for the grab, then the view and camera are put back.
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "cam", "name": "cam1"}]})
    client.ok("parm_set", {"items": [{"path": "/obj/cam1/t", "value": [0, 1, 6]}]})
    through = client.ok(
        "look", {"source": "viewer", "camera": "/obj/cam1", "resolution": [320, 240]}
    )
    assert through["camera_used"] == "/obj/cam1"
    assert client.view_state() == before


def test_rop_capture_runs_in_process(gui: GuiSession) -> None:
    """look auto renders a temporary viewport ROP in the GUI process: no kept
    child hython (headless only), and the user's view is untouched."""
    client = gui.client
    _scene(client)
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "cam", "name": "cam1"}]})
    before = client.view_state()
    shot = client.ok("look", {"camera": "/obj/cam1", "resolution": [320, 240]})
    assert shot["backend_used"] in ("flipbook", "opengl")
    assert shot["camera_used"] == "/obj/cam1"
    framed = client.ok("look", {"fit": "all", "resolution": [320, 240]})
    assert framed["fit_used"] == "all"
    assert framed["camera_used"] == "temporary"
    assert client.view_state() == before
    warm = client.python(
        "import hocuspocus.host.tools.visual as v\nresult = v._warm['child'] is None"
    )
    assert warm is True
    # The temporary camera and ROP were deleted.
    left = client.python(
        "result = [n.path() for n in hou.node('/').allSubChildren() "
        "if n.userData('hocuspocus:internal')]"
    )
    assert left == []


def test_look_at_a_sop_in_a_subnet_shows_it_alone_in_process(gui: GuiSession) -> None:
    """D52 in the GUI: the temporary object that shows a SOP alone is made in the live
    scene, outside undo, and deleted; the user's flags and view stay as they were, and
    source viewer says it is not isolated (Karma: ``test_karma_looks_render_in_the_gui``)."""
    client = gui.client
    _scene(client)
    client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "sub", "parent": "/obj/box_geo", "type": "subnet"},
                {"op": "create", "parent": "$sub", "type": "torus", "name": "ring"},
            ]
        },
    )
    before = client.view_state()
    undo_before = client.python("result = list(hou.undos.undoLabels())")
    alone = client.ok("look", {"target": "/obj/box_geo/subnet1/ring", "resolution": [320, 240]})
    assert alone["backend_used"] in ("flipbook", "opengl") and alone["fit_used"] == "target"
    assert any("alone" in n for n in alone["notes"]), alone
    viewer = client.ok("look", {"target": "/obj/box_geo/subnet1/ring", "source": "viewer"})
    assert any("as the user sees it" in n for n in viewer["notes"]), viewer
    assert client.view_state() == before
    assert client.python("result = list(hou.undos.undoLabels())") == undo_before
    left = client.python(
        "result = [n.path() for n in hou.node('/').allSubChildren() "
        "if n.userData('hocuspocus:internal')]"
    )
    assert left == []
    assert client.python("result = hou.node('/obj/box_geo').displayNode().name()") == "box1"


def _contrast(result: dict[str, Any]) -> int:
    import base64
    import io

    image_mod = pytest.importorskip("PIL.Image")
    image = image_mod.open(io.BytesIO(base64.b64decode(result["image"]["png_base64"])))
    lo, hi = image.convert("L").getextrema()
    return hi - lo


STAGE_SPHERE = """
ball = hou.node('/stage').createNode('sphere', 'ball')
ball.setDisplayFlag(True)
"""


def test_karma_looks_render_in_the_gui(gui: GuiSession) -> None:
    """``look`` lit (no lights) and final render with a temporary Karma ROP in the GUI
    process: of /obj, of a SOP alone and of a stage; and ``render`` of the user's Karma
    ROP writes its frame. A GUI Houdini starts husk in the background unless the ROP's
    Block Until Render Complete is on, so render() returned before the image existed:
    every GUI Karma look answered cook_failed "no output file" in 2.0 and 2.1 (hython
    always waits)."""
    client = gui.client
    _scene(client)
    client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "sub", "parent": "/obj/box_geo", "type": "subnet"},
                {"op": "create", "parent": "$sub", "type": "torus", "name": "ring"},
            ]
        },
    )
    before = client.view_state()
    res = [160, 120]
    lit = client.ok("look", {"quality": "lit", "resolution": res})
    assert lit["backend_used"] == "karma" and lit["samples"] == 2, lit
    assert any("no lights" in n for n in lit["notes"]), lit
    assert _contrast(lit) > 20
    final = client.ok("look", {"quality": "final", "resolution": res})
    assert final["backend_used"] == "karma" and final["samples"] == 32, final
    assert _contrast(final) > 20
    alone = client.ok(
        "look", {"target": "/obj/box_geo/subnet1/ring", "quality": "final", "resolution": res}
    )
    assert alone["backend_used"] == "karma" and alone["fit_used"] == "target", alone
    assert _contrast(alone) > 20
    client.python(STAGE_SPHERE)
    stage = client.ok("look", {"target": "/stage", "quality": "final", "resolution": res})
    assert stage["backend_used"] == "karma" and stage["scene"] == "stage", stage
    assert _contrast(stage) > 20
    assert client.view_state() == before
    left = client.python(
        "result = [n.path() for n in hou.node('/').allSubChildren() "
        "if n.userData('hocuspocus:internal')]"
    )
    assert left == []

    # The user's own Karma ROP with Block Until Render Complete off (its default): render
    # turns it on for the render and puts it back.
    client.ok(
        "edit",
        {
            "ops": [
                {"op": "create", "id": "cam", "parent": "/obj", "type": "cam", "name": "shot"},
                {"op": "set", "path": "$cam/t", "value": [0, 1, 6]},
                {"op": "create", "id": "rop", "parent": "/out", "type": "karma", "name": "beauty"},
                {"op": "set", "path": "$rop/camera", "value": "/obj/shot"},
                {"op": "set", "path": "$rop/resolutionx", "value": 160},
                {"op": "set", "path": "$rop/resolutiony", "value": 120},
                {"op": "set", "path": "$rop/samplesperpixel", "value": 2},
            ]
        },
    )
    assert client.python("hou.parm('/out/beauty/soho_foreground').eval()") == 0
    out = (gui.work_dir / "render" / "beauty.$F4.exr").as_posix()
    rendered = client.ok(
        "render", {"rop_path": "/out/beauty", "frames": [1, 1], "output": out, "wait_s": 60}
    )
    assert rendered["state"] == "done" and "missing" not in rendered, rendered
    assert (gui.work_dir / "render" / "beauty.0001.exr").is_file()
    assert client.python("hou.parm('/out/beauty/soho_foreground').eval()") == 0


def test_time_moves_the_playbar_and_captures_do_not(gui: GuiSession) -> None:
    client = gui.client
    _scene(client)
    moved = client.ok("time", {"frame": 12, "range": [1, 48]})
    assert moved["frame"] == 12
    assert moved["range"] == [1, 48]
    assert client.python("hou.frame()") == 12
    assert client.python("list(hou.playbar.playbackRange())") == [1, 48]
    for source in ("viewer", "auto"):
        client.ok("look", {"source": source, "frame": 5, "resolution": [160, 120]})
        assert client.python("hou.frame()") == 12, source
    assert client.ok("time")["frame"] == 12


def test_viewport_cooks_between_calls_and_says_so_once(gui: GuiSession) -> None:
    """G2 (a mode): the GUI viewport cooks displayed nodes between calls. ``time`` says
    so with its first frame change and ``inspect`` (what: node) with its first
    ``cook_state``, once
    per session each."""
    client = gui.client
    _scene(client)
    client.python("import hocuspocus.host.tools.session as s\ns._VIEWPORT_NOTED.clear()")
    first = client.ok("time", {"frame": 3})
    assert "Scene Viewer recooks" in first["notes"][0]
    assert "notes" not in client.ok("time", {"frame": 4})
    assert "notes" not in client.ok("time")  # a read changes no frame

    client.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": "/obj/box_geo",
                    "type": "sphere",
                    "name": "uncooked",
                    "cook": False,
                    "flags": {"display": True},
                }
            ]
        },
    )

    def cooked_by_viewport() -> bool:
        info = client.ok("inspect", UNCOOKED)
        return info["nodes"][0]["cook_state"] == "cooked"

    assert _wait_for(cooked_by_viewport), "the viewport never cooked the displayed node"
    client.python(
        "import hocuspocus.host.tools.session as s\ns._VIEWPORT_NOTED.discard('cook_state')"
    )
    noted = client.ok("inspect", UNCOOKED)
    assert "cook_state can read cooked" in noted["notes"][0]
    assert "notes" not in client.ok("inspect", UNCOOKED)


UNCOOKED = {"what": "node", "paths": ["/obj/box_geo/uncooked"], "detail": "full"}


SCRUB_DURING_COOK = """
import hdefereval
_scrub_tries = [0]
def _scrub():
    _scrub_tries[0] += 1
    if 3 <= hou.frame() <= 20:
        hou.setFrame(200)
    elif _scrub_tries[0] < 5000:
        hdefereval.executeDeferredAfterWaiting(_scrub, 1)
hdefereval.executeDeferred(_scrub)
"""


def test_cook_frame_range_leaves_a_scrubbed_playbar(gui: GuiSession) -> None:
    """G4: ``cook {frame_range}`` steps the visible playbar; it goes back to the start
    frame only when the user did not move it during the job, and says so either way."""
    client = gui.client
    _scene(client)
    client.ok(
        "node_create",
        {
            "items": [
                {
                    "parent": "/obj/box_geo",
                    "type": "python",
                    "name": "slow",
                    "inputs": [{"index": 0, "from": "/obj/box_geo/box1"}],
                    "parms": {"python": "import time\ntime.sleep(0.05)\n"},
                }
            ]
        },
    )
    client.ok("time", {"frame": 50, "range": [1, 240]})
    cook = {"paths": ["/obj/box_geo/slow"], "frame_range": [1, 30], "force": True, "wait_s": 60}

    untouched = client.ok("cook", cook)
    assert untouched["frames_cooked"] == 30
    assert client.python("hou.frame()") == 50
    assert any("put back to frame 50" in n for n in untouched["notes"]), untouched.get("notes")

    client.python(SCRUB_DURING_COOK)  # the user drags the playbar to 200 mid-job
    scrubbed = client.ok("cook", cook)
    assert scrubbed["frames_cooked"] == 30
    assert client.python("hou.frame()") == 200
    assert any("moved to frame 200" in n for n in scrubbed["notes"]), scrubbed.get("notes")


def test_undo_history_interleaves_agent_and_user_steps(gui: GuiSession) -> None:
    client = gui.client
    _scene(client)
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "null", "name": "agent_null"}]})
    client.user_edit("hou.node('/obj/agent_null').parm('tx').set(3.0)")

    def user_step() -> str | None:
        history = client.ok("undo", {"action": "history"})["history"]
        return next((h for h in history if not h.startswith("HocusPocus:")), None)

    manual = _wait_for(user_step)
    assert manual, "the deferred edit never reached the undo history"
    history = client.ok("undo", {"action": "history"})["history"]
    assert history[0] == manual  # the user's step is the newest
    assert any(h.startswith("HocusPocus: node_create") for h in history[1:])
    # undo stops before the user's step unless told to cross it.
    blocked = client.ok("undo", {"action": "undo"})
    assert blocked["performed"] == []
    assert blocked["blocked_by"] == manual
    assert client.python("hou.node('/obj/agent_null').parm('tx').eval()") == 3.0
    crossed = client.ok("undo", {"action": "undo", "include_user_steps": True})
    assert crossed["performed"] == [manual]
    assert crossed["user_steps"] == [manual]
    assert client.python("hou.node('/obj/agent_null').parm('tx').eval()") == 0.0


def test_events_record_a_manual_rename(gui: GuiSession) -> None:
    client = gui.client
    _scene(client)
    created = client.ok(
        "node_create", {"items": [{"parent": "/obj", "type": "null", "name": "watched"}]}
    )
    assert created["results"][0]["path"] == "/obj/watched"
    since = client.ok("events", {"limit": 1000})["next_since"]
    client.user_edit("hou.node('/obj/watched').setName('renamed_by_user')")

    def renamed() -> list[dict[str, Any]]:
        events = client.ok("events", {"since": since, "limit": 1000})["events"]
        return [e for e in events if e["kind"] == "NameChanged"]

    found = _wait_for(renamed)
    assert found, "the manual rename was not recorded"
    event = found[-1]
    assert event["path"] == "/obj/renamed_by_user"
    assert event["origin"] == "other"
    assert event["detail"]["old_name"] == "watched"


def test_hda_create_round_trip(gui: GuiSession) -> None:
    client = gui.client
    _scene(client)
    client.ok(
        "node_create",
        {
            "items": [
                {"parent": "/obj", "type": "geo", "name": "asset_geo"},
                {"parent": "/obj/asset_geo", "type": "subnet", "name": "rock"},
                {"parent": "/obj/asset_geo/rock", "type": "box", "name": "inner"},
            ]
        },
    )
    ext = client.python("hou.hda.defaultFileExtension()")  # the licence's (D47)
    library = (gui.work_dir / "otls" / f"hp_gui_rock{ext}").as_posix()
    made = client.ok(
        "hda",
        {
            "action": "create",
            "path": "/obj/asset_geo/rock",
            "name": "hpgui::rock::1.0",
            "library_path": library,
            "label": "HP GUI Rock",
        },
    )
    path = made["path"]
    assert made["hda_locked"] is False
    assert made["undo_label"].startswith("HocusPocus: hda create")
    assert Path(library).is_file()
    client.ok("node_create", {"items": [{"parent": path, "type": "sphere", "name": "added"}]})
    assert client.ok("hda", {"action": "save", "path": path})["saved"] is True
    assert client.ok("hda", {"action": "match", "path": path})["hda_locked"] is True
    assert client.python(f"hou.node('{path}/added') is not None") is True
    listed = client.ok("hda", {"action": "list", "library_path": library})
    assert listed["definitions"][0]["label"] == "HP GUI Rock"
    assert client.ok("hda", {"action": "unlock", "path": path})["hda_locked"] is False
    history = client.ok("undo", {"action": "history"})["history"]
    assert any(h.startswith("HocusPocus: hda create") for h in history)


def _dirty(client: GuiClient) -> dict[str, Any]:
    hip = client.ok("houdini_status")["hip"]
    return {"dirty": hip["dirty"], "dirty_source": hip["dirty_source"]}


def test_reads_and_captures_leave_the_gui_hip_clean(gui: GuiSession) -> None:
    """G1: a type probe and a capture's temporary camera and ROP set Houdini's own flag,
    but dirty (the one source in both modes) stays false and on_unsaved: fail passes."""
    client = gui.client
    _scene(client)
    client.ok("hip_save", {"path": (gui.work_dir / "g1_reads.hip").as_posix()})
    assert _dirty(client) == {"dirty": False, "dirty_source": None}
    client.ok("inspect", {"what": "type", "target": "Sop/copytopoints", "detail": "full"})
    client.ok("look", {"resolution": [160, 120]})
    status = client.ok("houdini_status")["hip"]
    assert (status["dirty"], status["dirty_source"]) == (False, None)
    assert isinstance(status["houdini_flag"], bool)  # a diagnostic only
    assert client.ok("hip_new", {"on_unsaved": "fail"})["saved_first"] is False


def test_user_edits_dirty_the_gui_hip(gui: GuiSession) -> None:
    """G1: the user's edit on a watched node arrives as an origin: other event; an edit
    on a node no event watches is seen through Houdini's flag between two calls."""
    client = gui.client
    _scene(client)
    client.ok("hip_save", {"path": (gui.work_dir / "g1_a.hip").as_posix()})
    client.user_edit_after_save("hou.node('/obj/box_geo').setName('renamed_geo')", "g1_b.hip")
    client.ok("hip_save", {"path": (gui.work_dir / "g1_b.hip").as_posix()})
    assert _wait_for(lambda: _dirty(client)["dirty"]), "the rename never dirtied the scene"
    assert _dirty(client)["dirty_source"] == "user_event"
    refused = client.error("hip_new", {"on_unsaved": "fail"})
    assert refused["code"] == "unsaved_changes"
    assert refused["detail"]["dirty_source"] == "user_event"

    # A node made inside agent code is not watched; the user's later parm edit on it
    # sends no event, but sets Houdini's flag between two calls.
    client.python("hou.node('/obj/renamed_geo').createNode('sphere', 'unwatched')")
    client.user_edit_after_save(
        "hou.node('/obj/renamed_geo/unwatched').parm('scale').set(2.5)", "g1_c.hip"
    )
    client.ok("hip_save", {"path": (gui.work_dir / "g1_c.hip").as_posix()})
    assert _wait_for(lambda: _dirty(client)["dirty"]), "the parm edit never dirtied the scene"
    assert _dirty(client)["dirty_source"] == "houdini_flag"
    assert client.python("hou.node('/obj/renamed_geo/unwatched').parm('scale').eval()") == 2.5
    client.ok("hip_new", {"on_unsaved": "discard"})
    assert _dirty(client) == {"dirty": False, "dirty_source": None}


def test_selection_names_the_panes_it_moves(gui: GuiSession) -> None:
    """G3: selecting a SOP takes the unpinned Scene Viewer and Network Editor into its
    network on the next idle tick. Putting them back would change the selection (Houdini
    couples the two), so ``edit {op: select}`` keeps the selection and
    name the panes in ``context_changed``; a selection in the panes' own network moves
    nothing and says nothing."""
    client = gui.client
    _scene(client)
    client.python(PANES_TO_OBJ)
    before = client.python(PANES)
    assert before and set(before.values()) == {"/obj"}

    # The object is in /obj, where the panes are: nothing moves.
    same = client.ok("edit", {"ops": [{"op": "select", "paths": ["/obj/box_geo"]}]})
    assert same["selected"] == ["/obj/box_geo"] and "context_changed" not in same
    time.sleep(1.0)  # several idle ticks: a follow would have happened by now
    assert client.python(PANES) == before

    moving = {f"{name} (/obj/box_geo)" for name in before}
    chosen = client.ok("edit", {"ops": [{"op": "select", "paths": ["/obj/box_geo/box1"]}]})
    assert chosen["selected"] == ["/obj/box_geo/box1"]
    assert set(chosen["context_changed"]) == moving
    assert chosen["notes"]
    time.sleep(1.0)
    assert set(client.python(PANES).values()) == {"/obj/box_geo"}  # as reported
    assert client.python("[n.path() for n in hou.selectedNodes()]") == ["/obj/box_geo/box1"]

    client.python(PANES_TO_OBJ)
    edited = client.ok("edit", {"ops": [{"op": "select", "paths": ["/obj/box_geo/box1"]}]})
    assert edited["selected"] == ["/obj/box_geo/box1"]
    assert set(edited["context_changed"]) == moving
    time.sleep(1.0)
    assert set(client.python(PANES).values()) == {"/obj/box_geo"}
    assert client.python("[n.path() for n in hou.selectedNodes()]") == ["/obj/box_geo/box1"]
    client.python(PANES_TO_OBJ)


STUB_PROBE = """
import hdefereval
import hocuspocus.host.modal as _m
def _probe():
    _m._gui_probe = getattr(hou.ui.displayMessage, "_hocuspocus_stub", False)
hdefereval.executeDeferred(_probe)
"""


def _stubs_outside_calls(client: GuiClient) -> Any:
    """Whether ``hou.ui.displayMessage`` is the HocusPocus stub when the user's own code
    runs (an idle tick after the call, outside the executor): it must not be."""
    client.python("import hocuspocus.host.modal as m\nm.__dict__.pop('_gui_probe', None)")
    client.python(STUB_PROBE)
    probe = "import hocuspocus.host.modal as m\nresult = getattr(m, '_gui_probe', None)"
    _wait_for(lambda: client.python(probe) is not None, timeout_s=10.0)
    return client.python(probe)


def test_agent_code_opening_a_dialog_gets_ui_required(gui: GuiSession) -> None:
    """G5: a modal ``hou.ui`` call in ``houdini_python`` fails at once with
    ``ui_required`` instead of blocking the GUI until someone clicks; Houdini stays
    responsive and the user's own ``hou.ui`` is untouched between calls."""
    client = gui.client
    _scene(client)
    started = time.monotonic()
    refused = client.error(
        "houdini_python",
        {"code": "print('before')\nhou.ui.displayMessage('HocusPocus G5: never shown')"},
        timeout_s=20.0,
    )
    assert time.monotonic() - started < 10.0
    assert refused["code"] == "ui_required"
    assert "hou.ui.displayMessage()" in refused["message"]
    assert "block Houdini's main thread until a person answers" in refused["message"]
    assert refused["detail"]["refused"] == ["displayMessage"]
    assert refused["detail"]["stdout"] == "before\n"
    assert "rolled_back" in refused["detail"]
    for code, name in (
        ("hou.ui.selectFile()", "selectFile"),
        ("hou.ui.readInput('name?')", "readInput"),
        ("hou.ui.selectNode()", "selectNode"),
        ("hou.ui.displayConfirmation('sure?')", "displayConfirmation"),
    ):
        error = client.error("houdini_python", {"code": code}, timeout_s=20.0)
        assert error["code"] == "ui_required", (code, error)
        assert error["detail"]["refused"] == [name]
    # Responsive: the next call runs at once, and a non-modal hou.ui call still works.
    assert client.python("1 + 1") == 2
    client.python("hou.ui.setStatusMessage('HocusPocus G5 test')")
    # Inside a call the stub is in place; outside, Houdini's own function is back.
    assert client.python("getattr(hou.ui.displayMessage, '_hocuspocus_stub', False)") is True
    assert _stubs_outside_calls(client) is False


DIALOG_BUTTON = """
node = hou.node('/obj').createNode('null', 'dialog_button')
group = node.parmTemplateGroup()
group.append(hou.ButtonParmTemplate(
    'ask', 'Ask',
    script_callback="kwargs['node'].parm('tx').set(5); hou.ui.displayMessage('pressed'); "
    "kwargs['node'].parm('ty').set(7)",
    script_callback_language=hou.scriptLanguage.Python))
node.setParmTemplateGroup(group)
"""


def test_a_pressed_callback_that_opens_a_dialog_gets_ui_required(gui: GuiSession) -> None:
    """G5: a button callback that opens a dialog, pressed through ``parm_set {press}``
    or an ``edit`` set op, fails with ``ui_required`` (Houdini catches the stub's
    exception inside the callback, the dispatcher still sees it) and is rolled back."""
    client = gui.client
    _scene(client)
    client.python(DIALOG_BUTTON)
    started = time.monotonic()
    refused = client.error(
        "parm_set", {"items": [{"path": "/obj/dialog_button/ask", "press": True}]}, timeout_s=20.0
    )
    assert time.monotonic() - started < 10.0
    assert refused["code"] == "ui_required", refused
    assert "hou.ui.displayMessage()" in refused["message"]
    assert refused["message"].startswith("parm_set reached")
    assert refused["detail"]["refused"] == ["displayMessage"]
    assert refused["detail"]["rolled_back"] is True
    # The callback's change before the dialog was undone; the one after never ran.
    assert client.python("hou.parm('/obj/dialog_button/tx').eval()") == 0.0
    assert client.python("hou.parm('/obj/dialog_button/ty').eval()") == 0.0

    edited = client.error(
        "edit",
        {"ops": [{"op": "set", "path": "/obj/dialog_button/ask", "press": True}]},
        timeout_s=20.0,
    )
    assert edited["code"] == "ui_required", edited
    assert client.python("hou.parm('/obj/dialog_button/tx').eval()") == 0.0
    assert client.python("1 + 1") == 2
    assert _stubs_outside_calls(client) is False


def test_creation_and_load_scripts_that_open_a_dialog(gui: GuiSession) -> None:
    """G5: a creation script's dialog fails the call that made the node (rolled back); a
    hip load script's dialog leaves the file loaded, and the load says so in
    ``warnings``. Neither blocks Houdini."""
    client = gui.client
    _scene(client)
    refused = client.error(
        "node_create", {"items": [{"parent": "/obj", "type": "null", "name": "dialog_made"}]}
    )
    assert refused["code"] == "ui_required", refused
    assert refused["detail"]["refused"] == ["displayMessage"]
    assert refused["detail"]["rolled_back"] is True
    assert client.python("hou.node('/obj/dialog_made') is None") is True
    assert client.python("1 + 1") == 2

    # An Indie or Apprentice licence saves as .hiplc: open the file it wrote.
    hip = client.ok("hip_save", {"path": (gui.work_dir / "dialog_456.hip").as_posix()})["path"]
    loaded = client.ok("hip_open", {"path": hip, "on_unsaved": "discard"})
    assert any("hou.ui.displayMessage()" in w for w in loaded["warnings"]), loaded
    assert client.python("hou.hipFile.basename()").startswith("dialog_456")
    assert client.python("hou.node('/obj/box_geo') is not None") is True
    assert client.python("1 + 1") == 2
    client.ok("hip_new", {"on_unsaved": "discard"})


def _close_native_dialogs(pid: int) -> int:
    """Close the dialogs of Houdini ``pid`` that Qt's ``activeModalWidget`` cannot see
    (Houdini's own message windows, titled "Houdini"), as a person clicking their close
    box would. Windows only; returns how many it closed."""
    if sys.platform != "win32":  # pragma: no cover - the GUI runner is Windows today
        return 0
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    closed = []

    def visit(hwnd: Any, _param: Any) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if title.value == "Houdini":
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                closed.append(hwnd)
        return True

    user32.EnumWindows(proto(visit), 0)
    return len(closed)


USER_DIALOG = """
import json, time
import hdefereval
from PySide6 import QtCore, QtWidgets
_marker = {marker!r}
def _log(event):
    with open(_marker, "a", encoding="utf-8") as f:
        f.write(json.dumps({{"event": event, "t": time.time()}}) + "\\n")
_tries = [0]
_done = [False]
def _close():
    if _done[0]:  # closed already: never touch a later test's dialog
        return
    _tries[0] += 1
    w = QtWidgets.QApplication.activeModalWidget()
    if w is None:
        w = next((t for t in QtWidgets.QApplication.topLevelWidgets()
                  if t.isVisible() and t.isModal()), None)
    if w is None:
        _log("no_modal_widget")
        if _tries[0] < 40:
            QtCore.QTimer.singleShot(250, _close)
        return
    _log("closing " + type(w).__name__)
    if hasattr(w, "done"):
        w.done(0)
    else:
        w.close()
def _open():
    QtCore.QTimer.singleShot({close_ms}, _close)
    _log("opened")
    if {kind!r} == "hou_ui":
        hou.ui.displayMessage("HocusPocus G5 test: a user dialog, closed by a timer")
    else:
        box = QtWidgets.QMessageBox(hou.qt.mainWindow())
        box.setText("HocusPocus G5 test: a user Qt dialog, closed by a timer")
        box.exec()
    _done[0] = True
    _log("closed")
if {source!r} == "qt_event":
    hdefereval.executeDeferred(lambda: QtCore.QTimer.singleShot(0, _open))
else:
    hdefereval.executeDeferred(_open)
"""

DIALOG_OPEN_MS = 8000
PROBE_TIMEOUT_S = 3.0


def _events(marker: Path) -> list[str]:
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [json.loads(line)["event"] for line in lines if line.strip()]


def _measure_user_dialog(gui: GuiSession, kind: str, source: str) -> dict[str, Any]:
    """Open a user's modal dialog outside any call (``kind``: ``hou_ui`` or ``qt``; from
    ``source``: a Qt event like a shelf click, or an event-loop callback like
    ``hdefereval``), closed by a timer after :data:`DIALOG_OPEN_MS`, and send a call while
    it is open. Returns what that call saw."""
    client = gui.client
    marker = gui.work_dir / f"user_dialog_{kind}_{source}.jsonl"
    client.python(
        USER_DIALOG.format(
            marker=marker.as_posix(), close_ms=DIALOG_OPEN_MS, kind=kind, source=source
        )
    )
    assert _wait_for(lambda: "opened" in _events(marker), timeout_s=20.0), _events(marker)
    sent = time.monotonic()
    ok, result, _meta = client.call(
        "houdini_python", {"code": "result = 'pumped'"}, timeout_s=PROBE_TIMEOUT_S
    )
    answered_s = round(time.monotonic() - sent, 2)
    still_open = "closed" not in _events(marker)
    closed = _wait_for(lambda: "closed" in _events(marker), timeout_s=DIALOG_OPEN_MS / 1000 + 5)
    native = 0
    if not closed:  # a Houdini message window, which Qt's timer cannot find
        native = _close_native_dialogs(gui.instance.pid)
        closed = _wait_for(lambda: "closed" in _events(marker), timeout_s=20.0)
    assert closed, f"neither the timer nor WM_CLOSE closed the user's dialog: {_events(marker)}"
    # Houdini is free again once the dialog is gone.
    assert client.python("1 + 1") == 2
    return {
        "ok": ok,
        "code": None if ok else result.get("code"),
        "started": None if ok else (result.get("detail") or {}).get("started"),
        "answered_s": answered_s,
        "while_open": still_open,
        "closer": [e for e in _events(marker) if e.startswith("closing")]
        + (["WM_CLOSE"] if native else []),
    }


@pytest.mark.parametrize("source", ["qt_event", "event_loop_callback"])
@pytest.mark.parametrize("kind", ["qt", "hou_ui"])
def test_executor_while_a_user_dialog_is_open(gui: GuiSession, kind: str, source: str) -> None:
    """G5, measured on 22.0.466: the executor's pump (a ``hou.ui`` event-loop callback)
    does not run while the user has a modal dialog open, whether it is a ``hou.ui``
    dialog (Houdini's own window) or a Qt ``exec()``, and whether it was opened from a Qt
    event (a shelf click) or an event-loop callback (``hdefereval``); Qt timers do run.
    A call sent meanwhile never starts and answers ``houdini_busy`` with
    ``started: false`` after its timeout, then Houdini is free once the dialog closes."""
    _scene(gui.client)
    seen = _measure_user_dialog(gui, kind, source)
    print(f"G5 user dialog {kind} from {source}: {seen}")
    assert seen["while_open"], seen  # the probe call ran while the dialog was open
    assert seen["closer"], seen
    assert seen["ok"] is False, seen
    assert seen["code"] == "houdini_busy", seen
    assert seen["started"] is False, seen
    assert seen["answered_s"] >= PROBE_TIMEOUT_S - 0.5, seen
    # hou.ui dialogs are Houdini windows Qt cannot see; a Qt dialog closes from its timer.
    assert seen["closer"] == (["WM_CLOSE"] if kind == "hou_ui" else ["closing QMessageBox"])


def test_quit_closes_the_gui(gui: GuiSession) -> None:
    """Last: ``houdini_connect {quit}`` through the bridge's own code path. An agent
    mutation sets the tracked dirty flag (G1), so ``fail`` refuses first."""
    from hocuspocus.bridge import instances as registry
    from hocuspocus.bridge import local_tools
    from hocuspocus.bridge.config import BridgeConfig
    from hocuspocus.bridge.server import Bridge
    from hocuspocus.tools.errors import ToolError

    instances_dir = gui.state_dir / "instances"
    bridge = Bridge(
        BridgeConfig(profile="full"),
        scan=lambda: registry.scan(instances_dir),
        launches=registry.LaunchLog(gui.state_dir / "launches"),
    )
    pid = gui.instance.pid
    gui.client.ok("node_create", {"items": [{"parent": "/obj", "type": "null", "name": "unsaved"}]})
    with pytest.raises(ToolError) as refused:
        local_tools.houdini_connect(bridge, {"quit": True, "pid": pid})
    assert refused.value.code == "unsaved_changes"
    assert _pid_alive(pid)
    out = local_tools.houdini_connect(bridge, {"quit": True, "pid": pid, "on_unsaved": "discard"})
    assert out["quit"] is True and out["pid"] == pid
    assert _wait_for(lambda: not _pid_alive(pid), timeout_s=60.0)
    assert not (instances_dir / f"{pid}.json").exists()
