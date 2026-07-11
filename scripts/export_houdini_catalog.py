"""Export a portable HocusScript catalog from hython.

Usage:
    hython scripts/export_houdini_catalog.py --project path/to/hocus-project
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / "python3.11libs"
sys.path.insert(0, str(PYTHON_LIBS))

# Houdini may preload an installed HocusPocus package before executing scripts.
# Extend that package's search roots so this source-tree exporter remains usable
# without first copying an in-development provider into the user package.
import hocuspocus
import hocuspocus.live

source_package = str(PYTHON_LIBS / "hocuspocus")
source_live = str(PYTHON_LIBS / "hocuspocus" / "live")
if source_package not in hocuspocus.__path__:
    hocuspocus.__path__.insert(0, source_package)
if source_live not in hocuspocus.live.__path__:
    hocuspocus.live.__path__.insert(0, source_live)

from hocuspocus.live.catalog_provider import LiveHoudiniCatalogProvider
from hocuspocus.hocusscript.project import ProjectContext, ProjectError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        type=Path,
        help="HocusScript project directory (or set HOCUS_PROJECT_DIRECTORY)",
    )
    arguments = parser.parse_args(argv)

    project_directory = arguments.project or os.environ.get("HOCUS_PROJECT_DIRECTORY")
    if not project_directory:
        parser.error("--project or HOCUS_PROJECT_DIRECTORY is required")
    try:
        project = ProjectContext.load(project_directory, validate_lock=False)
    except ProjectError as error:
        parser.error(f"{error.code}: {error.message}")
    if project.manifest_version != 2 or project.catalog_path is None or project.catalog_relative_path is None:
        parser.error("project manifest v2 with an explicit [catalog].path is required")

    try:
        import hou  # type: ignore
    except ImportError as error:
        parser.error(f"this script must run under hython: {error}")

    snapshot = LiveHoudiniCatalogProvider(hou).get_catalog()
    output = project.catalog_path
    output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output = output.resolve(strict=False)
    try:
        resolved_output.relative_to(project.root)
    except ValueError:
        parser.error("catalog destination escaped the approved project directory")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=output.name + ".",
        suffix=".tmp",
        dir=output.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(snapshot.to_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, resolved_output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        f"Wrote {len(snapshot.operators)} operators to "
        f"{project.catalog_relative_path} in project {project.uid}"
    )
    print(snapshot.fingerprint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
