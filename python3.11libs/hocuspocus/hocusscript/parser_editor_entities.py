"""Parser mixin for the closed language-0.4 network-editor surface."""

from __future__ import annotations

from .editor_syntax import (
    EditorConnectionRef,
    EditorDestinationRef,
    EditorDestinationRefs,
    EditorEntityDecl,
    EditorItemRef,
    EditorItemRefs,
    EditorProperty,
)
from .diagnostics import SourceSpan
from .syntax import ArrayExpr, LiteralExpr


_PROPERTY_KINDS = {
    "network_box": {
        "label": "literal", "position": "array", "size": "array",
        "color": "array", "items": "refs",
    },
    "sticky_note": {
        "text": "literal", "position": "array", "size": "array",
        "color": "array", "text_size": "literal",
        "background": "literal", "minimized": "literal",
    },
    "node_comment": {
        "node": "ref", "text": "literal", "visible": "literal",
    },
    "network_dot": {
        "position": "array", "pinned": "literal", "input": "connection",
        "outputs": "destinations",
    },
    "layout_constraint": {
        "kind": "literal", "items": "refs", "anchor": "ref",
        "offset": "array", "spacing": "literal", "padding": "array",
        "priority": "literal",
    },
}
_ITEM_KINDS = {"node", "dot", "box", "sticky"}


class EditorEntityParserMixin:
    def _parse_editor_entity(self):
        start = self._advance()
        kind = str(start.value)
        self._expect("AT", "HOCUS933", "Editor declarations require an explicit @id.")
        self._expect_ident("id", "HOCUS933", "Expected id after '@'.")
        self._expect("LPAREN", "HOCUS933", "Expected '(' after @id.")
        identity = self._expect(
            "STRING", "HOCUS933", "Expected a quoted durable editor entity ID."
        )
        self._expect("RPAREN", "HOCUS933", "Expected ')' after the editor entity ID.")
        self._expect("LBRACE", "HOCUS933", "Expected '{' before editor properties.")
        properties = []
        seen: set[str] = set()
        while self._current().kind not in {"RBRACE", "EOF"}:
            name = self._expect(
                "IDENT", "HOCUS934", "Expected an editor property name."
            )
            property_name = str(name.value)
            expected = _PROPERTY_KINDS[kind].get(property_name)
            if expected is None:
                self._error(
                    "HOCUS934",
                    f"Unsupported {kind} property: {property_name}.",
                    token=name,
                )
            if property_name in seen:
                self._error(
                    "HOCUS934",
                    f"Duplicate {kind} property: {property_name}.",
                    token=name,
                )
            seen.add(property_name)
            self._expect("EQUAL", "HOCUS934", "Expected '=' after editor property.")
            value = self._parse_editor_property(expected)
            end = self._statement_end()
            properties.append(
                EditorProperty(
                    property_name,
                    value,
                    self._joined_span(name, end),
                    name.span,
                )
            )
        end = self._expect(
            "RBRACE", "HOCUS935", "Expected '}' to close editor declaration."
        )
        return EditorEntityDecl(
            kind,
            str(identity.value),
            tuple(properties),
            self._joined_span(start, end),
            identity.span,
        )

    def _parse_editor_property(self, expected: str):
        if expected == "ref":
            return self._parse_editor_item_ref()
        if expected == "refs":
            return self._parse_editor_item_refs()
        if expected == "connection":
            return self._parse_editor_connection_ref()
        if expected == "destinations":
            return self._parse_editor_destinations()
        value = self._parse_value()
        required = ArrayExpr if expected == "array" else LiteralExpr
        if not isinstance(value, required):
            self._error(
                "HOCUS936",
                f"Editor property requires a {expected} value.",
            )
        return value

    def _parse_editor_item_ref(self):
        start = self._expect(
            "IDENT", "HOCUS937", "Expected node, dot, box, or sticky reference."
        )
        kind = str(start.value)
        if kind not in _ITEM_KINDS:
            self._error("HOCUS937", "Unsupported editor item reference kind.", token=start)
        token_kind = "IDENT" if kind == "node" else "STRING"
        identity = self._expect(
            token_kind,
            "HOCUS937",
            "Node references use symbols; editor-item references use quoted IDs.",
        )
        return EditorItemRef(
            kind,
            str(identity.value),
            self._joined_span(start, identity),
            identity.span,
        )

    def _parse_editor_item_refs(self):
        start = self._expect("LBRACKET", "HOCUS938", "Expected '[' before item references.")
        items = []
        if self._current().kind != "RBRACKET":
            while True:
                items.append(self._parse_editor_item_ref())
                if self._match("COMMA") is None:
                    break
        end = self._expect("RBRACKET", "HOCUS938", "Expected ']' after item references.")
        return EditorItemRefs(tuple(items), self._joined_span(start, end))

    def _parse_editor_connection_ref(self):
        item = self._parse_editor_item_ref()
        self._expect("DOT", "HOCUS939", "Editor connections require .output[index].")
        self._expect_ident(
            "output", "HOCUS939", "Editor connections require .output[index]."
        )
        self._expect("LBRACKET", "HOCUS939", "Expected '[' before output index.")
        index = self._expect("NUMBER", "HOCUS939", "Expected an integer output index.")
        if type(index.value) is not int or index.value < 0:
            self._error(
                "HOCUS939", "Editor output index must be a nonnegative integer.",
                token=index,
            )
        end = self._expect("RBRACKET", "HOCUS939", "Expected ']' after output index.")
        return EditorConnectionRef(
            item,
            index.value,
            SourceSpan(item.span.source_name, item.span.start, end.span.end),
            index.span,
        )

    def _parse_editor_destinations(self):
        start = self._expect(
            "LBRACKET", "HOCUS941", "Expected '[' before dot destinations."
        )
        items = []
        if self._current().kind != "RBRACKET":
            while True:
                node = self._parse_editor_item_ref()
                if node.item_kind != "node":
                    self._error(
                        "HOCUS941", "Dot destinations must reference node inputs."
                    )
                self._expect(
                    "DOT", "HOCUS941", "Dot destinations require .input[index]."
                )
                self._expect_ident(
                    "input", "HOCUS941", "Dot destinations require .input[index]."
                )
                self._expect(
                    "LBRACKET", "HOCUS941", "Expected '[' before input index."
                )
                index = self._expect(
                    "NUMBER", "HOCUS941", "Expected an integer input index."
                )
                if type(index.value) is not int or index.value < 0:
                    self._error(
                        "HOCUS941",
                        "Dot destination input index must be nonnegative.",
                        token=index,
                    )
                end = self._expect(
                    "RBRACKET", "HOCUS941", "Expected ']' after input index."
                )
                items.append(
                    EditorDestinationRef(
                        node,
                        index.value,
                        SourceSpan(node.span.source_name, node.span.start, end.span.end),
                        index.span,
                    )
                )
                if self._match("COMMA") is None:
                    break
        end = self._expect(
            "RBRACKET", "HOCUS941", "Expected ']' after dot destinations."
        )
        return EditorDestinationRefs(tuple(items), self._joined_span(start, end))
