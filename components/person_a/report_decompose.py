from __future__ import annotations

from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def main() -> None:
    args = cli_parser("甲: decompose a report into D.DxPairs").parse_args()
    report = load_inputs(args.input, ["B.Report"])["B.Report"]
    config = load_config(args.config)
    case_id = report["case_id"]
    report_id = report["payload"]["report_id"]

    pairs = []
    for index, observation in enumerate(report["payload"]["observations"], start=1):
        pairs.append(
            {
                "dx_pair_id": f"{case_id}-dx-{index:03d}",
                "case_id": case_id,
                "source_report_id": report_id,
                "dx_item": observation["dx_item"],
                "dx_result": observation["dx_result"],
            }
        )

    artifact = {
        "contract": "D.DxPairs",
        "schema_version": "1.0",
        "artifact_id": f"D-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {"dx_pairs": pairs},
    }
    write_artifact(artifact, args.output, "D.DxPairs")


if __name__ == "__main__":
    main()

