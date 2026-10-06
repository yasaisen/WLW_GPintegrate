# 丁（Person D）canonical example

`visual_filter` 的單案範例：`[E] E.ROIs@2.0` + `[G] G.VisualAttributeQueries@2.0` →
`[H] H.MatchedROIs@2.0`。

| 檔案 | 內容 |
|---|---|
| `E_rois.valid.json` | case `case-001`；`case-001-he`（參考切片，指向 `synthetic_slide.tiff`）與 `case-001-er`（非參考切片）各 2 個 ROI |
| `E_rois.empty.valid.json` | 同一 case，所有 stain 皆無 ROI |
| `G_queries.valid.json` | `Histologic_Type`、`Microcalcification` 各 1 個 mapped query；`Microcalcification` 另有 1 個合成 unmapped query（`case-001-query-003`）；`referenceWSI` 為 `case-001-he` |
| `synthetic_slide.tiff` | OpenSlide generic tiled TIFF，33792 × 19968 px，mpp 0.5；只有兩個 HE ROI 範圍內有程式產生的仿 H&E 紋理，其餘為白底；SHA-256 `a1f9c031b72c67308a860e24ba3f1a6fa2a04e00564a6990322ba47e22eb3d30` |
| `H_matches.expected.json` | `example` 模式完整預期輸出（逐內容比對） |
| `H_matches.empty.expected.json` | `native` 模式、空 ROI case 的完整預期輸出；不載入模型（逐內容比對） |
| `H_matches.native.structure.json` | `native` 模式、完整 case 的預期結構 |
| `check_native_structure.py` | 依結構檔檢查 `native` 輸出 |

## 涵蓋情境

| 情境 | 位置 |
|---|---|
| selected／rejected／`insufficient_visual_evidence` | `case-001-he` ROI 的 `query-001`、`query-002`，由模型決定 |
| 非 reference WSI | `case-001-er` 的所有 ROI（`stain_not_in_reference_wsi`） |
| unmapped query | `case-001-query-003`（`query_unmapped`） |
| 空 ROI case | `E_rois.empty.valid.json` |

兩個 HE ROI 刻意畫成不同樣貌（密集大而不規則的核 vs. 稀疏小而規則的核），但合成影像不保證模型給出
特定狀態；各分支的確定性覆蓋由 `components/person_d/tests/` 以假模型驗證。

## 來源與去識別化

- E 取自丙提供的合成樣本：移除 `roiCase` schema 不允許的 `structured_report`，並將 `case-001-he`
  的 `filename`／`filepath` 改指向合成切片。
- G 取自甲提供的樣本。病理號、日期、報告原文、WSI 檔名與路徑已移除；case metadata 與 E 相同，
  `dx_pair_id`、`query_id`、`referenceWSI` 改為 `case-001` 命名。`diagnosticCriteria`、
  `candidateReference` 維持原樣；`case-001-query-003` 為合成。
- E、G `reference_versions` 的 `source_path` 原為產生者工作站的絕對路徑，改為
  `example://<source_name>`；`source_name` 與 `sha256` 維持原樣。
- 合成切片由程式產生，不含任何影像來源或 PHI。

## 執行

CLI 只接受 sibling `run/` 下的輸入；`E_rois.valid.json` 的切片路徑
`../run/input/person_d/examples/synthetic_slide.tiff` 也依此複製位置設定：

```bash
mkdir -p ../run/input/person_d/examples
cp components/person_d/examples/E_rois.valid.json \
   components/person_d/examples/E_rois.empty.valid.json \
   components/person_d/examples/G_queries.valid.json \
   components/person_d/examples/synthetic_slide.tiff \
   ../run/input/person_d/examples/

# 1. example 模式：不需外部資產
python -m components.person_d.visual_filter \
  --input ../run/input/person_d/examples/E_rois.valid.json \
  --input ../run/input/person_d/examples/G_queries.valid.json \
  --output ../run/output/person_d/examples/H_matches.json \
  --config components/person_d/configs/example.json

# 2. native 模式、空 ROI case：需 reference/person_d/template_ref 的 prompt 與 label map
python -m components.person_d.visual_filter \
  --input ../run/input/person_d/examples/E_rois.empty.valid.json \
  --input ../run/input/person_d/examples/G_queries.valid.json \
  --output ../run/output/person_d/examples/H_matches.empty.json \
  --config components/person_d/configs/native.example.json

# 3. native 模式、完整 case：需 PLIP、CONCH 與 Example 範例圖
#    尚無 CONCH 授權時改用 configs/native.smoke.json（隨機權重，只驗證流程）
python -m components.person_d.visual_filter \
  --input ../run/input/person_d/examples/E_rois.valid.json \
  --input ../run/input/person_d/examples/G_queries.valid.json \
  --output ../run/output/person_d/examples/H_matches.native.json \
  --config components/person_d/configs/native.example.json
```

`contracts/paths.py` 只允許 `components/person_x/configs/` 下的 config，因此範例直接使用
`configs/` 內的設定，不另放 `config.example.json`。Docker 執行方式見 `components/person_d/README.md`。

## 比對

```bash
compare() { python -c "import json, sys; a, b = (json.load(open(p, encoding='utf-8')) for p in sys.argv[1:]); sys.exit(a != b)" "$1" "$2" && echo "match: $2"; }
compare components/person_d/examples/H_matches.expected.json ../run/output/person_d/examples/H_matches.json
compare components/person_d/examples/H_matches.empty.expected.json ../run/output/person_d/examples/H_matches.empty.json
python components/person_d/examples/check_native_structure.py \
  components/person_d/examples/H_matches.native.structure.json \
  ../run/output/person_d/examples/H_matches.native.json
```

- 1、2 以 JSON 內容逐一比對；2 的 `reference_versions` 含 prompt 與 label map 的 SHA-256，
  更新 `template_ref` 資產後需重新產生。
- 3 的狀態與分數取決於模型與 GPU 浮點誤差，不與固定輸出逐值比對：ROI 與 event 的順序、`roi_id`、
  `dx_pair_id`、`query_id` 與確定性判定必須完全相同，模型判定須落在允許的 status／reason 內。
- 3 的 score 容許誤差與最終狀態判定定義於 `H_matches.native.structure.json` 的 `score_rule`
  （與 `configs/native.example.json` 的 `matching` 相同）：由 `visualAttrs_info.matching.<query_id>`
  的逐屬性判定重算 score，與 event `score` 差距須 ≤ `score_tolerance`（1e-6，score 取到小數 6 位）；
  status／reason 須符合：evaluated 屬性數 < `min_evaluated_attributes` → `skipped`／
  `insufficient_visual_evidence`；Must_False 命中或 Must_True 未滿足 → `rejected`／
  `must_condition_failed`；score < `score_threshold` → `rejected`／`score_below_threshold`；
  其餘 → `selected`／`visual_attributes_match`。各選項的模型相似度分數不比對；同一張 GPU 上
  Windows 與 Linux 容器的實測差距 ≤ 1e-6。
