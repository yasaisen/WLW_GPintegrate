# Query Generation implementation guide

## Contract

```text
D.DxPairs@2.0 + F.Chunks@2.0
              └─ query_generation.py
                    └─ G.VisualAttributeQueries@2.0
```

D and F must have the same `case_id`. Chunks are joined to diagnoses by
`dx_pair_id`, never by array position. G preserves the D case/diagnosis
structure and adds `visualAttrQueries` to each DxItem.

## Backends

- `reference`: maps Histologic Type to the mounted type-level visual criteria.
- `learnable_soft_prompt`: uses Gemma plus the trained `.pt` soft prompt and
  exactly the configured number of F chunks (currently three).
- `example`: deterministic empty queries for public contract tests only.

`query_generation.py` orchestrates the contract. `reference_data.py` loads the
mapping and visual reference tables. `learnable_query_generator.py` loads Gemma,
the soft-prompt checkpoint, and the attribute vocabulary, then validates the
generated controlled values before merging them into G.

## External files

```text
reference/person_a/
├── checkpoint/soft_prompt_best.pt
└── template_ref/
    ├── Histologic_Type_mappingTable.json
    ├── candidateReference.json
    ├── [typeLevel]visualAttrs_v1.2.1_2603241656.json
    └── chunks_with_attribute.json
```

These assets are mounted at `/reference:ro`. Their SHA-256 values and revisions
are recorded in `external-assets.yaml`. Hugging Face downloads are cached in the
writable sibling `run/cache/huggingface`; `HF_TOKEN` is supplied at runtime.

## CLI

Reference mapping:

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/query_generation.default.json
```

Learnable soft prompt:

```bash
python -m components.person_a.query_generation \
  --input ../run/output/work/D_dx_pairs.json \
  --input ../run/output/work/F_chunks.json \
  --output ../run/output/work/G_queries.json \
  --config components/person_a/configs/query_generation.learnable.json
```

In Docker, override the default Report Decompose entrypoint:

```bash
docker run --rm --gpus all \
  --env-file integration/.env \
  -v "$(pwd)/../reference:/reference:ro" \
  -v "$(pwd)/../run:/run" \
  --entrypoint python \
  wlw/person-a:0.8.0 \
  -m components.person_a.query_generation \
  --input /run/output/work/D_dx_pairs.json \
  --input /run/output/work/F_chunks.json \
  --output /run/output/work/G_queries.json \
  --config /app/components/person_a/configs/query_generation.learnable.json
```

## Acceptance checks

- D and F pass their canonical schemas and share `case_id`.
- The learnable backend receives at least three F chunks for each mapped
  Histologic Type DxPair.
- Every emitted query points to the correct `dx_pair_id` and lists the actual
  `chunk_ids` used.
- Generated values are in the mounted controlled vocabulary.
- G passes `G_visual_attribute_queries.schema.json` and preserves D metadata.
- Missing reference/checkpoint/model/GPU failures exit non-zero without a
  partial G output.
