# TEST_RESULTS — 實際執行與限制

環境：Linux 隔離容器；Python 3.13；具備部分訓練／預測套件與全域 TypeScript，但缺少 `ortools` 和前端本機 `node_modules`。全部測試在原 ZIP 的「複製工作目錄」進行；修改回報的測試使用新建暫存 SQLite 複本。**沒有在使用者原始 SQLite 上執行資料重設。**

| 測試 | 結果 | 方法／範圍 |
|---|---|---|
| `NODE_PATH=$(npm root -g) node frontend/tests/test_local_minimal_update.cjs` | **通過** | 實際執行時間區間欄位演算法：2／3 同時段、連續 15 分鐘、同 lane 重用；TSX 語法與 UI 連線靜態檢查。**非瀏覽器視覺測試**。 |
| `NODE_PATH=$(npm root -g) node frontend/tests/test_v5_ui.cjs` | **通過** | 原有 6 項靜態回歸檢查。 |
| `NODE_PATH=$(npm root -g) node frontend/tests/test_v6_ui.cjs` | **通過** | 原有 12 項來源檢查。 |
| `NODE_PATH=$(npm root -g) node frontend/tests/test_v7_ui.cjs` | **通過** | 原有 12 項靜態／布局算式檢查。 |
| `NODE_PATH=$(npm root -g) node frontend/tests/test_v8_ui.cjs` | **通過** | 原有 TSX 解析、幾何、完成任務、三框、淡色背景檢查。 |
| `python -m unittest discover -s tests -p test_local_minimal_update.py -v` | **4 項通過** | SQLite 副本上原地更新一筆已完成備註兩次，筆數不增；拒絕修改醫療判定；重複刷新不新增傷病任務；LightGBM 5 類指標、CatBoost MAE、25 項校準載入。 |
| `python -m unittest discover -s tests -v` | **未全過** | 總計 `Ran 18 tests`，有 **2 個失敗子案例** 與 **1 個 setUpClass 錯誤**。其餘執行的測試為通過。 |
| 原基準執行 `test_missing_due_date.py` | **同樣失敗 2 個子案例** | 當疫苗缺少 due_date 時，現有實作得到 `is_new=1`，原測試期待 `0`。**已在未修改的基準檔重現，非本次引入**；因限制不允許順便修改疫苗規則，也未篡改測試期待。 |
| `test_schedule.SchedulingTests` | **無法執行** | 缺少 Google OR-Tools：`ModuleNotFoundError: No module named 'ortools'`；不能宣稱排程求解器驗證通過。 |
| `npm run build` | **無法完成** | 前端本機依賴未安裝；TS 回報缺少 React JSX types、vite、plugin-react 等模組。全域 TypeScript 的 TSX **語法** 解析有通過，但不等於完整型別檢查與 Vite 建置。 |
| 真實瀏覽器表單定位、浮層不遮擋、刷新後畫面、員工／管理者雙視角 E2E | **未執行** | 缺少本機前端依賴及瀏覽器測試環境；須在使用者既有環境確認。 |
| Read-only injury audit script | **可執行** | 在基準 SQLite 以唯讀連線得到歷史多版本候選列表；不更新或刪除資料。 |

## 警示

- `sklearn` 載入歷史模型時出現 1.9.1 → 1.8.0 版本警告；模型權重及環境依賴沒有因此被修改。
- SQLite 缺少獨立傷病事件 ID，歷史候選**不能安全自動刪除**；見 `CHANGES.md`。
- 既有 `task_overrides` 以 `(animal_id,label)` 聚合回報；同動物同名而實屬不同事件的完整獨立報告，不在本次無 schema 遷移的處理範圍內。
- 以上狀態為已執行結果，不將靜態斷言寫成瀏覽器端到端測試。

## 本機完成驗收建議

在具備原有套件的 Windows 專案根目錄：

```powershell
cd .\frontend
npm run build
node .\tests\test_local_minimal_update.cjs
node .\tests\test_v5_ui.cjs
node .\tests\test_v6_ui.cjs
node .\tests\test_v7_ui.cjs
node .\tests\test_v8_ui.cjs
cd ..
.\backend\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

請由實際員工帳號、管理者帳號測試：完成回報前後、重新整理、編輯備註、短任務與併欄、管理者備註同步、今日任務池黑字、模型評估指標載入及原派工限制。成功登入需要沿用既有專案設定。
