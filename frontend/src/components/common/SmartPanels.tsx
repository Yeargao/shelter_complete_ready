import CameraCapture,{photoFile} from './CameraCapture';
import {displayTaskLabel} from './taskPresentation';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,type PhotoMatch} from '../../services/api';
import {taipeiToday} from './scheduleDates';
import {useStored,smartRequest,executeCommand,type Command,type Report} from './smartState';
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
 if(c.type==='rule'||c.type==='workflow')return <p>此功能已移除</p>;

 if(c.type==='task')return <p>建立任務：{c.name} #{c.animal_id} · {displayTaskLabel(c.label)} · {c.earliest} 至 {c.due}</p>;
 return null;
}
type Recommendation={animal_id:number;name:string;steps:{label:string;existing:boolean}[]};
export function RecommendationPanel({animalId}:{animalId:number}){
 const [result,setResult]=useStored<Recommendation|null>('recommend:'+animalId,null);
 const [completed,setCompleted]=useStored<Record<string,string>>('recommend-complete:'+animalId,{});
 const [dates,setDates]=useStored<Record<string,string>>('recommend-dates:'+animalId,{});
 const a=useActions();const qc=useQueryClient();
 return <Fold id={'recommend:'+animalId} title="照護流程建議" defaultOpen={true}>
  {a.button('get',result?'重新整理建議':'取得建議',async()=>{setResult(await smartRequest<Recommendation>('/recommend/'+animalId));setCompleted({})})}{a.error('get')}
  {result&&<div className="space-y-2">{result.steps.map(s=><Result key={s.label}><strong>{displayTaskLabel(s.label)}</strong>{s.existing||completed[s.label]?<button type="button" disabled>{completed[s.label]??'已有任務'}</button>:<div className="smart-inline"><label>日期<input type="date" min={taipeiToday()} value={dates[s.label]??taipeiToday()} onChange={e=>setDates(p=>({...p,[s.label]:e.target.value}))}/></label>{a.button(s.label,'確認新增任務',async()=>{const date=dates[s.label]??taipeiToday();const outcome=await executeCommand({type:'task',animal_id:animalId,name:result.name,label:s.label,earliest:date,due:date});setCompleted(p=>({...p,[s.label]:outcome}));await qc.invalidateQueries({queryKey:['schedule-week']});await qc.invalidateQueries({queryKey:['tasks']})},!(dates[s.label]??taipeiToday()))}</div>}{a.error(s.label)}</Result>)}{!result.steps.length&&<p>無待處理建議</p>}</div>}
 </Fold>
}
const consistencyKey=['consistency-audit'];
function useConsistency(){
 return useQuery({queryKey:consistencyKey,queryFn:()=>api.auditData('health'),refetchInterval:15000,staleTime:10000,refetchOnWindowFocus:true});
}
export function ConsistencySync(){
 const qc=useQueryClient();
 useConsistency();
 useEffect(()=>{
  const sync=()=>void qc.invalidateQueries({queryKey:consistencyKey});
  window.addEventListener('shelter-data-changed',sync);
  return()=>window.removeEventListener('shelter-data-changed',sync);
 },[qc]);
 return null;
}
export function QualityPanel({scope='all',animalId}:{scope?:'all'|'health'|'resources';animalId?:number}){
 const id='quality:'+scope+':'+(animalId??'all');
 const query=useConsistency();
 const [kind,setKind]=useStored(id+':filter','');
 const all=query.data?.findings.filter(r=>animalId===undefined||r.animal_id===animalId)??[];
 const findings=all.filter(r=>!kind||r.kind===kind);
 return <Fold id={id} title="資料一致性核對" defaultOpen={true}>
  {query.error&&<ErrorText text={message(query.error)}/>}
  {!query.data&&query.isPending&&<p>核對中…</p>}
  {query.data&&<><p>待核對 {all.length} 筆</p>{query.data.checked_at&&<small>最後核對：{new Date(query.data.checked_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}</small>}
   {all.length>0&&<label>類型<select value={kind} onChange={e=>setKind(e.target.value)}><option value="">全部</option>{Array.from(new Set(all.map(r=>r.kind))).map(k=><option key={k}>{k}</option>)}</select></label>}
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
 const a=useActions();
 useEffect(()=>{if(!file){setPreview('');return}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url)},[file]);
 const dataPhoto=currentPhoto?.startsWith('data:image/')&&currentPhoto.includes(';base64,')?currentPhoto.split(';base64,')[1]:null;
 const matches=result?.results.filter(r=>r.animal_id!==animalId)??[];
 return <details className={embedded?'md:col-span-2 smart-section space-y-3':'panel smart-section space-y-3'} open={open} onToggle={e=>{if(e.currentTarget.open!==open)setOpen(e.currentTarget.open)}}><summary>動物照片比對</summary>
  <div className="ai-form"><CameraCapture disabled={a.busy.compare} onPhoto={data=>{setFile(photoFile(data));setResult(null);setFilename('');}}/>
   {preview&&<img src={preview} className="ai-preview" alt="待比對照片"/>}
   {a.button('compare',result?'重新比對':'比對既有照片',async()=>{if(!file&&!dataPhoto)return;if(file&&file.size>15*1024*1024)throw Error('原始圖片最多 15 MB');const r=await api.comparePhotos(file?await encodePhoto(file):dataPhoto!);setResult(r);setFilename(file?.name??'目前動物照片')},!file&&!dataPhoto)}
   <button type="button" className="secondary" disabled={a.busy.compare||(!file&&!result)} onClick={()=>{setFile(undefined);setResult(null);setFilename('')}}>清除</button>
  </div>{a.error('compare')}
  {result&&<><p>{filename} · {result.mode==='clip_embedding'?'CLIP':'影像特徵'} · 比對 {result.processed} 張</p>{result.warning&&<p className="muted">{result.warning}</p>}{(result.skipped>0||result.remote_skipped>0)&&<small>無法讀取 {result.skipped} 張；外部網址略過 {result.remote_skipped} 張</small>}
   {matches.length===0?<p>無可比對結果</p>:<div className="ai-results">{matches.map(r=><Result key={r.animal_id}><div className="ai-photo-result"><Thumb item={r}/><div><Link to={'/animals/'+r.animal_id}>#{r.animal_id} {r.name}</Link><p>{r.is_active?'目前在所':'已離所'}</p><p>相似分數 {r.score.toFixed(3)}（非身分確認）</p></div></div></Result>)}</div>}
  </>}
 </details>
}
