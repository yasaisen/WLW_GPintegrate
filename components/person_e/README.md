# Person E: CLEE evidence selection

This component consumes one `D.DxPairs@2.0` artifact and the matching
`H.MatchedROIs@2.0` artifact. It writes `I.CLEESelectedROIs@2.0`, preserving
all H ROIs and appending one auditable CLEE decision per diagnostic pair.

Only H events marked selected and belonging to the diagnostic pair's
`referenceWSI` are submitted. A submitted ROI receives the complete layered
`pseudo_DxPair`; `finalResult.assigned_as_ref` controls the I selected status.
An empty eligible set is a successful result and does not load the model.

## Run

From the repository or component kit root:

```bash
python -m components.person_e.clee \
  --input ../run/output/person_cde/cases/case-001/D_dx_pairs.json \
  --input ../run/output/person_cde/cases/case-001/H_matches.json \
  --output ../run/output/person_cde/cases/case-001/I_selected_rois.json \
  --config components/person_e/configs/native.json
```

The default config is a deterministic test fixture. `configs/native.json` is the active real-inference
configuration. MedGemma, embedding, and CLEE checkpoint paths are managed only there and resolve
below sibling `reference/person_e/`; runtime artifacts remain below sibling `run/`.

## Image input

When `main_info.roi_path` names an existing RGB crop, CLEE uses it. Otherwise
the component opens `stains[].filepath`, reads `level0_info.xywh`, and resamples
the rectangle to `main_info.mpp`. ROI crops and relative paths must resolve below
sibling `run`; only an absolute WSI `stains[].filepath` may remain external.

## Runtime behavior

Inference uses deterministic ROI ordering and every eligible ROI. The forward
limit divides a layer into chunks. ROIs meeting the validation calibrated case
importance threshold enter the next layer, and processing ends after one chunk,
no selected references, or no reduction. Classification thresholds produce
the checkpoint-declared class `assigned` value independently from evidence
selection. The current checkpoint supports `Histologic_Type` and
`Microcalcification`; their predictions are merged into the same ROI's layered
`pseudo_DxPair` without overwriting one another.

The native backend requires CUDA for the supplied configuration and fails with
a nonzero exit on missing assets, checkpoint inconsistency, model errors, or
output coverage errors. It does not import or execute DRGVLM.
