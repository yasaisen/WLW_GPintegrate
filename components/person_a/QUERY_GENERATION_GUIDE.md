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
- `learnable_soft_prompt`: uses Gemma plus the trained Stage 2 condition `.pt`
  soft prompt and exactly the configured number of F chunks (currently three).
  Its output is a complete group/attribute/option tree. Every option is mapped
  to `Must_True`, `Must_False`, `High_Possibly_True`, `Low_Possibly_True`,
  `Negligible`, or `Not_Mentioned`.
- `example`: deterministic empty queries for public contract tests only.

`query_generation.py` orchestrates the contract. `reference_data.py` loads the
mapping and visual reference tables. `learnable_query_generator.py` loads Gemma,
the soft-prompt checkpoint, and the condition-annotated chunk reference. It
validates the complete generated option-condition tree before replacing the
`conditions` maps in G. The training and evaluation scripts are provenance for
this runtime logic; they are not invoked when generating G.

## External files

```text
reference/person_a/
├── checkpoint/soft_prompt_stage2_64SP_50epoch_chunk_option_conditions_retrieval_mixed_best.pt
└── template_ref/
    ├── Histologic_Type_mappingTable.json
    ├── candidateReference.json
    ├── [typeLevel]visualAttrs_v1.2.1_2603241656.json
    └── chunks_with_attribute_condition.json
```

These assets are mounted at `/reference:ro`. Their SHA-256 values and revisions
are recorded in `external-assets.yaml`. Hugging Face downloads are cached in the
writable sibling `run/cache/huggingface`; `HF_TOKEN` is supplied at runtime.

The runtime implementation was aligned to these Nano5 sources without copying
the training loop into the production entrypoint:

- `train_stage2_condition.py`, SHA-256
  `41c100f9ee42a0e3b5140e42e4b93c77b056ae925e40ed88dcc43d49dca9fcb2`
- `evaluate_stage2_condition.py`, SHA-256
  `5a93e2b5577a4f47233d445618480fdbb436a86849f0cf132fc16fc2bf89e06b`

Those two scripts train/evaluate the soft prompt. Production inference only
loads Gemma, the mounted `.pt`, D, F, and the mounted condition reference.
The mounted checkpoint metadata is checked against the condition reference at
startup: model name, target format, type-level SHA, annotated-chunk SHA,
condition vocabulary, and the complete option tree must agree. The current
checkpoint is shape `64 × 1152`, best epoch `21`.

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
  wlw/person-a:0.9.0 \
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
- Person B does not need to expose its internal code to Person A. It only needs
  to provide a valid F artifact whose chunks contain `dx_pair_id`, `chunk_id`,
  and non-empty `text`; Person A uses the first three chunks for that DxPair.
- Every emitted query points to the correct `dx_pair_id` and lists the actual
  `chunk_ids` used.
- The generated tree contains every canonical option exactly once, and every
  leaf is one of the six legal condition strings.
- G passes `G_visual_attribute_queries.schema.json` and preserves D metadata.
- Missing reference/checkpoint/model/GPU failures exit non-zero without a
  partial G output.
