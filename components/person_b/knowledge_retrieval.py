from __future__ import annotations

from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def main() -> None:
    args = cli_parser("乙: retrieve F literature chunks for D diagnostic pairs").parse_args()
    inputs = load_inputs(args.input, ["A.Literature", "D.DxPairs"])
    literature = inputs["A.Literature"]
    dx_pairs = inputs["D.DxPairs"]
    config = load_config(args.config)
    case_id = dx_pairs["case_id"]

    chunks = []
    chunk_index = 1
    for pair in dx_pairs["payload"]["dx_pairs"]:
        haystack = f"{pair['dx_item']} {pair['dx_result']}".lower()
        ranked = []
        for document in literature["payload"]["documents"]:
            hits = sum(keyword.lower() in haystack for keyword in document["keywords"])
            score = min(1.0, config["base_score"] + hits * config["score_per_keyword"])
            ranked.append((score, document))
        ranked.sort(key=lambda item: (-item[0], item[1]["literature_id"]))
        for score, document in ranked[: config["top_k"]]:
            chunks.append(
                {
                    "chunk_id": f"{case_id}-chunk-{chunk_index:03d}",
                    "dx_pair_id": pair["dx_pair_id"],
                    "literature_id": document["literature_id"],
                    "text": document["text"],
                    "visual_attributes": document["visual_attributes"],
                    "relevance_score": round(score, 3),
                }
            )
            chunk_index += 1

    artifact = {
        "contract": "F.Chunks",
        "schema_version": "1.0",
        "artifact_id": f"F-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {"chunks": chunks},
    }
    write_artifact(artifact, args.output, "F.Chunks")


if __name__ == "__main__":
    main()

