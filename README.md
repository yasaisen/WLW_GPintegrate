# WLW integration mini demo

這是一個刻意做小、但可以實際跑通的 **contract-first、containerized batch DAG**。它把
`WLW_arch.png` 的甲～戊、`[A]`～`[H]` 與最終 `[I]` ROI 做成可執行範例；模型、WSI 演算法與 CLEE
邏輯都是 deterministic mock，重點是展示「如何整合」，不是重現研究方法。

## 圖與程式的對應

| 人員 | 此 demo 的 executable | 輸入 | 輸出 |
|---|---|---|---|
| 甲 | `report_decompose` | B | D |
| 乙 | `knowledge_retrieval` | A、D | F |
| 甲 | `query_generation` | F | G |
| 丙 | `interest_pattern` | C | E |
| 丁 | `visual_filter` | E、G | H |
| 戊 | `clee` | D、H | I：CLEE selected ROIs（核心最終產物） |

執行關係如下：

```text
B report ──> 甲/report_decompose ──> D dx_pairs ───────────────┐
                                         │                    │
A literature ───────────────> 乙/retrieval ──> F chunks       │
                                                │              │
                                                v              │
                                      甲/query_generation      │
                                                │ G queries    │
                                                v              v
C WSI reference ─> 丙/interest_pattern ─> E ROIs ─> 丁/filter ─> H ─> 戊/CLEE ─> I selected ROIs
```

DRGVLM 不在核心 DAG 內；它只是讀取 I 做下游實驗的其中一個 evaluation consumer。

注意 E/H 中沒有 base64 image。交換的是 `image_uri + coordinate + resolution`，因此大型
WSI 不必在元件間複製。

## 1. 不用 Docker，先看一次完整流程

本 demo 只有 Python standard library dependency：

```bash
cd WLW_integrate
python3 pipeline/run_pipeline.py
```

每一步都由 orchestrator 以相同 execution contract 呼叫：

```text
python3 -m <component> \
  --input <artifact.json> [--input <another-artifact.json>] \
  --output <artifact.json> \
  --config <config.json>
```

輸出會寫到 `integration/artifacts-local/`：

```text
D_dx_pairs.json
F_chunks.json
G_queries.json
E_rois.json
H_matches.json
I_selected_rois.json
```

這些中間檔就是圖上的箭頭；直接打開它們會比只看架構文字更有感。

## 2. 單獨把一個元件當 black box 執行

例如甲的 Report Decompose：

```bash
python3 -m components.person_a.report_decompose \
  --input integration/fixtures/input/B_report.json \
  --output /tmp/D_dx_pairs.json \
  --config integration/configs/report_decompose.json
```

元件內部未來可以換成 PyTorch、LLM 或院內演算法；integration layer 只依賴 CLI、D schema
與 exit code，不需要 import 甲的 class。

有兩種上游資料的元件只是重複 `--input`。例如丁：

```bash
python3 -m components.person_d.visual_filter \
  --input integration/artifacts-local/E_rois.json \
  --input integration/artifacts-local/G_queries.json \
  --output /tmp/H_matches.json \
  --config integration/configs/visual_filter.json
```

## 3. Contract test

`contracts/schemas/` 是 A～I 的 canonical JSON Schema。runtime 會在讀取輸入及寫出輸出時
各驗一次，fail fast；測試再驗證 canonical fixtures、整條 pipeline 與一個刻意破壞的 artifact：

```bash
python3 -m unittest discover -s tests -v
```

本 demo 為了零 dependency，`contracts/runtime.py` 實作了本專案 schema 所需的 JSON Schema
子集合。正式專案建議直接用 `jsonschema`、Pydantic，並把 `contracts` 發布成有版本的 package。

## 4. Docker Compose 整合測試

每位成員有自己的 Dockerfile；不是共用同一個 Python environment：

```bash
cd integration
LOCAL_UID=$(id -u) LOCAL_GID=$(id -g) \
  docker compose up --build --abort-on-container-failure
```

Compose 用 `service_completed_successfully` 表達 DAG 依賴，產物會留在
`integration/artifacts/`。傳入 host UID/GID 是為了避免 bind mount 的產物變成 root-owned。
這裡把 Compose 當 E2E integration test，而
`pipeline/run_pipeline.py` 才是清楚、可讀的 scientific pipeline controller。

若在 HPC 執行，可將相同 image 推到 registry，再由 Apptainer 拉 OCI image；資料與模型應
以唯讀 mount 提供，不要 `COPY` 進 image。

## 5. 每位成員要交什麼

這個資料夾示範了以下交付邊界：

1. `contracts/schemas/*.schema.json`：A～I 資料 contract 與 schema version。
2. `integration/fixtures/input/`：canonical input example。
3. `components/person_*/`：統一 CLI 的 independent executable。
4. `components/person_*/requirements.txt` 與 `Dockerfile`：各自的 Python 與系統 runtime。
5. `tests/`：contract test 與 E2E smoke test。
6. `component.yaml`：owner、I/O、資源與 entrypoint manifest。

每位成員的詳細準備清單：

- [甲：Report Decompose / Query Generation](components/person_a/PREPARATION.md)
- [乙：Knowledge Base / Retrieval](components/person_b/PREPARATION.md)
- [丙：WSI Interest Pattern Extraction](components/person_c/PREPARATION.md)
- [丁：Visual Attribute Extraction / Matching](components/person_d/PREPARATION.md)
- [戊：CLEE / Downstream Handoff](components/person_e/PREPARATION.md)

實際接入時，每個 mock 函式可被真正方法逐一替換；只要 CLI 和 A～I contracts 不變，其他
成員與 pipeline 不需跟著重寫。

由既有 CLEE metadata 反推的第一版欄位提案與尚待確認事項，整理在
[`contracts/METADATA_DERIVED_CONTRACTS_V0_1.md`](contracts/METADATA_DERIVED_CONTRACTS_V0_1.md)。
