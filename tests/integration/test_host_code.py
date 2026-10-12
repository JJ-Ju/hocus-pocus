"""houdini_python against real Houdini."""

from __future__ import annotations

import pytest

hou = pytest.importorskip("hou")


def test_stdout_and_trailing_expression(client):
    result = client.ok(
        "houdini_python",
        {"code": "print('hello')\nn = hou.node('/obj').createNode('geo', 'py_geo')\nn.path()"},
    )
    assert result["stdout"] == "hello\n"
    assert result["stderr"] == ""
    assert result["result"] == "/obj/py_geo"
    assert "exception" not in result
    assert hou.node("/obj/py_geo") is not None


def test_result_variable_and_repr_fallback(client):
    result = client.ok(
        "houdini_python", {"code": "result = {'node': hou.node('/obj'), 'n': (1, 2.5)}"}
    )
    assert result["result"]["n"] == [1, 2.5]
    assert "/obj" in result["result"]["node"]  # repr fallback for hou objects


def test_stderr_capture(client):
    result = client.ok("houdini_python", {"code": "import sys\nsys.stderr.write('oops')"})
    assert result["stderr"] == "oops"


def test_exception_is_a_python_exception_error_and_rolls_back(client):
    """1.1 contract (review 11 B13b): an uncaught exception is an isError result."""
    error = client.error(
        "houdini_python",
        {
            "code": "print('before')\nhou.node('/obj').createNode('geo', 'half_done')\n"
            "hou.node('/obj').createNode('not_a_real_type_xyz')"
        },
    )
    assert error["code"] == "python_exception"
    assert error["message"].startswith("hou.OperationFailed: ")
    assert error["detail"]["stdout"] == "before\n"
    assert "<houdini_python>" in error["detail"]["traceback"]
    assert error["detail"]["rolled_back"] is True and "rolled back" in error["hint"]
    assert hou.node("/obj/half_done") is None  # the partial change was undone


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("import sys\nprint('bye')\nsys.exit(3)", "SystemExit: 3"),
        ("raise SystemExit", "SystemExit"),
        ("raise KeyboardInterrupt('stop')", "KeyboardInterrupt: stop"),
    ],
)
def test_exit_and_interrupt_are_errors_and_the_host_survives(client, code, message):
    error = client.error("houdini_python", {"code": code})
    assert error["code"] == "python_exception" and error["message"] == message
    # The host is still serving.
    assert client.ok("houdini_python", {"code": "1 + 1"})["result"] == 2


def test_success_results_are_unchanged(client):
    result = client.ok("houdini_python", {"code": "1"})
    assert result["result"] == 1 and "ok" not in result and "exception" not in result


def test_deadline_stops_a_runaway_loop_and_frees_houdini(client):
    """Review 10 §1.6: a while True: no longer wedges every later call."""
    envelope = client.call(
        "houdini_python",
        {"code": "hou.node('/obj').createNode('geo', 'loop_geo')\nwhile True:\n    pass"},
        timeout_s=2,
    )
    assert envelope["ok"] is False
    error = envelope["error"]
    assert error["code"] == "houdini_busy"
    assert error["detail"]["started"] is True and error["detail"]["stopped"] is True
    assert "timeout_s" in error["hint"]
    assert hou.node("/obj/loop_geo") is None  # rolled back
    assert client.ok("houdini_python", {"code": "2 + 2"})["result"] == 4


def test_result_variable_when_trailing_expression_is_none(client):
    result = client.ok("houdini_python", {"code": "result = 42\nprint('x')"})
    assert result["result"] == 42
    result = client.ok("houdini_python", {"code": "result = 'kept'\nNone"})
    assert result["result"] == "kept"


def test_syntax_error(client):
    error = client.error("houdini_python", {"code": "def broken(:\n  pass"})
    assert error["code"] == "python_exception" and error["message"].startswith("SyntaxError")


def test_hscript(client):
    result = client.ok("houdini_python", {"code": "echo hp_hscript_ok", "language": "hscript"})
    assert result["stdout"].strip() == "hp_hscript_ok"


def test_python_disabled(client):
    client.host.config.allow_python = False
    error = client.error("houdini_python", {"code": "1"})
    assert error["code"] == "python_disabled"
    assert "allow_python" in error["hint"]


def test_output_is_capped(client):
    result = client.ok("houdini_python", {"code": "print('x' * 100000)"})
    assert result["truncated"] is True
    assert len(result["stdout"]) < 20000
    assert "truncated" in result["stdout"]


def test_marks_scene_dirty(client):
    assert client.ok("houdini_status")["hip"]["dirty"] is False
    client.ok("houdini_python", {"code": "hou.node('/obj').createNode('geo')"})
    assert client.ok("houdini_status")["hip"]["dirty"] is True
