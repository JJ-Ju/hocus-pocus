"""hou_undo_group's rollback, reported honestly (review 10 section 1.7), with a fake hou."""

from __future__ import annotations

import contextlib
import logging
import sys
import types

import pytest

from hocuspocus.host.config import HostConfig
from hocuspocus.host.dispatch import Dispatcher
from hocuspocus.host.jobs import JobManager
from hocuspocus.host.tools.registry import HostContext, HostTool, SceneState
from hocuspocus.host.undo import LABEL_MAX_CHARS, UndoHistory, hou_undo_group, make_label
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit


class FakeUndos:
    def __init__(self, enabled: bool = True, undo_fails: bool = False) -> None:
        self.stack: list[str] = ["older work"]
        self.enabled = enabled
        self.undo_fails = undo_fails
        self.open: list[str] = []

    def areEnabled(self) -> bool:  # noqa: N802 - hou API
        return self.enabled

    def undoLabels(self) -> tuple[str, ...]:  # noqa: N802 - hou API
        return tuple(reversed(self.stack))

    @contextlib.contextmanager
    def group(self, label):
        self.open.append(label)
        try:
            yield
        finally:
            self.open.pop()
            if self.enabled and getattr(self, "record", True):
                self.stack.append(label)

    def performUndo(self) -> None:  # noqa: N802 - hou API
        if self.undo_fails:
            raise RuntimeError("undo failed")
        self.stack.pop()


@pytest.fixture
def fake_hou(monkeypatch):
    undos = FakeUndos()
    monkeypatch.setitem(sys.modules, "hou", types.SimpleNamespace(undos=undos))
    return undos


def _fail(group_label="HocusPocus: t"):
    with pytest.raises(ValueError), hou_undo_group(group_label) as outcome:
        raise ValueError("boom")
    return outcome


def test_failure_is_rolled_back_and_says_so(fake_hou):
    outcome = _fail()
    assert outcome.failed and outcome.rolled_back is True
    assert fake_hou.stack == ["older work"]


def test_undo_disabled_reports_no_rollback(fake_hou):
    fake_hou.enabled = False
    outcome = _fail()
    assert outcome.rolled_back is False and outcome.undo_enabled is False


def test_failed_undo_reports_no_rollback(fake_hou):
    fake_hou.undo_fails = True
    assert _fail().rolled_back is False


def test_success_is_not_a_rollback(fake_hou):
    with hou_undo_group("HocusPocus: ok") as outcome:
        pass
    assert outcome.failed is False and outcome.rolled_back is False
    assert fake_hou.stack[-1] == "HocusPocus: ok"


def test_labels_are_ascii_and_short():
    label = make_label("node_create", {"path": "/obj/" + "é" * 300})
    assert len(label) <= LABEL_MAX_CHARS == 100
    assert label.isascii() and label.endswith("...")


def _dispatcher(group, fn):
    ctx = HostContext(
        config=HostConfig(),
        executor=None,
        logger=logging.getLogger("test"),
        scene=SceneState(),
        jobs=JobManager(None),
        undo=UndoHistory(),
    )
    tools = {"mutate": HostTool("mutate", fn, read_only=False, main_thread=False)}
    return ctx, Dispatcher(ctx, tools.get, undo_group=group)


@pytest.mark.parametrize("enabled", [True, False])
def test_dispatcher_fills_in_rolled_back_from_the_group(fake_hou, enabled):
    fake_hou.enabled = enabled

    def fn(args, ctx):
        raise ToolError("invalid_value", "bad", detail={"rolled_back": None})

    ctx, dispatcher = _dispatcher(hou_undo_group, fn)
    envelope = dispatcher.call("mutate", {})
    assert envelope["ok"] is False
    assert envelope["error"]["detail"]["rolled_back"] is enabled
    assert ctx.extras["rolled_back"] is enabled


def test_dispatcher_keeps_a_tool_supplied_rolled_back(fake_hou):
    def fn(args, ctx):
        raise ToolError("invalid_value", "bad", detail={"item": 1, "rolled_back": False})

    _ctx, dispatcher = _dispatcher(hou_undo_group, fn)
    assert dispatcher.call("mutate", {})["error"]["detail"]["rolled_back"] is False


# -- a rolled-back call is not redoable (review 21 papercut 2) ------------------------------


class RedoUndos(FakeUndos):
    """FakeUndos with Houdini's redo stack: an undo moves the entry onto it."""

    def __init__(self) -> None:
        super().__init__()
        self.redo: list[str] = []

    def redoLabels(self) -> tuple[str, ...]:  # noqa: N802 - hou API
        return tuple(reversed(self.redo))

    def performUndo(self) -> None:  # noqa: N802 - hou API
        self.redo.append(self.stack.pop())


def test_dispatcher_remembers_a_rolled_back_call_on_the_redo_stack(monkeypatch):
    undos = RedoUndos()
    monkeypatch.setitem(sys.modules, "hou", types.SimpleNamespace(undos=undos))

    def fn(args, ctx):
        raise ToolError("python_exception", "ZeroDivisionError", detail={"rolled_back": None})

    ctx, dispatcher = _dispatcher(hou_undo_group, fn)
    assert dispatcher.call("mutate", {})["error"]["detail"]["rolled_back"] is True
    redo = undos.redoLabels()
    assert redo == ("HocusPocus: mutate",)
    assert ctx.undo.rolled_back_in(redo) == {0}


def test_rolled_back_entry_is_found_under_later_undos_and_forgotten_once_gone():
    history = UndoHistory()
    history.rolled_back(("HocusPocus: houdini_python 1/0",))
    # Undoing an older step puts it on top; the failed call stays at the bottom.
    assert history.rolled_back_in(
        ("HocusPocus: parm_set 1 parm", "HocusPocus: houdini_python 1/0")
    ) == {1}
    # A new change cleared the redo stack; a later stack with the same label is not it.
    assert history.rolled_back_in(()) == set()
    assert history.rolled_back_in(("HocusPocus: houdini_python 1/0",)) == set()


def test_nothing_is_remembered_when_the_group_recorded_nothing():
    history = UndoHistory()
    history.rolled_back(None)
    history.rolled_back(())
    assert history.rolled_back_in(("x",)) == set()


# -- one host log line per call (review 22 finding 4) ---------------------------------------


def test_every_call_writes_one_log_line(caplog):
    def ok(args, ctx):
        return {"done": True}

    def bad(args, ctx):
        raise ToolError("invalid_value", "nope")

    ctx = HostContext(
        config=HostConfig(),
        executor=None,
        logger=logging.getLogger("hocuspocus.host.test_calls"),
        scene=SceneState(),
        jobs=JobManager(None),
        undo=UndoHistory(),
    )
    tools = {
        "ok_tool": HostTool("ok_tool", ok, read_only=True, main_thread=False),
        "bad_tool": HostTool("bad_tool", bad, read_only=True, main_thread=False),
    }
    dispatcher = Dispatcher(ctx, tools.get)
    with caplog.at_level(logging.INFO, logger="hocuspocus.host.test_calls"):
        envelope = dispatcher.call("ok_tool", {})
        dispatcher.call("bad_tool", {})
        dispatcher.call("no_such_tool", {})
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 3
    pid = f"pid {__import__('os').getpid()}"
    assert lines[0].startswith("call ok_tool ") and lines[0].endswith(f" ok {pid}")
    assert f"{envelope['_meta']['elapsed_ms']} ms main 0 ms" in lines[0]
    assert lines[1].endswith(f" invalid_value {pid}") and lines[2].startswith("call no_such_tool ")
    assert envelope["_meta"]["timing"] == {"main_thread_ms": 0}
