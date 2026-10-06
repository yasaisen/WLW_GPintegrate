"""
 SPDX-License-Identifier: MIT
 Copyright (c) 2026, yasaisen (clover)
 
 This file is part of a project licensed under the MIT License.
 See the LICENSE file in the project root for more information.
 
 last modified in 2604281629
"""


import torch
from PIL import Image
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, TypeVar



@dataclass
class ROI:
    global_idx: int
    image: Image.Image
    mpp: float
    cxcywh: Tuple[float, float, float, float]
    visualAttrs: Dict
    roi_wh: Tuple[float, float]
    DxItem: str
    DxResult: str
    DxResult_embeddings: torch.Tensor


@dataclass(frozen=True)
class ROIRecord:
    global_idx: int
    image_path: Optional[str]
    mpp: Optional[float]
    cxcywh: Optional[Tuple[float, float, float, float]]
    visualAttrs: Optional[Dict]
    roi_wh: Tuple[float, float]
    DxItem: str
    DxResult: str
    DxResult_embeddings: torch.Tensor

_ROIType = TypeVar("_ROIType")

@dataclass
class Case:
    global_idx: int
    case_id: int
    pid: int
    roi_ExistCounts: Dict[str, int]
    rois: List[ROI]

    DxPair_dict: Dict[str, Dict] # DxItem -> {"DxResult": str, "DxResult_embeddings": torch.Tensor}












