# V5-B3.1：子程序測試歸屬

## 根因與機制

原 `build_coverage_map.py` 只在 pytest 主程序啟動 coverage，並以 `test:<正式 pytest ID>` 切換 context。固定版 SQLGlot 的 optimizer 與 executor 測試使用 `ProcessPoolExecutor(spawn)`；子程序執行的 SQLGlot 程式碼和結果序列化不在主程序 coverage 內，故索引缺少「發起測試 → 子程序方法」關係。普通 helper 呼叫仍在主程序，原本就能記錄；子程序啟動時的匯入執行則是另一種未歸屬活動。

新增建置期專用 `subprocess_coverage.py`：攔截 `ProcessPoolExecutor.submit`，把當前正式測試 ID、提交順序與父任務脈絡一起送進 worker。每個任務用獨立的 coverage 追蹤 SQLGlot 行，包括結果序列化期間的 Python 呼叫；以唯一任務脈絡寫出紀錄。重用 worker 時每項任務重新設定脈絡，巢狀提交沿用原發起測試並加上父任務路徑。主程序把已提交與實際寫出的任務核對，缺失、未知父測試與收集期任務分開記錄。子程序啟動匯入及其他啟動方式仍標為未知；沒有把缺少覆蓋當成無影響證明。

`build_coverage_map.py --subprocess-spool <全新目錄>` 將子程序行合併進原有逐行與方法索引，並加入 `child_coverage` 任務關係、狀態、CPU 及未解決訊號。原 `coverage_index.json.gz` 保留；新資料放在 `coverage_index_b31.json.gz`。正式容器透過 `V5_COVERAGE_MODE=baseline|subprocess` 選擇索引，預設 `baseline`；原 `V5_FIXTURE_MODE` 仍獨立可用。排程、patch 分析與原有回退規則未改。

重建時先確認 `D:\workspace\rwx-blast-radius\sqlglot-pinned` 的 HEAD 為 `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`，使用現有 `rwx-v5-coverage:py313` 映像；唯讀掛入該來源與正式 `tests.json`，可寫掛入 V5 工作區，再執行：

```text
PYTHON_CPU_COUNT=2 SKIP_INTEGRATION=0 python3 -B /work/build_coverage_map.py --source /source --manifest /manifest.json --output /work/coverage_index_b31.json.gz --subprocess-spool /work/subprocess_full_b31.tmp
```

`--subprocess-spool` 要求全新目錄，避免把舊任務紀錄混入新索引。建置容器使用無網路、唯讀根檔案系統、2 CPU、4 GB 記憶體與暫存 `/tmp`；答案檔沒有掛入。

## 實際執行證據

- Python 3.13 受控案例驗證單一、多個、巢狀、失敗、未知父測試、模組匯入期提交、同類別不同測試及結果序列化。重用一個 worker 的兩個測試保持不同 ID；失敗任務仍保留發起者。任務內容在不同次執行中一致，CPU 時間除外。
- 固定 SQLGlot 的兩項 optimizer 正式測試試跑：2 項通過、739 個子測試通過；記錄 691 個子程序任務。沒有缺失紀錄。主程序單獨觀測的部分方法關係由子程序執行得到補強。
- 全套新索引：1620 項正式測試通過、1 項正式跳過，25,440 個子測試通過；正式 ID 缺失 0、額外 ID 0、pytest 失敗 0。記錄 **2,183** 個子程序任務，涉及 **24** 個正式測試；任務脈絡全部唯一，任務狀態全部正常，未知父測試及缺失任務均為 0。固定版測試另有直接 `subprocess.run`，本輪不追蹤。

| 索引／建置指標 | 舊索引 | 新索引 |
| --- | ---: | ---: |
| 壓縮索引大小 | 721,404 bytes | 760,698 bytes |
| 來源檔數 | 170 | 176 |
| 方法條目 | 3,350 | 3,407 |
| 來源行 × 正式測試關係 | 2,504,223 | 2,565,148 |
| 新增／移除關係 | — | **+60,925／0** |
| 同條件全套建置牆鐘時間 | 176.898 秒 | 317.866 秒 |
| 主程序 CPU | 153.781 秒 | 155.688 秒 |
| 可歸屬子任務 CPU | 舊版未記錄 | 101.301 秒 |

建置比較都在同一 Python 3.13 映像、2 個可見 CPU、4 GB 記憶體限制下完成。新建置多花 **140.968 秒**；舊版未記錄子程序 CPU，因此兩欄 CPU 不能直接當作總 CPU 差。新建置主程序峰值 RSS 約 2,023,132 KiB，子程序不包含在這個數字內；容器在 4 GB 限制內完成。臨時任務紀錄約 20.0 MB，只在建置時使用，不進正式映像。

由固定來源執行得到的新增方法關係包括：`_should_eliminate_join` 新增 5 個正式測試、`serde.dump` 新增 13 個、`BigQueryParser._parse_table_parts` 新增 5 個。這些是已觀測的正向關係，不代表其餘測試安全。

## 本地樣本評分

同一 V5-B3.1 映像分別選用舊、新索引；兩者都開啟 B2.2 fixture-only 模式，評分答案只交給離線官方 `score.py`。

| 指標 | B2.2 舊索引 | B3.1 子程序索引 |
| --- | ---: | ---: |
| 官方本地 Simulated | 1393.257 秒 | **552.611 秒** |
| 漏檢 commit | 3 | **0** |
| 全套回退 | 11／30 | 11／30 |
| 30 案選取測試次數合計 | 18,501 | 18,537 |
| 單次 selector CPU | 294.568 ms | 310.862 ms |
| 單次 selector 峰值 RSS | 133,836 KiB | 139,092 KiB |

10 個 patch 的候選集合增加，合計新增 36 次測試選取，移除 0 次。此前三個漏檢案的候選數變化為 **24→29、24→37、137→142**；新增正式測試編號分別為 `1106,1325,1355,1440,1441`；`1324,1325,1327,1353,1355,1362,1375,1377,1417,1420,1440,1441,1454`；以及 `1314,1353,1355,1378,1420`。本地樣本新增漏檢為 0，三個舊漏檢案均被偵測。新索引也讓部分 patch 選到較慢的測試，使不含漏檢罰分的排程成本由 493.257 秒增至 552.611 秒；900 秒罰分消失後，淨改善 **840.646 秒**。這些編號只用於離線結果說明，沒有寫入選擇規則或索引生成邏輯。

容器未設模式時仍使用舊覆蓋索引與保守 fixture 模式，官方本地分數維持 1669.893 秒、3 次漏檢。兩種實驗模式的 JSONL 都由官方評分器接受；診斷只寫 stderr。

## 限制與結論

子程序啟動／模組匯入早於被包住的任務，無法精確歸屬；直接 `subprocess.run`、其他程序啟動方式、原生程式碼及未執行路徑也未覆蓋。每個任務的結果先在 worker 內序列化以追蹤 `__reduce__`，固定版 1620 項測試均通過，但這是建置期插樁，對其他回傳型別的語義仍需警惕。主程序中的非同步管理執行緒亦未被證明完全無跨測試歸屬。全套回退未被放寬，隱藏 patch 的漏檢風險仍在。

**建議：GO**，B3.2 可在此可重現索引上做有界驗證；**NO-GO**，目前不能僅憑本地樣本零漏檢就宣稱安全正式提交。B3.1 本輪未開始 B3.2。

本輪新增／修改：`subprocess_coverage.py`、`build_coverage_map.py`、`test_subprocess_coverage.py`、`test_build_coverage_map.py`、`v5_main.py`、`Dockerfile`、`coverage_index_b31.json.gz`、`V5_B3_1_report.md`、`CONTEXT.md`。Python 3.13 編譯通過；相關單元測試 **67 通過、0 失敗**。未修改 V1–V4、官方評分規則或樣本答案，未提交、推送或排行榜提交。
