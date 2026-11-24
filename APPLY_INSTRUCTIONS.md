# APPLY_INSTRUCTIONS — Windows PowerShell 覆蓋與啟動

## 事前檢查（很重要）

1. 必須使用這次差異包所對應的基準：本對話先前產出的 `shelter_complete_updated_full.zip` → `shelter_complete_ready`。若你手上有**更晚**的 ZIP，請先比對版本，避免直接覆蓋較新的改動。
2. **停止前後端服務**後才覆蓋程式，保留你的 `backend/showcase.sqlite3`、模型權重、原 `node_modules` 和 `.venv` 原樣。差異包不包含以上任何檔案。
3. 建議先自行備份現有整個專案，尤其 SQLite。**不需要 migration，不需要重設 SQLite，也不需要重新訓練模型。**

## 1. 將檔案覆蓋到既有原路徑

請在 ZIP 所在目錄開 PowerShell，將 `$project` 改成你電腦上的現有專案根目錄（裡面應有 `backend`、`frontend`、`tests`）。此指令僅複製差異包內的程式／測試檔案，**不覆蓋原 SQLite**：

```powershell
$project = 'C:\Projects\shelter_complete_ready'  # 修改成你的專案實際路徑
$extract = Join-Path $env:TEMP 'shelter_minimal_diff_extract'
Expand-Archive -LiteralPath '.\shelter_update_diff.zip' -DestinationPath $extract -Force
$patch = Join-Path $extract 'shelter_update_diff'
foreach ($folder in @('backend','frontend','tests')) {
    Get-ChildItem -Path (Join-Path $patch $folder) -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
        $relative = $_.FullName.Substring($patch.Length).TrimStart('\')
        $destination = Join-Path $project $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
        Write-Host "Updated $relative"
    }
}
```

此腳本只會複製 `backend/`、`frontend/`、`tests/` 的新增／修改檔案，不會複製 `CHANGES.md` 等說明檔。若要在本機保留說明文件，可手動複製 ZIP 根目錄三份 Markdown。

## 2. 套件與建置

本次未增加依賴，因此**原來的** `.venv`、`node_modules` 可以繼續使用。若原依賴齊全，直接建置：

```powershell
Set-Location (Join-Path $project 'frontend')
npm run build
```

只有在你的原套件缺失時，才依原有鎖檔／requirements 安裝（不是本次差異包要求）：

```powershell
Set-Location (Join-Path $project 'frontend')
npm ci
Set-Location (Join-Path $project 'backend')
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果你的虛擬環境在**專案根目錄**而非 `backend/.venv`，請將上述與下述 `.\.venv\Scripts\python.exe` 改成 `..\.venv\Scripts\python.exe`。

## 3. 測試

```powershell
Set-Location $project
node .\frontend\tests\test_local_minimal_update.cjs
node .\frontend\tests\test_v5_ui.cjs
node .\frontend\tests\test_v6_ui.cjs
node .\frontend\tests\test_v7_ui.cjs
node .\frontend\tests\test_v8_ui.cjs
.\backend\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

原有 `test_missing_due_date.py` 的 2 個疫苗缺失日期子案例在基準亦失敗；已列在 `TEST_RESULTS.md`。請勿改測試期待值以掩蓋問題。

## 4. 啟動

**後端 PowerShell 視窗：**

```powershell
Set-Location (Join-Path $project 'backend')
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001
```

**前端另開 PowerShell 視窗：**

```powershell
Set-Location (Join-Path $project 'frontend')
npm run dev
```

前端遵循原來 `frontend/package.json` 設定的 port 8000；FastAPI 在 port 8001。請勿自行改動既有 API 代理／環境設定。

## 5. 唯讀調查既有傷病歷史多版本任務（可選）

```powershell
Set-Location $project
.\backend\.venv\Scripts\python.exe .\backend\tools\audit_injury_task_duplicates.py --db .\backend\showcase.sqlite3 | Out-File -FilePath .\injury_task_audit.json -Encoding utf8
```

這份 JSON **只是候選清單**，不是安全刪除建議。工具用 `mode=ro` 開 SQLite，不會自動清除或變更歷史資料；沒有 migration。

## 6. 為何此次不附完整系統？

依需求，只交付 `shelter_update_diff/`，內含本次修改的完整原檔、必要新檔及三份說明。不包含原模型、資料集、SQLite、node_modules、.venv、編譯產物，也沒有對原專案做無關刪除。
