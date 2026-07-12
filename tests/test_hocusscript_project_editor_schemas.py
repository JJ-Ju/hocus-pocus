from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))
sys.path.insert(0, str(ROOT / "tests"))

from hocuspocus.core.mcp_types import ResourceRegistry, ToolRegistry
from hocuspocus.hocusscript import (
    complete_project_source,
    definition_path,
)
from hocuspocus.live.operations import LiveOperations
from test_hocusscript_module_compiler import ENTRY_SOURCE, _native_project

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional developer dependency
    Draft202012Validator = None


def _schema(name: str) -> dict:
    return json.loads((ROOT / "docs" / "schemas" / name).read_text(encoding="utf-8"))


def _assert_no_host_path(test: unittest.TestCase, payload: object, roots: tuple[Path, ...]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for root in roots:
        test.assertNotIn(str(root), encoded)
        test.assertNotIn(str(root).replace("\\", "/"), encoded)


@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class HocusScriptProjectEditorSchemaTests(unittest.TestCase):
    def _validator(self, name: str) -> Draft202012Validator:
        schema = _schema(name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def _payloads(self, root: Path) -> tuple[dict, dict]:
        _native_project(root)
        source = ENTRY_SOURCE.decode("utf-8")
        offset = source.index("Root") + 2
        completion = complete_project_source(
            root, "src/main.hocus", source, offset,
        ).to_dict()
        definition = definition_path(root, "src/main.hocus", offset).to_dict()
        return completion, definition

    def test_exact_native_payloads_validate_and_are_strictly_closed(self) -> None:
        completion_validator = self._validator("project-completion-output-v1.schema.json")
        definition_validator = self._validator("project-definition-output-v1.schema.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            completion, definition = self._payloads(root)
        completion_validator.validate(completion)
        definition_validator.validate(definition)

        self.assertEqual(
            completion["items"][0]["replacementSpan"]["sourceUri"],
            completion["sourceUri"],
        )
        target = definition["items"][0]
        self.assertEqual(target["span"]["sourceUri"], target["sourceUri"])
        self.assertTrue(target["sourceUri"].startswith("hocus-project://"))

        extra = copy.deepcopy(completion)
        extra["pins"]["nativePath"] = "C:/secret/project"
        self.assertTrue(list(completion_validator.iter_errors(extra)))
        bad_digest = copy.deepcopy(completion)
        bad_digest["pins"]["resolverPolicyDigest"] = "sha256:" + "A" * 64
        self.assertTrue(list(completion_validator.iter_errors(bad_digest)))
        bad_state = copy.deepcopy(completion)
        bad_state["subjectLockState"] = "verified"
        self.assertTrue(list(completion_validator.iter_errors(bad_state)))
        host_span = copy.deepcopy(completion)
        host_span["items"][0]["replacementSpan"]["sourceUri"] = "C:/secret/main.hocus"
        self.assertTrue(list(completion_validator.iter_errors(host_span)))

        host_target = copy.deepcopy(definition)
        host_target["items"][0]["sourceUri"] = "file:///tmp/root.hocus"
        self.assertTrue(list(definition_validator.iter_errors(host_target)))
        unexpected = copy.deepcopy(definition)
        unexpected["items"][0]["source"] = "hocus 0.2;"
        self.assertTrue(list(definition_validator.iter_errors(unexpected)))

    def test_dirty_buffer_state_and_relocation_are_host_path_free(self) -> None:
        validator = self._validator("project-completion-output-v1.schema.json")
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            roots = (Path(first), Path(second))
            payloads = []
            for root in roots:
                _native_project(root)
                payload = complete_project_source(
                    root, "modules/root.hocus", "hocus 0.", len("hocus 0."),
                ).to_dict()
                validator.validate(payload)
                self.assertEqual(payload["subjectLockState"], "modified")
                _assert_no_host_path(self, payload, roots)
                payloads.append(payload)
            self.assertEqual(payloads[0], payloads[1])

    def test_project_uri_contract_rejects_dot_segments_and_noncanonical_escapes(self) -> None:
        schemas = (
            _schema("project-completion-output-v1.schema.json"),
            _schema("project-definition-output-v1.schema.json"),
        )
        accepted = (
            "hocus-project://project/src/main.hocus",
            "hocus-project://project/modules/caf%C3%A9.hocus",
            "hocus-project://project/modules/space%20name.hocus",
        )
        rejected = (
            "hocus-project://project/./main.hocus",
            "hocus-project://project/src/../main.hocus",
            "hocus-project://project/src/%2E%2E/main.hocus",
            "hocus-project://project/src/%2Fescape.hocus",
            "hocus-project://project/src/%5Cescape.hocus",
            "hocus-project://project/src/name%3Aevil.hocus",
            "hocus-project://project/src/%41lias.hocus",
            "hocus-project://project/src/%2emain.hocus",
            "hocus-project://project/src/main%2Ehocus",
        )
        for schema in schemas:
            validator = Draft202012Validator(schema["$defs"]["projectUri"])
            for uri in accepted:
                with self.subTest(schema=schema["$id"], accepted=uri):
                    validator.validate(uri)
            for uri in rejected:
                with self.subTest(schema=schema["$id"], rejected=uri):
                    self.assertTrue(list(validator.iter_errors(uri)))

    def test_native_schemas_and_apis_are_not_registered_in_live_mcp(self) -> None:
        operations = LiveOperations.__new__(LiveOperations)
        tools = ToolRegistry()
        resources = ResourceRegistry()
        operations.register(tools, resources)

        for name in (
            "complete_path", "complete_project_source", "definition_path",
            "definition_project_source", "document.complete_project_source",
            "document.definition_path",
        ):
            self.assertIsNone(tools.get(name))
        for uri in (
            "houdini://documents/schema/project-completion-output/v1",
            "houdini://documents/schema/project-definition-output/v1",
        ):
            self.assertIsNone(resources.get(uri))

        live = tools.get("document.complete_source")
        self.assertIsNotNone(live)
        assert live is not None
        self.assertEqual(live.input_schema, {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source": {"type": "string", "maxLength": 1048576},
                "offset": {"type": "integer", "minimum": 0},
                "source_name": {"type": "string", "maxLength": 1024, "default": "<mcp-source>"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
            },
            "required": ["source", "offset"],
        })
        live_schema = _schema("document-complete-source-output-v1.schema.json")
        self.assertEqual(live_schema["$id"], "hocuspocus://schemas/document-complete-source-output/v1")
        self.assertEqual(
            set(live_schema["properties"]),
            {
                "interfaceVersion", "offsetEncoding", "sourceUri", "offset", "context",
                "catalogFingerprint", "isIncomplete", "items",
            },
        )
        self.assertNotIn("project", json.dumps(live_schema).casefold())


if __name__ == "__main__":
    unittest.main()
