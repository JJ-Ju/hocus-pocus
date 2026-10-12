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


def test_exception_is_reported_not_raised(client):
    result = client.ok(
        "houdini_python",
        {"code": "print('before')\nhou.node('/obj').createNode('not_a_real_type_xyz')"},
    )
    assert result["stdout"] == "before\n"
    exc = result["exception"]
    assert exc["type"] == "hou.OperationFailed"
    assert "Invalid node type" in exc["message"] or exc["message"]
    assert "<houdini_python>" in exc["traceback"]


def test_syntax_error(client):
    result = client.ok("houdini_python", {"code": "def broken(:\n  pass"})
    assert result["exception"]["type"] == "SyntaxError"


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
