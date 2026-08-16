"""Small dependency-free runtime for the demo's JSON Schemas.

Production code should use a complete JSON Schema implementation or generated
Pydantic models.  This validator intentionally implements only the keywords
used by the schemas in this repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
SCHEMA_DIR = ROOT / "schemas"

CONTRACT_SCHEMAS = {
    "A.Literature": "A_literature.schema.json",
    "B.Report": "B_report.schema.json",
    "C.WSI": "C_wsi.schema.json",
    "D.DxPairs": "D_dx_pairs.schema.json",
    "E.ROIs": "E_rois.schema.json",
    "F.Chunks": "F_chunks.schema.json",
    "G.VisualAttributeQueries": "G_visual_attribute_queries.schema.json",
    "H.MatchedROIs": "H_matched_rois.schema.json",
    "I.CLEESelectedROIs": "I_clee_selected_rois.schema.json",
}


class ContractError(ValueError):
    """Raised when an artifact violates its declared contract."""


def _typename(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ContractError(f"Unsupported schema type in demo validator: {expected}")


def _validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: expected constant {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: {value!r} is not one of {schema['enum']!r}")

    expected = schema.get("type")
    if expected is not None and not _is_type(value, expected):
        raise ContractError(f"{path}: expected {expected}, got {_typename(value)}")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ContractError(f"{path}: missing required property {key!r}")
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise ContractError(f"{path}: unexpected properties {sorted(extras)!r}")
        for key, child in value.items():
            if key in properties:
                _validate(child, properties[key], f"{path}.{key}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: expected at least {schema['minItems']} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{index}]")

    if isinstance(value, str) and "minLength" in schema:
        if len(value) < schema["minLength"]:
            raise ContractError(f"{path}: string is shorter than {schema['minLength']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractError(f"{path}: {value} is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractError(f"{path}: {value} is above maximum {schema['maximum']}")


def validate_artifact(artifact: dict[str, Any], expected_contract: str | None = None) -> None:
    contract = artifact.get("contract")
    if not isinstance(contract, str):
        raise ContractError("$: missing string property 'contract'")
    if expected_contract is not None and contract != expected_contract:
        raise ContractError(f"$: expected contract {expected_contract!r}, got {contract!r}")
    try:
        schema_file = CONTRACT_SCHEMAS[contract]
    except KeyError as exc:
        raise ContractError(f"$: unknown contract {contract!r}") from exc
    schema = json.loads((SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    _validate(artifact, schema)


def load_inputs(paths: Iterable[str | Path], required_contracts: Iterable[str]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for raw_path in paths:
        path = Path(raw_path)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        validate_artifact(artifact)
        contract = artifact["contract"]
        if contract in artifacts:
            raise ContractError(f"Duplicate input contract {contract!r}")
        artifacts[contract] = artifact

    required = set(required_contracts)
    missing = required - set(artifacts)
    unexpected = set(artifacts) - required
    if missing or unexpected:
        raise ContractError(
            f"Input contract mismatch; missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )
    return artifacts


def load_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_artifact(artifact: dict[str, Any], output: str | Path, expected_contract: str) -> None:
    validate_artifact(artifact, expected_contract)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {expected_contract} -> {path}")


def cli_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="Input artifact path; repeat for a component with multiple inputs",
    )
    parser.add_argument("--output", required=True, help="Output artifact path")
    parser.add_argument("--config", required=True, help="Component config JSON path")
    return parser
