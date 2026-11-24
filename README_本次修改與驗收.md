# 收容所系統：本次修改、驗收與啟動說明（2026-11-17）

> **以你提供的 `shelter_complete_integrated(1).zip` 為唯一原始碼基礎**，沿用 `shelter_complete_ready` 目錄結構。原始 `README_完整整合說明.md` 說明上一版功能；**本文件為這次修改的增補說明，若前後不一致，以此文件為準**。

## 交付內容

- `backend/requirements.txt`、`stage2_training/requirements.txt`、React 前端設定、SQLite `backend/showcase.sqlite3`、CatBoost/LightGBM 權重、輸入 CSV、訓練程式、Optuna 研究資料庫、現有測試和遷移程式都保留。
- 不包含虛擬環境、`node_modules`、`__pycache__`、`.pyc`、執行時備份或編譯產物。**原始 SQLite 沒有執行重設**；僅在 SQLite 複本上測試重設機制。
- 清除檔案：`frontend/sample_animal_needs_preview.csv`（與 `backend/animal_needs_preview.csv` 的 SHA-256 完全相同，且沒有其他原始碼引用；保留後端原件）。清除測試執行時產生的 `__pycache__/*.pyc`，均非原始 ZIP 檔案。
- 重要：**不因檔名有 `old`/`backup`/`test` 就移除**。原有訓練用 Optuna DB、模型評估、測試及資料遷移均保留。

## 修改對照表

| 項目 | 修改位置 | 驗收行為 |
| --- | --- | --- |
| 工作完成藍橘長條 | `frontend/src/pages/ResourcePage.tsx`, `ResourceBoard.css` | 依同一工作日指派的任務**筆數**計算藍色已完成、橘色未完成；0 筆灰色；`工作完成 X/Y` 不變 |
| 已完成仍顯示於時間表 | `ResourcePage.tsx`, `StaffHome.tsx`, `DailyTimeline.tsx`, `DailyTimeline.css` | 保留 SQLite 的員工、開始／結束時間；淡灰底、灰字、刪除線；重新回報需要先重新開啟 |
| SQLite 展示資料重設 | `backend/tools/reset_showcase_tasks.py`, `backend/main.py` | 明確執行 CLI 才重設；先備份；保留動物／員工／醫療實際紀錄；重新整理不自動重新最佳化 |
| 80/80 資源覆蓋 | `backend/stage2_service.py`, `backend/main.py` | 個體資源缺值先依 SQLite 個體值、再依既有對照表補值，沒有合理數據時明確回報錯誤 |
| 個體 Hazard 預測 | `backend/stage2_service.py` | 維持 LightGBM、競爭風險及未來每日 Hazard 連乘；第 180 天後固定尾端 Hazard 作**未驗證外推**，不強制歸一到 100% |
| 新群體離所重複扣除 | `backend/stage2_service.py` | CatBoost 全群體離所量先扣除既有動物的 LightGBM 預期離所，再將剩餘離所量用於新入所群體 |
| 需求圖與個體報表 | `frontend/src/pages/ResourcePage.tsx`, `frontend/src/services/api.ts` | 實際覆蓋數、補值數、外推／稀疏數、個體條件存活率；維持兩張曲線與 Monte Carlo 情境區間 |
| 三欄黑框 | `frontend/src/pages/ResourceBoard.css` | 只對既有今日任務池、員工時間表、員工負載加 `1px solid #000`；不改 grid 比例 |
| 任務池淡色背景與黑字 | `frontend/src/pages/ResourcePage.tsx`, `ResourceBoard.css` | 保留原優先級圓點顏色，未完成任務使用淡紅／橘黃／綠，任務文字黑色 |
| 15/30/60 分鐘高度 | `DailyTimeline.tsx`, `DailyTimeline.css` | 固定每 30 分鐘 88px；15 分鐘占 44px，任務卡片內縮 2px；回報表單移到時間軸下方避免遮蓋其他任務 |
| 即時狀態 | `StaffHome.tsx`, `ResourcePage.tsx` | 本視角 mutation 即時更新狀態；同瀏覽器跨分頁 BroadcastChannel 更新；其他裝置最長約 1 秒輪詢 |
| Model bundle 相容性 | `backend/requirements.txt` | 提高 scikit-learn 版本下限至隨附模型序列化時使用的 1.9.1（在已安裝 1.8 的環境載入會產生警告） |

**範圍說明：**模型權重、`stage2_training` 訓練流程、原有 OR-Tools 求解規則及正常工作的 API 路徑不變。`main.py` 僅增加重設旗標／防重複完成／個體資源查看及必要的後端配合。

## 使用原有 venv 與 node_modules 啟動（Windows PowerShell）

先將整個 `shelter_complete_ready` 資料夾解壓縮／覆蓋至原專案位置；**保留你原有的虛擬環境及 `frontend/node_modules`**。以下命令由 `shelter_complete_ready` 根目錄開始。

後端（第一個終端機）：

```powershell
cd backend
# 先啟動你已存在的 venv（位置若不同，調整路徑）：
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

前端（第二個終端機）：

```powershell
cd frontend
# node_modules 已存在可略過；缺套件時先 npm ci
npm run dev
```

網站：`http://127.0.0.1:8000`。保留原有前端 8000 → 後端 8001 的 Vite proxy。

## SQLite 資料重設（只有刻意執行才會生效）

**先關閉後端**，在專案根目錄執行：

```powershell
# 1. 只預覽將清除多少展示狀態，不會修改資料
python backend/tools/reset_showcase_tasks.py

# 2. 確認後才真正清除；會在 backend/reset_backups/ 留下完整 SQLite 備份
python backend/tools/reset_showcase_tasks.py --apply --confirm RESET_TASKS

# 3. 重新啟動後端並在瀏覽器重新整理一次
```

清除 `assignment_snapshot`、`generated_tasks`、`task_metadata`、`task_report_history`、`task_overrides`、`task_animal_baseline` 的**展示任務資料**，並在不覆蓋其他人修改的情況下還原由回報造成的動物欄位變更。`animals`、`staff`、`profiles`、`vaccination_records`、`deworming_events` 和模型資料**不刪除**。重設工具先建立 SQLite backup，使用交易及 `PRAGMA foreign_key_check` 驗證；不通過便 rollback。

**重新整理瀏覽器不是重設操作**。重設後會記錄 `demo_ui_state.reset_mode=1`，頁面開啟時不再自動最佳化；待管理者按資源配置頁原有最佳化標題旁新增的 **「重新最佳化派工」** 按鈕（此按鈕僅在重設後顯示），才重新派工並清除旗標。若要還原，停止後端，將備份檔覆蓋 `backend/showcase.sqlite3`（先自行額外備份目前版本）。

## 30 天模型與數值定義

- 預測基準日期仍保留原專案 `2026-10-22`，輸出 `2026-10-23`～`2026-11-21`，不更動原有日期設定。任務派工日期仍遵循原系統工作日期。
- 以 `S(d+t) / S(d)` 的**逐日條件 Hazard 連乘**求現有動物仍在所率；不用在非常小的 `S(d)` 上直接相除，沒有最後一天強制離所 100%。
- LightGBM 競爭風險模型的 `max_day` 之外把天數特徵封頂，採最後一日 Hazard 外推；**可計算不等於外推已驗證**。
- 個體資源的補值依既有 `resource_by_condition.csv` 的物種、品種、年齡、健康參數；原 SQLite 個體數值有效時優先使用。無法匹配或入所日期不合理時明確失敗，不虛報 80/80。
- Monte Carlo 仍為 600 次，取 5%～95% **模擬情境百分位範圍**，未經回測校準，不是信賴區間。
- 原始 SQLite 中 162 筆動物，80 隻有效在所；本次實際跑模型 **80/80**，補值 80 隻、長期／稀疏警告 43 隻。這是**目前資料檔與預測基準日期**的結果，新增、離所或修正資料後會依實際內容重新計算。

## 測試與限制

測試命令（使用既有 Python 虛擬環境，從專案根目錄）：

```powershell
python -m unittest discover -s tests -p "test_stage2_integration.py" -v
python -m unittest discover -s tests -p "test_resource_coverage.py" -v
python -m unittest discover -s tests -p "test_task_demo_reset.py" -v
cd frontend
node tests/test_v5_ui.cjs
node tests/test_v6_ui.cjs
node tests/test_v7_ui.cjs
node tests/test_v8_ui.cjs
npm run build
```

在本次建置環境中，以上 Python 測試（Stage 2、80 隻覆蓋、SQLite 複本重設）與前端的 V5～V8 檔案／幾何檢查通過，TypeScript JSX 語法檢查通過。

**尚未完成的驗證：**本次建置環境沒有 `ortools`，且網路無法安裝，因此無法實際運行原有 OR-Tools 端到端 API、全部排程回歸測試；建置環境也沒有此專案的 `frontend/node_modules`，無法跑真實的 Vite production build。需在你既有環境中 `pip install -r backend/requirements.txt`、`npm run build` 並執行全部現有測試。**不能把靜態檢查說成求解器驗收已通過**。

## 修改檔案與刪除清單

詳見交付的 `CHANGES.txt` 和差異 ZIP。差異包保留從 `shelter_complete_ready/` 開始的原相對路徑，可以對照後套用；完整包則可以直接作為專案主資料夾。
