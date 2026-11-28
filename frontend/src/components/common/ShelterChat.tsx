import {useEffect, useRef, useState} from 'react';
import {MessageCircle, X} from 'lucide-react';
import {api,type ChatAnswer} from '../../services/api';
import {useQueryClient} from '@tanstack/react-query';
import {Link} from 'react-router-dom';
import {useStored,executeCommand,type Command,type Report,type Check} from './smartState';
import {CommandPreview,SmartChart} from './SmartPanels';
import './ShelterChat.css';
import {displayTaskLabel,taskChoices} from './taskPresentation';


const managerQuestions = [
 '第一次使用','健康照護流程','疫苗流程','驅蟲流程','絕育流程','待指派照護任務',
 '某動物生病了之後要怎麼做？', '飼料庫存還剩多少？', '員工請假後如何調整排程？', '今天有哪些緊急任務？', '哪些員工還有剩餘工時？', '這週有哪些任務尚未安排？',
 '目前收容所還能容納多少動物？', '統計這週各員工的任務完成率', '查詢今天已完成哪些任務', '開啟健康行政核對',
];
const staffQuestions = [
 '第一次使用','我的照護任務回報選項','健康照護流程','疫苗流程','驅蟲流程','絕育流程',
 '某動物生病了之後要怎麼做？', '怎麼回報照護任務？', '如何收回回報？', '我今天有哪些任務？', '我的下一項任務是什麼？', '這隻動物最近的健康狀況？',
 '哪些動物需要特別注意？', '這隻動物是否有驅蟲紀錄？', '本週我還有哪些工作未完成？',
];
const origins = {db:'資料庫即時查詢',rules:'規則式回答',gemini:'Gemini AI'};

type AnimalAction={type:'animal_action';action_id:string;animal_id:number;name:string;kind:'edit'|'undo';changes:{field:string;before:string;after:string}[]};
type StaffReport={type:'staff_report';task_id:string;name:string;label:string;day:string;result:string;note:string;administered_date?:string|null;next_step?:string};
type Turn={links?:{path:string;label:string}[];suggestions?:{label:string;question:string}[];id:string;question:string;answer?:ChatAnswer;command?:Command|AnimalAction|StaffReport;report?:Report;check?:Check;applied?:string;error?:string;actionStatus?:string};
const newId=()=>crypto.randomUUID();
async function agentRequest<T>(path:string,body?:object,signal?:AbortSignal):Promise<T>{
 const res=await fetch((import.meta.env.VITE_API_URL||'').replace(/\/+$/,'')+'/api/agent'+path,{method:body?'POST':'GET',cache:'no-store',signal,headers:{'Content-Type':'application/json',Authorization:'Bearer '+sessionStorage.getItem('shelter_token')},...(body?{body:JSON.stringify(body)}:{})});
 const data=await res.json();if(!res.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail??'請求失敗'));return data as T;
}
export default function ShelterChat({manager}:{manager:boolean}) {
 const qc=useQueryClient();
 const confirming=useRef(new Set<string>());
 const [actions,setActions]=useState<Record<string,boolean>>({});
 const [prompts,setPrompts]=useStored('chat-prompts',false);
 const [sourceOpen,setSourceOpen]=useStored<Record<string,boolean>>('chat-sources',{});
 const dialog = useRef<HTMLDialogElement>(null);
 const launcher = useRef<HTMLButtonElement>(null);
 const scroll = useRef<HTMLDivElement>(null);
 const active = useRef<AbortController>();
 const [input, setInput] = useStored('chat-input','');
 const [pending, setPending] = useState(false);
 const [error, setError] = useState('');
 const [turns, setTurns] = useStored<Turn[]>('chat-turns',[]);
 const [sessionId,setSessionId]=useStored('agent-session',newId());
 useEffect(()=>()=>active.current?.abort(), []);
 useEffect(()=>{if(scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight}, [turns,pending,error]);

 function stop() {
  active.current?.abort();
  active.current=undefined;
  setPending(false);
 }

 async function syncStatuses(){
  if(!manager)return;
  const r=await agentRequest<{actions:{action_id:string;status:string}[]}>('/actions?session_id='+encodeURIComponent(sessionId));
  const statuses=new Map(r.actions.map(a=>[a.action_id,a.status]));
  setTurns(p=>p.map(t=>{
   if(t.command?.type!=='animal_action')return t;
   const status=statuses.get(t.command.action_id);
   return status?{...t,actionStatus:status}:t;
  }));
 }
 useEffect(()=>{void syncStatuses().catch(()=>{});},[sessionId]);
 async function send(value:string) {
  const question=value.trim();
  if(!question||active.current||confirming.current.size)return;
  const controller=new AbortController();active.current=controller;
  setInput('');setError('');setPending(true);
  try {
   const response=await agentRequest<{turns:Omit<Turn,'id'>[]}>('/chat',{question,session_id:sessionId},controller.signal);
   if(active.current!==controller)return;
   setTurns(p=>[...p,...response.turns.map(t=>({...t,id:newId()}))]);
   await syncStatuses();
  }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'暫時無法查詢')}
  finally{if(active.current===controller){active.current=undefined;setPending(false)}}
 }
 async function confirm(turn:Turn,decision:'confirm'|'cancel'='confirm'){
  if(!turn.command||(!manager&&turn.command.type!=='staff_report')||turn.applied||active.current||confirming.current.size||(turn.actionStatus&&turn.actionStatus!=='pending'))return;
  confirming.current.add(turn.id);setActions(p=>({...p,[turn.id]:true}));
  try{
   let outcome:string;
   if(turn.command.type==='animal_action'){
    const r=await agentRequest<{message:string;status:string}>('/actions/'+turn.command.action_id,{session_id:sessionId,decision});
    outcome=r.message;
   }else if(turn.command.type==='staff_report'){
    if(decision==='cancel')outcome='已取消';
    else{await api.reportWeekly(turn.command.task_id,{result:turn.command.result,note:turn.command.note,administered_date:turn.command.administered_date,photos:[],expected_day:turn.command.day});outcome='已回報'+(turn.command.next_step?' · '+turn.command.next_step:'');}
   }else{
    if(decision==='cancel')outcome='已取消';
    else outcome=await executeCommand(turn.command);
   }
   setTurns(p=>p.map(t=>t.id===turn.id?{...t,applied:outcome,error:undefined}:t));
   await syncStatuses();
   if(decision==='confirm'){
    window.dispatchEvent(new Event('shelter-data-changed'));
    for(const key of ['smart-monitor','schedule-week','tasks','animal','animals','summary','resource-overview','health'])
     await qc.invalidateQueries({queryKey:[key]});
   }
  }catch(e){setTurns(p=>p.map(t=>t.id===turn.id?{...t,error:e instanceof Error?e.message:String(e)}:t));await syncStatuses().catch(()=>{})}
  finally{confirming.current.delete(turn.id);setActions(p=>({...p,[turn.id]:false}))}
 }

 return <>
  <button ref={launcher} type="button" className="chat-launcher" onClick={()=>dialog.current?.showModal()}>
   <MessageCircle aria-hidden="true" size={20}/> 收容所助理
  </button>
  <dialog ref={dialog} aria-labelledby="shelter-chat-title" className="chat-dialog" onClose={()=>{launcher.current?.focus();}}>
   <div className="chat-panel">
    <header><div className="chat-heading"><MessageCircle size={21} aria-hidden="true"/><h2 id="shelter-chat-title">收容所助理</h2></div>
     <button type="button" className="secondary" onClick={()=>dialog.current?.close()} aria-label="關閉聊天"><X size={20}/></button>
    </header>
    <div className="chat-stream" ref={scroll} role="log" aria-label="對話訊息">
     {!turns.length&&<p className="chat-empty">可以詢問照護流程、動物資料及任務，也能依權限建立操作草案。</p>}
     {turns.map(t=><div className="chat-turn" key={t.id}>
      <p className="chat-question">{t.question}</p>
      {t.answer&&<article className="chat-answer">
       <p>{t.answer.answer}</p>
       {t.links?.length? <div className="smart-inline">{t.links.map(l=><Link key={l.path} to={l.path} onClick={()=>dialog.current?.close()}>{l.label}</Link>)}</div>:null}
       {t.suggestions?.length?<div className="smart-inline">{t.suggestions.map(s=><button type="button" className="secondary" key={s.question} disabled={pending||Object.values(actions).some(Boolean)} onClick={()=>void send(s.question)}>{s.label}</button>)}</div>:null}
       <small>{origins[t.answer.source]}</small>
       
       <details open={!!sourceOpen[t.id]} onToggle={e=>{if(e.currentTarget.open!==!!sourceOpen[t.id])setSourceOpen(p=>({...p,[t.id]:e.currentTarget.open}))}}><summary>資料來源</summary>
        <p>查詢時間 {new Date(t.answer.queried_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}</p>
        {t.answer.sources.length>0&&<ul>{t.answer.sources.map(source=><li key={source}>{source}</li>)}</ul>}
       </details>
      </article>}
      {t.command&&<article className="chat-answer space-y-2">{t.command.type==='animal_action'?<><strong>{t.command.name} #{t.command.animal_id} · {t.command.kind==='undo'?'復原草案':'資料修改草案'}</strong><table className="data-table"><thead><tr><th>欄位</th><th>修改前</th><th>修改後</th></tr></thead><tbody>{t.command.changes.map((c,i)=><tr key={i}><td>{c.field}</td><td>{c.before}</td><td>{c.after}</td></tr>)}</tbody></table></>:t.command.type==='staff_report'?<><strong>{t.command.name} · {displayTaskLabel(t.command.label)} · {t.command.day}</strong><p>回報結果：{taskChoices[t.command.label]?.find(([value])=>value===(t.command as StaffReport).result)?.[1]??t.command.result}</p>{t.command.note&&<p>備註：{t.command.note}</p>}{t.command.administered_date&&<p>實際施打日期：{t.command.administered_date}</p>}{t.command.next_step&&<p>後續：{t.command.next_step}</p>}</>:<CommandPreview command={t.command} onNavigate={()=>dialog.current?.close()}/>}
       {t.report&&<SmartChart report={t.report}/>}
       {t.check&&!t.check.ok&&<div className="text-red-700">{t.check.issues.map(x=><p key={x}>{x}</p>)}</div>}
       {['task','animal_action','staff_report'].includes(t.command.type)&&<div className="smart-inline"><button type="button" disabled={!!t.applied||pending||Object.values(actions).some(Boolean)||(t.actionStatus!==undefined&&t.actionStatus!=='pending')||(t.command.type==='task'&&!t.check?.ok)} onClick={()=>void confirm(t)}>{t.actionStatus==='undone'?'已復原':t.actionStatus==='cancelled'?'已取消':t.applied??(t.actionStatus==='applied'?'已執行':actions[t.id]?'處理中…':'確認執行')}</button>{!t.applied&&(!t.actionStatus||t.actionStatus==='pending')&&<button type="button" className="secondary" disabled={pending||Object.values(actions).some(Boolean)} onClick={()=>void confirm(t,'cancel')}>取消</button>}</div>}
      </article>}
      {t.error&&<p role="alert" className="text-red-700">{t.error}</p>}
     </div>)}
     {pending&&<p role="status">正在查詢…</p>}
     {error&&<p role="alert" className="text-red-700">{error}</p>}
    </div>
    <details className="chat-prompts" open={prompts} onToggle={e=>{if(e.currentTarget.open!==prompts)setPrompts(e.currentTarget.open)}}><summary>常用問題</summary>
     <div>{(manager?managerQuestions:staffQuestions).map(question=><button type="button" key={question}
      className="secondary" disabled={pending||Object.values(actions).some(Boolean)} onClick={()=>void send(question)}>{question}</button>)}</div>
    </details>
    <form onSubmit={e=>{e.preventDefault();void send(input);}}>
     <label htmlFor="chat-question" className="sr-only">輸入問題</label>
     <input id="chat-question" placeholder="輸入問題" maxLength={500} value={input} onChange={e=>setInput(e.target.value)}/>
     <button disabled={pending||Object.values(actions).some(Boolean)||!input.trim()}>送出</button>
    </form>
    <footer>
     {pending&&<button type="button" className="secondary" onClick={()=>{stop();setError('已停止等待，可重新送出問題。');}}>停止等待</button>}
     <button type="button" className="secondary" disabled={pending||Object.values(actions).some(Boolean)} onClick={()=>{stop();setTurns([]);setSourceOpen({});setError('');setInput('');setSessionId(newId());}}>清除對話</button>
    </footer>
   </div>
  </dialog>
 </>;
}
