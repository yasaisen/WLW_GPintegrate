# 丙的準備與交付清單

## 你的責任邊界

丙負責從 WSI 找出值得後續分析的 ROI：

```text
C.WSI reference ──> interest_pattern ──> E.ROIs references
```

C/E 交換的是 metadata 與位置，不是把 WSI/ROI pixels 放進 JSON。真實程式應依 `image_uri`
開啟 mounted WSI，再輸出 ROI ID、座標與 resolution。

## 需要準備的東西與放置位置

| 要準備的項目 | 放置位置 | 說明 |
|---|---|---|
| Interest pattern 實作 | `components/person_c/interest_pattern.py` | 讀 C、寫 E；保留統一 CLI |
| Python dependencies | `components/person_c/requirements.txt` | 放 Python binding、torch/vision 等直接依賴並固定版本 |
| OS/OpenSlide dependencies | `components/person_c/Dockerfile` | `apt` library、CUDA base 等不應寫進 requirements |
| 預設 config | `components/person_c/configs/default.json` | ROI size、threshold、level/magnification 等 |
| Runtime/model manifest | `components/person_c/component.yaml` | GPU/VRAM、RAM、model revision、timeout |
| C fixture | `integration/fixtures/input/C_wsi.json` | demo URI 不需要真的存在；正式 smoke fixture 應另備小圖 |
| E expected output | `integration/artifacts-local/E_rois.json` | 可直接看到 URI+coordinate 的交換方式 |
| C/E schemas | `contracts/schemas/C_*.json`、`E_*.json` | 座標語意要由全組共同鎖定 |
| Model checkpoint | host `/models/person-c/<model>/<revision>/` | 唯讀 mount；config 記 revision/hash |
| 真實 WSI | host `/data/wsi/...` | 唯讀 mount 到 container 的穩定位置，例如 `/data` |

## 最重要：先鎖定座標語意

交付前要和丁確認下列定義，不能只口頭約定：

- `x/y` 的原點是否為左上角。
- `x/y/width/height` 是 level 0 座標，還是 `coordinate.level` 對應 level 的座標。
- width/height 的單位是 pixel。
- 邊界是半開區間 `[x, x + width)` 還是其他定義。
- `mpp` 是原始 WSI 還是 extraction level 的值。
- `magnification` 如何推導；未知值如何表示。
- ROI 是否允許重疊，以及相同 ROI 的 stable ID 如何產生。

目前 schema 使用 `coordinate.level` 明示 level。正式版建議把上述規則寫入 C/E schema 的
`description`，並準備一張已知座標的小型測試影像做 round-trip test。

## WSI 與 ROI pixels 怎麼處理

不要做：

```text
E.json = {"image": "很長的 base64..."}
```

應做：

```text
E.json = image_uri + wsi_id + roi_id + coordinate + resolution
```

丁收到 E 後，用同一個 mounted `image_uri` 讀出 pixels。若跨機器執行，`image_uri` 應是兩邊
都能解析的 object storage URI 或標準 mount path，而不是丙個人電腦上的絕對路徑。

## 套件與 CUDA 的分工

- `torch==...`、Python OpenSlide binding：`requirements.txt`。
- `libopenslide`、系統影像 codec：`Dockerfile`。
- CUDA/cuDNN：由選定的 base image 固定，並與 torch wheel 相容。
- GPU/VRAM 最低需求：`component.yaml`。
- 模型權重：外部 `/models` mount。

正式接入 GPU 後，應另記錄 driver/runtime 相容範圍，並用一台 clean GPU machine 做 container
smoke test。

## 交付前自己跑

```bash
python3 -m components.person_c.interest_pattern \
  --input integration/fixtures/input/C_wsi.json \
  --output /tmp/E_rois.json \
  --config components/person_c/configs/default.json

python3 pipeline/run_pipeline.py
python3 -m unittest discover -s tests -v
```

## 完成定義

- C→E 通過 contract validation。
- E 不包含 pixels，且每個 ROI 都有 stable `roi_id`、`wsi_id`、URI、座標、level、mpp。
- 丁能使用 canonical E 讀出完全相同的 ROI 範圍。
- 缺檔、WSI 損壞、座標越界、GPU OOM 有明確錯誤與 non-zero exit code。
- image 不包含 WSI、病人資料或大型 checkpoint。

