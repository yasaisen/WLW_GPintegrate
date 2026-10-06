from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from components.person_d.visual_filter import build_example_artifact, build_native_artifact
from contracts.metadata import iter_rois
from contracts.paths import REFERENCE_ROOT
from contracts.runtime import validate_artifact


COMPONENT = Path(__file__).resolve().parents[1]
EXAMPLES = COMPONENT / "examples"
STAGE = "visual_attributes_matching_filter"
LABEL_MAP = {
    "version": "test",
    "criteria_version": "1.2.1",
    "global_aliases": {"N/A": ["Unable to confirm"]},
    "attribute_aliases": {},
}
POSITIVE = {
    "Cellular_and_Nuclear": {
        "Cytological_Atypia": ["High-grade/Severe"],
        "Chromatin": ["Hyperchromatic"],
        "Cell_Pleomorphism": ["Moderate"],
    }
}
NEGATIVE = {"Cellular_and_Nuclear": {"Chromatin": ["Regular"], "Cell_Pleomorphism": ["Moderate"]}}


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class _FakeExtractor:
    def __init__(self, labels_by_roi: dict[str, dict]):
        self.labels_by_roi = labels_by_roi
        self.calls: list[str] = []

    def extract(self, image: Image.Image) -> dict:
        roi_id = image.info["roi_id"]
        self.calls.append(roi_id)
        consistent = self.labels_by_roi[roi_id]
        models = {
            name: {
                category: {
                    attribute: {"prediction": labels[0] if labels else "N/A", "scores": {"N/A": 0.1}}
                    for attribute, labels in attributes.items()
                }
                for category, attributes in consistent.items()
            }
            for name in ("PLIP", "CONCH")
        }
        return {"consistent": consistent, "models": models}

    def example_metadata(self) -> dict:
        return {"PLIP": {"enabled": False}, "CONCH": {"enabled": False}}


class _FakeReader:
    def __init__(self) -> None:
        self.reads: list[tuple[str, str]] = []

    def read(self, stain: dict, roi: dict) -> Image.Image:
        self.reads.append((stain["stain_id"], roi["roi_id"]))
        image = Image.new("RGB", (8, 8))
        image.info["roi_id"] = roi["roi_id"]
        return image


class NativeVisualFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = REFERENCE_ROOT / "person_d" / "template_ref"
        directory.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(temp.cleanup)
        label_map = Path(temp.name) / "criteria_label_map.json"
        label_map.write_text(json.dumps(LABEL_MAP), encoding="utf-8")
        self.config = json.loads(
            (COMPONENT / "configs/native.example.json").read_text(encoding="utf-8")
        )
        self.config["matching"]["label_map_path"] = str(label_map)
        self.e = _load("E_rois.valid.json")
        self.g = _load("G_queries.valid.json")

    def _build(self, extractor: _FakeExtractor, e=None, g=None, reader=None):
        loads: list[int] = []

        def factory() -> _FakeExtractor:
            loads.append(1)
            return extractor

        artifact = build_native_artifact(
            e or self.e,
            g or self.g,
            self.config,
            extractor_factory=factory,
            image_reader=reader or _FakeReader(),
            extraction_info={"backend": "plip+conch"},
        )
        return artifact, loads

    def test_all_rois_are_kept_and_reference_rois_are_matched(self) -> None:
        extractor = _FakeExtractor(
            {
                "case-001-case-001-he-roi-001": POSITIVE,
                "case-001-case-001-he-roi-002": NEGATIVE,
            }
        )
        reader = _FakeReader()
        artifact, loads = self._build(extractor, reader=reader)
        validate_artifact(artifact, "H.MatchedROIs")

        self.assertEqual(
            [roi["roi_id"] for _, roi in iter_rois(self.e["payload"])],
            [roi["roi_id"] for _, roi in iter_rois(artifact["payload"])],
        )
        self.assertEqual(1, len(loads))
        self.assertEqual(
            [("case-001-he", "case-001-case-001-he-roi-001"), ("case-001-he", "case-001-case-001-he-roi-002")],
            reader.reads,
        )

        decisions = {}
        for stain, roi in iter_rois(artifact["payload"]):
            self.assertEqual("interest_pattern_extraction", roi["selection_history"][0]["stage"])
            for event in roi["selection_history"][1:]:
                self.assertEqual(STAGE, event["stage"])
                key = (roi["roi_id"], event["dx_pair_id"], event.get("query_id"))
                self.assertNotIn(key, decisions)
                decisions[key] = event
        he_selected = decisions[("case-001-case-001-he-roi-001", "case-001-dx-001", "case-001-query-001")]
        self.assertEqual(("selected", "visual_attributes_match"), (he_selected["status"], he_selected["reason"]))
        he_rejected = decisions[("case-001-case-001-he-roi-002", "case-001-dx-002", "case-001-query-002")]
        self.assertEqual(("rejected", "must_condition_failed"), (he_rejected["status"], he_rejected["reason"]))
        unmapped = decisions[("case-001-case-001-he-roi-002", "case-001-dx-002", "case-001-query-003")]
        self.assertEqual(("skipped", "query_unmapped"), (unmapped["status"], unmapped["reason"]))
        er_skipped = decisions[("case-001-case-001-er-roi-001", "case-001-dx-001", None)]
        self.assertEqual(("skipped", "stain_not_in_reference_wsi"), (er_skipped["status"], er_skipped["reason"]))

        payload = artifact["payload"]
        self.assertTrue(payload["reference_versions"]["visual_attribute_extraction"]["models_loaded"])
        self.assertEqual(
            "1.2.1",
            payload["reference_versions"]["visual_matching_filter"]["label_map"]["criteria_version"],
        )

    def test_unmapped_query_is_skipped_without_loading_models(self) -> None:
        g = copy.deepcopy(self.g)
        for record in g["payload"]["case_list"][0]["structured_report"]["DxItems"].values():
            for query in record["visualAttrQueries"]:
                query["criteria_status"] = "unmapped"
                query["diagnosticCriteria"] = None
        artifact, loads = self._build(_FakeExtractor({}), g=g)
        validate_artifact(artifact, "H.MatchedROIs")
        self.assertEqual([], loads)
        reasons = {
            event["reason"]
            for _, roi in iter_rois(artifact["payload"])
            for event in roi["selection_history"][1:]
        }
        self.assertEqual({"query_unmapped", "stain_not_in_reference_wsi"}, reasons)
        self.assertFalse(
            artifact["payload"]["reference_versions"]["visual_attribute_extraction"]["models_loaded"]
        )

    def test_empty_roi_case_succeeds_without_models(self) -> None:
        e = copy.deepcopy(self.e)
        for block in e["payload"]["case_list"][0]["tissue_blocks"]:
            for stain in block["stains"]:
                stain["roi_list"], stain["roi_num"] = [], 0
        artifact, loads = self._build(_FakeExtractor({}), e=e)
        validate_artifact(artifact, "H.MatchedROIs")
        self.assertEqual([], loads)
        self.assertEqual([], list(iter_rois(artifact["payload"])))

    def test_model_disagreement_is_skipped(self) -> None:
        empty = {"Cellular_and_Nuclear": {"Chromatin": []}}
        extractor = _FakeExtractor(
            {"case-001-case-001-he-roi-001": empty, "case-001-case-001-he-roi-002": empty}
        )
        artifact, _ = self._build(extractor)
        validate_artifact(artifact, "H.MatchedROIs")
        he_events = [
            event
            for stain, roi in iter_rois(artifact["payload"])
            if stain["stain_id"] == "case-001-he"
            for event in roi["selection_history"][1:]
        ]
        self.assertEqual(
            {"insufficient_visual_evidence", "query_unmapped"},
            {event["reason"] for event in he_events},
        )
        self.assertTrue(all("query_id" in event for event in he_events))

    def test_identity_and_linkage_errors_fail(self) -> None:
        extractor = _FakeExtractor({})
        e = copy.deepcopy(self.e)
        e["case_id"] = e["payload"]["case_list"][0]["case_id"] = "case-other"
        with self.assertRaisesRegex(ValueError, "same case"):
            self._build(extractor, e=e)

        g = copy.deepcopy(self.g)
        g["payload"]["case_list"][0]["tissue_blocks"][0]["stains"].pop()
        with self.assertRaisesRegex(ValueError, "stain_id sets differ"):
            self._build(extractor, g=g)

        g = copy.deepcopy(self.g)
        record = g["payload"]["case_list"][0]["structured_report"]["DxItems"]["Histologic_Type"]
        record["visualAttrQueries"][0]["dx_pair_id"] = "case-001-dx-999"
        with self.assertRaisesRegex(ValueError, "dx_pair_id"):
            self._build(extractor, g=g)

    def test_extraction_errors_propagate(self) -> None:
        class _Broken(_FakeExtractor):
            def extract(self, image):
                raise RuntimeError("CUDA out of memory")

        with self.assertRaisesRegex(RuntimeError, "CUDA"):
            self._build(_Broken({}))


class ExampleModeTests(unittest.TestCase):
    def test_example_mode_matches_canonical_expected_output(self) -> None:
        config = json.loads((COMPONENT / "configs/example.json").read_text(encoding="utf-8"))
        artifact = build_example_artifact(
            _load("E_rois.valid.json"), _load("G_queries.valid.json"), config["component_version"]
        )
        validate_artifact(artifact, "H.MatchedROIs")
        self.assertEqual(_load("H_matches.expected.json"), artifact)


if __name__ == "__main__":
    unittest.main()
