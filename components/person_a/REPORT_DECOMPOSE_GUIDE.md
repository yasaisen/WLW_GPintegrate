# Report Decompose

## Data flow

```text
B.ReportTables manifest
  └─ prepare_case_list.py
       └─ CaseListInput batch
            └─ pipeline fan-out
                 └─ report_decompose.py
                      └─ D.DxPairs@2.0 (one case)
```

`report_decompose.py` accepts one normalized CaseList case; it does not open
Excel directly. `prepare_case_list.py`, `table_parsers.py`, and `xlsx_reader.py`
perform the upstream Excel/CSV normalization.

VGHTC always uses the original hospital Regex. CGMH uses its Regex first and
MedGemma according to `report_decompose.default.json`. A report that does not
state Histologic Type is valid and does not emit that DxItem.

## Data layout

```text
lab_20/
├── WLW_GPintegrate/                  # repository and image build context
├── reference/person_a/template_ref/ # read-only candidates/mappings
└── run/                              # inputs, outputs, cache, logs
```

Reports and WSI files remain outside Git and the image. Mount them read-only,
for example at `/data/reports`. The B manifest points to mounted table files;
CaseList stains contain the corresponding container-visible WSI paths.

## Run

Create the multi-case CaseList:

```bash
python -m components.person_a.prepare_case_list \
  --input ../run/input/B_report_tables.json \
  --output ../run/input/pipeline/cases.json \
  --config components/person_a/configs/report_decompose.default.json
```

Run the repository contract demo. This command demonstrates fan-out but uses
the checked-in example configs for all components:

```bash
python pipeline/run_pipeline.py \
  --case-list ../run/input/pipeline/cases.json \
  --literature ../run/input/pipeline/A_literature.json \
  --artifacts ../run/output/pipeline
```

Run one case directly:

```bash
python -m components.person_a.report_decompose \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/D_dx_pairs.json \
  --config components/person_a/configs/report_decompose.default.json
```

## Docker on Windows PowerShell

```powershell
docker run --rm --gpus all `
  --env-file "integration/.env" `
  -v "C:/lab_20/reference:/reference:ro" `
  -v "C:/lab_20/run:/run" `
  -v "D:/hospital-data:/data/reports:ro" `
  wlw/person-a:0.9.0 `
  --input /run/input/pipeline/case-001.json `
  --output /run/output/work/D_dx_pairs.json `
  --config /app/components/person_a/configs/report_decompose.default.json
```

Replace host paths with local paths. Do not append a backslash after a
PowerShell backtick. D is written to the host `run/` mount.

## Acceptance checks

- CaseList input passes `case_list_input.schema.json` and contains one case at
  the Report Decompose boundary.
- D passes `D_dx_pairs.schema.json`.
- Case, block, stain, WSI identity, and filepaths are preserved.
- `referenceBlock`, `referenceType`, and `referenceWSI` match the selected stains.
- Invalid input, reference, or model failures exit non-zero without a partial D.
- No report, WSI, model, token, cache, or output is committed or copied into the
  image.
