import {useEffect,useRef,useState,type FormEvent} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {useQueryClient} from '@tanstack/react-query';
import {api,type ComparisonPlan,type ScheduleStrategy,type PhotoMatch} from '../services/api';
import {taipeiToday} from '../components/common/scheduleDates';
import './AIToolsPage.css';

const tabs=[['search','語意搜尋'],['quality','資料品質'],['schedule','排程比較'],['photos','照片比對']] as const;
const strategies:{id:ScheduleStrategy;title:string;description:string}[]=[
 {id:'balanced',title:'工作量平衡',description:'維持原有排程目標，優先覆蓋任務，再平衡上午下午及日間工時。'},
 {id:'urgent',title:'緊急任務優先',description:'先最大化緊急與高優先任務指派，再考慮總覆蓋工時。'},
 {id:'retain',title:'最少異動',description:'維持任務覆蓋、優先級及期限後，優先保留原本指派。'},
];
const message=(e:unknown)=>e instanceof Error?e.message:String(e);
const methods:Record<string,string>={local_embedding:'本機 Embedding',gemini_embedding:'Gemini Embedding',local_lexical:'本機文字／同義詞比對',clip_embedding:'CLIP 影像 Embedding',visual_signature:'感知雜湊與色彩特徵'};
function Warning({text}:{text:string|null|undefined}){return text?<p className="ai-warning" role="status">{text}</p>:null;}
function ErrorText({text}:{text:string}){return text?<p className="ai-error" role="alert">{text}</p>:null;}

function Search(){
 const [query,setQuery]=useState(''),[open,setOpen]=useState(false);
 const [result,setResult]=useState<Awaited<ReturnType<typeof api.searchNotes>>>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function run(e:FormEvent){e.preventDefault();if(!query.trim()||busy)return;setBusy(true);setError('');setResult(undefined);
  try{setResult(await api.searchNotes(query.trim(),open));}catch(err){setError(message(err));}finally{setBusy(false);}
 }
 return <section className="panel ai-section">
  <h2>照護紀錄語意搜尋</h2><p className="muted">搜尋現有照護回報及異常備註。結果附原始紀錄，不產生新的健康事實。</p>
  <form onSubmit={run} className="ai-form">
   <label>搜尋描述<input required maxLength={300} value={query} onChange={e=>setQuery(e.target.value)} placeholder="例如：行動不便、食慾不佳"/></label>
   <label className="ai-check"><input type="checkbox" checked={open} onChange={e=>setOpen(e.target.checked)}/>僅未結案異常</label>
   <button disabled={busy||!query.trim()}>{busy?'搜尋中…':'搜尋紀錄'}</button>
  </form><ErrorText text={error}/>
  {result&&<><p className="ai-method">方式：{methods[result.mode]??result.mode} · 已比對 {result.searched} 筆（最近最多 {result.limit} 筆）</p><Warning text={result.warning}/>
   {result.results.length===0?<p>沒有找到符合條件的紀錄。</p>:<div className="ai-results">{result.results.map(r=><article key={r.task_id} className="ai-result">
    <div className="ai-result-heading"><Link to={'/animals/'+r.animal_id}>#{r.animal_id} {r.name}</Link><span className="status">{r.open_issue?'待處理異常':'照護紀錄'}</span></div>
    <p>{r.text}</p><small className="muted">{r.label} · {r.reported_at?.slice(0,10)??'日期未記錄'} · 相似分數 {r.score.toFixed(3)}</small>
    <small className="muted">來源：{r.task_id}</small>
   </article>)}</div>}
  </>}
 </section>;
}

function Quality(){
 const [result,setResult]=useState<Awaited<ReturnType<typeof api.auditData>>>(),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [kind,setKind]=useState('');
 async function run(){setBusy(true);setResult(undefined);setError('');setKind('');try{setResult(await api.auditData());}catch(err){setError(message(err));}finally{setBusy(false);}}
 const findings=result?.findings.filter(r=>!kind||r.kind===kind)??[];
 return <section className="panel ai-section">
  <h2>AI 資料品質核對</h2><p className="muted">檢查健康狀況、疫苗、驅蟲、日期及資源設定。模型異常是核對候選，不是錯誤定論。</p>
  <button disabled={busy} onClick={()=>void run()}>{busy?'核對中…':'掃描現有資料'}</button><ErrorText text={error}/>
  {result&&<><p className="ai-method">發現 {result.findings.length} 筆待核對項目 · Isolation Forest 已分析 {result.model_groups} 組</p><Warning text={result.warning}/><p className="muted">{result.note}</p>
   <label>依問題類型篩選<select value={kind} onChange={e=>setKind(e.target.value)}><option value="">全部</option>{Array.from(new Set(result.findings.map(r=>r.kind))).map(k=><option key={k}>{k}</option>)}</select></label>
   {findings.length===0?<p>沒有符合目前篩選條件的核對項目。</p>:<div className="ai-results">{findings.map((r,i)=><article className="ai-result" key={r.animal_id+':'+i}>
    <div className="ai-result-heading"><Link to={'/animals/'+r.animal_id}>#{r.animal_id} {r.name}</Link><span className="status">{r.kind}</span></div>
    <p>{r.detail}</p><small className="muted">來源：{r.source}</small>
   </article>)}</div>}
  </>}
 </section>;
}

function Schedule({initialDay}:{initialDay:string}){
 const qc=useQueryClient();
 const [day,setDay]=useState(initialDay),[plans,setPlans]=useState<ComparisonPlan[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [current,setCurrent]=useState(''),[selected,setSelected]=useState<ScheduleStrategy>();
 const [confirmed,setConfirmed]=useState(false);
 const comparable=plans.length>0&&plans.every(p=>p.revision===plans[0].revision);
 async function compare(){
  if(busy||day<taipeiToday())return;
  setBusy(true);setPlans([]);setError('');setNotice('');setSelected(undefined);setConfirmed(false);
  try{for(const strategy of strategies){setCurrent(strategy.title);const next=await api.previewStrategy(day,strategy.id);setPlans(old=>[...old,next]);}}
  catch(err){setError(message(err));}finally{setCurrent('');setBusy(false);}
 }
 async function apply(){
  const p=plans.find(item=>item.strategy===selected);
  if(!p?.plan_id||!confirmed||!comparable||plans.length!==strategies.length||busy)return;
  setBusy(true);setError('');setNotice('');
  try{await api.applyWeek(p.plan_id);setPlans([]);setSelected(undefined);setConfirmed(false);setNotice('已套用選擇的排程方案。');
   await Promise.all([qc.invalidateQueries({queryKey:['schedule-week']}),qc.invalidateQueries({queryKey:['resource-overview']})]);
  }catch(err){setError(message(err));setConfirmed(false);}finally{setBusy(false);}
 }
 const chosen=plans.find(p=>p.strategy===selected);
 return <section className="panel ai-section">
  <h2>七天排程方案比較</h2><p className="muted">使用現有 CP-SAT 求解器與三種目標。相同資料下比較真實求解結果；預覽不套用指派，固定任務及技能、工時等限制仍生效。</p>
  <div className="ai-form"><label>起始日期<input type="date" value={day} min={taipeiToday()} disabled={busy} onChange={e=>{setDay(e.target.value);setPlans([]);setSelected(undefined);setConfirmed(false);setNotice('');setError('');}}/></label>
   <button disabled={busy||!day||day<taipeiToday()} onClick={()=>void compare()}>{busy?'處理中…':'產生三種方案'}</button><Link to="/resources">返回資源配置</Link></div>
  {current&&<p role="status">正在求解：{current}（已完成 {plans.length}/3）</p>}<ErrorText text={error}/>{notice&&<p role="status">{notice}</p>}
  {plans.length>0&&<><div className="ai-plan-grid">{strategies.map(strategy=>{
    const p=plans.find(item=>item.strategy===strategy.id);const m=p?.metrics;
    return <article className="ai-result" key={strategy.id}><h3>{strategy.title}</h3><p className="muted">{strategy.description}</p>
     {p&&m?<><p className="status">{p.solver_status==='OPTIMAL'?'已證明最佳解':'可行解（未證明最佳）'}</p>
      <dl className="ai-metrics"><dt>已安排任務</dt><dd>{m.assigned}/{m.total}</dd><dt>緊急任務期限內安排</dt><dd>{m.urgent_on_time}/{m.urgent_total}</dd>
       <dt>逾期指派</dt><dd>{m.late}</dd><dt>原指派保留</dt><dd>{m.retained}/{m.original}</dd>
       <dt>異動任務數</dt><dd>{m.changed}</dd><dt>員工工時利用率差距</dt><dd>{m.utilization_spread===null?'不適用':m.utilization_spread+' 個百分點'}</dd></dl>
      <button type="button" className={selected===strategy.id?'':'secondary'} aria-pressed={selected===strategy.id} disabled={busy||!p.plan_id||!comparable||plans.length!==strategies.length} onClick={()=>{setSelected(strategy.id);setConfirmed(false)}}>選擇此方案</button>
     </>:<p className="muted">尚未完成求解</p>}</article>;
   })}</div>
   {!comparable&&<Warning text="求解期間資料已變動，三個方案不可直接比較。請重新產生。"/>}
   <p className="muted">工時利用率差距為有可用工時員工中最高與最低利用率之差；任務安排不等於實際完成。各目標可能得到相同方案。</p>
  </>}
  {chosen&&comparable&&<div className="ai-result"><h3>方案異動明細</h3>
   <div className="ai-change-list">{chosen.changes.length?chosen.changes.map(c=><p key={c.task_id}>{c.animal_name} · {c.label}：{c.adjustment_reason}</p>):<p>沒有指派異動。</p>}</div>
   <label className="ai-check"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>我已核對方案，確認套用</label>
   <button disabled={!confirmed||busy||!chosen.plan_id||plans.length!==strategies.length} onClick={()=>void apply()}>確認套用此方案</button>
  </div>}
 </section>;
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
function Photos(){
 const [file,setFile]=useState<File>(),[preview,setPreview]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [result,setResult]=useState<Awaited<ReturnType<typeof api.comparePhotos>>>();
 const input=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(!file){setPreview('');return}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url)},[file]);
 async function run(){if(!file||busy)return;setBusy(true);setError('');setResult(undefined);
  try{if(file.size>15*1024*1024)throw Error('原始圖片最多 15 MB');setResult(await api.comparePhotos(await encodePhoto(file)));}
  catch(e){setError(message(e));}finally{setBusy(false)}
 }
 return <section className="panel ai-section"><h2>動物照片比對</h2><p className="muted">上傳或拍攝動物照片，與系統內可讀取的既有動物及照護照片比對。相似分數不是同一動物的機率，請人工核對編號、晶片與紀錄。</p>
  <div className="ai-form"><label>選擇照片<input ref={input} type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e=>{setFile(e.target.files?.[0]);setResult(undefined);setError('')}}/></label>
   <label>手機拍照<input type="file" accept="image/*" capture="environment" disabled={busy} onChange={e=>{setFile(e.target.files?.[0]);setResult(undefined);setError('')}}/></label>
   {preview&&<img src={preview} className="ai-preview" alt="待比對照片"/>}
   <button disabled={!file||busy} onClick={()=>void run()}>{busy?'比對中…':'比對既有照片'}</button>
   <button className="secondary" disabled={busy||!file} onClick={()=>{setFile(undefined);setResult(undefined);setError('');if(input.current)input.current.value=''}}>清除</button>
  </div><ErrorText text={error}/>
  {result&&<><p className="ai-method">方式：{methods[result.mode]??result.mode} · 成功比對 {result.processed} 張 · 無法讀取 {result.skipped} 張 · 未抓取外部 URL {result.remote_skipped} 張（最多處理 {result.limit} 張）</p><Warning text={result.warning}/>
   {result.results.length===0?<p>沒有可讀取的既有照片，因此無法比對。此結果不表示沒有重複動物。</p>:<div className="ai-results">{result.results.map(r=><article className="ai-result" key={r.animal_id}>
    <div className="ai-photo-result"><Thumb item={r}/><div><Link to={'/animals/'+r.animal_id}>#{r.animal_id} {r.name}</Link><p>{r.is_active?'目前在所':'已離所'}</p><p>相似分數 {r.score.toFixed(3)}</p><small className="muted">{r.source==='task'?'照護回報照片':'動物建檔照片'}</small></div></div>
   </article>)}</div>}
  </>}
  <Link to="/animals/new">返回新增／重新入所</Link>
 </section>;
}

export default function AIToolsPage({manager}:{manager:boolean}){
 const [params,setParams]=useSearchParams();
 const visible=manager?tabs:tabs.slice(0,1);
 const tab=visible.find(t=>t[0]===params.get('tab'))?.[0]??'search';
 const initialDay=params.get('day')||taipeiToday();
 return <section className="ai-page space-y-4"><header><h1>AI 智慧工具</h1><p className="muted">使用現有收容所資料；AI 只提供候選與決策支援。</p></header>
  {manager&&<nav className="ai-tabs" aria-label="AI 功能">{visible.map(([id,label])=><button key={id} type="button" className={tab===id?'':'secondary'} aria-pressed={tab===id} onClick={()=>setParams({tab:id,...(id==='schedule'?{day:initialDay}:{})})}>{label}</button>)}</nav>}
  {tab==='search'&&<Search/>}{manager&&tab==='quality'&&<Quality/>}{manager&&tab==='schedule'&&<Schedule initialDay={initialDay}/>}
  {manager&&tab==='photos'&&<Photos/>}
 </section>;
}
