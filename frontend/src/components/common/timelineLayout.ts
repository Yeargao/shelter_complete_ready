/** Presentation-only interval partitioning. Never changes the scheduling timestamps. */
export type TimeInterval={task_id:string;s:number;e:number};
export type TimeColumn={index:number;count:number};
export function timelineColumns(events:TimeInterval[]):Map<string,TimeColumn>{
 const result=new Map<string,TimeColumn>();
 const sorted=[...events].sort((a,b)=>a.s-b.s||a.e-b.e||a.task_id.localeCompare(b.task_id));
 let group:TimeInterval[]=[];
 let groupEnd=-Infinity;
 const flush=()=>{
  if(!group.length)return;
  const laneEnds:number[]=[];
  const assigned:{id:string;index:number}[]=[];
  for(const task of group){
   let lane=laneEnds.findIndex(end=>end<=task.s);
   if(lane<0){lane=laneEnds.length;laneEnds.push(task.e)}else laneEnds[lane]=task.e;
   assigned.push({id:task.task_id,index:lane});
  }
  for(const entry of assigned)result.set(entry.id,{index:entry.index,count:laneEnds.length});
  group=[];
 };
 for(const event of sorted){
  if(group.length&&event.s>=groupEnd)flush();
  group.push(event);groupEnd=Math.max(groupEnd,event.e);
 }
 flush();
 return result;
}
