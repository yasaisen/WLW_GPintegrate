from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from contracts.runtime import ContractError, validate_artifact


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "integration" / "fixtures" / "input"


class ContractTests(unittest.TestCase):
    def test_canonical_inputs_validate(self) -> None:
        for filename in ["A_literature.json", "B_report.json", "C_wsi.json"]:
            artifact = json.loads((INPUTS / filename).read_text(encoding="utf-8"))
            validate_artifact(artifact)

    def test_missing_required_id_fails_at_boundary(self) -> None:
        artifact = json.loads((INPUTS / "B_report.json").read_text(encoding="utf-8"))
        broken = copy.deepcopy(artifact)
        del broken["case_id"]
        with self.assertRaisesRegex(ContractError, "case_id"):
            validate_artifact(broken)


if __name__ == "__main__":
    unittest.main()

