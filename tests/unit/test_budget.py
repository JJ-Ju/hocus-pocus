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


# -- clipping on a character boundary (review 25 papercut 8) --------------------------------


def test_byte_cuts_never_decode_to_a_replacement_character():
    from hocuspocus.tools.budget import utf8_head, utf8_tail

    data = "areas tha… été \U0001f600 end".encode()
    for cut in range(len(data) + 1):
        head, tail = utf8_head(data[:cut]), utf8_tail(data[cut:])
        assert "�" not in head and "�" not in tail, cut
        assert data.decode().startswith(head) and data.decode().endswith(tail)
    assert utf8_head(data[:10]) == "areas tha"  # the 3-byte ellipsis cut after one byte
    assert utf8_head(b"bad \xff byte") == "bad � byte"  # real damage still shows


def test_clip_cuts_on_a_character_and_marks_it():
    from hocuspocus.tools.budget import clip

    assert clip("short", 10) == "short"
    assert clip("abcdefghij", 5) == "abcd…"
    assert clip("ab \U0001f600cd", 5) == "ab \U0001f600…"
    pair = chr(0xD83D) + chr(0xDE00)  # UTF-16 text decoded with surrogatepass
    assert clip("ab" + pair + "cd", 4) == "ab" + chr(0x2026)  # never split a surrogate pair


def test_help_head_read_drops_a_cut_character(tmp_path):
    import zipfile

    from hocuspocus.host.tools.types import _HelpArchive

    text = '"""Creates a mask, letting you limit the effect to areas thät are visible."""'
    path = tmp_path / "nodes.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("sop/x.txt", text.encode("utf-8"))
    help_zip = _HelpArchive()
    help_zip._opened, help_zip._zip = True, zipfile.ZipFile(path)
    help_zip._names = frozenset(help_zip._zip.namelist())
    cut = text.encode("utf-8").index("ä".encode()) + 1  # inside the two-byte a-umlaut
    head = help_zip.read("sop/x.txt", cut)
    assert "�" not in head and head.endswith("areas th")
    help_zip._zip.close()
