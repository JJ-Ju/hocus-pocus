"""houdini_python's runner without Houdini: exceptions become errors, the deadline stops
runaway code (review 10 §1.6, review 11 B13b)."""

from __future__ import annotations

import sys
import time

import pytest

from hocuspocus.host.tools import code
from hocuspocus.tools.errors import ToolError

pytestmark = pytest.mark.unit

FAKE_HOU = object()


def run(source: str, **kw):
    return code.run_python(source, hou_module=FAKE_HOU, **kw)


def test_success_has_no_exception():
    payload = run("print('hi')\nresult = 3")
    assert payload["stdout"] == "hi\n" and payload["result"] == 3
    assert "exception" not in payload and "ok" not in payload


def test_exception_becomes_python_exception_error():
    payload = run("print('before')\n1/0")
    error = code.exception_error(payload, 30.0, 16384)
    assert isinstance(error, ToolError) and error.code == "python_exception"
    assert error.message == "ZeroDivisionError: division by zero"
    assert error.detail["stdout"] == "before\n" and error.detail["stderr"] == ""
    assert "<houdini_python>" in error.detail["traceback"]
    assert error.hint and "rolled back" in error.hint
    assert error.to_dict()["retryable"] is False


@pytest.mark.parametrize("source", ["import sys\nsys.exit(3)", "raise KeyboardInterrupt('x')"])
def test_exit_and_interrupt_never_escape(source):
    payload = run(source)
    error = code.exception_error(payload, 30.0, 16384)
    assert error.code == "python_exception"
    if "exit" in source:
        assert error.message == "SystemExit: 3" and "sys.exit" in error.hint


def test_syntax_error_is_an_exception():
    error = code.exception_error(run("def broken(:\n  pass"), 30.0, 16384)
    assert error.code == "python_exception" and error.message.startswith("SyntaxError")


def test_detail_is_capped():
    error = code.exception_error(run("print('x' * 100000)\n1/0"), 30.0, 4096)
    assert len(error.detail["stdout"]) < 4096


def test_deadline_stops_a_runaway_loop():
    started = time.monotonic()
    payload = run("n = 0\nwhile True:\n    n += 1", timeout_s=0.5)
    elapsed = time.monotonic() - started
    assert payload["exception"]["timeout"] is True
    assert elapsed < 0.5  # stopped before the executor's own timeout
    error = code.exception_error(payload, 0.5, 16384)
    assert error.code == "houdini_busy"
    assert error.detail["started"] is True and error.detail["stopped"] is True
    assert error.to_dict()["retryable"] is False and "timeout_s" in error.hint


def test_deadline_restores_the_previous_trace_hook():
    def tracer(frame, event, arg):
        return None

    sys.settrace(tracer)
    try:
        run("x = 1", timeout_s=5)
        assert sys.gettrace() is tracer
    finally:
        sys.settrace(None)


def test_no_timeout_means_no_trace_hook():
    previous = sys.gettrace()
    assert run("import sys\nresult = sys.gettrace() is None", timeout_s=None)["result"] == (
        previous is None
    )
    assert code.deadline_for(None, 0.0) is None
    assert code.deadline_for(30.0, 100.0) == pytest.approx(129.0)
    assert code.deadline_for(2.0, 0.0) == pytest.approx(1.8)
