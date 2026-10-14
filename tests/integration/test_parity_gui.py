"""The GUI column of docs/parity.md: a scripted ``houdinifx`` session (spec-2.0 §5.3).

Runs in the dev venv's Python, not in hython::

    .venv/Scripts/python -m pytest tests/integration/test_parity_gui.py --rungui -q

One session fixture launches ``houdinifx`` through :mod:`hocuspocus.bridge.launch` with an
isolated ``HOUDINI_USER_PREF_DIR`` (the dev package JSON and a ``profile = "full"`` toml in
it), an isolated ``HOCUSPOCUS_STATE_DIR`` and an ephemeral port, waits for the registry
entry and drives the host over ``POST /hp/v1/call`` with the bridge's own
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


@pytest.fixture(scope="session")
def gui(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GuiSession]:
    from hocuspocus.bridge import instances as registry
    from hocuspocus.bridge.launch import Launcher, detect_hfs, gui_executable

    hfs = detect_hfs(None)
    if hfs is None or gui_executable(hfs) is None:
        pytest.skip("no Houdini 22 install with houdinifx found (set HOCUSPOCUS_HFS or HFS)")
    base = tmp_path_factory.mktemp("hp-gui")
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
    )
    instances_dir = state / "instances"
    launcher = Launcher(
        str(hfs), environ=env, owned=False, scan=lambda: registry.scan(instances_dir)
    )
    spawned = launcher.spawn("gui", work_dir=work)
    started = {spawned.proc.pid}
    session: GuiSession | None = None
    try:
        launched = launcher.wait(spawned, LAUNCH_WAIT_S)
        inst = launched.instance
        started.add(inst.pid)
        assert inst.port != FORBIDDEN_PORT
        session = GuiSession(GuiClient(inst.port, inst.token), inst, spawned.proc, state, work)
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

    # auto in the GUI, /obj, no camera: the Scene Viewer as it is (parity: mode).
    as_is = client.ok("viewport_capture", {"resolution": [320, 240]})
    assert as_is["source_used"] == "viewer"
    assert as_is["fit_used"] == "none"
    assert as_is["image"]["png_base64"]
    assert client.view_state() == before

    # An explicit fit frames the free view for the grab only.
    fitted = client.ok(
        "viewport_capture", {"source": "viewer", "fit": "all", "resolution": [320, 240]}
    )
    assert fitted["source_used"] == "viewer"
    assert fitted["fit_used"] == "all"
    assert fitted["image"]["png_base64"] != as_is["image"]["png_base64"]
    assert client.view_state() == before

    # A camera: looked through for the grab, then the view and camera are put back.
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "cam", "name": "cam1"}]})
    client.ok("parm_set", {"items": [{"path": "/obj/cam1/t", "value": [0, 1, 6]}]})
    through = client.ok(
        "viewport_capture", {"source": "viewer", "camera": "/obj/cam1", "resolution": [320, 240]}
    )
    assert through["camera_used"] == "/obj/cam1"
    assert client.view_state() == before


def test_rop_capture_runs_in_process(gui: GuiSession) -> None:
    """auto with a camera renders a temporary viewport ROP in the GUI process: no kept
    child hython (headless only), and the user's view is untouched."""
    client = gui.client
    _scene(client)
    client.ok("node_create", {"items": [{"parent": "/obj", "type": "cam", "name": "cam1"}]})
    before = client.view_state()
    shot = client.ok("viewport_capture", {"camera": "/obj/cam1", "resolution": [320, 240]})
    assert shot["source_used"] in ("flipbook_rop", "opengl_rop")
    assert shot["camera_used"] == "/obj/cam1"
    framed = client.ok(
        "viewport_capture", {"source": "flipbook_rop", "fit": "all", "resolution": [320, 240]}
    )
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


def test_time_moves_the_playbar_and_captures_do_not(gui: GuiSession) -> None:
    client = gui.client
    _scene(client)
    moved = client.ok("time", {"frame": 12, "range": [1, 48]})
    assert moved["frame"] == 12
    assert moved["range"] == [1, 48]
    assert client.python("hou.frame()") == 12
    assert client.python("list(hou.playbar.playbackRange())") == [1, 48]
    for source in ("viewer", "flipbook_rop"):
        client.ok("viewport_capture", {"source": source, "frame": 5, "resolution": [160, 120]})
        assert client.python("hou.frame()") == 12, source
    assert client.ok("time")["frame"] == 12


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
    library = (gui.work_dir / "otls" / "hp_gui_rock.hda").as_posix()
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
    client.ok("node_type_info", {"type": "Sop/copytopoints", "detail": "full"})
    client.ok("viewport_capture", {"source": "flipbook_rop", "resolution": [160, 120]})
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
    couples the two), so ``selection`` and ``edit {op: select}`` keep the selection and
    name the panes in ``context_changed``; a selection in the panes' own network moves
    nothing and says nothing."""
    client = gui.client
    _scene(client)
    client.python(PANES_TO_OBJ)
    before = client.python(PANES)
    assert before and set(before.values()) == {"/obj"}

    # The object is in /obj, where the panes are: nothing moves.
    same = client.ok("selection", {"paths": ["/obj/box_geo"]})
    assert same == {"selected": ["/obj/box_geo"]}
    time.sleep(1.0)  # several idle ticks: a follow would have happened by now
    assert client.python(PANES) == before

    moving = {f"{name} (/obj/box_geo)" for name in before}
    chosen = client.ok("selection", {"paths": ["/obj/box_geo/box1"]})
    assert chosen["selected"] == ["/obj/box_geo/box1"]
    assert set(chosen["context_changed"]) == moving
    assert chosen["notes"]
    time.sleep(1.0)
    assert set(client.python(PANES).values()) == {"/obj/box_geo"}  # as reported
    assert client.python("[n.path() for n in hou.selectedNodes()]") == ["/obj/box_geo/box1"]

    client.python(PANES_TO_OBJ)
    client.python("import hocuspocus.host as h\nh.current().config.profile = 'v2'")
    try:
        edited = client.ok("edit", {"ops": [{"op": "select", "paths": ["/obj/box_geo/box1"]}]})
    finally:
        client.python("import hocuspocus.host as h\nh.current().config.profile = 'full'")
    row = edited["results"][0]
    assert row["selected"] == ["/obj/box_geo/box1"]
    assert set(row["context_changed"]) == moving
    time.sleep(1.0)
    assert set(client.python(PANES).values()) == {"/obj/box_geo"}
    assert client.python("[n.path() for n in hou.selectedNodes()]") == ["/obj/box_geo/box1"]
    client.python(PANES_TO_OBJ)


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
