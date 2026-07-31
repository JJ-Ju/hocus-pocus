"""Parser mixin for node-local language-0.4 runtime declarations."""

from __future__ import annotations

from .runtime_syntax import AnimationDecl, RuntimeProperty, SpareParameterDecl


_FIELDS = {
    "spare": {
        "label", "type", "tuple_size", "default", "menu_items",
    },
    "animate": {
        "value_type", "value", "authored_fps", "display_fps",
        "extrapolation", "keys",
    },
}


class RuntimeEntityParserMixin:
    def _parse_runtime_node_statement(self):
        if self._language_version != "0.4":
            return None
        if self._is_ident("spare") or self._is_ident("animate"):
            return self._parse_runtime_entity()
        if self._is_ident("time_sample"):
            self._error(
                "HOCUS946",
                "USD time samples are outside the HS7 animation lane.",
            )
        return None

    def _parse_runtime_entity(self):
        start = self._advance()
        kind = str(start.value)
        name = self._expect(
            "IDENT", "HOCUS943",
            "Expected a spare name or exact parameter/component token.",
        )
        self._expect("AT", "HOCUS943", "Runtime declarations require an explicit @id.")
        self._expect_ident("id", "HOCUS943", "Expected id after '@'.")
        self._expect("LPAREN", "HOCUS943", "Expected '(' after @id.")
        identity = self._expect(
            "STRING", "HOCUS943", "Expected a quoted durable runtime entity ID."
        )
        self._expect("RPAREN", "HOCUS943", "Expected ')' after the runtime entity ID.")
        self._expect("LBRACE", "HOCUS943", "Expected '{' before runtime properties.")
        properties: list[RuntimeProperty] = []
        seen: set[str] = set()
        while self._current().kind not in {"RBRACE", "EOF"}:
            field = self._expect(
                "IDENT", "HOCUS944", "Expected a runtime property name."
            )
            field_name = str(field.value)
            if field_name not in _FIELDS[kind]:
                self._error(
                    "HOCUS944",
                    f"Unsupported {kind} property: {field_name}.",
                    token=field,
                )
            if field_name in seen:
                self._error(
                    "HOCUS944", f"Duplicate {kind} property: {field_name}.",
                    token=field,
                )
            seen.add(field_name)
            self._expect("EQUAL", "HOCUS944", "Expected '=' after runtime property.")
            value = self._parse_value()
            end = self._statement_end()
            properties.append(RuntimeProperty(
                field_name, value, self._joined_span(field, end), field.span,
            ))
        end = self._expect(
            "RBRACE", "HOCUS945", "Expected '}' to close runtime declaration."
        )
        common = (
            str(name.value), str(identity.value), tuple(properties),
            self._joined_span(start, end), name.span, identity.span,
        )
        return (
            SpareParameterDecl(*common)
            if kind == "spare" else AnimationDecl(*common)
        )
