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
from .project import ProjectError, compile_path


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.project:
        parser.error("--project or HOCUS_PROJECT_DIRECTORY is required")
    try:
        result = compile_path(args.source, project_directory=args.project, strict=not args.no_strict)
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
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
