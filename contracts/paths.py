"""Canonical paths for the sibling reference and run directories."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ROOT = PROJECT_ROOT.parent / "reference"
RUN_ROOT = PROJECT_ROOT.parent / "run"
COMPONENTS_ROOT = PROJECT_ROOT / "components"


def _resolve_under(root: Path, raw_path: str | Path, label: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"{label} must stay under {resolved_root}; got {resolved}"
        ) from exc
    return resolved


def resolve_reference_path(raw_path: str | Path) -> Path:
    """Resolve a configured asset and enforce the sibling reference boundary."""

    return _resolve_under(REFERENCE_ROOT, raw_path, "Reference path")


def resolve_person_reference_path(person: str, raw_path: str | Path) -> Path:
    """Resolve an asset below the owning reference/person_x directory."""

    if person not in {"person_a", "person_b", "person_c", "person_d", "person_e"}:
        raise ValueError(f"Unknown reference owner: {person!r}")
    return _resolve_under(
        REFERENCE_ROOT / person,
        raw_path,
        f"{person} reference path",
    )


def resolve_run_path(raw_path: str | Path) -> Path:
    """Resolve runtime data and enforce the sibling run boundary."""

    return _resolve_under(RUN_ROOT, raw_path, "Run path")


def resolve_component_config_path(raw_path: str | Path) -> Path:
    """Resolve a config and require components/person_x/configs ownership."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(COMPONENTS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(
            "Component config must stay under "
            f"{COMPONENTS_ROOT.resolve()}/person_x/configs; got {resolved}"
        ) from exc
    parts = relative.parts
    if len(parts) < 3 or not parts[0].startswith("person_") or parts[1] != "configs":
        raise ValueError(
            "Component config must stay under "
            f"{COMPONENTS_ROOT.resolve()}/person_x/configs; got {resolved}"
        )
    return resolved


def sibling_logical_path(path: str | Path) -> str:
    """Return a stable reference/... or run/... provenance path."""

    resolved = Path(path).resolve()
    sibling_root = PROJECT_ROOT.parent.resolve()
    try:
        return resolved.relative_to(sibling_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Path is outside the project sibling layout: {resolved}"
        ) from exc
