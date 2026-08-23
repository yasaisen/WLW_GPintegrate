# Report Decompose 整合說明

## 這一塊負責什麼

甲的 Report Decompose 一次接收一份 run-level `B.ReportTables`，讀取其中全部 table source，
把資料依 `case_id` 分組，再為每個 case 產生一份 `D.DxPairs`。整個元件只執行一次，不是由
pipeline 對每個 case 重複呼叫。

```text
B_report_tables.json
└── tables[]
    ├── VGHTC table/file/directory
    └── CGMH table/file/directory
            │
            ▼
table_parsers.py：Excel/CSV → reports + WSIs，依 case_id 分組
            │
            ▼
report_extraction.py：每份 report raw text → DxItem + raw result
            │
            ▼
report_decompose.py：補 candidate metadata/referenceWSI，寫出 D
            │
            ├── D_dx_pairs_index.json
            ├── cases/case-001/D_dx_pairs.json
            ├── cases/case-002/D_dx_pairs.json
            └── ...
```

`pipeline/run_pipeline.py` 的迴圈從這裡才開始：它讀取 `D_dx_pairs_index.json`，將每一份 D
分別送往 F/G/E/H/I。pipeline 的迴圈不會重做 Report Decompose。

## 各檔案的責任

### `B_report_tables.json`

只放來源清單，不放 Excel 內容，也不放分解答案：

```json
{
  "contract": "B.ReportTables",
  "schema_version": "1.0",
  "artifact_id": "hospital-run-001",
  "payload": {
    "tables": [
      {
        "table_idx": 0,
        "table_type": "VGHTC2024",
        "table_path": "/data/report/VGHTC"
      },
      {
        "table_idx": 1,
        "table_type": "CGMH2019",
        "table_path": "/data/report/CGMH"
      }
    ]
  }
}
```

相對路徑以 `B_report_tables.json` 所在資料夾為基準；正式 server/Docker 建議使用容器內固定路徑，
例如把 host 的共用資料目錄唯讀掛載成 `/data/report`，再讓 B 使用 `/data/report/...`。真實院方
Excel/WSI 不應 commit 到 Git。

### `table_parsers.py`

這層只做資料整理，不做診斷文字抽取：

1. 根據 `table_type` 選擇中榮或長庚 adapter。
2. 讀取病理報告、WSI 總表、染色、block 與路徑。
3. 依 `case_id` 合併成 `reports[]` 和 `wsis[]`。
4. 缺 report 或 WSI 的 case 寫入 D index 的 `skipped_cases`。

標準化 CSV/XLSX 若已有 `dx_item/dx_result`，parser 也會帶入，主要用於測試或已完成結構化的
資料來源。

### `report_extraction.py`

這是由 Query_Design 整理出的可重用 extraction boundary。與舊腳本不同，它：

- 不寫死 Excel 路徑。
- 不使用 Pandas 重新讀整批表格。
- 不在 import 時直接執行。
- 一次只接收 parser 已整理好的 report text。
- 遇到 `Gross description:` 就停止，避免從 gross section 誤抓結果。
- 支援中榮／長庚既有欄位名稱與別名。
- 同一 case 同一 DxItem 只保留第一個非空結果。

`Histologic Type` 和 catalog 的 `Histologic_Type` 這類空格／底線差異會自動對應；無法自動對應
時，在 config 的 `item_name_map` 指定：

```json
"item_name_map": {
  "Her-2/neu status": "HER2_Status"
}
```

### `medgemma_extractor.py`

它把原本 `medgemma_extract.py` 的模型載入、chunk、JSON 解析與 first-nonempty merge 改成可由
pipeline 呼叫的 class。模型在同一個 Report Decompose 程序中只載入一次，不會每個 case
重新載入。

預設 demo 不載入 MedGemma。要使用時：

1. 在 person A 的 server image 安裝 `requirements-medgemma.txt` 所列套件，並依 server CUDA
   版本鎖定實際版本。
2. 提供 `HF_TOKEN`。
3. 使用 `report_decompose.medgemma.example.json`，或把正式 config 的 backend 改成
   `regex_then_medgemma`。

三種 backend：

- `regex`：只跑確定性的 Query_Design 規則，預設值。
- `medgemma`：只跑模型。
- `regex_then_medgemma`：regex 先跑，模型補 regex 沒抓到的欄位。

## DxResult 文字與類別

抽取器先得到報告中的原始文字，例如：

```text
Invasive carcinoma of no special type (ductal).
```

D 需要同時保留：

- `DxResultRawTxt`：報告原始抽取文字。
- `DxResultTxt`：目前使用的可讀文字。
- `DxResultCls`：供後續元件使用的正式類別。

若抽取文字已等於 candidate catalog 的類別，程式會自動使用 catalog 中的正式大小寫。若不同，
可在 config 明確映射：

```json
"result_class_map": {
  "Histologic_Type": {
    "Invasive ductal carcinoma": "Invasive breast carcinoma of no special type"
  }
}
```

整合與資料檢查期間建議 `strict_result_classes: false`，未映射文字仍會寫入 D，不會讓整批中斷；
正式上線且 mapping 完整後可改成 `true`，任何不合法類別都會立即報錯。

## 執行

```bash
python3 -m components.person_a.report_decompose \
  --input /inputs/B_report_tables.json \
  --output /artifacts/D_dx_pairs_index.json \
  --config /configs/report_decompose.json
```

執行完先檢查：

1. `D_dx_pairs_index.json` 的 `cases[]` 和 `skipped_cases[]`。
2. 每個 `cases/<case_id>/D_dx_pairs.json` 的 `report_raw_content`。
3. `structured_report.DxItems` 是否有抽取結果。
4. 每個 DxItem 的 `referenceWSI[]` 是否選到正確染色切片。

## 測試

`tests/test_report_extraction.py` 包含一個沒有預填 `dx_item/dx_result` 的 B table，會真正走完：

```text
B table → regex extraction → D index → per-case D → schema validation
```

執行：

```bash
python3 -m unittest tests.test_report_extraction -v
```

完整 pipeline 測試另外需要 repository 外部的 lab_19 candidate/visual reference 檔案；在獨立 clone
沒有掛載這些 references 時，原專案的 pipeline/reference tests 會因缺檔失敗，這不是 extraction
程式本身的錯誤。
