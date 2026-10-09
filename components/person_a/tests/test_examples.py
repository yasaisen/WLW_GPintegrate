from __future__ import annotations

import json
import unittest
from pathlib import Path

from components.person_a.query_generation import build_example_artifact
from components.person_a.report_decompose import build_artifact
from contracts.runtime import ContractError, validate_artifact, validate_case_list_input


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PersonAExampleTests(unittest.TestCase):
    def test_report_decompose_canonical_example(self) -> None:
        directory = ROOT / "examples/report_decompose"
        source = _json(directory / "case_list.valid.json")
        config = _json(directory / "config.example.json")
        expected = _json(directory / "D_dx_pairs.expected.json")
        validate_case_list_input(source, single_case=True)
        actual = build_artifact(source, config)
        validate_artifact(actual, "D.DxPairs")
        self.assertEqual(expected, actual)

    def test_invalid_case_list_fails(self) -> None:
        source = _json(
            ROOT / "examples/report_decompose/case_list.invalid.json"
        )
        with self.assertRaises(ContractError):
            validate_case_list_input(source, single_case=True)

    def test_query_generation_canonical_example(self) -> None:
        directory = ROOT / "examples/query_generation"
        d_artifact = _json(directory / "D_dx_pairs.valid.json")
        f_artifact = _json(directory / "F_chunks.valid.json")
        config = _json(directory / "config.example.json")
        expected = _json(directory / "G_queries.expected.json")
        validate_artifact(d_artifact, "D.DxPairs")
        validate_artifact(f_artifact, "F.Chunks")
        actual = build_example_artifact(
            d_artifact, f_artifact, config["component_version"]
        )
        validate_artifact(actual, "G.VisualAttributeQueries")
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
