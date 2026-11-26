# Shelter AI V3

管理者可查看即時資源和班表、預覽七天派工並確認寫入。照護人員可查看個人今日與本週任務，透過任務 ID 回報結果、醫療日期與照片。兩種角色皆可使用右下角的收容所助理。

## Windows PowerShell 啟動

從專案根目錄開啟後端。工作資料庫不存在時，FastAPI 會以 SQLite 備份 API 複製展示資料。

```powershell
Set-Location C:\Users\LF24\Desktop\shelter_professor_v2
if (-not (Test-Path .\backend\.venv\Scripts\python.exe)) {
    python -m venv .\backend\.venv
}
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:SHELTER_DB_PATH = Join-Path $env:LOCALAPPDATA 'ShelterV3\shelter.sqlite3'
$env:SHELTER_UPLOAD_DIR = Join-Path $env:LOCALAPPDATA 'ShelterV3\uploads'
$env:SHELTER_MODEL_MODE = 'demo'
$env:LLM_ENABLED = '0'
.\backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8001
```

開啟第二個 PowerShell 視窗啟動前端。

```powershell
Set-Location C:\Users\LF24\Desktop\shelter_professor_v2\frontend
npm.cmd ci
npm.cmd run dev
```

瀏覽 `http://127.0.0.1:8000`。展示帳號管理者為 `01`，照護人員為 `02` 至 `06`。FastAPI 文件位於 `http://127.0.0.1:8001/docs`。使用既有營運資料時，先備份資料庫和照片，並以 `SHELTER_DB_PATH` 指向要保留的工作資料庫。

若已在 `backend` 目錄，使用 `.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001`。遇到 `cannot import name 'genai' from 'google'`，先用同一個虛擬環境的 Python 安裝該環境的 requirements。若直接執行 `uvicorn` 出現 `Fatal error in launcher`，改由專案虛擬環境執行 `python.exe -m uvicorn`。

## Gemini 免費層

在 Google AI Studio 選擇尚未啟用計費的 Free Tier 專案，使用該專案的 API key。預設為 `gemini-3.5-flash-lite`，允許明確指定 `gemini-2.5-flash-lite`。官方定價頁列出兩者的免費文字層，模型能否使用及實際限制依個別專案顯示為準。金鑰和所有 `LLM_*` 設定都放在 FastAPI 執行環境。 [Google Gemini 定價](https://ai.google.dev/gemini-api/docs/pricing) · [Google AI Studio Rate Limits](https://aistudio.google.com/rate-limit) · [Google API 限制說明](https://ai.google.dev/gemini-api/docs/rate-limits)

| 變數 | 設定 |
| --- | --- |
| `GEMINI_API_KEY`、`GEMINI_MODEL` | 伺服器端金鑰及專案有免費額度的模型 |
| `LLM_ENABLED`、`LLM_DATA_APPROVED` | 兩者設為 `1` 才允許外部呼叫。資料限展示或經允許交由 Gemini 處理的資料 |
| `LLM_MAX_REQUESTS_PER_MINUTE`、`LLM_MAX_REQUESTS_PER_DAY`、`LLM_MAX_INPUT_TOKENS_PER_MINUTE` | 依 AI Studio 設定本地上限。預設 `0` 以停用外部呼叫 |
| `LLM_MAX_OUTPUT_TOKENS` | 單次輸出上限，預設 512 |
| `LLM_CHAT_RESERVED_REQUESTS` | 聊天專用的本地每日請求數，預設 0 |
| `LLM_CACHE_TTL_SECONDS` | 照護摘要有效秒數，預設 86400 |

照護摘要與聊天共用官方 `google-genai` Python SDK。用量在送出請求前以 SQLite 寫入交易保留。RPM 與 TPM 採滾動 60 秒，RPD 依美國太平洋時間。輸入 Token 先用 UTF-8 位元組保守估算，收到 Gemini 回報的 prompt token 才更新。失敗也計入本地請求數。每次使用者操作最多一個外部請求，429 遵守 Retry-After，其他短暫或設定錯誤有冷卻與本地降級。 [Google Gen AI SDK 文件](https://googleapis.github.io/python-genai/)

照護工作台每次載入排程都可顯示規則式提示。開啟任務詳細資料時才查 SQLite AI 快取；同一動物、任務內容與有效資料版本可跨員工及時段共用。沒有快取時僅高優先級與緊急待辦嘗試 Gemini。多個同鍵請求僅一個取得生成租約，其餘先取得規則結果。醫療與回報更新以 SHA-256 資料版本產生新快取鍵。AI 用量位在管理總覽底部，顯示本地紀錄與預算。

### 本機啟用 Gemini

1. 到 Google AI Studio 的 API Keys 頁面，建立或選擇 Free Tier 專案的金鑰。前往 Rate Limits 頁，在同一個專案查看可用模型及 RPM、RPD、輸入 TPM。 [建立 API 金鑰](https://aistudio.google.com/api-keys) · [查看 Rate Limits](https://aistudio.google.com/rate-limit)
2. 在執行 FastAPI 的 PowerShell 視窗按 **Ctrl+C** 停止服務。保留原先的 `SHELTER_DB_PATH` 和 `SHELTER_UPLOAD_DIR` 以繼續使用既有資料。
3. 在同一個視窗執行下列指令。金鑰輸入時會隱藏。模型請填該專案可用且後端支援的 `gemini-3.5-flash-lite` 或 `gemini-2.5-flash-lite`。只在使用展示資料或已獲授權時設定 `LLM_DATA_APPROVED=1`。

```powershell
$shelterGeminiSecret = Read-Host 'Gemini API Key' -AsSecureString
$env:GEMINI_API_KEY = [pscredential]::new('gemini', $shelterGeminiSecret).GetNetworkCredential().Password
$env:GEMINI_MODEL = Read-Host 'AI Studio 可用的 Flash-Lite 模型 ID'
$env:LLM_MAX_REQUESTS_PER_MINUTE = Read-Host '專案 RPM 的本地上限'
$env:LLM_MAX_REQUESTS_PER_DAY = Read-Host '專案 RPD 的本地上限'
$env:LLM_MAX_INPUT_TOKENS_PER_MINUTE = Read-Host '專案輸入 TPM 的本地上限'
$env:LLM_MAX_OUTPUT_TOKENS = '512'
$env:LLM_CHAT_RESERVED_REQUESTS = '0'
$env:LLM_DATA_APPROVED = '1'
$env:LLM_ENABLED = '1'
Set-Location C:\Users\LF24\Desktop\shelter_professor_v2
.\backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8001
```

4. 用管理者登入並展開「AI 使用量」。先確認預算大於 0。使用展示動物名稱問收容所助理「這隻動物最近的健康狀況？」以驗證一筆 Gemini 查詢。成功時會看到「Gemini AI」來源與新增的 Gemini 請求。班表、容量和一般例行任務優先使用資料庫或規則式答案。

線上版則在 **FastAPI 後端主機**的 Environment 設定這些變數。依本專案 Vercel 的預設轉送設定，該後端位於 Render。若正式版另設 `VITE_API_URL`，以該值所指服務為準。儲存變數後重新啟動或部署最新後端。如果已更新前端，但員工按下收回仍收到「此操作僅管理者可執行」，請確認正在服務前端的是含有 `POST /api/schedule/tasks/{task_id}/withdraw-report` 且允許本人回報操作的最新後端。可從該後端的 `/docs` 核對端點。

| 畫面或錯誤 | 處理方式 |
| --- | --- |
| 已停用或未設定金鑰 | 確認變數設在目前對外提供 FastAPI 的程序或服務，啟用後重啟 |
| 本地預算為 0 | 在 AI Studio 查同一個專案的額度，填入正整數本地上限 |
| 401、403、404 | 檢查金鑰效力、專案權限，以及模型 ID 是否在該專案可用 |
| 429 或冷卻中 | 等待限流冷卻，並到 AI Studio 檢查用量。每日預算以美國太平洋時間午夜重設 |
| 規則式摘要 | 開啟高優先級或緊急待辦的照護重點才可能新生成摘要。用展示動物的健康概況問題也可驗證 Gemini |

## 日曆及動態重排

1. 開啟 **資源配置**，選日期以查看從當天開始的連續七天。日檢視以員工分欄，週檢視以日期分欄，可切換員工及橫向捲動。
2. 點選 **七天最佳化派工**。同一個 CP-SAT 模型以 15 分鐘時間格及每日工時求解。先最大化派入的任務時數，再依緊急性、優先級與期限排程，接著縮小最高與最低日工時的差距，最後減少異動。清單沿用健康行政核對的任務類型，另可查看由健康事件或回報衍生的待指派任務。
3. 檢查每項原位置、新位置及調整原因，再確認套用。工時、出勤、技能、休息與重疊採硬性限制。期限以逾期目標處理；允許補排單次任務。每日照護只能排在指定日，疫苗及驅蟲採原有醫療週期。
4. 可拖放至日曆，或點選任務填入員工、日期、時間與鎖定狀態。後端寫入前重新驗證。預覽可能得到 `FEASIBLE`，或因固定衝突／逾時無法提供可套用方案。
   每天 11:30–13:30 為固定休息時間，日曆會標記，所有新指派與最佳化都避開該時段。今天及未來原本排在午休且尚未開始的任務會移回待指派池。每日班表還可以設定額外休息時間。
5. 班表、工時、入離所、健康狀態與緊急事件會標示待更新。再次預覽再套用。預覽後若資料已變，API 回傳 409。歷史週只供查閱；逾期照護保留並在逾期清單中可見。

## 收容所助理

從右下角開啟，選用常見問題或輸入動物名稱、動物 ID、員工姓名或任務 ID。管理者可查收容數、空位、工時、急件、未指派原因和請假影響。照護人員可查個人班表、下一項、待辦及有任務關聯的動物健康與醫療紀錄。可在查詢一隻動物後接問「牠有驅蟲嗎？」。

一般問題使用本地意圖辨識、Asia/Taipei 日期解析與受控的唯讀查詢工具，直接查詢 SQLite；較難辨識的問題才在 Gemini 已啟用且資料已核准時，使用原生 Function Calling 選擇 `query_shelter` 的結構化參數。Few-shot 提示提供常見問法，模型只選擇允許的意圖、時段及排序，不產生 SQL、不自行指定 ID。動物、員工及任務在伺服器辨識並重新檢查權限。個體健康綜整仍可使用匿名資料排序。停用 AI 或額度不足時，已支援的本地查詢不受影響。

支援「今天誰最忙」「明天下午誰比較有空」「下週五有哪些工作」「上下午工作量平均嗎」「牠有打過預防針嗎」等問法。對話在前端保存最近十輪；後端將最近一次已查詢的意圖、日期、時段、員工、動物、任務與篩選條件，以登入工作階段簽署為不透明 context token。重新登入、登出或清除對話會結束該上下文；不接受跨帳號或自行偽造的指涉。日期範圍最多 31 天；不支援的日期或時段要求補充。上週／本週／下週未指定星期幾時維持既有七天滾動窗口，明確星期幾則依台灣日曆解析。時段剩餘工時是依已記錄班表、休息、工作和每日可用工時計算的上限，未定位的其他工時可能降低實際可用量。AI 解析只送出經本地已知名稱及 ID 遮蔽的問句，仍須遵守 LLM_DATA_APPROVED；請勿輸入個資。新回覆欄位 `intent`、`intent_source` 與 `query` 可用於除錯，原有 `answer`、`source`、`sources`、`context` 保持相容。

## API 與 SQLite 遷移

所有營運 API 使用登入取得的 Bearer token。

| 方法與路徑 | 行為 |
| --- | --- |
| POST `/api/chat` | 傳入 `question` 及選用的 `context`，回傳 `answer`、`source`、`sources`、`queried_at` 等 |
| GET `/api/llm/usage` | 管理者用量資料 |
| GET `/api/schedule/overview` | 管理者即時資源及派工狀態 |
| GET `/api/schedule/week?week=YYYY-MM-DD` | 日期、班表、任務、逾期及待更新狀態，依角色查詢 |
| POST `/api/schedule/preview?week=YYYY-MM-DD`、POST `/api/schedule/apply/{plan_id}` | 七天預覽、資料版本檢查及套用 |
| PUT `/api/schedule/shifts/{staff_id}/{day}` | 單日出勤、上下班、休息與可用工時 |
| POST `/api/schedule/tasks`、PATCH `/api/schedule/tasks/{task_id}/placement` | 新增、指派、鎖定、解鎖或移回任務池 |
| POST `/api/schedule/tasks/{task_id}/summary` | 規則或 AI 詳細摘要，限管理者與任務指派人 |
| POST `/api/schedule/tasks/{task_id}/report` | 照護者依 task ID 回報，支援醫療日期及照片 |
| POST `/api/schedule/tasks/{task_id}/event`、POST `/api/schedule/tasks/{task_id}/resolve` | 管理者記錄延遲、開始及處理異常 |
| GET `/api/schedule/tasks/{task_id}/photos/{photo_id}` | 管理者與上傳員工可讀取私有照片 |

啟動時以可重複執行的 `CREATE TABLE/INDEX/TRIGGER IF NOT EXISTS` 建立增量 schema。V3 加入 `llm_attempts`、`llm_events`、`llm_state`、`llm_summary_cache`、`llm_summary_leases`、`weekly_applied`。既有 `care_summary_cache` 保留供歷史相容，新快取使用資料版本鍵。舊動物、醫療及指派紀錄繼續保留。舊版單日與研究 API 保留供相容用途。營運日曆使用 `/api/schedule/*`。

## Vercel 與持久化

現有 Vercel 設定部署 Vite 靜態前端，`/api/*` 轉送到現有的外部 FastAPI 主機。正式建置時可將 `VITE_API_URL` 設為 HTTPS 的 FastAPI origin，並設定 `VITE_SHELTER_DEMO=false`。FastAPI 的 `SHELTER_CORS_ORIGINS` 填入前端 origin，並設定強密鑰 `SHELTER_AUTH_SECRET` 與獨立登入密碼 `SHELTER_AUTH_PASSWORDS`。前端使用 sessionStorage 儲存登入狀態，派工及照護由後端 SQLite 持久化。

FastAPI 主機須配置持久化磁碟，以 `SHELTER_DB_PATH` 及 `SHELTER_UPLOAD_DIR` 指向掛載目錄。可用既有 S3 相容私有 bucket 儲存照片，相關設定見 `.env.example`。SQLite 持久性取決於後端磁碟，Vercel 部署前端不會提供該磁碟。線上主機的版本、CORS 和重啟持久性尚未驗收。

## 驗證指令

從專案根目錄執行。測試會寫入獨立資料庫，Gemini HTTP 由 mock 替代。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:SHELTER_DB_PATH = Join-Path ([System.IO.Path]::GetTempPath()) ("shelter-test-{0}.sqlite3" -f [guid]::NewGuid())
$env:LLM_ENABLED = '0'
python -m unittest discover -s tests -v
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
Get-ChildItem frontend/tests/test_*.cjs | ForEach-Object { node $_.FullName }
```

測試結果與驗收範圍見 [CHANGES_V3.md](CHANGES_V3.md)。
