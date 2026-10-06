# Person E configuration

`default.json` uses the deterministic fixture backend for repository contract
and pipeline tests. It does not run a neural network.

`native.json` is the active real CLEE configuration; `native.example.json` documents the same shape.
Reference paths must stay below sibling `reference/person_e/`, and runtime image roots below sibling
`run/`:

| Key | Meaning |
|---|---|
| `checkpoint_dir` | Directory containing `config.json`, `[checkpoint]best_model.json`, the prefix checkpoint, and threshold bundles. |
| `backend.model.weight_path` | Parent directory of `medgemma-1.5-4b-it` and, by default, the embedding file named by the checkpoint config. |
| `backend.model.embedding_path` | Optional explicit embedding `.pt` file. `null` resolves its basename below `weight_path`. |
| `image_root` | Base for relative WSI or ROI image paths. Absolute artifact paths do not use it. |
| `max_roi_dxitem_inputs_per_forward` | Positive hierarchical chunk limit. It never samples or drops ROIs. |

`backend.model.device` is normally `cuda`. `dtype` accepts `bfloat16`,
`float16`, or `float32`; `attn_implementation` is passed to Transformers and
defaults to `sdpa`. Set `pp_num_gpus` only when the requested number of CUDA
devices is visible; Transformers distributes the frozen model with its device
map.

Set `wlw_supported_dx_items` to `null` to use the checkpoint's active label
space as the authority. The current checkpoint therefore enables both
`Histologic_Type` and `Microcalcification`. A deployment may provide an
explicit list to narrow, but never expand, checkpoint support. The threshold
bundle must be validation calibrated and match the best checkpoint epoch.
