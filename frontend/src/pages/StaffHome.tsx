
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type WeeklyTask } from '../services/api';
import { ErrorView } from '../components/common/States';
import { addDays, taipeiToday } from '../components/common/scheduleDates';
import ScheduleCalendar from '../components/common/ScheduleCalendar';
import {aiGuidance} from '../components/common/aiStatus';
import {displayTaskLabel} from '../components/common/taskPresentation';
import TaskPhotos from '../components/common/TaskPhotos';
import './StaffHome.css';

const choices:Record<string,[string,string][]> = {
 '確認驅蟲紀錄': [['yes','已驅蟲'],['no','未驅蟲']],
 '基礎驅蟲': [['done','已完成'],['failed','未能執行']],
 '補做驅蟲': [['done','已完成'],['failed','未能執行']],
 '健康狀態待確認': [['healthy','健康'],['sick','生病'],['injured','受傷']],
 '優先確認健康狀況': [['healthy','健康'],['sick','生病'],['injured','受傷']],
 '疫苗紀錄待確認': [['yes','已施打'],['no','未施打']],
 '確認疫苗紀錄': [['yes','已施打'],['no','未施打']],
 '疫苗施打': [['done','已完成'],['failed','未能執行']],
};

function encodePhoto(file:File) {
 return new Promise<string>((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(String(reader.result).split(',')[1]);
  reader.onerror=()=>reject(Error('無法讀取圖片'));
  reader.readAsDataURL(file);
 });
}

function PhotoPreview({file}:{file:File}) {
 const [url,setUrl]=useState('');
 useEffect(()=>{const next=URL.createObjectURL(file);setUrl(next);return()=>URL.revokeObjectURL(next);},[file]);
 return url?<img className="care-image" src={url} alt="待上傳照片"/>:null;
}

function TaskCard({task:t}:{task:WeeklyTask}) {
 const qc=useQueryClient();
 const [choice,setChoice]=useState('');
 const [note,setNote]=useState('');
 const [dose,setDose]=useState('');
 const [files,setFiles]=useState<File[]>([]);
 const [upload,setUpload]=useState<number>();
 const summary=useMutation({mutationFn:()=>api.taskSummary(t.task_id)});
 const care=summary.data??t.summary;
 const follow=t.label==='健康問題追蹤';
 const needsDate=(result:string)=>t.label.includes('疫苗')&&['yes','done'].includes(result);
 const needsNote=(result:string)=>['reported','failed','sick','injured'].includes(result);
 const result=choice;
 const displayPriority=t.display_priority??t.priority;
 const refresh=async()=>{await qc.invalidateQueries({queryKey:['schedule-week']});await qc.invalidateQueries({queryKey:['resource-overview']});};
 const withdraw=useMutation({mutationFn:()=>api.withdrawReport(t.task_id),onSuccess:async()=>{
  setChoice('');setNote('');setFiles([]);setDose('');summary.reset();await refresh();
 }});
 const canWithdraw=t.is_active&&t.report?.reported_at.slice(0,10)===taipeiToday()&&!t.issue?.resolved_at;
 const report=useMutation({
  mutationFn:async(value:string)=>{
   setUpload(undefined);
   const photos=needsNote(value)?files:[];
   if(photos.length>4||photos.some(f=>f.size>5*1024*1024))throw Error('最多四張，每張最多 5 MB');
   return api.reportWeekly(t.task_id,{result:value,note,administered_date:dose||null,
    photos:await Promise.all(photos.map(encodePhoto))},photos.length?setUpload:undefined);
  },
  onSuccess:refresh
 });
 const cancelReport=()=>{setChoice('');setNote('');setDose('');setFiles([]);setUpload(undefined);report.reset();};
 return <article className="staff-care-card weekly-task" data-priority={displayPriority} data-done={t.state==='done'}>
  <div className="staff-care-identity">
   <strong><span className="weekly-dot" aria-hidden="true"/>{t.start_time}–{t.end_time}　{displayTaskLabel(t.label)}</strong><div>{t.animal_name} #{t.animal_id}</div>
  {displayPriority<=1&&<span className="attention-badge alert-high">{displayPriority===0?'緊急':'高優先級'}</span>}
  </div>
  <div className="staff-care-controls">
  {care&&<p>{care.animal_summary} <small>（{care.mode==='llm'?'Gemini AI':care.mode==='cache'?'AI 快取摘要':'規則式摘要'}{
    care.fallback_reason==='in_progress'?' · AI 摘要處理中':care.fallback_reason?' · 目前 AI 無法使用':''
  }）</small></p>}
  <details onToggle={e=>{
   if(e.currentTarget.open&&!summary.isPending)summary.mutate();
  }}>
   <summary>動物資料及照護重點</summary>
   {t.photo_url?<img className="rounded-lg max-w-xs w-full" src={t.photo_url} alt={t.animal_name}/>:<p className="muted">🐾 尚無動物照片</p>}
   {t.note&&<p>注意事項：{t.note}</p>}
   {care&&<ul>{[...care.known_issues,...care.observations,...care.unconfirmed].filter(x=>x!==t.note&&x!==`本次任務：${t.label}`).map((x,i)=><li key={i}>{x}</li>)}</ul>}
   {summary.isPending&&<p role="status">正在查詢照護摘要…</p>}
   {summary.error&&<ErrorView error={summary.error}/>}
   {summary.data&&<button type="button" className="secondary" disabled={summary.isPending}
    onClick={()=>summary.mutate()}>重新查詢摘要</button>}
  </details>
  {care?.fallback_reason&&<p className="muted">{aiGuidance(care.fallback_reason)}</p>}
  {t.report?<div><strong>已回報</strong> · {t.report.result} {t.report.note}{t.issue&&<p>{t.issue.resolved_at?'問題已解決':'待管理者處理'}</p>}<TaskPhotos task={t}/>
   {canWithdraw&&<button type="button" className="secondary" disabled={withdraw.isPending}
    title="收回任務完成回報，已記錄的醫療紀錄仍會保留" onClick={()=>withdraw.mutate()}>收回完成回報</button>}
   {withdraw.error&&<ErrorView error={withdraw.error}/>}</div>:
   t.day&&t.day<=taipeiToday()&&t.is_active&&['pending','in_progress'].includes(t.state)?<>
    {!follow&&<div className="flex flex-wrap gap-2">{(choices[t.label]??[['done','完成任務']]).map(([value,label])=><button key={value} disabled={report.isPending}
     className={choice===value?'':'secondary'} onClick={()=>{setChoice(value);if(!needsDate(value)&&!needsNote(value))report.mutate(value);}}>{label}</button>)}
     <button type="button" className="secondary" disabled={report.isPending} onClick={()=>setChoice('reported')}>回報異常</button></div>}
    {follow&&!choice&&<button type="button" className="secondary" onClick={()=>setChoice('reported')}>填寫追蹤回報</button>}
    {(needsDate(result)||needsNote(result))&&<form className="space-y-2" onSubmit={e=>{e.preventDefault();report.mutate(result);}}>
     {needsDate(result)&&<label>實際施打日期<input required type="date" max={taipeiToday()} value={dose} onChange={e=>setDose(e.target.value)}/></label>}
     <label>情況說明（選填）<textarea value={note} onChange={e=>setNote(e.target.value)}/></label>
     {needsNote(result)&&<>
      <label>選擇照片<input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={e=>setFiles(Array.from(e.target.files??[]))}/></label>
      <label>手機拍照<input type="file" accept="image/*" capture="environment" onChange={e=>setFiles([...files,...Array.from(e.target.files??[])])}/></label>
      <div className="flex flex-wrap gap-2">{files.map((file,i)=><PhotoPreview key={file.name+i} file={file}/>)}</div>
      {files.length>0&&<button type="button" className="secondary" onClick={()=>setFiles([])}>清除照片</button>}
     </>}
     <button disabled={report.isPending}>送出回報</button>
     <button type="button" className="secondary ml-2" disabled={report.isPending} onClick={cancelReport}>取消回報</button>
    </form>}
   </>:null}
  {report.error&&<ErrorView error={report.error}/>}
  {report.isPending&&<p role="status">{files.length
   ?upload===undefined?'正在準備照片…':upload<100?`照片上傳 ${upload}%`:'照片已上傳，正在儲存回報…'
   :'正在儲存回報…'}</p>}
  {withdraw.isSuccess&&!t.report&&<p role="status">已收回，任務恢復待辦。</p>}
  </div>
 </article>;
}

export default function StaffHome({userId}:{userId:number}) {
 const [day,setDay]=useState(taipeiToday);
 const [weekly,setWeekly]=useState(false);
 const [selectedId,setSelectedId]=useState<string>();
 const detail=useRef<HTMLElement>(null);
 useEffect(()=>{if(selectedId)detail.current?.focus();},[selectedId]);
 const query=useQuery({queryKey:['schedule-week','staff',userId,day],queryFn:()=>api.week(day),refetchInterval:15000});
 const today=taipeiToday();
 const tasks=query.data?.tasks??[];
 const worker=query.data?.workers[0];
 const days=weekly?(query.data?.days??[]):[day];
 const selected=tasks.find(task=>task.task_id===selectedId&&days.includes(task.day??''));
 const go=(date:string)=>{setDay(date);setSelectedId(undefined);};
 return <section className="space-y-4">
  <h1>照護人員工作台</h1>
  <section className="panel weekly-board-panel space-y-3">
   <h2>個人日曆</h2>
   <div className="weekly-toolbar">
    <button type="button" className="secondary" onClick={()=>go(addDays(day,weekly?-7:-1))}>{weekly?'上一週':'前一天'}</button>
    <button type="button" className="secondary" onClick={()=>go(today)}>今天</button>
    <button type="button" className="secondary" onClick={()=>go(addDays(day,weekly?7:1))}>{weekly?'下一週':'後一天'}</button>
    <input aria-label="排程日期" type="date" value={day} onChange={e=>{if(e.target.value)go(e.target.value);}}/>
    <select aria-label="日曆檢視" value={weekly?'week':'day'} onChange={e=>{setWeekly(e.target.value==='week');setSelectedId(undefined);}}>
     <option value="day">日檢視</option><option value="week">週檢視</option>
    </select>
   </div>
   {query.error&&<ErrorView error={query.error}/>}
   {query.isLoading&&<p role="status">載入任務中…</p>}
   {selected&&<section ref={detail} tabIndex={-1} aria-label="照護任務詳細資料" className="weekly-task-detail staff-task-detail">
    <div className="weekly-detail-heading"><h3>{selected.state==='done'?'已回報任務':'照護任務'}</h3>
     <button type="button" className="secondary" onClick={()=>setSelectedId(undefined)}>關閉</button></div>
    <TaskCard key={selected.task_id} task={selected}/>
   </section>}
   {worker&&<ScheduleCalendar columns={days.map(date=>({day:date,sid:worker.id,title:date.slice(5)}))}
    shifts={query.data?.shifts??[]} tasks={tasks} onTask={task=>setSelectedId(task.task_id)} selectedId={selectedId}/>}
   {worker&&!tasks.some(task=>task.day&&days.includes(task.day)&&task.state!=='cancelled')&&<p className="muted">這段期間沒有指派任務</p>}
  </section>
 </section>;
}
