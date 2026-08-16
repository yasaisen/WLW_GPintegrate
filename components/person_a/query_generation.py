from __future__ import annotations

from collections import defaultdict

from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def main() -> None:
    args = cli_parser("甲: generate G visual attribute queries from F chunks").parse_args()
    chunks_artifact = load_inputs(args.input, ["F.Chunks"])["F.Chunks"]
    config = load_config(args.config)
    case_id = chunks_artifact["case_id"]

    by_dx: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks_artifact["payload"]["chunks"]:
        by_dx[chunk["dx_pair_id"]].update(chunk["visual_attributes"])

    queries = []
    for index, (dx_pair_id, attributes) in enumerate(sorted(by_dx.items()), start=1):
        selected = sorted(attributes)[: config["max_attributes_per_query"]]
        queries.append(
            {
                "query_id": f"{case_id}-query-{index:03d}",
                "dx_pair_id": dx_pair_id,
                "text": "Find ROI showing: " + ", ".join(selected),
                "required_attributes": selected,
            }
        )

    artifact = {
        "contract": "G.VisualAttributeQueries",
        "schema_version": "1.0",
        "artifact_id": f"G-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {"queries": queries},
    }
    write_artifact(artifact, args.output, "G.VisualAttributeQueries")


if __name__ == "__main__":
    main()

