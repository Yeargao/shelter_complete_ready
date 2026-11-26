
import { useEffect, useState } from 'react';
import { api, type WeeklyTask } from '../../services/api';

function Photo({task,id}:{task:string;id:string}) {
 const [src,setSrc]=useState('');
 const [failed,setFailed]=useState(false);
 useEffect(()=>{
  let active=true, url='';
  api.taskPhoto(task,id).then(blob=>{
   if(active){url=URL.createObjectURL(blob);setSrc(url);}
  }).catch(()=>{if(active)setFailed(true);});
  return()=>{active=false;if(url)URL.revokeObjectURL(url);};
 },[id,task]);
 return failed?<span>無法顯示照片</span>:src?<img width={160} className="rounded-lg" src={src} alt="照護回報照片"/>:null;
}

export default function TaskPhotos({task}:{task:WeeklyTask}) {
 return <div className="flex flex-wrap gap-2">{task.photos.map(id=><Photo key={id} task={task.task_id} id={id}/>)}</div>;
}
