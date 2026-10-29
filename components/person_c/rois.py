"""Region-proposal polygons -> E.ROIs rectangles (pure Python, no torch/openslide).

Geometry rules (documented for 丁/戊, who rebuild pixels from these fields):

* Coordinates are level-0 pixels, origin at the slide's top-left, x to the right,
  y down. ``xywh`` is ``[left, top, width, height]``; the rectangle covers
  ``[left, left + width) x [top, top + height)`` and always lies inside the slide.
* One ROI per connected component (one proposal polygon): its axis-aligned bounding
  box, rounded outwards to whole pixels and clamped to the slide. ROI sizes vary;
  boxes of nested or neighbouring components may overlap.
* Components smaller than ``min_region_area_px`` (polygon area, level-0 px^2, holes
  subtracted) are dropped. At most ``max_rois`` ROIs are kept, largest component
  first. The result is sorted by ``(top, left)``; ``global_idx`` follows that order.
* ``main_info`` is the same rectangle resampled to a per-ROI working MPP:
  ``mpp = max(target_mpp, longest_side_um / max_main_side_px)``, i.e. ``target_mpp``
  unless that would make the longest side exceed ``max_main_side_px`` (large
  components are viewed coarser instead of being split). Then
  ``roi_wh = max(1, round(level0_wh * level0_mpp / mpp))`` per axis (the exact rule
  person_e's ``_read_wsi_roi`` uses) and ``xywh`` is the level-0 ``xywh`` scaled by
  the same per-axis factor and rounded. ``level0_info`` is never affected.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

Box = tuple[int, int, int, int]


def _ring_area(ring: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def plan_boxes(
    features: Sequence[dict[str, Any]],
    slide_wh: tuple[int, int],
    min_region_area_px: float,
    max_rois: int,
) -> list[Box]:
    if max_rois <= 0:
        raise ValueError("max_rois must be positive")
    components = []
    for feature in features:
        rings = feature["geometry"]["coordinates"]
        area = _ring_area(rings[0]) - sum(_ring_area(h) for h in rings[1:])
        if area >= min_region_area_px:
            components.append((area, rings[0]))
    components.sort(key=lambda item: -item[0])

    boxes: dict[Box, None] = {}
    for _, ring in components[:max_rois]:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        left = min(max(math.floor(min(xs)), 0), slide_wh[0] - 1)
        top = min(max(math.floor(min(ys)), 0), slide_wh[1] - 1)
        right = min(max(math.ceil(max(xs)), left + 1), slide_wh[0])
        bottom = min(max(math.ceil(max(ys)), top + 1), slide_wh[1])
        boxes.setdefault((left, top, right - left, bottom - top))
    return sorted(boxes, key=lambda b: (b[1], b[0]))


def _mpp_field(mpp: tuple[float, float]) -> float | list[float]:
    return mpp[0] if mpp[0] == mpp[1] else [mpp[0], mpp[1]]


def build_roi_info(
    box: Box,
    level0_mpp: tuple[float, float],
    target_mpp: float,
    max_main_side_px: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    left, top, width, height = box
    if max_main_side_px is not None:
        longest_um = max(width * level0_mpp[0], height * level0_mpp[1])
        target_mpp = max(target_mpp, longest_um / max_main_side_px)
    level0 = {
        "area": width * height,
        "coords_seg": None,
        "cxcywh": [left + width / 2, top + height / 2, width, height],
        "mpp": _mpp_field(level0_mpp),
        "roi_path": None,
        "roi_wh": [width, height],
        "xywh": [left, top, width, height],
    }
    sx, sy = level0_mpp[0] / target_mpp, level0_mpp[1] / target_mpp
    main_w, main_h = max(1, round(width * sx)), max(1, round(height * sy))
    main_left, main_top = round(left * sx), round(top * sy)
    main = {
        "area": main_w * main_h,
        "coords_seg": None,
        "cxcywh": [main_left + main_w / 2, main_top + main_h / 2, main_w, main_h],
        "mpp": target_mpp,
        "roi_path": None,
        "roi_wh": [main_w, main_h],
        "xywh": [main_left, main_top, main_w, main_h],
    }
    return level0, main


def candidate_event(producer: str) -> dict[str, Any]:
    return {
        "stage": "interest_pattern_extraction",
        "owner": "person_C",
        "artifact_contract": "E.ROIs",
        "action": "candidate_generated",
        "status": "selected",
        "selected": True,
        "reason": "interest_pattern_candidate_generated",
        "producer": producer,
    }
