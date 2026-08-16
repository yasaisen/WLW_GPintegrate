# 戊的準備與交付清單

## 你的責任邊界

戊負責將文字診斷 pair 與配對後的影像 evidence 送入 CLEE，產生整體核心框架的最終 ROI：

```text
D.DxPairs ─────────────┐
                        ├─> CLEE ──> I.CLEESelectedROIs  （核心最終產物）
H.MatchedROIs ─────────┘                  │
                                         └─> DRGVLM 等 evaluation consumers
```

DRGVLM 不是戊的 CLEE component，也不是核心 DAG 的最後一步。它只是拿 I 做實驗的方法之一；
未來換成其他 VLM、人工閱片或統計分析時，核心 A～I pipeline 不應因此改動。

## 需要準備的東西與放置位置

| 要準備的項目 | 放置位置 | 說明 |
|---|---|---|
| CLEE 實作 | `components/person_e/clee.py` | 讀 D/H、寫最終 artifact；保留統一 CLI |
| Python dependencies | `components/person_e/requirements.txt` | 只放 CLEE 的直接依賴；DRGVLM 有自己的 evaluation environment |
| OS/CUDA dependencies | `components/person_e/Dockerfile` | 若需要 GPU/CUDA，需改 base image 並記錄相容性 |
| 預設 config | `components/person_e/configs/default.json` | threshold、aggregation、fallback、model revision |
| Runtime/model manifest | `components/person_e/component.yaml` | Python、CPU/RAM/GPU、timeout、entrypoint |
| D input example | `integration/artifacts-local/D_dx_pairs.json` | 由甲產生 |
| H input example | `integration/artifacts-local/H_matches.json` | 由丁產生；可能為空 matches |
| 最終 expected output | `integration/artifacts-local/I_selected_rois.json` | CLEE 選出的 ROI references 與 provenance |
| D/H/I schemas | `contracts/schemas/` | I 是核心最終 contract |
| Model checkpoint | host `/models/person-e/<model>/<revision>/` | 唯讀 mount；不放 image |
| DRGVLM 程式與環境 | `evaluation/drgvlm/` | 與 person_e image/environment 分離 |
| Evaluation output | 建議 `/runs/<run_id>/evaluation/drgvlm/` | 不覆寫 I 或中間 D/H artifact |

## D 與 H 如何對齊

只能使用 stable ID join：

```text
D.dx_pair_id == H.dx_pair_id
```

不可假設 `D.dx_pairs[0]` 對應 `H.matches[0]`。H 可能：

- 同一個 diagnosis 對應多個 ROI。
- 某個 diagnosis 沒有 ROI。
- matching 排序因模型版本改變。

I 應保留 `match_id`、`query_id`、`roi_id`、score、WSI URI、座標及解析度，讓 DRGVLM 或其他
consumer 能重建同一個 ROI，也讓 error analysis 一路追回 D/H。

## 要先定義的科學語意

- H 沒有 match 時，I 應是空 `selected_rois`，還是要輸出 rejection record？
- 多 ROI 如何篩選與排序？threshold、top-k 或 learned CLEE score？
- `clee_score` 是否 calibration 過？能不能跨版本比較？
- I 除 authoritative WSI reference 外，是否也需要 optional materialized crop URI？
- 哪些欄位屬於模型輸出，哪些是原始 report 的 observation？

這些選擇寫入 config 與方法文件；不要隱藏在 hard-coded if/else。

## I 與下游 DRGVLM 的邊界

I 的最低必要內容是：

```text
selection_id + case_id + dx_pair_id + roi_id + image_uri + coordinate + resolution
```

由 DRGVLM 按座標讀取 pixels。若 CLEE 已產生 dynamic-MPP PNG，可在 I 提供 `roi_image_uri` 作
cache；仍應保留 WSI reference/level-0 coordinate 作 authoritative provenance。DRGVLM 自己的 prompt、
model weight、config 與 metrics 放 `evaluation/drgvlm/` 及 `/runs/<run_id>/evaluation/`，不要混入 I。

## 交付前自己跑

```bash
python3 pipeline/run_pipeline.py

python3 -m components.person_e.clee \
  --input integration/artifacts-local/D_dx_pairs.json \
  --input integration/artifacts-local/H_matches.json \
  --output /tmp/I_selected_rois.json \
  --config components/person_e/configs/default.json

python3 -m unittest discover -s tests -v
```

## 完成定義

- canonical D/H 能執行，最終 I 通過 schema。
- join 只靠 stable IDs，不靠 array index 或檔名順序。
- H 空 matches 有明確、經團隊同意的科學語意。
- 每個 selected ROI 能 trace 到 D、G、H、E 與原 WSI。
- DRGVLM 不被 import 進 CLEE；它只透過 I contract 消費結果。
- image 不包含資料、credential 或大型 checkpoint。
