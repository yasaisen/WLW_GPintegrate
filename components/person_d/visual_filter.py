"""Contract-only example for the Person D matching boundary.

The example performs no image or visual-attribute inference.  It copies ROI
metadata from E, copies the structured report from G, and marks any supplied
ROI as skipped by this unimplemented stage.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from contracts.metadata import ensure_same_case, single_case
from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person D example requires an example config with component_version")
    return producer


def build_example_artifact(
    e_artifact: dict[str, Any], g_artifact: dict[str, Any], producer: str
) -> dict[str, Any]:
    case_id = ensure_same_case(e_artifact, g_artifact)
    e_case = deepcopy(single_case(e_artifact))
    g_case = single_case(g_artifact)
    e_case["structured_report"] = deepcopy(g_case["structured_report"])

    records = list(e_case["structured_report"]["DxItems"].values())
    for block in e_case["tissue_blocks"]:
        for stain in block["stains"]:
            for roi in stain["roi_list"]:
                roi["visualAttrs"] = {}
                roi["visualAttrs_info"] = {
                    "implemented": False,
                    "purpose": "contract smoke test",
                }
                event_records = records or [None]
                for record in event_records:
                    event: dict[str, Any] = {
                        "stage": "visual_attributes_matching_filter",
                        "owner": "person_D",
                        "artifact_contract": "H.MatchedROIs",
                        "action": "legality_evaluated",
                        "status": "skipped",
                        "selected": False,
                        "reason": "example_stub_no_evaluation",
                        "producer": producer,
                    }
                    if record is not None:
                        event["dx_pair_id"] = record["dx_pair_id"]
                    roi["selection_history"].append(event)
            stain["roi_num"] = len(stain["roi_list"])

    payload: dict[str, Any] = {
        "data_mode": "inference",
        "DxItem_list": list(g_artifact["payload"]["DxItem_list"]),
        "reference_versions": deepcopy(
            g_artifact["payload"].get("reference_versions", {})
        ),
        "case_list": [e_case],
    }
    payload["reference_versions"]["example_visual_stub"] = {
        "implemented": False,
        "purpose": "contract smoke test",
    }
    if "candidateReference" in g_artifact["payload"]:
        payload["candidateReference"] = deepcopy(
            g_artifact["payload"]["candidateReference"]
        )

    return {
        "contract": "H.MatchedROIs",
        "schema_version": "2.0",
        "artifact_id": f"H-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": payload,
    }


def main() -> None:
    args = cli_parser("Person D example: E.ROIs and G queries to H").parse_args()
    inputs = load_inputs(args.input, ["E.ROIs", "G.VisualAttributeQueries"])
    artifact = build_example_artifact(
        inputs["E.ROIs"],
        inputs["G.VisualAttributeQueries"],
        _producer(load_config(args.config)),
    )
    write_artifact(artifact, args.output, "H.MatchedROIs")


if __name__ == "__main__":
    main()
