from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from components.person_a.reference_data import (
    load_histologic_mapping,
    load_visual_references,
)
from contracts.metadata import dx_items, ensure_same_case
from contracts.runtime import cli_parser, load_config, load_inputs, write_artifact


def _merge_learned_attributes(
    criteria: dict[str, Any],
    generated: dict[str, Any],
    backend_config: dict[str, Any],
) -> dict[str, Any]:
    """Translate generated values into the condition format consumed by Person D.

    The Nano5 target contains selected values (or ``Not_Mentioned``), while G's
    diagnostic criteria contains one condition for every controlled-vocabulary
    option.  This conversion is explicit and configurable instead of silently
    inventing fields in G.
    """

    merged = deepcopy(criteria)
    visual_attrs = merged.get("visualAttrs")
    if not isinstance(visual_attrs, dict):
        raise ValueError("Mapped diagnosticCriteria has no visualAttrs object")
    expected = {
        (category, feature)
        for category, features in visual_attrs.items()
        for feature in features
    }
    actual = {
        (category, feature)
        for category, features in generated.items()
        if isinstance(features, dict)
        for feature in features
    }
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            "Learned Attribute keys do not match G diagnostic criteria; "
            f"missing={missing}, unexpected={unexpected}"
        )

    merge_mode = str(backend_config.get("condition_merge_mode", "replace"))
    if merge_mode not in {"replace", "overlay"}:
        raise ValueError("condition_merge_mode must be replace or overlay")
    selected_condition = str(
        backend_config.get("selected_value_condition", "Must_True")
    )
    unselected_condition = str(
        backend_config.get("unselected_value_condition", "Not_Mentioned")
    )

    for category, features in visual_attrs.items():
        generated_features = generated.get(category)
        if not isinstance(generated_features, dict):
            raise ValueError(f"Generated Attribute category {category!r} is invalid")
        for feature, definition in features.items():
            if not isinstance(definition, dict):
                raise ValueError(
                    f"G visual attribute {category}.{feature} is not an object"
                )
            options = definition.get("options")
            conditions = definition.get("conditions")
            if not isinstance(options, list) or not isinstance(conditions, dict):
                raise ValueError(
                    f"G visual attribute {category}.{feature} lacks options/conditions"
                )
            value = generated_features[feature]
            if value == "Not_Mentioned":
                selected: list[str] = []
            elif isinstance(value, list) and value and all(
                isinstance(item, str) for item in value
            ):
                selected = value
            else:
                raise ValueError(
                    f"Generated {category}.{feature} must be Not_Mentioned "
                    "or a non-empty string list"
                )
            illegal = sorted(set(selected) - set(options))
            if illegal:
                raise ValueError(
                    f"Generated {category}.{feature} values are not present in "
                    f"candidate options: {illegal}"
                )
            if merge_mode == "replace":
                definition["conditions"] = {
                    option: unselected_condition for option in options
                }
                conditions = definition["conditions"]
            for option in selected:
                conditions[option] = selected_condition
    return merged


def _learnable_generator(backend_config: dict[str, Any]) -> Any:
    from components.person_a.learnable_query_generator import (
        LearnableSoftPromptGenerator,
    )

    return LearnableSoftPromptGenerator(backend_config)


def build_example_artifact(
    d_artifact: dict[str, Any],
    f_artifact: dict[str, Any],
    producer: str,
) -> dict[str, Any]:
    """Emit deterministic empty queries for the public contract smoke test."""

    case_id = ensure_same_case(d_artifact, f_artifact)
    payload = deepcopy(d_artifact["payload"])
    for record in payload["case_list"][0]["structured_report"]["DxItems"].values():
        record["visualAttrQueries"] = []
    payload.setdefault("reference_versions", {})["example_query_stub"] = {
        "implemented": False,
        "purpose": "contract smoke test",
    }
    return {
        "contract": "G.VisualAttributeQueries",
        "schema_version": "2.0",
        "artifact_id": f"G-example-{case_id}",
        "case_id": case_id,
        "producer": producer,
        "payload": payload,
    }


def generate_artifact(
    dx_artifact: dict[str, Any],
    chunks_artifact: dict[str, Any],
    config: dict[str, Any],
    generator: Any | None = None,
) -> dict[str, Any]:
    case_id = ensure_same_case(dx_artifact, chunks_artifact)
    payload = deepcopy(dx_artifact["payload"])

    mapping, mapping_provenance = load_histologic_mapping(
        config["histologic_mapping_path"]
    )
    candidate_document, type_levels, visual_provenance = load_visual_references(
        config["candidate_reference_path"], config["type_level_path"]
    )
    type_levels_by_result = {item["DxResult"]: item for item in type_levels}
    payload["candidateReference"] = candidate_document
    payload.setdefault("reference_versions", {}).update(visual_provenance)
    payload["reference_versions"]["histologic_type_mapping"] = mapping_provenance

    backend_config = deepcopy(config.get("backend") or {"mode": "reference"})
    backend_mode = str(backend_config.get("mode", "reference"))
    if backend_mode not in {"reference", "learnable_soft_prompt"}:
        raise ValueError(
            "query generation backend.mode must be reference or "
            "learnable_soft_prompt"
        )

    by_dx: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks_artifact["payload"]["chunks"]:
        by_dx[chunk["dx_pair_id"]].append(chunk)

    query_index = 1
    learnable_provenance: dict[str, Any] | None = None
    for dx_item, record in dx_items(payload).items():
        record["visualAttrQueries"] = []
        if dx_item != "Histologic_Type":
            continue
        dx_result = record["DxResultCls"]
        if not isinstance(dx_result, str):
            raise ValueError("Histologic_Type DxResultCls must be a single string")
        mapped_result = mapping.get(dx_result)
        criteria = type_levels_by_result.get(mapped_result) if mapped_result else None
        if mapped_result is not None and criteria is None:
            raise ValueError(
                f"Histologic mapping target {mapped_result!r} has no type-level criteria"
            )
        chunks = by_dx[record["dx_pair_id"]]
        used_chunks = chunks
        if backend_mode == "learnable_soft_prompt" and criteria is not None:
            required_chunk_count = int(
                backend_config.get("required_chunk_count", 3)
            )
            if len(chunks) < required_chunk_count:
                raise ValueError(
                    f"DxPair {record['dx_pair_id']!r} has {len(chunks)} F chunks; "
                    f"the trained soft prompt requires {required_chunk_count}"
                )
            used_chunks = chunks[:required_chunk_count]
            if generator is None:
                generator = _learnable_generator(backend_config)
            dx_text = record.get("DxResultRawTxt") or record["DxResultTxt"]
            generated = generator.generate(dx_text, used_chunks)
            criteria = _merge_learned_attributes(
                criteria,
                generated,
                backend_config,
            )
            learnable_provenance = deepcopy(generator.provenance)
            learnable_provenance.update(
                {
                    "condition_merge_mode": backend_config.get(
                        "condition_merge_mode", "replace"
                    ),
                    "selected_value_condition": backend_config.get(
                        "selected_value_condition", "Must_True"
                    ),
                    "unselected_value_condition": backend_config.get(
                        "unselected_value_condition", "Not_Mentioned"
                    ),
                }
            )
        evidence = " ".join(chunk["text"] for chunk in used_chunks)
        status = "mapped" if criteria is not None else "unmapped"
        mapping_source = (
            f"{mapping_provenance['source_name']}#sha256="
            f"{mapping_provenance['sha256']}"
        )
        if learnable_provenance is not None and criteria is not None:
            mapping_source += (
                ";soft_prompt#sha256="
                f"{learnable_provenance['checkpoint_sha256']}"
            )
        record["visualAttrQueries"].append(
            {
                "query_id": f"{case_id}-query-{query_index:03d}",
                "dx_pair_id": record["dx_pair_id"],
                "text": evidence or f"Evaluate visual criteria for {dx_result}.",
                "criteria_status": status,
                "diagnosticCriteria": deepcopy(criteria),
                "mapping_source": mapping_source,
                "chunk_ids": [chunk["chunk_id"] for chunk in used_chunks],
            }
        )
        query_index += 1

    if learnable_provenance is not None:
        payload["reference_versions"][
            "learnable_query_generation"
        ] = learnable_provenance

    return {
        "contract": "G.VisualAttributeQueries",
        "schema_version": "2.0",
        "artifact_id": f"G-{case_id}",
        "case_id": case_id,
        "producer": config["component_version"],
        "payload": payload,
    }


def main() -> None:
    args = cli_parser("甲: generate G visual attribute queries from F chunks").parse_args()
    inputs = load_inputs(args.input, ["D.DxPairs", "F.Chunks"])
    config = load_config(args.config)
    if config.get("mode") == "example":
        artifact = build_example_artifact(
            inputs["D.DxPairs"],
            inputs["F.Chunks"],
            config["component_version"],
        )
    else:
        artifact = generate_artifact(
            inputs["D.DxPairs"],
            inputs["F.Chunks"],
            config,
        )
    write_artifact(artifact, args.output, "G.VisualAttributeQueries")


if __name__ == "__main__":
    main()
