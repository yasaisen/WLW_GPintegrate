# 乙的準備與交付清單

## 你的責任邊界

乙負責文獻知識庫與 retrieval：

```text
A.Literature ──> Knowledge Base Construction ──> versioned knowledge base
                                                   │
D.DxPairs ─────────────────────────────────────────┴─> retrieval ──> F.Chunks
```

目前 demo 為了簡單，`knowledge_retrieval.py` 每次直接從 A 建立小型 in-memory knowledge base。
正式資料量變大時，建議把「建庫」與「查詢」拆成兩個 executable，但 F 的 contract 不必因此改變。

## 需要準備的東西與放置位置

| 要準備的項目 | 放置位置 | 說明 |
|---|---|---|
| Retrieval 實作 | `components/person_b/knowledge_retrieval.py` | 讀 A、D，寫 F；正式版也可改讀外部 versioned index |
| 建庫程式（正式版） | 建議 `components/person_b/build_knowledge_base.py` | A→index；必須有獨立 CLI、版本與 build log |
| Python dependencies | `components/person_b/requirements.txt` | 放 embedding、retrieval 或 DB client 的 pinned Python packages |
| 預設 config | `components/person_b/configs/default.json` | top-k、index 名稱、retrieval 參數；不要放 credential |
| Runtime 描述 | `components/person_b/component.yaml` | 記錄 Python、CPU/RAM、是否需要 GPU、index/model revision |
| Container recipe | `components/person_b/Dockerfile` | 安裝 client/library；不要把整個文獻庫 COPY 進 image |
| A canonical input | `integration/fixtures/input/A_literature.json` | 小型、固定、可提交的假資料 |
| D canonical input | pipeline 產生的 `integration/artifacts-local/D_dx_pairs.json` | 用來驗證你接受甲的 D |
| F expected output | `integration/artifacts-local/F_chunks.json` | 每段 chunk 要保留 literature 與 dx provenance |
| A/F schemas | `contracts/schemas/A_*.json`、`F_*.json` | contract 變更先走中央審核與版本化 |

## Knowledge base 本體放哪裡

大型 index 不屬於 Git repository，也不屬於 Docker image。建議：

```text
/data/knowledge-base/
└── pathology-literature/
    └── kb-2026-08-15/
        ├── index files ...
        ├── manifest.json
        └── build-log.json
```

`manifest.json` 至少記錄：

- knowledge base ID/version
- 原始 corpus 版本或 checksum
- chunking 參數
- embedding model name/revision/hash
- 建立時間與程式版本

container 以 `/knowledge-base:ro` mount 讀取。config 記邏輯位置 `/knowledge-base/...`，不要記
`/home/某人/...`。

## F.Chunks 必須保留的 provenance

- `chunk_id`：這次交換資料中的唯一 ID。
- `dx_pair_id`：它是在回答哪一個 D。
- `literature_id`：可追回 A/corpus 的哪篇文獻。
- `text`：給甲 query generation 的實際 evidence text。
- `visual_attributes`：示範中的結構化視覺線索。
- `relevance_score`：定義分數範圍及方向；本 contract 是 0～1，越大越相關。

若真實 retrieval 另有 distance、rank、page、section 等欄位，先與 producer/consumer 討論是否
加入 F v1.x；不要塞進未定義的 `metadata` 讓每個人自行猜。

## 套件、模型、機密的分工

- Python client/library：`requirements.txt`。
- `libpq`、compiler 等 OS package：`Dockerfile`。
- embedding checkpoint：外部 `/models/person-b/...` 唯讀 mount。
- vector DB endpoint：config 或 environment variable。
- password/token：secret/environment variable，不進 Git。
- index/corpus：外部 `/data/knowledge-base/...`。

## 交付前自己跑

```bash
python3 pipeline/run_pipeline.py

python3 -m components.person_b.knowledge_retrieval \
  --input integration/fixtures/input/A_literature.json \
  --input integration/artifacts-local/D_dx_pairs.json \
  --output /tmp/F_chunks.json \
  --config components/person_b/configs/default.json

python3 -m unittest discover -s tests -v
```

## 完成定義

- 能接受 canonical D，而不 import 甲的 package。
- F 通過 schema，且每個 chunk 都能 trace 到 `dx_pair_id` 與 `literature_id`。
- knowledge base/model revision 被記錄，不依賴「目前 server 上剛好那一版」。
- 無結果、index 不存在、credential 缺失時有明確錯誤與 non-zero exit code。
- Docker image 不包含 corpus、index、credential 或大型 checkpoint。

