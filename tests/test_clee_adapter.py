from __future__ import annotations

import json
import unittest
from pathlib import Path

from components.person_e.adapter import load_checkpoint_support, run_fixture_backend
from components.person_e.clee import _merge_pseudo_dx_pair


ROOT = Path(__file__).resolve().parents[1]


class CLEEAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads(
            (ROOT / "components/person_e/configs/default.json").read_text(
                encoding="utf-8"
            )
        )
        self.support = load_checkpoint_support(self.config)

    def test_effective_support_is_wlw_policy_intersect_checkpoint(self) -> None:
        self.assertEqual(
            ("Histologic_Type", "Microcalcification"),
            self.support.active_DxItem_list,
        )
        self.assertEqual(
            ("Histologic_Type", "Microcalcification"),
            self.support.effective_DxItem_list,
        )
        self.assertTrue(
            self.support.supports("Histologic_Type", "Invasive Carcinoma(IC)")
        )
        self.assertTrue(self.support.supports("Microcalcification", "Present"))

    def test_multiple_dxitem_traces_merge_on_one_roi(self) -> None:
        roi = {"roi_id": "roi-1"}
        _merge_pseudo_dx_pair(
            roi,
            "Histologic_Type",
            {
                "0": {"Histologic_Type": {"assigned": "Invasive Carcinoma(IC)"}},
                "finalResult": {
                    "Histologic_Type": {"assigned": "Invasive Carcinoma(IC)"}
                },
            },
        )
        _merge_pseudo_dx_pair(
            roi,
            "Microcalcification",
            {
                "0": {"Microcalcification": {"assigned": "Present"}},
                "finalResult": {"Microcalcification": {"assigned": "Present"}},
            },
        )
        self.assertEqual(
            {"Histologic_Type", "Microcalcification"},
            set(roi["pseudo_DxPair"]["finalResult"]),
        )

    def test_fixture_backend_preserves_all_rois_across_hierarchical_chunks(self) -> None:
        payload = {
            "case_list": [
                {
                    "tissue_blocks": [
                        {
                            "stains": [
                                {
                                    "roi_list": [
                                        {"roi_id": f"roi-{idx}", "global_idx": idx}
                                        for idx in range(5)
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        result = run_fixture_backend(
            input_payload=payload,
            DxItem="Histologic_Type",
            case_label="Invasive Carcinoma(IC)",
            support=self.support,
            max_inputs_per_forward=2,
            score_cycle=[0.82, 0.55],
        )

        self.assertEqual(
            {f"roi-{idx}" for idx in range(5)},
            set(result.predictions_by_roi_id),
        )
        for idx in range(5):
            trace = result.predictions_by_roi_id[f"roi-{idx}"]
            self.assertIn("0", trace)
            self.assertIn("finalResult", trace)
            prediction = trace["finalResult"]["Histologic_Type"]
            self.assertEqual(idx % 2 == 0, prediction["assigned_as_ref"])
            if idx % 2 == 0:
                self.assertIn("1", trace)
            else:
                self.assertNotIn("1", trace)


if __name__ == "__main__":
    unittest.main()
