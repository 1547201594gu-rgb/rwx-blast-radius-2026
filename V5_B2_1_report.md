# V5-B2.1：Fixture reader 正式測試 ID 對接

## 根因與修正

`build_coverage_map.py` 的 fixture I/O 記錄使用原始 pytest node ID，例如 `tests/test_optimizer.py::TestOptimizer::test_simplify`；逐行 coverage 使用 `test:` 加此前綴。原 `impact_selector.py` 只接受後者，所以 65 筆觀測 fixture reader（分布於 62 個 fixture）全部無法在正式清單中對接。正式清單共 1620 個唯一 ID；本批 65 筆原始 reader 均可精確對應，沒有參數化 ID、重名或缺失的實際資料問題。

在 `impact_selector.py` 增加 `resolve_fixture_readers(readers, manifest)`，以正式 `tests.json` 的完整 ID 為唯一依據，接受原始 ID 與單層 `test:` 前綴，回傳排序後的正式編號、逐筆對應、未對應、歧義及收集階段讀取標記。短名稱和參數化基底不作猜測；正式清單編號、重複 ID、缺欄位與不合法路徑會直接報錯。`analyze_patch` 現會保留已對應 reader 的正向證據，明列未對應／歧義 reader，並對每個修改過的 SQL fixture 保留 `fixture_impact_completeness_unproved` 全套回退。索引與排程程式未改，也沒有建立特定 patch 或失敗答案規則。

## 11 案重新審計

「原／新候選」是**全套回退前**的正向證據數；「假設成本」只計這些候選的排程，不能當作安全可執行方案。原本 11 個 reader 均是完整但未被接納的原始 pytest ID；修正後各有 1 個精確正式 ID，剩餘未對應 reader 均為 0。

| Patch | 新對應正式 ID | 原／新候選 | 新候選假設成本 | 全套回退 |
| --- | ---: | ---: | ---: | --- |
| 2vdj | 1377 | 0／1 | 2,083 ms | 是 |
| 6vvp | 1383 | 0／1 | 2,037 ms | 是 |
| 986c | 1454 | 1／2 | 4,292 ms | 是；另有 Python 範圍風險 |
| bvw2 | 1302 | 0／1 | 2,061 ms | 是；另有 Python 範圍風險 |
| egys | 1434 | 0／1 | 2,596 ms | 是 |
| f4bn | 1375 | 0／1 | 2,007 ms | 是 |
| gbhk | 1302 | 0／1 | 2,061 ms | 是 |
| mthh | 1343 | 0／1 | 3,016 ms | 是 |
| nwnx | 1378 | 0／1 | 2,092 ms | 是 |
| rszg | 1382 | 234／234 | 13,112 ms | 是；reader 已在原候選內，另有 Python 範圍與匯入期風險 |
| st8f | 1335 | 0／1 | 2,008 ms | 是 |

30 個 patch 的診斷顯示：`fixture_reader_unresolved` 由 11 案降至 0；11 案均保留 `fixture_impact_completeness_unproved`。八個純 fixture patch 的單 reader 假設成本合計 17,900 ms，與 B1 的條件式估計一致；實際沒有因此省下排程時間。

## 驗證與限制

- Python 3.13 編譯：通過。
- V5 單元與既有回歸測試：46 通過、0 失敗；新增 10 項，涵蓋精確／帶前綴 ID、多 reader、重複、歧義、參數化基底、無效清單、收集期讀取及回退。
- 離線官方樣本評分：**1669.893 秒，漏檢 3 次，19 次全套回退**，與修正前一致；30 行 JSONL 正常。單次 selector CPU 診斷約 **284.995 ms**；修正前記錄為 236.151 ms，兩次單次量測不足以證明穩定性能差異。
- 覆蓋資料只記錄實際觀測的讀取，未證明條件式、共用、子程序或收集期的全部可能讀取者。原有三次漏檢仍在，V5 不能正式提交。

**結論：**B2.1 的 ID 對接已修復，可供後續研究使用；目前**不適合**啟用 fixture-only 選測。已觀測 reader 只提供正向證據，不能據此排除其他測試。

本輪新增／修改：`impact_selector.py`、`test_impact_selector.py`、`V5_B2_1_report.md`、`CONTEXT.md`；本地忽略的審計輸出與 JSONL 另行更新。未修改評分規則、穩定分支、覆蓋索引或 Dockerfile，未提交或推送。
