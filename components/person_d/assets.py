"""SHA-256 checks for Person D reference assets.

Standard library only, so ``verify_assets`` can check ``reference/person_d/``
before any model framework is installed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> tuple[int, str]:
    """Return the file count and the tree hash used in ``external-assets.yaml``.

    The tree hash is the SHA-256 of the newline-joined ``<file-sha256>  <relative-posix-path>``
    lines, sorted by the case-sensitive relative path.
    """

    files = sorted((path.relative_to(root).as_posix(), path) for path in root.rglob("*") if path.is_file())
    lines = [f"{file_sha256(path)}  {relative}" for relative, path in files]
    return len(files), hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def required_digest(config: dict[str, Any], key: str, owner: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"Person D {owner} config requires {key} as a lowercase SHA-256 hex digest")
    return value


def check_digest(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")
