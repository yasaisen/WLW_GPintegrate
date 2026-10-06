# 乙（Person B）：Literature Preparation／Knowledge Retrieval 準備與交付

乙負責建立 `[A]` 文獻 artifact，以及依 `[D]` 產生 `[F]` retrieval chunks。目前僅有合成文獻與
空 retrieval result 的 contract stub；正式方法不得沿用 stub 結果作為研究輸出。

## 1. Input／output 規格

| Entrypoint | Input | Output |
|---|---|---|
| `components.person_b.prepare_literature` | 外部文獻來源，由 config／reference 管理 | `[A] A.Literature@2.0` |
| `components.person_b.knowledge_retrieval` | `[A] A.Literature@2.0` + `[D] D.DxPairs@2.0` | `[F] F.Chunks@2.0` |

- A 只承載 schema 允許的文字階層與 provenance，不夾帶未定義 image/base64 欄位。
- F 的 chunk 必須可追溯至 `dx_pair_id`、`literature_id` 與 `section_id`。
- retrieval runtime 不得在缺少 index/model 時靜默重建、改用其他 host 路徑或回退成未記錄的方法。
- `prepare_literature` 是主 DAG 前的獨立準備步驟；若改成接受 `--input` artifact，必須先定義其
  canonical contract。DAG runtime 的 `knowledge_retrieval` 仍遵守重複 `--input` 的 Unified CLI。

Canonical schemas：

- `contracts/schemas/A_literature.schema.json`
- `contracts/schemas/D_dx_pairs.schema.json`
- `contracts/schemas/F_chunks.schema.json`

## 2. 交換 JSON 結構示例

以下 `<...>` 代表文件中省略的 required fields；短版片段不可取代完整 canonical fixture。
`prepare_literature` 的原始 corpus 尚不是中央交換 contract，因此來源格式必須由乙的 adapter 與 README
明確版本化；跨元件交換從 `[A]` 開始。

### Literature preparation source：乙自行版本化的外部來源

```json
{
  "source_version": "<owner-defined version>",
  "documents": [
    {
      "source_idx": 0,
      "title": "Synthetic literature",
      "sections": [
        {
          "section_idx": 0,
          "title": "Example",
          "text": "Synthetic text for contract testing."
        }
      ]
    }
  ]
}
```

這只是 adapter 輸入示意，不得標成 `[A]`。正式交付需說明來源 schema、revision 與如何轉換為 A。

### Literature preparation output：`[A] A.Literature@2.0`

```json
{
  "contract": "A.Literature",
  "schema_version": "2.0",
  "artifact_id": "A-corpus-v1",
  "producer": "person-b/literature-preparation:<version>",
  "payload": {
    "corpus": {
      "corpus_id": "corpus-v1",
      "title": "Synthetic literature",
      "source_file": "synthetic-source.json",
      "source_path": "reference/person_b/checkpoint/synthetic-source.json",
      "sha256": "<source sha256>",
      "source_size_bytes": 123,
      "literature_count": 1
    },
    "literature_list": [
      {
        "literature_id": "lit-001",
        "source_idx": 0,
        "level": 1,
        "title_list": ["Synthetic literature", null, null, null],
        "title": "Synthetic literature",
        "href": null,
        "sections": [
          {
            "section_id": "sec-001",
            "section_idx": 0,
            "title": "Example",
            "text": "Synthetic text for contract testing."
          }
        ]
      }
    ]
  }
}
```

### Knowledge Retrieval second input：`[D] D.DxPairs@2.0`

```json
{
  "contract": "D.DxPairs",
  "schema_version": "2.0",
  "artifact_id": "D-case-001",
  "case_id": "case-001",
  "producer": "person-a/report-decompose:<version>",
  "payload": {
    "data_mode": "inference",
    "DxItem_list": ["Histologic_Type"],
    "case_list": [
      {
        "case_id": "case-001",
        "structured_report": {
          "DxItems": {
            "Histologic_Type": {
              "dx_pair_id": "case-001-dx-001",
              "DxResultTxt": "<retrieval query source>",
              "<其餘 DxItem fields>": "見 metadata_case_payload.schema.json"
            }
          }
        },
        "<其餘 metadata-shaped case fields>": "見 metadata schema"
      }
    ]
  }
}
```

### Knowledge Retrieval output：`[F] F.Chunks@2.0`

```json
{
  "contract": "F.Chunks",
  "schema_version": "2.0",
  "artifact_id": "F-case-001",
  "case_id": "case-001",
  "producer": "person-b/knowledge-retrieval:<version>",
  "payload": {
    "corpus_id": "corpus-v1",
    "knowledge_base": {
      "knowledge_base_id": "kb-v1",
      "archive_path": "reference/person_b/checkpoint/kb-v1",
      "archive_sha256": "<archive sha256>",
      "corpus_sha256": "<same corpus sha256 as A>",
      "embedding_model_path": "reference/person_b/checkpoint/embedding-model",
      "embedding_model_sha256": "<model sha256>",
      "document_count": 1,
      "max_tokens": 512,
      "query_max_tokens": 128,
      "retrieval_mode": "hybrid",
      "top_k": 1,
      "candidate_k": 1,
      "hybrid_weights": {"dense": 0.5, "sparse": 0.5}
    },
    "chunks": [
      {
        "chunk_id": "chunk-001",
        "dx_pair_id": "case-001-dx-001",
        "literature_id": "lit-001",
        "section_id": "sec-001",
        "source_idx": 0,
        "section_idx": 0,
        "title_list": ["Synthetic literature", null, null, null],
        "literature_title": "Synthetic literature",
        "section_title": "Example",
        "source_href": null,
        "text": "Synthetic text for contract testing.",
        "indexed_token_count": 6,
        "retrieval_rank": 1,
        "dense_score": 0.8,
        "dense_rank": 1,
        "sparse_score": 0.7,
        "sparse_rank": 1,
        "relevance_score": 0.9
      }
    ]
  }
}
```

交換 linkage 為 `A.corpus_id/literature_id/section_id`、`D.case_id/dx_pair_id` 與 F 中對應欄位。

## 3. 打包準備

```text
WLW_GPintegrate/components/person_b/       # 程式與非敏感設定
reference/person_b/checkpoint/             # embedding model、index、corpus snapshot 等大型資產
reference/person_b/template_ref/           # 可版本化的檢索模板或 mapping
run/input/pipeline/A_literature.json        # pipeline 共用 A
run/output/pipeline/cases/<case_id>/        # 每案 F 與後續 artifact
```

- 環境：Dockerfile、requirements；模型 framework 與 binary dependency 固定版本。
- 超參數：retrieval mode、top-k、token limit、batch size、index filter 等只放 configs。
- 程式：corpus adapter、index builder、retriever 分層，避免 runtime 隱式修改 reference。
- 外部參考：corpus、embedding model、index archive 放 `reference/person_b/`，不進 image。
- 外部資產 manifest 至少記錄 corpus/index/model 的 revision、SHA-256、相依關係與預期檔名。

## 4. Unified CLI

主 DAG 的容器介面：

```bash
component \
  --input /input/A_literature.json \
  --input /input/D_dx_pairs.json \
  --output /output/F_chunks.json \
  --config /config/knowledge_retrieval.yaml
```

目前 Python／JSON config 形式：

```bash
python pipeline/run_prepare_literature.py

python -m components.person_b.knowledge_retrieval \
  --input ../run/input/pipeline/A_literature.json \
  --input ../run/output/work/D_dx_pairs.json \
  --output ../run/output/work/F_chunks.json \
  --config components/person_b/configs/example.json
```

所有 input 先依 contract 辨識，不依參數位置；corpus/index digest 不一致、模型缺失、D case 不合法或
輸出驗證失敗時必須 non-zero exit。

## 5. Dockerfile／requirements.txt

目前 stub 是 Python 3.12、CPU、standard library。正式版本若加入向量資料庫、embedding framework、
GPU runtime 或原生 binary，必須全部固定於 requirements 與 Dockerfile，並從 clean machine 建置：

```bash
docker build --no-cache \
  -f components/person_b/Dockerfile \
  -t wlw/person-b:<version> .
```

image 內不得包含 corpus、index、checkpoint、token 或 cache。必須分別驗證 index preparation 與
case-level retrieval；README 說明 CPU fallback、GPU 數量、最低 VRAM、RAM 峰值、磁碟需求與 timeout。

## 6. Canonical examples

至少交付：

```text
components/person_b/examples/
├── prepare_literature/
│   ├── source.synthetic.json
│   ├── A_literature.expected.json
│   ├── config.example.json
│   └── README.md
└── knowledge_retrieval/
    ├── A_literature.valid.json
    ├── D_dx_pairs.valid.json
    ├── F_chunks.expected.json
    ├── config.example.json
    └── README.md
```

範例文獻必須是合成或可再散布內容，不得擷取受限制 corpus。expected F 應固定排序／tie-break 規則；
若 backend 非決定性，README 必須定義容許誤差與必要欄位。

## 7. README 必填資訊

列出 component version、A/F schema version、corpus 名稱與 revision、retrieval/index 方法、embedding
模型與 revision、Python/framework、GPU/VRAM 或 CPU/RAM、checkpoint/index logical path 與 SHA-256、
index 建置命令、runtime CLI、Docker build/run、canonical example、失敗條件與已知限制。

## 8. 提交檢查

- [ ] A 與 F 通過 canonical schema，F 的來源 ID 均能追回 A/D。
- [ ] corpus、model、index 與 config digest 關係已記錄並可驗證。
- [ ] clean-machine 可建 index、啟動 runtime，且不依賴 host cache。
- [ ] source、configs、examples、tests、Dockerfile、requirements、README、PREPARATION 已提交。
- [ ] 外部資產只放 `reference/person_b/`；corpus/index/checkpoint 本體不提交至 Git 或 image。
- [ ] 根目錄 contract 與 pipeline tests 全部通過。
