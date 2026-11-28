import {useEffect,useState} from 'react';
import {useQuery,useMutation} from '@tanstack/react-query';
import {api,type CarePhoto} from '../../services/api';

function Thumbnail({photo}:{photo:CarePhoto}){
 const [url,setUrl]=useState(''),[failed,setFailed]=useState(false);
 useEffect(()=>{let alive=true,object='';setFailed(false);setUrl('');
  api.taskPhoto(photo.task_id,photo.photo_id).then(blob=>{if(alive){object=URL.createObjectURL(blob);setUrl(object);}}).catch(()=>{if(alive)setFailed(true);});
  return()=>{alive=false;if(object)URL.revokeObjectURL(object);};
 },[photo.task_id,photo.photo_id]);
 return failed?<p className="muted">照片已無法讀取</p>:url?<img className="rounded-lg max-w-xs w-full" src={url} alt={photo.label+'回報照片'}/>:<p className="muted">載入照片…</p>;
}
export default function CarePhotoHistory({animalId,manager}:{animalId:number;manager:boolean}){
 const query=useQuery({queryKey:['animal-photos',animalId],queryFn:()=>api.animalPhotos(animalId)});
 const [previous,setPrevious]=useState(''),[current,setCurrent]=useState('');
 const compare=useMutation({mutationFn:()=>api.compareCarePhotos(animalId,previous,current)});
 const photos=query.data??[];
 return <section className="panel space-y-3"><h2>健康照片追蹤紀錄</h2>
  {query.isLoading&&<p>載入中…</p>}
  {query.error&&<p role="alert">{query.error.message}</p>}
  {!query.isLoading&&!query.error&&!photos.length&&<p className="muted">尚無可查看的回報照片</p>}
  {manager&&photos.length>=2&&<div className="space-y-2">
   <label>較早照片<select value={previous} disabled={compare.isPending} onChange={e=>{setPrevious(e.target.value);compare.reset();}}><option value="">請選擇</option>{photos.map((p,i)=><option key={p.photo_id} value={p.photo_id}>{p.uploaded_at.slice(0,16)} · {p.label} · #{i+1}</option>)}</select></label>
   <label>較新照片<select value={current} disabled={compare.isPending} onChange={e=>{setCurrent(e.target.value);compare.reset();}}><option value="">請選擇</option>{photos.map((p,i)=><option key={p.photo_id} value={p.photo_id}>{p.uploaded_at.slice(0,16)} · {p.label} · #{i+1}</option>)}</select></label>
   <button type="button" className="secondary" disabled={!previous||!current||previous===current||compare.isPending} onClick={()=>compare.mutate()}>{compare.isPending?'比較中…':'Gemini 比較外觀'}</button>
   {compare.error&&<p role="alert">{compare.error.message}</p>}
   {compare.data&&<p>AI 可見差異（非診斷）：{compare.data.observation}</p>}
  </div>}
  {photos.map(p=><article key={p.photo_id} className="rounded-lg border p-3 space-y-2"><strong>{p.uploaded_at.slice(0,16).replace('T',' ')} · {p.label}</strong><Thumbnail photo={p}/><p>{p.note||'無補充說明'}</p></article>)}
 </section>;
}
