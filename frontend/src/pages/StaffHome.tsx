import React from 'react';
import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {api} from '../services/api';
import DailyTimeline, {type TimelineTask} from '../components/common/DailyTimeline';
import './StaffHome.css';
export default function StaffHome({userId}:{userId:number}){
 const client=useQueryClient();
 const staff=useQuery({queryKey:['staff',1],queryFn:()=>api.staff(1)});
 const plan=useQuery({queryKey:['staffAssignments',userId],queryFn:api.staffAssignments,refetchInterval:5000});
 const [selectedTaskId,setSelectedTaskId]=React.useState<string|null>(null);
 const [choice,setChoice]=React.useState('');
 const [resolved,setResolved]=React.useState('');
 const [note,setNote]=React.useState('');
 const [administeredDate,setAdministeredDate]=React.useState(new Date().toISOString().slice(0,10));
 const [states,setStates]=React.useState<Record<string,string>>({});
 React.useEffect(()=>{setStates({})},[plan.dataUpdatedAt]);
 const change=useMutation({mutationFn:api.setTask,onSuccess:(_r,v)=>{
  setStates(old=>({...old,[`${v.animal_id}:${v.label}`]:v.state}));
  setSelectedTaskId(null);setChoice('');setResolved('');setNote('');setAdministeredDate(new Date().toISOString().slice(0,10));
  client.invalidateQueries({queryKey:['tasks']});client.invalidateQueries({queryKey:['staffAssignments']});client.invalidateQueries({queryKey:['staff-assignments']});client.invalidateQueries({queryKey:['animals']});
  if(typeof BroadcastChannel!=='undefined'){const channel=new BroadcastChannel('shelter-task-events');channel.postMessage({type:'task-updated'});channel.close();}
 }});
 const worker=staff.data?.[userId-2];
 const assignments=(plan.data?.assignments||[]).filter(a=>a.staff_id===worker?.id);
 const start=plan.data?.planning_start||'';
 const stateOf=(a:typeof assignments[number])=>states[`${a.animal_id}:${a.label}`]||a.state;
 const activeTask=assignments.find(a=>a.task_id===selectedTaskId);
 const active=activeTask?`${activeTask.animal_id}:${activeTask.label}`:null;
 const item=(a:typeof assignments[number])=>{
  const done=stateOf(a)==='done',urgent=a.label.includes('優先確認健康狀況');
  const isHealth=a.label==='健康狀態待確認';
  const key=`${a.animal_id}:${a.label}`;
  return <div className="staff-inline-report space-y-2">
   {(active===key&&!done||done&&selectedTaskId===a.task_id)&&<>
   {done&&<p>✓ 已完成 · 已儲存的回報{a.note?.trim()?` · 備註：${a.note}`:''}</p>}
   {!urgent&&<><p>{isHealth?'請選擇健康狀況':a.label.includes('疫苗')?'是否已注射疫苗？':a.label.includes('驅蟲')?'是否已驅蟲？':a.label==='評估絕育安排'?'是否已絕育？':'請回報此項工作結果'}</p>
    <select value={choice} disabled={done} onChange={e=>setChoice(e.target.value)}><option value="">請選擇</option>{(isHealth?[['healthy','健康'],['sick','生病'],['injured','受傷']]:[['yes','是'],['no','否']]).map(([v,t])=><option value={v} key={v}>{t}</option>)}</select>
   </>}
   {a.label.includes('疫苗')&&choice==='yes'&&<label className="block">實際施打日期<input type="date" value={administeredDate} disabled={done} onChange={e=>setAdministeredDate(e.target.value)}/></label>}
   {urgent&&<label className="block">健康問題是否解決？<select value={resolved} disabled={done} onChange={e=>setResolved(e.target.value)}><option value="">請選擇</option><option value="yes">是</option><option value="no">否</option></select></label>}
   <label className="block">{urgent&&resolved==='no'?'未解決原因與後續處理紀錄（必填）':'備註（選填）'}<textarea className="w-full" value={note} onChange={e=>setNote(e.target.value)} /></label>
   {done&&<p className="muted">已完成的判定結果與醫療施打日期不可直接改寫；此處可更新備註，不會重複完成任務。</p>}
   {change.error&&<p className="text-red-700">回報失敗：{String(change.error)}</p>}
   <div className="staff-report-actions" data-three={done}>
    <button type="button" disabled={(!done&&!urgent&&!choice)||(!done&&urgent&&(!resolved||(resolved==='no'&&!note.trim())))||change.isPending} onClick={()=>change.mutate({animal_id:a.animal_id,label:a.label,state:'done',result:urgent?undefined:choice as 'healthy'|'sick'|'injured'|'yes'|'no',resolved:urgent?resolved as 'yes'|'no':undefined,note,administered_date:a.label.includes('疫苗')&&choice==='yes'?administeredDate:undefined,edit_report:done})}>{done?'儲存修改':'確認送出'}</button>
    <button type="button" className="secondary" onClick={()=>setSelectedTaskId(null)}>關閉</button>
    {done&&<button type="button" className="secondary" disabled={change.isPending} onClick={()=>change.mutate({animal_id:a.animal_id,label:a.label,state:'pending'})}>取消完成</button>}
   </div>
   </>}
  </div>;
 };
 const todayAssignments=assignments.filter(a=>a.date===start).map(a=>({...a,state:stateOf(a)})).sort((a,b)=>String(a.start_time||'').localeCompare(String(b.start_time||'')));
 const conflictingIntervals=todayAssignments.some((a,i)=>a.start_time&&a.end_time&&todayAssignments.some((b,j)=>j!==i&&b.start_time&&b.end_time&&a.start_time!<b.end_time!&&b.start_time!<a.end_time!));
 const openTask=(task:TimelineTask)=>{
  const a=todayAssignments.find(entry=>entry.task_id===task.task_id);
  if(!a)return;
  if(selectedTaskId===a.task_id){setSelectedTaskId(null);return;}
  setSelectedTaskId(a.task_id);setChoice(a.result||'');setResolved(a.resolved||'');setNote(a.note||'');setAdministeredDate(a.administered_date||new Date().toISOString().slice(0,10));
 };
 return <section className="space-y-5 staff-workspace"><div className="hero"><h1>照護人員工作台</h1><p>登入編號 {String(userId).padStart(2,'0')} · {worker?.name||'待指定員工'}。</p></div><div className="panel space-y-3"><h2>個人單日時間表</h2><p className="muted">{start} · {plan.data?.note||'載入派工中…'}</p>{change.error&&<p className="text-red-700">回報失敗：{String(change.error)}</p>}{plan.error&&<p className="text-red-700">讀取失敗：{String(plan.error)}</p>}{conflictingIntervals&&<p role="alert" className="text-red-700">警告：同一員工有時間重疊的展示紀錄，請管理者核對派工與資料來源；本頁只調整呈現，不修改排程。</p>}<DailyTimeline tasks={todayAssignments} shiftStart={worker?.shift_start} shiftEnd={worker?.shift_end} breakStart={worker?.break_start} breakEnd={worker?.break_end} expandedTaskId={selectedTaskId} renderTaskDetails={task=>{const original=todayAssignments.find(a=>a.task_id===task.task_id);return original?item(original):null}} onTaskClick={openTask}/></div></section>;
}
