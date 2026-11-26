import {useEffect, useRef, useState} from 'react';
import {MessageCircle, X} from 'lucide-react';
import {api, type ChatAnswer} from '../../services/api';
import './ShelterChat.css';
import {aiGuidance} from './aiStatus';

const managerQuestions = [
 '今天有哪些緊急任務？', '哪些員工還有剩餘工時？', '這週有哪些任務尚未安排？',
 '目前收容所還能容納多少動物？', '為什麼這項任務沒有成功指派？', '某位員工請假會影響哪些任務？',
];
const staffQuestions = [
 '我今天有哪些任務？', '我的下一項任務是什麼？', '這隻動物最近的健康狀況？',
 '哪些動物需要特別注意？', '這隻動物是否有驅蟲紀錄？', '本週我還有哪些工作未完成？',
];
const origins = {db:'資料庫即時查詢',rules:'規則式回答',gemini:'Gemini AI'};

export default function ShelterChat({manager}:{manager:boolean}) {
 const dialog = useRef<HTMLDialogElement>(null);
 const launcher = useRef<HTMLButtonElement>(null);
 const scroll = useRef<HTMLDivElement>(null);
 const active = useRef<AbortController>();
 const [input, setInput] = useState('');
 const [pending, setPending] = useState(false);
 const [error, setError] = useState('');
 const [turns, setTurns] = useState<{question:string;answer?:ChatAnswer}[]>([]);
 const [context, setContext] = useState<string|null>(null);
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
  const controller=new AbortController();
  active.current=controller;
  setInput('');
  setError('');
  setPending(true);
  setTurns(previous=>[...previous.slice(-9),{question}]);
  try {
   const answer=await api.chat(question,context,controller.signal);
   if(active.current!==controller)return;
   setTurns(previous=>[...previous.slice(0,-1),{question,answer}]);
   setContext(answer.context);
  } catch(e) {
   if(!controller.signal.aborted)setError(e instanceof Error?e.message:'暫時無法查詢');
  } finally {
   if(active.current===controller){active.current=undefined;setPending(false);}
  }
 }

 return <>
  <button ref={launcher} type="button" className="chat-launcher" onClick={()=>dialog.current?.showModal()}>
   <MessageCircle aria-hidden="true" size={20}/> 收容所助理
  </button>
  <dialog ref={dialog} aria-labelledby="shelter-chat-title" className="chat-dialog" onClose={()=>{stop();launcher.current?.focus();}}>
   <div className="chat-panel">
    <header><div className="chat-heading"><MessageCircle size={21} aria-hidden="true"/><h2 id="shelter-chat-title">收容所助理</h2></div>
     <button type="button" className="secondary" onClick={()=>dialog.current?.close()} aria-label="關閉聊天"><X size={20}/></button>
    </header>
    <div className="chat-stream" ref={scroll} role="log" aria-label="對話訊息">
     {!turns.length&&<p className="chat-empty">可指定動物名稱、編號或任務 ID 來查詢。</p>}
     {turns.map(({question,answer},i)=><div className="chat-turn" key={i}>
      <p className="chat-question">{question}</p>
      {answer&&<article className="chat-answer">
       <p>{answer.answer}</p>
       <small>{origins[answer.source]}{answer.fallback_reason?' · 目前 AI 無法使用':''}</small>
       {answer.fallback_reason&&<p className="muted">{aiGuidance(answer.fallback_reason)}</p>}
       <details><summary>資料來源</summary>
        <p>查詢時間 {new Date(answer.queried_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}</p>
        {answer.sources.length>0&&<ul>{answer.sources.map(source=><li key={source}>{source}</li>)}</ul>}
       </details>
      </article>}
     </div>)}
     {pending&&<p role="status">正在查詢…</p>}
     {error&&<p role="alert" className="text-red-700">{error}</p>}
    </div>
    <details className="chat-prompts" open={!turns.length || undefined}><summary>常用問題</summary>
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
     <button type="button" className="secondary" onClick={()=>{stop();setTurns([]);setError('');setInput('');setContext(null);}}>清除對話</button>
    </footer>
   </div>
  </dialog>
 </>;
}
