import {useEffect, useRef, useState} from 'react';
import {MessageCircle, X} from 'lucide-react';
import {api, type ChatAnswer} from '../../services/api';
import {useQueryClient} from '@tanstack/react-query';
import {useStored,smartRequest,isSmartCommand,splitCommands,executeCommand,type Command,type Report,type Check} from './smartState';
import {CommandPreview,SmartChart} from './SmartPanels';
import './ShelterChat.css';


const managerQuestions = [
 '今天有哪些緊急任務？', '哪些員工還有剩餘工時？', '這週有哪些任務尚未安排？',
 '目前收容所還能容納多少動物？', '統計這週各員工的任務完成率', '飼料低於30公斤提醒我', '建立工作流程，動物入所後確認疫苗紀錄',
];
const staffQuestions = [
 '我今天有哪些任務？', '我的下一項任務是什麼？', '這隻動物最近的健康狀況？',
 '哪些動物需要特別注意？', '這隻動物是否有驅蟲紀錄？', '本週我還有哪些工作未完成？',
];
const origins = {db:'資料庫即時查詢',rules:'規則式回答',gemini:'Gemini AI'};

type Turn={id:string;question:string;answer?:ChatAnswer;command?:Command;report?:Report;check?:Check;applied?:string;error?:string};
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
 const [context, setContext] = useStored<string|null>('chat-context',null);
 useEffect(()=>()=>active.current?.abort(), []);
 useEffect(()=>{if(scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight}, [turns,pending,error]);

 function stop() {
  active.current?.abort();
  active.current=undefined;
  setPending(false);
 }

 async function send(value:string) {
  const question=value.trim();
  if(!question||active.current)return;
  const parts=manager?splitCommands(question):[question];
  if(parts.length>6){setError('一次最多六項操作');return}
  const controller=new AbortController();
  active.current=controller;
  setInput('');setError('');setPending(true);
  let ctx=context;
  try {
   for(const [index,part] of parts.entries()){
    if(controller.signal.aborted)break;
    const id=crypto.randomUUID();
    let turn:Turn={id,question:part};
    setTurns(previous=>[...previous,turn]);
    try {
     if(manager&&isSmartCommand(part)&&(!/^(我要|幫我|請)?(查詢|查一下|查看|查)/.test(part)||/統計|報表|分布|完成率/.test(part))){
      const command=await smartRequest<Command>('/command',{text:part,context:ctx});
      turn={...turn,command};
      if(command.type==='report')turn.report=await smartRequest<Report>('/report?'+new URLSearchParams({kind:command.kind,start:command.start,end:command.end}));
      if(command.type==='task')turn.check=await smartRequest<Check>('/check',{animal_id:command.animal_id,label:command.label});
     }else if(!manager&&/^(我要|請|幫我)?(開啟|前往|看)(個人工作台|照護人員工作台|今日工作|動物列表)$/.test(part)){
      turn.command={type:'link',path:part.includes('動物列表')?'/animals':'/',message:'開啟頁面'};
     }else{
      const answer=await api.chat(index>0?'另外'+part:part,ctx,controller.signal);turn.answer=answer;ctx=answer.context;
     }
    }catch(e){if(!controller.signal.aborted)turn.error=e instanceof Error?e.message:'暫時無法查詢'}
    if(active.current!==controller)break;
    setTurns(previous=>previous.map(v=>v.id===id?turn:v));setContext(ctx);
   }
  }finally {
   if(active.current===controller){active.current=undefined;setPending(false)}
  }
 }
 async function confirm(turn:Turn){
  if(!manager||!turn.command||turn.applied||confirming.current.has(turn.id))return;
  confirming.current.add(turn.id);setActions(p=>({...p,[turn.id]:true}));
  try{
   const outcome=await executeCommand(turn.command);
   setTurns(p=>p.map(t=>t.id===turn.id?{...t,applied:outcome,error:undefined}:t));
   await qc.invalidateQueries({queryKey:['smart-monitor']});
   if(turn.command.type==='task'){
    await qc.invalidateQueries({queryKey:['schedule-week']});await qc.invalidateQueries({queryKey:['tasks']});
   }
  }catch(e){setTurns(p=>p.map(t=>t.id===turn.id?{...t,error:e instanceof Error?e.message:String(e)}:t))}
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
     {!turns.length&&<p className="chat-empty">可指定動物名稱、編號或任務 ID 來查詢。</p>}
     {turns.map(t=><div className="chat-turn" key={t.id}>
      <p className="chat-question">{t.question}</p>
      {t.answer&&<article className="chat-answer">
       <p>{t.answer.answer}</p>
       <small>{origins[t.answer.source]}</small>
       
       <details open={!!sourceOpen[t.id]} onToggle={e=>{if(e.currentTarget.open!==!!sourceOpen[t.id])setSourceOpen(p=>({...p,[t.id]:e.currentTarget.open}))}}><summary>資料來源</summary>
        <p>查詢時間 {new Date(t.answer.queried_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}</p>
        {t.answer.sources.length>0&&<ul>{t.answer.sources.map(source=><li key={source}>{source}</li>)}</ul>}
       </details>
      </article>}
      {t.command&&<article className="chat-answer space-y-2"><CommandPreview command={t.command} onNavigate={()=>dialog.current?.close()}/>
       {t.report&&<SmartChart report={t.report}/>}
       {t.check&&!t.check.ok&&<div className="text-red-700">{t.check.issues.map(x=><p key={x}>{x}</p>)}</div>}
       {['rule','workflow','task'].includes(t.command.type)&&<button type="button" disabled={!!t.applied||actions[t.id]||(t.command.type==='task'&&!t.check?.ok)} onClick={()=>void confirm(t)}>{t.applied??(actions[t.id]?'處理中…':'確認執行')}</button>}
      </article>}
      {t.error&&<p role="alert" className="text-red-700">{t.error}</p>}
     </div>)}
     {pending&&<p role="status">正在查詢…</p>}
     {error&&<p role="alert" className="text-red-700">{error}</p>}
    </div>
    <details className="chat-prompts" open={prompts} onToggle={e=>{if(e.currentTarget.open!==prompts)setPrompts(e.currentTarget.open)}}><summary>常用問題</summary>
     <div>{(manager?managerQuestions:staffQuestions).map(question=><button type="button" key={question}
      className="secondary" disabled={pending} onClick={()=>void send(question)}>{question}</button>)}</div>
    </details>
    <form onSubmit={e=>{e.preventDefault();void send(input);}}>
     <label htmlFor="chat-question" className="sr-only">輸入問題</label>
     <input id="chat-question" placeholder="輸入問題" maxLength={500} value={input} onChange={e=>setInput(e.target.value)}/>
     <button disabled={pending||!input.trim()}>送出</button>
    </form>
    <footer>
     {pending&&<button type="button" className="secondary" onClick={()=>{stop();setError('已停止等待，可重新送出問題。');}}>停止等待</button>}
     <button type="button" className="secondary" disabled={Object.values(actions).some(Boolean)} onClick={()=>{stop();setTurns([]);setSourceOpen({});setError('');setInput('');setContext(null);}}>清除對話</button>
    </footer>
   </div>
  </dialog>
 </>;
}
