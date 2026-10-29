# WLW_GPintegrate 正式整合修正與執行報告

日期：2026-10-29（Asia/Taipei）

## 1. 結論

已完成本次要求的程式、設定與路徑修正，並以無參數 production 預設正式執行：

```bash
python /home/yasaisen/Desktop/27_research/research_main_v3/lab_23/WLW_GPintegrate/pipeline/run_pipeline.py
```

最終執行 exit code 為 0；同一次不中斷 run 完成 `S1202317`、`S1226464`、`S1129952`
三個案例及 D→I 全部六個 stage。這不是 smoke、preflight 或 example profile：runner 使用 Docker、
真實 MRXS、正式 sibling `reference/` 資產、正式 literature corpus 與 production configs。

本次特別要求亦已落實：

- Person A Query Generation 為真正 `learnable_soft_prompt`，Gemma 完整放在單張 GPU，
  `device_map_strategy=single_device`、`gpu_memory_limit=null`，沒有 CPU offload。
- Person D 使用 `native.json`，`matching.enable=true`；三案均實際載入 PLIP、CONCH 與 440 張
  few-shot example，沒有 `matching_disabled_passthrough`。
- Person C 使用真正 `region_proposal`、CONCH、BCSS vocabulary 與 vMF；不是 example stub。
- Person B 使用 dense retrieval 與正式 `rag_database`／embedding assets。
- Person E 使用 native config 並在每案執行；但本批沒有 ROI 通過 Person D，因此依契約回報
  `skipped_no_eligible_rois`，沒有進行 CLEE model forward。詳見第 9 節限制。

## 2. 驗收範圍與正式執行定義

本次以以下條件判定「正式」：

1. `pipeline/run_prepare_literature.py` 與 `pipeline/run_pipeline.py` 都使用預設 production profile。
2. production 必須使用 Docker executor，容器以 `/reference:ro` 與 `/run` 掛載 sibling 目錄。
3. 各元件使用自己的正式 config 與 external reference/checkpoint；不得以 example、smoke、stub
   或 matching-disabled profile 代替。
4. 輸入為 `run/input/pipeline/cases.json` 中三案及對應 MRXS。
5. `A.Literature` 與每案 D/E/F/G/H/I 都必須通過 canonical schema。
6. 最終 runner 必須寫出包含三案、18 筆 stage execution 的 `run_manifest.json`。

## 3. 實測環境

| 項目 | 實測值 |
|---|---|
| OS／kernel | Linux 6.8.0-138-generic x86_64 |
| GPU | NVIDIA GeForce RTX 4090 |
| VRAM | 24,564 MiB |
| NVIDIA driver | 580.178.04 |
| 主機 RAM | 94 GiB（最終驗收時 available 約 80 GiB） |
| Swap | 41 GiB |
| Docker Server | 29.1.3 |
| 檔案系統可用空間 | 最終約 113 GiB |

正式映像與最終 image ID：

| 元件 | Image | Image ID |
|---|---|---|
| Person A | `wlw/person-a:0.9.0-lab23-production` | `sha256:d3546f4ecb5564321835866df7d26b182bc68d500ff48e819e1f6e4fd9c29608` |
| Person B | `wlw/person-b:0.5.0-lab23-production` | `sha256:032f5aebf31f4c90be2a81c3a67740e1bc5b453d7e71204c113e759546717fbe` |
| Person C | `wlw/person-c:0.1.0-lab23-production` | `sha256:d492da40e18317cbe41bfd3b0589ab12cd6f60e239048b7cfebbb663ec81a791` |
| Person D | `wlw/person-d:0.2.0-lab23-production` | `sha256:24225bdc63759c3b6c07bbbee110bc4f872b81a00607ed29de48261bb221307e` |
| Person E | `wlw/person-e:1.1.0-lab23-production` | `sha256:31ed637b9ae295566922c6d2d1d4e6a7754301da0e95b5a0a2b43fa3469027e8` |

## 4. 最終設定與路徑對應

`pipeline/run_pipeline.py`、`integration/compose.yaml` 與元件文件已統一到以下正式對應：

| Stage | Config | 重要模式／資產 |
|---|---|---|
| A Report Decompose | `components/person_a/configs/report_decompose.default.json` | hospital-routed；VGHTC 走正式 regex extractor |
| C Interest Pattern | `components/person_c/configs/region_proposal.json` | `mode=region_proposal`；Person C CONCH checkpoint、BCSS vocab |
| B Knowledge Retrieval | `components/person_b/configs/dense.default.json` | `mode=dense`；正式 KB、MedEmbed 與 `reference/person_b/rag_database` |
| A Query Generation | `components/person_a/configs/query_generation.production.json` | `learnable_soft_prompt`、Gemma 3 1B、64-token soft prompt、single GPU、canonical diagnosis retry |
| D Visual Filter | `components/person_d/configs/native.json` | PLIP+CONCH、440 files few-shot、`matching.enable=true` |
| E CLEE | `components/person_e/configs/native.json` | `backend.mode=native`、epoch 223 checkpoint／threshold bundle |

正式 profile 載入時增加 fail-fast 檢查：config 不存在、模式不是上述正式值、A 不是
`single_device`、A 未啟用 canonical retry、或 D 未開 matching 都會在執行元件前失敗。

其他路徑修正：

- Person C production 原先指向已不存在的 `default.json`／`demo.json`，改為
  `region_proposal.json`；example profile 改為現有 `example.json`。
- Person D 新增正式 `native.json`；`native.example.json` 保持 matching-disabled，只供受控整合 fixture，
  無參數 production 不會選它。
- Person B corpus 文件／manifest 路徑由錯誤的 checkpoint 子路徑修正為實際
  `reference/person_b/rag_database`。
- `run_prepare_literature.py` 增加 config／source 存在檢查與 production mode 檢查。
- 容器 config path 在組 command 前確認檔案存在，避免 Docker 內才出現模糊錯誤。

## 5. 主要程式修正

### 5.1 Person A：真實 soft prompt 與可稽核重試

新增 `query_generation.production.json`，保留固定的 Gemma revision、soft-prompt checkpoint、
condition vocabulary 與 8,192 input/output token 上限，並使用 `single_device`。沒有設定 GPU／CPU
offload memory cap。

第二案的原始病理敘述會使模型在第一個 attribute group 後進入重複並產生非法 JSON。處理方式不是
修字串、reference mapping 代填或降級後端，而是：

1. 先用 raw `DxResultRawTxt` 執行相同模型與 soft prompt。
2. 嚴格 JSON／canonical schema／condition vocabulary 驗證不通過時，拒絕該輸出。
3. 若 production config 明示 `retry_with_canonical_dx=true`，改用已驗證 histologic mapping 的
   canonical diagnosis，再以相同模型、soft prompt 與三個 retrieval chunks 重跑。
4. G provenance 記錄每次 input strategy、accepted/rejected、response SHA-256、字元數與 token 數；
   不把被拒絕的原文寫入正式 G。

本次第二案第一次輸出 8,192 tokens／44,953 chars，錯誤為 JSON 缺冒號；canonical retry 產出
1,509 tokens／5,355 chars 並通過所有驗證。第一、三案 raw diagnosis 直接成功。

### 5.2 Person C：大型真實 MRXS 記憶體修正

原始程式在大 WSI 上有四個會放大記憶體的點：

- 最終 `accumulator[keep]` 一次建立大型 GPU 複本。
- surrounding pooling 建立 `Hg × Wg × D` dense host tensor；第一案網格為
  9,192 × 8,504，三通道會遠超主機 RAM。
- vMF concatenate／normalize 預設以 1,000,000 rows 處理，單 chunk 可額外要求 6.68 GiB。
- 第三案 5,176,576 cells 的 512 + 768 維 float32 accumulators 合計約 26.5 GB，超過 RTX 4090。

修正如下：

- weighted mean 與 L2 normalize 以 8,192 rows 分塊，逐塊轉成 host float16，再釋放 GPU accumulator。
- surrounding pooling 改成 sparse lookup + GPU chunk gather，只配置有效 cell 的輸出，不建立
  `Hg × Wg × D` feature grid。
- vMF chunk 預設降為 65,536，並修正呼叫鏈，確保 chunk 參數真正傳入 spherical k-means。
- 根據當下可用 VRAM 與 cell 數自動選 accumulator strategy：
  - 可容納時使用 `joint_gpu`，一次累積兩個通道。
  - 不可容納時使用 `two_pass_gpu`：先 GPU float32 累積／正規化 512 維特徵並搬到 RAM，
    釋放後再重讀 WSI、累積 768 維特徵。沒有改模型、dtype 或 weighted-mean 數學。
- vMF clustering 期間暫時把不使用的模型移到 CPU，zero-shot 前再移回 GPU。

新增測試涵蓋分塊 weighted mean 等價、sparse surrounding 與 dense reference 等價、vMF chunk
確實傳遞，以及 4.16M／5.18M cells 的 joint／two-pass 選擇。

### 5.3 Person D／B 與共用 runner

- Person D production config 改為 `native.json` 並開啟 matching；component／external-assets／config
  文件同步更新。
- Person D 正式資產驗證涵蓋 prompts、label map、PLIP weight 與五個 support files、CONCH、
  440 張 few-shot tree/layout 及 mapping acceptance。
- Person B `rag_database` 路徑在 README、component manifest、external-assets 與 literature runner 統一。
- production image tags、compose config、pipeline profile 與測試同步，避免來源碼與舊映像版本混用。

## 6. 正式 Literature Preparation

執行：

```bash
python /home/yasaisen/Desktop/27_research/research_main_v3/lab_23/WLW_GPintegrate/pipeline/run_prepare_literature.py
```

結果：

- Artifact：`A.Literature@2.0`
- Producer：`person-b/literature-preparation:0.2.0`
- Corpus：`reference/person_b/rag_database`
- Corpus SHA-256：`ffd76f0893866aad7b2dd0f71bce76c90d1de8faf245eb2414a500637c01bc30`
- Literature nodes：87
- Sections：1,349
- 產物：`run/input/pipeline/A_literature.json`

## 7. 問題重現與修正歷程

以下是實際 formal production 嘗試中找出的問題；失敗 run 不作最終驗收：

| 問題 | 實際症狀 | 修正 |
|---|---|---|
| Person C 最終 boolean indexing | 第一案嘗試額外 7.94 GiB，CUDA OOM | 分塊 weighted mean／normalize 並逐塊移至 RAM |
| Person C vMF 1M-row chunk | 額外 6.68 GiB，CUDA OOM | chunk 改 65,536，並修正 caller 未傳入 chunk 的問題 |
| Person C dense surrounding | 依第一案網格估算會建立超大型 dense feature tensor | sparse lookup + chunk gather |
| Person A 舊 low-VRAM profile | CPU offload，第二案推論耗時過長 | 依使用者指示改 production single-device，完整模型放 GPU |
| Person A 第二案非法 JSON | raw diagnosis 產生 8,192-token 重複迴圈 | 嚴格拒絕後，以 canonical mapped diagnosis 重跑同一 soft prompt 模型並記 provenance |
| Person C 第三案 accumulator | 兩個 accumulator 合計約 26.5 GB；另一次曾遇暫時 GPU 佔用 | 自動 two-pass GPU，host 保存已正規化的第一路結果 |

## 8. 最終 production run 結果

最終 run：

- 開始：2026-10-29 14:46:03（Asia/Taipei）
- 完成：2026-10-29 15:03:29（Asia/Taipei）
- Profile：`production`
- Executor：`docker`
- 完成案例：3
- Execution records：18
- 合計案例 elapsed：1,045.599 秒（約 17 分 26 秒）

| Case | Person C cells／strategy | E ROI | F chunks | G query | A generation | D matching selected | E model evaluated | 全案時間 |
|---|---|---:|---:|---:|---|---:|---:|---:|
| `S1202317` | 4,163,584／`joint_gpu` | 1 | 3 | 1 | raw accepted | 0 | 0 | 274.163 秒 |
| `S1226464` | 3,055,872／`joint_gpu` | 153 | 3 | 1 | raw rejected → canonical accepted | 0 | 0 | 335.211 秒 |
| `S1129952` | 5,176,576／`two_pass_gpu` | 139 | 3 | 1 | raw accepted | 0 | 0 | 436.225 秒 |

各 stage elapsed seconds：

| Case | A report | C ROI | B retrieval | A query | D visual filter | E CLEE runner |
|---|---:|---:|---:|---:|---:|---:|
| `S1202317` | 1.031 | 186.810 | 7.773 | 29.716 | 47.102 | 1.731 |
| `S1226464` | 0.374 | 99.467 | 7.756 | 154.469 | 66.994 | 6.151 |
| `S1129952` | 0.951 | 317.950 | 14.134 | 39.525 | 60.384 | 3.281 |

## 9. D matching 與 E CLEE 結果解讀

三案 H provenance 均顯示：

- `visual_attribute_extraction.backend=plip+conch`
- `models_loaded=true`
- PLIP／CONCH 正式權重 SHA-256 符合設定
- PLIP 與 CONCH example prototypes 都 enabled，440 張圖均可讀
- `visual_matching_filter.enabled=true`

每個 ROI 都產生 `visualAttrs` 與 PLIP／CONCH 分數，證明不是 matching-disabled passthrough。D 對
Histologic_Type 的結果皆為 `skipped/insufficient_visual_evidence`；Microcalcification 沒有 G query，
故為 `skipped/no_visual_attr_query`。D 沒有選出 ROI：1、153、139 案例的 selected 都是 0。

因此 Person E 的 native 程式雖有讀取 epoch 223 checkpoint config、threshold bundle 與有效 label
space，仍依上游結果回報：

- `execution_statuses=["skipped_no_eligible_rois"]`
- `evaluated_roi_count=0`
- `selected_roi_count=0`
- Histologic_Type 原因：`upstream_visual_filter_rejected`
- Microcalcification 原因：`unsupported_dx_result`

這是嚴格 production matching 的資料結果。若要另外驗證「CLEE model forward 必定發生」，需要一筆
能通過 D matching 的 ROI／query，或另行改變 D threshold／mapping policy；本次沒有放寬正式門檻，
也沒有使用 `native.example.json` 的 matching bypass。

## 10. 驗證結果

### 10.1 Contract／artifact

以 `contracts.runtime` 驗證：

- `A.Literature`：通過
- 3 份單案 `CaseListInput`：通過
- 3 × D/E/F/G/H/I，共 18 份 artifact：全部通過

### 10.2 測試與設定

| 驗證 | 結果 |
|---|---|
| `python -m unittest discover -s tests` | 107 passed，1 skipped（平台限定） |
| Person C image 內元件測試 | 24 passed |
| Person D `verify_assets` with `native.json` | 全部通過；440/440 few-shot layout 被 loader 使用 |
| `docker compose -f integration/compose.yaml config --quiet` | 通過 |
| Production profile strict config test | 通過 |

## 11. 已知限制

1. 三份 sample 都是 VGHTC，Report Decompose 依正式 hospital routing 使用 regex；MedGemma 是 CGMH／
   fallback 路徑，本批沒有觸發。這不代表 MedGemma 在本 run 中做過 inference。
2. Person D matching 真正開啟且模型真正執行，但沒有 ROI 達到足夠 visual evidence；Person E 因此沒有
   CLEE forward。詳見第 9 節。
3. Person C ROI 演算法仍是 CONCH + vMF 初版；ROI 數量與外框大小會依 tissue coverage／分群而變。
4. Person C `two_pass_gpu` 會重讀 WSI 並多做一次 CONCH forward，換取 bounded VRAM；第三案 C 時間
   因此為 317.950 秒。
5. 本結果是研究軟體整合驗收，不是臨床效能或診斷準確度驗證。

## 12. 最終產物位置

- Manifest：`../run/output/pipeline/run_manifest.json`
- 正式 log：`../run/logs/pipeline-production-20261029T064603Z.log`
- Literature：`../run/input/pipeline/A_literature.json`
- 每案 D–I：`../run/output/pipeline/cases/<case_id>/`
- 本報告：`INTEGRATION_EXECUTION_REPORT.zh-TW.md`

正式輸出目錄只保留 case input 與 D–I；除錯期間擷取的 Person A raw／diagnostic G 已在驗收後移除。
