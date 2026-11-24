# 收容所完整專案：Stage 2 AI 整合版

這是**完整資料夾**，不是差異包。由使用者提供的 `shelter_complete_ready(2).zip` 與 `stage2_training(1).zip` 組成，保留原 SQLite、原 React 頁面、原模型與訓練資料。

## 已改動與未改動
- `backend/stage2_service.py`：LightGBM 競爭風險條件存活、CatBoost 遞迴預測、依個體/物種資源係數與 600 次 Monte Carlo 計算飼料及工時；加入獨立測試分組 Brier 診斷。
- `frontend/src/pages/ResourcePage.tsx` 與 `frontend/src/pages/ResourceBoard.css`：派工時間表右側三角形跟隨所選員工列高度，捲動/視窗大小變動時同步；既有配色與版型保持原樣，底部兩圖讀取後端新模型。
- `frontend/src/pages/EvaluationPage.tsx`：實際測試指標、30 天各原因校準分組、CatBoost 物種分組、長期 Brier 有效性。
- `frontend/tsconfig.json`：為相容現有 `DailyTimeline.tsx` 中 `Array.at()`，只將 TypeScript 編譯目標及 lib 設為 ES2022；無畫面變化。
- `tests/test_stage2_integration.py`：模型、公式、30 天日期和指標 API 的整合測試。
- 未修改其他 React 頁面的 JSX/CSS、既有 `backend/main.py`、資料庫內容或模型權重。

## 日期、模型與上、下界
- 預測基準日 2026-10-22，顯示 2026-10-23 ～ 2026-11-21 共 30 天。
- 現有動物：每隻動物「條件仍在所機率 S(d+t)/S(d) × 該個體資源係數」。
- 新入所群體：依物種累加 CatBoost 預測入所、扣除 CatBoost 預測離所（非負截斷），乘以 `resource_by_condition.csv` 該物種平均係數。
- **避免重複扣除**：LightGBM 已預測現有動物離所，CatBoost 預測離所**只扣除新增群體**，否則會重複扣現有離所。
- Monte Carlo 600 次、固定 seed 20261023：依每隻動物條件存活率抽樣、以每日獨立 Poisson 抽樣新增入所與離所；取第 5 與第 95 百分位。**這是模型假設下的情境帶，不是已驗證的 90% 預測區間/信賴區間**。
- 「原因別 Hazard」歸一規則：當同一天原因別危險率和大於一，按總和縮放；各原因每日事件機率先乘前一日存活機率、再累加成 CIF，與 S(t) 加總約等於 1。

## 長期在所模型限制（重要）
- 隨附最佳 LightGBM Hazard 模型**實際訓練至第 180 天**。為使任意正整數在所天數可計算條件預測，**第 181 天起沿用第 180 天的原因別 Hazard**（常數尾端，分段指數存活尾），以前向相乘計算 S(d+t)/S(d)，避免 S(d) 浮點下溢。不會直接給 0% 或 100%。
- 此為**可計算的模型延伸假設，不是重新訓練成已驗證任意天數模型**。回傳 `tail_extrapolated: true`、警告「此預測超出主要訓練資料範圍，可靠度未驗證」。
- `inputs/lightgbm_hazard.csv` 中 test split 最長觀察 79 天；因此無法用其驗證 90/120/150/180 天 landmark 預測的 30 天 Brier。評估頁會如實保留空值。
- 30 天 landmark、再預測 30 天：以 train split 估計設限 KM、在 test split 計算 IPCW **全原因**存活 Brier；它不是原因別的 CIF Brier。

## 模型評估可追溯來源
- `stage2_training/outputs/lightgbm_hazard/metrics_by_cause.csv`：欄位 `cause,cause_specific_c_index,brier_7d,brier_30d,...,integrated_brier_score`。
- `stage2_training/outputs/lightgbm_hazard/calibration.csv`：欄位 `cause,horizon,bin,n,predicted,observed`。
- `stage2_training/outputs/catboost/{intake_count,exit_count}/metrics.json`：獨立測試 MAE、RMSE、WAPE。
- `stage2_training/outputs/catboost/{intake_count,exit_count}/metrics_by_species.csv`：依物種分組。
- `stage2_training/inputs/resource_by_condition.csv`：資源情境係數，不是實際消耗量。
- 評估檔沒有共同訓練雜湊以證明版本完全一致，會在 API 附註；scikit-learn 版本需與 pickle 訓練版本相容。

## Windows PowerShell 啟動
先在解壓縮後的 `shelter_complete_ready` 根目錄開兩個終端機。Python 建議使用 3.11～3.13 並先建立虛擬環境。

後端：
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```
前端（**另一個**在專案根目錄開啟的終端機）：
```powershell
cd frontend
npm install
npm run dev
```
前端顯示網址以 Vite 執行時輸出為準；API 文件 http://127.0.0.1:8001/docs。

## 檢查
```powershell
# 在專案根目錄執行
python -m unittest discover -s tests -p test_stage2_integration.py -v
```
上列 3 個測試已於目前環境通過；前端 TypeScript 型別檢查通過；本環境的原 Windows `node_modules` 不含 Linux Rollup 原生套件，無法在本環境完成 Vite bundle。原 `node_modules`、建置快取、舊 SQLite 備份、舊差異包說明、訓練暫存日誌已從交付物清理，**未刪除原始模型、訓練資料、Optuna 記錄與主要 SQLite 資料庫**。
