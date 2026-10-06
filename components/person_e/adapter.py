"""Thin WLW adapter primitives for a replaceable inference-only CLEE backend."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from contracts.metadata import iter_rois
from contracts.paths import (
    PROJECT_ROOT,
    RUN_ROOT,
    resolve_person_reference_path,
    resolve_run_path,
)


FINAL_RESULT_KEY = "finalResult"
UNABLE_TO_DETERMINE = "unable_to_determine"


@dataclass(frozen=True)
class CheckpointSupport:
    config_path: Path
    threshold_bundle_path: Path
    active_DxItem_list: tuple[str, ...]
    active_DxResult_dict: dict[str, tuple[str, ...]]
    effective_DxItem_list: tuple[str, ...]
    checkpoint_epoch: int
    bundle_id: str
    case_importance_thresholds: dict[str, float]
    roi_classification_thresholds: dict[str, dict[str, float | None]]

    def supports(self, DxItem: str, DxResult: str | None = None) -> bool:
        if DxItem not in self.effective_DxItem_list:
            return False
        if DxResult is None:
            return True
        return DxResult in self.active_DxResult_dict.get(DxItem, ())


@dataclass(frozen=True)
class BackendResult:
    predictions_by_roi_id: dict[str, dict[str, Any]]
    execution_status: str


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    return value


def resolve_project_path(raw_path: str | None) -> Path | None:
    """Resolve a configured CLEE asset below the sibling reference root."""

    if raw_path is None:
        return None
    return resolve_person_reference_path("person_e", raw_path)


def _checkpoint_paths(config: Mapping[str, Any]) -> tuple[Path, Path]:
    checkpoint_dir = resolve_project_path(config.get("checkpoint_dir"))
    config_path = resolve_project_path(config.get("checkpoint_config_path"))
    if config_path is None and checkpoint_dir is not None:
        config_path = checkpoint_dir / "config.json"
    if config_path is None or not config_path.is_file():
        raise FileNotFoundError(
            "CLEE checkpoint config is required and must exist: "
            f"{config_path}"
        )

    threshold_path = resolve_project_path(config.get("threshold_bundle_path"))
    if threshold_path is None:
        if checkpoint_dir is None:
            raise ValueError(
                "threshold_bundle_path is required when checkpoint_dir is absent"
            )
        manifest_path = checkpoint_dir / "[checkpoint]best_model.json"
        manifest = _load_json(manifest_path)
        epoch = int(manifest["checkpoint_metadata"]["epoch_idx"])
        epoch_prefix = f"threshold_bundle[{epoch:03d}]_"
        matches = sorted(
            path
            for path in checkpoint_dir.iterdir()
            if path.name.startswith(epoch_prefix) and path.suffix == ".json"
        )
        if len(matches) != 1:
            raise ValueError(
                f"Expected one threshold bundle for checkpoint epoch {epoch}, "
                f"found {len(matches)}"
            )
        threshold_path = matches[0]
    if not threshold_path.is_file():
        raise FileNotFoundError(f"CLEE threshold bundle does not exist: {threshold_path}")
    return config_path, threshold_path


def load_checkpoint_support(config: Mapping[str, Any]) -> CheckpointSupport:
    """Read checkpoint-declared support without importing the CLEE runtime."""

    config_path, threshold_path = _checkpoint_paths(config)
    checkpoint_config = _load_json(config_path)
    threshold_bundle = _load_json(threshold_path)

    if threshold_bundle.get("schema_version") != "clee_threshold_bundle_v3":
        raise ValueError(
            "Unsupported CLEE threshold schema: "
            f"{threshold_bundle.get('schema_version')!r}"
        )
    if threshold_bundle.get("source_split") != "valid":
        raise ValueError("CLEE thresholds must be calibrated from the valid split")
    if threshold_bundle.get("score_type") != "cosine_similarity":
        raise ValueError("CLEE selection requires cosine_similarity thresholds")

    config_active_items = tuple(
        str(item) for item in checkpoint_config.get("active_DxItem_list", [])
    )
    config_active_results = {
        str(item): tuple(str(result) for result in results)
        for item, results in checkpoint_config.get("active_DxResult_dict", {}).items()
    }
    label_space = threshold_bundle.get("label_space", {})
    threshold_active_items = tuple(
        str(item) for item in label_space.get("active_DxItem_list", [])
    )
    threshold_active_results = {
        str(item): tuple(str(result) for result in results)
        for item, results in label_space.get("active_DxResult_dict", {}).items()
    }
    if config_active_items != threshold_active_items:
        raise ValueError(
            "CLEE config/threshold active_DxItem_list mismatch: "
            f"config={config_active_items}, threshold={threshold_active_items}"
        )
    if config_active_results != threshold_active_results:
        raise ValueError("CLEE config/threshold active_DxResult_dict mismatch")

    raw_policy = config.get("wlw_supported_dx_items")
    if raw_policy is None:
        # The checkpoint and its validation-calibrated threshold bundle are the
        # authoritative declaration of the label space.  A deployment may
        # still provide an explicit list to narrow (never expand) that space.
        effective_items = config_active_items
    elif (
        isinstance(raw_policy, Sequence)
        and not isinstance(raw_policy, (str, bytes))
        and all(isinstance(item, str) and item for item in raw_policy)
    ):
        wlw_whitelist = tuple(dict.fromkeys(str(item) for item in raw_policy))
        effective_items = tuple(
            item for item in wlw_whitelist if item in config_active_items
        )
    else:
        raise ValueError(
            "wlw_supported_dx_items must be null or a list of nonempty strings"
        )

    case_importance = threshold_bundle.get("case_importance", {}).get(
        "by_DxItem", {}
    )
    case_thresholds: dict[str, float] = {}
    roi_thresholds: dict[str, dict[str, float | None]] = {}
    all_roi_thresholds = threshold_bundle.get("roi_classification", {})
    for DxItem in effective_items:
        threshold_info = case_importance.get(DxItem)
        if not isinstance(threshold_info, Mapping):
            raise ValueError(f"Missing CLEE case-importance threshold for {DxItem}")
        if threshold_info.get("comparison") != ">=":
            raise ValueError(f"Unsupported CLEE comparison for {DxItem}")
        case_thresholds[DxItem] = float(threshold_info["threshold"])

        item_thresholds = all_roi_thresholds.get(DxItem)
        if not isinstance(item_thresholds, Mapping):
            raise ValueError(f"Missing CLEE ROI thresholds for {DxItem}")
        roi_thresholds[DxItem] = {}
        for DxResult in config_active_results.get(DxItem, ()):
            result_info = item_thresholds.get(DxResult)
            if not isinstance(result_info, Mapping):
                raise ValueError(f"Missing CLEE ROI threshold for {DxItem}/{DxResult}")
            if result_info.get("comparison") != ">=":
                raise ValueError(
                    f"Unsupported CLEE ROI threshold comparison for "
                    f"{DxItem}/{DxResult}"
                )
            raw_threshold = result_info.get("threshold")
            roi_thresholds[DxItem][DxResult] = (
                None if raw_threshold is None else float(raw_threshold)
            )

    return CheckpointSupport(
        config_path=config_path,
        threshold_bundle_path=threshold_path,
        active_DxItem_list=config_active_items,
        active_DxResult_dict=config_active_results,
        effective_DxItem_list=effective_items,
        checkpoint_epoch=int(threshold_bundle["epoch_idx"]),
        bundle_id=str(threshold_bundle.get("bundle_id") or "unidentified-bundle"),
        case_importance_thresholds=case_thresholds,
        roi_classification_thresholds=roi_thresholds,
    )


def _fixture_scores(
    labels: Sequence[str],
    case_label: str,
    global_idx: int,
    score_cycle: Sequence[float],
) -> dict[str, float]:
    importance = float(score_cycle[global_idx % len(score_cycle)])
    scores = {
        label: round(max(-1.0, importance - 0.35 - index * 0.01), 6)
        for index, label in enumerate(labels)
    }
    scores[case_label] = round(importance, 6)
    return scores


def _fixture_prediction(
    DxItem: str,
    case_label: str,
    global_idx: int,
    chunk_idx: int,
    support: CheckpointSupport,
    score_cycle: Sequence[float],
) -> dict[str, Any]:
    labels = support.active_DxResult_dict[DxItem]
    all_scores = _fixture_scores(labels, case_label, global_idx, score_cycle)
    candidate_pairs = []
    for label in labels:
        threshold = support.roi_classification_thresholds[DxItem][label]
        if threshold is not None and all_scores[label] >= threshold:
            candidate_pairs.append((label, all_scores[label]))
    candidate_pairs.sort(key=lambda item: item[1], reverse=True)
    assigned = candidate_pairs[0][0] if candidate_pairs else UNABLE_TO_DETERMINE
    importance = all_scores[case_label]
    assigned_as_ref = (
        importance >= support.case_importance_thresholds[DxItem]
    )
    return {
        "chunk_idx": chunk_idx,
        "assigned": assigned,
        "importance": importance,
        "assigned_as_ref": assigned_as_ref,
        "candidate@top3AUC": dict(candidate_pairs[:3]),
        "candidate@ALL": all_scores,
    }


def run_fixture_backend(
    input_payload: dict[str, Any],
    DxItem: str,
    case_label: str,
    support: CheckpointSupport,
    max_inputs_per_forward: int,
    score_cycle: Sequence[float],
) -> BackendResult:
    """Produce CLEE-shaped traces for contract/E2E tests only."""

    if max_inputs_per_forward <= 0:
        raise ValueError("max_roi_dxitem_inputs_per_forward must be positive")
    if not score_cycle:
        raise ValueError("fixture_importance_score_cycle must not be empty")

    roi_records = [
        (roi["roi_id"], int(roi["global_idx"]))
        for _, roi in iter_rois(input_payload)
    ]
    traces: dict[str, dict[str, Any]] = {roi_id: {} for roi_id, _ in roi_records}
    pending = list(roi_records)
    layer_idx = 0
    while pending:
        selected: list[tuple[str, int]] = []
        chunks = [
            pending[index : index + max_inputs_per_forward]
            for index in range(0, len(pending), max_inputs_per_forward)
        ]
        for chunk_idx, chunk in enumerate(chunks):
            for roi_id, global_idx in chunk:
                prediction = _fixture_prediction(
                    DxItem=DxItem,
                    case_label=case_label,
                    global_idx=global_idx,
                    chunk_idx=chunk_idx,
                    support=support,
                    score_cycle=score_cycle,
                )
                traces[roi_id][str(layer_idx)] = {DxItem: prediction}
                traces[roi_id][FINAL_RESULT_KEY] = {
                    DxItem: deepcopy(prediction)
                }
                if prediction["assigned_as_ref"] is True:
                    selected.append((roi_id, global_idx))

        if len(chunks) == 1 or not selected or len(selected) == len(pending):
            break
        pending = selected
        layer_idx += 1

    return BackendResult(
        predictions_by_roi_id=traces,
        execution_status="fixture_completed",
    )


def _format_command(
    template: Sequence[str],
    replacements: Mapping[str, str],
) -> list[str]:
    if not template:
        raise ValueError("external_command backend requires command_template")
    return [str(part).format_map(replacements) for part in template]


def run_external_backend(
    input_payload: dict[str, Any],
    config: Mapping[str, Any],
) -> BackendResult:
    """Invoke an inference-only CLEE CLI and read its metadata output."""

    backend = config["backend"]
    work_root = RUN_ROOT / "output" / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="wlw-clee-", dir=work_root
    ) as temp_dir:
        temporary_dir = Path(temp_dir)
        input_path = temporary_dir / "input_metadata.json"
        output_path = temporary_dir / "output_metadata.json"
        input_path.write_text(
            json.dumps(input_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        replacements = {
            "input_metadata": str(input_path),
            "output_metadata": str(output_path),
            "output_dir": str(temporary_dir),
            "checkpoint_dir": str(
                resolve_project_path(config.get("checkpoint_dir")) or ""
            ),
            "image_root": str(
                resolve_run_path(config["image_root"])
                if config.get("image_root")
                else ""
            ),
            "weight_path": str(
                resolve_project_path(config.get("model_weight_path")) or ""
            ),
            "max_roi_dxitem_inputs_per_forward": str(
                int(config["max_roi_dxitem_inputs_per_forward"])
            ),
        }
        command = _format_command(backend.get("command_template", []), replacements)
        subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        if not output_path.is_file():
            raise FileNotFoundError(
                "Inference-only CLEE did not create its declared output: "
                f"{output_path}"
            )
        output_metadata = _load_json(output_path)

    predictions: dict[str, dict[str, Any]] = {}
    for _, roi in iter_rois(output_metadata):
        roi_id = str(roi.get("roi_id") or "")
        pseudo_DxPair = roi.get("pseudo_DxPair")
        if not roi_id or not isinstance(pseudo_DxPair, dict):
            raise ValueError(
                "Inference-only CLEE output must preserve roi_id and add "
                "pseudo_DxPair to every submitted ROI"
            )
        predictions[roi_id] = pseudo_DxPair
    return BackendResult(
        predictions_by_roi_id=predictions,
        execution_status="external_completed",
    )


def run_backend(
    input_payload: dict[str, Any],
    DxItem: str,
    case_label: str,
    support: CheckpointSupport,
    config: Mapping[str, Any],
) -> BackendResult:
    mode = str(config["backend"]["mode"])
    if mode == "fixture":
        return run_fixture_backend(
            input_payload=input_payload,
            DxItem=DxItem,
            case_label=case_label,
            support=support,
            max_inputs_per_forward=int(
                config["max_roi_dxitem_inputs_per_forward"]
            ),
            score_cycle=[
                float(value)
                for value in config["backend"]["fixture_importance_score_cycle"]
            ],
        )
    if mode == "external_command":
        return run_external_backend(input_payload=input_payload, config=config)
    if mode == "native":
        # Keep torch/transformers/OpenSlide imports out of fixture and contract
        # tests; the production dependencies are loaded only for real inference.
        from components.person_e.native_inference import run_native_inference

        return BackendResult(
            predictions_by_roi_id=run_native_inference(
                input_payload=input_payload,
                DxItem=DxItem,
                case_label=case_label,
                support=support,
                config=config,
            ),
            execution_status="native_completed",
        )
    if mode == "deferred":
        return BackendResult(
            predictions_by_roi_id={},
            execution_status="backend_deferred",
        )
    raise ValueError(f"Unsupported CLEE backend mode: {mode!r}")
