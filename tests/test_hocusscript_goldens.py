from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import compile_source

FIXTURES = ROOT / "tests" / "fixtures" / "hocusscript" / "v0.1"


def _without_spans(value):
    if isinstance(value, dict):
        return {
            key: _without_spans(item)
            for key, item in value.items()
            if key not in {"span", "bodySpan", "offsetMap", "fieldSpans"}
        }
    if isinstance(value, list):
        return [_without_spans(item) for item in value]
    return value


class HocusScriptGoldenTests(unittest.TestCase):
    def test_all_features_source_lowers_to_checked_in_graphspec(self) -> None:
        source_path = FIXTURES / "all_features.hocus"
        source_uri = "hocus-fixture:///v0.1/all_features.hocus"
        source = source_path.read_text(encoding="utf-8")
        result = compile_source(source, source_path.name, source_uri=source_uri)
        self.assertTrue(result.valid, [item.to_dict() for item in result.diagnostics])
        assert result.graph_spec is not None
        expected = json.loads((FIXTURES / "all_features.graph.json").read_text(encoding="utf-8"))
        self.assertEqual(_without_spans(result.graph_spec.to_dict()), expected)

        assert result.formatted_source is not None
        formatted = compile_source(result.formatted_source, source_path.name, source_uri=source_uri)
        self.assertTrue(formatted.valid, [item.to_dict() for item in formatted.diagnostics])
        assert formatted.graph_spec is not None
        self.assertEqual(_without_spans(formatted.graph_spec.to_dict()), expected)
        self.assertEqual(formatted.formatted_source, result.formatted_source)

    def test_recovery_diagnostics_match_checked_in_locations(self) -> None:
        source_path = FIXTURES / "recovery.hocus"
        result = compile_source(
            source_path.read_text(encoding="utf-8"),
            source_path.name,
            source_uri="hocus-fixture:///v0.1/recovery.hocus",
        )
        self.assertFalse(result.valid)
        expected = json.loads((FIXTURES / "recovery.diagnostics.json").read_text(encoding="utf-8"))
        actual = [
            {"code": item.code, "line": item.span.start.line, "column": item.span.start.column}
            for item in result.diagnostics
            if item.code in {"HOCUS207", "HOCUS208", "HOCUS243"}
        ]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
