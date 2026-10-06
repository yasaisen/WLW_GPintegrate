# Person A: Report Decompose and Query Generation

Component version: `0.8.0`

This directory contains the Person A research implementation behind the shared
single-case CLI. It preserves the central contracts and does not store reports,
WSIs, model weights, reference tables, credentials, caches, or runtime outputs.

## Contract boundaries

- `report_decompose`: `CaseListInput@1.0` → `D.DxPairs@2.0`
- `query_generation`: `D.DxPairs@2.0` + `F.Chunks@2.0` →
  `G.VisualAttributeQueries@2.0`

Each component invocation handles exactly one case. `pipeline/run_pipeline.py`
splits a multi-case CaseList and invokes the components once per case.
`B.ReportTables@1.0` is an upstream ingestion manifest, not the runtime input of
Report Decompose. For the existing hospital Excel layout,
`components.person_a.prepare_case_list` converts B to canonical CaseList first.

## Implemented behavior

- VGHTC report extraction: original hospital Regex only.
- CGMH report extraction: hospital Regex first, then MedGemma according to the
  configured fallback behavior.
- Histologic Type classification: `UDH`, `FEA`, `ADH`, `DCIS`, `IC`, `OTHER`,
  and `AMBIGUOUS`; other diagnostic results remain free text.
- D preserves the source case, block, stain, WSI identity, and WSI filepath.
- Query Generation supports reference mapping and the Nano5 learned soft-prompt
  backend for Gemma.

## Runtime

- Python 3.11
- PyTorch 2.6.0 + CUDA 12.4 wheel
- Transformers 5.16.1, Accelerate 1.14.0, bitsandbytes 0.50.1
- Report Decompose with MedGemma: one CUDA GPU; current tested target is at
  least 4 GB VRAM using NF4 4-bit loading and CPU offload.
- Learnable Query Generation: one CUDA GPU plus mounted soft-prompt checkpoint.

The base models are downloaded from Hugging Face into `/run/cache/huggingface`.
The token is read from `HF_TOKEN`; it is never stored in this repository.

## External assets

The sibling directory is mounted read-only as `/reference`:

```text
reference/person_a/
├── checkpoint/soft_prompt_best.pt
└── template_ref/
    ├── DxStructuredCandidates_integrated.json
    ├── Histologic_Type_mappingTable.json
    ├── candidateReference.json
    ├── [typeLevel]visualAttrs_v1.2.1_2603241656.json
    └── chunks_with_attribute.json
```

Exact revisions, SHA-256 values, licenses, and mount paths are recorded in
`external-assets.yaml`. These files are intentionally not copied into the image
or committed to Git.

## CLI

Commands below run from the repository root. All JSON input/output paths must
be under the sibling `run/` directory; config files stay under
`components/person_a/configs/`.

Legacy hospital tables to a multi-case CaseList batch:

```bash
python -m components.person_a.prepare_case_list \
  --input ../run/input/B_report_tables.json \
  --output ../run/input/pipeline/cases.json \
  --config components/person_a/configs/report_decompose.default.json
```

One normalized case to D:

```bash
python -m components.person_a.report_decompose \
  --input ../run/input/pipeline/case-001.json \
  --output ../run/output/work/D_dx_pairs.json \
  --config components/person_a/configs/report_decompose.default.json
```

D and F to G with the learned backend:

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/query_generation.learnable.json
```

## Docker

Build from the repository root:

```bash
docker build --no-cache \
  -f components/person_a/Dockerfile \
  -t wlw/person-a:0.8.0 .
```

Run one CaseList case. The standard sibling mounts are read-only reference data
and writable runtime state:

```bash
docker run --rm --gpus all \
  --env-file integration/.env \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  wlw/person-a:0.8.0 \
  --input /run/input/pipeline/case-001.json \
  --output /run/output/work/D_dx_pairs.json \
  --config /app/components/person_a/configs/report_decompose.default.json
```

Hospital report/WSI directories may be mounted separately, for example at
`/data/reports:ro`; the generated CaseList must store the matching container
filepath. WSI files are referenced by path and are never embedded in D.

## Examples and tests

- `examples/report_decompose/`: valid/invalid CaseList, config, expected D.
- `examples/query_generation/`: valid D/F, config, expected G.

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s components/person_a/tests -v
docker compose -f integration/compose.yaml config --quiet
```

## Known failure conditions

The CLI exits non-zero and must not leave a partial output when the input is not
schema-valid, contains more than one case, has unknown contract versions, mixes
case IDs, requests an unknown DxItem, lacks a declared reference/checkpoint, or
cannot load the configured GPU/model. Reports without a Histologic Type are
valid; they simply do not produce that DxItem.

## Change log

- `0.8.0`: aligned with the sibling `reference/` and `run/` layout; changed
  Report Decompose from B batch input/D index output to single-case
  `CaseListInput@1.0`/`D.DxPairs@2.0`; kept B-to-CaseList as an explicit upstream
  adapter; removed external assets and the production B manifest from the image.
- `0.7.0`: integrated hospital table parsing, Regex/MedGemma report extraction,
  seven-class Histologic Type, and learnable Query Generation.
