from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from components.person_a.learnable_query_generator import (
    CONDITION_LABELS,
    LearnableQueryGenerationError,
    parse_strict_json_object,
    validate_generated_attributes,
)
from components.person_a.query_generation import generate_artifact
from contracts.metadata import dx_items
from contracts.paths import REFERENCE_ROOT
from contracts.runtime import validate_artifact


PERSON_A_REFERENCE = REFERENCE_ROOT / "person_a/template_ref"


class FakeLearnableGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.provenance = {
            "backend": "learnable_soft_prompt",
            "model_name": "google/gemma-3-1b-it",
            "model_revision": None,
            "model_integrity": {
                "model_id": "google/gemma-3-1b-it",
                "model_revision": "synthetic-revision",
                "tree_sha256": "a" * 64,
                "integrity_verified": True,
            },
            "checkpoint_name": "soft_prompt_condition_best.pt",
            "checkpoint_sha256": "abc123",
            "visual_attribute_template": {
                "source_name": "visual_attribute_template.json",
                "sha256": "def456",
            },
            "required_chunk_count": 3,
        }

    def generate(self, dx_text: str, chunks: list[dict]) -> dict:
        self.calls.append((dx_text, [chunk["chunk_id"] for chunk in chunks]))
        return {
            "Cellular_and_Nuclear": {
                "Cell_Pleomorphism": {
                    "Monomorphic": "Must_True",
                    "Pleomorphic": "Not_Mentioned",
                },
                "Polarity": {
                    "Maintained": "High_Possibly_True",
                    "Lost": "Must_False",
                },
            }
        }


def _d_artifact() -> dict:
    return {
        "contract": "D.DxPairs",
        "schema_version": "2.0",
        "artifact_id": "D-case-001",
        "case_id": "case-001",
        "producer": "test",
        "payload": {
            "data_mode": "inference",
            "DxItem_list": ["Histologic_Type"],
            "reference_versions": {},
            "case_list": [
                {
                    "sample_idx": 0,
                    "case_id": "case-001",
                    "hospital": "TEST",
                    "patient_info": {},
                    "date": "",
                    "source": {},
                    "organ": "Breast",
                    "report_raw_content": "Deidentified report",
                    "structured_report": {
                        "reportType": None,
                        "reportSubTypes": None,
                        "DxItems": {
                            "Histologic_Type": {
                                "dx_pair_id": "case-001-dx-001",
                                "source_report_id": "report-001",
                                "DxResultCls": "ADH",
                                "DxResultTxt": "Atypical ductal hyperplasia",
                                "DxResultRawTxt": "Focal atypical ductal hyperplasia",
                                "referenceBlock": None,
                                "referenceType": ["HE"],
                                "referenceWSI": ["case-001-he"],
                                "appear_reportTypes": ["Pathology"],
                                "optionTypes": "single_choice",
                                "has_numericalData": False,
                            }
                        },
                    },
                    "tissue_blocks": [
                        {
                            "block_id": "A",
                            "memo": "",
                            "stains": [
                                {
                                    "stain_id": "case-001-he",
                                    "stain_type": "HE",
                                    "filename": "case-001-he.svs",
                                    "filepath": "/data/case-001-he.svs",
                                    "memo": "",
                                    "roi_num": 0,
                                    "roi_list": [],
                                }
                            ],
                        }
                    ],
                    "memo": "",
                }
            ],
        },
    }


def _f_artifact(count: int = 3) -> dict:
    chunks = []
    for index in range(count):
        chunks.append(
            {
                "chunk_id": f"case-001-chunk-{index + 1:03d}",
                "dx_pair_id": "case-001-dx-001",
                "literature_id": "literature-001",
                "section_id": f"section-{index + 1:03d}",
                "source_idx": 0,
                "section_idx": index,
                "title_list": ["Breast", "ADH", None, None],
                "literature_title": "Deidentified reference",
                "section_title": "Histopathology",
                "source_href": None,
                "text": f"Reference evidence {index + 1}",
                "retrieval_rank": index + 1,
                "relevance_score": 1.0,
            }
        )
    return {
        "contract": "F.Chunks",
        "schema_version": "2.0",
        "artifact_id": "F-case-001",
        "case_id": "case-001",
        "producer": "test",
        "payload": {"corpus_id": "test-corpus", "chunks": chunks},
    }


def _write_references(root: Path) -> dict:
    template = {
        "version": "1.2.1",
        "type": "visualAttributeTemplate",
        "conditionLabels": sorted(CONDITION_LABELS),
        "visualAttrs": {
            "Cellular_and_Nuclear": {
                "Cell_Pleomorphism": {
                    "type": "nominal",
                    "options": ["Monomorphic", "Pleomorphic"],
                    "normal": ["Monomorphic"],
                },
                "Polarity": {
                    "type": "ordinal",
                    "options": ["Maintained", "Lost"],
                    "normal": ["Maintained"],
                },
            }
        }
    }
    mapping = {
        "Histologic_Type_mappingTable": {
            "ADH": {
                "DxResult": "Atypical ductal hyperplasia",
                "typeLevel_idx": 0,
            }
        }
    }
    paths = {
        "visual_attribute_template_path": root / "visual_attribute_template.json",
        "histologic_mapping_path": root / "mapping.json",
    }
    paths["visual_attribute_template_path"].write_text(
        json.dumps(template), encoding="utf-8"
    )
    paths["histologic_mapping_path"].write_text(
        json.dumps(mapping), encoding="utf-8"
    )
    return {key: str(value) for key, value in paths.items()}


class LearnableQueryGenerationTest(unittest.TestCase):
    def test_condition_reference_backend_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {"mode": "reference"},
            }
            with self.assertRaisesRegex(
                ValueError, "no condition-reference fallback"
            ):
                generate_artifact(_d_artifact(), _f_artifact(count=1), config)

    def test_learnable_backend_produces_valid_g_and_uses_three_chunks(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {
                    "mode": "learnable_soft_prompt",
                    "required_chunk_count": 3,
                },
            }
            generator = FakeLearnableGenerator()
            chunks = _f_artifact(count=5)
            chunks["payload"]["chunks"].reverse()
            artifact = generate_artifact(
                _d_artifact(), chunks, config, generator=generator
            )

        validate_artifact(artifact, "G.VisualAttributeQueries")
        self.assertEqual(
            [
                (
                    "Focal atypical ductal hyperplasia",
                    [
                        "case-001-chunk-001",
                        "case-001-chunk-002",
                        "case-001-chunk-003",
                    ],
                )
            ],
            generator.calls,
        )
        query = dx_items(artifact["payload"])["Histologic_Type"][
            "visualAttrQueries"
        ][0]
        conditions = query["diagnosticCriteria"]["visualAttrs"][
            "Cellular_and_Nuclear"
        ]
        self.assertEqual(
            {"Monomorphic": "Must_True", "Pleomorphic": "Not_Mentioned"},
            conditions["Cell_Pleomorphism"]["conditions"],
        )
        self.assertEqual(
            {"Maintained": "High_Possibly_True", "Lost": "Must_False"},
            conditions["Polarity"]["conditions"],
        )
        self.assertEqual(
            "abc123",
            artifact["payload"]["reference_versions"]
            ["learnable_query_generation"]["checkpoint_sha256"],
        )
        selection = artifact["payload"]["reference_versions"][
            "learnable_query_generation"
        ]
        self.assertEqual("model_generation_only", selection["condition_source"])
        self.assertEqual(generator.provenance["model_integrity"], selection["model_integrity"])
        self.assertEqual(
            "ascending_retrieval_rank_top_n",
            selection["chunk_selection_rule"],
        )
        self.assertEqual(
            [
                {"chunk_id": "case-001-chunk-001", "retrieval_rank": 1},
                {"chunk_id": "case-001-chunk-002", "retrieval_rank": 2},
                {"chunk_id": "case-001-chunk-003", "retrieval_rank": 3},
            ],
            selection["selected_chunks_by_dx_pair"]["case-001-dx-001"],
        )

    def test_learnable_backend_retries_invalid_output_with_canonical_dx(self) -> None:
        class RecoveringGenerator(FakeLearnableGenerator):
            def __init__(self) -> None:
                super().__init__()
                self.last_generation_diagnostics = {}

            def generate(self, dx_text: str, chunks: list[dict]) -> dict:
                self.calls.append(
                    (dx_text, [chunk["chunk_id"] for chunk in chunks])
                )
                if dx_text == "Focal atypical ductal hyperplasia":
                    self.last_generation_diagnostics = {
                        "response_sha256": "1" * 64,
                        "response_chars": 4096,
                        "generated_tokens": 768,
                    }
                    raise LearnableQueryGenerationError(
                        "Model response is not strict JSON; response context='omitted'"
                    )
                self.last_generation_diagnostics = {
                    "response_sha256": "2" * 64,
                    "response_chars": 2048,
                    "generated_tokens": 512,
                }
                return {
                    "Cellular_and_Nuclear": {
                        "Cell_Pleomorphism": {
                            "Monomorphic": "Must_True",
                            "Pleomorphic": "Not_Mentioned",
                        },
                        "Polarity": {
                            "Maintained": "High_Possibly_True",
                            "Lost": "Must_False",
                        },
                    }
                }

        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {
                    "mode": "learnable_soft_prompt",
                    "required_chunk_count": 3,
                    "retry_with_canonical_dx": True,
                },
            }
            generator = RecoveringGenerator()
            artifact = generate_artifact(
                _d_artifact(), _f_artifact(), config, generator=generator
            )

        validate_artifact(artifact, "G.VisualAttributeQueries")
        self.assertEqual(
            [
                "Focal atypical ductal hyperplasia",
                "Atypical ductal hyperplasia",
            ],
            [call[0] for call in generator.calls],
        )
        provenance = artifact["payload"]["reference_versions"][
            "learnable_query_generation"
        ]
        self.assertTrue(provenance["canonical_dx_retry_enabled"])
        self.assertEqual(
            ["rejected", "accepted"],
            [attempt["status"] for attempt in provenance["generation_attempts"]],
        )
        self.assertEqual(
            "canonical_mapped_dx",
            provenance["generation_attempts"][1]["input_strategy"],
        )
        self.assertNotIn(
            "response context",
            provenance["generation_attempts"][0]["error"],
        )

    def test_learnable_backend_fails_when_f_has_fewer_than_three_chunks(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {
                    "mode": "learnable_soft_prompt",
                    "required_chunk_count": 3,
                },
            }
            with self.assertRaisesRegex(ValueError, "requires 3"):
                generate_artifact(
                    _d_artifact(),
                    _f_artifact(count=1),
                    config,
                    generator=FakeLearnableGenerator(),
                )

    def test_f_rejects_duplicate_rank_chunk_id_and_foreign_dx_pair(self) -> None:
        with tempfile.TemporaryDirectory(dir=PERSON_A_REFERENCE) as temp_dir:
            config = {
                "component_version": "person-a/query-generation:0.7.0",
                "asset_integrity": "record_only",
                **_write_references(Path(temp_dir)),
                "backend": {
                    "mode": "learnable_soft_prompt",
                    "required_chunk_count": 3,
                },
            }

            duplicate_rank = _f_artifact()
            duplicate_rank["payload"]["chunks"][1]["retrieval_rank"] = 1
            with self.assertRaisesRegex(ValueError, "duplicate retrieval_rank"):
                generate_artifact(_d_artifact(), duplicate_rank, config)

            duplicate_id = _f_artifact()
            duplicate_id["payload"]["chunks"][1]["chunk_id"] = (
                duplicate_id["payload"]["chunks"][0]["chunk_id"]
            )
            with self.assertRaisesRegex(ValueError, "duplicate chunk_id"):
                generate_artifact(_d_artifact(), duplicate_id, config)

            foreign = _f_artifact()
            foreign["payload"]["chunks"][0]["dx_pair_id"] = "foreign-dx"
            with self.assertRaisesRegex(ValueError, "absent from D"):
                generate_artifact(_d_artifact(), foreign, config)

    def test_template_based_strict_json_validation(self) -> None:
        attributes = {
            "Category": {
                "Feature": {
                    "Present": "Must_True",
                    "Absent": "Not_Mentioned",
                },
                "Other": {"Seen": "Low_Possibly_True"},
            }
        }
        template = json.loads(json.dumps(attributes))
        allowed = {
            path: set(CONDITION_LABELS)
            for path in (
                "Category.Feature.Present",
                "Category.Feature.Absent",
                "Category.Other.Seen",
            )
        }
        generated = parse_strict_json_object(json.dumps(attributes))
        validate_generated_attributes(generated, template, allowed)
        self.assertEqual(
            {
                "Must_True",
                "Must_False",
                "High_Possibly_True",
                "Low_Possibly_True",
                "Negligible",
                "Not_Mentioned",
            },
            allowed["Category.Feature.Present"],
        )
        with self.assertRaises(LearnableQueryGenerationError):
            parse_strict_json_object("```json\n{}\n```")

        invalid = json.loads(json.dumps(attributes))
        invalid["Category"]["Feature"]["Present"] = "Sometimes"
        with self.assertRaises(LearnableQueryGenerationError):
            validate_generated_attributes(invalid, template, allowed)


if __name__ == "__main__":
    unittest.main()
