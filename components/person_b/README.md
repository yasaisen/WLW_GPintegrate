# Person B implementation slot

This directory contains contract-only examples, not a literature indexing or retrieval system.

- `prepare_literature`: synthetic example → `A.Literature@2.0`
- `knowledge_retrieval`: `A.Literature@2.0` + `D.DxPairs@2.0` → `F.Chunks@2.0`

The preparation entrypoint emits one synthetic record. The retrieval entrypoint emits an empty
chunk list and does not load a corpus, index, embedding model, or checkpoint.

```bash
python pipeline/run_prepare_literature.py
```
