import {RecommendationPanel,QualityPanel,PhotoComparison} from '../components/common/SmartPanels';
import {useState} from 'react';
import {Link,useParams,useLocation} from 'react-router-dom';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import AnimalForm from '../components/animals/AnimalForm';
import {api} from '../services/api';
import {ErrorView,Loading} from '../components/common/States';
import type {Animal,AnimalInput} from '../types';
const tri=(v:string)=>({yes:'已完成',no:'未完成',unknown:'待確認'}[v]||v);
const healthLabel=(v:string)=>({healthy:'健康',needs_review:'健康狀態待確認',serious:'嚴重狀況',unknown:'未註明',sick:'生病',injured:'受傷'}[v]||v);
export default function AnimalDetail(){
 const manager=(()=>{try{return JSON.parse(sessionStorage.getItem('shelter_session')||'null')?.role==='manager'}catch{return false}})();
 const location=useLocation();
 const returnTo=typeof location.state?.returnTo==='string'&&/^\/animals(?:\?|$)/.test(location.state.returnTo)?location.state.returnTo:'/animals';
 const id=Number(useParams().id),client=useQueryClient(),[editing,setEditing]=useState(false);
 const animal=useQuery({queryKey:['animal',id],queryFn:()=>api.animal(id),enabled:Number.isInteger(id)});
 const healthTasks=useQuery({queryKey:['tasks'],queryFn:api.tasks,enabled:manager});
 const save=useMutation({mutationFn:(a:AnimalInput)=>api.update(id,a),onSuccess:async()=>{setEditing(false);await Promise.all([client.invalidateQueries({queryKey:['animal',id]}),client.invalidateQueries({queryKey:['animals']}),client.invalidateQueries({queryKey:['health']}),client.invalidateQueries({queryKey:['summary']})]);}});
 if(animal.isLoading)return <Loading/>;if(animal.error)return <ErrorView error={animal.error}/>;if(!animal.data)return null;
 const a=animal.data as Animal;
 const tasks=[['serious','sick','injured'].includes(a.health_status)?'優先確認健康狀況':a.health_status!=='healthy'?'健康狀態待確認':null,a.vaccinated!=='yes'?'確認疫苗紀錄':null,a.dewormed!=='yes'?'確認驅蟲紀錄':null,a.sterilized!=='yes'?'評估絕育安排':null].filter(Boolean);
 const input:AnimalInput={name:a.name,species:a.species,breed:a.breed,age_months:a.age_months,sex:a.sex,health_status:a.health_status,vaccinated:a.vaccinated,sterilized:a.sterilized,dewormed:a.dewormed,intake_date:a.intake_date,photo_url:a.photo_url};
 return <section className="space-y-5">
 <div className="flex justify-between items-center"><Link to={returnTo}>← 返回動物列表</Link>{manager&&<button onClick={()=>setEditing(!editing)}>{editing?'關閉編輯':'修改資料'}</button>}</div>
 <div className="panel space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="eyebrow">ANIMAL PROFILE · #{a.id}</div><h1>{a.species==='dog'?'🐕':a.species==='cat'?'🐈':'🐾'} {a.name}</h1><p className="muted">{a.breed||'品種未填'} · {a.sex==='male'?'雄性':a.sex==='female'?'雌性':'性別未知'} · {a.age_months??'—'} 個月</p></div><span className="status !text-lg !px-5 !py-3 !font-bold !rounded-xl shadow-sm" style={['serious','sick','injured'].includes(a.health_status)?{color:'#b91c1c',background:'#fee2e2'}:a.health_status!=='healthy'?{color:'#92400e',background:'#fef3c7'}:{}}>{healthLabel(a.health_status)}</span></div>
 {a.photo_url&&<img className="ux-profile-photo" src={a.photo_url} alt={a.name}/>}
 {manager&&<Link className="action-link" to={`/resources?animal=${a.id}`}>建立照護任務</Link>}
 <div className="grid md:grid-cols-3 gap-3">{[['入所日期',a.intake_date],['已停留',`${a.stay_days??'—'} 天`],['動物編號',`#${a.id}`],['疫苗',tri(a.vaccinated)],['驅蟲',tri(a.dewormed)],['絕育',tri(a.sterilized)]].map(([k,v])=><div className="rounded-xl bg-slate-50 p-4" key={k}><div className="muted text-sm">{k}</div><strong>{v}</strong></div>)}</div>
 </div>
 {manager&&editing&&<AnimalForm initial={input} photoCacheId={'detail:'+id} animalId={id} onSubmit={async v=>{await save.mutateAsync(v)}}/>}{save.error&&<ErrorView error={save.error}/>}
 <div className="panel space-y-3"><h2>需要注意的事項</h2>{tasks.length? <div className="grid md:grid-cols-2 gap-2">{tasks.map(t=><div className="rounded-xl border border-amber-200 bg-amber-50 p-3" key={t}>{t}</div>)}</div>:<p className="muted">目前沒有依登錄資料產生的待辦事項。</p>}</div>
 {manager&&<div className="panel space-y-3"><h2>健康行政核對</h2><div className="grid md:grid-cols-2 gap-2">{(healthTasks.data||[]).filter(t=>t.animal_id===id).map(t=><div key={t.id} className="rounded-xl bg-slate-50 p-3">{t.label} · {t.state==='done'?'已完成':'待處理'}</div>)}</div>{!healthTasks.data?.some(t=>t.animal_id===id)&&<p className="muted">目前沒有待核對工作。</p>}</div>}
 {manager&&<><RecommendationPanel key={'r'+id} animalId={id}/><QualityPanel key={'q'+id} animalId={id}/>{!editing&&<PhotoComparison key={'p'+id} cacheId={'detail:'+id} currentPhoto={a.photo_url} animalId={id}/>}</>}
 </section>;
}
