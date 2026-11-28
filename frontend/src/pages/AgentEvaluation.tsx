import {useRef,useState} from 'react';
import {useStored} from '../components/common/smartState';
type Metric={name:string;value:number|null;unit:string;n:number;detail:string};
type Evaluation={at:string;metrics:Metric[];cases:{name:string;passed:boolean;detail:string}[]};
export default function AgentEvaluation(){
 const [result,setResult]=useStored<Evaluation|null>('agent-evaluation',null);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const lock=useRef(false);
 async function run(){
  if(lock.current)return;lock.current=true;setBusy(true);setError('');
  try{
   const res=await fetch((import.meta.env.VITE_API_URL||'').replace(/\/+$/,'')+'/api/agent/evaluate',{method:'POST',headers:{Authorization:'Bearer '+sessionStorage.getItem('shelter_token')}});
   const body=await res.json();if(!res.ok)throw Error(body.detail??'測試失敗');setResult(body);
  }catch(e){setError(e instanceof Error?e.message:String(e))}finally{lock.current=false;setBusy(false)}
 }
 return <section className="space-y-4"><h1>AI 評估</h1><details className="panel space-y-3"><summary className="cursor-pointer font-semibold text-lg">收容所助理｜功能與權限</summary><div className="space-y-2"><p>本機規則優先辨識照護結果、查詢資料與建立確認草案；查詢可視設定使用 Gemini。未確認的草案不寫入資料庫。</p><p>管理者：查看全所健康行政、待指派照護任務與動物紀錄；指派及排程須至資源配置核對。照護人員：只可回報本人任務，並可在聊天中選擇結果、補充備註與疫苗日期。</p><p>資料來源：動物登錄、每週任務、醫療紀錄及規則表。助理不代替獸醫診斷、醫療處置或員工實際執行。</p></div></details><details className="panel space-y-3"><summary className="cursor-pointer font-semibold text-lg">四大照護流程與常用問句</summary><div className="space-y-3"><p><strong>健康照護：</strong>健康狀態待確認 → 傷病治療 → 健康問題追蹤；康復結束，未改善返回傷病治療。</p><p><strong>疫苗：</strong>確認疫苗紀錄 → 疫苗施打或更新疫苗紀錄；施打失敗重試，更新後依實際日期安排下次施打。</p><p><strong>驅蟲：</strong>確認驅蟲紀錄 → 基礎驅蟲或更新驅蟲狀態；成功後更新驅蟲紀錄，重新入所新增基礎驅蟲。</p><p><strong>絕育：</strong>評估絕育安排 → 絕育手術或更新絕育狀態；手術成功後接續術後健康追蹤，異常轉傷病治療。</p><p>可詢問「第一次使用」、「健康照護流程」、「疫苗流程」、「驅蟲流程」、「絕育流程」，管理者可詢問「待指派照護任務」，員工可詢問「我的照護任務回報選項」。</p></div></details><details open className="panel space-y-3"><summary className="cursor-pointer font-semibold text-lg">Chatbot 回歸測試</summary><p className="muted">在隔離資料庫測量既有行政修改與本機照護結果規則。完整 HTTP 對話測試另由 GitHub Actions 執行；未量測正式 Gemini 流量與網路端到端延遲。</p><button type="button" disabled={busy} onClick={()=>void run()}>{busy?'測試中…':result?'重新測試':'執行測試'}</button>{error&&<p role="alert" className="text-red-700">{error}</p>}{result&&<p>測試時間：{new Date(result.at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}</p>}
 <div style={{overflowX:'auto'}}><table className="data-table"><thead><tr><th>指標</th><th>結果</th><th>樣本數</th><th>定義／範圍</th></tr></thead><tbody>{(result?.metrics??['Care Outcome Recognition','Care Transition Coverage','Intent Accuracy','Multi-intent F1','Slot F1','Joint Goal Accuracy','Date Parsing Accuracy','Task Success Rate','Undo Success Rate','Unauthorized Execution Rate','LLM Invocation Rate','Average Response Time','Duplicate Execution Rate'].map(name=>({name,value:null,unit:'',n:0,detail:'尚未測試'}))).map(m=><tr key={m.name}><td>{m.name}</td><td>{m.value===null?'未測量':m.value.toFixed(2)+' '+m.unit}</td><td>{m.n||'—'}</td><td>{m.detail}</td></tr>)}</tbody></table></div></details>
 {result&&<details className="panel space-y-2"><summary className="cursor-pointer font-semibold text-lg">測試案例（{result.cases.filter(c=>c.passed).length}／{result.cases.length} 通過）</summary>{result.cases.map(c=><div key={c.name} className="rounded border p-2"><strong className={c.passed?'text-green-700':'text-red-700'}>{c.passed?'通過':'失敗'} · {c.name}</strong><p>{c.detail}</p></div>)}</details>}</section>
}
