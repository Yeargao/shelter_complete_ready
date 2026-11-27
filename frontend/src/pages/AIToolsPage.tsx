import {useEffect,useRef,useState} from 'react';
import {Link,useSearchParams} from 'react-router-dom';
import {api,type PhotoMatch} from '../services/api';
import './AIToolsPage.css';

const tabs=[['quality','資料品質'],['photos','照片比對']] as const;
const message=(e:unknown)=>e instanceof Error?e.message:String(e);
const methods:Record<string,string>={clip_embedding:'CLIP 影像 Embedding',visual_signature:'感知雜湊與色彩特徵'};
function Warning({text}:{text:string|null|undefined}){return text?<p className="ai-warning" role="status">{text}</p>:null;}
function ErrorText({text}:{text:string}){return text?<p className="ai-error" role="alert">{text}</p>:null;}

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

export default function AIToolsPage(){
 const [params,setParams]=useSearchParams();
 const tab=tabs.find(t=>t[0]===params.get('tab'))?.[0]??'quality';
 return <section className="ai-page space-y-4"><header><h1>AI 智慧工具</h1><p className="muted">使用現有收容所資料；AI 只提供候選與決策支援。</p></header>
  <nav className="ai-tabs" aria-label="AI 功能">{tabs.map(([id,label])=><button key={id} type="button" className={tab===id?'':'secondary'} aria-pressed={tab===id} onClick={()=>setParams({tab:id})}>{label}</button>)}</nav>
  {tab==='quality'&&<Quality/>}{tab==='photos'&&<Photos/>}
 </section>;
}
