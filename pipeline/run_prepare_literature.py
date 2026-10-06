"""Independent runner for the synthetic Person B example artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.paths import RUN_ROOT, resolve_run_path


DEFAULT_CONFIG = ROOT / "components/person_b/configs/example.json"
DEFAULT_OUTPUT = RUN_ROOT / "input/pipeline/A_literature.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the synthetic A.Literature contract example"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="A.Literature output below sibling run/",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Person B example config",
    )
    args = parser.parse_args()
    output = resolve_run_path(args.output)
    command = [
        sys.executable,
        "-m",
        "components.person_b.prepare_literature",
        "--output",
        str(output),
        "--config",
        str(args.config),
    ]
    print("=== components.person_b.prepare_literature ===", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    print(f"Synthetic literature artifact complete: {output}")


if __name__ == "__main__":
    main()
