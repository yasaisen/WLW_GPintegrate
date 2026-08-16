from __future__ import annotations

from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def main() -> None:
    args = cli_parser("丙: find E ROI references in a C WSI").parse_args()
    wsi = load_inputs(args.input, ["C.WSI"])["C.WSI"]
    config = load_config(args.config)
    case_id = wsi["case_id"]
    payload = wsi["payload"]

    rois = []
    for index, region in enumerate(config["demo_regions"], start=1):
        rois.append(
            {
                "roi_id": f"{case_id}-roi-{index:03d}",
                "case_id": case_id,
                "wsi_id": payload["wsi_id"],
                "image_uri": payload["image_uri"],
                "coordinate": {
                    "x": region["x"],
                    "y": region["y"],
                    "width": region["width"],
                    "height": region["height"],
                    "level": region["level"],
                },
                "resolution": {
                    "mpp": payload["mpp"],
                    "magnification": config["magnification"],
                },
            }
        )

    artifact = {
        "contract": "E.ROIs",
        "schema_version": "1.0",
        "artifact_id": f"E-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": {"rois": rois},
    }
    write_artifact(artifact, args.output, "E.ROIs")


if __name__ == "__main__":
    main()

