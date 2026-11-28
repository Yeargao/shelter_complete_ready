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
 return <section className="space-y-4"><h1>AI 評估</h1><div className="panel space-y-3"><h2>Chatbot 回歸測試</h2><button type="button" disabled={busy} onClick={()=>void run()}>{busy?'測試中…':result?'重新測試':'執行測試'}</button>{error&&<p role="alert" className="text-red-700">{error}</p>}{result&&<p>測試時間：{new Date(result.at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}</p>}
 <div style={{overflowX:'auto'}}><table className="data-table"><thead><tr><th>指標</th><th>結果</th><th>樣本數</th><th>定義／範圍</th></tr></thead><tbody>{(result?.metrics??['Intent Accuracy','Multi-intent F1','Slot F1','Joint Goal Accuracy','Date Parsing Accuracy','Task Success Rate','Undo Success Rate','Unauthorized Execution Rate','LLM Invocation Rate','Average Response Time','Duplicate Execution Rate'].map(name=>({name,value:null,unit:'',n:0,detail:'尚未測試'}))).map(m=><tr key={m.name}><td>{m.name}</td><td>{m.value===null?'未測量':m.value.toFixed(2)+' '+m.unit}</td><td>{m.n||'—'}</td><td>{m.detail}</td></tr>)}</tbody></table></div></div>
 {result&&<div className="panel space-y-2"><h2>測試案例</h2>{result.cases.map(c=><div key={c.name} className="rounded border p-2"><strong className={c.passed?'text-green-700':'text-red-700'}>{c.passed?'通過':'失敗'} · {c.name}</strong><p>{c.detail}</p></div>)}</div>}</section>
}
