"""Check reference/person_d/ against the digests of a Person D native config.

    python -m components.person_d.verify_assets --config components/person_d/configs/native.example.json

Standard library only: run it after copying or downloading the reference assets,
before building or running the image.  Exits 1 when an asset is missing or differs.
The native run performs the same checks before it writes H.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Iterator, Optional

from components.person_d.assets import file_sha256, tree_sha256
from contracts.paths import resolve_person_reference_path, sibling_logical_path
from contracts.runtime import load_config


# PLIP loads with from_pretrained, so the whole repository snapshot is needed.
PLIP_FILES = (
    "config.json",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def _assets(config: dict[str, Any]) -> Iterator[tuple[str, str, str, Optional[str]]]:
    extraction, matching = config["extraction"], config["matching"]
    yield "prompts", extraction["prompts_path"], "file", extraction["prompts_sha256"]
    yield "label map", matching["label_map_path"], "file", matching["label_map_sha256"]
    plip_dir = extraction["plip"]["weight_path"].rstrip("/")
    yield "PLIP", f"{plip_dir}/pytorch_model.bin", "file", extraction["plip"]["sha256"]
    for name in PLIP_FILES:
        yield f"PLIP {name}", f"{plip_dir}/{name}", "present", None
    yield "CONCH", extraction["conch"]["checkpoint_path"], "file", extraction["conch"]["sha256"]
    if extraction["use_example_prototypes"]:
        yield "few-shot examples", extraction["example_dir"], "tree", extraction["example_tree_sha256"]


def main() -> None:
    parser = argparse.ArgumentParser(description="丁: verify reference/person_d against a native config")
    parser.add_argument("--config", required=True, help="Person D native config JSON path")
    args = parser.parse_args()
    config = load_config(args.config)

    failures = 0
    for label, raw_path, kind, expected in _assets(config):
        path = resolve_person_reference_path("person_d", raw_path)
        exists = path.is_dir() if kind == "tree" else path.is_file()
        if not exists:
            failures += 1
            print(f"MISSING   {label}: {sibling_logical_path(path)}")
            continue
        if kind == "present":
            print(f"OK        {label}: {sibling_logical_path(path)} (present)")
            continue
        if kind == "tree":
            count, actual = tree_sha256(path)
            detail = f"{count} files, tree {actual}"
        else:
            actual = file_sha256(path)
            detail = actual
        if expected is None:
            print(f"UNPINNED  {label}: {sibling_logical_path(path)} ({detail}; no digest configured)")
        elif actual == expected:
            print(f"OK        {label}: {sibling_logical_path(path)} ({detail})")
        else:
            failures += 1
            print(f"MISMATCH  {label}: {sibling_logical_path(path)} (expected {expected}, got {detail})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
