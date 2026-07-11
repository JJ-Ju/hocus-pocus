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
from .formatter import format_graph
from .model import COMPILER_VERSION, GRAPH_SPEC_VERSION, CompileResult, GraphSpec
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
    "COMPILER_VERSION",
    "CompiledBundle",
    "CatalogConstraint",
    "ConnectionSelection",
    "DeferredCheck",
    "Diagnostic",
    "FakeCatalogProvider",
    "GraphSpec",
    "GRAPH_SPEC_VERSION",
    "ProjectContext",
    "ProjectError",
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
    "decode_compiled_bundle",
    "decode_catalog_snapshot",
    "format_graph",
    "resolve_graph",
    "validate_graph",
]
