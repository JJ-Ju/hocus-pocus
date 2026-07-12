from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import ProjectContext, compile_source, update_project_lock
from hocuspocus.hocusscript.module_compiler import compile_project_module_graph
from hocuspocus.hocusscript.resolved_modules import (
    ModuleResolutionError, module_interface_digest, module_source_digest,
    module_transitive_digest,
)
from test_hocusscript_project_v3 import _manifest, _project


LEAF_SOURCE = b'''hocus 0.2;
module Leaf() exports (result: node_output) {
  node leaf @id("leaf-node"): "box" {}
  export result = leaf.output[0];
}
'''

ROOT_SOURCE = b'''hocus 0.2;
import { Leaf } from "./leaf.hocus";
module Root() exports (result: node_output) {
  use leaf @id("leaf-instance") = Leaf();
  export result = leaf.result;
}
'''

ENTRY_SOURCE = b'''hocus 0.2;
import { Root } from "../modules/root.hocus";
graph Main {
  target "/obj/main";
  use root @id("root-instance") = Root();
  node out: "null" { input[0] = root.result; }
  output = out;
}
'''


def _record(uri: str, path: str, source: bytes, interface: dict, dependencies=(), child_digests=None):
    source_digest = module_source_digest(source)
    interface_digest = module_interface_digest(interface)
    transitive_digest = module_transitive_digest(
        uri=uri, source_digest=source_digest, interface_digest=interface_digest,
        dependencies=((child, (child_digests or {})[child]) for child in dependencies),
    )
    return {
        "moduleUri": uri,
        "projectUid": "local-project",
        "libraryUid": None,
        "libraryVersion": None,
        "moduleManifestDigest": None,
        "languageVersion": "0.2",
        "sourcePath": path,
        "contentDigest": source_digest,
        "interfaceDigest": interface_digest,
        "transitiveDigest": transitive_digest,
        "dependencies": list(dependencies),
        "externalAlias": None,
    }


def _native_project(root: Path) -> None:
    _project(root, manifest=_manifest(module_directories='["modules"]'))
    (root / "src" / "main.hocus").write_bytes(ENTRY_SOURCE)
    (root / "modules" / "leaf.hocus").write_bytes(LEAF_SOURCE)
    (root / "modules" / "root.hocus").write_bytes(ROOT_SOURCE)
    update_project_lock(root, [], allow_write=True)
    leaf_uri = "hocus-project://local-project/modules/leaf.hocus"
    root_uri = "hocus-project://local-project/modules/root.hocus"
    leaf = _record(
        leaf_uri, "modules/leaf.hocus", LEAF_SOURCE,
        {"schemaVersion": 1, "moduleName": "Leaf", "parameters": [],
         "exports": [{"name": "result", "type": "node_output"}]},
    )
    root_record = _record(
        root_uri, "modules/root.hocus", ROOT_SOURCE,
        {"schemaVersion": 1, "moduleName": "Root", "parameters": [],
         "exports": [{"name": "result", "type": "node_output"}]},
        (leaf_uri,), {leaf_uri: leaf["transitiveDigest"]},
    )
    lock_path = root / "pins" / "hocus.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["modules"] = [leaf, root_record]
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )


class HocusScriptModuleCompilerTests(unittest.TestCase):
    def test_native_project_compile_is_deterministic_read_only_and_inspectable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _native_project(root)
            before = {path.relative_to(root).as_posix(): path.read_bytes()
                      for path in root.rglob("*") if path.is_file()}
            first = compile_project_module_graph(root, "src/main.hocus")
            second = compile_project_module_graph(root, "src/main.hocus")
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertEqual(first.compile_digest, second.compile_digest)
            context = ProjectContext.load(root)
            self.assertEqual(first.catalog_content_digest, context.catalog_content_digest)
            self.assertEqual(first.catalog_fingerprint, context.catalog_fingerprint)
            self.assertEqual(first.to_dict()["catalogContentDigest"], context.catalog_content_digest)
            self.assertEqual(first.to_dict()["catalogFingerprint"], context.catalog_fingerprint)
            self.assertEqual([item.uri.rsplit("/", 1)[-1] for item in first.modules],
                             ["leaf.hocus", "root.hocus"])
            self.assertEqual(first.graph_spec.graph_spec_version, "0.3")
            self.assertEqual(first.graph_spec.expansion_map.to_dict(), first.to_dict()["expansionMap"])
            self.assertEqual(first.diagnostics, ())
            self.assertTrue(first.to_dict()["readyForSemanticResolution"])
            self.assertFalse(first.to_dict()["readyForDocumentLowering"])
            self.assertNotIn(str(root), first.to_json(pretty=True))
            with self.assertRaises(ModuleResolutionError):
                compile_project_module_graph(root, "src/main.hocus", cancelled=lambda: True)
            after = {path.relative_to(root).as_posix(): path.read_bytes()
                     for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_verified_empty_closure_compiles_and_compile_source_stays_gated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _project(root, manifest=_manifest(module_directories='["modules"]'))
            (root / "src" / "main.hocus").write_bytes(b'hocus 0.2; graph Main { target "/obj/main"; }')
            update_project_lock(root, [], allow_write=True)
            compiled = compile_project_module_graph(root, "src/main.hocus")
            self.assertEqual(compiled.modules, ())
            self.assertEqual(compiled.graph_spec.graph_spec_version, "0.3")
        result = compile_source('hocus 0.2; graph Main { target "/obj/main"; }', "main.hocus")
        self.assertFalse(result.valid)
        self.assertIn("HOCUS102", {item.code for item in result.diagnostics})


if __name__ == "__main__":
    unittest.main()
