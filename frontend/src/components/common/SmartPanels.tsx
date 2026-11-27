import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,type PhotoMatch,type WeeklyTask} from '../../services/api';
import {taipeiToday} from './scheduleDates';
import {useStored,smartRequest,metrics,events,labels,executeCommand,type Command,type Metric,type EventKind,type Monitor,type Options,type Handover,type Report} from './smartState';
import './SmartPanels.css';

const message=(e:unknown)=>e instanceof Error?e.message:String(e);
function ErrorText({text}:{text:string}){return text?<p role="alert" className="ai-error">{text}</p>:null}
function Result({children}:{children:ReactNode}){return <div className="ai-result">{children}</div>}
function useActions(){
 const [busy,setBusy]=useState<Record<string,boolean>>({});
 const [errors,setErrors]=useState<Record<string,string>>({});
 const locked=useRef(new Set<string>());
 async function run(key:string,fn:()=>Promise<unknown>){
  if(locked.current.has(key))return;
  locked.current.add(key);setBusy(p=>({...p,[key]:true}));setErrors(p=>({...p,[key]:''}));
  try{await fn()}catch(e){setErrors(p=>({...p,[key]:message(e)}))}finally{locked.current.delete(key);setBusy(p=>({...p,[key]:false}))}
 }
 const button=(key:string,title:string,fn:()=>Promise<unknown>,disabled=false)=><button type="button" disabled={disabled||busy[key]} onClick={()=>void run(key,fn)}>{busy[key]?'處理中…':title}</button>;
 const error=(key:string)=><ErrorText text={errors[key]??''}/>;
 return {button,error,busy,run};
}
function Fold({id,title,children,defaultOpen=false}:{id:string;title:string;children:ReactNode;defaultOpen?:boolean}){
 const [open,setOpen]=useStored('fold:'+id,defaultOpen);
 return <details className="panel smart-section space-y-3" open={open} onToggle={e=>{if(e.currentTarget.open!==open)setOpen(e.currentTarget.open)}}><summary>{title}</summary>{children}</details>
}
export function SmartChart({report:r}:{report:Report}){
 const max=Math.max(1,...r.rows.map(v=>v.value));
 return <div className="smart-chart space-y-2"><h3>{r.title}</h3><small>{r.start} ～ {r.end} · {r.note}</small>{!r.rows.length&&<p>沒有資料</p>}{r.rows.map(x=><div key={x.label}><p>{x.label}：{x.value}{r.unit}{x.total!==undefined?'（'+x.completed+'/'+x.total+'）':''}</p><div style={{height:8,background:'#e2e8f0',borderRadius:4}}><div style={{height:8,background:'#0f766e',borderRadius:4,width:(100*x.value/(r.unit==='%'?100:max))+'%'}}/></div></div>)}</div>
}
export function CommandPreview({command:c,onNavigate}:{command:Command;onNavigate?:()=>void}){
 if(c.type==='link')return <Link to={c.path} onClick={onNavigate}>{c.message}</Link>;
 if(c.type==='clarify')return <p>{c.message}</p>;
 if(c.type==='rule')return <p>提醒：{metrics[c.metric]} {c.metric==='overdue'?'':c.threshold}</p>;
 if(c.type==='workflow')return <p>工作流程：{events[c.event]} → {c.labels.join('、')}</p>;
 if(c.type==='task')return <p>建立任務：{c.name} #{c.animal_id} · {c.label} · {c.earliest} 至 {c.due}</p>;
 return null;
}
function useMonitor(){
 const qc=useQueryClient();
 const query=useQuery({queryKey:['smart-monitor'],queryFn:()=>smartRequest<Monitor>('/monitor'),refetchInterval:60000,staleTime:30000});
 return {data:query.data,error:query.error,refresh:()=>qc.invalidateQueries({queryKey:['smart-monitor']})};
}
export function ReminderPanel(){
 const {data,error,refresh}=useMonitor();const a=useActions();
 const [metric,setMetric]=useStored<Metric>('metric','stock');
 const [threshold,setThreshold]=useStored('threshold','30');
 const [notice,setNotice]=useStored('reminder-notice','');
 const [rulesOpen,setRulesOpen]=useStored('reminder-rules-open',false);
 const reminders=[...(data?.inbox??[]),...(data?.history??[])].filter(x=>x.kind==='reminder').sort((a,b)=>b.created.localeCompare(a.created)||a.id.localeCompare(b.id));
 return <section className="panel space-y-3"><h2>智慧提醒</h2>{error&&<ErrorText text={message(error)}/>}
  {reminders.map(x=><Result key={x.id}><p>{x.detail}</p>{x.state==='pending'?a.button(x.id,'標記已讀',async()=>{await smartRequest('/inbox/'+x.id+'/ack',{});await refresh()}):<button type="button" disabled>已讀</button>}{a.error(x.id)}</Result>)}
  {data&&!reminders.length&&<p className="muted">無提醒</p>}
  <details className="space-y-2" open={rulesOpen} onToggle={e=>{if(e.currentTarget.open!==rulesOpen)setRulesOpen(e.currentTarget.open)}}><summary>提醒規則</summary>
   <div className="ai-form"><label>條件<select value={metric} onChange={e=>setMetric(e.target.value as Metric)}>{Object.entries(metrics).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
   {metric!=='overdue'&&<label>門檻<input type="number" min="0" value={threshold} onChange={e=>setThreshold(e.target.value)}/></label>}
   {a.button('rule','建立提醒',async()=>{await smartRequest('/rules',{metric,threshold:metric==='overdue'?0:Number(threshold)});setNotice('已建立提醒');await refresh()},metric!=='overdue'&&(!threshold.trim()||!Number.isFinite(Number(threshold))||Number(threshold)<0))}</div>
   {a.error('rule')}{notice&&<p role="status">{notice}</p>}
   {data?.rules.map(r=><Result key={r.id}><p>{metrics[r.metric]} {r.metric==='overdue'?'':r.threshold}</p>{a.button(r.id,'停用',async()=>{await smartRequest('/rules/'+r.id,undefined,'DELETE');await refresh()})}{a.error(r.id)}</Result>)}
  </details>
 </section>
}
export function WorkflowPanel(){
 const {data,error,refresh}=useMonitor();const a=useActions();const qc=useQueryClient();
 const [event,setEvent]=useStored<EventKind>('event','intake');
 const [steps,setSteps]=useStored<string[]>('steps',['健康狀態待確認','確認疫苗紀錄','確認驅蟲紀錄']);
 const [notice,setNotice]=useStored('workflow-notice','');
 const [applied,setApplied]=useStored<Record<string,string>>('workflow-applied',{});
 const items=[...(data?.inbox??[]),...(data?.history??[])].filter(x=>x.kind==='workflow').sort((a,b)=>b.created.localeCompare(a.created)||a.id.localeCompare(b.id));
 return <Fold id="workflow" title="自訂自動化工作流程">{error&&<ErrorText text={message(error)}/>}
  <label>觸發事件<select value={event} onChange={e=>setEvent(e.target.value as EventKind)}>{Object.entries(events).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
  <div className="smart-inline">{labels.map(l=><label key={l} className="weekly-checkbox"><input type="checkbox" checked={steps.includes(l)} onChange={e=>setSteps(p=>e.target.checked?[...p,l]:p.filter(x=>x!==l))}/>{l}</label>)}</div>
  {a.button('create','建立工作流程',async()=>{await smartRequest('/workflows',{event,labels:steps});setNotice('已建立工作流程');await refresh()},!steps.length)}{a.error('create')}{notice&&<p>{notice}</p>}
  {data?.workflows.map(w=><Result key={w.id}><p>{events[w.event]} → {JSON.parse(w.labels).join('、')}</p>{a.button(w.id,'停用',async()=>{await smartRequest('/rules/'+w.id,undefined,'DELETE');await refresh()})}{a.error(w.id)}</Result>)}
  <h3>工作流程草案</h3>{items.map(x=><Result key={x.id}><p>{x.detail}</p>{x.state==='pending'&&!applied[x.id]?<div className="smart-inline">{a.button(x.id,'確認建立任務',async()=>{const r=await smartRequest<{message:string}>('/inbox/'+x.id+'/apply',{});setApplied(p=>({...p,[x.id]:r.message}));await refresh();await qc.invalidateQueries({queryKey:['schedule-week']})})}{a.button('skip'+x.id,'略過',async()=>{await smartRequest('/inbox/'+x.id+'/ack',{});setApplied(p=>({...p,[x.id]:'已略過'}));await refresh()})}</div>:<button type="button" disabled>{applied[x.id]??(x.state==='applied'?'已執行':'已略過')}</button>}{a.error(x.id)}{a.error('skip'+x.id)}</Result>)}{!items.length&&<p className="muted">無工作流程草案</p>}
 </Fold>
}
type Recommendation={animal_id:number;name:string;steps:{label:string;existing:boolean}[]};
export function RecommendationPanel({animalId}:{animalId:number}){
 const [result,setResult]=useStored<Recommendation|null>('recommend:'+animalId,null);
 const [completed,setCompleted]=useStored<Record<string,string>>('recommend-complete:'+animalId,{});
 const [dates,setDates]=useStored<Record<string,string>>('recommend-dates:'+animalId,{});
 const a=useActions();const qc=useQueryClient();
 return <Fold id={'recommend:'+animalId} title="照護流程建議" defaultOpen={true}>
  {a.button('get',result?'重新整理建議':'取得建議',async()=>{setResult(await smartRequest<Recommendation>('/recommend/'+animalId));setCompleted({})})}{a.error('get')}
  {result&&<div className="space-y-2">{result.steps.map(s=><Result key={s.label}><strong>{s.label}</strong>{s.existing||completed[s.label]?<button type="button" disabled>{completed[s.label]??'已有任務'}</button>:<div className="smart-inline"><label>日期<input type="date" min={taipeiToday()} value={dates[s.label]??taipeiToday()} onChange={e=>setDates(p=>({...p,[s.label]:e.target.value}))}/></label>{a.button(s.label,'確認新增任務',async()=>{const date=dates[s.label]??taipeiToday();const outcome=await executeCommand({type:'task',animal_id:animalId,name:result.name,label:s.label,earliest:date,due:date});setCompleted(p=>({...p,[s.label]:outcome}));await qc.invalidateQueries({queryKey:['schedule-week']});await qc.invalidateQueries({queryKey:['tasks']})},!(dates[s.label]??taipeiToday()))}</div>}{a.error(s.label)}</Result>)}{!result.steps.length&&<p>無待處理建議</p>}</div>}
 </Fold>
}
export function QualityPanel({scope='all',animalId}:{scope?:'all'|'health'|'resources';animalId?:number}){
 const id='quality:'+scope+':'+(animalId??'all');
 const [result,setResult]=useStored<Awaited<ReturnType<typeof api.auditData>>|null>(id,null);
 const [kind,setKind]=useStored(id+':filter','');
 const a=useActions();
 const findings=result?.findings.filter(r=>!kind||r.kind===kind)??[];
 return <Fold id={id} title={scope==='resources'?'資源與排程核對':'資料一致性核對'}>
  {a.button('scan',result?'重新掃描':'掃描資料',async()=>{setResult(await api.auditData(scope,animalId));setKind('')})}{a.error('scan')}
  {result&&<><p>待核對 {result.findings.length} 筆</p>{result.warning&&<ErrorText text={result.warning}/>}
   {result.findings.length>0&&<label>類型<select value={kind} onChange={e=>setKind(e.target.value)}><option value="">全部</option>{Array.from(new Set(result.findings.map(r=>r.kind))).map(k=><option key={k}>{k}</option>)}</select></label>}
   {findings.length===0?<p>無符合項目</p>:<div className="ai-results">{findings.map((r,i)=><Result key={r.animal_id+':'+i}><div className="ai-result-heading"><Link to={'/animals/'+r.animal_id}>#{r.animal_id} {r.name}</Link><span className="status">{r.kind}</span></div><p>{r.detail}</p><small className="muted">{r.source}</small></Result>)}</div>}
  </>}
 </Fold>
}
function Thumb({item}:{item:PhotoMatch}){
 const [url,setUrl]=useState(''),[failed,setFailed]=useState(false);
 useEffect(()=>{if(!item.task_id||!item.photo_id)return;let active=true,object='';
  api.taskPhoto(item.task_id,item.photo_id).then(blob=>{if(active){object=URL.createObjectURL(blob);setUrl(object);}}).catch(()=>{if(active)setFailed(true)});
  return()=>{active=false;if(object)URL.revokeObjectURL(object)};
 },[item.task_id,item.photo_id]);
 return url?<img className="ai-thumb" src={url} alt={'動物 '+item.name+' 的照護照片'}/>:failed?<small className="muted">無法載入照片</small>:null;
}

function encodePhoto(file:File):Promise<string>{
 return new Promise((resolve,reject)=>{
  const image=new Image(),url=URL.createObjectURL(file);
  image.onload=()=>{try{
   const scale=Math.min(1,1024/Math.max(image.naturalWidth,image.naturalHeight));
   const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));
   const ctx=canvas.getContext('2d');if(!ctx)throw Error('無法處理影像');
   ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0,canvas.width,canvas.height);
   resolve(canvas.toDataURL('image/jpeg',.85).split(',')[1]);
  }catch(e){reject(e)}finally{URL.revokeObjectURL(url)}};
  image.onerror=()=>{URL.revokeObjectURL(url);reject(Error('無法讀取圖片，請使用 JPEG、PNG 或 WebP'))};
  image.src=url;
 });
}

export function PhotoComparison({cacheId,currentPhoto,animalId,embedded=false}:{cacheId:string;currentPhoto?:string|null;animalId?:number;embedded?:boolean}){
 const [file,setFile]=useState<File>(),[preview,setPreview]=useState('');
 const [result,setResult]=useStored<Awaited<ReturnType<typeof api.comparePhotos>>|null>('photo:'+cacheId,null);
 const [filename,setFilename]=useStored('photo-name:'+cacheId,'');
 const [open,setOpen]=useStored('photo-open:'+cacheId,false);
 const input=useRef<HTMLInputElement>(null);const a=useActions();
 useEffect(()=>{if(!file){setPreview('');return}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url)},[file]);
 const dataPhoto=currentPhoto?.startsWith('data:image/')&&currentPhoto.includes(';base64,')?currentPhoto.split(';base64,')[1]:null;
 const matches=result?.results.filter(r=>r.animal_id!==animalId)??[];
 return <details className={embedded?'md:col-span-2 smart-section space-y-3':'panel smart-section space-y-3'} open={open} onToggle={e=>{if(e.currentTarget.open!==open)setOpen(e.currentTarget.open)}}><summary>動物照片比對</summary>
  <div className="ai-form"><label>選擇照片<input ref={input} type="file" accept="image/jpeg,image/png,image/webp" disabled={a.busy.compare} onChange={e=>setFile(e.target.files?.[0])}/></label><label>手機拍照<input type="file" accept="image/*" capture="environment" disabled={a.busy.compare} onChange={e=>setFile(e.target.files?.[0])}/></label>
   {preview&&<img src={preview} className="ai-preview" alt="待比對照片"/>}
   {a.button('compare',result?'重新比對':'比對既有照片',async()=>{if(!file&&!dataPhoto)return;if(file&&file.size>15*1024*1024)throw Error('原始圖片最多 15 MB');const r=await api.comparePhotos(file?await encodePhoto(file):dataPhoto!);setResult(r);setFilename(file?.name??'目前動物照片')},!file&&!dataPhoto)}
   <button type="button" className="secondary" disabled={a.busy.compare||(!file&&!result)} onClick={()=>{setFile(undefined);setResult(null);setFilename('');if(input.current)input.current.value=''}}>清除</button>
  </div>{a.error('compare')}
  {result&&<><p>{filename} · {result.mode==='clip_embedding'?'CLIP':'影像特徵'} · 比對 {result.processed} 張</p>{result.warning&&<p className="muted">{result.warning}</p>}{(result.skipped>0||result.remote_skipped>0)&&<small>無法讀取 {result.skipped} 張；外部網址略過 {result.remote_skipped} 張</small>}
   {matches.length===0?<p>無可比對結果</p>:<div className="ai-results">{matches.map(r=><Result key={r.animal_id}><div className="ai-photo-result"><Thumb item={r}/><div><Link to={'/animals/'+r.animal_id}>#{r.animal_id} {r.name}</Link><p>{r.is_active?'目前在所':'已離所'}</p><p>相似分數 {r.score.toFixed(3)}（非身分確認）</p></div></div></Result>)}</div>}
  </>}
 </details>
}
export function HandoverPanel({staffId,day:initialDay,personal=false}:{staffId?:number;day?:string;personal?:boolean}){
 const [staff,setStaff]=useStored('handover-staff',staffId?String(staffId):'');
 const [day,setDay]=useStored('handover-day',initialDay??taipeiToday());
 const selected=personal?String(staffId??''):staff;
 const when=personal?(initialDay??taipeiToday()):day;
 const [results,setResults]=useStored<Record<string,Handover>>('handover-results',{});
 const key=selected+':'+when;const result=results[key];
 const options=useQuery({queryKey:['smart-options'],queryFn:()=>smartRequest<Options>('/options'),enabled:!personal,staleTime:60000});
 const a=useActions();
 return <Fold id={personal?'handover-personal':'handover-manager'} title="工作交接" defaultOpen={personal}>
  <div className="ai-form">{!personal&&<><label>員工<select value={staff} onChange={e=>setStaff(e.target.value)}><option value="">選擇員工</option>{options.data?.staff.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><label>日期<input type="date" value={day} onChange={e=>setDay(e.target.value)}/></label></>}
   {a.button('get',result?'重新整理交接':'查看交接',async()=>{const r=await smartRequest<Handover>('/handover',{staff_id:Number(selected),day:when});setResults(p=>({...p,[key]:r}))},!selected||!when)}
  </div>{a.error('get')}{options.error&&<ErrorText text={message(options.error)}/>}
  {result&&<Result><strong>{result.name} · {result.day}</strong><p>已完成 {result.done} 項 · 待完成 {result.pending} 項</p>{result.tasks.map(t=><p key={t.task_id}>{t.name} · {t.label} · {t.state==='done'?'已完成':t.state==='in_progress'?'執行中':'待完成'}{t.result?' · '+t.result:''}{t.note?' · '+t.note:''}</p>)}{result.issues.length>0&&<><h3>未結案異常</h3>{result.issues.map(i=><p key={i.task_id}>{i.name}：{i.note}</p>)}</>}</Result>}
 </Fold>
}
export function StaffHandover({staffId,day,tasks}:{staffId?:number;day:string;tasks:WeeklyTask[]}){
 const list=tasks.filter(t=>t.day===day&&t.state!=='cancelled');
 return <section className="space-y-2"><div className="panel space-y-2"><h2>當日工作交接</h2><p>已完成 {list.filter(t=>t.state==='done').length} 項 · 待完成 {list.filter(t=>['pending','in_progress'].includes(t.state)).length} 項</p>{list.filter(t=>t.issue&&!t.issue.resolved_at).map(t=><p key={t.task_id}>{t.animal_name} · {t.label} · 異常待處理</p>)}</div><HandoverPanel staffId={staffId} day={day} personal/></section>
}
