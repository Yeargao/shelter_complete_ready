import {useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {api} from '../../services/api';
import {ErrorView, Loading} from './States';
import {aiGuidance} from './aiStatus';

const statusLabels:Record<string,string> = {
 connected:'今日有成功請求', unverified:'尚未驗證', cooling_down:'冷卻中', disabled:'已停用',
 missing_key:'未設定金鑰', invalid_model:'模型未列入允許清單', rate_limited:'Gemini 限流',
 data_not_approved:'尚未允許傳送資料', local_budget_disabled:'本地預算停用',
 upstream_error:'Gemini 服務異常', network_error:'連線異常或逾時',
 invalid_response:'回應格式錯誤', configuration_400:'請求設定無效',
 configuration_401:'驗證失敗', configuration_403:'權限不足', configuration_404:'模型不可用',
};

export default function LlmUsage() {
 const [open,setOpen]=useState(false);
 const usage=useQuery({queryKey:['llm-usage'],queryFn:api.llmUsage,enabled:open,refetchInterval:30000});
 const data=usage.data;
 return <details className="panel llm-usage space-y-3" onToggle={e=>setOpen(e.currentTarget.open)}>
  <summary>AI 使用量</summary>
  {usage.isLoading&&<Loading/>}
  {usage.error&&<ErrorView error={usage.error}/>}
  {data&&<>
   <p>{data.day}（美國太平洋時間）</p>
   <dl className="llm-usage-grid">
    <div><dt>今日計入／本地每日預算</dt><dd>{data.used} / {data.local_daily_budget}</dd></div>
    <div><dt>摘要快取命中率</dt><dd>{data.cache_hit_rate===null?'尚無紀錄':`${Math.round(data.cache_hit_rate*100)}%`}</dd></div>
    <div><dt>Chatbot Gemini 請求</dt><dd>{data.chat_requests}</dd></div>
    <div><dt>Chatbot 問答次數</dt><dd>{data.chat_interactions}</dd></div>
    <div><dt>照護摘要 Gemini 請求</dt><dd>{data.summary_requests}</dd></div>
    <div className="llm-status"><dt>Gemini 連線</dt><dd>{statusLabels[data.connection]??'尚未驗證'}</dd></div>
    <div className="llm-status"><dt>冷卻狀態</dt><dd>{data.cooling?'冷卻中':'未冷卻'}</dd></div>
    <div className="llm-status"><dt>最近一次錯誤</dt><dd>{data.last_error?statusLabels[data.last_error]??'外部 API 回應異常':'無紀錄'}</dd></div>
    <div><dt>成功／失敗／使用本地回答</dt><dd>{data.successes} / {data.failures} / {data.rule_answers}</dd></div>
   </dl>
   {data.local_daily_budget===0&&<p>本地每日預算為 0。請在後端依 AI Studio 免費層額度設定 LLM_MAX_REQUESTS_PER_DAY、LLM_MAX_REQUESTS_PER_MINUTE 和 LLM_MAX_INPUT_TOKENS_PER_MINUTE。</p>}
   {(data.cooling||['disabled','missing_key','data_not_approved','invalid_model','local_budget_disabled'].includes(data.connection))&&
    <p>{aiGuidance(data.cooling&&data.last_error?data.last_error:data.connection)}</p>}
  </>}
  <p>以上為本地預算及紀錄，失敗請求不等於 Google 成功用量；設定遭拒的請求不計入本地每日預算。Google 官方額度請查看 <a href="https://aistudio.google.com/rate-limit" target="_blank" rel="noreferrer">Google AI Studio Rate Limits</a>。</p>
 </details>;
}
