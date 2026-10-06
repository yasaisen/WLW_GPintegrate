"""Create a tiny synthetic A.Literature artifact for contract smoke tests."""

from __future__ import annotations

import argparse
from typing import Any

from contracts.runtime import load_config, write_artifact


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person B example requires an example config with component_version")
    return producer


def build_example_artifact(producer: str) -> dict[str, Any]:
    """Return synthetic content that is unrelated to any research corpus."""

    return {
        "contract": "A.Literature",
        "schema_version": "2.0",
        "artifact_id": "A-example-literature",
        "producer": producer,
        "payload": {
            "corpus": {
                "corpus_id": "example-corpus",
                "title": "Synthetic contract example",
                "source_file": "synthetic-example.txt",
                "source_path": "example://synthetic-example.txt",
                "sha256": "not-applicable-example-content",
                "source_size_bytes": 1,
                "literature_count": 1,
            },
            "literature_list": [
                {
                    "literature_id": "example-literature-001",
                    "source_idx": 0,
                    "level": 1,
                    "title_list": ["Synthetic example", None, None, None],
                    "title": "Synthetic example",
                    "href": None,
                    "sections": [
                        {
                            "section_id": "example-section-001",
                            "section_idx": 0,
                            "title": "Example",
                            "text": "Placeholder text for contract testing only.",
                        }
                    ],
                }
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Person B example: create synthetic A.Literature"
    )
    parser.add_argument("--output", required=True, help="Output A.Literature artifact")
    parser.add_argument("--config", required=True, help="Example component config")
    args = parser.parse_args()
    artifact = build_example_artifact(_producer(load_config(args.config)))
    write_artifact(artifact, args.output, "A.Literature")


if __name__ == "__main__":
    main()
