import {useEffect,useRef,useState} from 'react';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {ResponsiveContainer,LineChart,Line,XAxis,YAxis,CartesianGrid,Tooltip,Legend} from 'recharts';
import {api,type Staff} from '../services/api';
import {ErrorView,Loading} from '../components/common/States';
import DailyTimeline,{priorityColor} from '../components/common/DailyTimeline';
import {displayTaskLabel,reportText} from '../components/common/taskPresentation';
import {visibleAssignments} from '../components/common/assignmentPresentation';
import './ResourceBoard.css';

type Assignment={task_id:string;animal_id:number;animal_name:string;staff_id:number|null;staff_name:string|null;category:string;label:string;date:string|null;hours:number;state:string;start_time?:string|null;end_time?:string|null;is_new?:boolean;source?:string;due_date?:string|null;note?:string;result?:string|null;resolved?:string|null;answer?:string|null;priority?:number;eligible_staff_ids?:number[]};
const EDITABLE_SKILLS=[
 {value:'health:observation',label:'健康觀察（健康狀態待確認、基礎驅蟲）'},
 {value:'health:veterinary',label:'獸醫醫療（傷病治療、健康問題追蹤、疫苗施打）'},
 {value:'admin:records',label:'行政紀錄（疫苗紀錄、絕育安排）'},
 {value:'adoption:followup',label:'送養追蹤'},
] as const;

export default function ResourcePage(){
 const qc=useQueryClient();
 const profiles=useQuery({queryKey:['profiles'],queryFn:api.profiles});
 const staff=useQuery({queryKey:['staff',1],queryFn:()=>api.staff(1)});
 const needs=useQuery({queryKey:['needs-forecast',30],queryFn:()=>api.needsForecast(30)});
 const animals=useQuery({queryKey:['animal-needs'],queryFn:api.animalNeeds});
 const assignments=useQuery({queryKey:['staff-assignments'],queryFn:api.staffAssignments,refetchInterval:1000});
 const occupancy=useQuery({queryKey:['forecast',30],queryFn:()=>api.forecast(30)});
 const [tab,setTab]=useState<'all'|'unassigned'|'assigned'|'done'|'new'>('all');
 const [query,setQuery]=useState('');const [activeWorker,setActiveWorker]=useState<number|null>(null);
 const [assignedStaffFilter,setAssignedStaffFilter]=useState('all');
 const calendarRef=useRef<HTMLElement|null>(null);
 const workloadRef=useRef<HTMLDivElement|null>(null);
 const [arrowTop,setArrowTop]=useState(92);
 const [selected,setSelected]=useState<string[]>([]);
 const [batchWorker,setBatchWorker]=useState('');
 const [editableTask,setEditableTask]=useState<string|null>(null);
 const [targetWorker,setTargetWorker]=useState<Record<string,string>>({});
 const [editingStaff,setEditingStaff]=useState<Staff|null>(null);
 const saveStaff=useMutation({mutationFn:(w:Staff)=>api.updateStaff(w.id,w),onSuccess:async()=>{setEditingStaff(null);await Promise.all([qc.invalidateQueries({queryKey:['staff']}),qc.invalidateQueries({queryKey:['staff-assignments']})])}});
 const optimize=useMutation({mutationFn:()=>{const p=profiles.data?.[0];if(!p)throw Error('沒有收容所設定');return api.resources({...p,profile_id:p.id,forecast:occupancy.data?.forecast||[]})},onSuccess:async()=>{await qc.invalidateQueries({queryKey:['staff-assignments']});await qc.invalidateQueries({queryKey:['tasks']})}});
 const reassign=useMutation({mutationFn:({ids,staffId}:{ids:string[];staffId:number})=>ids.length===1?api.reassign(ids[0],staffId):api.batchReassign(ids,staffId),onSuccess:async()=>{setSelected([]);setEditableTask(null);setTargetWorker({});await Promise.all([qc.invalidateQueries({queryKey:['staff-assignments']}),qc.invalidateQueries({queryKey:['staffAssignments']})])}});
 const optimizedOnOpen=useRef(false);
 useEffect(()=>{
  // Instant cross-tab update for employee reports, plus 1s polling for other devices.
  if(typeof BroadcastChannel==='undefined')return;
  const channel=new BroadcastChannel('shelter-task-events');
  channel.onmessage=()=>{void qc.invalidateQueries({queryKey:['staff-assignments']});void qc.invalidateQueries({queryKey:['tasks']});};
  return ()=>channel.close();
 },[qc]);
 useEffect(()=>{
  if(optimizedOnOpen.current||!profiles.isSuccess||!assignments.isSuccess||!occupancy.isSuccess)return;
  // Explicit demo reset keeps the schedule empty until the manager requests optimization.
  // Viewing an already scheduled workday must not silently rerun allocation.
  if(assignments.data?.reset_mode||assignments.data?.assignments?.some(t=>t.staff_id!=null&&t.date===assignments.data?.planning_start)){optimizedOnOpen.current=true;return;}
  optimizedOnOpen.current=true;
  // One optimization request on opening the page, never on assignment updates.
  optimize.mutate();
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[profiles.isSuccess,assignments.isSuccess,occupancy.isSuccess]);
 useEffect(()=>{
  const calendar=calendarRef.current;
  const container=workloadRef.current;
  const targetId=activeWorker??staff.data?.[0]?.id;
  if(!calendar||!container||targetId==null)return;
  const item=Array.from(container.querySelectorAll<HTMLElement>('[data-worker-id]'))
       .find(node=>node.dataset.workerId===String(targetId));
  if(!item)return;
  const update=()=>{
   const box=calendar.getBoundingClientRect();
   const target=item.getBoundingClientRect();
   const center=target.top+target.height/2-box.top;
   setArrowTop(Math.min(Math.max(center,20),box.height-20));
  };
  update();
  window.addEventListener('resize',update);
  container.addEventListener('scroll',update,{passive:true});
  return ()=>{window.removeEventListener('resize',update);container.removeEventListener('scroll',update)};
 },[activeWorker,staff.data]);
 const list=visibleAssignments((assignments.data?.assignments||[]) as Assignment[]);
 const priority=(t:Assignment)=>t.priority??((t.label.includes('優先')||t.label==='優先確認健康狀況')?0:t.due_date&&t.due_date<(assignments.data?.planning_start||'')?1:t.due_date===assignments.data?.planning_start?2:t.category==='health'?3:4);
 const taskSort=(a:Assignment,b:Assignment)=>String(a.date||a.due_date||'9999').localeCompare(String(b.date||b.due_date||'9999'))||priority(a)-priority(b)||a.animal_id-b.animal_id||a.task_id.localeCompare(b.task_id);
 // `is_new` also exists on rule-created confirmations; only report-derived follow-ups belong in 新增任務.
 const assignedCountByWorker=new Map<number,number>();
 list.forEach(t=>{if(t.staff_id!=null&&t.state!=='done')assignedCountByWorker.set(t.staff_id,(assignedCountByWorker.get(t.staff_id)||0)+1)});
 const assignedSort=(a:Assignment,b:Assignment)=>String(a.staff_name||staff.data?.find(w=>w.id===a.staff_id)?.name||'').localeCompare(String(b.staff_name||staff.data?.find(w=>w.id===b.staff_id)?.name||''),'zh-Hant')||String(a.date||'').localeCompare(String(b.date||''))||String(a.start_time||'99:99').localeCompare(String(b.start_time||'99:99'))||String(a.end_time||'99:99').localeCompare(String(b.end_time||'99:99'))||a.task_id.localeCompare(b.task_id);
 const healthReports=new Set(((assignments.data?.assignments||[]) as Assignment[])
  .filter(t=>t.label==='健康狀態待確認'&&t.state==='done'&&(t.result==='sick'||t.result==='injured'))
  .map(t=>t.animal_id));
 const isNewFollowUp=(t:Assignment)=>Boolean(t.is_new)&&(
  t.source==='employee_report'||(t.label==='優先確認健康狀況'&&healthReports.has(t.animal_id))
 );
 const inNewQueue=(t:Assignment)=>isNewFollowUp(t)&&t.staff_id==null&&t.state!=='done';
 const visible=list.filter(t=>(tab==='all'||tab==='new'&&inNewQueue(t)||tab==='done'&&t.state==='done'||tab==='unassigned'&&t.staff_id==null&&t.state!=='done'||tab==='assigned'&&t.staff_id!=null&&t.state!=='done'&&(assignedStaffFilter==='all'||String(t.staff_id)===assignedStaffFilter))&&`${t.animal_name} ${t.label} ${t.animal_id}`.toLowerCase().includes(query.toLowerCase())).sort(tab==='assigned'?assignedSort:taskSort);
 const count=(k:string)=>list.filter(t=>k==='new'?inNewQueue(t):k==='unassigned'?t.staff_id==null&&t.state!=='done':k==='assigned'?t.staff_id!=null&&t.state!=='done':t.state==='done').length;
 const pendingHealthConfirm=list.filter(t=>t.label==='健康狀態待確認'&&t.staff_id==null&&t.state!=='done').length;
 const workers=staff.data||[];
 const focusedWorker=workers.find(w=>w.id===activeWorker)||workers[0];
 const available=(w:typeof workers[number])=>Math.max(0,w.available_hours-w.scheduled_hours);
 // Both the pool and the timeline use the same visible task records.
 const workDate=assignments.data?.planning_start||'';
 const dayAssignments=list.filter(t=>t.date===workDate);
 // Count raw schedule rows rather than the task pool's deduplicated display items.
 const workloadAssignments=Array.from(new Map(((assignments.data?.assignments||[]) as Assignment[])
  .filter(t=>t.date===workDate&&t.staff_id!=null).map(t=>[t.task_id,t] as const)).values());
 const assignedHours=(id:number)=>workloadAssignments.filter(t=>t.staff_id===id).reduce((sum,t)=>sum+Number(t.hours||0),0);

 const resultText=(t:Assignment)=>t.result==='no'?(t.label.includes('驅蟲')?'未驅蟲':t.label.includes('疫苗')?'未施打疫苗':'否'):t.result==='yes'?(t.label.includes('驅蟲')?'已驅蟲':t.label.includes('疫苗')?'已注射疫苗':'是'):t.result==='sick'?'生病':t.result==='injured'?'受傷':t.result==='healthy'?'健康':t.answer||t.note?.trim()||'待確認';
 const toggleTask=(id:string,checked:boolean)=>setSelected(old=>checked?[...new Set([...old,id])]:old.filter(x=>x!==id));
 const taskRow=(t:Assignment)=> <div key={t.task_id} className={`resource-task-row ${t.state==='done'?'resource-task-row--done':`resource-task-row--${priorityColor(t)}`} ${tab==='assigned'?'resource-task-row--assigned':''}`}>
  {t.state!=='done'&&<input type="checkbox" aria-label={`選取 ${t.label}`} checked={selected.includes(t.task_id)} onChange={e=>toggleTask(t.task_id,e.target.checked)}/>}
  <span className={`priority-dot priority-dot--${priorityColor(t)}`}/>
  <div className={`resource-task-title resource-task-title--${priorityColor(t)}`}><strong><span className="resource-task-name">{displayTaskLabel(t.label)}</span><span className="resource-task-identity"> · {t.animal_name} #{t.animal_id}</span></strong><small>{t.due_date||'待確認日期'}{(t.state==='done'||t.is_new)&&(t.result||t.answer||t.note)?<> · 員工回報：<span className={t.result==='no'||t.resolved==='no'?'resource-negative':''}>{t.resolved?reportText(t.result,t.resolved):t.result?reportText(t.result):t.answer||'—'}</span></>:null}{t.note?` · 備註：${t.note}`:''} · {t.hours}h{t.start_time&&t.end_time?` · ${t.start_time}–${t.end_time}`:''}</small></div>
  {t.state==='done'?<div className="resource-task-done"><b>已完成 · {t.staff_name||'未指定'}</b></div>:<div className="resource-assignment-control"><select aria-label={`選擇 ${t.label} 指派對象`} value={editableTask===t.task_id?(targetWorker[t.task_id]??String(t.staff_id??0)):String(t.staff_id??0)} disabled={editableTask!==t.task_id||reassign.isPending} onChange={e=>setTargetWorker(old=>({...old,[t.task_id]:e.target.value}))}><option value="0">未指派</option>{workers.filter(w=>w.id===t.staff_id||(t.eligible_staff_ids?.includes(w.id)??false)).map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select><button type="button" className="resource-assign-button" disabled={reassign.isPending} onClick={()=>{if(editableTask!==t.task_id){setEditableTask(t.task_id);setTargetWorker(old=>({...old,[t.task_id]:String(t.staff_id??0)}));return;}const staffId=Number(targetWorker[t.task_id]??t.staff_id??0);if(staffId!==Number(t.staff_id??0))reassign.mutate({ids:[t.task_id],staffId});else setEditableTask(null)}}>{editableTask===t.task_id?'確認':'指派'}</button></div>}
 </div>;
 return <section className="space-y-5">
  <div className="hero"><div className="eyebrow">RESOURCE CONTROL / WORKBENCH</div><h1>資源配置</h1><p>左側管理每日待辦，右側顯示員工單日時間表；保留 30 天需求推估。</p></div>
  {(profiles.isLoading||staff.isLoading||needs.isLoading||assignments.isLoading)&&<Loading/>}
  {[profiles.error,staff.error,needs.error,assignments.error,optimize.error,reassign.error].filter(Boolean).map((e,i)=><ErrorView key={i} error={e}/>)}
  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
   {[["待辦任務",list.length],["未派事項",count('unassigned')],["已分配",count('assigned')],["已完成",count('done')]].map(([label,value])=><div key={label} className="metric"><span>{label}</span><strong>{value}</strong></div>)}
  </div>
  <div className="resource-optimization-heading"><h2>⚡ OR-Tools 最佳化派工</h2><p className="muted">單日排程 · 15 分鐘精度 · 優先健康狀態確認（保留已鎖定任務）</p><button type="button" disabled={optimize.isPending||!profiles.data?.length} onClick={()=>{if(window.confirm('重新最佳化會重排今天尚未鎖定、尚未完成的任務；手動指派與已完成任務不會移動。確定繼續？'))optimize.mutate()}}>{optimize.isPending?'重新排程中…':'重新最佳化派工'}</button></div>
  {pendingHealthConfirm>0&&<p className="resource-high-priority-note" role="status">目前仍有 {pendingHealthConfirm} 項「健康狀態待確認」未指派。可按「重新最佳化派工」優先重新安排；若仍無法指派，請檢查員工技能、工時與已鎖定的工作。</p>}
  <div className="resource-board">
   <div className="panel resource-pool">
    <div className="resource-pool__header">
      <h2>今日任務池</h2>
      {selected.length>1?<div className="resource-batch" role="group" aria-label="批次指派"><strong>批次指派</strong><span>已選 {selected.length} 筆</span><select aria-label="批次選擇員工或移至未派" value={batchWorker} onChange={e=>setBatchWorker(e.target.value)}><option value="">選擇員工或操作</option>{workers.filter(w=>selected.every(id=>{const task=list.find(t=>t.task_id===id);return task?.eligible_staff_ids?.includes(w.id)??false})).map(w=><option key={w.id} value={w.id}>{w.name}</option>)}<option value="0">移至未派</option></select><button disabled={!batchWorker||reassign.isPending} onClick={()=>reassign.mutate({ids:selected,staffId:Number(batchWorker)})}>執行</button></div>:<input className="resource-search" placeholder="搜尋動物、任務、編號" value={query} onChange={e=>setQuery(e.target.value)}/>}
    </div>
    <div className="resource-tabs">{([['all','全部'],['unassigned','未指派'],['assigned','已指派'],['done','已完成'],['new','新增任務']] as const).map(([key,label])=><button type="button" key={key} className={tab===key?'resource-tab--active':''} onClick={()=>setTab(key)}>{label} ({key==='all'?list.length:count(key)})</button>)}</div>
    {tab==='assigned'&&<div className="resource-assigned-filter"><label htmlFor="assigned-staff-select">依員工篩選</label><select id="assigned-staff-select" value={assignedStaffFilter} onChange={e=>setAssignedStaffFilter(e.target.value)}><option value="all">全部員工 ({count('assigned')})</option>{[...assignedCountByWorker.keys()].sort((a,b)=>String(workers.find(w=>w.id===a)?.name||list.find(t=>t.staff_id===a)?.staff_name||'').localeCompare(String(workers.find(w=>w.id===b)?.name||list.find(t=>t.staff_id===b)?.staff_name||''),'zh-Hant')).map(id=><option key={id} value={String(id)}>{workers.find(w=>w.id===id)?.name||list.find(t=>t.staff_id===id)?.staff_name||`員工 #${id}`} ({assignedCountByWorker.get(id)})</option>)}</select></div>}
    <div className="resource-pool__scroll"><div className="resource-task-stack">{visible.map(taskRow)}</div>{!visible.length&&<p className="muted resource-no-tasks">此條件沒有工作。</p>}</div>
    <div className="resource-pool__footer">{tab==='assigned'?'員工 → 執行日期 → 開始時間':'日期 → 重要度 → 動物編碼 · 新任務預設未指派'}</div>
   </div>
   <section className="panel resource-calendar" ref={calendarRef} style={{"--resource-arrow-top":`${arrowTop}px`} as React.CSSProperties} aria-label="選定員工的時間表">
    <div className="resource-calendar__head"><h2>員工時間表</h2><span>{workDate}</span></div>
    {focusedWorker?<>
     <div className="resource-calendar__person"><strong>{focusedWorker.name}</strong><span>{focusedWorker.attending?'當日出勤':'未出勤'} · {assignedHours(focusedWorker.id).toFixed(2)}h / {available(focusedWorker).toFixed(2)}h 可派工時</span></div>
     <DailyTimeline key={focusedWorker.id} compact tasks={(assignments.data?.assignments||[]).filter(t=>t.date===workDate&&t.staff_id===focusedWorker.id)} shiftStart={focusedWorker.shift_start} shiftEnd={focusedWorker.shift_end} breakStart={focusedWorker.break_start} breakEnd={focusedWorker.break_end}/>
     <button type="button" className="secondary resource-calendar__edit" onClick={()=>setEditingStaff({...focusedWorker})}>編輯員工技能與工時</button>
    </>:<p className="muted">目前沒有員工資料。</p>}
   </section>
   <section className="resource-workload"><h2>員工負載</h2><div className="resource-workload__scroll" ref={workloadRef}>{workers.map(w=>{const workerTasks=workloadAssignments.filter(t=>t.staff_id===w.id),hours=assignedHours(w.id),used=w.scheduled_hours+hours,limit=w.available_hours,total=workerTasks.length,completed=workerTasks.filter(t=>t.state==='done').length,completedPercent=total?100*completed/total:0;return <button type="button" key={w.id} data-worker-id={w.id} className={`resource-worker ${focusedWorker?.id===w.id?'resource-worker--active':''}`} onClick={()=>setActiveWorker(w.id)}><span className="resource-worker__heading"><strong>{w.name}</strong><span>{focusedWorker?.id===w.id?'正在查看':'查看時間表'}</span></span><small>{w.skills.join('、')||'無技能資料'} · {w.attending?'出勤':'未出勤'}</small><span className="resource-worker__stats"><b>{used.toFixed(2)}h / {limit.toFixed(2)}h</b><span>{limit?Math.round(used/limit*100):0}%</span></span><span className={`resource-worker__progress ${!total?'resource-worker__progress--empty':''}`} aria-label={`已完成 ${completed} 項，未完成 ${total-completed} 項`}><span className="resource-worker__progress-done" style={{width:`${completedPercent}%`}}/>{total>0&&<span className="resource-worker__progress-pending" style={{width:`${100-completedPercent}%`}}/>}</span><span className="resource-worker__foot"><small>剩餘可派 {Math.max(0,available(w)-hours).toFixed(2)}h</small><b>工作完成 {completed}/{total}</b></span></button>})}{!workers.length&&<p className="muted">尚無員工</p>}</div></section>
  </div>
  {editingStaff&&<form className="panel space-y-3" onSubmit={e=>{e.preventDefault();saveStaff.mutate(editingStaff)}}><h2>編輯員工：{editingStaff.name}</h2><div className="grid md:grid-cols-3 gap-3"><label>每日可用工時<input type="number" min="0" step="0.25" value={editingStaff.available_hours} onChange={e=>setEditingStaff({...editingStaff,available_hours:Number(e.target.value)})}/></label><label>既有占用工時<input type="number" min="0" step="0.25" value={editingStaff.scheduled_hours} onChange={e=>setEditingStaff({...editingStaff,scheduled_hours:Number(e.target.value)})}/></label><label>每週工時上限<input type="number" min="0" step="0.25" value={editingStaff.weekly_hours} onChange={e=>setEditingStaff({...editingStaff,weekly_hours:Number(e.target.value)})}/></label></div><div className="grid md:grid-cols-4 gap-3"><label>上班時間<input type="time" step="900" value={editingStaff.shift_start} onChange={e=>setEditingStaff({...editingStaff,shift_start:e.target.value})}/></label><label>下班時間<input type="time" step="900" value={editingStaff.shift_end} onChange={e=>setEditingStaff({...editingStaff,shift_end:e.target.value})}/></label><label>休息開始<input type="time" step="900" value={editingStaff.break_start||''} onChange={e=>setEditingStaff({...editingStaff,break_start:e.target.value||null})}/></label><label>休息結束<input type="time" step="900" value={editingStaff.break_end||''} onChange={e=>setEditingStaff({...editingStaff,break_end:e.target.value||null})}/></label></div><fieldset className="resource-skill-editor"><legend>員工技能（可複選，影響派工資格）</legend><div className="resource-skill-options">{EDITABLE_SKILLS.map(skill=><label key={skill.value}><input type="checkbox" checked={editingStaff.skills.includes(skill.value)} onChange={e=>setEditingStaff({...editingStaff,skills:e.target.checked?[...editingStaff.skills,skill.value]:editingStaff.skills.filter(value=>value!==skill.value)})}/><span>{skill.label}</span></label>)}</div></fieldset><label className="flex gap-2 items-center"><input type="checkbox" className="!w-4 !h-4" checked={editingStaff.attending} onChange={e=>setEditingStaff({...editingStaff,attending:e.target.checked})}/>當日出勤</label><div className="flex gap-2"><button disabled={saveStaff.isPending}>儲存</button><button type="button" className="secondary" onClick={()=>setEditingStaff(null)}>取消</button></div>{saveStaff.error&&<ErrorView error={saveStaff.error}/>}</form>}
  <div className="panel space-y-4"><h2>未來 30 天飼料與基礎照護工時</h2>
   <div className="resource-forecast-grid"><div className="h-72"><ResponsiveContainer width="100%" height="100%"><LineChart data={needs.data?.forecast||[]}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="date" minTickGap={30}/><YAxis/><Tooltip/><Legend/><Line dataKey="expected_food_kg" name="每日飼料 kg" stroke="#0f766e" dot={false}/><Line dataKey="food_lower_kg" name="飼料情境下界 kg" stroke="#5eead4" dot={false} strokeDasharray="4 4"/><Line dataKey="food_upper_kg" name="飼料情境上界 kg" stroke="#5eead4" dot={false} strokeDasharray="4 4"/></LineChart></ResponsiveContainer></div>
   <div className="h-72"><ResponsiveContainer width="100%" height="100%"><LineChart data={needs.data?.forecast||[]}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="date" minTickGap={30}/><YAxis/><Tooltip/><Legend/><Line dataKey="expected_care_hours" name="每日照護 h" stroke="#2563eb" dot={false}/><Line dataKey="care_lower_hours" name="工時情境下界 h" stroke="#93c5fd" dot={false} strokeDasharray="4 4"/><Line dataKey="care_upper_hours" name="工時情境上界 h" stroke="#93c5fd" dot={false} strokeDasharray="4 4"/></LineChart></ResponsiveContainer></div></div>
   <details><summary className="cursor-pointer font-semibold">預測說明與統計</summary><div className="space-y-3 mt-3">
    <p className="muted">{needs.data?.note||'依個體資料估算；等待後端資料。'}</p>
    <div className="grid md:grid-cols-3 gap-3">{[['個體估算筆數',`${needs.data?.estimated_animals??0} / ${needs.data?.animal_count??0}`],['目前每日飼料',`${needs.data?.daily_food_kg??'—'} kg`],['目前每日基礎照護',`${needs.data?.daily_care_hours??'—'} h`]].map(([a,b])=><div className="metric" key={a}><span>{a}</span><strong>{b}</strong></div>)}</div>
    <p className="muted">外推或訓練範圍稀疏：{needs.data?.extrapolated_or_sparse_animals??0} 隻；使用資源對照表補值：{needs.data?.imputed_animals??0} 隻。{needs.data?.warnings?.length?`需注意：${needs.data.warnings.join('；')}`:''}</p>
   </div></details>
   <details><summary className="cursor-pointer font-semibold">每隻動物的個別估算（{animals.data?.length||0} 隻）</summary><div className="max-h-96 overflow-auto mt-3"><table className="data-table"><thead><tr><th>動物</th><th>物種</th><th>飼料 g/日</th><th>基礎照護 h/日</th><th>資源來源</th><th>30天條件存活</th></tr></thead><tbody>{animals.data?.map(a=><tr key={a.id}><td>{a.name} #{a.id}</td><td>{a.species}</td><td>{a.food_grams_per_day??'尚未估算'}</td><td>{a.routine_care_hours_per_day??'尚未估算'}</td><td>{a.resource_source||'—'}</td><td>{(()=>{const p=needs.data?.individual_predictions?.find(p=>p.animal_id===a.id);return p?`${(p.conditional_survival_30d*100).toFixed(1)}%${p.tail_extrapolated?'（尾端外推）':''}`:'—'})()}</td></tr>)}</tbody></table></div></details>
  </div>
 </section>
}
