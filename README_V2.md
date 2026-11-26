# 收容所管理 V2

管理者在資源配置頁查閱即時資源、編輯每日班表與員工資格，在七天內預覽排程並確認寫入。照護人員在個人工作台查看當日與七天任務，按任務類型回報，並可附多張照片。健康評估、送養及研究資料沿用既有資料與模型。

## 系統架構

- React、TypeScript、Vite 與 React Query 提供管理者及照護人員操作。跨帳號畫面每 15 秒更新。
- FastAPI 驗證角色與任務歸屬。SQLite 儲存照護業務資料，使用臺灣時間、週一至週日與 15 分鐘格。
- OR-Tools CP-SAT 以緊急、高優先、未指派與逾期、保留原位置、相對工作量依序求解。每層預設 6 秒，可用 `SHELTER_SOLVER_PHASE_SECONDS` 調整。剩餘工時為班表、休息、外部占用、已排工時與週上限共同約束的可派容量。
- 即時飼料和照護需求以資料庫個體估算加總。個體缺值時使用收容所設定的每隻平均值。完工與異常解決是獨立狀態。
- 既有研究 API 與評估頁仍可供研究用途。收容量權重在研究端點收到請求時才載入。營運頁無相關預測請求。

## 資料庫變更

首次啟動建立 V2 資料表與觸發器，首次排程讀取匯入可辨識的舊指派。重複遷移保留既有資料。日班表的缺省值繼承員工預設班表。原動物、醫療、舊任務及歷史表繼續保留。

| 資料表 | 用途 |
| --- | --- |
| `staff_daily_shifts` | 員工／日期出勤、上下班、休息、已占用及每日可用工時 |
| `weekly_tasks` | 獨立任務 ID、任務類型、資格、優先級、工時、日期、指派、狀態、鎖定與未指派原因 |
| `weekly_reports`、`weekly_issues` | 按任務 ID 防止重送，獨立追蹤異常是否已解決 |
| `weekly_plans`、`weekly_events` | 方案差異、確認版本與重排事件 |
| `weekly_staff_accounts`、`weekly_schedule_migrations` | 持久化展示帳號與員工關聯、記錄舊派工匯入 |
| `task_photos`、`care_summary_cache` | 照片歸屬、儲存位置與依資料指紋更新的快取 |

每日照護以動物與日期辨識。單次任務沿用規則產生的識別碼與醫療週期，重試與手動新增保留各自識別碼。週期照護的允許日為當日。單次任務的最早日是硬性限制，完成期限是逾期目標，保留逾期工作可補排的能力。

## API

所有下列路徑使用既有 Bearer token。班表、指派、預覽、套用與問題解決限管理者；照護工作台回報限該任務指派帳號。管理者與照片上傳員工可讀取私有照片。

| 方法與路徑 | 行為 |
| --- | --- |
| GET `/api/schedule/overview` | 即時資源概況 |
| GET `/api/schedule/week?week=YYYY-MM-DD` | 將所選日期轉為當週，依角色回傳任務 |
| PUT `/api/schedule/shifts/{staff_id}/{day}` | 編輯單日班表或登記請假 |
| POST `/api/schedule/preview?week=YYYY-MM-DD` | 回傳 CP-SAT 狀態、方案 ID、前後位置及原因 |
| POST `/api/schedule/apply/{plan_id}` | 比對資料版本後儲存；已變更回傳 HTTP 409 |
| POST `/api/schedule/tasks` | 新增任務或提高既有待辦優先級 |
| PATCH `/api/schedule/tasks/{task_id}/placement` | 驗證並儲存手動指派；員工為 null 時移回任務池 |
| POST `/api/schedule/tasks/{task_id}/event` | 標記執行中或延遲，保留重排前位置 |
| POST `/api/schedule/tasks/{task_id}/report` | 任務專用回報、選填醫療日期和照片 |
| GET `/api/schedule/tasks/{task_id}/photos/{photo_id}` | 讀取私有照片 |
| POST `/api/schedule/tasks/{task_id}/resolve` | 管理者確認問題已解決 |

舊 `POST /api/resources/optimize` 轉送至七天預覽。既有健康、認養、動物、醫療紀錄和研究 API 保留。

## Windows PowerShell 啟動

在專案根目錄開啟後端視窗。以下資料庫路徑不存在時，啟動會以 SQLite backup API 從展示資料建立工作副本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:SHELTER_DB_PATH = Join-Path $env:LOCALAPPDATA 'ShelterV2\showcase.sqlite3'
$env:SHELTER_UPLOAD_DIR = Join-Path $env:LOCALAPPDATA 'ShelterV2\uploads'
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8001
```

在另一個 PowerShell 視窗執行前端。

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

開啟 `http://127.0.0.1:8000`。展示管理者使用 `01`，照護人員使用 `02` 至 `06`。使用既有營運資料時，先備份並以 `SHELTER_DB_PATH` 指向持久化的資料庫。

## Gemini 照護摘要

在 [Google AI Studio 專案頁](https://aistudio.google.com/projects) 選擇 Free Tier 專案，維持未啟用帳單的狀態，並使用該專案的 API Key。Gemini 的計費層級依金鑰所屬專案決定。預設模型 `gemini-3.5-flash-lite` 支援免費文字輸入及輸出。若要指定其他模型，請選擇支援免費層及結構化 JSON 輸出的模型。[Google 定價](https://ai.google.dev/gemini-api/docs/pricing) · [Google 計費說明](https://ai.google.dev/gemini-api/docs/billing)

在 FastAPI 的執行環境設定 `GEMINI_API_KEY`。可用 `GEMINI_MODEL` 覆寫預設模型。`.env.example` 僅列出設定範例，FastAPI 讀取程序環境變數。金鑰應存入後端環境或部署平台的秘密設定，勿加入 Vite 變數、前端程式碼或 Git。

後端使用 Gemini Developer API 的結構化 JSON 輸出，驗證模型回傳的索引後，從既有資料挑選及排序摘要。任務卡仍顯示照護條目，API 仍回傳來源 ID、更新時間和摘要類型。人工自由文字與員工資料留在後端。SQLite 會依個體資料、任務指派、來源記錄與模型快取摘要。

缺少金鑰、HTTP 429、連線或 API 失敗，以及無效的模型回應，都會顯示規則式摘要與原因。API 失敗的規則式摘要快取五分鐘，期滿後由下一次讀取重新嘗試。備援只使用本機規則。

## 照片

本機預設儲存在 `backend/uploads/`，可用 `SHELTER_UPLOAD_DIR` 指定其他持久化目錄。支援 JPEG、PNG、WebP，每次最多四張、原始每張 5 MB、800 萬像素。服務驗證解碼後轉存 JPEG 並移除 EXIF。照片透過任務權限授權讀取。

正式環境設定私有 S3 相容 bucket `SHELTER_PHOTO_BUCKET`、可選的 `SHELTER_PHOTO_ENDPOINT`，以及 AWS SDK 所需的區域和憑證。建議在正式後端設定 `SHELTER_REQUIRE_OBJECT_STORAGE=1`。在 Vercel 執行時會要求物件儲存。金鑰放服務端環境變數，並確認反向代理請求大小可容納原始影像的 Base64 傳輸。

## Vercel 與持久化服務

- 在 Vercel 以儲存庫根目錄為 Root Directory，交由 `vercel.json` 建置 `frontend/dist` 並處理 SPA 路由。
- FastAPI 另行部署至具有持久磁碟的 Python 服務，設定 `SHELTER_DB_PATH`、照片儲存和帳號環境變數。更新 `vercel.json` 的既有 API 與 healthz 轉送目標，或在建置端使用 `VITE_API_URL` 並於後端加入對應的 `SHELTER_CORS_ORIGINS`。
- 展示模式同樣透過真實 FastAPI 與 CP-SAT。以正式登入時，設定至少 32 字元的 `SHELTER_AUTH_SECRET`、`SHELTER_AUTH_PASSWORDS` 的帳號 ID 到強密碼 JSON 對照，以及前端 `VITE_SHELTER_DEMO=false`。管理者帳號 ID 是 1。

## 測試

```powershell
python -B -m unittest discover -s tests -v
Set-Location frontend
npm.cmd test
Get-ChildItem tests/*.cjs | ForEach-Object {
  node $_.FullName
  if ($LASTEXITCODE -ne 0) { throw $_.Name }
}
npm.cmd run build
```

## 使用範圍及驗收限制

- 本版週排程對應現有展示收容所設定（profile 1）及既有六個帳號。沒有多收容所帳號管理介面。
- 動態事件在管理者資源頁輪詢偵測，或由管理者手動進入所選週並要求預覽。沒有背景佇列跨週自動建立方案。已開始、完成與鎖定的工作保留；鎖定工作不可行時，管理者需手動選擇新位置或解鎖。
- 求解在時限內可能只取得可行方案。資料量較大時建議以實際名單和主機實測延遲。
- 本機照片權限及 Gemini 摘要已透過自動測試驗證，Gemini HTTP 回應使用模擬。實際 Gemini、S3、Vercel 部署及手機相機尚未連線驗收。Chrome 已驗證跨日拖曳及 390 px 視窗的點擊指派。實機相機操作仍需人工驗收。
