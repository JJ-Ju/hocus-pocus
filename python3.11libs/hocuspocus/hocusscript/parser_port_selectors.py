"""Strict language-versioned input/output selector parsing."""

from __future__ import annotations

from typing import Any


class PortSelectorParserMixin:
    """Shared selector parser for graph and module statements."""

    def _parse_port_selector(
        self,
        *,
        expected_code: str,
        integer_code: str,
        expected_message: str,
        integer_message: str,
    ) -> tuple[int | None, str | None, Any, Any]:
        token = self._current()
        if self._language_version == "0.4" and token.kind == "STRING":
            self._advance()
            if not token.value:
                self._error(expected_code, "Port names cannot be empty.", token=token)
            end = self._expect("RBRACKET", expected_code, "Expected ']' after the port name.")
            return None, str(token.value), token.span, end
        token = self._expect("NUMBER", expected_code, expected_message)
        if not isinstance(token.value, int):
            self._error(integer_code, integer_message, token=token)
        end = self._expect("RBRACKET", expected_code, "Expected ']' after the port index.")
        return token.value, None, token.span, end
