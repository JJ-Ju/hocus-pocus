"""Deterministic lexer for the HocusScript 0.1 preview grammar."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .diagnostics import CodeOffsetMap, Diagnostic, HocusSourceError, SourcePosition, SourceSpan

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")

_PUNCTUATION = {
    "@": "AT",
    "(": "LPAREN",
    ")": "RPAREN",
    "{": "LBRACE",
    "}": "RBRACE",
    "[": "LBRACKET",
    "]": "RBRACKET",
    ":": "COLON",
    "=": "EQUAL",
    ".": "DOT",
    ",": "COMMA",
    ";": "SEMICOLON",
}


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: Any
    lexeme: str
    span: SourceSpan
    body_span: SourceSpan | None = None
    code_offset_map: CodeOffsetMap | None = None


class Lexer:
    def __init__(
        self,
        source: str,
        source_name: str,
        *,
        max_source_bytes: int = 1024 * 1024,
        max_tokens: int = 250_000,
        max_literal_bytes: int = 256 * 1024,
        max_code_bytes: int = 256 * 1024,
        max_numeric_characters: int = 256,
    ):
        self._source = source
        self._source_name = source_name
        self._max_tokens = max_tokens
        self._max_literal_bytes = max_literal_bytes
        self._max_code_bytes = max_code_bytes
        self._max_numeric_characters = max_numeric_characters
        self._index = 0
        self._line = 1
        self._column = 1
        try:
            source_size = len(source.encode("utf-8"))
        except UnicodeEncodeError as exc:
            prefix = source[: exc.start]
            line = prefix.count("\n") + 1
            last_newline = prefix.rfind("\n")
            column = exc.start - last_newline
            start = SourcePosition(exc.start, line, column)
            end = SourcePosition(exc.end, line, column + max(1, exc.end - exc.start))
            raise HocusSourceError(
                Diagnostic(
                    "error",
                    "HOCUS010",
                    "lex",
                    "Source contains an invalid Unicode scalar value.",
                    SourceSpan(source_name, start, end),
                )
            ) from exc
        if source_size > max_source_bytes:
            position = SourcePosition(0, 1, 1)
            raise HocusSourceError(
                Diagnostic(
                    "error",
                    "HOCUS001",
                    "lex",
                    f"Source exceeds the {max_source_bytes}-byte limit.",
                    SourceSpan(source_name, position, position),
                )
            )

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        while self._index < len(self._source):
            self._skip_trivia()
            if self._index >= len(self._source):
                break
            if len(tokens) >= self._max_tokens:
                self._error("HOCUS002", f"Token count exceeds the {self._max_tokens}-token limit.")
            tokens.append(self._next_token())
        position = self._position()
        tokens.append(Token("EOF", None, "", SourceSpan(self._source_name, position, position)))
        return tokens

    def _skip_trivia(self) -> None:
        while self._index < len(self._source):
            char = self._source[self._index]
            if char.isspace():
                self._advance()
                continue
            if self._source.startswith("//", self._index):
                self._advance(2)
                while self._index < len(self._source) and self._source[self._index] not in "\r\n":
                    self._advance()
                continue
            if self._source.startswith("/*", self._index):
                start = self._position()
                self._advance(2)
                while self._index < len(self._source) and not self._source.startswith("*/", self._index):
                    self._advance()
                if self._index >= len(self._source):
                    self._error("HOCUS003", "Unterminated block comment.", start=start)
                self._advance(2)
                continue
            break

    def _next_token(self) -> Token:
        start = self._position()
        char = self._source[self._index]
        if char in _PUNCTUATION:
            self._advance()
            return Token(_PUNCTUATION[char], char, char, self._span(start))
        if char == '"':
            return self._string_token(start)
        if char == "`":
            return self._code_token(start)
        identifier = _IDENTIFIER.match(self._source, self._index)
        if identifier is not None:
            lexeme = identifier.group(0)
            self._advance(len(lexeme))
            return Token("IDENT", lexeme, lexeme, self._span(start))
        number = _NUMBER.match(self._source, self._index)
        if number is not None:
            lexeme = number.group(0)
            self._advance(len(lexeme))
            if len(lexeme) > self._max_numeric_characters:
                self._error(
                    "HOCUS012",
                    f"Numeric literal exceeds the {self._max_numeric_characters}-character limit.",
                    start=start,
                )
            value: int | float
            try:
                if any(marker in lexeme for marker in ".eE"):
                    value = float(lexeme)
                    if not math.isfinite(value):
                        self._error("HOCUS013", "Numeric literals must be finite.", start=start)
                else:
                    value = int(lexeme)
            except ValueError:
                self._error("HOCUS012", "Numeric literal is too large to represent safely.", start=start)
            return Token("NUMBER", value, lexeme, self._span(start))
        self._error("HOCUS004", f"Unexpected character: {char!r}.", start=start)
        raise AssertionError("unreachable")

    def _string_token(self, start: SourcePosition) -> Token:
        start_index = self._index
        self._advance()
        escaped = False
        while self._index < len(self._source):
            char = self._source[self._index]
            if char in "\r\n":
                self._error("HOCUS005", "String literals may not contain an unescaped newline.", start=start)
            if char == '"' and not escaped:
                self._advance()
                lexeme = self._source[start_index:self._index]
                try:
                    value = json.loads(lexeme)
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    self._error("HOCUS006", f"Invalid string escape: {exc}.", start=start)
                try:
                    literal_size = len(value.encode("utf-8"))
                except UnicodeEncodeError:
                    self._error("HOCUS010", "String contains an invalid Unicode scalar value.", start=start)
                if literal_size > self._max_literal_bytes:
                    self._error(
                        "HOCUS011",
                        f"String literal exceeds the {self._max_literal_bytes}-byte limit.",
                        start=start,
                    )
                return Token("STRING", value, lexeme, self._span(start))
            if char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
            self._advance()
        self._error("HOCUS007", "Unterminated string literal.", start=start)
        raise AssertionError("unreachable")

    def _code_token(self, start: SourcePosition) -> Token:
        self._advance()
        body_start = self._position()
        body: list[str] = []
        checkpoints: list[tuple[int, int]] = [(0, body_start.offset)]
        while self._index < len(self._source):
            if self._source.startswith("\\`", self._index):
                body.append("`")
                self._advance(2)
                checkpoints.append((len(body), self._index))
                continue
            char = self._source[self._index]
            if char == "`":
                body_end = self._position()
                if checkpoints[-1] != (len(body), body_end.offset):
                    checkpoints.append((len(body), body_end.offset))
                self._advance()
                value = "".join(body)
                if len(value.encode("utf-8")) > self._max_code_bytes:
                    self._error(
                        "HOCUS008",
                        f"Embedded code exceeds the {self._max_code_bytes}-byte limit.",
                        start=start,
                    )
                return Token(
                    "CODE",
                    value,
                    value,
                    self._span(start),
                    body_span=SourceSpan(self._source_name, body_start, body_end),
                    code_offset_map=CodeOffsetMap(len(body), tuple(checkpoints)),
                )
            body.append(char)
            self._advance()
        self._error("HOCUS009", "Unterminated embedded code template.", start=start)
        raise AssertionError("unreachable")

    def _advance(self, count: int = 1) -> None:
        for _ in range(count):
            if self._index >= len(self._source):
                return
            char = self._source[self._index]
            self._index += 1
            if char == "\n":
                self._line += 1
                self._column = 1
            else:
                self._column += 1

    def _position(self) -> SourcePosition:
        return SourcePosition(self._index, self._line, self._column)

    def _span(self, start: SourcePosition) -> SourceSpan:
        return SourceSpan(self._source_name, start, self._position())

    def _error(self, code: str, message: str, *, start: SourcePosition | None = None) -> None:
        actual_start = start or self._position()
        raise HocusSourceError(
            Diagnostic(
                "error",
                code,
                "lex",
                message,
                SourceSpan(self._source_name, actual_start, self._position()),
            )
        )
