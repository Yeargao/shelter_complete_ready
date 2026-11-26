const guidance:Record<string,string> = {
 disabled:'Gemini 目前停用。請管理者在後端設定 LLM_ENABLED=1，並重新啟動服務。',
 missing_key:'後端缺少 Gemini API 金鑰。請管理者用 Google AI Studio 免費層專案的金鑰設定 GEMINI_API_KEY。',
 data_not_approved:'後端尚未允許將資料交由 Gemini 處理。確認資料適用後，請管理者設定 LLM_DATA_APPROVED=1。',
 invalid_model:'模型設定無效。請管理者在 AI Studio 確認專案有可用免費額度，並更新後端 GEMINI_MODEL。',
 local_budget_disabled:'後端本地預算設為 0 或設定無效，尚未送出 Gemini 請求。請在 Render 設定 LLM_MAX_REQUESTS_PER_DAY、LLM_MAX_REQUESTS_PER_MINUTE、LLM_MAX_INPUT_TOKENS_PER_MINUTE 為符合 AI Studio 專案額度的正整數。',
 daily_budget:'系統本地每日預算已達上限，或已保留給聊天；本次尚未呼叫 Google，不代表 AI Studio 額度已滿。請核對 Render 的 LLM_MAX_REQUESTS_PER_DAY 與 LLM_CHAT_RESERVED_REQUESTS。',
 minute_budget:'系統本地每分鐘請求限制已滿（含失敗請求）；本次尚未呼叫 Google。請稍後重試。',
 token_budget:'系統本地估算的輸入 Token 預算不足，本次尚未呼叫 Google；請核對 Render 的 LLM_MAX_INPUT_TOKENS_PER_MINUTE 與 AI Studio。',
 rate_limited:'Google Gemini API 曾回傳 HTTP 429，目前正在限流冷卻。這不一定代表每日額度用完；請確認 Render 的金鑰屬於 AI Studio 正在查看的專案，並核對該模型的 RPM、TPM、RPD。',
 configuration_400:'Gemini 拒絕請求設定。請管理者檢查模型與後端設定。',
 configuration_401:'Gemini 驗證失敗。請管理者確認後端金鑰仍然有效。',
 configuration_403:'Gemini 專案權限不足。請管理者確認金鑰與模型存取權。',
 configuration_404:'專案無法使用目前模型。請管理者在 AI Studio 確認可用的免費模型。',
 network_error:'Gemini 連線逾時或異常。請稍後重試，若持續發生請管理者檢查後端連線。',
 upstream_error:'Gemini 服務暫時異常。請稍後重試。',
 invalid_response:'Gemini 回應格式異常。請稍後重試。',
 in_progress:'同一份摘要正在產生，稍後可重新查詢。',
};
export function aiGuidance(reason:string) {
 return guidance[reason]??'請稍後重試，若持續發生請管理者檢查 AI 使用量面板。';
}
