# V3 變更與驗收

| 範圍 | 新增或修改 |
| --- | --- |
| 後端 | 新增 `backend/llm_service.py`、`backend/shelter_chat.py`。更新 `backend/main.py`、`backend/care_summary.py`、`backend/weekly_schedule.py`、`backend/requirements.txt` |
| 前端 | 新增 `frontend/src/components/common/LlmUsage.tsx`、`ShelterChat.tsx`、`ShelterChat.css`。更新 `App.tsx`、`index.css`、`components/common/ResourceOverview.tsx`、`pages/Dashboard.tsx`、`pages/ResourcePage.tsx`、`pages/ResourceBoard.css`、`pages/StaffHome.tsx`、`services/api.ts` |
| 測試 | 更新 `tests/test_care_summary.py`、`tests/test_weekly_schedule.py`、`tests/test_local_minimal_update.py` |
| 設定與文件 | 更新 `.env.example`，新增 `README_V3.md`、`CHANGES_V3.md` |

## 執行結果

| 驗證 | 結果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 40 項通過 |
| `npm test` | Vitest 1 項通過 |
| 前端舊版回歸腳本 | 6 支通過 |
| `npm run build` | TypeScript 檢查與 Vite 正式建置通過 |
| Edge 1440px | 日期切換、七欄週曆、CP-SAT 預覽與套用、點擊移回任務池、拖放並回查 SQLite 時間、管理者聊天 |
| Edge 390px | 驗證無頁面水平溢出、點擊指派並回查時間、驅蟲快速回報、異常照片預覽與送出、全畫面聊天、來源、等待、失敗與清除 |

七天聯合案例將七筆每日照護分別排入週一至週日。獨立案例覆蓋每日和每週工時、休息、技能、衝突、跨日、一次性醫療、請假、緊急優先、已完成和已執行中保留、過期預覽與異常照片權限。瀏覽器的獨立展示案例回傳 `CP-SAT OPTIMAL`。

原展示 SQLite 的獨立副本也完成了 2026-11-30 至 2026-12-06 排程。求解約 21.5 秒，狀態為 `FEASIBLE`。共 745 項有效待辦，週一至週日分別指派 28、10、30、50、50、56、48 項，合計 272 項，另 473 項保留在任務池。本次可行方案未證明最佳。

模擬 Gemini 覆蓋跨連線快取與用量讀回、重新指派共用快取、健康狀態變更與 TTL、並行同鍵、RPM／TPM／RPD、聊天保留、429 共用冷卻、無效 JSON、逾時、403、503 和缺少金鑰。聊天測試覆蓋角色、即時數值、動物指涉、同帳號不同工作階段隔離、資料權限、輸入形狀驗證、去識別化和 Gemini 失敗降級。

## 驗收界線

環境未提供 Gemini API key，外部 Gemini 實際連線、專案免費層額度和模型可用性待驗證。既有外部 FastAPI 主機的公開健康檢查逾時。Vercel 與生產服務未進行部署與上線驗收，持久化磁碟與物件儲存重啟行為需由實際主機驗證。
