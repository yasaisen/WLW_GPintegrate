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

`table_path` 指向 raw-data directory 時，VGHTC parser 會 join 病理報告 Excel、WSI 總表與
`data_path`；CGMH parser 會 join 病理報告 Excel、影像路徑 CSV、染色總表與 `data_path`。
WSI filename 可能含 `15.33.07` 這類掃描時間，實作只能移除已知 WSI 副檔名，不可直接用一般
suffix 規則誤刪時間尾段。Windows-style source paths 也必須先正規化成 container 可用的 separator。

### D.DxPairs

每個 per-case D 使用 `payload.case_list[0]`。報告原文在 `report_raw_content`，DxPair 在
`structured_report.DxItems`，WSI 在 `tissue_blocks[].stains[]`，其中 `filepath` 就是 report table
帶入的 `wsi_path`。合法 DxItem 及其預設欄位每次執行都由
`DxStructuredCandidates_integrated.json` 載入。

DxItem 的 `referenceWSI[]` 指定對應 WSI；來源有明示 ID 時以明示內容為準，否則依 catalog 的
`referenceType` 選染色（例如 HE），連 `referenceType` 都沒有時才預設全部 WSI。raw hospital
report 沒有結構化結果時可合法輸出空 `DxItems`，正式報告分解/NLP 接在甲的 extraction boundary。

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
