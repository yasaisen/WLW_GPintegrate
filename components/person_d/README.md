# Person D: Visual Attribute Extraction and Matching Filter

Owner: person_D. Component version `0.2.0` (`component.yaml`, config `component_version`
`person-d/visual-filter:0.2.0`, image tag `wlw/person-d:0.2.0`).

`visual_filter` consumes `E.ROIs@2.0` and `G.VisualAttributeQueries@2.0` and writes
`H.MatchedROIs@2.0` (schemas in `contracts/schemas/`). Every E ROI is kept with its upstream
`selection_history`; one `visual_attributes_matching_filter` event is appended per diagnostic pair
and query.

| Mode | Config | Behavior |
|---|---|---|
| `example` | `configs/example.json` | Contract-only stub for the repository pipeline test. No image or model; every ROI is `skipped` (`example_stub_no_evaluation`). |
| `native` | `configs/native.example.json` | PLIP + CONCH visual attribute extraction, then matching against G `diagnosticCriteria`. |
| `native` (smoke) | `configs/native.smoke.json` | Same path with random-initialised CONCH weights, for verifying the pipeline without gated CONCH access. Decisions have no diagnostic meaning. |

## Native method

1. **ROI image** (`roi_reader.py`): `main_info.roi_path` when present (below sibling `run/`);
   otherwise the WSI at `stains[].filepath` is read with OpenSlide at `level0_info.xywh` and resampled
   to `main_info.roi_wh`. `roi_wh` must agree with the level-0 size and both MPPs within 1 px. Only an
   absolute WSI filepath may point outside `run/`; relative paths resolve below `run/`.
2. **Visual Attribute Extraction** (`visual_attribute_extraction.py`, ported from
   `pipeline_quilt_1m.py`): for each of the 17 vocabulary attributes, PLIP and CONCH each score every
   option as `image_score_weight * image-to-option-prompt + example_score_weight *
   image-to-example-prototype + text_score_weight * custom-prompt-to-option`. Long option prompts are
   chunked and averaged. Single-select attributes take the arg-max; `Pattern` and
   `Specific_Sub_Architectures` keep options within `multi_select_margin` of the best. Only labels both
   models agree on are kept (`roi.visualAttrs`); per-model predictions and scores go to
   `roi.visualAttrs_info.models`.
3. **Visual Attribute Matching Filter** (`matching_filter.py`): agreed labels map to criteria options
   through `criteria_label_map.json`, then exact, then case-insensitive matching. An attribute is
   evaluated when it maps to at least one informative condition. A Must_False option, or an evaluated
   Must_True attribute without a Must_True option, gives `rejected` (`must_condition_failed`).
   Otherwise the mean `condition_weights` score must be `>= score_threshold` for `selected`
   (`visual_attributes_match`), else `rejected` (`score_below_threshold`). Fewer than
   `min_evaluated_attributes` evaluated attributes gives `skipped` (`insufficient_visual_evidence`).
   Per-attribute decisions are stored in `roi.visualAttrs_info.matching.<query_id>`.

Other `skipped` reasons: `stain_not_in_reference_wsi`, `no_visual_attr_query`, `query_unmapped`,
`no_diagnostic_pair`. Models load only when at least one reference-WSI ROI has a mapped query.

## Runtime

| Item | Value |
|---|---|
| Python / OS | 3.10, Ubuntu 22.04 (`nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04`) |
| Frameworks | torch 2.11.0+cu128, torchvision 0.26.0+cu128, transformers 4.57.6, timm 0.9.16, CONCH `141cc09c`, openslide-python 1.4.6, libopenslide0 3.4.1+dfsg-5build1 |
| CUDA / driver | The base image declares `NVIDIA_REQUIRE_CUDA=cuda>=12.8` and torch is the cu128 build, so the host driver must support CUDA 12.8 (NVIDIA R570 or newer). Verified only with driver 592.00. |
| GPU | Expected for `device: cuda`; one GPU. A CUDA device fails when CUDA is unavailable. |
| CPU fallback | Supported with `device: cpu`. Canonical example in the image: 373 s, peak resident set 2.95 GiB, same decisions and scores as the GPU run (Docker Desktop VM, 12 vCPU, 7 GB, same host). Per-ROI CPU latency not measured. |
| Batch size | One image per forward pass for ROIs and example images; not configurable |
| Minimum VRAM | Not determined below 8 GB; the measured peak below is the known requirement |
| Measured GPU memory | Peak `torch.cuda.max_memory_allocated` 2.11 GiB (reserved 2.31 GiB) |
| Measured RAM | Peak resident set 3.2 GiB |
| Measured time | About 97 s for the canonical example, dominated by model loading and example-prototype encoding; about 0.1 s per 1024 × 1024 ROI |
| Suggested timeout | GPU: 300 s plus 1 s per ROI (derived from the measurements above). CPU: no per-ROI figure; allow at least 600 s for the canonical example. |

Measurements: canonical example (`examples/E_rois.valid.json`, two extracted ROIs, 440 example
images), `configs/native.example.json` with the official PLIP and CONCH checkpoints, NVIDIA GeForce
RTX 5060 Laptop GPU 8 GB, driver 592.00, Windows 11, torch 2.11.0+cu128. The per-ROI latency was
measured over 30 ROIs with `configs/native.smoke.json`, whose CONCH model has the same architecture.

## External assets

All assets live below sibling `reference/person_d/` (mounted read-only at `/reference`) and are listed
with revision, SHA-256, size, and license in `external-assets.yaml`:

| Logical path | Asset | SHA-256 |
|---|---|---|
| `reference/person_d/checkpoint/plip/` | `vinid/plip` revision `67ade53d` | `pytorch_model.bin` `98a7f8d2a1f4a8fc8f6dedb3a16ff7efbe02a7ef67c93904c80bca9767c69630` |
| `reference/person_d/checkpoint/conch/pytorch_model.bin` | `MahmoodLab/CONCH` revision `f9ca9f87` (gated, CC BY-NC-ND 4.0) | `40a9644b9ba0e83a74576e0a5e5f7313599fa9c9cdaf3c20f8a3e271b0e9ae7c` |
| `reference/person_d/template_ref/visual_attribute_prompts.json` | Vocabulary, option descriptions, prompts (1.0.0) | `dbce02cae212adf1dadb905c868229d0c1ab5aa25b81b6c4c07342c764b2448c` |
| `reference/person_d/template_ref/criteria_label_map.json` | Label aliases for diagnosticCriteria 1.2.1 (1.0.0) | `e1f59e667358fbca6f6bfe70cbfc140cd6c0a4ed8f6661920b5562a042f46e38` |
| `reference/person_d/template_ref/Example/ROI_Analysis/` | Few-shot example images (440 files, de-identified) from WHO Classification of Tumours, Breast Tumours, 5th ed. (IARC, 2019); copyrighted, not redistributed | tree `5a4ba948b955a1762700b8881eff12614b9120c47f6d44c7e8d2be201b7f75ce` (algorithm in `external-assets.yaml`) |

Weights load from local files only; the image sets `HF_HUB_OFFLINE=1`. Download the gated CONCH
weights with your own Hugging Face access; never put a token in config, code, or the image.

```bash
hf download vinid/plip --revision 67ade53ddd32195868f422585f72698ef5d15094 \
  --local-dir ../reference/person_d/checkpoint/plip
hf download MahmoodLab/CONCH pytorch_model.bin --revision f9ca9f877171a28ade80228fb195ac5d79003357 \
  --local-dir ../reference/person_d/checkpoint/conch
```

## CLI

```bash
python -m components.person_d.visual_filter \
  --input ../run/output/work/E_rois.json \
  --input ../run/output/work/G_queries.json \
  --output ../run/output/work/H_matches.json \
  --config components/person_d/configs/native.example.json
```

## Docker

```bash
docker build --no-cache -f components/person_d/Dockerfile -t wlw/person-d:0.2.0 .

docker run --rm --gpus all \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  wlw/person-d:0.2.0 \
  --input /run/input/person_d/E_rois.json \
  --input /run/input/person_d/G_queries.json \
  --output /run/output/person_d/H_matches.json \
  --config /app/components/person_d/configs/native.example.json
```

The image sets `TORCHINDUCTOR_CACHE_DIR=/run/cache/person_d/torchinductor` so that it also runs under
a UID without a passwd entry, as `integration/compose.yaml` does. torch creates that directory empty;
apart from H, nothing else is written.

## Canonical example and tests

`examples/` holds a de-identified E/G pair, an empty-ROI E, a synthetic generic tiled TIFF, exact
expected H for `example` mode and for the native empty-ROI case, and a structure check for the native
model run (`check_native_structure.py`); see `examples/README.md` for commands and comparison.

```bash
python -m unittest discover -s components/person_d/tests -t . -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

`test_visual_filter.py` writes a temporary label map below `reference/person_d/template_ref/`, so
that directory must be writable when the tests run.

## Failure conditions

The process exits non-zero and writes no H when: E/G `case_id`, `data_mode`, or stain sets differ;
`referenceWSI` names an unknown stain; a query's `dx_pair_id` differs from its DxItem; `roi_id` or
`query_id` repeats; ROI geometry is invalid or outside the WSI; the prompt asset or label map is
missing; a ROI crop, WSI, weight, or example directory needed for extraction is missing; an example
image is unreadable; the configured CUDA device is unavailable; `diagnosticCriteria.version` differs
from the label map; or model inference fails.

## Limitations

- The vocabulary covers 17 of the 24 diagnosticCriteria 1.2.1 attributes. `Tumour_Border`,
  `Myoepithelial_Cell_Layer`, `Stromal_Characteristics`, `Cytoplasmic_Features`, `Mitotic_Activity`,
  `Squamous_Sebaceous_Differentiation`, and `Tumour_Infiltrating_Lymphocytes` are never evaluated;
  with `unverified_must_true: ignore`, their Must_True options are not enforced.
- `Cuboidal/Columnar` maps to criteria options with different conditions and is treated as ambiguous;
  `Pattern` `one to several layers` has no criteria option and is unmapped.
- 14 vocabulary options have no example images and receive no prototype score.
- GPU floating-point differences can change scores near ties and therefore near-tie predictions.
- Unsupported inputs: slide formats that OpenSlide 3.4.1 cannot open, `roi_path` crops that Pillow
  cannot read, and non-brightfield content (images are converted to RGB, so fluorescence or
  multiplex channels are not used). `diagnosticCriteria` versions other than the label map's
  `1.2.1` fail.
- The CONCH release does not include the CoCa `text_decoder`; it is unused because only the image
  and text encoders are called.
- The native path has been run end to end with the official PLIP and CONCH checkpoints on the
  synthetic slide only; it has not been validated on real slides.

## Changelog

- `0.2.0`: native PLIP + CONCH extraction and matching filter, weight SHA-256 checks, smoke config,
  native canonical example with a synthetic slide; `example` mode unchanged except for the version
  string.
- `0.1.0`: contract-only example stub.
