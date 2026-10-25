"""Modal ``hou.ui`` dialogs during a call in a GUI session (docs/parity.md G5, BIBLE §3.2).

A modal dialog stops Houdini's main thread inside C++ until a person answers it: the
``houdini_python`` deadline cannot fire there, the call returns ``houdini_busy`` and every
later call waits behind the dialog. So while the GUI executor runs HocusPocus work on the
main thread (:meth:`~hocuspocus.host.executor.MainThreadExecutor._execute`), the modal
entry points of ``hou.ui`` are replaced by stubs that raise
``ToolError("ui_required")`` naming the call, and put back afterwards, also when the work
raises, so the user's own UI between calls is untouched. Headless there is no ``hou.ui``
and nothing is patched.

The dispatcher (:func:`collecting`, :func:`refused_error`) fails a call that reached a stub
with ``ui_required`` even when Houdini swallowed the stub's exception (a parm callback, a
creation or load script), inside the call's undo group so its changes roll back. A call
that loaded or cleared the scene succeeds with a warning instead: the file is loaded.

Stdlib only; ``hou`` is imported lazily.
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from typing import Any

from hocuspocus.tools.errors import ToolError

MODAL_CALLS: dict[str, str] = {
    # name on hou.ui -> the public call it is reported as
    "displayMessage": "displayMessage",
    "displayConfirmation": "displayConfirmation",
    "displayCustomConfirmation": "displayCustomConfirmation",
    "displayFileDependencyDialog": "displayFileDependencyDialog",
    "readInput": "readInput",
    "readMultiInput": "readMultiInput",
    "selectFromList": "selectFromList",
    "selectFromTree": "selectFromTree",
    "selectFile": "selectFile",
    "_selectFile": "selectFile",
    "selectNode": "selectNode",
    "_selectNode": "selectNode",
    "selectMultipleNodes": "selectMultipleNodes",
    "selectNodeData": "selectNodeData",
    "_selectNodeData": "selectNodeData",
    "selectAttrib": "selectAttrib",
    "selectParm": "selectParm",
    "selectParmTag": "selectParmTag",
    "selectParmTuple": "selectParmTuple",
    "selectColor": "selectColor",
    "selectRawColor": "selectRawColor",
}
"""The ``hou.ui`` functions that wait for a person (Houdini 22.0.466): the ``display*``,
``read*`` and ``select*`` dialogs. Each is stubbed when this build has it. The
``open*`` windows (``openParameterInterfaceDialog``, ``openRenderDialog``, ...) return at
once and are left alone; so are Qt dialogs a script builds itself (``QDialog.exec``)."""

HINT = (
    "Pass the value as an argument or set it in code, print() messages instead (stdout "
    "comes back in the result), and press only buttons whose callbacks open no dialog."
)

_REFUSED: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "hocuspocus_modal_refused", default=None
)


class DialogRefused(ToolError, SystemExit):
    """What a stub raises: a ``ToolError("ui_required")`` that is also a ``SystemExit``.

    Measured on 22.0.466 in a GUI session: Houdini catches every exception a parm callback
    raises and then shows its own modal "Error running callback" window, which blocks the
    main thread just as the refused dialog would have; it shows none for ``SystemExit``,
    and does not exit. Python SOP cooks, Python expressions and ``456.py`` show no window
    either way. It is still an ``Exception``, so ``except Exception`` in the agent's code
    and the dispatcher catch it; the executor and dispatcher never re-raise it as an exit.
    """


def dialog_error(name: str) -> ToolError:
    """The error a stub raises for ``hou.ui.<name>``."""
    return DialogRefused(
        "ui_required",
        f"hou.ui.{name}() opens a modal dialog, which would block Houdini's main thread "
        "until a person answers it; HocusPocus refuses dialogs during a call.",
        hint=HINT,
        detail={"refused": [name]},
    )


def _stub(name: str) -> Any:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        refused = _REFUSED.get()
        if refused is not None and name not in refused:
            refused.append(name)
        raise dialog_error(name)

    refuse.__name__ = name
    refuse.__doc__ = f"HocusPocus stub: hou.ui.{name} is refused during a call (G5)."
    refuse._hocuspocus_stub = True  # type: ignore[attr-defined]
    return refuse


class ModalStubs:
    """Install the stubs on ``hou.ui``'s class while at least one :meth:`active` block is
    open, and put the originals back when the last one closes. Main thread only."""

    def __init__(self, ui: Any = None) -> None:
        self._ui = ui
        self._depth = 0
        self._saved: dict[str, Any] = {}
        self._target: Any = None

    def _resolve_ui(self) -> Any:
        if self._ui is not None:
            return self._ui
        try:
            import hou

            return getattr(hou, "ui", None)
        except ImportError:
            return None

    def install(self) -> None:
        ui = self._resolve_ui()
        if ui is None:  # headless: there is no hou.ui
            return
        # Patch the class: SWIG instances may refuse new attributes, and hou.ui's
        # Python-defined methods (selectFile, selectNode) live on the class too.
        target = type(ui)
        saved: dict[str, Any] = {}
        try:
            for name, public in MODAL_CALLS.items():
                if name not in vars(target):
                    continue
                original = vars(target)[name]
                if getattr(original, "_hocuspocus_stub", False):
                    continue
                setattr(target, name, _stub(public))
                saved[name] = original
        except Exception:
            for name, original in saved.items():
                with contextlib.suppress(Exception):
                    setattr(target, name, original)
            raise
        self._target, self._saved = target, saved

    def restore(self) -> None:
        target, saved = self._target, self._saved
        self._target, self._saved = None, {}
        if target is None:
            return
        for name, original in saved.items():
            with contextlib.suppress(Exception):
                setattr(target, name, original)

    @property
    def installed(self) -> bool:
        return self._target is not None

    @contextlib.contextmanager
    def active(self) -> Iterator[None]:
        if self._depth == 0:
            try:
                self.install()
            except Exception:
                # Never fail HocusPocus work because the stubs could not go in.
                self._target, self._saved = None, {}
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                self.restore()


@contextlib.contextmanager
def collecting() -> Iterator[list[str]]:
    """Collect the names of the modal calls refused while the block runs, on any thread
    whose work was submitted from it: :meth:`MainThreadExecutor.run` carries the caller's
    context to the main thread."""
    refused: list[str] = []
    token = _REFUSED.set(refused)
    try:
        yield refused
    finally:
        _REFUSED.reset(token)


def refused_error(
    tool: str, refused: list[str], cause: BaseException | None, *, mutating: bool
) -> ToolError:
    """The ``ui_required`` failure of a call that reached the stubs. ``cause`` is what the
    tool raised, if anything: its ``detail`` (``houdini_python``'s stdout and traceback)
    is kept."""
    names = ", ".join(f"hou.ui.{name}()" for name in refused)
    swallowed = (
        ""
        if cause is not None
        else " The refusal was caught (by Houdini in a callback or script, or by the code), "
        "so that work stopped there."
    )
    message = (
        f"{tool} reached {names}, a modal dialog that would block Houdini's main thread "
        f"until a person answers it; HocusPocus refused it and the call failed.{swallowed}"
    )
    detail: dict[str, Any] = {}
    cause_detail = getattr(cause, "detail", None)
    if isinstance(cause_detail, dict):
        detail.update(cause_detail)
    detail["refused"] = list(refused)
    code = getattr(cause, "code", None)
    if cause is not None and code not in ("ui_required", "python_exception"):
        # What the tool made of the refusal (houdini_python's is in detail.traceback).
        detail["error"] = f"{code}: {cause}" if code else f"{type(cause).__name__}: {cause}"
    if mutating:
        # None asks the dispatcher to fill in what the undo group really did.
        detail["rolled_back"] = None
    else:
        detail.pop("rolled_back", None)
    return ToolError("ui_required", message, hint=HINT, detail=detail)


def load_warning(refused: list[str]) -> str:
    """The warning on a call that loaded or cleared the scene and reached the stubs."""
    names = ", ".join(f"hou.ui.{name}()" for name in refused)
    return (
        f"A load or creation script called {names}; HocusPocus refused the modal dialog "
        "(ui_required), so that script stopped there. The scene is loaded."
    )
