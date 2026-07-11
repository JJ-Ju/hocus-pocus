from __future__ import annotations

import json
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from hocuspocus.hocusscript import compile_source
from test_hocusscript_parser import VALID_SOURCE


class HocusScriptCompilerTests(unittest.TestCase):
    def test_compile_is_deterministic(self) -> None:
        first = compile_source(VALID_SOURCE, "rocks.hocus")
        second = compile_source(VALID_SOURCE, "rocks.hocus")
        self.assertEqual(first.source_digest, second.source_digest)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )

    def test_formatter_is_idempotent(self) -> None:
        first = compile_source(VALID_SOURCE, "rocks.hocus")
        assert first.formatted_source is not None
        second = compile_source(first.formatted_source, "rocks.hocus")
        self.assertTrue(second.valid, [item.to_dict() for item in second.diagnostics])
        self.assertEqual(first.formatted_source, second.formatted_source)

    def test_duplicate_symbols_and_unknown_refs_are_diagnostics(self) -> None:
        source = '''hocus 0.1;
graph demo {
  target "/obj/geo1";
  existing item = "/obj/geo1/item";
  node item: "box" {}
  node out: "null" { input[0] = missing; }
}
'''
        result = compile_source(source, "duplicate.hocus")
        codes = {item.code for item in result.diagnostics}
        self.assertFalse(result.valid)
        self.assertIn("HOCUS306", codes)
        self.assertIn("HOCUS309", codes)

    def test_reconcile_requires_ownership(self) -> None:
        result = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; mode reconcile; }',
            "reconcile.hocus",
        )
        self.assertFalse(result.valid)
        self.assertIn("HOCUS305", {item.code for item in result.diagnostics})

    def test_external_paths_stay_in_scope(self) -> None:
        result = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; existing x = "/obj/other"; }',
            "scope.hocus",
        )
        self.assertFalse(result.valid)
        self.assertIn("HOCUS311", {item.code for item in result.diagnostics})

    def test_path_traversal_is_not_treated_as_in_scope(self) -> None:
        result = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; existing x = "/obj/geo1/../other"; }',
            "traversal.hocus",
        )
        self.assertFalse(result.valid)
        self.assertIn("HOCUS310", {item.code for item in result.diagnostics})

    def test_existing_nodes_cannot_receive_flag_mutations(self) -> None:
        result = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; existing x = "/obj/geo1/x"; display = x; }',
            "existing-flag.hocus",
        )
        self.assertFalse(result.valid)
        self.assertIn("HOCUS318", {item.code for item in result.diagnostics})

    def test_preview_cannot_claim_apply_readiness(self) -> None:
        result = compile_source(VALID_SOURCE, "rocks.hocus").to_dict()
        self.assertFalse(result["readyForDocumentLowering"])
        self.assertFalse(result["readyForApply"])
        self.assertEqual(result["stage"], "structural")

    def test_invalid_unicode_is_a_diagnostic_not_a_crash(self) -> None:
        result = compile_source("\ud800", "unicode.hocus")
        self.assertFalse(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS010")

    def test_host_language_imports_are_inert_and_rejected(self) -> None:
        result = compile_source(
            'import os; hocus 0.1; graph demo { target "/obj/geo1"; }',
            "host-code.hocus",
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.diagnostics[0].code, "HOCUS204")
        package = ROOT / "python3.11libs" / "hocuspocus" / "hocusscript"
        implementation = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
        self.assertNotIn("eval(", implementation)
        self.assertNotIn("exec(", implementation)
        self.assertNotIn("import subprocess", implementation)

    def test_nonfinite_and_oversized_numbers_are_diagnostics(self) -> None:
        infinite = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; node x: "null" { value = 1e999; } }',
            "infinite.hocus",
        )
        huge_integer = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; node x: "null" { value = '
            + ("9" * 5000)
            + "; } }",
            "huge-int.hocus",
        )
        self.assertEqual(infinite.diagnostics[0].code, "HOCUS013")
        self.assertEqual(huge_integer.diagnostics[0].code, "HOCUS012")

    def test_diagnostics_are_capped_with_a_truncation_record(self) -> None:
        parms = " ".join(f"value = {index};" for index in range(20))
        result = compile_source(
            f'hocus 0.1; graph demo {{ target "/obj/geo1"; node x: "null" {{ {parms} }} }}',
            "diagnostics.hocus",
            max_diagnostics=5,
        )
        self.assertEqual(len(result.diagnostics), 5)
        self.assertEqual(result.diagnostics[-1].code, "HOCUS019")

    def test_versions_are_explicit_in_preview_payload(self) -> None:
        payload = compile_source(VALID_SOURCE, "rocks.hocus").to_dict()
        self.assertEqual(payload["compilerVersion"], "0.2.0")
        self.assertEqual(payload["graphSpecVersion"], "0.1")
        self.assertEqual(payload["graphSpec"]["$schema"], "hocuspocus://schemas/graph-spec/v0.1")
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["sourceUri"], "hocus-memory:///rocks.hocus")
        self.assertEqual(payload["sourceKind"], "memory")
        schema = json.loads((ROOT / "docs" / "schemas" / "graph-spec-v0.1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], payload["graphSpec"]["$schema"])
        self.assertTrue(set(schema["required"]).issubset(payload["graphSpec"].keys()))
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            Draft202012Validator = None
        if Draft202012Validator is not None:
            validator = Draft202012Validator(schema)
            validator.validate(payload["graphSpec"])
            only_body_span = copy.deepcopy(payload["graphSpec"])
            del only_body_span["nodes"][1]["parms"][0]["value"]["offsetMap"]
            self.assertTrue(list(validator.iter_errors(only_body_span)))

    def test_empty_ownership_and_node_type_are_rejected(self) -> None:
        result = compile_source(
            'hocus 0.1; graph demo { target "/obj/geo1"; ownership ""; node x: "" {} }',
            "empty.hocus",
        )
        codes = {item.code for item in result.diagnostics}
        self.assertIn("HOCUS319", codes)
        self.assertIn("HOCUS320", codes)


if __name__ == "__main__":
    unittest.main()
