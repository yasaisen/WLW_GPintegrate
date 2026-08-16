"""Readable orchestration of the diagram's batch DAG."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "integration" / "fixtures" / "input"
CONFIGS = ROOT / "integration" / "configs"


def run_component(module: str, inputs: list[Path], output: Path, config: Path) -> None:
    command = [sys.executable, "-m", module]
    for input_path in inputs:
        command.extend(["--input", str(input_path)])
    command.extend(["--output", str(output), "--config", str(config)])
    print(f"\n=== {module} ===", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WLW contract-first demo DAG")
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=ROOT / "integration" / "artifacts-local",
        help="Directory for D-H and the final selected-ROI artifact I",
    )
    args = parser.parse_args()
    artifacts = args.artifacts.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    d = artifacts / "D_dx_pairs.json"
    e = artifacts / "E_rois.json"
    f = artifacts / "F_chunks.json"
    g = artifacts / "G_queries.json"
    h = artifacts / "H_matches.json"
    selected_rois = artifacts / "I_selected_rois.json"

    run_component(
        "components.person_a.report_decompose",
        [FIXTURES / "B_report.json"],
        d,
        CONFIGS / "report_decompose.json",
    )
    run_component(
        "components.person_b.knowledge_retrieval",
        [FIXTURES / "A_literature.json", d],
        f,
        CONFIGS / "knowledge_retrieval.json",
    )
    run_component(
        "components.person_a.query_generation",
        [f],
        g,
        CONFIGS / "query_generation.json",
    )
    run_component(
        "components.person_c.interest_pattern",
        [FIXTURES / "C_wsi.json"],
        e,
        CONFIGS / "interest_pattern.json",
    )
    run_component(
        "components.person_d.visual_filter",
        [e, g],
        h,
        CONFIGS / "visual_filter.json",
    )
    run_component(
        "components.person_e.clee",
        [d, h],
        selected_rois,
        CONFIGS / "clee.json",
    )
    print(f"\nPipeline complete. Final selected ROIs: {selected_rois}")


if __name__ == "__main__":
    main()
