"""Read E ROI pixels from E's stain filepath and ROI geometry.

``main_info.roi_path`` is used when E provides a crop; it must stay below
sibling ``run/``.  Otherwise the WSI at ``stains[].filepath`` is read at
``level0_info.xywh`` and resampled to ``main_info.roi_wh``.  Only an absolute
WSI filepath may point outside ``run/``.
"""

from __future__ import annotations

import math
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image

from contracts.paths import resolve_run_path


def _mpp_pair(value: Any, name: str) -> tuple[float, float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        pair = (float(value), float(value))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        pair = (float(value[0]), float(value[1]))
    else:
        raise ValueError(f"Invalid {name}: {value!r}")
    if any(not math.isfinite(part) or part <= 0 for part in pair):
        raise ValueError(f"{name} must contain positive finite values: {value!r}")
    return pair


def roi_geometry(roi: Mapping[str, Any]) -> tuple[tuple[int, int, int, int], tuple[int, int], float]:
    """Validate E geometry and return level-0 xywh, target size, and target downsample."""

    roi_id = roi["roi_id"]
    x, y, width, height = (int(value) for value in roi["level0_info"]["xywh"])
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"ROI {roi_id} has invalid level0_info.xywh")
    target_w, target_h = (int(value) for value in roi["main_info"]["roi_wh"])
    if target_w <= 0 or target_h <= 0:
        raise ValueError(f"ROI {roi_id} has invalid main_info.roi_wh")

    level0_mpp = _mpp_pair(roi["level0_info"]["mpp"], "level0_info.mpp")
    target_mpp = _mpp_pair(roi["main_info"]["mpp"], "main_info.mpp")
    expected = (
        round(width * level0_mpp[0] / target_mpp[0]),
        round(height * level0_mpp[1] / target_mpp[1]),
    )
    if abs(expected[0] - target_w) > 1 or abs(expected[1] - target_h) > 1:
        raise ValueError(
            f"ROI {roi_id} main_info.roi_wh {target_w, target_h} does not match "
            f"level0 xywh and mpp (expected about {expected})"
        )
    downsample = min(target_mpp[0] / level0_mpp[0], target_mpp[1] / level0_mpp[1])
    return (x, y, width, height), (target_w, target_h), downsample


def read_wsi_roi(slide: Any, roi: Mapping[str, Any]) -> Image.Image:
    (x, y, width, height), target_size, desired = roi_geometry(roi)
    if x + width > slide.dimensions[0] or y + height > slide.dimensions[1]:
        raise ValueError(f"ROI {roi['roi_id']} exceeds the WSI dimensions")

    level = slide.get_best_level_for_downsample(max(1.0, desired))
    downsample = float(slide.level_downsamples[level])
    source_size = (math.ceil(width / downsample), math.ceil(height / downsample))
    rgba = slide.read_region((x, y), level, source_size)
    try:
        image = rgba.convert("RGB")
    finally:
        rgba.close()
    if image.size != target_size:
        resized = image.resize(target_size, Image.Resampling.BICUBIC)
        image.close()
        image = resized
    return image


def _open_openslide(path: str) -> Any:
    import openslide

    return openslide.OpenSlide(path)


class ROIImageReader:
    """Open each WSI once per run and return RGB ROI images."""

    def __init__(self, open_slide: Callable[[str], Any] = _open_openslide):
        self._open_slide = open_slide
        self._slides: dict[Path, Any] = {}
        self._stack = ExitStack()

    def __enter__(self) -> "ROIImageReader":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._stack.close()
        self._slides.clear()

    def read(self, stain: Mapping[str, Any], roi: Mapping[str, Any]) -> Image.Image:
        roi_geometry(roi)
        roi_path = roi["main_info"].get("roi_path")
        if roi_path:
            path = resolve_run_path(roi_path)
            if not path.is_file():
                raise FileNotFoundError(f"ROI image is missing: {path}")
            with Image.open(path) as source:
                return source.convert("RGB")

        raw = Path(str(stain["filepath"])).expanduser()
        wsi_path = raw.resolve() if raw.is_absolute() else resolve_run_path(raw)
        if not wsi_path.exists():
            raise FileNotFoundError(
                f"WSI is missing for stain {stain['stain_id']}: {wsi_path}"
            )
        if wsi_path not in self._slides:
            slide = self._open_slide(str(wsi_path))
            if hasattr(slide, "close"):
                self._stack.callback(slide.close)
            self._slides[wsi_path] = slide
        return read_wsi_roi(self._slides[wsi_path], roi)
