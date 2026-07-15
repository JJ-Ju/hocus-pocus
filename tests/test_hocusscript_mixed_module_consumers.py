from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from hocuspocus.hocusscript.bundle import decode_compiled_bundle
from hocuspocus.hocusscript.module_compiler import (
    compile_project_mixed_module_graph,
    compile_project_module_graph,
)
from hocuspocus.hocusscript.module_semantic import (
    compile_project_mixed_module_bundle,
    compile_project_mixed_module_semantic,
    compile_project_module_bundle,
    compile_project_module_semantic,
)
from hocuspocus.hocusscript.project import ProjectError, update_project_lock, verify_project_lock
from hocuspocus.hocusscript.resolved_modules import ModuleResolutionError
from test_hocusscript_mixed_lock_update import _publish, _roots
from test_hocusscript_module_lock_plan import PROJECT_UID, _fixture, _write_source


HELPER_SOURCE = b'''hocus 0.2;
module Helper() exports (result: node_output) {
  node helper @id("helper-node"): "sop::null" {}
  export result = helper.output[0];
}
'''

BETA_SOURCE = b'''hocus 0.2;
module Beta() exports (result: node_output) {
  node beta @id("beta-node"): "sop::null" {}
  export result = beta.output[0];
}
'''

ALPHA_SOURCE = b'''hocus 0.2;
import { Helper } from "./helper.hocus";
import { Beta } from "@beta/main.hocus";
module Alpha() exports (result: node_output) {
  use helper @id("helper-instance") = Helper();
  use beta @id("beta-instance") = Beta();
  node alpha @id("alpha-node"): "sop::null" {
    input[0] = helper.result;
  }
  export result = alpha.output[0];
}
'''

LOCAL_SOURCE = b'''hocus 0.2;
import { Alpha } from "@alpha/modules/main.hocus";
module Local() exports (result: node_output) {
  use alpha @id("alpha-instance") = Alpha();
  node local @id("local-node"): "sop::null" {
    input[0] = alpha.result;
  }
  export result = local.output[0];
}
'''

ENTRY_SOURCE = b'''hocus 0.2;
import { Local } from "local.hocus";
graph Main {
  target "/obj/main";
  category Sop;
  use local @id("local-instance") = Local();
  node out @id("output-node"): "sop::null" {
    input[0] = local.result;
  }
  output = out;
}
'''


def _consumer_fixture(base: Path) -> tuple[Path, Path, Path]:
    project, alpha, beta = _fixture(base)
    _write_source(project / "src/main.hocus", ENTRY_SOURCE)
    _write_source(project / "modules/local.hocus", LOCAL_SOURCE)
    _write_source(alpha / "modules/main.hocus", ALPHA_SOURCE)
    _write_source(alpha / "modules/helper.hocus", HELPER_SOURCE)
    _write_source(beta / "main.hocus", BETA_SOURCE)
    _publish(project, alpha, beta)
    return project, alpha, beta


def _compile_all(project: Path, alpha: Path, beta: Path):
    roots = _roots(alpha, beta)
    graph = compile_project_mixed_module_graph(project, "src/main.hocus", roots)
    semantic = compile_project_mixed_module_semantic(project, "src/main.hocus", roots)
    bundle = compile_project_mixed_module_bundle(project, "src/main.hocus", roots)
    return graph, semantic, bundle


class MixedModuleConsumerTests(unittest.TestCase):
    def test_project_and_library_with_same_uid_and_relative_path_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _fixture(Path(temporary))
            current_digest = verify_project_lock(project).lock_digest
            manifest = project / "hocus.project.toml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    'uid = "external-root-project"', 'uid = "alpha-library"', 1,
                ),
                encoding="utf-8",
            )
            update_project_lock(
                project, [], expected_lock_digest=current_digest, allow_write=True,
            )
            _write_source(
                project / "src/main.hocus",
                ENTRY_SOURCE.replace(b'"local.hocus"', b'"main.hocus"'),
            )
            _write_source(project / "modules/main.hocus", LOCAL_SOURCE)
            _write_source(alpha / "modules/main.hocus", ALPHA_SOURCE)
            _write_source(alpha / "modules/helper.hocus", HELPER_SOURCE)
            _write_source(beta / "main.hocus", BETA_SOURCE)
            _publish(project, alpha, beta)

            result = compile_project_mixed_module_graph(
                project, "src/main.hocus", _roots(alpha, beta),
            )

        modules = result.resolved_module_set["modules"]
        by_uri = {item["uri"]: item for item in modules}
        project_uri = "hocus-project://alpha-library/modules/main.hocus"
        library_uri = "hocus-module://alpha-library/modules/main.hocus"
        self.assertEqual(by_uri[project_uri]["origin"], "project")
        self.assertEqual(by_uri[library_uri]["origin"], "external_library")

    def test_graph_semantic_and_bundle_preserve_exact_external_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, alpha, beta = _consumer_fixture(Path(temporary))
            graph, semantic, bundle = _compile_all(project, alpha, beta)

        modules = {
            item["uri"]: item for item in graph.to_dict()["resolvedModuleSet"]["modules"]
        }
        local_uri = f"hocus-project://{PROJECT_UID}/modules/local.hocus"
        alpha_main_uri = "hocus-module://alpha-library/modules/main.hocus"
        alpha_helper_uri = "hocus-module://alpha-library/modules/helper.hocus"
        beta_uri = "hocus-module://beta-library/main.hocus"
        self.assertEqual(set(modules), {local_uri, alpha_main_uri, alpha_helper_uri, beta_uri})

        self.assertEqual(
            {
                key: modules[local_uri][key]
                for key in ("origin", "ownerUid", "alias", "version", "moduleManifestDigest")
            },
            {
                "origin": "project",
                "ownerUid": PROJECT_UID,
                "alias": None,
                "version": None,
                "moduleManifestDigest": None,
            },
        )
        self.assertEqual(
            {
                key: modules[alpha_main_uri][key]
                for key in ("origin", "ownerUid", "alias", "version")
            },
            {
                "origin": "external_library",
                "ownerUid": "alpha-library",
                "alias": "alpha",
                "version": "1.2.3",
            },
        )
        self.assertEqual(
            {
                key: modules[beta_uri][key]
                for key in ("origin", "ownerUid", "alias", "version")
            },
            {
                "origin": "external_library",
                "ownerUid": "beta-library",
                "alias": "beta",
                "version": "2.0.0",
            },
        )
        self.assertEqual(
            modules[alpha_main_uri]["dependencies"],
            [alpha_helper_uri, beta_uri],
        )
        for uri in (alpha_main_uri, alpha_helper_uri, beta_uri):
            self.assertIsNotNone(modules[uri]["moduleManifestDigest"])

        formatted_uris = [item.uri for item in graph.modules]
        self.assertLess(formatted_uris.index(alpha_helper_uri), formatted_uris.index(alpha_main_uri))
        self.assertLess(formatted_uris.index(beta_uri), formatted_uris.index(alpha_main_uri))
        self.assertLess(formatted_uris.index(alpha_main_uri), formatted_uris.index(local_uri))
        mapping_uris = {
            item["primarySpan"]["sourceUri"]
            for item in graph.to_dict()["expansionMap"]["mappings"]
        }
        self.assertTrue({alpha_main_uri, alpha_helper_uri, beta_uri}.issubset(mapping_uris))

        self.assertTrue(semantic.valid)
        self.assertEqual(semantic.compile_result.to_dict(), graph.to_dict())
        payload = bundle.to_dict()
        self.assertEqual(payload["resolvedModuleSet"], graph.resolved_module_set)
        self.assertEqual(decode_compiled_bundle(payload).to_dict(), payload)
        self.assertEqual(
            [(item["uri"], item["digest"]) for item in payload["dependencies"]],
            sorted(
                (item["uri"], item["sourceDigest"])
                for item in payload["resolvedModuleSet"]["modules"]
            ),
        )

    def test_all_consumer_outputs_are_relocation_stable_and_path_free(self) -> None:
        payloads = []
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory in (first, second):
                base = Path(directory)
                project, alpha, beta = _consumer_fixture(base)
                graph, semantic, bundle = _compile_all(project, alpha, beta)
                payload = {
                    "graph": graph.to_dict(),
                    "semantic": semantic.to_dict(),
                    "bundle": bundle.to_dict(),
                }
                rendered = json.dumps(payload, sort_keys=True) + repr((graph, semantic, bundle))
                for native_path in (base, project, alpha, beta):
                    self.assertNotIn(str(native_path), rendered)
                payloads.append(payload)
        self.assertEqual(payloads[0], payloads[1])

    def test_stale_external_sources_manifests_and_root_identity_fail_closed(self) -> None:
        cases = ("source", "manifest", "wrong-root")
        for mode in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                project, alpha, beta = _consumer_fixture(Path(temporary))
                roots = _roots(alpha, beta)
                if mode == "source":
                    _write_source(alpha / "modules/helper.hocus", HELPER_SOURCE + b"\n")
                elif mode == "manifest":
                    (alpha / "hocus.module.toml").write_bytes(
                        (alpha / "hocus.module.toml").read_bytes() + b"\n"
                    )
                else:
                    roots["alpha"] = beta

                with self.assertRaises((ProjectError, ModuleResolutionError)) as rejected:
                    compile_project_mixed_module_graph(project, "src/main.hocus", roots)
                self.assertIn(rejected.exception.code, {"HOCUS458", "HOCUS461", "HOCUS462"})

    def test_legacy_consumers_remain_same_project_only(self) -> None:
        for function in (
            compile_project_module_graph,
            compile_project_module_semantic,
            compile_project_module_bundle,
        ):
            with self.subTest(function=function.__name__):
                self.assertNotIn("module_roots", inspect.signature(function).parameters)

        with tempfile.TemporaryDirectory() as temporary:
            project, _alpha, _beta = _consumer_fixture(Path(temporary))
            for function in (
                compile_project_module_graph,
                compile_project_module_semantic,
                compile_project_module_bundle,
            ):
                with self.subTest(function=function.__name__), self.assertRaises(
                    (ProjectError, ModuleResolutionError)
                ):
                    function(project, "src/main.hocus")


if __name__ == "__main__":
    unittest.main()
