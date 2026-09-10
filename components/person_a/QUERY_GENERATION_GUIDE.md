# Person A Query Generation（D + F → G）

## 正式資料流

```text
D.DxPairs（診斷文字與 Histologic Type）
              +
F.Chunks（乙檢索出的文獻文字）
              │
              ▼
google/gemma-3-1b-it + 64-token soft-prompt checkpoint
              │
              ▼
嚴格 JSON 解析與訓練 vocabulary 驗證
              │
              ▼
G.VisualAttributeQueries v2.0
```

`query_generation.py` 保留 repo 原本的 `--input/--output/--config` CLI。它不會
import 乙的內部程式，只讀取乙交付的 F artifact。

## 兩種 backend

- `reference`：不載入模型，維持原本 type-level mapping 行為，供 contract/E2E
  fixture 測試使用。
- `learnable_soft_prompt`：正式模型模式，使用 Nano5 訓練的 Gemma 3 soft prompt
  產生 Attribute JSON。

正式模式 config 是 `configs/query_generation.learnable.json`。中央
`integration/compose.yaml` 不需要因本次元件實作而修改；正式部署時將同樣的 CLI
參數與 mounts 交給 Docker、Singularity 或排程器。

## 模型輸出如何放進 G

Nano5 模型輸出的 leaf 是一組選定值或 `Not_Mentioned`：

```json
{"Cellular_and_Nuclear": {"Cell_Pleomorphism": ["Monomorphic"]}}
```

G 與 Person D 使用的格式則要求每個 option 都有 condition。本 adapter 提供兩種
明示的轉換策略：

- `condition_merge_mode=replace`：先把所有 option 設成
  `unselected_value_condition`，再把模型選到的值設成
  `selected_value_condition`。
- `condition_merge_mode=overlay`：保留 type-level 原條件，只覆蓋模型選到的值。

目前 learnable config 使用：選到的值為 `Must_True`，沒有選到的值為
`Not_Mentioned`。這是可在 config 調整的 adapter 規則；若整合負責人指定其他臨床
語意，只改 config，不需修改中央 schema。

## 外部檔案

下列內容不 COPY 進 image，也不提交 Git：

- `/models/person-a/soft_prompt_best.pt`
- `/models/huggingface/` 下的 Hugging Face cache
- 真實報告、WSI 與其他病人資料
- Hugging Face Token

下列 reference 由唯讀 mount 提供：

- `/references/Histologic_Type_mappingTable.json`
- `/references/candidateReference.json`
- `/references/[typeLevel]visualAttrs_v1.2.1_2603241656.json`
- `/references/chunks_with_attribute.json`

Token 只透過 `HF_TOKEN` 環境變數提供，不能寫進 `.sbatch`、config、Dockerfile 或
Git 歷史。

## F chunk 數量

目前 soft prompt 的訓練條件固定為每筆 3 個 chunks，所以正式 backend 也要求每個
Histologic Type DxPair 至少有 3 個 F chunks，並使用 F 中前 3 筆。若不足 3 筆，
程式以 non-zero exit code 失敗，不會複製文字或捏造資料湊數。

repo 現有 demo 的 Person B `top_k=1` 可以繼續搭配 `reference` backend 測 contract；
正式 learnable pipeline 必須由上游提供 3 個 chunks，或在共同確認後重新訓練成可接受
可變數量 chunks 的模型。

## Docker 單獨執行範例

```bash
docker run --rm --gpus all \
  --env-file ../.env \
  -v /host/artifacts:/artifacts \
  -v /host/references:/references:ro \
  -v /host/models/person-a:/models/person-a:ro \
  -v /host/hf-cache:/models/huggingface \
  --entrypoint python \
  wlw/person-a:0.7.0 \
  -m components.person_a.query_generation \
  --input /artifacts/D_dx_pairs.json \
  --input /artifacts/F_chunks.json \
  --output /artifacts/G_queries.json \
  --config /app/components/person_a/configs/query_generation.learnable.json
```

輸出會由 `write_artifact` 依中央 `G.VisualAttributeQueries` v2.0 schema 驗證；模型輸出
若不是完整 JSON、欄位不完整或值不在訓練 vocabulary 中，都會直接失敗。

## 尚需補齊的可重現資訊

Nano5 訓練程式未記錄 Hugging Face model revision。正式交付前應從當時使用的 model
cache 查出 snapshot commit，填入 `model_revision`，避免日後同一 model name 指到不同
內容。
