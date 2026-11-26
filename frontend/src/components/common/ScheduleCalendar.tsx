import type { DragEvent, ReactNode } from 'react';
import type {WeeklyShift, WeeklyTask} from '../../services/api';
import {gridTime, lunchBreak, timeGrid} from './scheduleDates';
import {displayTaskLabel} from './taskPresentation';
import {timelineColumns} from './timelineLayout';
import '../../pages/ResourceBoard.css';

export type ScheduleColumn = {day:string; sid?:number; title:string};
type DragControls = {
 start:(event:DragEvent,task:WeeklyTask)=>void;
 end:()=>void;
 canMove:(task:WeeklyTask)=>boolean;
 reason?:(shift:WeeklyShift|undefined,day:string,start:number)=>string;
 drop:(id:string,column:ScheduleColumn,start:string,reason:string)=>void;
 hover:(reason:string)=>void;
};

export const priorityName = ['緊急','高','中','一般','例行'];

export default function ScheduleCalendar({columns, shifts, tasks, onTask, drag, selectedId, renderInline}:{
 columns:ScheduleColumn[]; shifts:WeeklyShift[]; tasks:WeeklyTask[];
 onTask:(task:WeeklyTask)=>void; drag?:DragControls; selectedId?:string; renderInline?:(task:WeeklyTask)=>ReactNode;
}) {
 const placed = tasks.filter(t=>t.day&&t.start_time&&t.state!=='cancelled'
  &&columns.some(c=>c.day===t.day&&c.sid===t.staff_id));
 const activeShifts = shifts.filter(s=>columns.some(c=>c.day===s.day&&c.sid===s.id));
 const first=Math.min(36,...activeShifts.map(s=>timeGrid(s.shift_start)),...placed.map(t=>timeGrid(t.start_time)));
 const last=Math.max(68,...activeShifts.map(s=>timeGrid(s.shift_end)),...placed.map(t=>t.end_time?timeGrid(t.end_time):timeGrid(t.start_time)+t.hours*4));
 const ticks=Array.from({length:last-first},(_,i)=>first+i);
 // Personal day cards contain report controls: keep the full 66px quarter-hour scale
 // for every staff account, regardless of task count or duration.
 const rowHeight=drag?88*0.75:renderInline?66:66*0.75*0.75;
 // Both personal views use the same lunch height and the same coordinate function.
 const lunchHeight=rowHeight;
 const gridTicks=ticks.filter(tick=>tick<=lunchBreak[0]||tick>=lunchBreak[1]);
 const lunchTicks=lunchBreak[1]-lunchBreak[0];
 const gridOffset=(tick:number)=>(tick-first-Math.max(0,Math.min(lunchTicks,tick-lunchBreak[0]))*(1-lunchHeight/(rowHeight*lunchTicks)))*rowHeight;
 const slotHeight=(tick:number)=>gridOffset(tick===lunchBreak[0]?Math.min(last,lunchBreak[1]):tick+1)-gridOffset(tick);
 // Endpoints are authoritative: a 13:30–14:30 task spans all four quarter-hour cells.
 const taskEnd=(task:WeeklyTask)=>task.end_time?timeGrid(task.end_time):timeGrid(task.start_time)+task.hours*4;
 if(!columns.length)return <p className="muted">此處沒有可顯示的員工班表</p>;
 return <div className={`weekly-scroll${columns.length===7?' weekly-scroll--seven':''}`} role="region" aria-label="排程時間表" tabIndex={0}>
  <div className="weekly-calendar" style={{'--slot-height':`${rowHeight}px`,'--lunch-height':`${lunchHeight}px`} as React.CSSProperties}>
   <div className="weekly-times"><header>臺灣時間</header>{gridTicks.map(tick=><div key={tick}
    className={tick%4===0?'hour-line':''} style={{height:slotHeight(tick),boxSizing:'border-box'}} data-lunch={tick===lunchBreak[0]||undefined}>{tick%4===0||tick===lunchBreak[0]||tick===lunchBreak[1]?gridTime(tick):''}</div>)}</div>
   {columns.map(column=>{
    const daily=placed.filter(t=>t.day===column.day&&t.staff_id===column.sid);
    const shift=activeShifts.find(s=>s.id===column.sid&&s.day===column.day);
    const lanes=timelineColumns(daily.map(t=>({task_id:t.task_id,s:timeGrid(t.start_time),e:taskEnd(t)})));
    const progress=`完成 ${daily.filter(t=>t.state==='done').length}/${daily.length}`;
    const assigned=daily.reduce((total,t)=>total+t.hours,0).toFixed(2);
    return <div className="weekly-column" key={column.day+'-'+column.sid} data-date={column.day}>
     <header><strong>{column.title}</strong>
      {drag?<><small>已排 {assigned}h</small><small>尚可派 {shift?.assignable_hours?.toFixed(2)??'—'}h</small></>:
       <small title="已排時數／今日可用時數">已排／可用 {assigned}/{shift?.daily_capacity_hours?.toFixed(2)??'—'}h</small>}
      <small>{progress}</small></header>
     <div className="weekly-slots">
      {gridTicks.map(tick=>{
       const reason=drag?.reason?.(shift,column.day,tick);
       const lunch=tick>=lunchBreak[0]&&tick<lunchBreak[1];
       return <div key={tick} className={tick%4===0?'hour-line':''} style={{height:slotHeight(tick),boxSizing:'border-box'}} data-drop={reason===undefined?undefined:reason?'blocked':'allowed'}
        data-lunch={lunch||undefined} title={reason||(lunch?'11:30–13:30 休息，暫停派工':undefined)}
        onDragOver={drag&&reason!==undefined?e=>{e.preventDefault();drag.hover(reason);}:undefined}
        onDrop={drag&&reason!==undefined?e=>{e.preventDefault();e.stopPropagation();drag.drop(e.dataTransfer.getData('text/plain'),column,gridTime(tick),reason);}:undefined}>
        {tick===lunchBreak[0]&&<span className="lunch-label">11:30–13:30 休息</span>}</div>;
      })}
      {daily.map(task=>{
       const start=timeGrid(task.start_time);
       const priority=task.display_priority??task.priority;
       const label=displayTaskLabel(task.label);
       const showPriority=label!=='健康狀態待確認';
       const minutes=(taskEnd(task)-start)*15;
       const lane=lanes.get(task.task_id)??{index:0,count:1};
       const title=`${task.start_time}–${task.end_time} · ${task.animal_name} · ${label} · ${task.state==='done'?'已完成':!showPriority?'':priorityName[priority]}${task.locked?' · 已鎖定':''}`;
       const movable=Boolean(drag?.canMove(task));
       if(renderInline)return <div key={task.task_id} className="weekly-event weekly-event--staff-inline" data-personal="true" data-personal-minutes={minutes} data-priority={priority} data-done={task.state==='done'}
        style={{top:gridOffset(start)+1,height:Math.max(2,gridOffset(taskEnd(task))-gridOffset(start)-2),
         left:`calc(${lane.index*100/lane.count}% + 2px)`,right:`calc(${(lane.count-lane.index-1)*100/lane.count}% + 2px)`}}>
        {renderInline(task)}
       </div>;
       return <button type="button" key={task.task_id} className="weekly-event weekly-event--three-lines" data-priority={priority}
        data-done={task.state==='done'} data-manager-minutes={drag?minutes:undefined} data-personal-minutes={!drag?minutes:undefined} data-personal={!drag||undefined} draggable={movable} aria-pressed={selectedId===task.task_id}
        onDragStart={movable?e=>drag?.start(e,task):undefined} onDragEnd={movable?drag?.end:undefined}
        onClick={()=>onTask(task)} title={title} aria-label={title}
        style={{top:gridOffset(start)+1,height:Math.max(2,gridOffset(taskEnd(task))-gridOffset(start)-2),
         left:`calc(${lane.index*100/lane.count}% + 2px)`,right:`calc(${(lane.count-lane.index-1)*100/lane.count}% + 2px)`}}>
        <span className="weekly-event-time"><span className="weekly-dot" aria-hidden="true"/>{task.start_time}–{task.end_time}</span>
        <span className="weekly-event-animal">{task.animal_name}</span>
        <span className="weekly-event-label">{priority<=1&&task.state!=='done'&&showPriority?`${priorityName[priority]} · `:''}{label}</span>
       </button>;
      })}
     </div>
    </div>;
   })}
  </div>
 </div>;
}
