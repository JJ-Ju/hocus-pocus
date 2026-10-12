"""The one response truncator (tools/budget.py), used by host and bridge."""

from __future__ import annotations

from hocuspocus.tools.budget import size as encoded_size
from hocuspocus.tools.budget import truncate as _truncate


def truncate(payload, max_bytes):
    return _truncate(payload, max_bytes)[0]


def test_small_payload_is_returned_unchanged():
    payload = {"a": [1, 2, 3]}
    assert truncate(payload, 1024) is payload


def test_list_trimmed_at_item_boundaries():
    payload = {"rows": [{"path": f"/obj/geo{i}", "type": "geo"} for i in range(500)], "total": 500}
    result = truncate(payload, 2048)
    assert result["truncated"] is True
    assert encoded_size(result) <= 2048
    assert 0 < len(result["rows"]) < 500
    assert result["rows"] == payload["rows"][: len(result["rows"])]
    assert result["total"] == 500
    assert len(payload["rows"]) == 500  # input untouched


def test_largest_list_trimmed_first():
    payload = {"small": list(range(5)), "big": ["x" * 50] * 200}
    result = truncate(payload, 2000)
    assert result["small"] == list(range(5))
    assert len(result["big"]) < 200


def test_nested_lists():
    payload = {"nodes": [{"children": [f"/obj/n{i}/c{j}" for j in range(100)]} for i in range(3)]}
    result = truncate(payload, 1500)
    assert encoded_size(result) <= 1500
    assert result["truncated"] is True


def test_long_strings_shortened_with_marker():
    payload = {"stdout": "x" * 100_000, "stderr": "", "result": None}
    result = truncate(payload, 4096)
    assert encoded_size(result) <= 4096
    assert result["truncated"] is True
    assert result["stdout"].startswith("xxx")
    assert "truncated" in result["stdout"]
    assert result["stderr"] == ""


def test_multibyte_strings_fit():
    payload = {"text": "é" * 20_000}
    result = truncate(payload, 2048)
    assert encoded_size(result) <= 2048


def test_non_json_values_use_repr():
    class Thing:
        def __repr__(self):
            return "<thing>"

    result = truncate({"v": [Thing()] * 1000}, 1024)
    assert result["v"][0] == "<thing>"


def test_cuts_name_what_was_trimmed():
    payload = {"rows": list(range(1000)), "text": "y" * 50_000}
    result, cuts = _truncate(payload, 2048)
    assert encoded_size(result) <= 2048
    by_path = {cut["path"]: cut for cut in cuts}
    assert by_path["rows"]["total"] == 1000 and by_path["rows"]["kept"] == len(result["rows"])
    assert by_path["text"]["total_chars"] == 50_000
    assert result["text"].startswith("y" * by_path["text"]["kept_chars"] + "…[truncated")
    assert _truncate(payload, 10**6) == (payload, [])
