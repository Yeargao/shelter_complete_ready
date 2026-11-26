# V2 變更與驗收

- 總覽及資源配置改用即時資料，營運移除 30 天收容量、飼料、照護需求、上下界與個體存活顯示。研究模型改按需載入。
- 新增七天班表、獨立每日照護任務及單次任務、手動指派、分層 CP-SAT、確認前資料版本驗證。
- 資源配置採雙欄，提供篩選、日／週切換、拖曳與鍵盤／手機可用的表單替代操作。回報照護、異常處理、每日班表與醫療細節各自呈現。
- 快速回報、醫療日期欄位、手機拍照、私有照片及規則式／LLM 摘要接到七天任務。
- Vercel 從原始碼建置前端並轉送 FastAPI。資料庫與照片使用後端持久化設定。

## 實際驗收

| 項目 | 驗收方式 |
| --- | --- |
| 七天任務與遷移 | 暫存 SQLite 生成七個獨立每日任務，反覆讀取不重複；完成單日不影響其他日；同一筆單次醫療任務不重複 |
| 技能、出勤、休息、每日／每週工時 | CP-SAT 與跨日手動指派 API 回歸測試 |
| 時間重疊及跨日 | 指派 API 拒絕重疊及資格不符的指派；無頭 Chrome 驗證實際跨日拖曳與 390 px 點擊指派表單 |
| 變更與失效保護 | 請假後預覽變動，拒絕過期方案；鎖定仍可行時保留、不可行時回應衝突 |
| 新入所、離所、緊急工作 | 暫存 SQLite 上的事件及優先安排回歸測試 |
| 快速回報與醫療紀錄 | 本人回報、拒絕他人、重送不新增第二筆醫療記錄 |
| 照片及無模型設定 | 內容驗證、私有照片角色存取、規則式摘要及來源記錄 |
| 管理者同步 | 同一任務由員工回報，管理者讀取完成及尚未解決狀態 |
| 展示名單 | 80 隻、655 項任務的暫存副本得到 CP-SAT OPTIMAL，安排 319 項，確認套用成功 |
| 營運預測移除 | 前端原始碼斷言及 Chrome 請求紀錄確認資源頁與總覽無預測呼叫；研究測試保留 |
| 前端 | TypeScript、Vite production build、Vitest 與六個既有前端回歸腳本 |

既有後端 24 個測試及新增 7 個 HTTP 測試保留。兩個舊 Python 測試更新隔離載入設定，以支援週排程模組。六個舊前端腳本將已移除的單日版面或預測斷言改為週版面、任務池、任務 ID 回報及無預測呼叫檢查，保留健康頁與獨立時間表佈局的行為測試。

## 檔案

新增

- `.env.example`、`README_V2.md`、`CHANGES_V2.md`
- `backend/weekly_schedule.py`、`backend/care_summary.py`、`backend/care_photos.py`
- `frontend/src/components/common/ResourceOverview.tsx`、`TaskPhotos.tsx`、`scheduleDates.ts`
- `tests/test_weekly_schedule.py`

修改

- `.gitignore`、`vercel.json`
- `backend/main.py`、`backend/requirements.txt`
- `frontend/src/App.tsx`、`frontend/src/services/api.ts`
- `frontend/src/pages/AnimalDetail.tsx`、`AnimalList.tsx`、`Dashboard.tsx`、`ResourcePage.tsx`、`ResourceBoard.css`、`StaffHome.tsx`、`StaffHome.css`
- `frontend/tests/test_local_minimal_update.cjs`、`test_v5_ui.cjs`、`test_v6_ui.cjs`、`test_v7_ui.cjs`、`test_v8_ui.cjs`、`test_v9_ui.cjs`
- `tests/test_local_minimal_update.py`、`tests/test_schedule.py`

刪除檔案 0 個。資料庫原檔、研究資料、模型權重和既有建置輸出沒有隨程式修改。
