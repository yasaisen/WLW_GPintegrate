"""Contract-only example for the Person B retrieval boundary."""

from __future__ import annotations

from typing import Any

from contracts.metadata import single_case
from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person B example requires an example config with component_version")
    return producer


def build_example_artifact(
    literature: dict[str, Any], d_artifact: dict[str, Any], producer: str
) -> dict[str, Any]:
    """Return a valid empty retrieval result without ranking any text."""

    case_id = single_case(d_artifact)["case_id"]
    corpus_id = literature["payload"]["corpus"]["corpus_id"]
    return {
        "contract": "F.Chunks",
        "schema_version": "2.0",
        "artifact_id": f"F-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": {
            "corpus_id": corpus_id,
            "knowledge_base": {
                "knowledge_base_id": "example-not-built",
                "archive_path": "example://not-created",
                "archive_sha256": "not-applicable",
                "corpus_sha256": literature["payload"]["corpus"]["sha256"],
                "embedding_model_path": "example://not-configured",
                "embedding_model_sha256": "not-applicable",
                "document_count": 1,
                "max_tokens": 1,
                "query_max_tokens": 1,
                "retrieval_mode": "sparse",
                "top_k": 1,
                "candidate_k": 1,
                "hybrid_weights": {"dense": 0.0, "sparse": 1.0},
            },
            "chunks": [],
        },
    }


def main() -> None:
    args = cli_parser("Person B example: A.Literature and D.DxPairs to F").parse_args()
    inputs = load_inputs(args.input, ["A.Literature", "D.DxPairs"])
    artifact = build_example_artifact(
        inputs["A.Literature"],
        inputs["D.DxPairs"],
        _producer(load_config(args.config)),
    )
    write_artifact(artifact, args.output, "F.Chunks")


if __name__ == "__main__":
    main()
