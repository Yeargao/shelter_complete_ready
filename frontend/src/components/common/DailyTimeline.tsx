import {useMemo,type ReactNode} from 'react';
import {Link} from 'react-router-dom';
import './DailyTimeline.css';
import {displayTaskLabel} from './taskPresentation';
import {timelineColumns} from './timelineLayout';
export type TimelineTask={task_id:string;animal_id:number;animal_name:string;label:string;category:string;state:string;start_time?:string|null;end_time?:string|null;hours?:number;priority?:number;note?:string|null;result?:string|null};
type Props={tasks:TimelineTask[];shiftStart?:string|null;shiftEnd?:string|null;breakStart?:string|null;breakEnd?:string|null;emptyLabel?:string;onTaskClick?:(task:TimelineTask)=>void;renderTaskDetails?:(task:TimelineTask)=>ReactNode;expandedTaskId?:string|null;compact?:boolean};
const minutes=(v?:string|null):number|null=>{if(!v||!/^\d{1,2}:\d{2}$/.test(v))return null;const [h,m]=v.split(':').map(Number);return h>=0&&h<=23&&m>=0&&m<60?h*60+m:null;};
const fmt=(m:number)=>`${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}`;
export const priorityColor=(t:Pick<TimelineTask,'category'|'priority'> & {label?:string})=>{const label=t.label||'';if(label==='優先確認健康狀況'||label==='傷病治療'||label.includes('傷病治療'))return 'red';if(label==='健康狀態待確認')return 'orange';if(label==='健康問題追蹤')return 'amber';if(label==='基礎驅蟲'||label==='疫苗施打'||label==='疫苗紀錄待確認')return 'green';return t.priority!=null?(t.priority<=1?'red':t.priority<=2?'amber':'green'):(t.category==='health'?'amber':'green');};
const HALF_CELL=88; // One fixed 30-minute height; 15 minutes is exactly half this height.
// Staff-only display: two successive quarter-hour tasks exactly fill one half-hour cell.
// Their real start/end times remain unchanged and are printed on each card.
export function adjacentQuarterHourPairs<T extends {task_id:string;s:number;e:number}>(tasks:T[]){
 const pairs=new Map<string,{side:'left'|'right';slotStart:number}>();
 for(const first of tasks){
  if(first.s%30!==0||first.e!==first.s+15)continue;
  const inSlot=tasks.filter(t=>t.s<first.s+30&&t.e>first.s);
  if(inSlot.length!==2)continue;
  const second=inSlot.find(t=>t.task_id!==first.task_id);
  if(!second||second.s!==first.e||second.e!==first.s+30)continue;
  pairs.set(first.task_id,{side:'left',slotStart:first.s});
  pairs.set(second.task_id,{side:'right',slotStart:first.s});
 }
 return pairs;
}
export default function DailyTimeline({tasks,shiftStart,shiftEnd,breakStart,breakEnd,emptyLabel='尚無安排任務',onTaskClick,renderTaskDetails,expandedTaskId,compact=false}:Props){
 const schedule=useMemo(()=>{
  const scheduled=tasks.map(t=>({...t,s:minutes(t.start_time),e:minutes(t.end_time)})).filter((t):t is typeof t & {s:number;e:number}=>t.s!==null&&t.e!==null&&t.e>t.s).sort((a,b)=>a.s-b.s||a.task_id.localeCompare(b.task_id));
  const untimed=tasks.filter(t=>{const s=minutes(t.start_time),e=minutes(t.end_time);return s===null||e===null||e<=s;});
  const shiftS=minutes(shiftStart),shiftE=minutes(shiftEnd);
  const begin=Math.floor(Math.min(shiftS??540,...scheduled.map(t=>t.s))/30)*30;
  const end=Math.ceil(Math.max(shiftE??1080,...scheduled.map(t=>t.e))/30)*30;
  const rows=Array.from({length:Math.max(1,Math.ceil((end-begin)/30))},(_,i)=>begin+i*30);
  const heights=rows.map(()=>HALF_CELL);
  const offsets=heights.reduce<number[]>((acc,h)=>{acc.push((acc[acc.length-1]??0)+h);return acc},[0]);
  const position=(minute:number)=>{const idx=Math.max(0,Math.min(rows.length-1,Math.floor((minute-begin)/30)));return offsets[idx]+((minute-(begin+idx*30))/30)*heights[idx]};
  return {scheduled,untimed,rows,begin,end,heights,offsets,position};
 },[tasks,shiftStart,shiftEnd]);
 const breakS=minutes(breakStart),breakE=minutes(breakEnd);
 const paired=onTaskClick&&!compact?adjacentQuarterHourPairs(schedule.scheduled):new Map<string,{side:'left'|'right';slotStart:number}>();
 // Historic/manual rows may overlap. Give simultaneous events distinct lanes
 // rather than allowing the last card to hide earlier assigned tasks.
 const columns=timelineColumns(schedule.scheduled);
 const timeEvents=schedule.scheduled.map(t=>{
  const pair=paired.get(t.task_id);
  const begin=pair?pair.slotStart:t.s;
  const end=pair?pair.slotStart+30:t.e;
  const column=columns.get(t.task_id);
  const overlap=Boolean(!pair&&column&&column.count>1);
  const ratio=column&&overlap?column.index/column.count:0;
  const remaining=column&&overlap?(column.count-column.index-1)/column.count:0;
  const laneStyle=column&&overlap?{
   left:`calc(${100*ratio}% + ${68-72*ratio}px)`,
   right:`calc(${100*remaining}% + ${8-72*remaining}px)`,
  }:undefined;
  return {t,pair,overlap,laneStyle,top:schedule.position(begin),height:Math.max(0,schedule.position(end)-schedule.position(begin)-4)};
 });
 return <div className={`daily-timeline ${compact?'daily-timeline--compact':''}`}>
  <div className="daily-timeline__scroll" aria-label="單日 30 分鐘時間表">
   <div className="daily-timeline__canvas" style={{height:Math.max(HALF_CELL,schedule.offsets.at(-1)??HALF_CELL)}}>
    {schedule.rows.map((m,i)=><div className={`daily-timeline__row ${breakS!==null&&breakE!==null&&m<breakE&&m+30>breakS?'daily-timeline__row--break':''}`} key={m} style={{top:schedule.offsets[i],height:schedule.heights[i]}}><time>{fmt(m)}<span>–{fmt(m+30)}</span></time></div>)}
    {timeEvents.map(({t,top,height,pair,overlap,laneStyle})=><div className={`daily-timeline__event ${overlap?'daily-timeline__event--overlap':''} daily-timeline__event--${priorityColor(t)} ${t.state==='done'?'daily-timeline__event--done':''} ${!onTaskClick&&expandedTaskId===t.task_id?'daily-timeline__event--expanded':''} ${onTaskClick?'daily-timeline__event--staff':''} ${onTaskClick&&expandedTaskId===t.task_id?'daily-timeline__event--staff-report':''} ${onTaskClick&&t.e-t.s<=15&&!pair?'daily-timeline__event--short':''} ${onTaskClick&&t.e-t.s>=60?'daily-timeline__event--long':''} ${pair?`daily-timeline__event--staff-paired daily-timeline__event--staff-paired--${pair.side}`:''} ${!onTaskClick&&compact&&t.e-t.s<=15?'daily-timeline__event--manager-short':''}`} key={t.task_id} style={{top:top+2,height,...laneStyle}}>
      <div className="daily-timeline__event-head"><span className={`priority-dot priority-dot--${priorityColor(t)}`}/><strong>{t.start_time}–{t.end_time}</strong>{t.state==='done'&&<span aria-label="已完成">✓</span>}</div>
      {onTaskClick?<div className="daily-timeline__staff-grid">
       <div className="daily-timeline__event-name" title={`${t.label} · ${t.animal_name}`}>{displayTaskLabel(t.label)} <Link to={`/animals/${t.animal_id}`}>{t.animal_name}</Link></div>
       <button type="button" className="daily-timeline__action" onClick={()=>onTaskClick(t)} disabled={expandedTaskId===t.task_id}>{expandedTaskId===t.task_id?'編輯中':t.state==='done'?'查看':'回報'}</button>
       <div className={`daily-timeline__staff-answer ${expandedTaskId===t.task_id?'daily-timeline__staff-answer--active':'daily-timeline__staff-answer--locked'}`}>
        {renderTaskDetails&&expandedTaskId===t.task_id?renderTaskDetails(t):<><span>回報內容</span><select aria-label="先按回報才能編輯" disabled><option>{t.state==='done'?'已完成，按查看':'請先按回報'}</option></select></>}
       </div>
      </div>:<>
       <div className="daily-timeline__event-name" title={`${t.label} · ${t.animal_name}`}>{displayTaskLabel(t.label)} <Link to={`/animals/${t.animal_id}`}>{t.animal_name}</Link></div>
       {t.state==='done'&&(t.result||t.note)&&<small className="daily-timeline__feedback">{t.result&&`結果：${t.result}`}{t.note&&` · ${t.note}`}</small>}
       {renderTaskDetails&&expandedTaskId===t.task_id&&<div className="daily-timeline__inline-report">{renderTaskDetails(t)}</div>}
      </>}
     </div>)}
    {!schedule.scheduled.length&&<div className="daily-timeline__empty">{emptyLabel}</div>}
   </div>
  </div>
  {!!schedule.untimed.length&&<div className="daily-timeline__untimed"><strong>尚未設定時段（{schedule.untimed.length}）</strong>{schedule.untimed.map(t=><div key={t.task_id}><span className={`priority-dot priority-dot--${priorityColor(t)}`}/>{displayTaskLabel(t.label)} · {t.animal_name}{onTaskClick&&expandedTaskId!==t.task_id&&<button type="button" className="daily-timeline__action" onClick={()=>onTaskClick(t)}>回報</button>}{renderTaskDetails&&expandedTaskId===t.task_id&&<div className="daily-timeline__inline-report">{renderTaskDetails(t)}</div>}</div>)}</div>}
 </div>;
}
