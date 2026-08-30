from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any

from components.person_a.reference_data import load_dx_candidates
from components.person_a.report_extraction import ReportExtractionEngine
from components.person_a.table_parsers import parse_report_tables
from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def _case_directory_name(case_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", case_id).strip("._")
    if not safe:
        raise ValueError(f"case_id cannot be represented as a directory name: {case_id!r}")
    return safe


def _reference_wsi_ids(
    observation: dict[str, Any], wsis: list[dict[str, Any]], definition: dict[str, Any]
) -> list[str]:
    explicit = observation["reference_wsi_ids"]
    if explicit:
        return explicit
    reference_types = definition.get("referenceType", [])
    if not reference_types:
        return [wsi["wsi_id"] for wsi in wsis]
    allowed = {item.upper() for item in reference_types}
    return [wsi["wsi_id"] for wsi in wsis if wsi["stain_type"].upper() in allowed]


def _metadata_case(
    case: dict[str, Any],
    sample_idx: int,
    catalog: dict[str, Any],
    strict_result_classes: bool,
) -> dict[str, Any]:
    dx_items: dict[str, dict[str, Any]] = {}
    for pair in case["dx_pairs"]:
        item_name = pair["dx_item"]
        if item_name not in catalog:
            raise ValueError(
                f"Case {case['case_id']!r} contains unsupported DxItem {item_name!r}; "
                "add it to DxStructuredCandidates_integrated.json before using it"
            )
        if item_name in dx_items:
            raise ValueError(
                f"Case {case['case_id']!r} contains duplicate DxItem {item_name!r}; "
                "the metadata-shaped contract uses one record per DxItem"
            )
        definition = catalog[item_name]
        result = pair["dx_result"]
        allowed_results = definition["DxResultCls"]
        if strict_result_classes and result not in allowed_results:
            raise ValueError(
                f"Case {case['case_id']!r} {item_name} result {result!r} is not in "
                "DxStructuredCandidates_integrated.json"
            )
        dx_items[item_name] = {
            "dx_pair_id": pair["dx_pair_id"],
            "source_report_id": pair["source_report_id"],
            "DxResultCls": result,
            "DxResultTxt": pair.get("dx_result_text", result),
            "DxResultRawTxt": pair.get("dx_result_raw_text", result),
            "referenceBlock": None,
            "referenceType": list(definition.get("referenceType", [])),
            "referenceWSI": _reference_wsi_ids(pair, case["wsis"], definition),
            "appear_reportTypes": list(definition.get("appear_reportTypes", [])),
            "optionTypes": definition["optionTypes"],
            "has_numericalData": definition["has_numericalData"],
        }

    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for wsi in case["wsis"]:
        block_id = wsi["block_id"] or "block-001"
        blocks[block_id].append(
            {
                "stain_id": wsi["wsi_id"],
                "stain_type": wsi["stain_type"],
                "filename": Path(wsi["wsi_path"]).name,
                "filepath": wsi["wsi_path"],
                "memo": "",
                "roi_num": 0,
                "roi_list": [],
            }
        )

    reports = [
        {
            "report_id": report["report_id"],
            "table_idx": report["table_idx"],
            "source": report["source"],
        }
        for report in case["reports"]
    ]
    raw_reports = list(dict.fromkeys(report["raw_text"] for report in case["reports"]))
    return {
        "sample_idx": sample_idx,
        "case_id": case["case_id"],
        "hospital": case["hospital"],
        "patient_info": {},
        "date": "",
        "source": {"reports": reports},
        "organ": "Breast",
        "report_raw_content": "\n\n".join(raw_reports),
        "structured_report": {
            "reportType": None,
            "reportSubTypes": None,
            "DxItems": dx_items,
        },
        "tissue_blocks": [
            {
                "block_id": block_id,
                "stains": sorted(stains, key=lambda item: item["stain_id"]),
                "memo": "",
            }
            for block_id, stains in sorted(blocks.items())
        ],
        "memo": "",
    }


def main() -> None:
    args = cli_parser("甲: decompose report tables into per-case D.DxPairs").parse_args()
    report_tables = load_inputs(args.input, ["B.ReportTables"])["B.ReportTables"]
    config = load_config(args.config)
    candidate_reference, candidate_provenance = load_dx_candidates(
        config["dx_candidates_path"]
    )
    catalog = candidate_reference["DxItems"]
    input_manifest = Path(args.input[0]).resolve()
    output_index = Path(args.output).resolve()

    parsed = parse_report_tables(
        report_tables["payload"]["tables"], input_manifest.parent
    )
    if not parsed.cases:
        raise ValueError("Report Decompose produced no cases containing both report and WSI data")

    extraction = ReportExtractionEngine(catalog, config.get("report_extraction"))
    index_entries = []
    used_directories: set[str] = set()
    for sample_idx, case in enumerate(parsed.cases):
        extraction.fill_case(case)
        case_id = case["case_id"]
        directory_name = _case_directory_name(case_id)
        if directory_name in used_directories:
            raise ValueError(f"Case directory collision after normalization: {case_id!r}")
        used_directories.add(directory_name)

        artifact_path = output_index.parent / "cases" / directory_name / "D_dx_pairs.json"
        artifact = {
            "contract": "D.DxPairs",
            "schema_version": "2.0",
            "artifact_id": f"D-{case_id}",
            "case_id": case_id,
            "producer": config["component_version"],
            "payload": {
                "data_mode": "inference",
                "DxItem_list": list(catalog),
                "reference_versions": {"dx_candidates": candidate_provenance},
                "case_list": [
                    _metadata_case(
                        case,
                        sample_idx,
                        catalog,
                        extraction.strict_result_classes,
                    )
                ],
            },
        }
        write_artifact(artifact, artifact_path, "D.DxPairs")
        index_entries.append(
            {
                "case_id": case_id,
                "artifact_path": str(artifact_path.relative_to(output_index.parent)),
            }
        )

    index_artifact = {
        "contract": "D.DxPairsIndex",
        "schema_version": "1.0",
        "artifact_id": f"D-index-{report_tables['artifact_id']}",
        "producer": config["component_version"],
        "payload": {
            "cases": index_entries,
            "skipped_cases": parsed.skipped_cases,
        },
    }
    write_artifact(index_artifact, output_index, "D.DxPairsIndex")
    print(
        f"Report Decompose produced {len(index_entries)} cases; "
        f"skipped {len(parsed.skipped_cases)}"
    )


if __name__ == "__main__":
    main()
