from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from components.person_b.prepare_literature import build_example_artifact
from contracts.paths import (
    PROJECT_ROOT,
    REFERENCE_ROOT,
    RUN_ROOT,
    resolve_component_config_path,
    resolve_person_reference_path,
    resolve_reference_path,
    resolve_run_path,
)
from contracts.runtime import ContractError, validate_artifact, validate_case_list_input


ROOT = Path(__file__).resolve().parents[1]
CASE_FIXTURE = ROOT / "integration/fixtures/input/cases.example.json"


def example_report_tables() -> dict:
    return {
        "contract": "B.ReportTables",
        "schema_version": "1.0",
        "artifact_id": "B-example",
        "payload": {
            "tables": [
                {
                    "table_idx": 0,
                    "table_type": "VGHTC2024",
                    "table_path": "run/input/example.csv",
                }
            ]
        },
    }


class ContractTests(unittest.TestCase):
    def test_reference_and_run_are_project_siblings(self) -> None:
        self.assertEqual(PROJECT_ROOT.parent / "reference", REFERENCE_ROOT)
        self.assertEqual(PROJECT_ROOT.parent / "run", RUN_ROOT)

    def test_path_boundaries_reject_cross_root_or_project_paths(self) -> None:
        self.assertEqual(
            REFERENCE_ROOT / "person_a/template_ref/example.json",
            resolve_reference_path(
                "../reference/person_a/template_ref/example.json"
            ),
        )
        self.assertEqual(
            RUN_ROOT / "output/example.json",
            resolve_run_path("../run/output/example.json"),
        )
        with self.assertRaisesRegex(ValueError, "Reference path must stay"):
            resolve_reference_path("../run/input/example.json")
        with self.assertRaisesRegex(ValueError, "person_a reference path must stay"):
            resolve_person_reference_path(
                "person_a", "../reference/person_b/template_ref/example.json"
            )
        with self.assertRaisesRegex(ValueError, "Run path must stay"):
            resolve_run_path("components/person_a/configs/example.json")
        self.assertEqual(
            PROJECT_ROOT / "components/person_a/configs/example.json",
            resolve_component_config_path(
                "components/person_a/configs/example.json"
            ),
        )
        with self.assertRaisesRegex(ValueError, "Component config must stay"):
            resolve_component_config_path("../run/input/config.json")

    def test_canonical_inputs_validate(self) -> None:
        validate_artifact(build_example_artifact("person-b/example-test"))
        validate_artifact(example_report_tables())
        validate_case_list_input(json.loads(CASE_FIXTURE.read_text(encoding="utf-8")))

    def test_case_list_rejects_structured_report_and_roi_output_fields(self) -> None:
        source = json.loads(CASE_FIXTURE.read_text(encoding="utf-8"))
        broken = copy.deepcopy(source)
        broken["case_list"][0]["structured_report"] = {}
        with self.assertRaisesRegex(ContractError, "structured_report"):
            validate_case_list_input(broken)
        broken = copy.deepcopy(source)
        broken["case_list"][0]["tissue_blocks"][0]["stains"][0]["roi_list"] = []
        with self.assertRaisesRegex(ContractError, "roi_list"):
            validate_case_list_input(broken)

    def test_missing_required_id_fails_at_boundary(self) -> None:
        artifact = example_report_tables()
        broken = copy.deepcopy(artifact)
        del broken["artifact_id"]
        with self.assertRaisesRegex(ContractError, "artifact_id"):
            validate_artifact(broken)

    def test_missing_table_path_fails_at_report_boundary(self) -> None:
        artifact = example_report_tables()
        broken = copy.deepcopy(artifact)
        del broken["payload"]["tables"][0]["table_path"]
        with self.assertRaisesRegex(ContractError, "table_path"):
            validate_artifact(broken)

    def test_text_only_literature_rejects_image_fields(self) -> None:
        artifact = build_example_artifact("person-b/example-test")
        broken = copy.deepcopy(artifact)
        broken["payload"]["literature_list"][0]["images"] = [{"img_idx": 1}]
        with self.assertRaisesRegex(ContractError, "images"):
            validate_artifact(broken)


if __name__ == "__main__":
    unittest.main()
