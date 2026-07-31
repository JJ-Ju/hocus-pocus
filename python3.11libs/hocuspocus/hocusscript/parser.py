"""Version-dispatched recursive-descent parser for HocusScript source syntax."""

from __future__ import annotations

from .diagnostics import Diagnostic, HocusSourceError, SourceSpan
import re

from .lexer import Token
from .module_paths import is_literal_import_specifier
from .parser_tagged_values import TAGGED_VALUE_NAMES, TaggedValueParserMixin
from .parser_port_selectors import PortSelectorParserMixin
from .parser_editor_entities import EditorEntityParserMixin
from .parser_runtime_entities import RuntimeEntityParserMixin
from .editor_syntax import EDITOR_ENTITY_KEYWORDS
from .syntax import (
    CategoryStmt,
    CarryDecl,
    ControlOutputDecl,
    ExternalDecl,
    FlagStmt,
    GraphDecl,
    InputStmt,
    ImportDecl,
    LayoutStmt,
    LiteralExpr,
    ModeStmt,
    ModuleDecl,
    ModuleExportDecl,
    ModuleExpr,
    ModuleParamDecl,
    NamedArgument,
    NodeDecl,
    OwnershipStmt,
    ParmStmt,
    ParamRefExpr,
    ReferenceExpr,
    RevisionStmt,
    SyntaxSource,
    SymbolRefExpr,
    TargetStmt,
    VersionDecl,
    UseDecl,
    ExportStmt,
    ForDecl,
    IfDecl,
    YieldStmt,
)


_TYPE_NAMES = {"bool", "int", "float", "string", "node_output"}
_ID_SEED = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_RESERVED_SYMBOL_PREFIX = "__hocus_"


class Parser(
    EditorEntityParserMixin,
    RuntimeEntityParserMixin,
    PortSelectorParserMixin,
    TaggedValueParserMixin,
):
    def __init__(
        self,
        tokens: list[Token],
        *,
        max_value_depth: int = 128,
        max_nodes: int = 10_000,
        max_imports: int = 4_096,
        max_instances: int = 4_096,
        max_interface_items: int = 256,
        max_control_depth: int = 16,
        max_control_items: int = 256,
    ):
        self._tokens = tokens
        self._index = 0
        self._max_value_depth = max_value_depth
        self._max_nodes = max_nodes
        self._max_imports = max_imports
        self._max_instances = max_instances
        self._max_interface_items = max_interface_items
        self._max_control_depth = max_control_depth
        self._max_control_items = max_control_items
        self._control_items = 0
        self._value_items = 0
        self._v03_node_count = 0
        self._v03_instance_count = 0
        self._language_version = "0.1"
        self.diagnostics: list[Diagnostic] = []

    def parse(self) -> SyntaxSource:
        version: VersionDecl | None = None
        if self._is_ident("hocus"):
            start = self._advance()
            value = self._current()
            if value.kind not in {"NUMBER", "STRING"}:
                self._error("HOCUS201", "Expected a language version after 'hocus'.")
            self._advance()
            end = self._expect("SEMICOLON", "HOCUS202", "Expected ';' after the language version.")
            version = VersionDecl(
                value=value.lexeme if value.kind == "NUMBER" else str(value.value),
                quoted=value.kind == "STRING",
                span=self._joined_span(start, end),
                value_span=value.span,
            )
            self._language_version = version.value
        elif self._is_ident("graph"):
            self.diagnostics.append(
                Diagnostic(
                    "warning",
                    "HOCUS101",
                    "parse",
                    "Missing 'hocus 0.1;' header; preview compilation assumes language 0.1.",
                    self._current().span,
                )
            )

        if version is not None and version.value in {"0.2", "0.3", "0.4"}:
            return self._parse_v02_source(version)

        graph = self._parse_graph()
        self._expect("EOF", "HOCUS203", "Only one graph declaration is supported in language 0.1.")
        start = version.span.start if version is not None else graph.span.start
        return SyntaxSource(version, graph, SourceSpan(graph.span.source_name, start, graph.span.end))

    def _parse_v02_source(self, version: VersionDecl) -> SyntaxSource:
        imports: list[ImportDecl] = []
        while self._is_ident("import"):
            if len(imports) >= self._max_imports:
                self._error("HOCUS271", f"Source exceeds the {self._max_imports}-import limit.")
            imports.append(self._parse_import())
        if self._is_ident("graph"):
            graph = self._parse_graph()
            module = None
            root_span = graph.span
        elif self._is_ident("module"):
            module = self._parse_module()
            graph = None
            root_span = module.span
        else:
            self._error(
                "HOCUS260",
                f"Language {self._language_version} requires exactly one graph or module root declaration.",
            )
        self._expect(
            "EOF",
            "HOCUS260",
            f"Language {self._language_version} source supports exactly one root declaration.",
        )
        return SyntaxSource(
            version,
            graph,
            SourceSpan(root_span.source_name, version.span.start, root_span.end),
            tuple(imports),
            module,
        )

    def _parse_import(self) -> ImportDecl:
        start = self._advance()
        self._expect("LBRACE", "HOCUS261", "Expected '{' after import.")
        imported = self._expect_authored_ident("HOCUS261", "Expected one imported module name.")
        local = imported
        if self._is_ident("as"):
            self._advance()
            local = self._expect_authored_ident("HOCUS261", "Expected a local import name after 'as'.")
        self._expect("RBRACE", "HOCUS261", "Expected '}' after the import name.")
        self._expect_ident("from", "HOCUS261", "Expected 'from' after the import clause.")
        specifier = self._expect("STRING", "HOCUS262", "Import specifiers must be static string literals.")
        if not is_literal_import_specifier(str(specifier.value)):
            self._error(
                "HOCUS263",
                "Import specifiers must be portable literal .hocus paths without absolute or dynamic components.",
                token=specifier,
            )
        end = self._statement_end()
        return ImportDecl(
            str(imported.value),
            str(local.value),
            str(specifier.value),
            self._joined_span(start, end),
            imported.span,
            local.span,
            specifier.span,
        )

    def _parse_module(self) -> ModuleDecl:
        start = self._advance()
        name = self._expect_authored_ident("HOCUS264", "Expected a module name.")
        self._expect("LPAREN", "HOCUS265", "Expected '(' after the module name.")
        parameters = self._parse_interface_items(parameter=True)
        self._expect_ident("exports", "HOCUS266", "Expected an exports interface after module parameters.")
        self._expect("LPAREN", "HOCUS267", "Expected '(' after exports.")
        exports = self._parse_interface_items(parameter=False)
        self._expect("LBRACE", "HOCUS268", "Expected '{' before the module body.")
        statements = []
        counts = {"node": 0, "instance": 0}
        while self._current().kind not in {"RBRACE", "EOF"}:
            statement_index = self._index
            statement_kind = self._current().value if self._current().kind == "IDENT" else None
            try:
                statements.append(self._parse_module_statement(counts))
            except HocusSourceError as exc:
                if self._module_error_is_fatal(exc):
                    raise
                self.diagnostics.append(exc.diagnostic)
                self._recover_module_statement(exc, statement_index, statement_kind)
        end = self._expect("RBRACE", "HOCUS270", "Expected '}' to close the module.")
        return ModuleDecl(
            str(name.value),
            tuple(parameters),
            tuple(exports),
            tuple(statements),
            self._joined_span(start, end),
            name.span,
        )

    def _parse_module_statement(self, counts: dict[str, int]):
        if self._is_ident("node"):
            if self._uses_control_syntax():
                self._claim_v03_node()
            elif counts["node"] >= self._max_nodes:
                self._error("HOCUS314", f"Module exceeds the {self._max_nodes}-node limit.")
            statement = self._parse_node()
            counts["node"] += 1
            return statement
        if self._is_ident("use"):
            if self._uses_control_syntax():
                self._claim_v03_instance()
            elif counts["instance"] >= self._max_instances:
                self._error("HOCUS271", f"Module exceeds the {self._max_instances}-instance limit.")
            statement = self._parse_use()
            counts["instance"] += 1
            return statement
        if self._uses_control_syntax() and (
            self._is_ident("if") or self._is_ident("for")
        ):
            return self._parse_control(depth=1)
        if self._is_ident("export"):
            return self._parse_export()
        message = (
            "Modules support only node, use, and export statements."
            if self._language_version == "0.2"
            else "Modules support only node, use, control, and export statements."
        )
        self._error("HOCUS269", message)

    def _module_error_is_fatal(self, exc: HocusSourceError) -> bool:
        return (
            exc.diagnostic.code in {"HOCUS226", "HOCUS314", "HOCUS246"}
            or self._is_resource_limit(exc.diagnostic)
            or (
                self._language_version == "0.2"
                and exc.diagnostic.code == "HOCUS269"
                and (self._is_ident("if") or self._is_ident("for"))
            )
        )

    def _recover_module_statement(
        self, exc: HocusSourceError, statement_index: int, statement_kind: object,
    ) -> None:
        if self._uses_control_syntax() and statement_kind in {"if", "for"}:
            self._index = statement_index
            self._synchronize_control_declaration()
        elif exc.diagnostic.code in {"HOCUS222", "HOCUS223", "HOCUS224", "HOCUS225", "HOCUS300"}:
            self._synchronize_node_declaration()
        else:
            self._synchronize_statement(
                scope="module", preserve_current=exc.diagnostic.code == "HOCUS245",
            )

    def _parse_interface_items(
        self, *, parameter: bool
    ) -> list[ModuleParamDecl] | list[ModuleExportDecl]:
        items: list[ModuleParamDecl] | list[ModuleExportDecl] = []
        if self._match("RPAREN") is not None:
            return items
        while True:
            if len(items) >= self._max_interface_items:
                self._error(
                    "HOCUS271",
                    f"Module interfaces are limited to {self._max_interface_items} declarations.",
                )
            start = self._expect_authored_ident("HOCUS272", "Expected an interface name.")
            self._expect("COLON", "HOCUS273", "Expected ':' after the interface name.")
            type_token = self._expect(
                "IDENT", "HOCUS274", f"Expected a HocusScript {self._language_version} type name."
            )
            if type_token.value not in _TYPE_NAMES:
                self._error(
                    "HOCUS275",
                    "Type must be exactly bool, int, float, string, or node_output.",
                    token=type_token,
                )
            default: ModuleExpr | None = None
            default_span: SourceSpan | None = None
            if self._match("EQUAL") is not None:
                if not parameter:
                    self._error("HOCUS276", "Export interface declarations cannot have defaults.")
                if type_token.value == "node_output":
                    self._error("HOCUS276", "node_output parameters cannot have defaults.")
                default = self._parse_module_literal()
                expected_python_type = {
                    "bool": bool,
                    "int": int,
                    "float": float,
                    "string": str,
                }[str(type_token.value)]
                if type(default.value) is not expected_python_type:
                    self._error(
                        "HOCUS276",
                        f"Default for {type_token.value} must use an exact {type_token.value} literal.",
                        token=self._tokens[self._index - 1],
                    )
                default_span = default.span
            item_span = SourceSpan(start.span.source_name, start.span.start, (default or type_token).span.end)
            if parameter:
                assert isinstance(items, list)
                items.append(ModuleParamDecl(
                    str(start.value), str(type_token.value), default, item_span,
                    start.span, type_token.span, default_span,
                ))
            else:
                assert isinstance(items, list)
                items.append(ModuleExportDecl(
                    str(start.value), str(type_token.value), item_span, start.span, type_token.span
                ))
            if self._match("COMMA") is None:
                self._expect("RPAREN", "HOCUS277", "Expected ')' after the module interface.")
                return items
            if self._match("RPAREN") is not None:
                return items

    def _parse_use(self) -> UseDecl:
        start = self._advance()
        symbol = self._expect_authored_ident("HOCUS278", "Expected a local use symbol.")
        self._expect(
            "AT", "HOCUS279", f"Every language {self._language_version} use declaration requires @id."
        )
        annotation = self._expect("IDENT", "HOCUS279", "Expected id after '@'.")
        if annotation.value != "id":
            self._error("HOCUS279", "Only @id is supported on use declarations.", token=annotation)
        self._expect("LPAREN", "HOCUS279", "Expected '(' after @id.")
        seed = self._expect("STRING", "HOCUS280", "Expected a quoted durable use ID.")
        if not _ID_SEED.fullmatch(str(seed.value)):
            self._error(
                "HOCUS281",
                "Use IDs must match [A-Za-z0-9][A-Za-z0-9._:-]{0,127}.",
                token=seed,
            )
        self._expect("RPAREN", "HOCUS279", "Expected ')' after the durable use ID.")
        self._expect("EQUAL", "HOCUS282", "Expected '=' after the use identity.")
        module_name = self._expect_authored_ident("HOCUS283", "Expected an imported module name.")
        self._expect("LPAREN", "HOCUS284", "Expected '(' before named arguments.")
        arguments: list[NamedArgument] = []
        if self._match("RPAREN") is None:
            while True:
                if len(arguments) >= self._max_interface_items:
                    self._error(
                        "HOCUS271",
                        f"Module uses are limited to {self._max_interface_items} named arguments.",
                    )
                argument_name = self._expect_authored_ident("HOCUS285", "Expected a named argument.")
                self._expect("EQUAL", "HOCUS286", "Arguments must use name = value syntax.")
                value = self._parse_module_expr()
                arguments.append(NamedArgument(
                    str(argument_name.value),
                    value,
                    SourceSpan(argument_name.span.source_name, argument_name.span.start, value.span.end),
                    argument_name.span,
                ))
                if self._match("COMMA") is None:
                    self._expect("RPAREN", "HOCUS287", "Expected ')' after named arguments.")
                    break
                if self._match("RPAREN") is not None:
                    break
        end = self._statement_end()
        return UseDecl(
            str(symbol.value), str(seed.value), str(module_name.value), tuple(arguments),
            self._joined_span(start, end), symbol.span, seed.span, module_name.span,
        )

    def _parse_export(self) -> ExportStmt:
        start = self._advance()
        name = self._expect_authored_ident("HOCUS288", "Expected an export name.")
        self._expect("EQUAL", "HOCUS289", "Expected '=' after the export name.")
        value = self._parse_module_expr()
        end = self._statement_end()
        return ExportStmt(str(name.value), value, self._joined_span(start, end), name.span)

    def _parse_control(self, *, depth: int) -> IfDecl | ForDecl:
        if not self._uses_control_syntax():
            self._error("HOCUS315", "Compile-time controls require language 0.3 or 0.4.")
        if depth > self._max_control_depth:
            self._error(
                "HOCUS323",
                f"Control nesting exceeds the {self._max_control_depth}-level limit.",
            )
        if self._control_items >= self._max_control_items:
            self._error(
                "HOCUS323",
                f"Source exceeds the {self._max_control_items}-control-item limit.",
            )
        self._control_items += 1
        if self._is_ident("if"):
            return self._parse_if(depth=depth)
        if self._is_ident("for"):
            return self._parse_for(depth=depth)
        self._error("HOCUS315", "Expected an if or for compile-time control.")
        raise AssertionError("unreachable")

    def _parse_control_identity(self) -> tuple[Token, Token]:
        symbol = self._expect_authored_ident("HOCUS315", "Expected a control symbol.")
        self._expect("AT", "HOCUS316", "Every control requires an explicit @id.")
        annotation = self._expect("IDENT", "HOCUS316", "Expected id after '@'.")
        if annotation.value != "id":
            self._error("HOCUS316", "Only @id is supported on controls.", token=annotation)
        self._expect("LPAREN", "HOCUS316", "Expected '(' after @id.")
        seed = self._expect("STRING", "HOCUS316", "Expected a quoted durable control ID.")
        if not _ID_SEED.fullmatch(str(seed.value)):
            self._error(
                "HOCUS316",
                "Control IDs must match [A-Za-z0-9][A-Za-z0-9._:-]{0,127}.",
                token=seed,
            )
        self._expect("RPAREN", "HOCUS316", "Expected ')' after the durable control ID.")
        return symbol, seed

    def _parse_control_outputs(self) -> tuple[ControlOutputDecl, ...]:
        self._expect_ident("outputs", "HOCUS318", "Expected an outputs interface.")
        self._expect("LPAREN", "HOCUS318", "Expected '(' after outputs.")
        outputs: list[ControlOutputDecl] = []
        if self._match("RPAREN") is not None:
            self._error("HOCUS318", "Control outputs require at least one declaration.")
        while True:
            if len(outputs) >= self._max_interface_items:
                self._error(
                    "HOCUS318",
                    f"Control outputs are limited to {self._max_interface_items} declarations.",
                )
            name = self._expect_authored_ident("HOCUS318", "Expected a control output name.")
            self._expect("COLON", "HOCUS318", "Expected ':' after the control output name.")
            type_token = self._expect("IDENT", "HOCUS318", "Expected a control output type.")
            if type_token.value not in _TYPE_NAMES:
                self._error(
                    "HOCUS318",
                    "Control output type must be bool, int, float, string, or node_output.",
                    token=type_token,
                )
            outputs.append(
                ControlOutputDecl(
                    str(name.value),
                    str(type_token.value),
                    SourceSpan(name.span.source_name, name.span.start, type_token.span.end),
                    name.span,
                    type_token.span,
                )
            )
            if self._match("COMMA") is None:
                self._expect("RPAREN", "HOCUS318", "Expected ')' after control outputs.")
                return tuple(outputs)
            if self._match("RPAREN") is not None:
                return tuple(outputs)

    def _parse_control_body(self, *, depth: int) -> tuple[tuple[object, ...], Token]:
        self._expect("LBRACE", "HOCUS319", "Expected '{' before the control body.")
        statements: list[object] = []
        while self._current().kind not in {"RBRACE", "EOF"}:
            statement_index = self._index
            statement_kind = self._current().value if self._current().kind == "IDENT" else None
            try:
                if self._is_ident("node"):
                    self._claim_v03_node()
                    statements.append(self._parse_node())
                elif self._is_ident("use"):
                    self._claim_v03_instance()
                    statements.append(self._parse_use())
                elif self._is_ident("if") or self._is_ident("for"):
                    statements.append(self._parse_control(depth=depth + 1))
                elif self._is_ident("yield"):
                    statements.append(self._parse_yield())
                else:
                    self._error(
                        "HOCUS319",
                        "Control bodies support only node, use, if, for, and yield statements.",
                    )
            except HocusSourceError as exc:
                if self._is_resource_limit(exc.diagnostic):
                    raise
                self.diagnostics.append(exc.diagnostic)
                if statement_kind in {"if", "for"}:
                    self._index = statement_index
                    self._synchronize_control_declaration()
                elif exc.diagnostic.code in {"HOCUS222", "HOCUS223", "HOCUS224", "HOCUS225", "HOCUS300"}:
                    self._synchronize_node_declaration()
                else:
                    self._synchronize_statement(scope="control", preserve_current=True)
        end = self._expect("RBRACE", "HOCUS319", "Expected '}' to close the control body.")
        return tuple(statements), end

    def _claim_v03_node(self) -> None:
        if self._v03_node_count >= self._max_nodes:
            self._error(
                "HOCUS314",
                f"Language 0.3 source exceeds the {self._max_nodes}-node limit.",
            )
        self._v03_node_count += 1

    def _claim_v03_instance(self) -> None:
        if self._v03_instance_count >= self._max_instances:
            self._error(
                "HOCUS271",
                f"Language 0.3 source exceeds the {self._max_instances}-instance limit.",
            )
        self._v03_instance_count += 1

    def _parse_yield(self) -> YieldStmt:
        start = self._advance()
        name = self._expect_authored_ident("HOCUS323", "Expected an output name after yield.")
        self._expect("EQUAL", "HOCUS323", "Expected '=' after the yielded output name.")
        value = self._parse_module_expr()
        end = self._expect("SEMICOLON", "HOCUS323", "Expected ';' after yield.")
        return YieldStmt(str(name.value), value, self._joined_span(start, end), name.span)

    def _parse_if(self, *, depth: int) -> IfDecl:
        start = self._advance()
        symbol, seed = self._parse_control_identity()
        self._expect("LPAREN", "HOCUS317", "Expected '(' before the if condition.")
        condition = self._parse_module_expr()
        self._expect("RPAREN", "HOCUS317", "Expected ')' after the if condition.")
        outputs = self._parse_control_outputs()
        then_body, _then_end = self._parse_control_body(depth=depth)
        self._expect_ident("else", "HOCUS320", "Every if control requires an else branch.")
        else_body, end = self._parse_control_body(depth=depth)
        return IfDecl(
            str(symbol.value),
            str(seed.value),
            condition,
            outputs,
            then_body,  # type: ignore[arg-type]
            else_body,  # type: ignore[arg-type]
            self._joined_span(start, end),
            symbol.span,
            seed.span,
            condition.span,
        )

    def _parse_for(self, *, depth: int) -> ForDecl:
        start = self._advance()
        symbol, seed = self._parse_control_identity()
        self._expect("LPAREN", "HOCUS321", "Expected '(' before the for iterator.")
        iterator = self._expect_authored_ident("HOCUS321", "Expected a for iterator name.")
        self._expect_ident("in", "HOCUS321", "Expected 'in' after the for iterator.")
        self._expect_ident("range", "HOCUS321", "For controls require range(EXPR).")
        self._expect("LPAREN", "HOCUS321", "Expected '(' after range.")
        count = self._parse_module_expr()
        self._expect("RPAREN", "HOCUS321", "Expected ')' after the range expression.")
        self._expect("RPAREN", "HOCUS321", "Expected ')' after the for iterator.")
        self._expect_ident("carry", "HOCUS322", "Expected a carry interface.")
        self._expect("LPAREN", "HOCUS322", "Expected '(' after carry.")
        carries: list[CarryDecl] = []
        if self._match("RPAREN") is None:
            while True:
                if len(carries) >= self._max_interface_items:
                    self._error(
                        "HOCUS322",
                        f"For carries are limited to {self._max_interface_items} declarations.",
                    )
                name = self._expect_authored_ident("HOCUS322", "Expected a carry name.")
                self._expect("COLON", "HOCUS322", "Expected ':' after the carry name.")
                type_token = self._expect("IDENT", "HOCUS322", "Expected a carry type.")
                if type_token.value not in _TYPE_NAMES:
                    self._error(
                        "HOCUS322",
                        "Carry type must be bool, int, float, string, or node_output.",
                        token=type_token,
                    )
                self._expect("EQUAL", "HOCUS322", "Every carry requires an initial value.")
                initial = self._parse_module_expr()
                carries.append(
                    CarryDecl(
                        str(name.value),
                        str(type_token.value),
                        initial,
                        SourceSpan(name.span.source_name, name.span.start, initial.span.end),
                        name.span,
                        type_token.span,
                        initial.span,
                    )
                )
                if self._match("COMMA") is None:
                    self._expect("RPAREN", "HOCUS322", "Expected ')' after carries.")
                    break
                if self._match("RPAREN") is not None:
                    break
        if not carries:
            self._error("HOCUS322", "For controls require at least one carry declaration.")
        body, end = self._parse_control_body(depth=depth)
        return ForDecl(
            str(symbol.value),
            str(seed.value),
            str(iterator.value),
            count,
            tuple(carries),
            body,  # type: ignore[arg-type]
            self._joined_span(start, end),
            symbol.span,
            seed.span,
            iterator.span,
            count.span,
        )

    def _parse_graph(self) -> GraphDecl:
        start = self._expect_ident("graph", "HOCUS204", "Expected a graph declaration.")
        name = self._expect("IDENT", "HOCUS205", "Expected a graph name.")
        if self._uses_module_syntax():
            self._reject_reserved_symbol(name)
        self._expect("LBRACE", "HOCUS206", "Expected '{' after the graph name.")
        statements = []
        seen_singletons: set[str] = set()
        counts = {"node": 0, "instance": 0}

        while self._current().kind not in {"RBRACE", "EOF"}:
            statement_index = self._index
            statement_kind = self._current().value if self._current().kind == "IDENT" else None
            try:
                statements.append(self._parse_graph_statement(seen_singletons, counts))
            except HocusSourceError as exc:
                if self._graph_error_is_fatal(exc):
                    raise
                self.diagnostics.append(exc.diagnostic)
                self._recover_graph_statement(exc, statement_index, statement_kind)

        end = self._expect("RBRACE", "HOCUS218", "Expected '}' to close the graph.")
        return GraphDecl(str(name.value), tuple(statements), self._joined_span(start, end), name.span)

    def _parse_graph_statement(
        self, seen_singletons: set[str], counts: dict[str, int],
    ):
        directive = self._parse_graph_directive(seen_singletons)
        if directive is not None:
            return directive
        return self._parse_graph_body_statement(seen_singletons, counts)

    def _parse_graph_directive(self, seen_singletons: set[str]):
        parsers = (
            ("target", self._parse_target), ("category", self._parse_category),
            ("mode", self._parse_mode), ("expect", self._parse_revision),
            ("ownership", self._parse_ownership),
        )
        for keyword, parser in parsers:
            if self._is_ident(keyword):
                self._claim_singleton(keyword, seen_singletons)
                return parser()
        if self._is_ident("existing") or self._is_ident("adopt"):
            return self._parse_external()
        return None

    def _parse_graph_body_statement(
        self, seen_singletons: set[str], counts: dict[str, int],
    ):
        if self._is_ident("node"):
            return self._parse_counted_graph_node(counts)
        if self._uses_module_syntax() and self._is_ident("use"):
            return self._parse_counted_graph_use(counts)
        if self._uses_control_syntax() and (
            self._is_ident("if") or self._is_ident("for")
        ):
            return self._parse_control(depth=1)
        if (
            self._language_version == "0.4"
            and self._current().value in EDITOR_ENTITY_KEYWORDS
        ):
            return self._parse_editor_entity()
        if self._is_ident("display") or self._is_ident("render") or self._is_ident("output"):
            key = str(self._current().value)
            self._claim_singleton(key, seen_singletons)
            return self._parse_flag()
        if self._is_ident("layout"):
            self._claim_singleton("layout", seen_singletons)
            return self._parse_layout()
        message = (
            "Unknown graph statement. HocusScript 0.1 does not execute TypeScript or JavaScript constructs."
            if self._language_version == "0.1"
            else (
                f"Unknown graph statement. HocusScript {self._language_version} "
                "does not execute host-language constructs."
            )
        )
        self._error("HOCUS217", message)

    def _parse_counted_graph_node(self, counts: dict[str, int]) -> NodeDecl:
        if self._uses_control_syntax():
            self._claim_v03_node()
        elif counts["node"] >= self._max_nodes:
            self._error("HOCUS314", f"Graph exceeds the {self._max_nodes}-node limit.")
        statement = self._parse_node()
        counts["node"] += 1
        return statement

    def _parse_counted_graph_use(self, counts: dict[str, int]) -> UseDecl:
        if self._uses_control_syntax():
            self._claim_v03_instance()
        elif counts["instance"] >= self._max_instances:
            self._error("HOCUS271", f"Graph exceeds the {self._max_instances}-instance limit.")
        statement = self._parse_use()
        counts["instance"] += 1
        return statement

    def _graph_error_is_fatal(self, exc: HocusSourceError) -> bool:
        return (
            exc.diagnostic.code in {"HOCUS226", "HOCUS314", "HOCUS246"}
            or self._is_resource_limit(exc.diagnostic)
            or (
                self._language_version == "0.2"
                and exc.diagnostic.code == "HOCUS217"
                and (self._is_ident("if") or self._is_ident("for"))
            )
        )

    def _recover_graph_statement(
        self, exc: HocusSourceError, statement_index: int, statement_kind: object,
    ) -> None:
        if self._uses_control_syntax() and statement_kind in {"if", "for"}:
            self._index = statement_index
            self._synchronize_control_declaration()
        elif exc.diagnostic.code in {"HOCUS222", "HOCUS223", "HOCUS224", "HOCUS225", "HOCUS300"}:
            self._synchronize_node_declaration()
        else:
            self._synchronize_statement(
                scope="graph", preserve_current=exc.diagnostic.code == "HOCUS245",
            )

    def _parse_target(self) -> TargetStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("STRING", "HOCUS207", "Expected a quoted target path.")
        end = self._statement_end()
        return TargetStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_category(self) -> CategoryStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("IDENT", "HOCUS208", "Expected a category name.")
        end = self._statement_end()
        return CategoryStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_mode(self) -> ModeStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("IDENT", "HOCUS209", "Expected merge or reconcile.")
        end = self._statement_end()
        return ModeStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_revision(self) -> RevisionStmt:
        start = self._advance()
        had_revision = False
        if self._is_ident("revision"):
            self._advance()
            had_revision = True
        had_equal = self._match("EQUAL") is not None
        value = self._expect("NUMBER", "HOCUS210", "Expected an integer document revision.")
        if not isinstance(value.value, int):
            self._error("HOCUS211", "Expected revision must be an integer.", token=value)
        end = self._statement_end()
        return RevisionStmt(value.value, had_revision, had_equal, self._joined_span(start, end), value.span)

    def _parse_ownership(self) -> OwnershipStmt:
        start = self._advance()
        had_equal = self._match("EQUAL") is not None
        value = self._expect("STRING", "HOCUS212", "Expected a quoted ownership namespace.")
        end = self._statement_end()
        return OwnershipStmt(str(value.value), had_equal, self._joined_span(start, end), value.span)

    def _parse_external(self) -> ExternalDecl:
        start = self._advance()
        adopted = start.value == "adopt"
        symbol = self._expect("IDENT", "HOCUS219", "Expected a symbol for the external node.")
        if self._uses_module_syntax():
            self._reject_reserved_symbol(symbol)
        self._expect("EQUAL", "HOCUS220", "Expected '=' in an external node declaration.")
        path = self._expect("STRING", "HOCUS221", "Expected a quoted Houdini path.")
        end = self._statement_end()
        return ExternalDecl(
            str(symbol.value),
            str(path.value),
            adopted,
            self._joined_span(start, end),
            symbol.span,
            path.span,
        )

    def _parse_node(self) -> NodeDecl:
        start = self._advance()
        symbol = self._expect("IDENT", "HOCUS222", "Expected a node symbol.")
        if self._uses_module_syntax():
            self._reject_reserved_symbol(symbol)
        explicit_id: str | None = None
        explicit_id_span: SourceSpan | None = None
        if self._match("AT") is not None:
            annotation = self._expect("IDENT", "HOCUS247", "Expected 'id' after '@'.")
            if annotation.value != "id":
                self._error("HOCUS248", "Only the @id annotation is supported on node declarations.", token=annotation)
            self._expect("LPAREN", "HOCUS249", "Expected '(' after @id.")
            value = self._expect("STRING", "HOCUS250", "Expected a quoted durable node ID.")
            explicit_id = str(value.value)
            explicit_id_span = value.span
            if self._uses_module_syntax() and not _ID_SEED.fullmatch(explicit_id):
                self._error(
                    "HOCUS281",
                    "Node IDs must match [A-Za-z0-9][A-Za-z0-9._:-]{0,127}.",
                    token=value,
                )
            self._expect("RPAREN", "HOCUS251", "Expected ')' after the durable node ID.")
        self._expect("COLON", "HOCUS223", "Expected ':' after the node symbol.")
        type_token = self._current()
        if type_token.kind not in {"IDENT", "STRING"}:
            self._error("HOCUS224", "Expected a node type name.")
        self._advance()
        self._expect("LBRACE", "HOCUS225", "Expected '{' before node assignments.")
        statements = []
        while self._current().kind not in {"RBRACE", "EOF"}:
            try:
                runtime = self._parse_runtime_node_statement()
                if runtime is not None:
                    statements.append(runtime)
                elif self._is_ident("input"):
                    statements.append(
                        self._parse_module_input() if self._uses_module_syntax() else self._parse_input()
                    )
                else:
                    statements.append(
                        self._parse_module_parm() if self._uses_module_syntax() else self._parse_parm()
                    )
            except HocusSourceError as exc:
                if exc.diagnostic.code == "HOCUS246":
                    raise
                self.diagnostics.append(exc.diagnostic)
                self._synchronize_statement(
                    scope="node",
                    preserve_current=exc.diagnostic.code == "HOCUS245",
                )
        end = self._expect("RBRACE", "HOCUS226", "Expected '}' to close the node.")
        return NodeDecl(
            str(symbol.value),
            explicit_id,
            str(type_token.value),
            type_token.kind == "STRING",
            tuple(statements),
            self._joined_span(start, end),
            symbol.span,
            explicit_id_span,
            type_token.span,
        )

    def _parse_module_input(self) -> InputStmt:
        start = self._advance()
        self._expect("LBRACKET", "HOCUS227", "Expected '[' after input.")
        index, name, selector_span, _ = self._parse_port_selector(
            expected_code="HOCUS228", integer_code="HOCUS229",
            expected_message="Expected an integer input index.",
            integer_message="Input index must be an integer.",
        )
        self._expect("EQUAL", "HOCUS231", "Expected '=' in an input assignment.")
        source = self._parse_module_expr()
        if not isinstance(source, (ParamRefExpr, SymbolRefExpr)):
            self._error("HOCUS290", "Module inputs require a node_output reference.")
        end = self._statement_end()
        return InputStmt(
            index, source, self._joined_span(start, end),
            selector_span if index is not None else None,
            name, selector_span if name is not None else None,
        )

    def _parse_module_parm(self) -> ParmStmt:
        name = self._expect_authored_ident("HOCUS239", "Expected a parameter name.")
        self._expect("EQUAL", "HOCUS240", "Expected '=' after the parameter name.")
        token = self._current()
        rich_value = (
            self._language_version == "0.4"
            and (token.kind == "LBRACKET" or (
                token.kind == "IDENT" and token.value in {"vex", "python", "hscript"}
                and self._tokens[self._index + 1].kind == "CODE"
            ) or (
                token.kind == "IDENT" and token.value in TAGGED_VALUE_NAMES
                and self._tokens[self._index + 1].kind == "LPAREN"
            ))
        )
        value = self._parse_value() if rich_value else self._parse_module_expr()
        end = self._statement_end()
        return ParmStmt(str(name.value), value, self._joined_span(name, end), name.span)

    def _parse_input(self) -> InputStmt:
        start = self._advance()
        self._expect("LBRACKET", "HOCUS227", "Expected '[' after input.")
        index, name, selector_span, _ = self._parse_port_selector(
            expected_code="HOCUS228", integer_code="HOCUS229",
            expected_message="Expected an integer input index.",
            integer_message="Input index must be an integer.",
        )
        self._expect("EQUAL", "HOCUS231", "Expected '=' in an input assignment.")
        reference = self._parse_reference()
        end = self._statement_end()
        return InputStmt(
            index, reference, self._joined_span(start, end),
            selector_span if index is not None else None,
            name, selector_span if name is not None else None,
        )

    def _parse_reference(self) -> ReferenceExpr:
        symbol = self._expect("IDENT", "HOCUS232", "Expected a node symbol.")
        output_index: int | None = 0
        output_name: str | None = None
        output_span: SourceSpan | None = symbol.span
        end = symbol
        explicit_output = False
        port_keyword: str | None = None
        if self._match("DOT") is not None:
            explicit_output = True
            port = self._expect("IDENT", "HOCUS233", "Expected output or out after '.'.")
            if port.value not in {"output", "out"}:
                self._error("HOCUS234", "Only .output[index] and .out[index] are supported in 0.1.", token=port)
            port_keyword = str(port.value)
            self._expect("LBRACKET", "HOCUS235", "Expected '[' before the output index.")
            output_index, output_name, output_span, end = self._parse_port_selector(
                expected_code="HOCUS236", integer_code="HOCUS237",
                expected_message="Expected an integer output index.",
                integer_message="Output index must be an integer.",
            )
        return ReferenceExpr(
            str(symbol.value),
            output_index,
            explicit_output,
            port_keyword,
            self._joined_span(symbol, end),
            symbol.span,
            output_span if output_index is not None else None,
            output_name,
            output_span if output_name is not None else None,
        )

    def _parse_parm(self) -> ParmStmt:
        name = self._expect("IDENT", "HOCUS239", "Expected a parameter name.")
        self._expect("EQUAL", "HOCUS240", "Expected '=' after the parameter name.")
        value = self._parse_value()
        end = self._statement_end()
        return ParmStmt(str(name.value), value, self._joined_span(name, end), name.span)

    def _parse_module_literal(self) -> LiteralExpr:
        token = self._current()
        if token.kind in {"STRING", "NUMBER"}:
            self._advance()
            return LiteralExpr(token.value, token.span)
        if token.kind == "IDENT" and token.value in {"true", "false"}:
            self._advance()
            return LiteralExpr(token.value == "true", token.span)
        self._error(
            "HOCUS291",
            f"Language {self._language_version} defaults must be bool, int, float, or string literals.",
        )
        raise AssertionError("unreachable")

    def _parse_module_expr(self) -> ModuleExpr:
        token = self._current()
        if token.kind in {"STRING", "NUMBER"} or (
            token.kind == "IDENT" and token.value in {"true", "false"}
        ):
            return self._parse_module_literal()
        root = self._expect_authored_ident(
            "HOCUS292",
            "Expected a literal, param reference, local node output, or instance export.",
        )
        self._expect("DOT", "HOCUS293", "References require an explicit member after '.'.")
        member = self._expect_authored_ident("HOCUS294", "Expected a reference member name.")
        if root.value == "param":
            if self._current().kind == "LBRACKET":
                self._error("HOCUS295", "Parameter references cannot use output indexes.")
            return ParamRefExpr(
                str(member.value),
                SourceSpan(root.span.source_name, root.span.start, member.span.end),
                member.span,
            )
        output_index: int | None = None
        output_name: str | None = None
        output_span: SourceSpan | None = None
        end = member
        if member.value == "output":
            self._expect("LBRACKET", "HOCUS296", "Local node outputs require an explicit output index.")
            output_index, output_name, output_span, end = self._parse_port_selector(
                expected_code="HOCUS297", integer_code="HOCUS298",
                expected_message="Expected an integer output index.",
                integer_message="Output indexes must be integers.",
            )
        elif self._current().kind == "LBRACKET":
            self._error("HOCUS296", "Only .output[index] references may use an output index.")
        return SymbolRefExpr(
            str(root.value),
            str(member.value),
            output_index,
            self._joined_span(root, end),
            root.span,
            member.span,
            output_span if output_index is not None else None,
            output_name,
            output_span if output_name is not None else None,
        )

    def _parse_flag(self) -> FlagStmt:
        start = self._advance()
        key = str(start.value)
        self._expect("EQUAL", "HOCUS213", f"Expected '=' after {key}.")
        symbol = self._expect("IDENT", "HOCUS214", f"Expected a symbol after {key} =.")
        if self._uses_module_syntax():
            self._reject_reserved_symbol(symbol)
        end = self._statement_end()
        return FlagStmt(key, str(symbol.value), self._joined_span(start, end), symbol.span)

    def _parse_layout(self) -> LayoutStmt:
        start = self._advance()
        self._expect("EQUAL", "HOCUS215", "Expected '=' after layout.")
        value = self._expect("IDENT", "HOCUS216", "Expected auto layout mode.")
        end = self._statement_end()
        return LayoutStmt(str(value.value), self._joined_span(start, end), value.span)

    def _claim_singleton(self, name: str, seen: set[str]) -> None:
        if name in seen:
            self._error("HOCUS244", f"Duplicate graph statement: {name}.")
        seen.add(name)

    def _statement_end(self) -> Token:
        return self._expect("SEMICOLON", "HOCUS245", "Expected ';' after the statement.")

    def _synchronize_statement(self, *, scope: str, preserve_current: bool) -> None:
        if preserve_current and self._is_statement_start(scope):
            return
        start_index = self._index
        while self._current().kind not in {"SEMICOLON", "RBRACE", "EOF"}:
            self._advance()
        if self._current().kind == "SEMICOLON":
            self._advance()
        if self._index == start_index and self._current().kind not in {"RBRACE", "EOF"}:
            self._advance()

    def _synchronize_node_declaration(self) -> None:
        depth = 0
        saw_body = False
        while self._current().kind != "EOF":
            token = self._current()
            if token.kind == "LBRACE":
                saw_body = True
                depth += 1
                self._advance()
                continue
            if token.kind == "RBRACE":
                if not saw_body:
                    return
                depth -= 1
                self._advance()
                if depth == 0:
                    return
                continue
            if not saw_body and self._is_statement_start("graph"):
                return
            if not saw_body and token.kind == "SEMICOLON":
                self._advance()
                return
            self._advance()

    def _synchronize_control_declaration(self) -> None:
        """Skip one malformed control from its keyword through its bounded bodies."""

        kind = str(self._current().value) if self._current().kind == "IDENT" else ""
        self._advance()
        body_count = 0
        while self._current().kind != "EOF":
            if self._current().kind == "RBRACE":
                return
            if self._current().kind == "SEMICOLON":
                self._advance()
                return
            if self._current().kind != "LBRACE":
                if body_count == 0 and self._is_statement_start("control"):
                    return
                self._advance()
                continue
            self._consume_balanced_block()
            body_count += 1
            if kind != "if" or body_count >= 2:
                return
            if self._is_ident("else"):
                self._advance()
                if self._current().kind != "LBRACE":
                    return
                continue
            return

    def _consume_balanced_block(self) -> None:
        depth = 0
        while self._current().kind != "EOF":
            if self._current().kind == "LBRACE":
                depth += 1
            elif self._current().kind == "RBRACE":
                depth -= 1
            self._advance()
            if depth == 0:
                return

    @staticmethod
    def _is_resource_limit(diagnostic: Diagnostic) -> bool:
        if diagnostic.code in {"HOCUS226", "HOCUS246", "HOCUS314"}:
            return True
        return diagnostic.code in {"HOCUS271", "HOCUS318", "HOCUS322", "HOCUS323"} and any(
            marker in diagnostic.message for marker in ("limit", "limited to", "exceeds")
        )

    def _is_statement_start(self, scope: str) -> bool:
        token = self._current()
        if token.kind != "IDENT":
            return False
        if scope == "node":
            return True
        if scope == "control":
            return token.value in {"node", "use", "if", "for", "yield"}
        if scope == "module":
            return token.value in {"node", "use", "export"} or (
                self._uses_control_syntax() and token.value in {"if", "for"}
            )
        starts = {
            "target", "category", "mode", "expect", "ownership", "existing", "adopt", "node",
            "display", "render", "output", "layout",
        }
        starts.update(EDITOR_ENTITY_KEYWORDS)
        return token.value in starts or (
            self._uses_module_syntax() and token.value == "use"
        ) or (
            self._uses_control_syntax() and token.value in {"if", "for"}
        )

    def _uses_module_syntax(self) -> bool:
        return self._language_version in {"0.2", "0.3", "0.4"}

    def _uses_control_syntax(self) -> bool:
        return self._language_version in {"0.3", "0.4"}

    def _expect_authored_ident(self, code: str, message: str) -> Token:
        token = self._expect("IDENT", code, message)
        self._reject_reserved_symbol(token)
        return token

    def _reject_reserved_symbol(self, token: Token) -> None:
        if str(token.value).startswith(_RESERVED_SYMBOL_PREFIX):
            self._error(
                "HOCUS300",
                f"Authored language {self._language_version} names cannot use the reserved __hocus_ prefix.",
                token=token,
            )

    def _joined_span(self, start: Token, end: Token) -> SourceSpan:
        return SourceSpan(start.span.source_name, start.span.start, end.span.end)

    def _current(self) -> Token:
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._current()
        if token.kind != "EOF":
            self._index += 1
        return token

    def _match(self, kind: str) -> Token | None:
        if self._current().kind != kind:
            return None
        return self._advance()

    def _is_ident(self, value: str) -> bool:
        token = self._current()
        return token.kind == "IDENT" and token.value == value

    def _expect_ident(self, value: str, code: str, message: str) -> Token:
        if not self._is_ident(value):
            self._error(code, message)
        return self._advance()

    def _expect(self, kind: str, code: str, message: str) -> Token:
        token = self._current()
        if token.kind != kind:
            self._error(code, message, token=token)
        return self._advance()

    def _error(self, code: str, message: str, *, token: Token | None = None) -> None:
        actual = token or self._current()
        raise HocusSourceError(Diagnostic("error", code, "parse", message, actual.span))


def parse_syntax(source: str, source_name: str = "<memory>") -> SyntaxSource:
    from .parser_api import parse_syntax as parse
    return parse(source, source_name)
