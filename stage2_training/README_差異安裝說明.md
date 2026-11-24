# 收容所 Stage 2 差異包 V2

## 放置位置
把本 ZIP **內容**複製至現有 `shelter_complete_ready/` 根目錄；保留資料夾相對路徑，僅覆蓋同名的修改檔。
請先備份 `backend/main.py`、`frontend/src/pages/ResourcePage.tsx`、`frontend/src/pages/EvaluationPage.tsx`。不要覆蓋或刪除 `backend/showcase.sqlite3`。

## 僅修改
- `backend/main.py`：資源預測基準日固定 2026-10-22，使第一天為 **2026-10-23**；保留既有 API 及其他介面。
- `backend/stage2_service.py`：30 天條件存活 + 物種 CatBoost 遞迴出入所 + 物種平均資源係數；Monte Carlo 模擬。
- `backend/requirements.txt`：新增推論相依套件。
- `frontend/src/pages/ResourcePage.tsx`：依所選員工重建並定位其時間表；其他佈局、配色、兩張圖線條設定均不改。
- `frontend/src/pages/EvaluationPage.tsx`：增加 LightGBM 和 CatBoost 指標與解釋，原有三張評估卡保留。
- `stage2_training/`：新增實際模型、訓練資料和測試評估檔。請只信任來源已確認的 pickle。

## 算法
- 以 2026-10-22 當作條件預測基準，第一點 2026-10-23，最後 2026-11-21。
- 對仍在所的個體，計算 `Σ P(第t天仍在所 | 基準日仍在所) × 個體每日資源量`。
- CatBoost 分物種預測入所及離所，以物種 `resource_by_condition.csv` 平均飼料／照護係數估算新群體每日資源量。
- 新群體存量為 `max(0, 前一日新群體存量 + 當日預測入所 − 當日預測離所)`，避免算出負的動物數；此為**對未來新入所群體**的情境估計，CatBoost 離所數不重扣已由 LightGBM 存活機率處理的既有動物。
- Monte Carlo 使用固定種子、600 次模擬：個體以共享均勻亂數依條件存活率抽樣留所，物種每日入所與離所以 Poisson 均值為 CatBoost 輸出抽樣，取每日模擬結果第5、95百分位作上下界；它是**未校準的90%模擬情境帶**，不是90%/95%置信區間，亦未包含模型參數估計不確定性。
- 如果既有動物在所天數超出 LightGBM `max_day`，不外推也不暗中填零；API 的 `estimated_animals` / `animal_count` 和 warnings 說明涵蓋率，因此曲線不能當作完整全所總需求。
- 日期截點後的真實記錄不作 CatBoost 特徵，避免未來資料洩漏。

## 模型評估新增
- LightGBM 各原因 `Cause-specific C-index`：風險排序能力（不是準確率）。
- 各原因 `IBS`：多個評估時間點的 Brier Score 梯形積分近似，越小通常越好，須與基準模型比較。
- `30 天 Brier` 與 `Calibration` 分組數：機率誤差與校準分組；沒有 30 天校準就會顯示缺失警告，不能聲稱已校準。
- CatBoost 分入所／離所的 `MAE`（平均絕對誤差）、`RMSE`（偏重大誤差）、`WAPE`（總絕對誤差相對實際總量百分比）。這些是獨立測試集的**單步**結果，不代表 30 天遞迴預測已驗證。
- 既有評估卡片與樣式不變；缺失指標、版本不一致、物種不符時提供警告，沒有填入虛構測試值。

## PowerShell 執行
從 `shelter_complete_ready` 根目錄：

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

另開一個終端機在根目錄：

```powershell
cd frontend
npm install
npm run dev
```

前端 http://127.0.0.1:8000；API http://127.0.0.1:8001/docs。

## 已驗證與限制
- 後端 Python 編譯通過。
- 使用示範 SQLite 中 80 隻在所動物執行 30 天預測成功；基準日 2026-10-22，模型涵蓋 47/80 隻，其他因超過 LightGBM 可預測天數等理由排除。
- 已產生每天食物、工時、Monte Carlo 上下界；已讀取 5 個離所原因的評估指標。
- 測試環境載入 pickle 時出現 scikit-learn 訓練版 1.9.1 與現有 1.8.0 不一致警告，正式部署請以原訓練環境對齊版本再驗證；此包未重新訓練。
- 未在本機執行完整前端 npm build / 瀏覽器視覺回歸，若部署後有 TS 問題請提供錯誤訊息。

## 本次補強：資源條件與長期資料
- 個體照護係數優先依物種、品種、年齡組及 `health_condition` 對照使用者提供的 CSV；找不到相同健康條件時退回該組 `unknown`，不擅自當成需特殊照護。這些值仍是 `HEURISTIC_NOT_MEASURED` 估計。
- `/api/stage2/evaluation` 會附上 `training_duration_diagnostics`，列出訓練在所天數 P50/P90/P95/P99 與第 30/60/90/120/150/180 天的 at-risk 筆數。這是資料涵蓋分析，不是長期分組校準誤差。
- 超過訓練天數 P95 的個體會發出資料稀疏警告。超過模型 `max_day=180` 的個體仍不可使用現有模型外推，會明確標示並從*可評估群體*排除；**沒有改訓練模型，也沒有完成「任意天數 Hazard」或「長期分組 Brier Score」**。要真正解決需重訓更長時域的模型、再做設限校正分組評估。
- 本差異包不變動其他頁面路由、不會讓選單只剩兩頁；只更動資源配置與模型評估頁及其必要的後端推論 API。
