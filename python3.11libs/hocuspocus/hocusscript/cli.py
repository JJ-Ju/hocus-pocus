"""Native command-line interface for HocusScript source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .bundle import CompiledBundle
from .compiler import compile_source
from .exporter import MAX_EXPORT_RESPONSE_BYTES
from .project import ProjectContext, ProjectError, compile_path
from .semantic import CatalogConstraint, resolve_graph

MAX_EXPORT_HANDOFF_BYTES = MAX_EXPORT_RESPONSE_BYTES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hocus", description="Check, format, and compile native HocusScript files.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "format", "compile"):
        command = subparsers.add_parser(name)
        command.add_argument("source", help="A .hocus path relative to --project, or a contained absolute path.")
        command.add_argument(
            "--project",
            default=os.environ.get("HOCUS_PROJECT_DIRECTORY"),
            help="Explicit HocusScript project directory (or HOCUS_PROJECT_DIRECTORY).",
        )
        command.add_argument("--no-strict", action="store_true", help="Allow a missing language header as a warning.")
    subparsers.choices["check"].add_argument("--json", action="store_true", help="Emit the structural result as JSON.")
    subparsers.choices["format"].add_argument("--write", action="store_true", help="Replace the source file atomically.")
    subparsers.choices["compile"].add_argument("-o", "--output", help="Write pretty bundle JSON to this native path.")
    handoff = subparsers.add_parser(
        "write-export",
        help="Validate a document.export_source JSON handoff and write its source natively.",
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
    args = parser.parse_args(argv)
    if not args.project:
        parser.error("--project or HOCUS_PROJECT_DIRECTORY is required")
    try:
        if args.command == "write-export":
            return _write_export_handoff(args.handoff, args.destination, args.project, args.expected_digest)
        result = compile_path(
            args.source,
            project_directory=args.project,
            strict=not args.no_strict,
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
            if args.write:
                if result.native_source_path is None:
                    raise ProjectError("HOCUS418", "Native source path is unavailable for in-place formatting.")
                _atomic_write(Path(result.native_source_path), result.formatted_source, expected_digest=result.source_digest)
            else:
                sys.stdout.write(result.formatted_source)
            return 0
        bundle = CompiledBundle.from_result(result)
        if not bundle.payload["portable"]:
            print(f"HOCUS417: {args.project!s} requires hocus.project.toml with a stable project uid for bundle compilation.", file=sys.stderr)
            return 1
        output = bundle.to_json(pretty=True)
        if args.output:
            _atomic_write(Path(args.output).expanduser().resolve(), output)
        else:
            sys.stdout.write(output)
        return 0
    except ProjectError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1


def _print_diagnostics(payload: dict) -> None:
    for diagnostic in payload["diagnostics"]:
        location = diagnostic.get("sourceUri", payload.get("sourceUri", "<source>"))
        span = diagnostic.get("span", {}).get("start", {})
        line = span.get("line", 1)
        column = span.get("column", 1)
        print(f"{location}:{line}:{column}: {diagnostic['severity']} {diagnostic['code']}: {diagnostic['message']}")


def _atomic_write(path: Path, text: str, *, expected_digest: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected_digest is None and path.exists():
        raise ProjectError(
            "HOCUS440",
            "Destination already exists; pass its exact --expected-digest to replace it.",
            details={"path": str(path)},
        )
    if expected_digest is not None:
        try:
            current_digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        except OSError as exc:
            raise ProjectError("HOCUS418", f"Could not re-read source before replacement: {exc}") from exc
        if current_digest != expected_digest:
            raise ProjectError(
                "HOCUS418",
                "Source changed after compilation; refusing to overwrite it.",
                details={"expectedDigest": expected_digest, "actualDigest": current_digest},
            )
    original_mode = path.stat().st_mode if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if original_mode is not None:
            os.chmod(temporary, original_mode)
        if expected_digest is None:
            try:
                # Same-directory hard-link publication is atomic and fails if the
                # destination appeared after the preflight check.
                os.link(temporary, path)
            except FileExistsError as exc:
                raise ProjectError(
                    "HOCUS440",
                    "Destination was created concurrently; refusing to overwrite it.",
                    details={"path": str(path)},
                ) from exc
            except OSError as exc:
                raise ProjectError("HOCUS447", f"Could not publish destination atomically: {exc}") from exc
            temporary.unlink()
        else:
            # Recheck immediately before replacement to narrow the check/replace race.
            current_digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
            if current_digest != expected_digest:
                raise ProjectError(
                    "HOCUS418",
                    "Destination changed during replacement; refusing to overwrite it.",
                    details={"expectedDigest": expected_digest, "actualDigest": current_digest},
                )
            os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_export_handoff(
    handoff_path: str,
    destination: str,
    project_directory: str,
    expected_digest: str | None,
) -> int:
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

    project = ProjectContext.load(project_directory, validate_lock=True)
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
    output_path = project.resolve_source_destination(destination)
    source_uri = project.source_uri_for_resolved(output_path)
    compiled = compile_source(source, output_path.name, source_uri=source_uri, strict=True)
    if not compiled.valid or compiled.graph_spec is None:
        raise ProjectError(
            "HOCUS445",
            "Exported source did not pass native recompilation.",
            details={"diagnostics": [item.to_dict() for item in compiled.diagnostics]},
        )
    catalog_fingerprint = provenance.get("catalogFingerprint")
    if catalog_fingerprint is not None:
        if project.catalog is None:
            raise ProjectError("HOCUS446", "Export requires a project-locked catalog for semantic verification.")
        if catalog_fingerprint != project.catalog.fingerprint:
            raise ProjectError(
                "HOCUS446",
                "Export catalog fingerprint does not match the selected project.",
                details={"export": catalog_fingerprint, "project": project.catalog.fingerprint},
            )
        semantic = resolve_graph(
            compiled.graph_spec,
            project.catalog,
            constraint=CatalogConstraint(catalog_fingerprint),
        )
        if not semantic.valid:
            raise ProjectError(
                "HOCUS445",
                "Exported source failed catalog-backed recompilation.",
                details={"diagnostics": [item.to_dict() for item in semantic.diagnostics]},
            )
    _atomic_write(output_path, source, expected_digest=expected_digest)
    print(json.dumps({"path": str(output_path), "sourceUri": source_uri, "sourceDigest": actual_source_digest}, sort_keys=True))
    return 0


def _read_handoff(path: Path) -> bytes:
    try:
        with path.expanduser().resolve().open("rb") as handle:
            return handle.read(MAX_EXPORT_HANDOFF_BYTES + 1)
    except OSError as exc:
        raise ProjectError("HOCUS441", f"Could not read export handoff: {exc}") from exc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
