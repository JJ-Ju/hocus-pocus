"""Offline HocusScript parsing, validation, and formatting."""

from .bundle import BUNDLE_VERSION, BundleValidationError, CompiledBundle, decode_compiled_bundle
from .catalog import (
    CATALOG_SCHEMA_URI,
    CATALOG_VERSION,
    CatalogProvider,
    CatalogSnapshot,
    CatalogValidationError,
    FakeCatalogProvider,
    SnapshotCatalogProvider,
    decode_catalog_snapshot,
)
from .compiler import SUPPORTED_LANGUAGE_VERSIONS, compile_source, validate_graph
from .diagnostics import Diagnostic, SourcePosition, SourceSpan
from .document_lowering import (
    DOCUMENT_SCHEMA_URI,
    PREVIEW_VERSION,
    DocumentLoweringError,
    DocumentPreview,
    lower_bundle_to_document,
)
from .editor import (
    CompletionItem,
    CompletionResult,
    EditorCheckResult,
    EditorFormatResult,
    check_source,
    complete_source,
    format_source,
)
from .formatter import format_graph
from .exporter import ExportDiagnostic, NetworkDocumentExport, export_network_document
from .model import COMPILER_VERSION, GRAPH_SPEC_VERSION, CompileResult, GraphSpec, graph_spec_from_dict
from .project import ProjectContext, ProjectError, compile_path
from .semantic import (
    CatalogConstraint,
    ConnectionSelection,
    DeferredCheck,
    ExternalNodeBinding,
    OperatorSelection,
    ParameterSelection,
    SemanticResult,
    resolve_graph,
)

__all__ = [
    "BUNDLE_VERSION",
    "BundleValidationError",
    "CATALOG_SCHEMA_URI",
    "CATALOG_VERSION",
    "CatalogProvider",
    "CatalogSnapshot",
    "CatalogValidationError",
    "CompileResult",
    "CompletionItem",
    "CompletionResult",
    "COMPILER_VERSION",
    "CompiledBundle",
    "CatalogConstraint",
    "ConnectionSelection",
    "DeferredCheck",
    "Diagnostic",
    "DOCUMENT_SCHEMA_URI",
    "DocumentLoweringError",
    "DocumentPreview",
    "EditorCheckResult",
    "EditorFormatResult",
    "ExportDiagnostic",
    "FakeCatalogProvider",
    "GraphSpec",
    "GRAPH_SPEC_VERSION",
    "ProjectContext",
    "ProjectError",
    "PREVIEW_VERSION",
    "NetworkDocumentExport",
    "SUPPORTED_LANGUAGE_VERSIONS",
    "SourcePosition",
    "SourceSpan",
    "ExternalNodeBinding",
    "OperatorSelection",
    "ParameterSelection",
    "SemanticResult",
    "SnapshotCatalogProvider",
    "compile_path",
    "compile_source",
    "check_source",
    "complete_source",
    "decode_compiled_bundle",
    "decode_catalog_snapshot",
    "format_graph",
    "format_source",
    "export_network_document",
    "graph_spec_from_dict",
    "lower_bundle_to_document",
    "resolve_graph",
    "validate_graph",
]
