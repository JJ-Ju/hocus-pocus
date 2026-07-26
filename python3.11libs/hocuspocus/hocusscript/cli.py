"""Native command-line interface for HocusScript source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from .bundle import (
    MAX_MODULE_BUNDLE_BYTES,
    BundleValidationError,
    CompiledBundle,
)
from .compiler import MAX_SOURCE_BYTES, compile_source
from .expander import ModuleExpansionError
from .exporter import MAX_EXPORT_RESPONSE_BYTES
from .lock_update import update_project_module_lock
from .mixed_lock_update import update_project_mixed_module_lock
from .module_compiler import ModuleProjectCompileError
from .module_format import (
    ModuleProjectFormatError,
    format_project_module_path,
)
from .module_semantic import (
    ModuleSemanticCompileError,
    compile_project_mixed_module_bundle,
    compile_project_mixed_module_semantic,
    compile_project_module_bundle,
    compile_project_module_semantic,
)
from .module_paths import ALIAS_PATTERN
from .native_artifact import NativeArtifactError, publish_text_artifact
from .project import MAX_EXTERNAL_ALIASES, ProjectContext, ProjectError, compile_path
from .resolved_modules import ModuleResolutionError
from .semantic import CatalogConstraint, resolve_graph

MAX_EXPORT_HANDOFF_BYTES = MAX_EXPORT_RESPONSE_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hocus",
        description="Check, format, compile, and lock native HocusScript projects.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "format", "compile"):
        command = subparsers.add_parser(name, allow_abbrev=False)
        command.add_argument(
            "source",
            help="A project-relative .hocus path (legacy 0.1 also accepts a contained absolute path).",
        )
        command.add_argument(
            "--project",
            default=os.environ.get("HOCUS_PROJECT_DIRECTORY"),
            help="Explicit HocusScript project directory (or HOCUS_PROJECT_DIRECTORY).",
        )
        command.add_argument(
            "--no-strict",
            action="store_true",
            help="Legacy language 0.1 only: allow a missing language header as a warning.",
        )
    subparsers.choices["check"].add_argument(
        "--json", action="store_true", help="Emit the machine-readable check result as JSON.",
    )
    for name in ("check", "compile"):
        subparsers.choices[name].add_argument(
            "--module-root",
            action="append",
            default=[],
            metavar="ALIAS=ABSOLUTE_PATH",
            help=(
                "Approve one manifest-declared alias=absolute-path root for this call; "
                "repeat to provide the complete exact alias mapping."
            ),
        )
    subparsers.choices["format"].add_argument("--write", action="store_true", help="Replace the source file atomically.")
    subparsers.choices["compile"].add_argument("-o", "--output", help="Write pretty bundle JSON to this native path.")
    subparsers.choices["compile"].add_argument(
        "--expected-output-digest",
        help="Exact raw SHA-256 digest required to replace an existing output file.",
    )
    lock = subparsers.add_parser(
        "lock",
        help="Explicitly derive and atomically update a HocusScript 0.2 module lock.",
        allow_abbrev=False,
    )
    lock.add_argument("entries", nargs="+", help="Project-relative graph entry .hocus files.")
    lock.add_argument("--update", action="store_true", help="Derive and publish the complete selected entry closures.")
    lock.add_argument(
        "--project",
        default=os.environ.get("HOCUS_PROJECT_DIRECTORY"),
        help="Explicit HocusScript project directory (or HOCUS_PROJECT_DIRECTORY).",
    )
    lock.add_argument(
        "--expected-lock-digest",
        help="Exact current canonical lock digest required for replacement.",
    )
    lock.add_argument(
        "--module-root",
        action="append",
        default=[],
        metavar="ALIAS=ABSOLUTE_PATH",
        help=(
            "Approve one manifest-declared alias=absolute-path root for this update; "
            "repeat to provide the complete exact alias mapping."
        ),
    )
    handoff = subparsers.add_parser(
        "write-export",
        help="Validate a document.export_source JSON handoff and write its source natively.",
        allow_abbrev=False,
    )
    handoff.add_argument("handoff", help="Export JSON path, or - to read JSON from stdin.")
    handoff.add_argument("destination", help="A project-contained .hocus destination.")
    handoff.add_argument(
        "--project",
        default=os.environ.get("HOCUS_PROJECT_DIRECTORY"),
        help="Explicit HocusScript project directory (or HOCUS_PROJECT_DIRECTORY).",
    )
    handoff.add_argument(
        "--expected-digest",
        help="Required source digest when intentionally replacing an existing destination.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    _validate_raw_arguments(parser, raw_arguments)
    args = parser.parse_args(raw_arguments)
    _validate_parsed_arguments(parser, args)
    try:
        return _dispatch_command(args)
    except _CLI_ERRORS as exc:
        return _report_cli_error(args, exc)


def _validate_raw_arguments(
    parser: argparse.ArgumentParser, raw_arguments: list[str],
) -> None:
    module_root_options = [
        value.partition("=")[0]
        for value in raw_arguments
        if isinstance(value, str) and value.startswith("--")
        and len(value.partition("=")[0]) > 2
        and (
            value.partition("=")[0].startswith("--module-root")
            or "--module-root".startswith(value.partition("=")[0])
        )
    ]
    supported_root_command = bool(
        raw_arguments and raw_arguments[0] in {"check", "compile", "lock"}
    )
    if any(value != "--module-root" for value in module_root_options):
        parser.error("external roots require the exact --module-root option spelling")
    if module_root_options and not supported_root_command:
        parser.error("--module-root is available only for check, compile, and lock --update")


def _validate_parsed_arguments(
    parser: argparse.ArgumentParser, args: argparse.Namespace,
) -> None:
    if not args.project:
        parser.error("--project or HOCUS_PROJECT_DIRECTORY is required")
    if args.command == "compile" and args.expected_output_digest and not args.output:
        parser.error("--expected-output-digest requires --output")
    if args.command == "lock" and not args.update:
        parser.error("lock currently requires --update")


def _dispatch_command(args: argparse.Namespace) -> int:
    module_roots = _parse_module_roots(getattr(args, "module_root", ()))
    if args.command == "write-export":
        return _write_export_handoff(
            args.handoff, args.destination, args.project, args.expected_digest,
        )
    if args.command == "lock":
        return _run_lock_command(args, module_roots)
    project = ProjectContext.load(args.project, validate_lock=False)
    if project.manifest_version == 3 or project.language_version == "0.2":
        return _run_module_command(args, module_roots)
    if module_roots:
        raise ProjectError(
            "HOCUS460", "--module-root requires a language 0.2 schema v3 project.",
        )
    return _run_legacy_command(args)


def _run_lock_command(args: argparse.Namespace, module_roots: dict[str, str]) -> int:
    if module_roots:
        result = update_project_mixed_module_lock(
            args.project, args.entries, module_roots, allow_write=True,
            expected_lock_digest=args.expected_lock_digest,
        )
    else:
        result = update_project_module_lock(
            args.project, args.entries, allow_write=True,
            expected_lock_digest=args.expected_lock_digest,
        )
    sys.stdout.write(json.dumps(
        result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True,
    ) + "\n")
    return 0


def _run_legacy_command(args: argparse.Namespace) -> int:
    result = compile_path(
        args.source, project_directory=args.project, strict=not args.no_strict,
        validate_lock=args.command != "format",
    )
    if args.command == "check":
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_diagnostics(result.to_dict())
        return 0 if result.valid else 1
    if not result.valid or result.formatted_source is None:
        _print_diagnostics(result.to_dict())
        return 1
    if args.command == "format":
        return _publish_legacy_format(args, result)
    bundle = CompiledBundle.from_result(result)
    if not bundle.payload["portable"]:
        print(f"HOCUS417: {args.project!s} requires hocus.project.toml with a stable project uid for bundle compilation.", file=sys.stderr)
        return 1
    output = bundle.to_json(pretty=True)
    if args.output:
        _atomic_write(
            Path(args.output).expanduser().resolve(), output,
            expected_digest=args.expected_output_digest, max_bytes=MAX_MODULE_BUNDLE_BYTES,
        )
    else:
        sys.stdout.write(output)
    return 0


def _publish_legacy_format(args: argparse.Namespace, result: Any) -> int:
    if args.write:
        if result.native_source_path is None:
            raise ProjectError("HOCUS418", "Native source path is unavailable for in-place formatting.")
        _atomic_write(
            Path(result.native_source_path), result.formatted_source,
            expected_digest=result.source_digest,
        )
    else:
        sys.stdout.write(result.formatted_source)
    return 0


def _report_cli_error(args: argparse.Namespace, exc: Any) -> int:
    if args.command == "check" and args.json:
        sys.stdout.write(json.dumps(
            _module_check_error_payload(exc), ensure_ascii=False, indent=2, sort_keys=True,
        ) + "\n")
        return 1
    print(f"{exc.code}: {exc.message}", file=sys.stderr)
    return 1


_CLI_ERRORS = (
    ProjectError,
    ModuleResolutionError,
    ModuleExpansionError,
    ModuleProjectCompileError,
    ModuleProjectFormatError,
    ModuleSemanticCompileError,
    BundleValidationError,
    NativeArtifactError,
)


def _run_module_command(
    args: argparse.Namespace,
    module_roots: dict[str, str],
) -> int:
    if args.no_strict:
        raise ProjectError(
            "HOCUS460",
            "--no-strict is a language 0.1 compatibility option; language 0.2 headers are mandatory.",
        )
    if args.command == "format":
        result = format_project_module_path(args.project, args.source)
        if not result.valid or result.formatted_source is None:
            _print_diagnostics(result.to_dict())
            return 1
        if args.write:
            _atomic_write(
                Path(result.native_source_path),
                result.formatted_source,
                expected_digest=result.source_digest,
                max_bytes=MAX_SOURCE_BYTES,
            )
        else:
            sys.stdout.write(result.formatted_source)
        return 0
    if args.command == "check":
        result = (
            compile_project_mixed_module_semantic(
                args.project, args.source, module_roots,
            )
            if module_roots else
            compile_project_module_semantic(args.project, args.source)
        )
        if args.json:
            sys.stdout.write(result.to_json(pretty=True))
        else:
            _print_diagnostics(result.semantic)
        return 0 if result.valid else 1
    bundle = (
        compile_project_mixed_module_bundle(
            args.project, args.source, module_roots,
        )
        if module_roots else
        compile_project_module_bundle(args.project, args.source)
    )
    output = bundle.to_json(pretty=True)
    if args.output:
        _atomic_write(
            Path(args.output).expanduser().resolve(),
            output,
            expected_digest=args.expected_output_digest,
            max_bytes=MAX_MODULE_BUNDLE_BYTES,
        )
    else:
        sys.stdout.write(output)
    return 0


def _parse_module_roots(values: Sequence[str]) -> dict[str, str]:
    if not isinstance(values, (list, tuple)) or len(values) > MAX_EXTERNAL_ALIASES:
        raise ProjectError("HOCUS458", "--module-root values exceed the alias limit.")
    roots: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str):
            raise ProjectError("HOCUS458", "--module-root must use alias=absolute-path.")
        alias, separator, path = value.partition("=")
        if (
            not separator
            or ALIAS_PATTERN.fullmatch(alias) is None
            or not path
            or path != path.strip()
            or not Path(path).is_absolute()
            or alias in roots
        ):
            raise ProjectError(
                "HOCUS458",
                "--module-root must use one unique alias=absolute-path value per alias.",
            )
        roots[alias] = path
    return roots


def _module_check_error_payload(exc) -> dict:
    details = dict(getattr(exc, "details", {}) or {})
    diagnostic = details.get("diagnostic")
    if not isinstance(diagnostic, dict):
        diagnostic = {
            "severity": "error",
            "code": exc.code,
            "phase": "project",
            "message": exc.message,
            # Project/native exception details may contain diagnostic-only host
            # paths. Machine-readable check output is deliberately portable.
            "details": {},
        }
        source_uri = details.get("sourceUri")
        if isinstance(source_uri, str) and source_uri.startswith((
            "hocus-project://", "hocus-module://", "hocus-workspace:///", "hocus-memory:///",
        )):
            diagnostic["sourceUri"] = source_uri
    return {
        "stage": "semantic",
        "valid": False,
        "readyForBundle": False,
        "readyForDocumentLowering": False,
        "readyForApply": False,
        "diagnostics": [diagnostic],
    }


def _print_diagnostics(payload: dict) -> None:
    for diagnostic in payload["diagnostics"]:
        location = diagnostic.get("sourceUri", payload.get("sourceUri", "<source>"))
        span = diagnostic.get("span", {}).get("start", {})
        line = span.get("line", 1)
        column = span.get("column", 1)
        print(
            f"{location}:{line}:{column}: {diagnostic['severity']} {diagnostic['code']}: {diagnostic['message']}",
            file=sys.stderr,
        )


def _atomic_write(
    path: Path,
    text: str,
    *,
    expected_digest: str | None = None,
    max_bytes: int = MAX_MODULE_BUNDLE_BYTES,
) -> None:
    try:
        publish_text_artifact(
            path, text, expected_digest=expected_digest, max_bytes=max_bytes,
        )
    except NativeArtifactError as exc:
        if exc.code == "HOCUS491":
            code = "HOCUS440" if expected_digest is None else "HOCUS418"
        elif exc.code == "HOCUS490" and expected_digest is not None:
            code = "HOCUS418"
        else:
            code = "HOCUS447"
        raise ProjectError(code, exc.message, details=exc.details) from exc


def _write_export_handoff(
    handoff_path: str,
    destination: str,
    project_directory: str,
    expected_digest: str | None,
) -> int:
    payload = _load_export_handoff(handoff_path, project_directory)
    source, provenance, source_digest = _validate_export_payload(payload)
    project = ProjectContext.load(project_directory, validate_lock=True)
    _validate_export_project_identity(project, provenance)
    output_path = project.resolve_source_destination(destination)
    source_uri = project.source_uri_for_resolved(output_path)
    compiled = _compile_export_source(source, output_path, source_uri)
    _verify_export_catalog(project, provenance, compiled)
    _atomic_write(output_path, source, expected_digest=expected_digest)
    print(json.dumps({"sourceUri": source_uri, "sourceDigest": source_digest}, sort_keys=True))
    return 0


def _load_export_handoff(handoff_path: str, project_directory: str) -> dict[str, Any]:
    preview = ProjectContext.load(project_directory, validate_lock=False)
    if preview.manifest_version == 4 or preview.language_version == "0.3":
        raise ProjectError(
            "HOCUS456",
            "HocusScript 0.3 export publication remains disabled until its native integration batch.",
        )
    raw = sys.stdin.buffer.read(MAX_EXPORT_HANDOFF_BYTES + 1) if handoff_path == "-" else _read_handoff(Path(handoff_path))
    if len(raw) > MAX_EXPORT_HANDOFF_BYTES:
        raise ProjectError("HOCUS441", "Export handoff exceeds the native size limit.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectError("HOCUS442", f"Export handoff is not valid UTF-8 JSON: {exc}") from exc
    if isinstance(payload, dict) and isinstance(payload.get("structuredContent"), dict):
        payload = payload["structuredContent"]
    if (
        not isinstance(payload, dict)
        or payload.get("stage") != "source_export"
        or payload.get("exportVersion") != "1.0"
        or payload.get("languageVersion") != "0.1"
        or payload.get("valid") is not True
    ):
        raise ProjectError("HOCUS443", "Export handoff is not a successful source_export result.")
    return payload


def _validate_export_payload(
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any], str]:
    source = payload.get("source")
    provenance = payload.get("provenance")
    if (
        not isinstance(source, str)
        or not isinstance(provenance, dict)
        or provenance.get("format") != "hocus-export-provenance-v0.1"
    ):
        raise ProjectError("HOCUS443", "Export handoff must contain source text and provenance.")
    actual_source_digest = f"sha256:{hashlib.sha256(source.encode('utf-8')).hexdigest()}"
    if provenance.get("sourceDigest") != actual_source_digest:
        raise ProjectError(
            "HOCUS444",
            "Export source digest does not match its provenance.",
            details={"expected": provenance.get("sourceDigest"), "actual": actual_source_digest},
        )
    return source, provenance, actual_source_digest


def _validate_export_project_identity(
    project: ProjectContext, provenance: dict[str, Any],
) -> None:
    entity_records = provenance.get("entities")
    exported_project_uids: set[str] = set()
    if isinstance(entity_records, dict):
        for record in entity_records.values():
            hocus = record.get("hocus") if isinstance(record, dict) else None
            if isinstance(hocus, dict) and isinstance(hocus.get("projectUid"), str):
                exported_project_uids.add(hocus["projectUid"])
    if len(exported_project_uids) > 1 or (
        exported_project_uids and project.uid not in exported_project_uids
    ):
        raise ProjectError(
            "HOCUS448",
            "Export provenance project identity does not match the selected project.",
            details={"exportProjectUids": sorted(exported_project_uids), "projectUid": project.uid},
        )


def _compile_export_source(source: str, output_path: Path, source_uri: str):
    compiled = compile_source(source, output_path.name, source_uri=source_uri, strict=True)
    if not compiled.valid or compiled.graph_spec is None:
        raise ProjectError(
            "HOCUS445",
            "Exported source did not pass native recompilation.",
            details={"diagnostics": [item.to_dict() for item in compiled.diagnostics]},
        )
    return compiled


def _verify_export_catalog(
    project: ProjectContext, provenance: dict[str, Any], compiled: Any,
) -> None:
    catalog_fingerprint = provenance.get("catalogFingerprint")
    if catalog_fingerprint is None:
        return
    if project.catalog is None:
        raise ProjectError("HOCUS446", "Export requires a project-locked catalog for semantic verification.")
    if catalog_fingerprint != project.catalog.fingerprint:
        raise ProjectError(
            "HOCUS446",
            "Export catalog fingerprint does not match the selected project.",
            details={"export": catalog_fingerprint, "project": project.catalog.fingerprint},
        )
    semantic = resolve_graph(
        compiled.graph_spec, project.catalog,
        constraint=CatalogConstraint(catalog_fingerprint),
    )
    if not semantic.valid:
        raise ProjectError(
            "HOCUS445", "Exported source failed catalog-backed recompilation.",
            details={"diagnostics": [item.to_dict() for item in semantic.diagnostics]},
        )


def _read_handoff(path: Path) -> bytes:
    try:
        with path.expanduser().resolve().open("rb") as handle:
            return handle.read(MAX_EXPORT_HANDOFF_BYTES + 1)
    except OSError as exc:
        raise ProjectError("HOCUS441", f"Could not read export handoff: {exc}") from exc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
