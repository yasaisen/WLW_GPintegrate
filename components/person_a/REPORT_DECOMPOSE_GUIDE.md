# Report Decompose implementation guide

## Current data flow

```text
B.ReportTables manifest
  └─ prepare_case_list.py
       └─ CaseListInput (may contain many cases)
            └─ pipeline fan-out (one case per file/invocation)
                 └─ report_decompose.py
                      └─ D.DxPairs@2.0 (one case)
```

The change from the earlier implementation is the component boundary:
`report_decompose.py` no longer opens Excel and no longer creates a D index.
Hospital table parsing remains available in `prepare_case_list.py`,
`table_parsers.py`, and `xlsx_reader.py`, but it is an upstream normalization
step. This matches the central `CaseListInput@1.0` contract.

## Responsibilities by file

- `prepare_case_list.py`: B manifest → canonical CaseList batch.
- `table_parsers.py`: VGHTC/CGMH report and WSI filename/layout adapters.
- `xlsx_reader.py`: dependency-free XLSX record reader.
- `report_decompose.py`: one normalized case → one schema-valid D.
- `report_extraction.py`: hospital routing and Regex/MedGemma fallback.
- `medgemma_extractor.py`: MedGemma loading, chunking, prompting, JSON parsing.
- `histologic_type_classifier.py`: seven-class Histologic Type normalization.
- `reference_data.py`: loads only mounted Person A reference files and records
  SHA-256 provenance.
- `configs/report_decompose.default.json`: production extraction behavior and
  logical asset paths.

## Data and mount layout

```text
lab_20/
├── WLW_GPintegrate/                  # Git repository and image build context
├── reference/person_a/template_ref/ # candidates; read-only at runtime
└── run/                              # inputs, outputs, cache, logs
```

Patient reports and WSI files remain outside Git and outside the image. They
may be mounted at `/data/reports:ro`; the B manifest refers to the mounted table
location, and CaseList stains store matching container-visible WSI paths.

## Production sequence

1. Put the B manifest under `run/input/`.
2. Run `prepare_case_list` once to create `run/input/pipeline/cases.json`.
3. Let `pipeline/run_pipeline.py` split the batch into one case per directory.
4. For each case, run `report_decompose` and write one D.

```bash
python -m components.person_a.prepare_case_list \
  --input ../run/input/B_report_tables.json \
  --output ../run/input/pipeline/cases.json \
  --config components/person_a/configs/report_decompose.default.json

python pipeline/run_pipeline.py \
  --case-list ../run/input/pipeline/cases.json \
  --literature ../run/input/pipeline/A_literature.json \
  --artifacts ../run/output/pipeline
```

VGHTC always uses the original Regex path. CGMH uses Regex and then MedGemma
according to the configured fallback rules. A report that truly does not state
Histologic Type is valid; no Histologic Type DxItem is emitted.

## Docker example on Windows PowerShell

PowerShell uses the backtick for line continuation:

```powershell
docker run --rm --gpus all `
  --env-file "integration/.env" `
  -v "C:/lab_20/reference:/reference:ro" `
  -v "C:/lab_20/run:/run" `
  -v "D:/hospital-data:/data/reports:ro" `
  wlw/person-a:0.8.0 `
  --input /run/input/pipeline/case-001.json `
  --output /run/output/work/D_dx_pairs.json `
  --config /app/components/person_a/configs/report_decompose.default.json
```

Do not append a backslash after a PowerShell line. The output is always under
the host sibling `run/` because `/run` is a bind mount.

## Acceptance checks

- CaseList input passes `case_list_input.schema.json` and contains one case at
  the Report Decompose boundary.
- D passes `D_dx_pairs.schema.json`.
- `case_id`, block IDs, stain IDs, stain types, filenames, and filepaths are
  preserved.
- `referenceBlock`, `referenceType`, and `referenceWSI` agree with the selected
  source stains.
- Invalid input/reference/model failures exit non-zero without partial D.
- No report, WSI, model, candidate table, token, cache, or output is committed
  or copied into the image.
