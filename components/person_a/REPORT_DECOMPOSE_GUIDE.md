# Person A：Report Decompose 實作說明

本文件只說明 `components/person_a` 的責任。中央 `integration/compose.yaml`、pipeline controller、
contracts 與其他成員元件不由 Person A 自行修改。

## 執行邊界

```text
B.ReportTables
  -> table_parsers：依 GitHub 既有規則讀 VGHTC／CGMH raw tables
  -> report_extraction：逐份報告抽取診斷欄位
  -> report_decompose：組成並驗證 D index 與 per-case D
```

對外介面維持 GitHub 規定的 CLI：

```text
python -m components.person_a.report_decompose \
  --input <B.ReportTables.json> \
  --output <D.DxPairsIndex.json> \
  --config <report_decompose.default.json>
```

integration layer 只需要知道 CLI、B／D contracts 與 exit code，不需要 import Person A 的 Python
class。

## B 與院端資料

B 的 `payload.tables[]` 仍只包含：

- `table_idx`
- `table_type`：`VGHTC2024` 或 `CGMH2019`
- `table_path`：單一標準化 CSV/XLSX，或掛載後的院端 raw-data directory

既有 parser 行為維持不變：

- VGHTC directory：讀兩份病理報告 Excel、`VGHTC_list_total_2.xlsx` 與 `data_path`。
- CGMH directory：讀 `Pathology_Report_v1.xlsx`、`Pathology_image_path_v1.csv`、
  `CGMH_list_total.xlsx` 與 `data_path`。
- 標準化表格：直接讀 `report_text`、`wsi_path`、`stain_type`、`block_id`、`dx_item` 與
  `dx_result` 等欄位。

報告、WSI、candidate JSON 與模型權重都留在 Git repository 外；Docker 執行時由使用者或整合
負責人以唯讀 mount 提供。B 內的路徑必須是容器看得到的路徑，不是某位成員的 Windows home
directory。

## 報告抽取規則

正式 config 使用 `hospital_routed`：

```text
VGHTC
└─ 只使用 Query_Design Regex，不呼叫 MedGemma

CGMH
└─ 先使用 Query_Design Regex
   ├─ 完全沒有命中：MedGemma 抽取全部 configured DxItems
   └─ 有任何命中：保留 Regex 結果，MedGemma 只補 Histologic Type
```

表格已提供 `dx_item/dx_result` 時，`only_when_missing: true` 會保留既有結果，不重新抽取。

`strict_result_classes: true` 會要求 `DxResultCls` 存在於
`DxStructuredCandidates_integrated.json`。模型或 Regex 的原始文字保留在 `DxResultRawTxt` 與
`DxResultTxt`；若原始文字不是候選類別，必須在 `result_class_map` 明確映射，不能自行放寬 contract。

## 標準 Person A 檔案

- `Dockerfile`：Person A 唯一正式 container recipe。
- `requirements.txt`：固定 Transformers、Accelerate、bitsandbytes 與 sentencepiece 版本；
  PyTorch CUDA wheel 固定在 Dockerfile。
- `component.yaml`：記錄 Python、CUDA、GPU/VRAM、模型 revision 與 entrypoints。
- `configs/report_decompose.default.json`：B -> D 正式預設設定。
- `configs/query_generation.default.json`：D + F -> G 正式預設設定。
- `report_extraction.py`：Regex、醫院分流與結果類別映射。
- `medgemma_extractor.py`：MedGemma adapter；同一程序只載入一次模型。
- `medgemma_smoke.py`：GPU、4-bit 與真模型短生成檢查。

## 不用 Docker 執行 Regex／測試資料

在 repository 根目錄：

```powershell
python -m components.person_a.report_decompose `
  --input integration/fixtures/input/B_report_tables.json `
  --output integration/artifacts-local/D_dx_pairs_index.json `
  --config components/person_a/configs/report_decompose.default.json
```

fixture 已有結構化結果，因此不需要載入 MedGemma。正式 raw CGMH 報告才會依分流規則使用模型。

## 建立與單獨執行 Person A Docker image

在 repository 根目錄建立 GitHub 規定的 Person A Dockerfile：

```powershell
docker build -f components/person_a/Dockerfile -t wlw/person-a:0.5.0 .
```

以下是單獨執行 B -> D 的示意；實際 host 路徑由執行機器決定：

```powershell
docker run --rm --gpus all `
  -e HF_TOKEN `
  -e HF_HOME=/models/huggingface `
  -v "D:/WLW_data/raw:/data/raw:ro" `
  -v "D:/WLW_data/wsi:/data/wsi:ro" `
  -v "D:/WLW_reference/DxStructuredCandidates_integrated.json:/references/DxStructuredCandidates_integrated.json:ro" `
  -v "D:/WLW_models/huggingface:/models/huggingface" `
  -v "D:/WLW_output:/outputs" `
  wlw/person-a:0.5.0 `
  --input /data/raw/B_report_tables.json `
  --output /outputs/D_dx_pairs_index.json `
  --config /app/components/person_a/configs/report_decompose.default.json
```

raw directory 內的 B 可將 `table_path` 寫成 `/data/raw/VGHTC` 與 `/data/raw/CGMH`；院端
`data_path` 必須指向容器內的 WSI mount，例如 `/data/wsi`。中央 Compose 如何提供相同 mounts，
由 integration 負責人接線。

## MedGemma 環境檢查

先只檢查 GPU／套件／4-bit：

```powershell
docker run --rm --gpus all `
  --entrypoint python `
  wlw/person-a:0.5.0 `
  -m components.person_a.medgemma_smoke
```

需要真正載入模型時，另外傳入 token 與外部模型快取：

```powershell
docker run --rm --gpus all `
  -e HF_TOKEN `
  -v "D:/WLW_models/huggingface:/models/huggingface" `
  --entrypoint python `
  wlw/person-a:0.5.0 `
  -m components.person_a.medgemma_smoke --load-model
```

成功條件包含：

- `status` 是 `ok`。
- `generation.Histologic_Type` 非空。
- `generation_diagnostics.first_step_logits.all_finite` 是 `true`。

## 交付前驗證

```powershell
python -m unittest tests.test_report_extraction tests.test_report_tables
python -m unittest discover -s tests -v
```

必須確認：

- B -> D index／per-case D 通過 schema validation。
- VGHTC 絕不呼叫 MedGemma。
- CGMH 依 Regex 命中情況呼叫 MedGemma。
- 缺 input、candidate、模型權限或 GPU 時以 non-zero exit code 失敗。
- Git 變更不包含 `.env`、token、報告、WSI、candidate 真實檔案或模型權重。
