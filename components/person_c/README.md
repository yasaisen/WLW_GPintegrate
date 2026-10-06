# Person C implementation slot

This directory contains a contract-only example, not a WSI or ROI inference implementation.
`interest_pattern` accepts one `CaseListInput@1.0`, retains its case/block/stain metadata, and emits
`E.ROIs@2.0` with empty ROI lists. It never opens a slide or loads a model.

```bash
python -m components.person_c.interest_pattern \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/E_rois.json \
  --config components/person_c/configs/example.json
```
