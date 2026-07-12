from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import complete_source, export_network_document, format_source
from hocuspocus.hocusscript.catalog import (
    CategoryDefinition,
    DefinitionSource,
    FakeCatalogProvider,
    OperatorDefinition,
)
from test_hocusscript_exporter import _document, _provider as export_provider

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional developer dependency
    Draft202012Validator = None


def _schema(name: str) -> dict:
    return json.loads((ROOT / "docs" / "schemas" / name).read_text(encoding="utf-8"))


def _completion_provider() -> FakeCatalogProvider:
    return FakeCatalogProvider.create(
        categories=(CategoryDefinition("Sop", "SOP", "sop"),),
        operators=(
            OperatorDefinition(
                "box", "box", None, None, "Sop", (), DefinitionSource("builtin"), (), (), ()
            ),
        ),
    )


@unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
class HocusScriptEditorOutputSchemaTests(unittest.TestCase):
    def _validator(self, name: str):
        schema = _schema(name)
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)

    def test_format_output_schema_accepts_valid_and_invalid_results(self) -> None:
        validator = self._validator("document-format-source-output-v1.schema.json")
        valid = format_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; mode merge; }',
            "demo.hocus",
        ).to_dict()
        invalid = format_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; node broken: }',
            source_uri="hocus-project://demo/broken.hocus",
        ).to_dict()
        validator.validate(valid)
        validator.validate(invalid)

        extra = copy.deepcopy(valid)
        extra["unexpected"] = True
        self.assertTrue(list(validator.iter_errors(extra)))
        false_success = copy.deepcopy(valid)
        false_success["formattedSource"] = None
        self.assertTrue(list(validator.iter_errors(false_success)))
        false_failure = copy.deepcopy(invalid)
        false_failure["changed"] = True
        self.assertTrue(list(validator.iter_errors(false_failure)))

    def test_completion_output_schema_accepts_exact_editor_payload(self) -> None:
        validator = self._validator("document-complete-source-output-v1.schema.json")
        source = 'hocus 0.1; graph demo { category Sop; node result: "bo'
        payload = complete_source(
            source,
            len(source),
            _completion_provider(),
            source_uri="hocus-project://demo/main.hocus",
        ).to_dict()
        validator.validate(payload)
        self.assertEqual(payload["items"][0]["replacementSpan"]["sourceUri"], payload["sourceUri"])

        missing_span = copy.deepcopy(payload)
        del missing_span["items"][0]["replacementSpan"]["end"]
        self.assertTrue(list(validator.iter_errors(missing_span)))
        oversized = copy.deepcopy(payload)
        oversized["items"] = [copy.deepcopy(payload["items"][0]) for _ in range(201)]
        self.assertTrue(list(validator.iter_errors(oversized)))

    def test_export_output_schema_accepts_success_and_fail_closed_payloads(self) -> None:
        validator = self._validator("document-export-source-output-v1.schema.json")
        valid = export_network_document(
            _document(), graph_name="exported_geo", catalog=export_provider()
        ).to_dict()
        invalid = export_network_document({}).to_dict()
        overflowing_document = _document()
        overflowing_document["ports"] = [
            {
                "uid": f"port:asset.source-01:output:{index}",
                "kind": "opaque",
                "nodeUid": "asset.source-01",
                "direction": "output",
                "index": index,
                "metadata": {},
            }
            for index in range(600)
        ]
        bounded = export_network_document(overflowing_document).to_dict()
        validator.validate(valid)
        validator.validate(invalid)
        validator.validate(bounded)
        self.assertEqual(len(bounded["diagnostics"]), 500)
        sentinel = next(item for item in bounded["diagnostics"] if item["code"] == "HOCUS819")
        self.assertGreater(sentinel["details"]["omittedCount"], 0)
        malformed_sentinel = copy.deepcopy(bounded)
        next(
            item for item in malformed_sentinel["diagnostics"] if item["code"] == "HOCUS819"
        )["details"].pop("omittedCount")
        self.assertTrue(list(validator.iter_errors(malformed_sentinel)))

        missing_provenance = copy.deepcopy(valid)
        del missing_provenance["provenance"]["managedFields"]
        self.assertTrue(list(validator.iter_errors(missing_provenance)))
        false_success = copy.deepcopy(valid)
        false_success["source"] = None
        self.assertTrue(list(validator.iter_errors(false_success)))
        false_failure = copy.deepcopy(invalid)
        false_failure["diagnostics"] = []
        self.assertTrue(list(validator.iter_errors(false_failure)))


if __name__ == "__main__":
    unittest.main()
