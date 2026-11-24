# CHANGES — 收容所系統最小差異修改

基準：本對話先前交付的 `shelter_complete_updated_full.zip` 中 `shelter_complete_ready/`。本次不重新建專案，不修改模型、不重設 SQLite；不包含完整專案。**需確保本機準備覆蓋的版本即為該基準，否則請先核對。**

## 修改範圍

本次修改 **8** 個既有檔案、新增 **4** 個程式/測試檔案、刪除 **0** 個檔案；另新增交付說明文件三份。

### 已修改（完整檔案，可直接覆蓋原相對路徑）

| 相對路徑 | 變更內容與原因 |
|---|---|
| `frontend/src/components/common/DailyTimeline.tsx` | 員工回報浮層使用點擊按鈕的 DOM 邊界定位；按需左右／視窗邊界調整，Portal 防止撐高時間卡；員工顯示重疊任務分欄；管理者已完成卡片顯示「✓ 已完成」與真實回報備註。 |
| `frontend/src/components/common/DailyTimeline.css` | 僅新增時間表範圍內的浮層、重疊欄位、完成標籤、備註文字樣式；保留既有排程時間與未完成任務配色。 |
| `frontend/src/pages/StaffHome.tsx` | 「回報」／「編輯回報」切換、讀回已儲存欄位、取消與提交；編輯已完成任務時僅允許更新備註，不意外改寫健康判定或注射紀錄；發現同員工衝突顯示警告。 |
| `frontend/src/services/api.ts` | 沿用現有 `request()` 補 `stage2Evaluation`；在回報請求新增**可選** `edit_report`，派工回應新增可選 `administered_date`。 |
| `backend/main.py` | 已完成回報可使用原 `PUT /api/tasks` 以 `edit_report=true` 原地更新 `task_overrides.note`，保留同筆任務與醫療紀錄；查詢員工派工時回傳施打日期；避免同動物舊傷病任務在換日期／刷新後反覆生成並標成新任務；不刪既有不確定的歷史紀錄。 |
| `frontend/src/pages/ResourceBoard.css` | 僅限定 `.resource-pool` 中非已完成任務的一般文字為黑色；保留圓點與淡色背景，不碰其他兩欄。 |
| `frontend/src/pages/ResourcePage.tsx` | 將圖表前的長段預測說明、補值與外推警示移到圖表區底部 `<details>` 收合區，不修改曲線資料與計算。 |
| `frontend/src/pages/EvaluationPage.tsx` | Stage 2 指標查詢由絕對 `/api/...` 原生 `fetch` 改走專案既有 API request，沿用 API base URL、登入資訊與錯誤處理；指標仍來自原始已保存評估檔。 |

### 新增

| 相對路徑 | 原因 |
|---|---|
| `frontend/src/components/common/timelineLayout.ts` | 單純前端計算重疊時間區間水平欄位；端點剛好相接的任務仍各自單欄。 |
| `backend/tools/audit_injury_task_duplicates.py` | 唯讀列出傷病任務多版本候選資料（`mode=ro`），**不刪除**、不自動更正。 |
| `frontend/tests/test_local_minimal_update.cjs` | 區間欄位真實運算單元測試、TSX 語法與連接點靜態檢查。 |
| `tests/test_local_minimal_update.py` | 使用暫存 SQLite 複本測試回報備註原地更新、醫療判定保護、刷新不增傷病任務、已保存模型指標載入。 |

## 不變事項

- 無 SQLite schema 變更、無 migration；原 `backend/showcase.sqlite3` 位元雜湊與基準相同，且不包含於差異包。
- 不修改模型權重、訓練資料、LightGBM Hazard、CatBoost、預測公式、Monte Carlo、OR-Tools 排程、派工驗證、員工時間數值或 30 天預測曲線。
- 既有 `requirements.txt` 和 `package.json` 完全不變，不需因這次修改更新依賴。
- 既有報告權限檢查（非管理者僅能回報自己已指派任務）保留。

## API 相容性

- **請求擴充（可選）**：`PUT /api/tasks` 可帶 `edit_report: true`，只對已完成且真實儲存的任務有效；只能更新備註，改動醫療結果將回 HTTP 409。普通舊請求行為維持。
- **回應擴充（可選）**：`GET /api/staff/assignments` 任務加入 `administered_date`。沒有刪除或更名欄位。

## 傷病任務與未完成事項

既有 SQLite 中同一動物的 `優先確認健康狀況` 曾存在多個 `@日期` 版本，部分另有派工或回報資料。源頭是每日渲染 API 對舊日期 task ID 加新日期後可能持久化。本次避免該路徑對**已有傷病任務歷史**的動物再產生新日期項目，也不再把舊日期版本標示成「新增任務」。已存在紀錄**保留，不做假定式合併或自動刪除**。

**限制**：資料庫沒有獨立的健康事件 ID；對同一動物的新一輪獨立傷病事件與舊事件，僅靠現有 animal_id + label 無法完整區分，也不能宣稱已建立完整事件級唯一鍵。現有系統的 explicit employee-report 觸發流程保留；如需完全正確支援同動物多次相異傷病事件，須另行明確授權引入事件 ID 及安全遷移。此項保守限制不應透過刪除舊資料掩蓋。可先用唯讀工具檢視原紀錄。

## 代碼來源與原文節錄

以下均摘自本次所依據的基準專案（非外部資料）：

- `frontend/src/pages/EvaluationPage.tsx` 原連線：`fetch('/api/stage2/evaluation?days=30')`，未沿用 `api.ts` 的 base URL。
- `backend/main.py` 原換日機制：`if task_id in previous_dates and previous_dates[task_id]!=WORK_DATE.isoformat():task_id+=f'@{WORK_DATE.isoformat()}'`。
- `backend/main.py` 原已存在傷病追蹤任務判斷：`existing=c.execute('SELECT 1 FROM generated_tasks WHERE task_id=?',(task_id,)).fetchone()`；說明 task_id 不含獨立傷病事件 ID。
- `frontend/src/components/common/DailyTimeline.tsx` 原按時間高度：`Math.max(0,schedule.position(t.e)-schedule.position(t.s)-4)`；本次不修改此幾何比例。

