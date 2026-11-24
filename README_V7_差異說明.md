# V7 工作池文字與員工時間表小修正

適用於已套用 V6 差異包的 `shelter_complete_ready`。

## 變更檔案
- `frontend/src/pages/ResourcePage.tsx`：今日任務池將任務名稱與動物名稱/編號拆開套色；員工負載按工作數量而非工時顯示完成數與藍橘比例，0/1 時全橘。
- `frontend/src/pages/ResourceBoard.css`：只為任務名稱套紅黃綠，動物名稱與編號維持黑色；0/1 時橘色進度條填滿。
- `frontend/src/pages/StaffHome.tsx`：個人時間表展開回報時採單列操作按鈕，含已完成工作的取消完成操作；其餘介面不動。
- `frontend/src/pages/StaffHome.css`：新增只作用於個人回報按鈕列的 nowrap CSS；欄寬不足時該列可橫向滾動，不會折成兩排。
- `frontend/tests/test_v7_ui.cjs`：TSX 語法與版面回歸靜態檢查。

## PowerShell
先關閉前端再解壓到既有專案根目錄：

```powershell
$root = 'C:\Users\LF24\Desktop\shelter_complete_ready'
Expand-Archive "$env:USERPROFILE\Downloads\shelter_ui_v7_diff.zip" -DestinationPath $root -Force
cd "$root\frontend"
node tests\test_v7_ui.cjs
npm run build
npm run dev
```

## 驗證與限制
- TSX 語法解析與 12 項版面/算術靜態測試通過。
- 0/1 轉換結果為完成 0%、未完成 100%，前端進度條顏色為全橘。
- 未在實際瀏覽器或使用者的 SQLite 資料庫執行 E2E 測試；王助理的真實 0/1 須以後端回傳紀錄為準，未硬編碼個別員工。
- 只修改前端，不更動資料庫、後端與最佳化派工；不更改管理者三欄比例或時間表字體排版。
