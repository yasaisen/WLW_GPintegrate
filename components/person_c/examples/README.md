# Person C canonical example

A contract-level example that needs no GPU, slide or model. It feeds fixed proposal polygons through
the real `build_region_artifact` (polygon -> ROI) path and compares the result with a frozen output.

| File | Content |
|---|---|
| `case_list.valid.json` | one case, two stains: `HE` (processed) and `IHC` (not processed, `stain_types=["HE"]`) |
| `proposals.valid.json` | GeoJSON polygons standing in for the CONCH region-proposal output (level-0 px) |
| `E_rois.expected.json` | expected `E.ROIs@2.0` for slide 30000 x 20000 px, MPP 0.25, config below |

Slide and config used by `tests/test_interest_pattern.py::CanonicalExampleTests`
(`EXAMPLE_SLIDE`, `EXAMPLE_CONFIG`): `target_mpp=0.5`, `min_region_area_px=262144`,
`max_rois_per_stain=256`, `max_main_side_px=2048`.

Covered cases (5 polygons, 4 ROIs):

1. ordinary component with fractional edges (rounded outwards);
2. component with a hole (the box ignores the hole);
3. tiny component (area < `min_region_area_px`): dropped;
4. component sticking out of the slide: box clamped to the slide;
5. very large component: `level0_info` keeps the full box, `main_info.mpp` grows so the longest
   side is 2048 px;
6. non-processed stain (`IHC`): kept with `roi_num = 0`, `roi_list = []`.

Run: `python -m unittest components.person_c.tests.test_interest_pattern`

A real end-to-end example needs a WSI with MPP metadata, the CONCH checkpoint under
`reference/person_c/` and a GPU; see the README (section 8) for the runs that were measured.
Failure cases covered by tests: multi-case input is rejected; a missing slide file raises
`FileNotFoundError`.
