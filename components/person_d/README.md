# Person D implementation slot

This directory contains a contract-only example, not a visual-attribute inference implementation.
`visual_filter` combines `E.ROIs@2.0` and `G.VisualAttributeQueries@2.0` into
`H.MatchedROIs@2.0`. It does not read WSI pixels or evaluate attributes. If an upstream implementation
provides ROIs, the example marks them as skipped.

```bash
python -m components.person_d.visual_filter \
  --input ../run/output/work/E_rois.json \
  --input ../run/output/work/G_queries.json \
  --output ../run/output/work/H_matches.json \
  --config components/person_d/configs/example.json
```
