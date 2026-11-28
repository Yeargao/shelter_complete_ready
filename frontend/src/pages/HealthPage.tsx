import {QualityPanel} from '../components/common/SmartPanels';
import {useStored} from '../components/common/smartState';
import {useState} from 'react';
import {Link} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {api} from '../services/api';
import {ErrorView,Loading} from '../components/common/States';
import {displayTaskLabel,healthGroupTitle,healthTaskLabels,reportText} from '../components/common/taskPresentation';
import './HealthPage.css';
export default function HealthPage(){
 const animals=useQuery({queryKey:['animals','health'],queryFn:()=>api.animals('','','',0,1000)});
 const tasks=useQuery({queryKey:['tasks'],queryFn:api.healthTasks});
 const [q,setQ]=useState('');
 const [openGroups,setOpenGroups]=useStored<Record<string,boolean>>('health-open-groups',{});
 const validIds=new Set((animals.data||[]).map(a=>a.id));
 const all=(tasks.data||[]).filter(t=>validIds.has(t.animal_id)&&`${t.animal_name} ${t.animal_id} ${displayTaskLabel(t.label)}`.toLowerCase().includes(q.trim().toLowerCase()));
 return <section className="space-y-5">
  <div className="hero"><h1>健康行政核對</h1></div>
  {(animals.isLoading||tasks.isLoading)&&<Loading/>}{animals.error&&<ErrorView error={animals.error}/ >}{tasks.error&&<ErrorView error={tasks.error}/ >}
  <input className="max-w-xs" aria-label="搜尋動物" placeholder="搜尋動物名稱、編碼或任務" value={q} onChange={e=>setQ(e.target.value)}/>
  <section className="panel space-y-3 health-admin-board"><h2 className="font-semibold text-lg">依待辦事項整理動物</h2>
   <div className="mt-3 space-y-3 health-admin-board__scroll">{healthTaskLabels.map(label=>{
    const group=all.filter(t=>t.label===label).sort((a,b)=>String(a.due_date||'9999').localeCompare(String(b.due_date||'9999'))||(a.priority??4)-(b.priority??4)||a.animal_id-b.animal_id);
    return <details key={label} open={!!openGroups[label]} onToggle={e=>{if(e.currentTarget.open!==!!openGroups[label])setOpenGroups(p=>({...p,[label]:e.currentTarget.open}))}} className="rounded-xl border border-slate-200 p-4"><summary className={`cursor-pointer font-semibold ${label==='優先確認健康狀況'?'text-red-700':label==='健康狀態待確認'?'text-orange-600':label==='健康問題追蹤'?'text-amber-600':''}`}>{healthGroupTitle(label)}（待辦 {group.filter(t=>t.state==='pending').length}／全部 {group.length}）</summary>
     <div className="mt-3 space-y-2">{group.map(t=><div key={t.id} className="weekly-task health-task" data-priority={t.label==='基礎驅蟲'?3:t.priority??4} data-done={t.state==='done'}>
       <Link to={`/animals/${t.animal_id}`} className="font-semibold"><span className="weekly-dot" aria-hidden="true"/>{t.animal_name} #{t.animal_id}</Link>
       <div className="text-sm text-slate-600">{t.state==='done'?'✓ 已完成':'待處理'} · {t.due_date||'待確認日期'}{t.state==='done'&&t.completed_at?` · 完成 ${t.completed_at.slice(0,10)}`:''}{t.state==='pending'&&t.due_date&&t.due_date<new Date().toISOString().slice(0,10)?' · 已逾期':''}{t.state==='done'&&(t.result||t.note)?` · 回報：${reportText(t.result)}`:''}{t.note?` · 備註：${t.note}`:''}</div>
      </div>)}{!group.length&&<p className="muted">目前沒有此類任務</p>}</div>
    </details>})}</div>
  </section>
  <QualityPanel scope="health"/>
 </section>;
}
