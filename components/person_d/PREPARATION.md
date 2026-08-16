# 丁的準備與交付清單

## 你的責任邊界

丁同時接收影像候選區與文字查詢，負責 visual attribute extraction 及 matching：

```text
E.ROIs ──> visual attribute extraction ──┐
                                         ├─> matching/filter ──> H.MatchedROIs
G.VisualAttributeQueries ────────────────┘
```

目前 demo 把 extraction 與 matching 寫在同一個 executable。正式版可以在內部分 class/function，
也可以拆成兩個 container；只要對外仍明確接受 E/G 並產生 H 即可。

## 需要準備的東西與放置位置

| 要準備的項目 | 放置位置 | 說明 |
|---|---|---|
| Extraction/matching 實作 | `components/person_d/visual_filter.py` | 讀 E、G，寫 H；不得依靠丙/甲的 Python object |
| Python dependencies | `components/person_d/requirements.txt` | torch、vision、model client 等直接依賴與版本 |
| OS/CUDA dependencies | `components/person_d/Dockerfile` | CUDA base、image codec、OpenSlide 等 |
| 預設 config | `components/person_d/configs/default.json` | threshold、top-k、batch size、model path/revision |
| Runtime/model manifest | `components/person_d/component.yaml` | GPU/VRAM、CPU/RAM、timeout、checkpoint hash |
| E input example | `integration/artifacts-local/E_rois.json` | 由丙產生，需確認座標語意 |
| G input example | `integration/artifacts-local/G_queries.json` | 由甲產生，需確認 attribute vocabulary |
| H expected output | `integration/artifacts-local/H_matches.json` | 每筆 match 同時保留 query、diagnosis、ROI provenance |
| E/G/H schemas | `contracts/schemas/` | 任何欄位變更先經 producer/consumer review |
| Model checkpoint | host `/models/person-d/<model>/<revision>/` | 唯讀 mount，不放 image |
| WSI | host `/data/wsi/...` | 依 E 的 `image_uri` 讀取，不在 E/H 搬 pixels |

## 兩條對接線要分別驗證

### 與丙對接 E

- 確認 `coordinate.level` 與 x/y/width/height 的單位。
- 確認 container 內能解析 E 的 `image_uri`。
- 確認 WSI mount 為 read-only。
- 準備至少一張已知 ROI 的小型 fixture，驗證裁出的 pixels 一致。

### 與甲對接 G

- 定義 `required_attributes` 使用自由文字還是 controlled vocabulary。
- 若使用 ontology ID，應把 ID 與 display text 分開定義。
- 定義大小寫、同義詞、否定詞及多屬性查詢的 matching 規則。
- score 必須說明範圍與方向；H v1.0 是 0～1、越大越匹配。

## H.MatchedROIs 的 provenance

每一筆 H match 至少要能回答：

1. 它回應哪個 `dx_pair_id`？
2. 它回應哪個 `query_id`？
3. 使用哪個 `roi_id`/`wsi_id`？
4. WSI 在哪個 `image_uri`，座標為何？
5. 哪些 attributes 實際 match？
6. 分數是多少，模型/元件版本是什麼？

目前 producer version 放在 artifact header。正式研究若要比較多個模型，建議在 manifest/config
記錄 checkpoint hash，必要時擴充 H schema 加上可重現的 model provenance。

## 空結果與錯誤要分開

「沒有 ROI 達 threshold」是合法科學結果，H 的 `matches` 可以是空 array；「WSI 打不開」或
「模型載入失敗」則是執行錯誤，應 non-zero exit，不能偽裝成空結果。這兩者會直接影響戊的
判讀，因此必須清楚區分。

## 交付前自己跑

```bash
python3 pipeline/run_pipeline.py

python3 -m components.person_d.visual_filter \
  --input integration/artifacts-local/E_rois.json \
  --input integration/artifacts-local/G_queries.json \
  --output /tmp/H_matches.json \
  --config components/person_d/configs/default.json

python3 -m unittest discover -s tests -v
```

## 完成定義

- canonical E 與 G 能獨立通過 input validation，H 通過 output validation。
- H 的每筆結果能 trace 到 D/G/E/WSI，不依賴 array index。
- 空 match 是合法 artifact；讀檔/模型錯誤是 non-zero exit。
- CPU/GPU、batch size、VRAM、timeout 與 checkpoint revision 有記錄。
- image 不包含 WSI、病人資料、credential 或大型 checkpoint。

