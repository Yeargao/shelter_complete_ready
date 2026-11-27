
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type Placement, type Plan, type Staff, type WeeklyShift, type WeeklyTask } from '../services/api';
import { ErrorView } from '../components/common/States';
import ScheduleCalendar, {priorityName} from '../components/common/ScheduleCalendar';
import { addDays, gridTime, lunchBreak, taipeiToday, timeGrid } from '../components/common/scheduleDates';
import TaskPhotos from '../components/common/TaskPhotos';
import {displayTaskLabel,healthTaskLabels} from '../components/common/taskPresentation';

const skills = [
 ['health:observation','健康觀察'],['health:veterinary','獸醫醫療'],
 ['admin:records','行政紀錄'],['adoption:followup','送養追蹤'],
];

export default function ResourcePage() {
 const qc = useQueryClient();
 const [day,setDay]=useState(taipeiToday);
 const [view,setView]=useState<'day'|'week'>('week');
 const [worker,setWorker]=useState<number>();
 const [search,setSearch]=useState('');
 const [poolTab,setPoolTab]=useState<'pending'|'derived'|'done'>('pending');
 const [eligibleOnly,setEligibleOnly]=useState(false);
 const [plan,setPlan]=useState<Plan>();
 const [selected,setSelected]=useState<WeeklyTask>();
 const [destination,setDestination]=useState({staff_id:0,day:'',start_time:'09:00',locked:true});
 const [shift,setShift]=useState<WeeklyShift>();
 const [staffSettings,setStaffSettings]=useState<Staff>();
 const [dragged,setDragged]=useState<WeeklyTask>();
 const dragTaskId=useRef<string>();
 const endDrag=()=>{dragTaskId.current=undefined;setDragged(undefined);};
 const [notice,setNotice]=useState('');
 const [dropIssue,setDropIssue]=useState('');
 const detailRef=useRef<HTMLElement>(null);
 useEffect(()=>{if(selected)detailRef.current?.focus();},[selected]);
 const week=useQuery({queryKey:['schedule-week',day],queryFn:()=>api.week(day),refetchInterval:dragged?false:15000,refetchOnWindowFocus:!dragged});
 const refresh=async()=>{setPlan(undefined);await qc.invalidateQueries({queryKey:['schedule-week']});await qc.invalidateQueries({queryKey:['resource-overview']});};
 const preview=useMutation({mutationFn:()=>api.previewWeek(day),onSuccess:setPlan});
 const apply=useMutation({mutationFn:api.applyWeek,onSuccess:refresh});
 const move=useMutation({mutationFn:({id,body}:{id:string;body:Parameters<typeof api.place>[1]})=>api.place(id,body),onSuccess:async()=>{setNotice('已儲存指派');setSelected(undefined);await refresh();}});
 const create=useMutation({mutationFn:api.createWeeklyTask,onSuccess:async()=>{setPoolTab('pending');await refresh();}});
 const resolve=useMutation({mutationFn:api.resolveIssue,onSuccess:async()=>{setSelected(undefined);await refresh();}});
 const event=useMutation({mutationFn:({id,date}:{id:string;date?:string})=>api.taskEvent(id,date?{event:'delay',earliest:date}:{event:'start'}),onSuccess:async()=>{setSelected(undefined);await refresh();}});
 const saveShift=useMutation({mutationFn:api.saveShift,onSuccess:refresh});
 const saveStaff=useMutation({mutationFn:(staff:Staff)=>api.updateStaff(staff.id,staff),
  onSuccess:async()=>{setStaffSettings(undefined);await refresh();}});
 const workers=week.data?.workers??[], tasks=week.data?.tasks??[], days=week.data?.days??[];
 const sid=worker??workers[0]?.id;
 const columns=view==='week'?days.map(date=>({day:date,sid,title:date.slice(5)})):workers.map(w=>({day,sid:w.id,title:w.name}));
 const ranges=week.data?.shifts??[];
 const historical=days.length>0&&days[days.length-1]<taipeiToday();
 const pool=tasks.filter(t=>!t.staff_id&&t.state==='pending'&&t.is_active&&[t.label,t.animal_name,t.animal_id].join(' ').toLowerCase().includes(search.replace('傷病治療','優先確認健康狀況').toLowerCase()));
 const go=(date:string)=>{setDay(date);setPlan(undefined);setShift(undefined);setSelected(undefined);setNotice('');setDropIssue('');};
 const focusedWorker=workers.find(w=>w.id===sid);
 const completedPool=tasks.filter(t=>t.state==='done'&&[t.label,displayTaskLabel(t.label),t.animal_name,t.animal_id].join(' ').toLowerCase().includes(search.toLowerCase()));
 const visiblePool=(poolTab==='done'?completedPool:pool.filter(t=>poolTab==='derived'?t.is_derived:!t.is_derived))
  .filter(t=>!eligibleOnly||focusedWorker?.skills.includes(t.skill));
 const choose=(t:WeeklyTask)=>{setSelected(t);setDestination({staff_id:t.staff_id??sid??0,day:t.day??(day<taipeiToday()?taipeiToday():day),start_time:t.start_time??'09:00',locked:t.staff_id===null||Boolean(t.locked)});};
 const drop=(id:string,staff_id:number,date?:string,start_time?:string)=>{
  if(id&&!move.isPending)move.mutate({id,body:{staff_id,day:date,start_time,locked:true}});
 };
 const beginDrag=(event:React.DragEvent,task:WeeklyTask)=>{
  dragTaskId.current=task.task_id;
  event.dataTransfer.setData('text/plain',task.task_id);
  event.dataTransfer.effectAllowed='move';
  setDragged(task);
  setNotice('');
  setDropIssue('');
 };
 const dropReason=(task:WeeklyTask,shift:WeeklyShift|undefined,date:string,start:number)=>{
  if(date<taipeiToday())return '歷史排程只供查閱';
  if(!shift?.attending)return '員工未出勤';
  if(!shift.skills.includes(task.skill))return '技能不符';
  const end=start+task.hours*4;
  if(start<lunchBreak[1]&&end>lunchBreak[0])return '11:30–13:30 休息時間，暫停派工';
  if(start<timeGrid(shift.shift_start)||end>timeGrid(shift.shift_end))return '超出上下班時間';
  if(shift.break_start&&shift.break_end&&start<timeGrid(shift.break_end)&&end>timeGrid(shift.break_start))return '與休息時間重疊';
  const assigned=tasks.filter(t=>t.staff_id===shift.id&&t.day===date&&t.state!=='cancelled'&&t.task_id!==task.task_id);
  if(assigned.some(t=>start<timeGrid(t.end_time)&&end>timeGrid(t.start_time)))return '與既有任務重疊';
  const shiftQuarters=timeGrid(shift.shift_end)-timeGrid(shift.shift_start)
   -(timeGrid(shift.break_end)-timeGrid(shift.break_start));
  const available=shift.daily_capacity_hours===undefined
   ?Math.min(shiftQuarters,Math.floor(shift.available_hours*4))-Math.ceil(shift.scheduled_hours*4)
   :shift.daily_capacity_hours*4;
  if(task.hours*4+assigned.reduce((total,t)=>total+t.hours*4,0)>available)return '超出每日可用工時';
  return '';
 };
 const placement=(p:Placement)=>{
  if(p[0]===null)return '任務池';
  return [workers.find(w=>w.id===p[0])?.name??p[0],p[1],p[2]===null?'':gridTime(p[2])].join(' ');
 };
 const navigating=preview.isPending||apply.isPending||move.isPending;
 return <section className="space-y-4">
  <h1>資源配置</h1>
  {[week.error,create.error,saveShift.error,resolve.error,saveStaff.error].filter(Boolean).map((error,i)=><ErrorView key={i} error={error}/>)}
  <div className="weekly-board">
   <aside className="panel weekly-board-panel weekly-pool-panel" onDragOver={e=>{if(dragged?.staff_id){e.preventDefault();e.dataTransfer.dropEffect='none';}}} onDrop={e=>{e.preventDefault();e.stopPropagation();if(dragged?.staff_id)setDropIssue('已指派任務只能透過七天最佳化派工重新移回任務池');endDrag();}}>
    <h2>待指派任務池</h2>
    <details><summary>建立任務</summary><form className="space-y-2" onSubmit={e=>{
     e.preventDefault();const f=new FormData(e.currentTarget);
     create.mutate({...Object.fromEntries(f),animal_id:Number(f.get('animal_id')),priority:Number(f.get('priority'))});
    }}>
     <label>動物編號<input name="animal_id" type="number" min="1" required/></label>
     <label>任務<select name="label">{healthTaskLabels.filter(l=>!['疫苗紀錄待確認','補做驅蟲'].includes(l)).map(l=><option key={l} value={l}>{displayTaskLabel(l)}</option>)}</select></label>
     <label>最早日期<input name="earliest" type="date" min={taipeiToday()} defaultValue={taipeiToday()} required/></label>
     <label>期限<input name="due" type="date" min={taipeiToday()} defaultValue={taipeiToday()} required/></label>
     <label>優先級<select name="priority" defaultValue="3">{priorityName.map((label,i)=><option key={label} value={i}>{label}</option>)}</select></label>
     <label>注意事項<textarea name="note"/></label>
     <button disabled={create.isPending}>新增</button>
    </form></details>
    <input aria-label="搜尋任務" placeholder="搜尋動物或任務" value={search} onChange={e=>setSearch(e.target.value)}/>
    <div className="weekly-pool-tabs" aria-label="任務類別">
     <button type="button" aria-pressed={poolTab==='pending'} className={poolTab==='pending'?'':'secondary'} onClick={()=>setPoolTab('pending')}>未指派</button>
     <button type="button" aria-pressed={poolTab==='derived'} className={poolTab==='derived'?'':'secondary'} onClick={()=>setPoolTab('derived')}>衍生任務</button>
     <button type="button" aria-pressed={poolTab==='done'} className={poolTab==='done'?'':'secondary'} onClick={()=>setPoolTab('done')}>已完成</button>
    </div>
    <label className="weekly-checkbox"><input type="checkbox" checked={eligibleOnly} disabled={!focusedWorker} onChange={e=>setEligibleOnly(e.target.checked)}/>只顯示{focusedWorker? ` ${focusedWorker.name} `:'所選員工'}技能符合的任務</label>
    <div className="weekly-pool">{visiblePool.map(t=><button key={t.task_id} className="weekly-task" data-priority={t.display_priority??t.priority} draggable={t.state==='pending'}
     onDragStart={t.state==='pending'?e=>beginDrag(e,t):undefined} onDragEnd={endDrag} onClick={()=>choose(t)}>
     <strong><span className="weekly-dot" aria-hidden="true"/>{displayTaskLabel(t.label)}</strong><span className="weekly-animal">
      {t.photo_url?<img src={t.photo_url} alt=""/>:<span aria-label="尚無照片">🐾</span>}{t.animal_name} #{t.animal_id}</span>
     <small>{t.hours*60} 分鐘 · 期限 {t.due??'未設定'}</small>{t.reason&&<small>{t.reason}</small>}
    </button>)}</div>
    {!visiblePool.length&&<p className="muted">沒有相符的{poolTab==='done'?'已完成任務':poolTab==='derived'?'衍生任務':'待指派任務'}</p>}
   </aside>
   <div className="panel weekly-board-panel space-y-3 min-w-0">
    <h2>員工日曆</h2>
    <div className="weekly-toolbar">
     <button className="secondary" disabled={navigating} onClick={()=>go(addDays(day,-7))}>上一週</button>
     <button className="secondary" disabled={navigating} onClick={()=>go(taipeiToday())}>今天</button>
     <button className="secondary" disabled={navigating} onClick={()=>go(addDays(day,7))}>下一週</button>
     <input aria-label="排程日期" type="date" disabled={navigating} value={day} onChange={e=>{if(e.target.value)go(e.target.value);}}/>
     <select aria-label="日曆檢視" value={view} onChange={e=>setView(e.target.value==='day'?'day':'week')}><option value="day">日檢視</option><option value="week">週檢視</option></select>
     <select aria-label="員工" value={sid??''} onChange={e=>setWorker(Number(e.target.value))}>{workers.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select>
     <button disabled={navigating||historical||week.isPending} onClick={()=>preview.mutate()}>七天最佳化派工</button>
    </div>
    {week.isLoading&&<p role="status">正在載入排程…</p>}
    {preview.isPending&&<p role="status">正在計算七天排程…</p>}
    {historical&&<p>歷史週只供查閱</p>}
    {notice&&<p role="status">{notice}</p>}
    {[preview.error,apply.error,move.error,event.error].filter(Boolean).map((error,i)=><ErrorView key={i} error={error}/>)}
    {workers.length>0&&<details><summary>全員每日工時</summary><ul>
     {workers.map(w=>{
      const assigned=tasks.filter(t=>t.staff_id===w.id&&t.day===day&&t.state!=='cancelled').reduce((total,t)=>total+t.hours,0);
      const shift=ranges.find(s=>s.id===w.id&&s.day===day);
      return <li key={w.id}>{w.name} · 已排 {assigned}h · 可派 {shift?.assignable_hours??'—'}h</li>;
     })}
    </ul></details>}
    {plan&&<section className="weekly-plan space-y-2"><h3>調整方案 · CP-SAT {plan.solver_status}</h3>
     <ul>{plan.changes.map(c=><li key={c.task_id}>{c.animal_name} · {displayTaskLabel(c.label)}　{placement(c.before)} → {placement(c.after)} {c.adjustment_reason}</li>)}</ul>
     {!plan.changes.length&&<p>沒有排程變動</p>}
     <button disabled={apply.isPending||!plan.plan_id} onClick={()=>{if(plan.plan_id)apply.mutate(plan.plan_id);}}>確認儲存</button>{' '}
     <button className="secondary" onClick={()=>setPlan(undefined)}>取消</button>
    </section>}
    {selected&&<section ref={detailRef} tabIndex={-1} aria-label="任務詳細資料" className="weekly-task-detail">
     <div className="weekly-detail-heading"><h3>{selected.animal_name} · {displayTaskLabel(selected.label)}</h3>
      <button type="button" className="secondary" onClick={()=>setSelected(undefined)}>關閉</button></div>
     <p className="muted">{selected.day??'待指派'}　{selected.start_time??''} {selected.end_time?`– ${selected.end_time}`:''}
      {selected.state==='done'?' · 已完成':selected.state==='in_progress'?' · 執行中':''}</p>
     {selected.note&&<p>{selected.note}</p>}
     {selected.report&&<p>回報：{selected.report.result} {selected.report.note}</p>}
     {selected.issue&&<p>{selected.issue.resolved_at?'問題已解決':'問題待處理'} {!selected.issue.resolved_at&&
      <button type="button" className="secondary" disabled={resolve.isPending} onClick={()=>resolve.mutate(selected.task_id)}>標記已解決</button>}</p>}
     {selected.state==='done'&&<TaskPhotos task={selected}/>}
     {selected.state==='pending'&&(!selected.day||selected.day>=taipeiToday())&&<form className="weekly-toolbar" onSubmit={e=>{e.preventDefault();move.mutate({id:selected.task_id,body:destination});}}>
     <select aria-label="指派員工" value={destination.staff_id} onChange={e=>setDestination({...destination,staff_id:Number(e.target.value)})}>{workers.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select>
     <input aria-label="指派日期" type="date" value={destination.day} required onChange={e=>setDestination({...destination,day:e.target.value})}/>
     <input aria-label="開始時間" type="time" step={900} value={destination.start_time} required onChange={e=>setDestination({...destination,start_time:e.target.value})}/>
     <label className="weekly-checkbox"><input type="checkbox" checked={destination.locked} onChange={e=>setDestination({...destination,locked:e.target.checked})}/>鎖定</label>
     <button disabled={move.isPending}>儲存指派</button>
     {selected.staff_id&&<small className="muted">如需移回任務池，請使用七天最佳化派工。</small>}
     {!selected.locked&&<button type="button" className="secondary" disabled={event.isPending} onClick={()=>event.mutate({id:selected.task_id,date:destination.day})}>延遲至所選日期</button>}
     {selected.staff_id&&selected.day===taipeiToday()&&<button type="button" className="secondary"
      onClick={()=>event.mutate({id:selected.task_id})}>標記執行中</button>}
     </form>}
    </section>}
    {week.data&&<ScheduleCalendar columns={columns} shifts={ranges} tasks={tasks} onTask={choose} selectedId={selected?.task_id}
     drag={{start:beginDrag,end:endDrag,
      canMove:t=>t.state==='pending'&&Boolean(t.day&&t.day>=taipeiToday()),
      reason:dragged?(s,d,tick)=>dropReason(dragged,s,d,tick):undefined,
      hover:setDropIssue,
      drop:(id,column,start,reason)=>{setDropIssue(reason);if(id&&id===dragTaskId.current&&!reason&&column.sid)drop(id,column.sid,column.day,start);endDrag();}}}/>}
   </div>
  </div>
  {dropIssue&&<div className="schedule-drop-message" role="status">{dropIssue}
   {!dragged&&<button type="button" className="secondary" onClick={()=>setDropIssue('')}>關閉</button>}
  </div>}
  {tasks.some(t=>t.state==='cancelled')&&<details className="panel"><summary>本週已取消任務</summary>
   <ul>{tasks.filter(t=>t.state==='cancelled').map(t=><li key={t.task_id}>{t.day??t.earliest} · {t.animal_name} · {t.label} · {t.reason}</li>)}</ul>
  </details>}
  <details className="panel"><summary>每日班表與員工設定</summary>
   <div className="weekly-toolbar">{workers.map(w=><button key={w.id} className="secondary" onClick={()=>setStaffSettings(w)}>編輯 {w.name}</button>)}</div>
   {staffSettings&&<form className="weekly-toolbar" onSubmit={e=>{e.preventDefault();saveStaff.mutate(staffSettings);}}>
    <strong>{staffSettings.name}</strong>
    {skills.map(([key,label])=><label key={key} className="weekly-checkbox"><input type="checkbox"
     checked={staffSettings.skills.includes(key)} onChange={e=>setStaffSettings({...staffSettings,
      skills:e.target.checked?[...staffSettings.skills,key]:staffSettings.skills.filter(skill=>skill!==key)})}/>{label}</label>)}
    <button disabled={saveStaff.isPending}>儲存員工設定</button>
   </form>}
   <div className="weekly-toolbar">{ranges.filter(s=>s.day===day).map(s=><button key={s.id} className="secondary" onClick={()=>setShift(s)}>{s.name} · 可派 {s.assignable_hours??'—'}h</button>)}</div>
   {shift&&<form className="weekly-toolbar" onSubmit={e=>{e.preventDefault();saveShift.mutate(shift);}}>
    <strong>{shift.name} {shift.day}</strong>
    <label className="weekly-checkbox"><input type="checkbox" checked={Boolean(shift.attending)} onChange={e=>setShift({...shift,attending:e.target.checked})}/>出勤</label>
    {([['shift_start','上班'],['shift_end','下班'],['break_start','額外休息開始'],['break_end','額外休息結束']] as const).map(([key,label])=><label key={key}>{label}<input type="time" step={900} value={shift[key]??''} onChange={e=>setShift({...shift,[key]:e.target.value||null})}/></label>)}
    <p className="muted">固定休息 11:30–13:30</p>
    {([['available_hours','每日可用工時'],['scheduled_hours','已占用工時']] as const).map(([key,label])=><label key={key}>{label}<input type="number" min={0} max={24} step={.25} value={shift[key]} onChange={e=>setShift({...shift,[key]:Number(e.target.value)})}/></label>)}
    <button disabled={saveShift.isPending||day<taipeiToday()}>儲存班表</button>
   </form>}
  </details>
 </section>;
}
