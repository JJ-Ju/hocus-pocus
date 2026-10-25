"""Modal hou.ui stubs during a call in a GUI session (docs/parity.md G5), without hou: a
fake ``ui`` class stands in for Houdini's SWIG one."""

from __future__ import annotations

import contextlib
import logging
import threading
import time

import pytest

from hocuspocus.host import modal
from hocuspocus.host.config import HostConfig
from hocuspocus.host.dispatch import Dispatcher
from hocuspocus.host.executor import MainThreadExecutor
from hocuspocus.host.modal import MODAL_CALLS, ModalStubs
from hocuspocus.host.runtime import CallJobManager
from hocuspocus.host.tools.registry import HostContext, HostTool, SceneState
from hocuspocus.host.undo import UndoHistory
from hocuspocus.tools.errors import ToolError


def _make_ui():
    """A stand-in for ``hou.ui``: SWIG methods and Python-added ones live on the class."""

    class ui:  # noqa: N801 - named like Houdini's class
        def displayMessage(self, text, **kwargs):  # noqa: N802
            return 0

        def readInput(self, message, **kwargs):  # noqa: N802
            return (0, "typed")

        def _selectFile(self, **kwargs):  # noqa: N802
            return "C:/picked.hip"

        def setStatusMessage(self, text, **kwargs):  # noqa: N802
            return None

    def selectFile(self, start_directory=None, **kwargs):  # noqa: N802
        return self._selectFile(start_directory=start_directory)

    ui.selectFile = selectFile  # what houpythonportion's _addMethod does
    return ui()


def test_the_modal_list_covers_the_dialogs_named_in_parity_g5():
    for name in (
        "displayMessage",
        "selectFile",
        "selectNode",
        "selectMultipleNodes",
        "readInput",
        "readMultiInput",
        "selectFromList",
        "selectColor",
        "displayConfirmation",
        "displayCustomConfirmation",
        "selectParmTag",
        "selectParm",
    ):
        assert name in MODAL_CALLS
    # Non-modal windows and helpers are left alone.
    for name in ("setStatusMessage", "openParameterInterfaceDialog", "addEventLoopCallback"):
        assert name not in MODAL_CALLS


def test_stubs_refuse_with_ui_required_and_the_originals_come_back():
    ui = _make_ui()
    originals = {name: vars(type(ui))[name] for name in ("displayMessage", "selectFile")}
    stubs = ModalStubs(ui)
    with stubs.active():
        assert stubs.installed
        with pytest.raises(ToolError) as caught:
            ui.displayMessage("hello")
        assert caught.value.code == "ui_required"
        assert "hou.ui.displayMessage()" in caught.value.message
        assert "block Houdini's main thread until a person answers" in caught.value.message
        assert caught.value.detail == {"refused": ["displayMessage"]}
        with pytest.raises(ToolError, match=r"hou\.ui\.selectFile\(\)"):
            ui.selectFile()
        # The private entry point is reported as its public name.
        with pytest.raises(ToolError, match=r"hou\.ui\.selectFile\(\)"):
            ui._selectFile()
        assert ui.setStatusMessage("not modal") is None
    assert not stubs.installed
    for name, original in originals.items():
        assert vars(type(ui))[name] is original
    assert ui.displayMessage("hello") == 0
    assert ui.readInput("?") == (0, "typed")
    assert ui.selectFile() == "C:/picked.hip"


def test_stubs_are_restored_when_the_work_raises_and_nest():
    ui = _make_ui()
    stubs = ModalStubs(ui)
    with pytest.raises(RuntimeError), stubs.active():
        with stubs.active(), pytest.raises(ToolError):
            ui.readInput("?")
        # Still inside the outer block: still stubbed.
        with pytest.raises(ToolError):
            ui.readInput("?")
        raise RuntimeError("the call failed")
    assert ui.readInput("?") == (0, "typed")


def test_without_hou_ui_nothing_is_patched():
    stubs = ModalStubs()  # no hou importable on plain CPython: headless behaviour
    with stubs.active():
        assert not stubs.installed


def test_names_this_build_lacks_are_skipped():
    ui = _make_ui()
    stubs = ModalStubs(ui)
    with stubs.active():
        assert not hasattr(ui, "selectParmTag")


def test_gui_executor_enters_the_guard_around_each_work_item():
    callbacks = []
    entered = []

    @contextlib.contextmanager
    def guard():
        entered.append("in")
        try:
            yield
        finally:
            entered.append("out")

    executor = MainThreadExecutor(
        "gui", add_callback=callbacks.append, remove_callback=callbacks.remove, modal_guard=guard
    )
    executor.start()
    box = {}

    def submit(fn):
        def target():
            try:
                box["value"] = executor.run(fn, 5)
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while thread.is_alive() and time.monotonic() < deadline:
            for callback in list(callbacks):
                callback()
            time.sleep(0.005)
        thread.join(1)

    submit(lambda: 42)
    assert box["value"] == 42
    assert entered == ["in", "out"]

    def boom():
        raise ValueError("nope")

    submit(boom)
    assert isinstance(box["error"], ValueError)
    assert entered == ["in", "out", "in", "out"]
    executor.stop()


def test_headless_executor_has_no_guard():
    executor = MainThreadExecutor("headless", main_thread_ident=threading.get_ident())
    executor.start()
    assert executor.modal_guard is None
    executor.stop()


# -- the dispatcher ------------------------------------------------------------------


class InlineExecutor:
    backend = "gui"

    def run(self, fn, timeout_s):
        return fn()


@pytest.fixture
def gui():
    ui = _make_ui()
    stubs = ModalStubs(ui)
    groups = []

    class Outcome:
        rolled_back = None

    @contextlib.contextmanager
    def fake_group(label):
        outcome = Outcome()
        groups.append(label)
        try:
            yield outcome
        except BaseException:
            outcome.rolled_back = True
            raise

    ctx = HostContext(
        config=HostConfig(),
        executor=InlineExecutor(),
        logger=logging.getLogger("test"),
        scene=SceneState(generation=3),
        jobs=CallJobManager(InlineExecutor()),
        undo=UndoHistory(),
    )
    tools = {}

    def add(name, fn, **kwargs):
        def guarded(args, ctx):
            with stubs.active():
                return fn(args, ctx)

        tools[name] = HostTool(name, guarded, **kwargs)

    dispatcher = Dispatcher(ctx, tools.get, undo_group=fake_group)
    return {"ui": ui, "add": add, "dispatcher": dispatcher, "ctx": ctx, "groups": groups}


def test_a_dialog_in_a_mutating_call_fails_it_with_ui_required_rolled_back(gui):
    ui = gui["ui"]
    gui["add"]("mutate", lambda args, ctx: ui.displayMessage("hi"), read_only=False)
    envelope = gui["dispatcher"].call("mutate", {})
    assert not envelope["ok"]
    error = envelope["error"]
    assert error["code"] == "ui_required"
    assert error["message"].startswith("mutate reached hou.ui.displayMessage()")
    assert error["detail"]["refused"] == ["displayMessage"]
    assert error["detail"]["rolled_back"] is True
    assert "error" not in error["detail"]
    assert error["hint"] == modal.HINT


def test_a_swallowed_dialog_still_fails_the_call(gui):
    ui = gui["ui"]

    def callback_like(args, ctx):
        with contextlib.suppress(Exception):  # Houdini catches a callback's exception
            ui.selectFile()
        return {"pressed": True}

    gui["add"]("press", callback_like, read_only=False)
    envelope = gui["dispatcher"].call("press", {})
    assert envelope["error"]["code"] == "ui_required"
    assert "hou.ui.selectFile()" in envelope["error"]["message"]
    assert "caught" in envelope["error"]["message"]
    assert envelope["error"]["detail"]["rolled_back"] is True


def test_a_read_that_reaches_a_dialog_fails_without_rolled_back(gui):
    ui = gui["ui"]

    def reader(args, ctx):
        try:
            ui.readInput("?")
        except ToolError as exc:
            raise ToolError("cook_failed", "the cook raised") from exc

    gui["add"]("reader", reader, read_only=True)
    envelope = gui["dispatcher"].call("reader", {})
    detail = envelope["error"]["detail"]
    assert envelope["error"]["code"] == "ui_required"
    assert "rolled_back" not in detail
    assert detail["error"] == "cook_failed: the cook raised"


def test_python_exception_detail_is_kept(gui):
    ui = gui["ui"]

    def code(args, ctx):
        try:
            ui.displayMessage("x")
        except ToolError as exc:
            raise ToolError(
                "python_exception",
                f"hocuspocus.tools.errors.ToolError: {exc}",
                detail={"stdout": "before\n", "stderr": "", "traceback": "tb", "rolled_back": None},
            ) from exc

    gui["add"]("houdini_python", code, read_only=False)
    envelope = gui["dispatcher"].call("houdini_python", {"code": "..."})
    error = envelope["error"]
    assert error["code"] == "ui_required"
    assert error["detail"]["stdout"] == "before\n"
    assert error["detail"]["traceback"] == "tb"
    assert "error" not in error["detail"]


def test_a_load_script_dialog_is_a_warning_on_a_loaded_scene(gui):
    ui = gui["ui"]

    def load(args, ctx):
        ctx.scene.generation += 1  # what AfterLoad does
        with contextlib.suppress(Exception):  # 456.py's exception is printed, not raised
            ui.displayConfirmation("Upgrade?")
        return {"path": "C:/x.hip", "warnings": []}

    ui_class = type(ui)
    ui_class.displayConfirmation = lambda self, text: True
    gui["add"]("hip_open", load, read_only=False)
    envelope = gui["dispatcher"].call("hip_open", {})
    assert envelope["ok"]
    (warning,) = envelope["result"]["warnings"]
    assert "hou.ui.displayConfirmation()" in warning
    assert "The scene is loaded" in warning


def test_calls_without_dialogs_are_untouched(gui):
    gui["add"]("plain", lambda args, ctx: {"fine": True}, read_only=False)
    envelope = gui["dispatcher"].call("plain", {})
    assert envelope["ok"]
    assert envelope["result"]["fine"] is True


def test_refusals_on_main_thread_steps_count_for_an_off_main_thread_call():
    """A tool off the main thread (cook, render) reaches hou through executor.run; the
    caller's context goes with each step, so a refusal there fails the call."""
    ui = _make_ui()
    stubs = ModalStubs(ui)
    main = threading.get_ident()
    executor = MainThreadExecutor("headless", main_thread_ident=main, modal_guard=stubs.active)
    executor.start()
    ctx = HostContext(
        config=HostConfig(),
        executor=executor,
        logger=logging.getLogger("test"),
        scene=SceneState(generation=1),
        jobs=CallJobManager(executor),
        undo=UndoHistory(),
    )

    def step():
        with contextlib.suppress(ToolError):  # a cook turns it into a node error
            ui.selectNode()
        return "cooked"

    ui_class = type(ui)
    ui_class.selectNode = lambda self: "/obj/geo1"

    def cook(args, ctx):
        return {"result": ctx.executor.run(step, 5)}

    tools = {"cook": HostTool("cook", cook, read_only=True, main_thread=False, scene=False)}
    dispatcher = Dispatcher(ctx, tools.get)
    box = {}
    thread = threading.Thread(target=lambda: box.update(dispatcher.call("cook", {})), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while thread.is_alive() and time.monotonic() < deadline:
        executor.pump_once(0.01)
    thread.join(1)
    executor.stop()
    assert box["ok"] is False
    assert box["error"]["code"] == "ui_required"
    assert box["error"]["detail"]["refused"] == ["selectNode"]
    assert ui.selectNode() == "/obj/geo1"


def test_the_refusal_is_a_tool_error_and_a_silent_exit():
    """Houdini shows its own blocking error window for any exception a parm callback
    raises except SystemExit (measured on 22.0.466), so the stub's error is both."""
    error = modal.dialog_error("displayMessage")
    assert isinstance(error, ToolError)
    assert isinstance(error, SystemExit)
    assert isinstance(error, Exception)
    assert error.code == "ui_required"
    assert error.to_dict()["code"] == "ui_required"


def test_the_executor_transports_a_refusal_instead_of_exiting():
    executor = MainThreadExecutor("headless", main_thread_ident=threading.get_ident())
    executor.start()
    box = {}

    def refuse():
        raise modal.dialog_error("readInput")

    def target():
        try:
            executor.run(refuse, 5)
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while thread.is_alive() and time.monotonic() < deadline:
        executor.pump_once(0.01)  # would raise SystemExit here if it were re-raised
    thread.join(1)
    executor.stop()
    assert isinstance(box["error"], modal.DialogRefused)


def test_the_dispatcher_answers_a_refusal_that_escapes_a_tool(gui):
    ui = gui["ui"]
    gui["add"]("direct", lambda args, ctx: ui.readInput("?"), read_only=True)
    envelope = gui["dispatcher"].call("direct", {})
    assert envelope["error"]["code"] == "ui_required"
    assert envelope["error"]["detail"]["refused"] == ["readInput"]
