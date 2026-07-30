"""Language-0.4 discriminated tagged-value parser."""

from __future__ import annotations

from typing import Any

from .diagnostics import SourceSpan
from .syntax import (
    ArrayExpr,
    ChannelReferenceValue,
    CodeExpr,
    ExpressionValue,
    LiteralExpr,
    MultiparmFieldExpr,
    MultiparmInstanceExpr,
    MultiparmValue,
    QuantityValue,
    RampPointExpr,
    RampValue,
    RawPathValue,
    ResetValue,
    TaggedValueExpr,
    ValueExpr,
)


TAGGED_VALUE_NAMES = frozenset({
    "reset",
    "expression",
    "channel",
    "raw_path",
    "quantity",
    "ramp",
    "multiparm",
})
_RAW_PATH_KINDS = {"node", "parm", "file", "usd_prim", "asset"}


class TaggedValueParserMixin:
    """Exact grammar mixed into the main version-dispatched parser."""

    def _parse_value(self, depth: int = 0) -> ValueExpr:
        if depth > min(self._max_value_depth, 64):
            self._error("HOCUS246", "Value nesting exceeds the 64-level limit.")
        self._value_items += 1
        if self._value_items > 100_000:
            self._error("HOCUS246", "Aggregate value count exceeds the 100000-value limit.")
        token = self._current()
        if token.kind in {"STRING", "NUMBER"}:
            self._advance()
            return LiteralExpr(token.value, token.span)
        if token.kind == "IDENT" and token.value in {"true", "false", "null"}:
            self._advance()
            value = {"true": True, "false": False, "null": None}[str(token.value)]
            return LiteralExpr(value, token.span)
        if token.kind == "IDENT" and token.value in {"vex", "python", "hscript"}:
            language = self._advance()
            code = self._expect(
                "CODE", "HOCUS241",
                "Expected a raw code template after the language tag.",
            )
            if code.body_span is None or code.code_offset_map is None:
                raise RuntimeError("CODE token is missing body source-map metadata")
            return CodeExpr(
                str(language.value),
                str(code.value),
                SourceSpan(language.span.source_name, language.span.start, code.span.end),
                code.body_span,
                code.code_offset_map,
            )
        if (
            self._language_version == "0.4"
            and token.kind == "IDENT"
            and token.value in TAGGED_VALUE_NAMES
            and self._tokens[self._index + 1].kind == "LPAREN"
        ):
            return self._parse_tagged_value(depth)
        if token.kind == "LBRACKET":
            return self._parse_array_value(depth)
        self._error(
            "HOCUS243",
            "Expected a scalar, array, code, or typed value.",
        )
        raise AssertionError("unreachable")

    def _parse_array_value(self, depth: int) -> ArrayExpr:
        start = self._advance()
        values: list[ValueExpr] = []
        trailing_comma = False
        if self._current().kind != "RBRACKET":
            while True:
                values.append(self._parse_value(depth + 1))
                if self._match("COMMA") is None:
                    break
                if self._current().kind == "RBRACKET":
                    trailing_comma = True
                    break
        end = self._expect(
            "RBRACKET", "HOCUS242", "Expected ']' to close the array."
        )
        return ArrayExpr(tuple(values), trailing_comma, self._joined_span(start, end))

    def _parse_tagged_value(self, depth: int) -> TaggedValueExpr:
        tag = self._advance()
        self._expect("LPAREN", "HOCUS247", f"Expected '(' after {tag.value}.")
        parser = {
            "reset": self._parse_reset_value,
            "expression": self._parse_expression_value,
            "channel": self._parse_channel_value,
            "raw_path": self._parse_raw_path_value,
            "quantity": self._parse_quantity_value,
            "ramp": lambda: self._parse_ramp_value(depth),
            "multiparm": lambda: self._parse_multiparm_value(depth),
        }[str(tag.value)]
        payload = parser()
        end = self._expect("RPAREN", "HOCUS248", f"Expected ')' after {tag.value}.")
        return TaggedValueExpr(str(tag.value), payload, self._joined_span(tag, end))

    def _parse_reset_value(self) -> ResetValue:
        if self._current().kind != "RPAREN":
            self._error("HOCUS247", "reset() does not accept arguments.")
        return ResetValue()

    def _parse_expression_value(self) -> ExpressionValue:
        language = self._expect("IDENT", "HOCUS247", "Expected an expression language.")
        if language.value not in {"hscript", "python"}:
            self._error(
                "HOCUS247",
                "Expression language must be hscript or python.",
                token=language,
            )
        code = self._expect(
            "CODE", "HOCUS247", "Expected an exact raw expression body."
        )
        if code.body_span is None or code.code_offset_map is None:
            raise RuntimeError("CODE token is missing body source-map metadata")
        return ExpressionValue(
            str(language.value),
            str(code.value),
            code.body_span,
            code.code_offset_map,
        )

    def _parse_channel_value(self) -> ChannelReferenceValue:
        node = self._expect_authored_ident(
            "HOCUS247", "Expected a channel source node symbol."
        )
        self._expect("COMMA", "HOCUS247", "Expected ',' after channel node symbol.")
        parm = self._expect_authored_ident(
            "HOCUS247", "Expected a channel source parameter name."
        )
        return ChannelReferenceValue(
            str(node.value), str(parm.value), node.span, parm.span
        )

    def _parse_raw_path_value(self) -> RawPathValue:
        kind = self._expect("IDENT", "HOCUS247", "Expected a raw path kind.")
        if kind.value not in _RAW_PATH_KINDS:
            self._error(
                "HOCUS247",
                f"Raw path kind must be one of {sorted(_RAW_PATH_KINDS)}.",
                token=kind,
            )
        self._expect("COMMA", "HOCUS247", "Expected ',' after raw path kind.")
        raw = self._expect("STRING", "HOCUS247", "Expected a raw path string.")
        return RawPathValue(str(kind.value), str(raw.value), kind.span, raw.span)

    def _parse_quantity_value(self) -> QuantityValue:
        magnitude = self._expect(
            "NUMBER", "HOCUS247", "Expected a finite quantity magnitude."
        )
        self._expect("COMMA", "HOCUS247", "Expected ',' after quantity magnitude.")
        unit = self._expect("STRING", "HOCUS247", "Expected a quantity unit.")
        return QuantityValue(
            magnitude.value, str(unit.value), magnitude.span, unit.span
        )

    def _parse_ramp_value(self, depth: int) -> RampValue:
        self._expect_ident(
            "points", "HOCUS247", "Expected points = [...] in ramp()."
        )
        self._expect("EQUAL", "HOCUS247", "Expected '=' after ramp points.")
        points = self._parse_ramp_points(depth)
        self._expect("COMMA", "HOCUS247", "Expected ',' after ramp points.")
        self._expect_ident(
            "basis", "HOCUS247", "Expected basis = [...] in ramp()."
        )
        self._expect("EQUAL", "HOCUS247", "Expected '=' after ramp basis.")
        basis = self._parse_string_array("ramp basis")
        return RampValue(tuple(points), tuple(basis))

    def _parse_ramp_points(self, depth: int) -> list[RampPointExpr]:
        self._expect("LBRACKET", "HOCUS247", "Expected '[' before ramp points.")
        points: list[RampPointExpr] = []
        while self._current().kind != "RBRACKET":
            start = self._expect(
                "LBRACKET", "HOCUS247", "Expected '[position, value]' ramp point."
            )
            position = self._expect(
                "NUMBER", "HOCUS247", "Expected a numeric ramp position."
            )
            self._expect("COMMA", "HOCUS247", "Expected ',' after ramp position.")
            value = self._parse_value(depth + 1)
            if not isinstance(value, (LiteralExpr, ArrayExpr)):
                self._error(
                    "HOCUS247",
                    "Ramp point values must be scalar or tuple literals.",
                    token=self._current(),
                )
            end = self._expect("RBRACKET", "HOCUS247", "Expected ']' after ramp point.")
            points.append(
                RampPointExpr(
                    position.value,
                    value,
                    self._joined_span(start, end),
                    position.span,
                )
            )
            if self._match("COMMA") is None:
                break
            if self._current().kind == "RBRACKET":
                break
        self._expect("RBRACKET", "HOCUS247", "Expected ']' after ramp points.")
        return points

    def _parse_string_array(self, label: str) -> list[str]:
        self._expect("LBRACKET", "HOCUS247", f"Expected '[' before {label}.")
        values: list[str] = []
        while self._current().kind != "RBRACKET":
            token = self._expect("STRING", "HOCUS247", f"Expected a string {label} item.")
            values.append(str(token.value))
            if self._match("COMMA") is None:
                break
            if self._current().kind == "RBRACKET":
                break
        self._expect("RBRACKET", "HOCUS247", f"Expected ']' after {label}.")
        return values

    def _parse_multiparm_value(self, depth: int) -> MultiparmValue:
        self._expect_ident(
            "instances", "HOCUS247", "Expected instances = [...] in multiparm()."
        )
        self._expect("EQUAL", "HOCUS247", "Expected '=' after multiparm instances.")
        self._expect("LBRACKET", "HOCUS247", "Expected '[' before multiparm instances.")
        instances: list[MultiparmInstanceExpr] = []
        while self._current().kind != "RBRACKET":
            instances.append(self._parse_multiparm_instance(depth))
            if self._match("COMMA") is None:
                break
            if self._current().kind == "RBRACKET":
                break
        self._expect("RBRACKET", "HOCUS247", "Expected ']' after multiparm instances.")
        return MultiparmValue(tuple(instances))

    def _parse_multiparm_instance(self, depth: int) -> MultiparmInstanceExpr:
        start = self._expect_ident(
            "instance", "HOCUS247", "Expected instance(id, {...})."
        )
        self._expect("LPAREN", "HOCUS247", "Expected '(' after instance.")
        identity = self._expect(
            "STRING", "HOCUS247", "Expected a stable multiparm instanceId."
        )
        self._expect("COMMA", "HOCUS247", "Expected ',' after multiparm instanceId.")
        self._expect("LBRACE", "HOCUS247", "Expected '{' before multiparm fields.")
        fields: list[MultiparmFieldExpr] = []
        while self._current().kind != "RBRACE":
            name = self._expect_authored_ident(
                "HOCUS247", "Expected a multiparm field name."
            )
            self._expect("EQUAL", "HOCUS247", "Expected '=' after multiparm field.")
            value = self._parse_value(depth + 1)
            end = self._expect(
                "SEMICOLON", "HOCUS247", "Expected ';' after multiparm field."
            )
            fields.append(
                MultiparmFieldExpr(
                    str(name.value),
                    value,
                    self._joined_span(name, end),
                    name.span,
                )
            )
        self._expect("RBRACE", "HOCUS247", "Expected '}' after multiparm fields.")
        end = self._expect("RPAREN", "HOCUS247", "Expected ')' after multiparm instance.")
        return MultiparmInstanceExpr(
            str(identity.value),
            tuple(fields),
            self._joined_span(start, end),
            identity.span,
        )


def tagged_value_parser_types() -> tuple[type[Any], ...]:
    """Expose the closed payload set to structural checks without cycles."""

    return (
        ResetValue,
        ExpressionValue,
        ChannelReferenceValue,
        RawPathValue,
        QuantityValue,
        RampValue,
        MultiparmValue,
    )
