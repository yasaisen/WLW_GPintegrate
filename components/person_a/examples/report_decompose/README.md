# Report Decompose canonical example

All content is synthetic. `case_list.valid.json` is a single-case
`CaseListInput@1.0`; `D_dx_pairs.expected.json` is the deterministic output of
`config.example.json`. `case_list.invalid.json` demonstrates fail-fast input
validation and must exit non-zero without writing a partial D artifact.
