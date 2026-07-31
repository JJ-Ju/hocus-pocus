"""Small public entry point for the bounded HocusScript parser."""

from __future__ import annotations

from .lexer import Lexer


def parse_syntax(source: str, source_name: str = "<memory>"):
    from .parser import Parser

    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not isinstance(source_name, str) or not source_name.strip():
        raise TypeError("source_name must be a non-empty string")
    parser = Parser(Lexer(source, source_name).tokenize())
    syntax = parser.parse()
    if parser.diagnostics:
        from .diagnostics import HocusSourceError

        raise HocusSourceError(parser.diagnostics[0])
    return syntax
