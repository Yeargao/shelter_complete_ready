const guidance:Record<string,string> = {
 disabled:'Gemini 目前停用。請管理者在後端設定 LLM_ENABLED=1，並重新啟動服務。',
 missing_key:'後端缺少 Gemini API 金鑰。請管理者用 Google AI Studio 免費層專案的金鑰設定 GEMINI_API_KEY。',
 data_not_approved:'後端尚未允許將資料交由 Gemini 處理。確認資料適用後，請管理者設定 LLM_DATA_APPROVED=1。',
 invalid_model:'模型設定無效。請管理者在 AI Studio 確認專案有可用免費額度，並更新後端 GEMINI_MODEL。',
 daily_budget:'本地每日額度已達上限，或剩餘請求已保留給聊天。請等太平洋時間午夜重設，或由管理者核對本地預算。',
 minute_budget:'本地每分鐘請求額度已滿。請稍後重試，或由管理者核對 AI Studio 的限制設定。',
 token_budget:'本地每分鐘輸入 Token 額度不足。請稍後重試，或由管理者核對 AI Studio 的限制設定。',
 rate_limited:'Gemini 正在限流冷卻。請稍後重試，管理者可到 AI Studio 查看專案額度。',
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
