import {useStored} from '../components/common/smartState';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type WeeklyTask, type PhotoObservation } from '../services/api';
import { ErrorView } from '../components/common/States';
import { addDays, taipeiToday } from '../components/common/scheduleDates';
import ScheduleCalendar from '../components/common/ScheduleCalendar';

import {displayTaskLabel,taskChoices} from '../components/common/taskPresentation';
import TaskPhotos from '../components/common/TaskPhotos';
import CameraCapture,{preparePhoto,photoFile} from '../components/common/CameraCapture';
import './StaffHome.css';

const directChoices:Record<string,[string,string][]>=Object.fromEntries(Object.entries(taskChoices).filter(([label])=>['確認驅蟲紀錄','基礎驅蟲','確認疫苗紀錄','疫苗施打','評估絕育安排','更新驅蟲狀態','更新驅蟲紀錄','更新絕育狀態','絕育手術'].includes(label)));
const choices=taskChoices;

async function encodePhoto(file:File) { return (await preparePhoto(file)).split(',')[1]; }

function PhotoPreview({file}:{file:File}) {
 const [url,setUrl]=useState('');
 useEffect(()=>{const next=URL.createObjectURL(file);setUrl(next);return()=>URL.revokeObjectURL(next);},[file]);
 return url?<img className="care-image" src={url} alt="待上傳照片"/>:null;
}

function TaskCard({task:t}:{task:WeeklyTask}) {
 const qc=useQueryClient();
 const [reportOpen,setReportOpen]=useState(false);
 const [choice,setChoice]=useState('');
 const [note,setNote]=useState('');
 const [files,setFiles]=useState<File[]>([]);
 const [captured,setCaptured]=useState<string[]>([]);
 const [inlinePhoto,setInlinePhoto]=useState(false);
 const [analysis,setAnalysis]=useState<PhotoObservation>();
 const [analyzing,setAnalyzing]=useState(false);
 const [photoError,setPhotoError]=useState('');
 const photoTask=['健康狀態待確認','優先確認健康狀況','健康問題追蹤','術後健康追蹤'].includes(t.label);
 const resetPhoto=()=>{setCaptured([]);setInlinePhoto(false);setAnalysis(undefined);setPhotoError('');};
 const addPhoto=(photo:string)=>{setCaptured(prev=>prev.length<4?[...prev,photo]:prev);setAnalysis(undefined);setPhotoError('');setInlinePhoto(true);};
 const [upload,setUpload]=useState<number>();
 const [summaryOpen,setSummaryOpen]=useStored('care-open:'+t.task_id,false);
 const [cachedSummary,setCachedSummary]=useStored<Awaited<ReturnType<typeof api.taskSummary>>|null>('care-result:'+t.task_id,null);
 const summary=useMutation({mutationFn:()=>api.taskSummary(t.task_id),onSuccess:setCachedSummary});
 const care=cachedSummary??t.summary;
 const follow=false;
 const [dose,setDose]=useState('');
 const direct=directChoices[t.label];
 const needsNote=(result:string)=>['reported','sick','injured','failed','not_recovered','improving','worsening','abnormal'].includes(result);
 const result=choice;
 const displayPriority=t.display_priority??t.priority;
 const refresh=async()=>{await qc.invalidateQueries({queryKey:['schedule-week']});await qc.invalidateQueries({queryKey:['resource-overview']});await qc.invalidateQueries({queryKey:['tasks']});await qc.invalidateQueries({queryKey:['animal-photos',t.animal_id]});};
 const withdraw=useMutation({mutationFn:()=>api.withdrawReport(t.task_id),onSuccess:async()=>{
  setReportOpen(false);setChoice('');setNote('');setFiles([]);resetPhoto();setDose('');await refresh();
 }});
 const canWithdraw=t.is_active&&t.report?.reported_at.slice(0,10)===taipeiToday()&&!t.issue?.resolved_at;
 const report=useMutation({
  mutationFn:async(value:string)=>{
   setUpload(undefined);
   const photos=(needsNote(value)||photoTask)?files:[];
   const extra=photoTask?captured:[];
   if(photos.length+extra.length>4)throw Error('最多四張照片');
   const encoded=[...extra.map(p=>p.split(',')[1]),...await Promise.all(photos.map(encodePhoto))];
   return api.reportWeekly(t.task_id,{result:value,note,administered_date:dose||null,
    photos:encoded},encoded.length?setUpload:undefined);
  },
  onSuccess:async()=>{setReportOpen(false);setChoice('');setNote('');setFiles([]);resetPhoto();setDose('');setUpload(undefined);await refresh();}
 });
 const cancelReport=()=>{setReportOpen(false);setChoice('');setNote('');setFiles([]);resetPhoto();setDose('');setUpload(undefined);report.reset();withdraw.reset();};
 const openReport=()=>{resetPhoto();setChoice(follow?'reported':'');setReportOpen(true);};
 const canReport=Boolean(t.day&&t.day<=taipeiToday()&&t.is_active&&['pending','in_progress'].includes(t.state));
 return <><article className="staff-care-card weekly-task" data-priority={displayPriority} data-done={t.state==='done'}>
  <div className="staff-care-copy">
  <div className="staff-care-identity">
   <strong><span className="weekly-dot" aria-hidden="true"/>{t.start_time}–{t.end_time}</strong><div>{t.animal_name} #{t.animal_id}</div>
   <div>{displayTaskLabel(t.label)}</div>
  </div>
  <div className="staff-care-controls staff-care-info">
  {care&&<p>{care.animal_summary}</p>}
  <details open={summaryOpen} onToggle={e=>{
   const open=e.currentTarget.open;
   if(open!==summaryOpen){setSummaryOpen(open);if(open&&!cachedSummary&&!summary.isPending)summary.mutate()}
  }}>
   <summary>動物資料及照護重點</summary>
   {t.photo_url?<img className="rounded-lg max-w-xs w-full" src={t.photo_url} alt={t.animal_name}/>:<p className="muted">🐾 尚無動物照片</p>}
   {t.note&&<p>注意事項：{t.note}</p>}
   {care&&<ul>{[...care.known_issues,...care.observations,...care.unconfirmed].filter(x=>x!==t.note&&x!==`本次任務：${t.label}`).map((x,i)=><li key={i}>{x}</li>)}</ul>}
   {summary.isPending&&<p role="status">正在查詢照護摘要…</p>}
   {summary.error&&<ErrorView error={summary.error}/>}
   {summaryOpen&&<button type="button" className="secondary" disabled={summary.isPending}
    onClick={()=>summary.mutate()}>重新查詢摘要</button>}
  </details>
  {withdraw.isSuccess&&!t.report&&<p role="status">已收回，任務恢復待辦。</p>}
  </div>
  </div>
  <div className="staff-care-controls staff-care-action-column">
  {t.report?(direct?
   (canWithdraw&&<div className="staff-report-actions"><button type="button" className="secondary" disabled={withdraw.isPending}
    onClick={()=>withdraw.mutate()}>收回回報</button></div>):
   <div className="staff-report-actions"><button type="button" className="secondary" onClick={openReport}>查看回報</button></div>):
   canReport?(direct?<div className="staff-report-actions">{direct.map(([value,label])=>
    <button type="button" key={value} className="secondary" disabled={report.isPending} onClick={()=>report.mutate(value)}>{label}</button>)}</div>:
    <div className="staff-report-actions"><button type="button" className="secondary" disabled={inlinePhoto||analyzing||report.isPending} onClick={openReport}>{follow?'填寫追蹤回報':'填寫回報'}</button></div>):null}
  {photoTask&&canReport&&!reportOpen&&!inlinePhoto&&<CameraCapture cameraOnly label="拍照回報" disabled={report.isPending} onPhoto={addPhoto}/>}
  {direct&&report.error&&<ErrorView error={report.error}/>}
  {direct&&withdraw.error&&<ErrorView error={withdraw.error}/>}
  {direct&&report.isPending&&<p role="status">正在儲存回報…</p>}
  </div>
 </article>
 {inlinePhoto&&canReport&&!reportOpen&&<form className="panel space-y-3" onSubmit={e=>{e.preventDefault();if(result&&!report.isPending&&!analyzing)report.mutate(result);}}>
  <h3>拍照回報：{t.animal_name} #{t.animal_id}</h3>
  <div className="flex flex-wrap gap-2">{captured.map((photo,i)=><div key={i}><img className="care-image" src={photo} alt={`回報照片 ${i+1}`}/><button type="button" className="secondary" disabled={analyzing||report.isPending} onClick={()=>{setCaptured(v=>v.filter((_,index)=>index!==i));setAnalysis(undefined);}}>移除</button></div>)}</div>
  <CameraCapture onPhoto={addPhoto} disabled={captured.length>=4||analyzing||report.isPending}/>
  <button type="button" className="secondary" disabled={!captured.length||analyzing||report.isPending} onClick={async()=>{setAnalyzing(true);setAnalysis(undefined);setPhotoError('');try{setAnalysis(await api.analyzePhoto(captured[captured.length-1].split(',')[1],t.task_id));}catch(e){setPhotoError(e instanceof Error?e.message:String(e));}finally{setAnalyzing(false);}}}>{analyzing?'分析中…':'Gemini 分析最新照片'}</button>
  {photoError&&<p role="alert">{photoError}</p>}
  {analysis&&<div className="rounded-lg border p-3"><strong>AI 影像觀察（非診斷）</strong><p>{analysis.observation}</p><p>照片品質：{analysis.image_quality}</p><button type="button" className="secondary" disabled={report.isPending||analysis.image_quality==='unusable'} onClick={()=>setNote(v=>{const line='AI 輔助觀察（人工確認）：'+analysis.observation;return v.includes(line)?v:[v,line].filter(Boolean).join('\n').slice(0,4000);})}>採用觀察文字</button></div>}
  <div className="flex flex-wrap gap-2">{(choices[t.label]??[]).map(([value,label])=><button type="button" key={value} disabled={report.isPending} className={choice===value?'':'secondary'} aria-pressed={choice===value} onClick={()=>setChoice(value)}>{label}</button>)}</div>
  <label>情況說明（人工確認）<textarea maxLength={4000} value={note} disabled={report.isPending} onChange={e=>setNote(e.target.value)}/></label>
  <div className="flex gap-2"><button type="submit" disabled={!result||report.isPending||analyzing}>確認並送出回報</button><button type="button" className="secondary" disabled={report.isPending||analyzing} onClick={cancelReport}>取消回報</button></div>
  {report.error&&<ErrorView error={report.error}/>}
  {report.isPending&&<p role="status">{upload===undefined?'正在準備回報…':`照片上傳 ${upload}%`}</p>}
 </form>}
 {!direct&&reportOpen&&(t.report||canReport)&&createPortal(
  <div role="presentation" style={{position:'fixed',inset:0,zIndex:1000,background:'rgba(0,0,0,.48)',display:'flex',alignItems:'center',justifyContent:'center',padding:16}}>
   <form role="dialog" aria-modal="true" aria-label="任務回報" className="panel space-y-3" style={{width:'min(100%,480px)',maxHeight:'90vh',overflowY:'auto'}} onSubmit={e=>{e.preventDefault();if(!t.report&&result&&!report.isPending)report.mutate(result);}}>
    <h2>任務回報：{t.animal_name} #{t.animal_id}</h2>
    <p>{displayTaskLabel(t.label)}</p>
    {t.report?<>
     <p><strong>已回報</strong> · {t.report.result} {t.report.note}</p>
     {t.issue&&<p>{t.issue.resolved_at?'問題已解決':'待管理者處理'}</p>}
     <TaskPhotos task={t}/>
     <div className="flex gap-2">
      {canWithdraw&&<button type="button" className="secondary" disabled={withdraw.isPending}
       title="收回任務完成回報，已記錄的醫療紀錄仍會保留" onClick={()=>withdraw.mutate()}>收回完成回報</button>}
      <button type="button" className="secondary" disabled={withdraw.isPending} onClick={cancelReport}>關閉</button>
     </div>
     {withdraw.error&&<ErrorView error={withdraw.error}/>}
    </>:<>
     {!follow&&<div className="flex flex-wrap gap-2">{(choices[t.label]??[['done','完成任務']]).map(([value,label])=>
      <button type="button" key={value} disabled={report.isPending} className={choice===value?'':'secondary'} aria-pressed={choice===value} onClick={()=>setChoice(value)}>{label}</button>)}
     </div>}
     {t.label==='更新疫苗紀錄'&&<label>實際施打日期（已有可信紀錄可留空）<input type="date" max={taipeiToday()} value={dose} onChange={e=>setDose(e.target.value)}/></label>}
     {(needsNote(result)||photoTask)&&<label>情況說明（選填）<textarea value={note} onChange={e=>setNote(e.target.value)}/></label>}
     {(needsNote(result)||photoTask)&&<>
      <CameraCapture disabled={report.isPending||files.length>=4} onPhoto={data=>setFiles(prev=>prev.length<4?[...prev,photoFile(data)]:prev)}/>
      <div className="flex flex-wrap gap-2">{files.map((file,i)=><PhotoPreview key={file.name+i} file={file}/>)}</div>
      {files.length>0&&<button type="button" className="secondary" onClick={()=>setFiles([])}>清除照片</button>}
     </>}
     <div className="flex gap-2">
      <button type="submit" disabled={!result||report.isPending}>送出回報</button>
      <button type="button" className="secondary" disabled={report.isPending} onClick={cancelReport}>取消回報</button>
     </div>
     {report.error&&<ErrorView error={report.error}/>}
     {report.isPending&&<p role="status">{files.length?upload===undefined?'正在準備照片…':upload<100?`照片上傳 ${upload}%`:'照片已上傳，正在儲存回報…':'正在儲存回報…'}</p>}
    </>}
   </form>
  </div>,document.body)}
 </>;
}

export default function StaffHome({userId}:{userId:number}) {
 const [day,setDay]=useState(taipeiToday);
 const [weekly,setWeekly]=useState(false);
 const [taskFilter,setTaskFilter]=useState<'all'|'pending'|'done'>('all');
 const [mobile,setMobile]=useState(()=>window.matchMedia('(max-width: 680px)').matches);
 useEffect(()=>{const media=window.matchMedia('(max-width: 680px)');const update=()=>{setMobile(media.matches);setSelectedId(undefined)};media.addEventListener('change',update);return()=>media.removeEventListener('change',update)},[]);
 const [selectedId,setSelectedId]=useState<string>();
 const detail=useRef<HTMLElement>(null);
 useEffect(()=>{if(selectedId)detail.current?.focus();},[selectedId]);
 const query=useQuery({queryKey:['schedule-week','staff',userId,day],queryFn:()=>api.week(day),refetchInterval:15000});
 const today=taipeiToday();
 const tasks=query.data?.tasks??[];
 const worker=query.data?.workers[0];
 const days=weekly?(query.data?.days??[]):[day];
 const periodTasks=tasks.filter(t=>days.includes(t.day??'')&&t.state!=='cancelled');
 const doneCount=periodTasks.filter(t=>t.state==='done').length;
 const visibleTasks=tasks.filter(t=>taskFilter==='all'||(taskFilter==='done'?t.state==='done':t.state!=='done'&&t.state!=='cancelled'));
 const nextTask=periodTasks.filter(t=>t.state!=='done'&&t.day===today&&t.start_time).sort((a,b)=>(a.start_time??'').localeCompare(b.start_time??''))[0];
 const selected=visibleTasks.find(task=>task.task_id===selectedId&&days.includes(task.day??''));
 const go=(date:string)=>{setDay(date);setSelectedId(undefined);};
 return <section className="space-y-4">
  <h1>照護人員工作台</h1>
  <section className="panel weekly-board-panel space-y-3" data-personal-calendar-user={userId}>
   <h2>個人日曆</h2>
   {worker&&!query.isLoading&&<div className="ux-progress-panel">
    <div className="ux-heading"><strong>{weekly?'本週':day===today?'今日':'當日'}任務進度</strong><span>{doneCount}/{periodTasks.length} 已完成</span></div>
    <progress aria-label="任務完成進度" value={doneCount} max={periodTasks.length||1}/>
    <div className="ux-stats"><span>全部 <b>{periodTasks.length}</b></span><span className="ux-success">已完成 <b>{doneCount}</b></span><span className="ux-warning">待完成 <b>{periodTasks.length-doneCount}</b></span></div>
    {nextTask&&<p><strong>今日最早未完成：</strong>{nextTask.start_time} · {nextTask.animal_name} · {displayTaskLabel(nextTask.label)}</p>}
    <div className="ux-tabs" aria-label="篩選照護任務">{([['all','全部'],['pending','待完成'],['done','已完成']] as const).map(([value,label])=><button type="button" key={value} aria-pressed={taskFilter===value} className={taskFilter===value?'':'secondary'} onClick={()=>{setTaskFilter(value);setSelectedId(undefined)}}>{label}</button>)}</div>
   </div>}
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
   {worker&&mobile&&<div className="mobile-task-list">{days.map(d=><section key={d}><h3>{d}</h3>{visibleTasks.filter(t=>t.day===d&&t.state!=='cancelled').sort((a,b)=>(a.start_time??'').localeCompare(b.start_time??'')).map(t=><TaskCard key={t.task_id} task={t}/>)}{!visibleTasks.some(t=>t.day===d&&t.state!=='cancelled')&&<p className="muted">本日無任務</p>}</section>)}</div>}
   {worker&&!mobile&&<ScheduleCalendar columns={days.map(date=>({day:date,sid:worker.id,title:date.slice(5)}))}
    shifts={query.data?.shifts??[]} tasks={visibleTasks} onTask={task=>setSelectedId(task.task_id)} selectedId={selectedId} renderInline={weekly?undefined:task=><TaskCard task={task}/>}/>}
   {worker&&!visibleTasks.some(task=>task.day&&days.includes(task.day)&&task.state!=='cancelled')&&<p className="muted">這段期間沒有符合篩選的任務</p>}
  </section>
 </section>;
}
