# 甲的準備與交付清單

## 你的責任邊界

甲負責兩個 executable，但可以共用同一個 Python/Docker environment：

```text
B.ReportTables ──> report_decompose ─┬─> D.DxPairsIndex
                                      └─> per-case D.DxPairs (metadata-shaped case)
D.DxPairs + F.Chunks ──> query_generation ──> G.VisualAttributeQueries
```

你只需要保證：任何符合 B v1.0 的輸入都能產生合法 D index 與 per-case D v2.0；D v2.0 與
F v2.0 能產生 G v2.0。integration layer 不應 import 你的內部 class。

## 需要準備的東西與放置位置

| 要準備的項目 | 放置位置 | 說明 |
|---|---|---|
| Report Decompose 實作 | `components/person_a/report_decompose.py` | 保留 `--input/--output/--config` CLI；一次處理多 table/case |
| Report extraction | `components/person_a/report_extraction.py` | Query_Design regex 的逐報告函式；不直接讀 Excel、不自行寫最終 JSON |
| Optional MedGemma | `components/person_a/medgemma_extractor.py` | 只在 config 選用時載入模型；同一程序內快取模型 |
| Hospital table parsers | `components/person_a/table_parsers.py` | 依 `table_type` 解析 VGHTC/CGMH，統一為 reports + WSIs |
| XLSX reader | `components/person_a/xlsx_reader.py` | 只讀取工作表欄位/值，不複製原始 Excel |
| Query Generation 實作 | `components/person_a/query_generation.py` | 讀 D/F、寫 G，不直接讀乙的程式或資料庫內部物件 |
| Python dependencies | `components/person_a/requirements.txt` | 一行一個直接依賴，正式版本應 pin，例如 `transformers==x.y.z` |
| 兩個預設 config | `components/person_a/configs/*.default.json` | 放可公開、可重現的預設參數；不要放密碼或機器絕對路徑 |
| Runtime 描述 | `components/person_a/component.yaml` | 填 Python、CPU、RAM、GPU/VRAM、entrypoints、版本 |
| Container recipe | `components/person_a/Dockerfile` | 安裝 OS/Python 環境；不要把 dataset/checkpoint 複製進 image |
| B/F canonical input | `integration/fixtures/` 或由上游 artifact 產生 | B 已有 fixture；F 由乙在 smoke test 產生 |
| D/G expected output | `integration/artifacts-local/` | 跑 pipeline 後生成，可用來人工檢查欄位 |
| D/G schema | `contracts/schemas/D_*.json`、`G_*.json` | canonical source，由整合負責人審核版本變更 |
| Contract/E2E tests | `tests/` | 至少驗 valid input、valid output、缺欄位時 fail |

## 資料 contract 要確認的細節

### B.ReportTables

B 是 run-level 來源 manifest，payload 的 `tables[]` 只放 `table_idx/table_type/table_path`；
它不屬於單一 case，所以 envelope 不放 `case_id`。

新預設 `wsi_discovery.mode=case_directory_he`：`table_path` 只負責指出掛載後的院別報告目錄，
VGHTC/CGMH parser 從其中的 Excel 讀取報告與 `case_id`；WSI 則另外從掛載後的
`/data/wsi/<case_id>/` 遞迴尋找檔名或子目錄含 `HE`/`H01` 的檔案。也就是以中榮的`病理序號`
或長庚的 `Path_ID` 作為 `case_id`（對話中統稱 `record_id`），再拿同一個 ID 找 WSI 資料夾。
若 WSI 根目錄先分院別，可透過
`hospital_subdirectories` 設定。

block 會優先由資料夾或檔名中 case ID 後的片段判斷；判斷不到時明確寫成 `UNSPECIFIED`。
等院方提供正式檔名規則後，可用 `block_pattern` 指定正規表示式。舊 WSI 清單表的 join 邏輯仍保留
在 `legacy_tables` 模式，但不是新預設。Windows-style source paths 也必須先正規化成 container
可用的 separator。

### D.DxPairs

每個 per-case D 使用 `payload.case_list[0]`。報告原文在 `report_raw_content`，DxPair 在
`structured_report.DxItems`，掃描找到的 WSI 在 `tissue_blocks[].stains[]`，其中 `filepath` 是
容器內可讀的 `/data/wsi/...` 路徑。合法 DxItem 及其預設欄位每次執行都由
`DxStructuredCandidates_integrated.json` 載入。

DxItem 的 `referenceWSI[]` 指定對應 WSI；來源有明示 ID 時以明示內容為準，否則依 catalog 的
`referenceType` 選染色（例如 HE），連 `referenceType` 都沒有時才預設全部 WSI。raw hospital
report 沒有預先填入結果時，`report_extraction.py` 會在 extraction boundary 逐份報告抽取；完全
沒有命中時仍可合法輸出空 `DxItems`，讓 run manifest 與人工稽核能看見該 case。

Report Decompose 的資料流、設定與切換 MedGemma 方法見
[`REPORT_DECOMPOSE_GUIDE.md`](REPORT_DECOMPOSE_GUIDE.md)。

每個 pair 必須有穩定 ID，不可只靠 list index：

- `dx_pair_id`
- `source_report_id`
- `DxResultCls` / `DxResultTxt` / `DxResultRawTxt`
- `referenceBlock` / `referenceType` / `referenceWSI`

D 同時會被乙、丙與戊使用。若你更名或刪除欄位，三個 consumer 都會受影響，因此不能只在自己的
程式裡偷偷修改；應先修改中央 schema、升版並更新 fixtures。

### G.VisualAttributeQueries

每個 Histologic Type query 放在相應 DxItem 的 `visualAttrQueries[]`，必須能追回原始診斷：

- `query_id`
- `dx_pair_id`
- `text`
- `criteria_status`：`mapped` 或 `unmapped`
- `diagnosticCriteria`：一個 type-level subtype；unmapped 時為 `null`
- `mapping_source` / `chunk_ids`

mapping 必須在 runtime 讀取 `Histologic_Type_mappingTable.json`，不可寫死在程式中。
`candidateReference.json` 是 visual attribute vocabulary，type-level 檔提供條件。

不要把自訂 Python object、tensor 或 tokenizer output 直接放入 G；G 必須是語言無關且能寫成
JSON 的交換資料。

## 模型與機密怎麼放

- 小型公開設定：放 `configs/`。
- 大型 checkpoint：建議 host 放 `/models/person-a/<model>/<revision>/`，以唯讀 volume mount。
- Hugging Face token/API key：用 runtime environment variable 或 secret manager，不寫入 Git、config
  或 Dockerfile。
- 報告原文與病人資料：放受控的 `/data` mount，不放 fixture；fixture 必須是去識別化假資料。

config 只記錄 checkpoint 的邏輯名稱、revision 或 hash，不應寫死某位成員 home directory。

## 交付前自己跑

```bash
python3 -m components.person_a.report_decompose \
  --input integration/fixtures/input/B_report_tables.json \
  --output /tmp/D_dx_pairs_index.json \
  --config components/person_a/configs/report_decompose.default.json

python3 pipeline/run_pipeline.py
python3 -m unittest discover -s tests -v
```

## 完成定義

- 乾淨環境可由 Dockerfile build。
- 兩個 entrypoint 都不需人工改 code/config path 才能執行。
- B→D index/per-case D 與 D+F→G 都通過 schema validation。
- 錯誤輸入會以 non-zero exit code 失敗，而不是產生半套 JSON。
- README/manifest 記錄真實 Python、CUDA、模型 revision 與資源需求。
