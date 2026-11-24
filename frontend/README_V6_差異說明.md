# V6 差異資源包 — 僅套用在已完成 V5 的專案

本包**不包含 SQLite、模型、後端或完整前端**。解壓在 `shelter_complete_ready` 根目錄，保留相對路徑。建議先備份原始程式，停止正在執行的前端後再套用。

## 修改清單

| 檔案 | 變更 |
| --- | --- |
| `frontend/src/pages/ResourcePage.tsx` | 員工完成數 / 總工作數；藍色已完成、橘色未完成比例依工作**筆數**計算；與工作池任務名稱緊急程度色彩同步。**保留原三欄布局**。 |
| `frontend/src/pages/ResourceBoard.css` | 右下角 `工作完成 ?/?`、任務名稱優先程度文字色、進度條；**未改布局 grid**。 |
| `frontend/src/pages/HealthPage.tsx` | 外層「依待辦事項整理動物」取消收合；內層保留可收合任務種類，健康問題追蹤直接在傷病治療下並顯示黃色字，僅基礎驅蟲和疫苗施打群組改名稱。 |
| `frontend/src/pages/HealthPage.css` | 外層列表限定 72vh/650px 高度並在**內部**捲動，避免大量動物把頁面撐長。 |
| `frontend/src/components/common/taskPresentation.ts` | 新增健康行政群組專用標題函式；**不變更真正 task label**。 |
| `frontend/src/components/common/DailyTimeline.tsx` | 紅：傷病治療；黃：健康問題追蹤；綠：基礎驅蟲、疫苗與一般健康核對；員工視角回報控制出現在工作卡右側，未點擊先呈淡灰唯讀。管理者時間表不套用回報版面。 |
| `frontend/src/components/common/DailyTimeline.css` | 員工工作卡 30% 說明、10% 按鈕、60% 回報欄；長時段卡片增大字與輸入元件；不修改時間軸列高與管理者三欄大小。 |
| `frontend/tests/test_v6_ui.cjs` | 12 項原始碼層級回歸斷言。 |

## 安裝及測試（Windows PowerShell）

```powershell
$root = 'C:\Users\LF24\Desktop\shelter_complete_ready'
# 先保存目前前端檔案（備份整個 src）
Copy-Item "$root\frontend\src" "$root\frontend\src.before_v6" -Recurse -Force
Expand-Archive "$env:USERPROFILE\Downloads\shelter_ui_v6_diff.zip" -DestinationPath $root -Force
cd "$root\frontend"
node tests\test_v6_ui.cjs
npm run build
npm run dev
```

`Copy-Item` 建立的備份位於 `frontend/src.before_v6`，不要把備份移進 `frontend/src` 以免被編譯器包含。

## 驗證範圍

- 本環境：已通過 4 個修改的 TSX/TS 語法解析及 12 項 Node 靜態回歸斷言。
- 尚未在你的正式資料及瀏覽器操作下測試；未完成完整 Vite/TypeScript 專案建置。
- 因為目前手邊沒有正式 SQLite，仍需在頁面驗證王助理是否有「今天的」已指派工作；若無則為灰色，不會任意將其他日期工作混入今日完成比例。
- 這次沒有修改任何資料庫或後端排程邏輯，既有答案與歷史紀錄不受影響。
