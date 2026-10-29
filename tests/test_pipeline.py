from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.metadata import iter_rois
from contracts.paths import RUN_ROOT
from contracts.runtime import validate_artifact, validate_case_list_input
from pipeline import run_pipeline


ROOT = Path(__file__).resolve().parents[1]
WORK = RUN_ROOT / "output" / "work"
FIXTURE = ROOT / "integration/fixtures/input/cases.example.json"


class ContractExamplePipelineTest(unittest.TestCase):
    def test_production_profile_uses_real_backends_without_matching_bypass(self) -> None:
        documents = {
            stage: json.loads(path.read_text(encoding="utf-8"))
            for stage, path in run_pipeline.PROFILES["production"].items()
        }

        self.assertEqual("dense", documents["knowledge_retrieval"]["mode"])
        self.assertEqual(
            "learnable_soft_prompt",
            documents["query_generation"]["backend"]["mode"],
        )
        self.assertEqual(
            "single_device",
            documents["query_generation"]["backend"]["device_map_strategy"],
        )
        self.assertIs(
            True,
            documents["query_generation"]["backend"][
                "retry_with_canonical_dx"
            ],
        )
        self.assertEqual("region_proposal", documents["interest_pattern"]["mode"])
        self.assertEqual("native", documents["visual_filter"]["mode"])
        self.assertIs(True, documents["visual_filter"]["matching"]["enable"])
        self.assertEqual("native", documents["clee"]["backend"]["mode"])

    def test_complete_example_pipeline(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        validate_case_list_input(source)
        WORK.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=WORK) as temp_dir:
            run_dir = Path(temp_dir)
            case_list = run_dir / "cases.json"
            literature = run_dir / "A_literature.json"
            artifacts = run_dir / "artifacts"
            case_list.write_text(
                json.dumps(source, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pipeline/run_prepare_literature.py"),
                    "--profile",
                    "example",
                    "--output",
                    str(literature),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pipeline/run_pipeline.py"),
                    "--profile",
                    "example",
                    "--case-list",
                    str(case_list),
                    "--literature",
                    str(literature),
                    "--artifacts",
                    str(artifacts),
                ],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            validate_artifact(
                json.loads(literature.read_text(encoding="utf-8")), "A.Literature"
            )
            case_dir = artifacts / "cases/example-case"
            filenames = {
                "D.DxPairs": "D_dx_pairs.json",
                "E.ROIs": "E_rois.json",
                "F.Chunks": "F_chunks.json",
                "G.VisualAttributeQueries": "G_queries.json",
                "H.MatchedROIs": "H_matches.json",
                "I.CLEESelectedROIs": "I_selected_rois.json",
            }
            results = {}
            for contract, filename in filenames.items():
                artifact = json.loads((case_dir / filename).read_text(encoding="utf-8"))
                validate_artifact(artifact, contract)
                self.assertEqual("example-case", artifact["case_id"])
                results[contract] = artifact

            self.assertEqual([], list(iter_rois(results["E.ROIs"]["payload"])))
            self.assertEqual([], results["F.Chunks"]["payload"]["chunks"])
            records = results["G.VisualAttributeQueries"]["payload"]["case_list"][0][
                "structured_report"
            ]["DxItems"]
            self.assertEqual(["Example_Diagnostic_Item"], list(records))
            self.assertEqual([], records["Example_Diagnostic_Item"]["visualAttrQueries"])
            self.assertEqual([], list(iter_rois(results["H.MatchedROIs"]["payload"])))
            self.assertEqual([], list(iter_rois(results["I.CLEESelectedROIs"]["payload"])))

            manifest = json.loads(
                (artifacts / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, len(manifest["completed_cases"]))
            self.assertEqual("example-case", manifest["completed_cases"][0]["case_id"])
            self.assertEqual(
                "cases/example-case/case_input.json",
                manifest["completed_cases"][0]["case_input_path"],
            )
            self.assertEqual(
                "cases/example-case/I_selected_rois.json",
                manifest["completed_cases"][0]["selected_rois_path"],
            )


if __name__ == "__main__":
    unittest.main()
