from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python3.11libs"))

from tests.hocusscript_hs8_asset_contract_helpers import (
    assert_hs8_asset_contract_foundation,
)
from tests.hocusscript_hs8_build_helpers import assert_hs8_build_foundation
from tests.hocusscript_hs8_integration_helpers import (
    assert_hs8_integrated_qualification,
)


class HocusScriptHS8Scenarios(unittest.TestCase):
    def test_hs8_asset_contracts_reject_invalid_production_facts(self) -> None:
        assert_hs8_asset_contract_foundation(self)

    def test_hs8_build_evidence_is_deterministic_and_publish_gated(self) -> None:
        assert_hs8_build_foundation(self)

    def test_hs8_qualification_surface_and_installed_fixture_are_cohesive(self) -> None:
        assert_hs8_integrated_qualification(self)


if __name__ == "__main__":
    unittest.main()
