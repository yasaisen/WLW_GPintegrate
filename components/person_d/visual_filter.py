from __future__ import annotations

from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def main() -> None:
    args = cli_parser("丁: match E ROI visual attributes against G queries").parse_args()
    inputs = load_inputs(args.input, ["E.ROIs", "G.VisualAttributeQueries"])
    rois = inputs["E.ROIs"]
    queries = inputs["G.VisualAttributeQueries"]
    config = load_config(args.config)
    case_id = rois["case_id"]
    if queries["case_id"] != case_id:
        raise ValueError("E and G case_id do not match")

    extracted = {}
    for index, roi in enumerate(rois["payload"]["rois"]):
        candidates = config["demo_attributes_by_roi_index"]
        extracted[roi["roi_id"]] = set(candidates[index % len(candidates)])

    matches = []
    for query in queries["payload"]["queries"]:
        required = set(query["required_attributes"])
        scored_rois = []
        for roi in rois["payload"]["rois"]:
            common = required & extracted[roi["roi_id"]]
            score = len(common) / len(required)
            if score >= config["minimum_score"]:
                scored_rois.append((score, sorted(common), roi))
        scored_rois.sort(key=lambda item: (-item[0], item[2]["roi_id"]))
        for score, common, roi in scored_rois[: config["top_k_per_query"]]:
            matches.append(
                {
                    "match_id": f"{query['query_id']}-{roi['roi_id']}",
                    "dx_pair_id": query["dx_pair_id"],
                    "query_id": query["query_id"],
                    "roi_id": roi["roi_id"],
                    "wsi_id": roi["wsi_id"],
                    "image_uri": roi["image_uri"],
                    "coordinate": roi["coordinate"],
                    "resolution": roi["resolution"],
                    "matched_attributes": common,
                    "score": round(score, 3),
                }
            )

    artifact = {
        "contract": "H.MatchedROIs",
        "schema_version": "1.0",
        "artifact_id": f"H-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {"matches": matches},
    }
    write_artifact(artifact, args.output, "H.MatchedROIs")


if __name__ == "__main__":
    main()
