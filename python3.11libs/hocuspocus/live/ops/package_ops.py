"""Scene packaging and archival operations."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from hocuspocus.core import paths as core_paths
from hocuspocus.core.jsonrpc import INVALID_PARAMS, JsonRpcError
from hocuspocus.core.policy import ensure_path_allowed

from ..context import RequestContext


class PackageOperationsMixin:
    def _normalize_package_destination(self, arguments: dict[str, Any]) -> Path:
        path_value = str(arguments.get("destination_path", "")).strip()
        if path_value:
            destination = ensure_path_allowed(path_value, self._settings)
        else:
            mode = str(arguments.get("mode", "zip")).strip().lower() or "zip"
            stem = str(arguments.get("package_name", "")).strip() or "scene_package"
            if mode == "directory":
                destination = core_paths.package_dir() / stem
            else:
                destination = core_paths.package_dir() / f"{stem}.zip"
            destination = ensure_path_allowed(destination, self._settings)
        return destination

    def _package_dependency_scan(self, arguments: dict[str, Any]) -> dict[str, Any]:
        scan_payload = arguments.get("dependency_scan")
        if isinstance(scan_payload, dict) and isinstance(scan_payload.get("dependencies"), list):
            return scan_payload
        root_path = str(arguments.get("root_path", "")).strip() or None
        return self._dependency_scan_impl({"root_path": root_path})

    @staticmethod
    def _package_relpath_for_file(path: Path) -> Path:
        drive = path.drive.rstrip(":").replace(":", "")
        parts = [part for part in path.parts[1:] if part not in {"\\", "/"}]
        if drive:
            return Path("files") / drive / Path(*parts)
        return Path("files") / Path(*parts)

    def _package_preview_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        include_outputs = bool(arguments.get("include_outputs", False))
        include_hip = bool(arguments.get("include_hip", True))
        root_path = str(arguments.get("root_path", "")).strip() or None
        existing_only = bool(arguments.get("existing_only", True))
        scan = self._package_dependency_scan(arguments)
        entries: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        seen_files: set[str] = set()

        if include_hip:
            hip_path = self._safe_value(lambda: self._require_hou().hipFile.path(), "") or ""
            if hip_path:
                hip_candidate = Path(hip_path).expanduser()
                if hip_candidate.exists():
                    normalized = str(hip_candidate.resolve(strict=False))
                    seen_files.add(normalized)
                    entries.append(
                        {
                            "kind": "hip_file",
                            "sourcePath": normalized,
                            "archivePath": str(Path("hip") / hip_candidate.name),
                            "exists": True,
                        }
                    )
                else:
                    skipped.append(
                        {
                            "kind": "hip_file",
                            "sourcePath": str(hip_candidate),
                            "reason": "missing",
                        }
                    )

        for dependency in scan.get("dependencies", []):
            direction = dependency.get("direction")
            if direction == "output" and not include_outputs:
                skipped.append(
                    {
                        "kind": dependency.get("kind"),
                        "sourcePath": dependency.get("expandedPath") or dependency.get("rawValue"),
                        "reason": "outputs_excluded",
                    }
                )
                continue

            source_value = str(
                dependency.get("expandedPath")
                or dependency.get("normalizedPath")
                or dependency.get("rawValue")
                or ""
            ).strip()
            if not source_value or source_value.startswith("opdef:") or source_value.startswith("`"):
                skipped.append(
                    {
                        "kind": dependency.get("kind"),
                        "sourcePath": source_value,
                        "reason": "non_filesystem_reference",
                    }
                )
                continue

            source_path = Path(source_value).expanduser()
            normalized = str(source_path.resolve(strict=False))
            exists = source_path.exists()
            is_file = source_path.is_file()
            if existing_only and not exists:
                skipped.append(
                    {
                        "kind": dependency.get("kind"),
                        "sourcePath": normalized,
                        "reason": "missing",
                    }
                )
                continue
            if exists and not is_file:
                skipped.append(
                    {
                        "kind": dependency.get("kind"),
                        "sourcePath": normalized,
                        "reason": "directory_unsupported",
                    }
                )
                continue
            if normalized in seen_files:
                continue
            seen_files.add(normalized)
            entries.append(
                {
                    "kind": dependency.get("kind"),
                    "direction": direction,
                    "sourcePath": normalized,
                    "archivePath": str(self._package_relpath_for_file(source_path)),
                    "parmPath": dependency.get("parmPath"),
                    "nodePath": dependency.get("nodePath"),
                    "exists": exists,
                }
            )

        summary = {
            "collectCount": len(entries),
            "skipCount": len(skipped),
            "includeHip": include_hip,
            "includeOutputs": include_outputs,
            "existingOnly": existing_only,
            "rootPath": root_path,
        }
        return {
            "summary": summary,
            "entries": entries,
            "skipped": skipped,
            "dependencySummary": scan.get("summary", {}),
        }

    def package_preview_scene(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._package_preview_impl(arguments), context)
        return self._tool_response(
            f"Prepared package preview with {data['summary']['collectCount']} file(s).",
            data,
        )

    def _package_write_directory(self, destination: Path, entries: list[dict[str, Any]]) -> list[str]:
        written: list[str] = []
        destination.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            source = Path(str(entry["sourcePath"]))
            relative = Path(str(entry["archivePath"]))
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            written.append(str(target.resolve(strict=False)))
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps({"entries": entries}, ensure_ascii=True, indent=2), encoding="utf-8")
        written.append(str(manifest_path.resolve(strict=False)))
        return written

    def _package_write_zip(self, destination: Path, entries: list[dict[str, Any]]) -> list[str]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry in entries:
                source = Path(str(entry["sourcePath"]))
                archive.write(source, arcname=str(entry["archivePath"]).replace("\\", "/"))
            archive.writestr("manifest.json", json.dumps({"entries": entries}, ensure_ascii=True, indent=2))
        return [str(destination.resolve(strict=False))]

    def _package_create_impl(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode = str(arguments.get("mode", "zip")).strip().lower() or "zip"
        if mode not in {"zip", "directory"}:
            raise JsonRpcError(INVALID_PARAMS, "mode must be 'zip' or 'directory'")
        dry_run = bool(arguments.get("dry_run", False))
        destination = self._normalize_package_destination(arguments)
        preview = self._package_preview_impl(arguments)
        entries = preview["entries"]

        written_paths: list[str] = []
        if not dry_run:
            if mode == "directory":
                written_paths = self._package_write_directory(destination, entries)
            else:
                written_paths = self._package_write_zip(destination, entries)

        return {
            "mode": mode,
            "dryRun": dry_run,
            "destinationPath": str(destination),
            "summary": preview["summary"],
            "entries": entries,
            "skipped": preview["skipped"],
            "dependencySummary": preview["dependencySummary"],
            "writtenPaths": written_paths,
        }

    def package_create_scene_package(self, arguments: dict[str, Any], context: RequestContext) -> dict[str, Any]:
        data = self._call_live(lambda: self._package_create_impl(arguments), context)
        verb = "Prepared" if data["dryRun"] else "Created"
        return self._tool_response(
            f"{verb} scene package with {data['summary']['collectCount']} collected file(s).",
            data,
        )

    def read_package_preview(self, context: RequestContext) -> dict[str, Any]:
        return self._resource_response(
            "houdini://packages/preview",
            self._call_live(
                lambda: self._package_preview_impl(
                    {
                        "include_hip": True,
                        "include_outputs": False,
                        "existing_only": True,
                    }
                ),
                context,
            ),
        )
