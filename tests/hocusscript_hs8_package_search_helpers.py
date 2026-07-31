"""Focused package-search provenance coverage inside the existing HS8 scenario."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import hocuspocus.live.hda_library_identity as hda_identity
from hocuspocus.live.catalog_provider import (
    LiveCatalogExtractionError,
    LiveHoudiniCatalogProvider,
    definition_content_digest,
)
from hocuspocus.live.hda_library_identity import HdaLibraryIdentityError
from hocuspocus.hocusscript.catalog import DefinitionSource
from hocuspocus.live.production_observation import ProductionFixtureObserver
from hocuspocus.live.package_search_provenance import (
    PackageSearchProvenanceError,
    collect_effective_package_search,
    decode_effective_package_search,
    verify_effective_package_search,
)
from hocuspocus.live.package_startup_trace import (
    PackageStartupTraceError,
    load_package_startup_trace,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT / "docs" / "schemas"
    / "effective-package-search-provenance-v1.schema.json"
)
SUPPORT = ROOT / "scripts" / "smoke_hocusscript_hs8_support.py"
MODULE = (
    ROOT / "python3.11libs" / "hocuspocus" / "live"
    / "package_search_provenance.py"
)


def assert_hs8_package_search_provenance(testcase: Any) -> None:
    """Prove live re-derivation, build binding, and hostile path rejection."""

    with tempfile.TemporaryDirectory(prefix="hs8-package-search-") as value:
        fixture = _Fixture(Path(value))
        receipt = fixture.collect()
        testcase.assertEqual(
            verify_effective_package_search(
                receipt,
                fixture.hou,
                fixture.provider,
                fixture.catalog,
                installed_root=fixture.installed,
                install_manifest=fixture.manifest,
                modules=fixture.modules,
                python_paths=fixture.python_paths,
                startup_trace=fixture.startup_trace,
            ),
            receipt,
        )
        testcase.assertEqual(
            receipt["installedPayload"]["manifestDigest"],
            fixture.manifest["manifestDigest"],
        )
        portable_root = Path(value) / "portable"
        portable_root.mkdir()
        portable = _Fixture(portable_root)
        testcase.assertEqual(
            receipt["installedPayload"]["rootDigest"],
            portable.collect()["installedPayload"]["rootDigest"],
        )
        testcase.assertEqual(
            receipt["packages"][0]["conditionKeys"],
            ["enable", "process_order"],
        )
        testcase.assertEqual(
            receipt["operatorWinners"][0]["winner"]["libraryLocator"],
            "hocus-install://root/rock.hda",
        )
        testcase.assertEqual(receipt["shadowing"], [])
        _assert_tamper_rejected(testcase, fixture, receipt)
        _assert_repository_import_rejected(testcase, fixture)
        _assert_shadow_path_rejected(testcase, fixture)
        _assert_ambiguous_hda_rejected(testcase, fixture)
        _assert_unexplained_hda_rejected(testcase, fixture)
        _assert_missing_optional_hda_ignored(testcase, fixture)
        _assert_regular_hda_digest_compatibility(testcase, fixture)
        _assert_directory_hda_identity(testcase, fixture)
        _assert_hda_library_identity_boundaries(testcase, fixture)
        _assert_package_shadow_rejected(testcase, fixture)
        _assert_package_info_boundary(testcase, fixture)
        _assert_native_binary_identity(testcase, fixture)
        _assert_contents_bytes_are_hashed(testcase)
        _assert_disabled_skipped_trace(testcase, fixture.root)
        _assert_schema_and_build_coverage(testcase, receipt)


class _Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.installed = root / "installed"
        self.python = self.installed / "python3.11libs"
        self.package_dir = root / "packages"
        self.hfs = root / "hfs"
        self.installed.mkdir()
        self.python.mkdir()
        self.package_dir.mkdir()
        self.hfs.mkdir()
        package = self.python / "hocuspocus"
        package.mkdir()
        self.module_file = package / "__init__.py"
        self.module_file.write_text("# installed\n", encoding="utf-8")
        self.hda_file = self.installed / "rock.hda"
        self.hda_file.write_bytes(b"rock-hda")
        self.package_file = self.package_dir / "hocuspocus.json"
        self.package_file.write_text(json.dumps({
            "enable": "houdini_os == 'windows'",
            "process_order": -100,
            "env": [{"HOCUSPOCUS_ROOT": "$HOCUSPOCUS_ROOT"}],
            "hpath": "$HOCUSPOCUS_ROOT",
        }), encoding="utf-8")
        self.startup_trace = _startup_trace(self.package_file)
        self.definition = _Definition(self.hda_file, current=True, preferred=True)
        self.node_type = _NodeType((self.definition,))
        self.category = _Category(self.node_type)
        self.hou = _Hou(self)
        self.provider = LiveHoudiniCatalogProvider(
            self.hou,
            package_directories=(self.package_dir,),
            catalog_version=2,
        )
        self.catalog = self.provider.get_catalog()
        self.manifest = {
            "$schema": "hocuspocus://schemas/install-manifest/v1",
            "kind": "hocus_install_manifest",
            "schemaVersion": 1,
            "governedRoots": [
                "config", "docs/schemas", "python_panels", "python3.11libs",
                "scripts", "toolbar", "package",
            ],
            "files": [
                {
                    "relativePath": "docs/schemas/asset-contract-v1.schema.json",
                    "role": "immutable",
                    "byteLength": 2,
                    "contentDigest": _digest(b"{}"),
                },
                {
                    "relativePath": "python3.11libs/hocuspocus/__init__.py",
                    "role": "immutable",
                    "byteLength": len(b"# installed\n"),
                    "contentDigest": _digest(b"# installed\n"),
                },
            ],
        }
        self.manifest["manifestDigest"] = _canonical_digest(self.manifest)
        self.modules = {
            "hocuspocus": SimpleNamespace(__file__=str(self.module_file)),
        }
        self.python_paths = (str(self.python),)

    def collect(self) -> dict[str, Any]:
        return collect_effective_package_search(
            self.hou,
            self.provider,
            self.catalog,
            installed_root=self.installed,
            install_manifest=self.manifest,
            modules=self.modules,
            python_paths=self.python_paths,
            startup_trace=self.startup_trace,
        )


class _Hou:
    def __init__(self, fixture: _Fixture):
        self.fixture = fixture
        self.ui = _Ui(fixture)
        self.hda = _Hda(fixture)

    def applicationVersion(self):
        return (22, 0, 368)

    def applicationVersionString(self):
        return "22.0.368"

    def applicationPlatformInfo(self):
        return "windows-x86_64"

    def applicationName(self):
        return "Houdini"

    def licenseCategory(self):
        return SimpleNamespace(name=lambda: "Commercial")

    def nodeTypeCategories(self):
        return {"Sop": self.fixture.category}

    def houdiniPath(self, variable=None):
        if variable == "HOUDINI_OTLSCAN_PATH":
            return (str(self.fixture.installed),)
        return (str(self.fixture.installed),)

    def getenv(self, name):
        return {
            "HFS": str(self.fixture.hfs),
            "HOCUSPOCUS_ROOT": str(self.fixture.installed),
        }.get(name)

    def expandString(self, value):
        return (
            str(value)
            .replace("$HFS", str(self.fixture.hfs))
            .replace("$HOCUSPOCUS_ROOT", str(self.fixture.installed))
        )


class _Ui:
    def __init__(self, fixture: _Fixture):
        self.fixture = fixture

    def packageInfo(self):
        return json.dumps({
            "hocuspocus": {
                "File path": str(self.fixture.package_file),
                "Load only once": True,
                "Variables": {
                    "HOCUSPOCUS_ROOT": str(self.fixture.installed),
                },
            },
        })


class _Hda:
    def __init__(self, fixture: _Fixture):
        self.fixture = fixture

    def loadedFiles(self):
        return tuple(
            str(item.libraryFilePath())
            for item in self.fixture.node_type.allInstalledDefinitions()
        )


class _Category:
    def __init__(self, node_type: Any):
        self.node_type = node_type

    def name(self):
        return "Sop"

    def label(self):
        return "SOP"

    def nodeTypes(self):
        result = {"studio::rock::1.0": self.node_type}
        native = getattr(self, "native", None)
        if native is not None:
            result[native.name()] = native
        return result


class _NodeType:
    def __init__(self, definitions: tuple[Any, ...]):
        self.definitions = definitions

    def name(self):
        return "studio::rock::1.0"

    def nameComponents(self):
        return ("", "studio", "rock", "1.0")

    def definition(self):
        currents = [item for item in self.definitions if item.isCurrent()]
        return currents[0] if len(currents) == 1 else self.definitions[0]

    def allInstalledDefinitions(self):
        return self.definitions

    def parmTemplates(self):
        return ()

    def minNumInputs(self):
        return 0

    def maxNumInputs(self):
        return 0

    def minNumOutputs(self):
        return 0

    def maxNumOutputs(self):
        return 0

    def childTypeCategory(self):
        return None


class _Definition:
    def __init__(
        self,
        path: Path,
        *,
        current: bool,
        preferred: bool,
        version: str = "1.0",
    ):
        self.path = path
        self.current = current
        self.preferred = preferred
        self.asset_version = version

    def libraryFilePath(self):
        return str(self.path)

    def version(self):
        return self.asset_version

    def sections(self):
        return {}

    def isCurrent(self):
        return self.current

    def isPreferred(self):
        return self.preferred


class _NativeNodeType:
    def __init__(self, name: str, path: Path, source: str = "CompiledCode"):
        self.raw_name = name
        self.path = path
        self.source_name = source

    def name(self):
        return self.raw_name

    def source(self):
        return f"nodeTypeSource.{self.source_name}"

    def sourcePath(self):
        return str(self.path) if self.source_name != "Internal" else "Internal"


class _Section:
    def __init__(self, content: bytes):
        self.content = content

    def contents(self):
        return self.content

    def size(self):
        return len(self.content)


class _SectionDefinition:
    def __init__(self, content: bytes):
        self.content = content

    def libraryFilePath(self):
        return ""

    def version(self):
        return "1.0"

    def sections(self):
        return {"Contents": _Section(self.content)}


def _assert_tamper_rejected(
    testcase: Any,
    fixture: _Fixture,
    receipt: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(receipt)
    tampered["precedence"]["packageProcessing"] = []
    tampered["receiptDigest"] = _canonical_digest({
        key: item for key, item in tampered.items() if key != "receiptDigest"
    })
    with testcase.assertRaises(PackageSearchProvenanceError):
        verify_effective_package_search(
            tampered,
            fixture.hou,
            fixture.provider,
            fixture.catalog,
            installed_root=fixture.installed,
            install_manifest=fixture.manifest,
            modules=fixture.modules,
            python_paths=fixture.python_paths,
            startup_trace=fixture.startup_trace,
        )
    malformed = copy.deepcopy(receipt)
    malformed["receiptDigest"] = _digest(b"forged")
    with testcase.assertRaises(PackageSearchProvenanceError):
        decode_effective_package_search(malformed)
    for mutation in ("package-type", "trace-order", "winner-envelope"):
        nested = copy.deepcopy(receipt)
        if mutation == "package-type":
            nested["packages"][0]["loaded"] = 1
        elif mutation == "trace-order":
            nested["packageTrace"]["events"][0]["rank"] = 9
            trace = nested["packageTrace"]
            trace["traceDigest"] = _canonical_digest({
                key: item for key, item in trace.items()
                if key != "traceDigest"
            })
        else:
            nested["operatorWinners"][0]["winner"]["unexpected"] = True
            nested["precedence"]["operatorWinnerDigest"] = _canonical_digest(
                nested["operatorWinners"],
            )
        nested["receiptDigest"] = _canonical_digest({
            key: item for key, item in nested.items()
            if key != "receiptDigest"
        })
        with testcase.assertRaises(PackageSearchProvenanceError):
            decode_effective_package_search(nested)
    invalid_manifest = copy.deepcopy(fixture.manifest)
    invalid_manifest["kind"] = "untrusted_install_manifest"
    invalid_manifest["manifestDigest"] = _canonical_digest({
        key: item for key, item in invalid_manifest.items()
        if key != "manifestDigest"
    })
    with testcase.assertRaisesRegex(
        PackageSearchProvenanceError, "manifest identity",
    ):
        collect_effective_package_search(
            fixture.hou,
            fixture.provider,
            fixture.catalog,
            installed_root=fixture.installed,
            install_manifest=invalid_manifest,
            modules=fixture.modules,
            python_paths=fixture.python_paths,
            startup_trace=fixture.startup_trace,
        )


def _assert_package_info_boundary(testcase: Any, fixture: _Fixture) -> None:
    original = fixture.hou.ui
    try:
        fixture.hou.ui = SimpleNamespace()
        headless = fixture.collect()
        testcase.assertTrue(headless["packages"][0]["loaded"])
        testcase.assertEqual(
            headless["packages"][0]["evaluatedDigest"], _canonical_digest({}),
        )
        fixture.hou.ui = SimpleNamespace(packageInfo=lambda: "[]")
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "evaluation is unbounded",
        ):
            fixture.collect()
        fixture.hou.ui = SimpleNamespace(packageInfo=lambda: "{}")
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "differs from the authoritative",
        ):
            fixture.collect()
        fixture.hou.ui = SimpleNamespace(
            packageInfo=lambda: (_ for _ in ()).throw(RuntimeError("failed")),
        )
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "unavailable or invalid",
        ):
            fixture.collect()
    finally:
        fixture.hou.ui = original


def _assert_repository_import_rejected(
    testcase: Any,
    fixture: _Fixture,
) -> None:
    outside = fixture.root / "checkout" / "hocuspocus"
    outside.mkdir(parents=True)
    source = outside / "__init__.py"
    source.write_text("# repository\n", encoding="utf-8")
    with testcase.assertRaisesRegex(
        PackageSearchProvenanceError, "imported outside",
    ):
        collect_effective_package_search(
            fixture.hou,
            fixture.provider,
            fixture.catalog,
            installed_root=fixture.installed,
            install_manifest=fixture.manifest,
            modules={"hocuspocus": SimpleNamespace(__file__=str(source))},
            python_paths=fixture.python_paths,
            startup_trace=fixture.startup_trace,
        )


def _assert_shadow_path_rejected(testcase: Any, fixture: _Fixture) -> None:
    shadow = fixture.root / "shadow"
    package = shadow / "hocuspocus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# shadow\n", encoding="utf-8")
    with testcase.assertRaisesRegex(
        PackageSearchProvenanceError, "shadows HocusPocus",
    ):
        collect_effective_package_search(
            fixture.hou,
            fixture.provider,
            fixture.catalog,
            installed_root=fixture.installed,
            install_manifest=fixture.manifest,
            modules=fixture.modules,
            python_paths=(str(shadow), *fixture.python_paths),
            startup_trace=fixture.startup_trace,
        )


def _assert_ambiguous_hda_rejected(testcase: Any, fixture: _Fixture) -> None:
    competing_path = fixture.installed / "competing.hda"
    competing_path.write_bytes(b"competing")
    competing = _Definition(competing_path, current=True, preferred=True)
    original = fixture.node_type.definitions
    fixture.node_type.definitions = (*original, competing)
    try:
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "winner is absent or ambiguous",
        ):
            fixture.collect()
    finally:
        fixture.node_type.definitions = original
    original[0].preferred = False
    competing.current = False
    fixture.node_type.definitions = (*original, competing)
    try:
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "winner is absent or ambiguous",
        ):
            fixture.collect()
    finally:
        original[0].preferred = True
        fixture.node_type.definitions = original


def _assert_unexplained_hda_rejected(testcase: Any, fixture: _Fixture) -> None:
    path = fixture.root / "manual" / "rogue.hda"
    path.parent.mkdir()
    path.write_bytes(b"rogue")
    rogue = _Definition(path, current=True, preferred=True)
    original = fixture.node_type.definitions
    fixture.node_type.definitions = (rogue,)
    try:
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "outside every effective search",
        ):
            fixture.collect()
    finally:
        fixture.node_type.definitions = original


def _assert_missing_optional_hda_ignored(
    testcase: Any,
    fixture: _Fixture,
) -> None:
    original = fixture.hou.hda.loadedFiles
    placeholder = fixture.root / "optional-placeholder.hda"
    placeholder.mkdir()
    fixture.hou.hda.loadedFiles = lambda: (
        *original(),
        str(fixture.root / "missing-optional.hda"),
        str(placeholder),
    )
    try:
        testcase.assertEqual(
            fixture.collect()["operatorWinners"][0]["winner"]["libraryLocator"],
            "hocus-install://root/rock.hda",
        )
    finally:
        fixture.hou.hda.loadedFiles = original


def _assert_directory_hda_identity(testcase: Any, fixture: _Fixture) -> None:
    library = fixture.installed / "expanded.hda"
    library.mkdir()
    (library / "Contents").write_bytes(b"expanded-hda")
    original = fixture.node_type.definitions
    fixture.node_type.definitions = (
        _Definition(library, current=True, preferred=True),
    )
    try:
        provider = LiveHoudiniCatalogProvider(
            fixture.hou,
            package_directories=(fixture.package_dir,),
            catalog_version=2,
        )
        receipt = collect_effective_package_search(
            fixture.hou,
            provider,
            provider.get_catalog(),
            installed_root=fixture.installed,
            install_manifest=fixture.manifest,
            modules=fixture.modules,
            python_paths=fixture.python_paths,
            startup_trace=fixture.startup_trace,
        )
        testcase.assertEqual(
            receipt["operatorWinners"][0]["winner"]["libraryLocator"],
            "hocus-install://root/expanded.hda",
        )
    finally:
        fixture.node_type.definitions = original


def _assert_regular_hda_digest_compatibility(
    testcase: Any,
    fixture: _Fixture,
) -> None:
    framed = (
        fixture.hda_file.name.encode("utf-8")
        + b"\0"
        + fixture.hda_file.read_bytes()
        + b"\0"
    )
    testcase.assertEqual(
        definition_content_digest(
            fixture.definition,
            "studio::rock::1.0",
        ),
        _digest(framed),
    )


def _assert_hda_library_identity_boundaries(
    testcase: Any,
    fixture: _Fixture,
) -> None:
    root = fixture.root / "hda-identity-boundaries"
    root.mkdir()
    with testcase.subTest("nested HDA reparse escape"):
        library = fixture.installed / "linked-expanded.hda"
        library.mkdir()
        (library / "Contents").write_bytes(b"stable-expanded-hda")
        outside = root / "outside"
        outside.mkdir()
        (outside / "ExternalSection").write_bytes(b"external")
        definition = _Definition(library, current=True, preferred=True)
        original = fixture.node_type.definitions
        fixture.node_type.definitions = (definition,)
        try:
            provider = LiveHoudiniCatalogProvider(
                fixture.hou,
                package_directories=(fixture.package_dir,),
                catalog_version=2,
            )
            catalog = provider.get_catalog()
            link = library / "escape"
            _create_directory_link(link, outside)
            with testcase.assertRaisesRegex(
                HdaLibraryIdentityError,
                "link or reparse point",
            ):
                hda_identity.hda_library_content_digest(library)
            with testcase.assertRaisesRegex(
                LiveCatalogExtractionError,
                "bounded stable byte identity",
            ):
                definition_content_digest(definition, "studio::rock::1.0")
            with testcase.assertRaisesRegex(
                PackageSearchProvenanceError,
                "bounded stable byte identity",
            ):
                collect_effective_package_search(
                    fixture.hou,
                    provider,
                    catalog,
                    installed_root=fixture.installed,
                    install_manifest=fixture.manifest,
                    modules=fixture.modules,
                    python_paths=fixture.python_paths,
                    startup_trace=fixture.startup_trace,
                )
        finally:
            fixture.node_type.definitions = original
    with testcase.subTest("directory HDA file-count limit"):
        library = root / "count.hda"
        library.mkdir()
        (library / "one").write_bytes(b"1")
        (library / "two").write_bytes(b"2")
        with (
            patch.object(hda_identity, "MAX_HDA_FILES", 1),
            testcase.assertRaisesRegex(
                HdaLibraryIdentityError,
                "file count exceeds",
            ),
        ):
            hda_identity.hda_library_content_digest(library)
    with testcase.subTest("directory HDA byte limits"):
        testcase.assertEqual(
            hda_identity.MAX_HDA_FILE_BYTES,
            128 * 1024 * 1024,
        )
        testcase.assertEqual(
            hda_identity.MAX_HDA_TOTAL_BYTES,
            256 * 1024 * 1024,
        )
        library = root / "bytes.hda"
        library.mkdir()
        first = library / "first"
        second = library / "second"
        first.write_bytes(b"1234")
        second.write_bytes(b"5678")
        with (
            patch.object(hda_identity, "MAX_HDA_FILE_BYTES", 3),
            testcase.assertRaisesRegex(
                HdaLibraryIdentityError,
                "file exceeds its byte limit",
            ),
        ):
            hda_identity.hda_library_content_digest(library)
        with (
            patch.object(hda_identity, "MAX_HDA_TOTAL_BYTES", 7),
            testcase.assertRaisesRegex(
                HdaLibraryIdentityError,
                "aggregate bytes exceed",
            ),
        ):
            hda_identity.hda_library_content_digest(library)
    with testcase.subTest("directory HDA framing is unambiguous"):
        first = root / "framing-a.hda"
        second = root / "framing-b.hda"
        first.mkdir()
        second.mkdir()
        (first / "a").write_bytes(b"x\0b\0y")
        (second / "a").write_bytes(b"x")
        (second / "b").write_bytes(b"y")
        testcase.assertNotEqual(
            hda_identity.hda_library_content_digest(first),
            hda_identity.hda_library_content_digest(second),
        )
    with testcase.subTest("same-inode restored-mtime mutation"):
        library = root / "same-inode.hda"
        library.write_bytes(b"first-pass")
        original = library.stat()
        original_read = hda_identity.os.read
        mutated = False

        def mutate_after_read(descriptor: int, count: int) -> bytes:
            nonlocal mutated
            chunk = original_read(descriptor, count)
            if chunk and not mutated:
                mutated = True
                with library.open("r+b") as stream:
                    stream.write(b"other-pass")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.utime(
                    library,
                    ns=(original.st_atime_ns, original.st_mtime_ns),
                )
            return chunk

        with (
            patch.object(hda_identity.os, "read", side_effect=mutate_after_read),
            testcase.assertRaisesRegex(
                HdaLibraryIdentityError,
                "changed while being read",
            ),
        ):
            hda_identity.hda_library_content_digest(library)
        testcase.assertTrue(mutated)
        testcase.assertEqual(library.stat().st_ino, original.st_ino)
        testcase.assertEqual(library.stat().st_mtime_ns, original.st_mtime_ns)
        testcase.assertEqual(library.read_bytes(), b"other-pass")
    _assert_windows_descriptor_ctime_compatibility(testcase, root)
    _assert_windows_terminal_hda_authority(testcase, root)
    with testcase.subTest("directory HDA stable file identity"):
        library = root / "unstable.hda"
        library.mkdir()
        content = library / "Contents"
        content.write_bytes(b"same-bytes")
        original_hash = hda_identity._hash_open_file

        def replace_after_read(digest: Any, record: Any) -> None:
            original_hash(digest, record)
            replacement = record.path.with_name("Replacement")
            replacement.write_bytes(record.path.read_bytes())
            os.utime(
                replacement,
                ns=(record.snapshot.mtime_ns, record.snapshot.mtime_ns),
            )
            os.replace(replacement, record.path)

        with (
            patch.object(
                hda_identity,
                "_hash_open_file",
                side_effect=replace_after_read,
            ),
            testcase.assertRaisesRegex(
                HdaLibraryIdentityError,
                "changed while it was hashed",
            ),
        ):
            hda_identity.hda_library_content_digest(library)
    _assert_observer_hda_cache_identity(testcase)


def _assert_observer_hda_cache_identity(testcase: Any) -> None:
    observer = ProductionFixtureObserver(
        SimpleNamespace(), authorized_roots=("/obj/cache",),
    )
    state = {"content": b"first"}
    section = SimpleNamespace(binaryContents=lambda: state["content"])
    definition = SimpleNamespace(
        version=lambda: "1.0", sections=lambda: {"Contents": section},
    )
    node_type = SimpleNamespace(
        nameWithCategory=lambda: "Sop/cache", definition=lambda: definition,
    )
    node = SimpleNamespace(path=lambda: "/obj/cache/node", type=lambda: node_type)
    first = observer._hda_dependency(node)[1]["digest"]
    state["content"] = b"second"
    with testcase.subTest("observer HDA cache content identity"):
        testcase.assertNotEqual(
            first, observer._hda_dependency(node)[1]["digest"],
        )


def _assert_windows_descriptor_ctime_compatibility(
    testcase: Any,
    root: Path,
) -> None:
    if os.name != "nt":
        return
    with testcase.subTest("descriptor/path ctime compatibility"):
        library = root / "windows-ctime.hda"
        library.write_bytes(b"stable-ctime-content")
        baseline = hda_identity.hda_library_content_digest(library)
        original_fstat = hda_identity.os.fstat

        def mismatched_ctime(descriptor: int) -> Any:
            value = original_fstat(descriptor)
            return SimpleNamespace(
                st_mode=value.st_mode,
                st_size=value.st_size,
                st_mtime_ns=value.st_mtime_ns,
                st_ctime_ns=value.st_ctime_ns + 1,
                st_dev=value.st_dev,
                st_ino=value.st_ino,
            )

        with patch.object(
            hda_identity.os,
            "fstat",
            side_effect=mismatched_ctime,
        ):
            testcase.assertEqual(
                hda_identity.hda_library_content_digest(library),
                baseline,
            )


def _assert_windows_terminal_hda_authority(
    testcase: Any,
    root: Path,
) -> None:
    if os.name != "nt":
        return
    with testcase.subTest("terminal native HDA identity"):
        library = root / "windows-terminal-authority.hda"
        library.write_bytes(b"first-pass")
        original = library.stat()
        original_open = hda_identity.os.open
        opened = 0
        mutated = False

        def mutate_before_terminal(path: Any, flags: int) -> int:
            nonlocal mutated, opened
            opened += 1
            if opened == 2:
                with library.open("r+b") as stream:
                    stream.write(b"other-pass")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.utime(
                    library,
                    ns=(original.st_atime_ns, original.st_mtime_ns),
                )
                mutated = True
            return original_open(path, flags)

        result = None
        with patch.object(
            hda_identity.os,
            "open",
            side_effect=mutate_before_terminal,
        ):
            try:
                result = hda_identity.hda_library_content_digest(library)
            except HdaLibraryIdentityError:
                pass
        testcase.assertTrue(mutated)
        testcase.assertGreaterEqual(opened, 2)
        testcase.assertEqual(library.stat().st_ino, original.st_ino)
        testcase.assertEqual(library.stat().st_size, original.st_size)
        testcase.assertEqual(library.stat().st_mtime_ns, original.st_mtime_ns)
        testcase.assertEqual(library.read_bytes(), b"other-pass")
        if result is not None:
            testcase.assertEqual(
                result,
                hda_identity.hda_library_content_digest(library),
            )


def _create_directory_link(link: Path, target: Path) -> None:
    if os.name != "nt":
        link.symlink_to(target, target_is_directory=True)
        return
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Could not create the nested Windows HDA junction fixture."
        )


def _assert_package_shadow_rejected(testcase: Any, fixture: _Fixture) -> None:
    shadow = fixture.package_dir / "z-shadow.json"
    shadow.write_text(json.dumps({
        "env": [{"HOCUSPOCUS_ROOT": str(fixture.installed)}],
    }), encoding="utf-8")
    original_trace = fixture.startup_trace
    fixture.startup_trace = _startup_trace(
        fixture.package_file, skipped=(shadow,),
    )
    try:
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "duplicated, or shadowed",
        ):
            fixture.collect()
    finally:
        fixture.startup_trace = original_trace
        shadow.unlink()


def _assert_native_binary_identity(testcase: Any, fixture: _Fixture) -> None:
    binary = fixture.installed / "native-test.dll"
    binary.write_bytes(b"native-winner-bytes")
    native = _NativeNodeType("studio_native", binary)
    original_native = getattr(fixture.category, "native", None)
    fixture.category.native = native
    operator = replace(
        fixture.catalog.operators[0],
        qualified_name="studio_native",
        name="studio_native",
        namespace=None,
        version=None,
        source=DefinitionSource(kind="builtin"),
    )
    catalog = replace(
        fixture.catalog,
        operators=(*fixture.catalog.operators, operator),
    )
    try:
        receipt = collect_effective_package_search(
            fixture.hou, fixture.provider, catalog,
            installed_root=fixture.installed,
            install_manifest=fixture.manifest,
            modules=fixture.modules,
            python_paths=fixture.python_paths,
            startup_trace=fixture.startup_trace,
        )
        winner = next(
            item["winner"] for item in receipt["operatorWinners"]
            if item["qualifiedName"] == "studio_native"
        )
        testcase.assertEqual(winner["kind"], "binary")
        testcase.assertEqual(winner["contentDigest"], _digest(binary.read_bytes()))
        native.source_name = "UnexplainedPlugin"
        with testcase.assertRaisesRegex(
            PackageSearchProvenanceError, "unexplained plugin source",
        ):
            collect_effective_package_search(
                fixture.hou, fixture.provider, catalog,
                installed_root=fixture.installed,
                install_manifest=fixture.manifest,
                modules=fixture.modules,
                python_paths=fixture.python_paths,
                startup_trace=fixture.startup_trace,
            )
    finally:
        if original_native is None:
            del fixture.category.native
        else:
            fixture.category.native = original_native
        binary.unlink()


def _assert_contents_bytes_are_hashed(testcase: Any) -> None:
    first = definition_content_digest(
        _SectionDefinition(b"first-bytes"), "studio::embedded::1.0",
    )
    second = definition_content_digest(
        _SectionDefinition(b"other-bytes"), "studio::embedded::1.0",
    )
    testcase.assertNotEqual(first, second)


def _assert_disabled_skipped_trace(testcase: Any, root: Path) -> None:
    loaded = (root / "base" / "loaded.json").resolve().as_posix()
    disabled = (root / "base" / "disabled.json").resolve().as_posix()
    recursive = (root / "queued" / "skipped.json").resolve().as_posix()
    source = (
        "= = = Houdini Package log = = =\n"
        f"Loading: {loaded}\nLoading: {disabled}\nLoading: {recursive}\n"
        f"Processing: {loaded}\n"
        "Loading Info:\n"
        "  Loaded Packages (1):\n"
        f"    {loaded}\n"
        "  Disabled Packages (1):\n"
        f"    {disabled}\n"
        "  Skipped Packages (1):\n"
        f"    {recursive}\n"
        "= = = = = = = = = = = = = = = =\n"
    )
    trace = load_package_startup_trace(source)
    testcase.assertEqual(len(trace["disabled"]), 1)
    testcase.assertEqual(len(trace["skipped"]), 1)
    testcase.assertEqual(trace["skipped"][0].parent.name, "queued")
    hostile = {
        "skipped_count": source.replace(
            "Skipped Packages (1):", "Skipped Packages (0):",
        ),
        "duplicate_skipped": source.replace(
            "  Skipped Packages (1):\n",
            f"  Skipped Packages (2):\n    {recursive}\n",
        ),
        "duplicate_summary": source.replace(
            "= = = = = = = = = = = = = = = =\n",
            f"  Skipped Packages (1):\n    {recursive}\n"
            "= = = = = = = = = = = = = = = =\n",
        ),
        "state_intersection": source.replace(
            f"    {recursive}\n", f"    {loaded}\n",
        ),
        "missing_explicit_skip": source.replace(
            f"  Skipped Packages (1):\n    {recursive}\n", "",
        ),
    }
    for label, candidate in hostile.items():
        with testcase.subTest(h22_skipped_trace=label):
            with testcase.assertRaises(PackageStartupTraceError):
                load_package_startup_trace(candidate)


def _assert_schema_and_build_coverage(
    testcase: Any,
    receipt: dict[str, Any],
) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    testcase.assertEqual(schema["$id"], receipt["$schema"])
    try:
        import jsonschema
    except ImportError:
        pass
    else:
        jsonschema.Draft202012Validator(schema).validate(receipt)
    support = SUPPORT.read_text(encoding="utf-8")
    testcase.assertIn("effective-package-search.json", support)
    testcase.assertIn("package_search_receipt", support)
    testcase.assertLessEqual(len(MODULE.read_text(encoding="utf-8").splitlines()), 1200)
    manifest_module = _load_install_manifest_module()
    governed = {
        item["relativePath"] for item in manifest_module.create_manifest(ROOT)["files"]
    }
    testcase.assertIn(
        "docs/schemas/effective-package-search-provenance-v1.schema.json",
        governed,
    )
    testcase.assertIn(
        "python3.11libs/hocuspocus/live/package_search_provenance.py",
        governed,
    )


def _load_install_manifest_module() -> Any:
    path = ROOT / "scripts" / "hs8_install_manifest.py"
    spec = importlib.util.spec_from_file_location("hs8_install_manifest_coverage", path)
    if spec is None or spec.loader is None:
        raise AssertionError("HS8 install-manifest helper cannot be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _startup_trace(
    package_file: Path,
    *,
    skipped: tuple[Path, ...] = (),
) -> str:
    source = package_file.resolve().as_posix()
    discovered = "".join(
        f"Loading: {item.resolve().as_posix()}\n\n" for item in skipped
    )
    skipped_summary = "".join(
        f"        {item.resolve().as_posix()}\n" for item in skipped
    )
    return (
        "= = = Houdini Package log = = =\n"
        f"Loading: {source}\n\n"
        f"{discovered}"
        f"Processing: {source}\n\n"
        "Loading Info:\n"
        "    Loaded Packages (1):\n"
        f"        {source}\n\n"
        "    Disabled Packages (0):\n\n"
        f"    Skipped Packages ({len(skipped)}):\n"
        f"{skipped_summary}\n"
        "= = = = = = = = = = = = = = = =\n"
    )


def _canonical_digest(value: Any) -> str:
    return _digest(json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8"))


__all__ = ["assert_hs8_package_search_provenance"]
