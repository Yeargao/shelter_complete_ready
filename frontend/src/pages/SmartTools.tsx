import {useEffect,useRef,useState,type SetStateAction} from 'react';
import {Link} from 'react-router-dom';
import {api,type ChatAnswer} from '../services/api';

const base=(import.meta.env.VITE_API_URL||'').replace(/\/+$/,'');
const prefix='shelter-smart-v1:';
export function useStored<T>(name:string,initial:T){
 const key=prefix+name;
 const [value,setValue]=useState<T>(()=>{try{const raw=sessionStorage.getItem(key);return raw===null?initial:JSON.parse(raw) as T}catch{return initial}});
 const ref=useRef(value);
 const owner=useRef(sessionStorage.getItem('shelter_token'));
 function update(next:SetStateAction<T>){
  if(owner.current!==sessionStorage.getItem('shelter_token'))return;
  const value=typeof next==='function'?(next as (v:T)=>T)(ref.current):next;
  ref.current=value;setValue(value);
  try{sessionStorage.setItem(key,JSON.stringify(value)??'null')}catch{/* result remains in memory */}
 }
 return [value,update] as const;
}
async function request<T>(path:string,body?:object,method?:string):Promise<T>{
 const response=await fetch(base+'/api/smart'+path,{method:method??(body?'POST':'GET'),cache:'no-store',headers:{'Content-Type':'application/json',Authorization:'Bearer '+sessionStorage.getItem('shelter_token')},...(body?{body:JSON.stringify(body)}:{})});
 const data=await response.json();
 if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail??'請求失敗'));
 return data as T;
}
const metrics={stock:'飼料庫存低於（公斤）',stay:'在所超過（天）且健康待確認',overdue:'緊急任務逾期',load:'今日排定工時達（%）',vaccine:'疫苗即將到期（天）'};
const reports={health:'動物健康分布',species:'物種分布',tasks:'任務狀態',staff:'員工任務完成率',intake:'入離所統計'};
const events={intake:'動物入所',sick:'生病',injured:'受傷',serious:'嚴重健康異常'};
const labels=['健康狀態待確認','優先確認健康狀況','確認疫苗紀錄','確認驅蟲紀錄','健康問題追蹤'];
const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
type Metric=keyof typeof metrics;
type ReportKind=keyof typeof reports;
type EventKind=keyof typeof events;
type Option={id:number;name:string};
type Options={animals:Option[];staff:Option[];labels:string[]};
type Rule={id:string;metric:Metric;threshold:number};
type Workflow={id:string;event:EventKind;labels:string;cursor:number};
type Inbox={id:string;kind:string;detail:string;created:string;state:string};
type Monitor={rules:Rule[];workflows:Workflow[];inbox:Inbox[]};
type Report={title:string;rows:{label:string;value:number;total?:number;completed?:number}[];note:string;start:string;end:string;unit:string};
type Recommendation={animal_id:number;name:string;steps:{label:string;existing:boolean}[]};
type Check={ok:boolean;issues:string[];note:string};
type Handover={name:string;day:string;done:number;pending:number;tasks:{task_id:string;name:string;label:string;state:string;result:string|null;note:string|null}[];issues:{task_id:string;name:string;note:string}[]};
type Audit={findings:{animal_id:number;name:string;kind:string;source:string}[]};
type Command={type:'rule';metric:Metric;threshold:number}|{type:'report';kind:ReportKind;start:string;end:string}|{type:'link';path:string;message:string}|{type:'clarify';message:string}|{type:'task';animal_id:number;label:string;earliest:string;due:string;name:string};
type Turn={question:string;answer?:ChatAnswer;command?:Command;report?:Report;error?:string;applied?:string};
function Result({children}:{children:React.ReactNode}){return <div className="ai-result">{children}</div>}
function Section({title,children}:{title:string;children:React.ReactNode}){return <section className="panel ai-section"><h2>{title}</h2>{children}</section>}
function Chart({report:r}:{report:Report}){const max=Math.max(1,...r.rows.map(v=>v.value));return <Result><h3>{r.title}</h3><small>{r.start} ～ {r.end} · {r.note}</small>{!r.rows.length&&<p>此範圍沒有資料。</p>}{r.rows.map(x=><div key={x.label}><p>{x.label}：{x.value}{r.unit}{x.total!==undefined?'（'+x.completed+'/'+x.total+'）':''}</p><div style={{height:8,background:'#e2e8f0',borderRadius:4}}><div style={{height:8,background:'#0f766e',borderRadius:4,width:(100*x.value/(r.unit==='%'?100:max))+'%'}}/></div></div>)}</Result>}
export default function SmartTools(){
 const [options,setOptions]=useState<Options>({animals:[],staff:[],labels:[]});
 const [monitor,setMonitor]=useStored<Monitor|null>('monitor',null);
 const [command,setCommand]=useStored('command','');
 const [turns,setTurns]=useStored<Turn[]>('turns',[]);
 const [context,setContext]=useStored<string|null>('context',null);
 const [metric,setMetric]=useStored<Metric>('metric','stock');
 const [threshold,setThreshold]=useStored('threshold','30');
 const [event,setEvent]=useStored<EventKind>('event','intake');
 const [steps,setSteps]=useStored<string[]>('steps',['健康狀態待確認','確認疫苗紀錄','確認驅蟲紀錄']);
 const [kind,setKind]=useStored<ReportKind>('report-kind','health');
 const [start,setStart]=useStored('start',today());
 const [end,setEnd]=useStored('end',today());
 const [report,setReport]=useStored<Report|null>('report',null);
 const [animal,setAnimal]=useStored('animal','');
 const [label,setLabel]=useStored('label','健康狀態待確認');
 const [recommend,setRecommend]=useStored<Recommendation|null>('recommend',null);
 const [check,setCheck]=useStored<Check|null>('check',null);
 const [staff,setStaff]=useStored('staff','');
 const [day,setDay]=useStored('day',today());
 const [handover,setHandover]=useStored<Handover|null>('handover',null);
 const [audit,setAudit]=useStored<Audit|null>('audit',null);
 const [notices,setNotices]=useStored<Record<string,string>>('notices',{});
 const [busy,setBusy]=useState<Record<string,boolean>>({});
 const [errors,setErrors]=useState<Record<string,string>>({});
 const locks=useRef(new Set<string>());
 const session=useRef(sessionStorage.getItem('shelter_token'));
 const alive=()=>session.current===sessionStorage.getItem('shelter_token');
 const monitorLock=useRef(false);
 async function refresh(){
  if(monitorLock.current||!alive())return;
  monitorLock.current=true;
  try{const data=await request<Monitor>('/monitor');if(alive()){setMonitor(data);setErrors(p=>({...p,monitor:''}))}}
  catch(e){if(alive())setErrors(p=>({...p,monitor:String(e)}))}
  finally{monitorLock.current=false}
 }
 useEffect(()=>{
  let active=true;
  request<Options>('/options').then(r=>{if(active&&alive())setOptions(r)}).catch(e=>{if(active)setErrors(p=>({...p,options:String(e)}))});
  void refresh();const timer=window.setInterval(()=>void refresh(),60000);
  return()=>{active=false;window.clearInterval(timer)};
 },[]);
 async function run(key:string,fn:()=>Promise<void>){
  if(locks.current.has(key))return;
  locks.current.add(key);setBusy(p=>({...p,[key]:true}));setErrors(p=>({...p,[key]:''}));
  try{await fn()}catch(e){if(alive())setErrors(p=>({...p,[key]:e instanceof Error?e.message:String(e)}))}
  finally{locks.current.delete(key);if(alive())setBusy(p=>({...p,[key]:false}))}
 }
 function err(key:string){return errors[key]?<p className="ai-error" role="alert">{errors[key]}</p>:null}
 function action(key:string,title:string,fn:()=>Promise<void>,disabled=false){return <button type="button" disabled={disabled||busy[key]} onClick={()=>void run(key,fn)}>{busy[key]?'處理中…':title}</button>}
 async function saveRule(m:Metric,n:number){if(!Number.isFinite(n)||n<0)throw Error('請提供有效門檻');await request('/rules',{metric:m,threshold:n});if(alive()){setNotices(p=>({...p,rules:'提醒規則已儲存'}));await refresh()}}
 async function saveWorkflow(){await request('/workflows',{event,labels:steps});if(alive()){setNotices(p=>({...p,workflow:'已啟用，從此刻之後的事件開始監控'}));await refresh()}}
 async function send(){
  const value=command.trim();if(!value)return;
  // Split independent requests only at explicit separators; preserve conjunctions in conditions.
  const parts=value.split(/[；;\n]+|(?:，|,)\s*(?=並|再|另外)|(?:並且|並)(?=幫|安排|新增|建立|統計|開啟)/).map(s=>s.trim().replace(/^(並且|並|再|另外)/,'')).filter(Boolean);
  if(parts.length>6)throw Error('一次最多六項操作');
  let ctx=context;
  for(const question of parts){
   let turn:Turn={question};
   try{
    if(/提醒|通知|統計|報表|分布|完成率|開啟|前往|我要|新增.*任務|安排.*任務/.test(question)){
     const c=await request<Command>('/command',{text:question,context:ctx});turn.command=c;
     if(c.type==='report')turn.report=await request<Report>('/report?'+new URLSearchParams({kind:c.kind,start:c.start,end:c.end}));
    }else{
     const answer=await api.chat(question,ctx,new AbortController().signal);turn.answer=answer;ctx=answer.context;
    }
   }catch(e){turn.error=String(e)}
   if(!alive())return;
   setTurns(p=>[...p,turn]);setContext(ctx);
  }
  if(alive())setCommand('');
 }
 function applyCommand(t:Turn,i:number){
  const c=t.command;if(!c||t.applied)return null;
  if(c.type==='rule')return action('turn'+i,'確認建立提醒',async()=>{await saveRule(c.metric,c.threshold);if(alive())setTurns(p=>p.map((v,j)=>j===i?{...v,applied:'提醒規則已儲存'}:v))});
  if(c.type==='task')return action('turn'+i,'確認建立任務',async()=>{const r=await request<{message:string}>('/task',{animal_id:c.animal_id,label:c.label,earliest:c.earliest,due:c.due});if(alive())setTurns(p=>p.map((v,j)=>j===i?{...v,applied:r.message}:v))});
  return null;
 }
 const selectAnimal=<select value={animal} onChange={e=>setAnimal(e.target.value)}><option value="">選擇在所動物</option>{options.animals.map(a=><option key={a.id} value={a.id}>{a.name} #{a.id}</option>)}</select>;
 return <div className="space-y-4">
  {err('options')}{err('monitor')}
  <Section title="1、2、4｜多意圖助理、多輪對話與智慧捷徑">
   <p className="muted">可查詢多個項目；跨功能請以分號分隔，例如「統計健康分布；飼料低於30公斤提醒我」。查詢承接既有對話上下文；寫入一律先確認。</p>
   <form className="ai-form" onSubmit={e=>{e.preventDefault();void run('command',send)}}>
    <label>輸入指令<input value={command} onChange={e=>setCommand(e.target.value)} maxLength={500} placeholder="例如：查 Rufus 的健康和疫苗紀錄"/></label>
    <button disabled={!command.trim()||busy.command}>{busy.command?'處理中…':'送出'}</button>
   </form>{err('command')}
   {turns.map((t,i)=><Result key={i}><strong>{t.question}</strong>{t.answer&&<><p>{t.answer.answer}</p><small>{t.answer.sources.join(' · ')} · {t.answer.queried_at}</small></>}{t.error&&<p className="ai-error">{t.error}</p>}{t.command?.type==='link'&&<Link to={t.command.path}>{t.command.message}</Link>}{t.command?.type==='clarify'&&<p>{t.command.message}</p>}{t.command?.type==='rule'&&<p>提醒草案：{metrics[t.command.metric]} {t.command.metric==='overdue'?'':t.command.threshold}</p>}{t.command?.type==='task'&&<p>任務草案：{t.command.name} · {t.command.label} · {t.command.earliest} 至 {t.command.due}</p>}{t.report&&<Chart report={t.report}/>}{applyCommand(t,i)}{err('turn'+i)}{t.applied&&<p>{t.applied}</p>}</Result>)}
   <button className="secondary" disabled={busy.command} onClick={()=>{setTurns([]);setContext(null)}}>清除對話</button>
  </Section>
  <Section title="3｜智慧條件提醒">
   <p className="muted">建立後每分鐘檢查一次（本頁開啟時）；提醒保存在資料庫，確認後不重複通知，直到條件解除。離線檢查需另外設定伺服器排程。</p>
   <div className="ai-form"><label>提醒條件<select value={metric} onChange={e=>setMetric(e.target.value as Metric)}>{Object.entries(metrics).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
    {metric!=='overdue'&&<label>門檻<input type="number" min="0" value={threshold} onChange={e=>setThreshold(e.target.value)}/></label>}
    {action('rules','建立提醒',()=>saveRule(metric,metric==='overdue'?0:Number(threshold)),metric!=='overdue'&&!threshold.trim())}
   </div>{err('rules')}{notices.rules&&<p>{notices.rules}</p>}
   {monitor?.rules.map(r=><Result key={r.id}><p>{metrics[r.metric]} {r.metric==='overdue'?'':r.threshold}</p>{action('remove'+r.id,'停用',async()=>{await request('/rules/'+r.id,undefined,'DELETE');await refresh()})}{err('remove'+r.id)}</Result>)}
   <h3>目前提醒</h3>{monitor?.inbox.filter(x=>x.kind==='reminder').map(x=><Result key={x.id}><p>{x.detail}</p><small>{x.created}</small>{action(x.id,'已閱',async()=>{await request('/inbox/'+x.id+'/ack',{});await refresh()})}{err(x.id)}</Result>)}
   {monitor&&!monitor.inbox.some(x=>x.kind==='reminder')&&<p>目前沒有未讀提醒。</p>}
  </Section>
  <Section title="5｜自動統計報表">
   <div className="ai-form"><label>統計項目<select value={kind} onChange={e=>setKind(e.target.value as ReportKind)}>{Object.entries(reports).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><label>開始<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label><label>結束<input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label>
    {action('report',report?'重新產生報表':'產生報表',async()=>{const result=await request<Report>('/report?'+new URLSearchParams({kind,start,end}));if(alive())setReport(result)},!start||!end)}</div>{err('report')}{report&&<Chart report={report}/>}
  </Section>
  <Section title="6｜智慧操作防錯">
   <div className="ai-form"><label>動物{selectAnimal}</label><label>欲建立的任務<select value={label} onChange={e=>setLabel(e.target.value)}>{(options.labels.length?options.labels:labels).map(l=><option key={l}>{l}</option>)}</select></label>{action('check','檢查操作',async()=>{const r=await request<Check>('/check',{animal_id:Number(animal),label});if(alive())setCheck(r)},!animal)}</div>{err('check')}{check&&<Result><strong>{check.ok?'目前沒有發現問題':'操作待確認'}</strong>{check.issues.map(x=><p key={x}>{x}</p>)}<small>{check.note}</small></Result>}
  </Section>
  <Section title="7｜智慧操作流程建議">
   <div className="ai-form"><label>動物{selectAnimal}</label>{action('recommend','檢查下一步',async()=>{const r=await request<Recommendation>('/recommend/'+animal);if(alive())setRecommend(r)},!animal)}</div>{err('recommend')}{recommend&&<Result><Link to={'/animals/'+recommend.animal_id}>{recommend.name} #{recommend.animal_id}</Link>{recommend.steps.map(s=><p key={s.label}>{s.label} · {s.existing?'已存在任務，避免重複建立':'建議核對／安排'}</p>)}{!recommend.steps.length&&<p>目前沒有符合規則的後續建議。</p>}<Link to="/resources">前往資源配置</Link></Result>}
  </Section>
  <Section title="8｜自訂自動化工作流程">
   <p className="muted">選擇事件與後續步驟；系統根據新事件產生符合現況的草案，不重複建立既有任務。確認後建立任務，再由原排程功能安排。</p>
   <label>觸發事件<select value={event} onChange={e=>setEvent(e.target.value as EventKind)}>{Object.entries(events).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
   {labels.map(l=><label key={l} style={{display:'flex',alignItems:'center',gap:8}}><input style={{width:'auto'}} type="checkbox" checked={steps.includes(l)} onChange={e=>setSteps(p=>e.target.checked?[...p,l]:p.filter(x=>x!==l))}/>{l}</label>)}
   {action('workflow','儲存工作流程',saveWorkflow,!steps.length)}{err('workflow')}{notices.workflow&&<p>{notices.workflow}</p>}
   {monitor?.workflows.map(w=><Result key={w.id}><p>{events[w.event]} → {JSON.parse(w.labels).join('、')}</p>{action('remove'+w.id,'停用',async()=>{await request('/rules/'+w.id,undefined,'DELETE');await refresh()})}{err('remove'+w.id)}</Result>)}
   <h3>待確認草案</h3>{monitor?.inbox.filter(x=>x.kind==='workflow').map(x=><Result key={x.id}><p>{x.detail}</p>{action(x.id,'確認建立任務',async()=>{const r=await request<{message:string}>('/inbox/'+x.id+'/apply',{});if(alive())setNotices(p=>({...p,[x.id]:r.message}));await refresh()})}{action('skip'+x.id,'略過',async()=>{await request('/inbox/'+x.id+'/ack',{});await refresh()})}{err(x.id)}{err('skip'+x.id)}</Result>)}
   {Object.entries(notices).filter(([k])=>k.includes(':')).map(([k,v])=><p key={k}>{v}</p>)}<Link to="/resources">前往資源配置預覽排程</Link>
  </Section>
  <Section title="9｜智慧工作交接">
   <div className="ai-form"><label>員工<select value={staff} onChange={e=>setStaff(e.target.value)}><option value="">選擇員工</option>{options.staff.map(a=><option key={a.id} value={a.id}>{a.name} #{a.id}</option>)}</select></label><label>日期<input type="date" value={day} onChange={e=>setDay(e.target.value)}/></label>{action('handover','產生交接',async()=>{const r=await request<Handover>('/handover',{staff_id:Number(staff),day});if(alive())setHandover(r)},!staff||!day)}</div>{err('handover')}{handover&&<Result><strong>{handover.name} · {handover.day}</strong><p>已完成 {handover.done} 項；未完成 {handover.pending} 項。</p>{handover.tasks.map(t=><p key={t.task_id}>{t.name} · {t.label} · {t.state}{t.result?' · '+t.result:''}{t.note?' · '+t.note:''}</p>)}<h3>未結案異常</h3>{handover.issues.map(i=><p key={i.task_id}>{i.name}：{i.note}</p>)}</Result>}
  </Section>
  <Section title="10｜智慧資料一致性檢查">
   {action('audit',audit?'重新掃描':'掃描跨表資料',async()=>{const r=await request<Audit>('/audit');if(alive())setAudit(r)})}{err('audit')}{audit&&<Result><p>發現 {audit.findings.length} 筆待核對資料（不自動修改）。</p>{audit.findings.map((f,i)=><div key={i}><Link to={'/animals/'+f.animal_id}>{f.name} #{f.animal_id}</Link><p>{f.kind}</p><small>{f.source}</small></div>)}</Result>}
  </Section>
 </div>
}
