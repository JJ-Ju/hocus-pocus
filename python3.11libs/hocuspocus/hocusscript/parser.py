"""Version-dispatched recursive-descent parser for HocusScript source syntax."""

from __future__ import annotations

from .diagnostics import Diagnostic, HocusSourceError, SourceSpan
import re

from .lexer import Lexer, Token
from .module_paths import is_literal_import_specifier
from .syntax import (
    ArrayExpr,
    CategoryStmt,
    CodeExpr,
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
    ValueExpr,
    VersionDecl,
    UseDecl,
    ExportStmt,
)


_TYPE_NAMES = {"bool", "int", "float", "string", "node_output"}
_ID_SEED = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_RESERVED_SYMBOL_PREFIX = "__hocus_"


class Parser:
    def __init__(
        self,
        tokens: list[Token],
        *,
        max_value_depth: int = 128,
        max_nodes: int = 10_000,
        max_imports: int = 4_096,
        max_instances: int = 4_096,
        max_interface_items: int = 256,
    ):
        self._tokens = tokens
        self._index = 0
        self._max_value_depth = max_value_depth
        self._max_nodes = max_nodes
        self._max_imports = max_imports
        self._max_instances = max_instances
        self._max_interface_items = max_interface_items
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

        if version is not None and version.value == "0.2":
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
            self._error("HOCUS260", "Language 0.2 requires exactly one graph or module root declaration.")
        self._expect("EOF", "HOCUS260", "Language 0.2 source supports exactly one root declaration.")
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
        node_count = 0
        instance_count = 0
        while self._current().kind not in {"RBRACE", "EOF"}:
            try:
                if self._is_ident("node"):
                    if node_count >= self._max_nodes:
                        self._error("HOCUS314", f"Module exceeds the {self._max_nodes}-node limit.")
                    statements.append(self._parse_node())
                    node_count += 1
                elif self._is_ident("use"):
                    if instance_count >= self._max_instances:
                        self._error("HOCUS271", f"Module exceeds the {self._max_instances}-instance limit.")
                    statements.append(self._parse_use())
                    instance_count += 1
                elif self._is_ident("export"):
                    statements.append(self._parse_export())
                else:
                    self._error(
                        "HOCUS269",
                        "Modules support only node, use, and export statements.",
                    )
            except HocusSourceError as exc:
                if exc.diagnostic.code in {"HOCUS226", "HOCUS314", "HOCUS246"}:
                    raise
                self.diagnostics.append(exc.diagnostic)
                if exc.diagnostic.code in {"HOCUS222", "HOCUS223", "HOCUS224", "HOCUS225", "HOCUS300"}:
                    self._synchronize_node_declaration()
                else:
                    self._synchronize_statement(
                        scope="module",
                        preserve_current=exc.diagnostic.code == "HOCUS245",
                    )
        end = self._expect("RBRACE", "HOCUS270", "Expected '}' to close the module.")
        return ModuleDecl(
            str(name.value),
            tuple(parameters),
            tuple(exports),
            tuple(statements),
            self._joined_span(start, end),
            name.span,
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
            type_token = self._expect("IDENT", "HOCUS274", "Expected a HocusScript 0.2 type name.")
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
        self._expect("AT", "HOCUS279", "Every language 0.2 use declaration requires @id.")
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

    def _parse_graph(self) -> GraphDecl:
        start = self._expect_ident("graph", "HOCUS204", "Expected a graph declaration.")
        name = self._expect("IDENT", "HOCUS205", "Expected a graph name.")
        if self._language_version == "0.2":
            self._reject_reserved_symbol(name)
        self._expect("LBRACE", "HOCUS206", "Expected '{' after the graph name.")
        statements = []
        seen_singletons: set[str] = set()
        node_count = 0
        instance_count = 0

        while self._current().kind not in {"RBRACE", "EOF"}:
            try:
                if self._is_ident("target"):
                    self._claim_singleton("target", seen_singletons)
                    statements.append(self._parse_target())
                elif self._is_ident("category"):
                    self._claim_singleton("category", seen_singletons)
                    statements.append(self._parse_category())
                elif self._is_ident("mode"):
                    self._claim_singleton("mode", seen_singletons)
                    statements.append(self._parse_mode())
                elif self._is_ident("expect"):
                    self._claim_singleton("expect", seen_singletons)
                    statements.append(self._parse_revision())
                elif self._is_ident("ownership"):
                    self._claim_singleton("ownership", seen_singletons)
                    statements.append(self._parse_ownership())
                elif self._is_ident("existing") or self._is_ident("adopt"):
                    statements.append(self._parse_external())
                elif self._is_ident("node"):
                    if node_count >= self._max_nodes:
                        self._error("HOCUS314", f"Graph exceeds the {self._max_nodes}-node limit.")
                    statements.append(self._parse_node())
                    node_count += 1
                elif self._language_version == "0.2" and self._is_ident("use"):
                    if instance_count >= self._max_instances:
                        self._error("HOCUS271", f"Graph exceeds the {self._max_instances}-instance limit.")
                    statements.append(self._parse_use())
                    instance_count += 1
                elif self._is_ident("display") or self._is_ident("render") or self._is_ident("output"):
                    key = str(self._current().value)
                    self._claim_singleton(key, seen_singletons)
                    statements.append(self._parse_flag())
                elif self._is_ident("layout"):
                    self._claim_singleton("layout", seen_singletons)
                    statements.append(self._parse_layout())
                else:
                    message = (
                        "Unknown graph statement. HocusScript 0.1 does not execute TypeScript or JavaScript constructs."
                        if self._language_version == "0.1"
                        else "Unknown graph statement. HocusScript 0.2 does not execute host-language constructs."
                    )
                    self._error(
                        "HOCUS217",
                        message,
                    )
            except HocusSourceError as exc:
                if exc.diagnostic.code in {"HOCUS226", "HOCUS314", "HOCUS246"}:
                    raise
                self.diagnostics.append(exc.diagnostic)
                if exc.diagnostic.code in {"HOCUS222", "HOCUS223", "HOCUS224", "HOCUS225", "HOCUS300"}:
                    self._synchronize_node_declaration()
                else:
                    self._synchronize_statement(
                        scope="graph",
                        preserve_current=exc.diagnostic.code == "HOCUS245",
                    )

        end = self._expect("RBRACE", "HOCUS218", "Expected '}' to close the graph.")
        return GraphDecl(str(name.value), tuple(statements), self._joined_span(start, end), name.span)

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
        if self._language_version == "0.2":
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
        if self._language_version == "0.2":
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
            if self._language_version == "0.2" and not _ID_SEED.fullmatch(explicit_id):
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
                if self._is_ident("input"):
                    statements.append(
                        self._parse_module_input() if self._language_version == "0.2" else self._parse_input()
                    )
                else:
                    statements.append(
                        self._parse_module_parm() if self._language_version == "0.2" else self._parse_parm()
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
        index = self._expect("NUMBER", "HOCUS228", "Expected an integer input index.")
        if not isinstance(index.value, int):
            self._error("HOCUS229", "Input index must be an integer.", token=index)
        self._expect("RBRACKET", "HOCUS230", "Expected ']' after the input index.")
        self._expect("EQUAL", "HOCUS231", "Expected '=' in an input assignment.")
        source = self._parse_module_expr()
        if not isinstance(source, (ParamRefExpr, SymbolRefExpr)):
            self._error("HOCUS290", "Module inputs require a node_output reference.")
        end = self._statement_end()
        return InputStmt(index.value, source, self._joined_span(start, end), index.span)

    def _parse_module_parm(self) -> ParmStmt:
        name = self._expect_authored_ident("HOCUS239", "Expected a parameter name.")
        self._expect("EQUAL", "HOCUS240", "Expected '=' after the parameter name.")
        value = self._parse_module_expr()
        end = self._statement_end()
        return ParmStmt(str(name.value), value, self._joined_span(name, end), name.span)

    def _parse_input(self) -> InputStmt:
        start = self._advance()
        self._expect("LBRACKET", "HOCUS227", "Expected '[' after input.")
        index = self._expect("NUMBER", "HOCUS228", "Expected an integer input index.")
        if not isinstance(index.value, int):
            self._error("HOCUS229", "Input index must be an integer.", token=index)
        self._expect("RBRACKET", "HOCUS230", "Expected ']' after the input index.")
        self._expect("EQUAL", "HOCUS231", "Expected '=' in an input assignment.")
        reference = self._parse_reference()
        end = self._statement_end()
        return InputStmt(index.value, reference, self._joined_span(start, end), index.span)

    def _parse_reference(self) -> ReferenceExpr:
        symbol = self._expect("IDENT", "HOCUS232", "Expected a node symbol.")
        output_index = 0
        output_span = symbol.span
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
            output = self._expect("NUMBER", "HOCUS236", "Expected an integer output index.")
            if not isinstance(output.value, int):
                self._error("HOCUS237", "Output index must be an integer.", token=output)
            output_index = output.value
            output_span = output.span
            end = self._expect("RBRACKET", "HOCUS238", "Expected ']' after the output index.")
        return ReferenceExpr(
            str(symbol.value),
            output_index,
            explicit_output,
            port_keyword,
            self._joined_span(symbol, end),
            symbol.span,
            output_span,
        )

    def _parse_parm(self) -> ParmStmt:
        name = self._expect("IDENT", "HOCUS239", "Expected a parameter name.")
        self._expect("EQUAL", "HOCUS240", "Expected '=' after the parameter name.")
        value = self._parse_value()
        end = self._statement_end()
        return ParmStmt(str(name.value), value, self._joined_span(name, end), name.span)

    def _parse_value(self, depth: int = 0) -> ValueExpr:
        if depth > self._max_value_depth:
            self._error("HOCUS246", f"Value nesting exceeds the {self._max_value_depth}-level limit.")
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
            code = self._expect("CODE", "HOCUS241", "Expected a raw code template after the language tag.")
            if code.body_span is None or code.code_offset_map is None:
                raise RuntimeError("CODE token is missing body source-map metadata")
            return CodeExpr(
                str(language.value),
                str(code.value),
                SourceSpan(language.span.source_name, language.span.start, code.span.end),
                code.body_span,
                code.code_offset_map,
            )
        if token.kind == "LBRACKET":
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
            end = self._expect("RBRACKET", "HOCUS242", "Expected ']' to close the array.")
            return ArrayExpr(tuple(values), trailing_comma, self._joined_span(start, end))
        self._error("HOCUS243", "Expected a scalar, array, or tagged code value; executable expressions are not supported.")
        raise AssertionError("unreachable")

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
            "Language 0.2 defaults must be bool, int, float, or string literals.",
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
        output_span: SourceSpan | None = None
        end = member
        if member.value == "output":
            self._expect("LBRACKET", "HOCUS296", "Local node outputs require an explicit output index.")
            output = self._expect("NUMBER", "HOCUS297", "Expected an integer output index.")
            if not isinstance(output.value, int):
                self._error("HOCUS298", "Output indexes must be integers.", token=output)
            output_index = output.value
            output_span = output.span
            end = self._expect("RBRACKET", "HOCUS299", "Expected ']' after the output index.")
        elif self._current().kind == "LBRACKET":
            self._error("HOCUS296", "Only .output[index] references may use an output index.")
        return SymbolRefExpr(
            str(root.value),
            str(member.value),
            output_index,
            self._joined_span(root, end),
            root.span,
            member.span,
            output_span,
        )

    def _parse_flag(self) -> FlagStmt:
        start = self._advance()
        key = str(start.value)
        self._expect("EQUAL", "HOCUS213", f"Expected '=' after {key}.")
        symbol = self._expect("IDENT", "HOCUS214", f"Expected a symbol after {key} =.")
        if self._language_version == "0.2":
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

    def _is_statement_start(self, scope: str) -> bool:
        token = self._current()
        if token.kind != "IDENT":
            return False
        if scope == "node":
            return True
        if scope == "module":
            return token.value in {"node", "use", "export"}
        starts = {
            "target", "category", "mode", "expect", "ownership", "existing", "adopt", "node",
            "display", "render", "output", "layout",
        }
        return token.value in starts or (
            self._language_version == "0.2" and token.value == "use"
        )

    def _expect_authored_ident(self, code: str, message: str) -> Token:
        token = self._expect("IDENT", code, message)
        self._reject_reserved_symbol(token)
        return token

    def _reject_reserved_symbol(self, token: Token) -> None:
        if str(token.value).startswith(_RESERVED_SYMBOL_PREFIX):
            self._error(
                "HOCUS300",
                "Authored language 0.2 names cannot use the reserved __hocus_ prefix.",
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
    """Parse one bounded source string into the version-dispatched syntax AST."""
    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not isinstance(source_name, str) or not source_name.strip():
        raise TypeError("source_name must be a non-empty string")
    parser = Parser(Lexer(source, source_name).tokenize())
    syntax = parser.parse()
    if parser.diagnostics:
        raise HocusSourceError(parser.diagnostics[0])
    return syntax
