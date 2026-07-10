from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript.diagnostics import HocusSourceError
from hocuspocus.hocusscript.lexer import Lexer


class HocusScriptLexerTests(unittest.TestCase):
    def test_comments_numbers_strings_and_code_keep_spans(self) -> None:
        source = '''// heading
hocus 0.1;
/* graph comment */ graph demo {
  target "/obj/geo1";
  node wrangle: "attribwrangle" {
    value = -1.25e2;
    snippet = vex`@Cd = {1, 0, 0};`;
  }
}
'''
        tokens = Lexer(source, "demo.hocus").tokenize()
        kinds = [token.kind for token in tokens]
        self.assertIn("STRING", kinds)
        self.assertIn("NUMBER", kinds)
        self.assertIn("CODE", kinds)
        code = next(token for token in tokens if token.kind == "CODE")
        self.assertEqual(code.value, "@Cd = {1, 0, 0};")
        self.assertEqual(code.span.start.line, 7)
        self.assertEqual(code.span.start.column, 18)

    def test_escaped_backtick_round_trips_in_code_token(self) -> None:
        token = next(
            item
            for item in Lexer('vex`a\\`b`', "code.hocus").tokenize()
            if item.kind == "CODE"
        )
        self.assertEqual(token.value, "a`b")

    def test_json_string_escapes_decode_deterministically(self) -> None:
        token = next(
            item
            for item in Lexer('"line\\n\\u263a"', "string.hocus").tokenize()
            if item.kind == "STRING"
        )
        self.assertEqual(token.value, "line\n☺")

    def test_unterminated_block_comment_is_structured(self) -> None:
        with self.assertRaises(HocusSourceError) as captured:
            Lexer("/* no end", "bad.hocus").tokenize()
        self.assertEqual(captured.exception.diagnostic.code, "HOCUS003")
        self.assertEqual(captured.exception.diagnostic.span.start.line, 1)

    def test_source_limit_is_enforced(self) -> None:
        with self.assertRaises(HocusSourceError) as captured:
            Lexer("x" * 20, "large.hocus", max_source_bytes=10)
        self.assertEqual(captured.exception.diagnostic.code, "HOCUS001")

    def test_string_literal_limit_is_enforced(self) -> None:
        with self.assertRaises(HocusSourceError) as captured:
            Lexer('"12345"', "large-string.hocus", max_literal_bytes=4).tokenize()
        self.assertEqual(captured.exception.diagnostic.code, "HOCUS011")

    def test_invalid_unicode_is_a_structured_lexer_error(self) -> None:
        with self.assertRaises(HocusSourceError) as captured:
            Lexer("\ud800", "unicode.hocus")
        self.assertEqual(captured.exception.diagnostic.code, "HOCUS010")


if __name__ == "__main__":
    unittest.main()
