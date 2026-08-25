# Report Decompose 整合說明

## 這一塊負責什麼

甲的 Report Decompose 一次接收一份 run-level `B.ReportTables`，讀取其中全部 table source，
把資料依 `case_id` 分組，再為每個 case 產生一份 `D.DxPairs`。整個元件只執行一次，不是由
pipeline 對每個 case 重複呼叫。

```text
B_report_tables.json
└── tables[]
    ├── /data/reports/VGHTC → 報告 Excel → reports + case_id
    └── /data/reports/CGMH  → 報告 Excel → reports + case_id
                                           │
/data/wsi/<case_id>/...HE... ──────────────┤
                                           ▼
table_parsers.py：依 case_id 把報告與 HE WSI 合在一起
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
        "table_path": "/data/reports/VGHTC"
      },
      {
        "table_idx": 1,
        "table_type": "CGMH2019",
        "table_path": "/data/reports/CGMH"
      }
    ]
  }
}
```

正式執行時，B 本身也放在外部的報告資料目錄，不放進 repository。B 裡寫的是 Docker **裡面**
看得到的路徑，不是某一台電腦的 `D:\...`。Compose 把不同電腦的實際位置統一映成
`/data/reports`，因此 B 不必跟著每台電腦修改。

## 正式資料如何 mount

建議先在 Docker 外面整理成：

```text
D:\WLW_data\
├── reports\
│   ├── B_report_tables.json
│   ├── VGHTC\
│   │   ├── 乳癌病理報告_240927.xlsx
│   │   └── 乳癌病理報告_241220.xlsx
│   └── CGMH\
│       └── Pathology_Report_v1.xlsx
└── wsi\
    ├── <case_id_1>\
    │   ├── <case_id_1>_A_HE.mrxs
    │   └── <case_id_1>_B_HE.mrxs
    └── <case_id_2>\
        └── HE\slide.svs
```

這只是建議的 host 目錄；資料真正放哪裡可由每台電腦自行決定。把
`integration/.env.example` 複製成 `integration/.env`，再填該電腦的路徑：

```dotenv
REPORT_ROOT=D:/WLW_data/reports
WSI_ROOT=D:/WLW_data/wsi
REPORT_TABLES_INPUT=/data/reports/B_report_tables.json
```

可把 `integration/fixtures/input/B_report_tables.mounted.example.json` 複製到
`<REPORT_ROOT>/B_report_tables.json` 當起點，再依實際院別資料夾修改 `table_path`。正式 B 放在
repository 外面，因此不會跟著 push。

`integration/.env` 不會被 Git 追蹤。Compose 的兩個唯讀 mount 是：

```yaml
volumes:
  - "${REPORT_ROOT}:/data/reports:ro"
  - "${WSI_ROOT}:/data/wsi:ro"
```

白話來說，mount 只是替資料開兩扇門：

- Docker 外的 `REPORT_ROOT`，在 Docker 裡改名看成 `/data/reports`。
- Docker 外的 `WSI_ROOT`，在 Docker 裡改名看成 `/data/wsi`。
- `:ro` 表示程式只能讀，不能修改院方原始資料。
- mount 不會自動把報告和 WSI 配在一起；配對工作由 `table_parsers.py` 完成。

所以不同電腦只需修改各自不會上傳的 `.env`，B 和程式裡永遠使用相同的容器路徑。GitHub 的
`integration/fixtures/input/` 仍保留少量假 case，目的是讓任何人 clone 後能測試格式與程式，並不
代表正式資料也要上傳。

## 目前 WSI 配對規則

這版依目前與學長確認到的資訊實作：

1. Excel 中的院方識別欄位作為 `case_id`（中榮是 `病理序號`，長庚是 `Path_ID`；對話中的
   `record_id` 是對這類識別欄位的統稱）。
2. 對每個有報告的 case，到 `/data/wsi/<case_id>/` 找它的 WSI。
3. 遞迴尋找 `.mrxs`、`.ndpi`、`.svs`、`.tif`、`.tiff`。
4. 只收檔名或相對子目錄含 `HE` 或 `H01` 的檔案，並在 D 中統一標成 `HE`。
5. 同一 case 可以有多張 HE；全部保留，再依 block 分組。
6. block 優先從子目錄或檔名中的片段判斷；判斷不出來就填 `UNSPECIFIED`，不憑空猜測。

例如：

```text
/data/wsi/CASE001/CASE001A,H01,130103.mrxs → case CASE001、block A、HE
/data/wsi/CASE001/B/HE/slide.svs            → case CASE001、block B、HE
/data/wsi/CASE001/HE/slide.svs              → case CASE001、block UNSPECIFIED、HE
```

若實際目錄是 `/data/wsi/VGHTC/<case_id>/` 與 `/data/wsi/CGMH/<case_id>/`，在 config 加：

```json
"hospital_subdirectories": {
  "VGHTC": "VGHTC",
  "CGMH": "CGMH"
}
```

若學長之後提供「檔名後綴如何表示 block」的精確規則，可以在 config 加 `block_pattern`；程式支援
一個命名為 `block` 的 capture group 或第一個 capture group。這是仍需用真實 WSI 檔名確認的部分，
不影響 report 與 case 先依 `case_id` 配對。

### `table_parsers.py`

這層只做資料整理，不做診斷文字抽取：

1. 根據 `table_type` 選擇中榮或長庚 adapter。
2. 從掛載的報告目錄讀取病理報告 Excel。
3. 用報告的 `case_id` 到另一個掛載的 WSI 根目錄尋找 HE/H01 檔案。
4. 依 `case_id` 合併成 `reports[]` 和 `wsis[]`。
5. 缺 report 或 WSI 的 case 寫入 D index 的 `skipped_cases`。

標準化 CSV/XLSX 若已有 `dx_item/dx_result`，parser 也會帶入，主要用於測試或已完成結構化的
資料來源。若必須沿用舊的 WSI 清單表，可把 `wsi_discovery.mode` 改成 `legacy_tables`；新正式流程
使用 `case_directory_he`。

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

表格本身已有 `dx_item/dx_result` 時不會重跑抽取，因此 canonical demo 不會載入 MedGemma。
處理長庚 raw report 時則依下列醫院流程使用模型。要執行時：

1. 在 person A 的 server image 安裝 `requirements-medgemma.txt` 所列套件，並依 server CUDA
   版本鎖定實際版本。
2. 提供 `HF_TOKEN`。
3. 使用 `report_decompose.medgemma.example.json`，正式 config 的 backend 維持
   `hospital_routed`。

正式的醫院分流規則：

```text
VGHTC（中榮）
└── 原本的中榮 Regex → 最終抽取結果

CGMH（長庚）
└── 先跑原本的長庚 Regex
    ├── 完全沒有抓到任何欄位
    │   └── MedGemma 抽取全部項目 → 最終結果
    └── 有抓到至少一個欄位
        └── MedGemma 只抽 Histologic Type
            └── Regex 基礎結果 + MedGemma Histologic Type → 最終結果
```

如果 MedGemma 成功回傳 Histologic Type，以模型值取代 regex 的 Histologic Type；其他 regex
欄位原樣保留。若模型沒有回傳 Histologic Type，則保留 regex 原值。

`regex`、`medgemma`、`regex_then_medgemma` 仍保留給單獨測試 backend；正式流程使用
`hospital_routed`，避免中榮誤觸 MedGemma。

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
  --input /data/reports/B_report_tables.json \
  --output /artifacts/D_dx_pairs_index.json \
  --config /configs/report_decompose.json
```

使用 Compose 時不需要手動輸入上述容器路徑；在 `integration` 目錄執行：

```bash
docker compose up --build --abort-on-container-failure
```

Compose 會讀取同目錄的 `.env`，自動完成 report 與 WSI mount。若不建立 `.env`，它會改用 GitHub
內的假 fixture，方便執行 demo。

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
