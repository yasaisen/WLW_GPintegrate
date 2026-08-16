from __future__ import annotations

from collections import defaultdict

from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def main() -> None:
    args = cli_parser("戊: select the final I ROI artifact from D and H").parse_args()
    inputs = load_inputs(args.input, ["D.DxPairs", "H.MatchedROIs"])
    dx_pairs = inputs["D.DxPairs"]
    matched_rois = inputs["H.MatchedROIs"]
    config = load_config(args.config)
    case_id = dx_pairs["case_id"]
    if matched_rois["case_id"] != case_id:
        raise ValueError("D and H case_id do not match")

    matches_by_dx = defaultdict(list)
    for match in matched_rois["payload"]["matches"]:
        matches_by_dx[match["dx_pair_id"]].append(match)

    selected_rois = []
    for pair in dx_pairs["payload"]["dx_pairs"]:
        candidates = [
            match
            for match in matches_by_dx[pair["dx_pair_id"]]
            if match["score"] >= config["minimum_selection_score"]
        ]
        candidates.sort(key=lambda item: (-item["score"], item["roi_id"]))
        for rank, match in enumerate(candidates[: config["top_k_per_dx"]], start=1):
            selected_rois.append(
                {
                    "selection_id": f"{case_id}-selection-{len(selected_rois) + 1:03d}",
                    "dx_pair_id": pair["dx_pair_id"],
                    "dx_item": pair["dx_item"],
                    "dx_result": pair["dx_result"],
                    "match_id": match["match_id"],
                    "query_id": match["query_id"],
                    "roi_id": match["roi_id"],
                    "wsi_id": match["wsi_id"],
                    "image_uri": match["image_uri"],
                    "coordinate": match["coordinate"],
                    "resolution": match["resolution"],
                    "matched_attributes": match["matched_attributes"],
                    "match_score": match["score"],
                    # The real CLEE implementation replaces this deterministic mock score.
                    "clee_score": match["score"],
                    "rank": rank,
                }
            )

    artifact = {
        "contract": "I.CLEESelectedROIs",
        "schema_version": "1.0",
        "artifact_id": f"I-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {"selected_rois": selected_rois},
    }
    write_artifact(artifact, args.output, "I.CLEESelectedROIs")


if __name__ == "__main__":
    main()
