// Deduplicate legacy snapshot rows for the same task event in the UI only.
// Historical records remain intact in SQLite.
export function visibleAssignments<T extends {task_id:string;animal_id:number;label:string;state:string;staff_id:number|null;start_time?:string|null;due_date?:string|null}>(rows:T[]):T[]{
 const treated=new Set(rows.filter(t=>t.label==='優先確認健康狀況'&&t.state==='done').map(t=>t.animal_id));
 const latest=new Map<string,T>();
 for(const row of rows){
  if(row.label==='健康狀態待確認'&&row.state==='done'&&treated.has(row.animal_id))continue;
  const cycle=row.label==='疫苗施打'?row.due_date||row.task_id.split('@')[1]||'':'';
  const key=`${row.animal_id}:${row.label}:${row.state==='done'?'done':'pending'}:${cycle}`;
  const prev=latest.get(key);
  if(!prev||((prev.staff_id==null)&&(row.staff_id!=null))||(!prev.start_time&&row.start_time))latest.set(key,row);
 }
 return [...latest.values()];
}
