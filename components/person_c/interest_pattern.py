"""Contract-only example for the Person C ROI-generation boundary.

No slide is opened and no ROI is inferred.  Every source stain is retained
with an empty ROI list.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from contracts.runtime import (
    cli_parser,
    load_case_list_input,
    load_config,
    write_artifact,
)


def _producer(config: dict[str, Any]) -> str:
    producer = config.get("component_version")
    if config.get("mode") != "example" or not isinstance(producer, str) or not producer:
        raise ValueError("Person C example requires an example config with component_version")
    return producer


def build_example_artifact(
    source: dict[str, Any], producer: str
) -> dict[str, Any]:
    case = deepcopy(source["case_list"][0])
    case_id = case["case_id"]
    for block in case["tissue_blocks"]:
        for stain in block["stains"]:
            stain["roi_num"] = 0
            stain["roi_list"] = []
    return {
        "contract": "E.ROIs",
        "schema_version": "2.0",
        "artifact_id": f"E-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": {
            "data_mode": "inference",
            "DxItem_list": list(source["DxItem_list"]),
            "reference_versions": {
                "example_stub": {"implemented": False, "purpose": "contract smoke test"}
            },
            "case_list": [case],
        },
    }


def main() -> None:
    args = cli_parser("Person C example: CaseList input to E.ROIs").parse_args()
    if len(args.input) != 1:
        raise ValueError("interest_pattern accepts exactly one CaseList input")
    source = load_case_list_input(args.input[0], single_case=True)
    artifact = build_example_artifact(source, _producer(load_config(args.config)))
    write_artifact(artifact, args.output, "E.ROIs")


if __name__ == "__main__":
    main()
