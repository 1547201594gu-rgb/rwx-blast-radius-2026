# V5-B2.2：SQL Fixture 單獨選測實驗

## 實作

在 `impact_selector.py` 增加兩種 `fixture_mode`：`baseline` 維持 B2.1 的全套回退；`aggressive_fixture_only` 僅當 patch 的**每個**改動都是同一路徑、具有有效 hunk 的既有 `.sql` fixture，且每個 fixture 的所有觀測 reader 都能精確對應正式測試 ID 時，選取 reader 編號的聯集。編號去重並排序。未知 patch、缺失或歧義 reader、收集期讀取、非 SQL fixture、混合 Python 改動、改名、刪除及檔案模式改動仍沿用原本回退。此模式保留 `aggressive_fixture_only_observed_readers_may_be_incomplete` 不確定性記錄。

`v5_main.py` 透過 `V5_FIXTURE_MODE=baseline|aggressive_fixture_only` 切換；預設為 `baseline`。正式 JSONL 仍只輸出答案，模式、候選數、回退原因及 CPU 診斷只寫入 stderr。排程器、Dockerfile、覆蓋索引與官方評分檔未改。

## 同一映像的離線樣本對比

| 指標 | Baseline | Aggressive fixture-only |
| --- | ---: | ---: |
| 官方本地 Simulated | 1669.893 秒 | **1393.257 秒** |
| 漏檢 commit | 3 | 3 |
| 全套回退 | 19／30 | 11／30 |
| 八個純 fixture patch 的排程成本 | 294,536 ms | 17,900 ms |
| 八案合計選取測試次數 | 12,960 | 8 |
| 單次 selector CPU | 281.190 ms | 290.882 ms |
| 單次峰值 RSS | 133,608 KiB | 133,608 KiB |

激進模式使模擬分數降低 **276.636 秒**，與八案的排程成本差完全一致；未增加本地樣本的漏檢。CPU 數字是各一次容器執行的診斷，不能當成穩定的效能差距。官方 `score.py` 的 Simulated 不含排行榜另計的 selector CPU。

本輪只優化 `tests/fixtures/optimizer/*.sql` 的八個純 fixture 修改，沒有對 Python 原始碼或混合 patch 改變選測決策。每案的觀測 reader 與排程如下：

| Patch | 正式測試 ID | 選取數 | 排程成本 |
| --- | ---: | ---: | ---: |
| 2vdj | 1377 | 1 | 2,083 ms |
| 6vvp | 1383 | 1 | 2,037 ms |
| egys | 1434 | 1 | 2,596 ms |
| f4bn | 1375 | 1 | 2,007 ms |
| gbhk | 1302 | 1 | 2,061 ms |
| mthh | 1343 | 1 | 3,016 ms |
| nwnx | 1378 | 1 | 2,092 ms |
| st8f | 1335 | 1 | 2,008 ms |

核對 30 行輸出及固定覆蓋索引：所有已觀測 fixture reader 均包含在各自排程內，沒有重複測試 ID；只有上述八案的排程改變。其餘 22 案與 baseline 相同。正式測試清單有 1620 個唯一 ID；覆蓋索引的 65 筆 reader 均能精確對應。

## 驗證與風險

Python 3.13 編譯通過。既有及新增單元測試 **57 通過、0 失敗**；本輪新增 11 項，覆蓋單一／共用／多個 fixture、去重、排序、有效編號、缺失與歧義 reader、未知與混合改動、改名、刪除、模式改動及錯誤模式。兩種模式的 JSONL 均由官方本地評分器接受。

觀測到的讀取只證明這些測試**曾經**讀取 fixture，不能證明讀取者清單完整。條件式讀取、共用 helper、收集期、子程序、動態路徑及未執行分支仍可能讓其他測試受到影響。本地八案沒有新增漏檢，不能推論隱藏 patch 安全；原有 3 次漏檢仍未修復。這是可重現的收益實驗，適合繼續研究，不適合作為安全選測或正式提交的依據。

本輪修改／新增：`impact_selector.py`、`v5_main.py`、`test_impact_selector.py`、`V5_B2_2_report.md`、`CONTEXT.md`；基準與激進模式的本地 `.tmp`／`.log` 驗證輸出由 `.gitignore` 排除。沒有提交、推送或排行榜提交，也未開始子程序歸屬工作。
