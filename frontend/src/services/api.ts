import type { Animal, AnimalInput, ModuleResult } from "../types";

const base = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(base + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(sessionStorage.getItem("shelter_token") ? { Authorization: `Bearer ${sessionStorage.getItem("shelter_token")}` } : {}), ...options?.headers },
  });
  if (!response.ok) {
    let message = `請求失敗（${response.status}）`;
    try {
      const body = await response.json();
      message = body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : body.error?.message || message;
    } catch {
      message = `請求失敗（${response.status}）`;
    }
    throw new Error(message);
  }
  return response.json();
}

export type ShelterProfile = {
  id: number;
  shelter_id: string;
  name: string;
  capacity: number;
  budget: number;
  staff_hours: number;
  food_rate: number;
  care_minutes: number;
  unit_cost: number;
  food_stock_kg: number;
};

export type Staff = {id:number;profile_id:number;name:string;skills:string[];available_hours:number;scheduled_hours:number;attending:boolean;weekly_hours:number;shift_start:string;shift_end:string;break_start:string|null;break_end:string|null};
export type Task = {id:string;animal_id:number;animal_name:string;category:string;skill:string;label:string;hours:number;serious:boolean;state:"pending"|"done"|"removed";due_date?:string|null;priority?:number;source?:string;is_new?:boolean;completed_at?:string|null;result?:string|null;note?:string|null};
export type CareSummary = {
 animal_summary:string; known_issues:string[]; observations:string[]; unconfirmed:string[];
 mode:'llm'|'cache'|'rule_based'; fallback_reason:string|null; source_record_ids:string[];
};
export type ChatAnswer = {answer:string;source:'db'|'rules'|'gemini';sources:string[];
 context:string|null;fallback_reason:string|null;queried_at:string};
export type LlmUsage = {day:string;local_daily_budget:number;used:number;successes:number;failures:number;
 chat_requests:number;chat_interactions:number;summary_requests:number;cache_hit_rate:number|null;rule_answers:number;
 connection:string;cooling:boolean;last_error:string|null};
export type WeeklyTask = {
 task_id:string; animal_id:number; animal_name:string; label:string; priority:number; hours:number;
 earliest:string; due:string|null; day:string|null; staff_id:number|null; start_time:string|null; recurring:number; skill:string;
 end_time:string|null; state:string; locked:number; reason:string|null; note:string|null;
 species:string; breed:string|null; age_months:number|null; health_status:string; photo_url:string|null;
 is_active:number; is_new?:boolean; is_derived?:boolean; display_priority?:number; photos:string[]; issue:{resolved_at:string|null}|null; report:{result:string;note:string;reported_at:string}|null;
 summary?:CareSummary;
};
export type Placement = [number|null,string|null,number|null];
export type WeeklyShift = Staff & {day:string;assignable_hours?:number;daily_capacity_hours?:number;break_windows?:[string,string][]};
export type Week = {days:string[]; event_id:number; workers:Staff[]; shifts:WeeklyShift[]; tasks:WeeklyTask[];
 schedule_status:string|null;overdue:Pick<WeeklyTask,'task_id'|'label'|'due'|'day'|'animal_name'>[]};
export type Plan = {plan_id:string|null;solver_status:string;changes:{task_id:string;animal_name:string;label:string;before:Placement;after:Placement;reason:string|null;adjustment_reason:string}[]};
export const api = {
  withdrawReport:(id:string)=>request<{ok:boolean}>(`/api/schedule/tasks/${encodeURIComponent(id)}/withdraw-report`,{method:'POST'}),
  chat:(question:string,context:string|null,signal:AbortSignal)=>request<ChatAnswer>('/api/chat',
    {method:'POST',body:JSON.stringify({question,context}),signal}),
  llmUsage:()=>request<LlmUsage>('/api/llm/usage'),
  taskSummary:(id:string)=>request<CareSummary>(`/api/schedule/tasks/${encodeURIComponent(id)}/summary`,{method:'POST'}),
  week:(week:string)=>request<Week>(`/api/schedule/week?week=${week}&rolling=true`),
  previewWeek:(week:string)=>request<Plan>(`/api/schedule/preview?week=${week}&rolling=true`,{method:'POST'}),
  applyWeek:(id:string)=>request<object>(`/api/schedule/apply/${id}`,{method:'POST'}),
  place:(id:string,body:{staff_id:number|null;day?:string;start_time?:string;locked?:boolean})=>request<object>(`/api/schedule/tasks/${encodeURIComponent(id)}/placement`,{method:'PATCH',body:JSON.stringify(body)}),
  createWeeklyTask:(body:object)=>request<object>('/api/schedule/tasks',{method:'POST',body:JSON.stringify(body)}),
  saveShift:(s:WeeklyShift)=>request<object>(`/api/schedule/shifts/${s.id}/${s.day}`,{method:'PUT',body:JSON.stringify(s)}),
  resolveIssue:(id:string)=>request<object>('/api/schedule/tasks/'+encodeURIComponent(id)+'/resolve',{method:'POST'}),
  taskEvent:(id:string,body:object)=>request<object>('/api/schedule/tasks/'+encodeURIComponent(id)+'/event',{method:'POST',body:JSON.stringify(body)}),
  async taskPhoto(id:string,photo:string) {
   const response=await fetch(base+'/api/schedule/tasks/'+encodeURIComponent(id)+'/photos/'+encodeURIComponent(photo),{headers:{Authorization:'Bearer '+sessionStorage.getItem('shelter_token')}});
   if(!response.ok)throw Error('無法讀取回報照片');
   return response.blob();
  },
  reportWeekly:(id:string,body:object,onUpload?: (percent:number)=>void)=>{
   const path=`/api/schedule/tasks/${encodeURIComponent(id)}/report`;
   if(!onUpload)return request<object>(path,{method:'POST',body:JSON.stringify(body)});
   return new Promise<object>((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    xhr.open('POST',base+path);
    xhr.timeout=60000;
    xhr.responseType='json';
    xhr.setRequestHeader('Content-Type','application/json');
    const token=sessionStorage.getItem('shelter_token');
    if(token)xhr.setRequestHeader('Authorization',`Bearer ${token}`);
    xhr.upload.onprogress=event=>{if(event.lengthComputable)onUpload(Math.round(event.loaded/event.total*100));};
    xhr.onerror=()=>reject(Error('照片上傳連線失敗'));
    xhr.ontimeout=()=>reject(Error('照片上傳逾時，請確認任務狀態後重試'));
    xhr.onload=()=>{
     if(xhr.status>=200&&xhr.status<300&&xhr.response?.ok)resolve(xhr.response);
     else reject(Error(typeof xhr.response?.detail==='string'?xhr.response.detail:`回報失敗（HTTP ${xhr.status}）`));
    };
    xhr.send(JSON.stringify(body));
   });
  },
  animalNeeds:()=>request<Array<{id:number;name:string;species:string;food_grams_per_day:number|null;routine_care_hours_per_day:number|null;resource_source?:string}>>('/api/resources/animal-needs'),
  batchReassign:(task_ids:string[],staff_id:number)=>request<{results:object[];count:number}>('/api/staff/assignments/batch',{method:'POST',body:JSON.stringify({task_ids,staff_id})}),
  reassign:(task_id:string,staff_id:number)=>request<object>(`/api/staff/assignments/${encodeURIComponent(task_id)}`,{method:'PATCH',body:JSON.stringify({staff_id})}),
  staffAssignments:()=>request<{assignments:Array<{task_id:string;animal_id:number;animal_name:string;staff_id:number|null;staff_name:string|null;category:string;label:string;date:string|null;hours:number;state:string;start_time?:string|null;end_time?:string|null;result?:string|null;resolved?:string|null;note?:string|null;administered_date?:string|null}>;planning_start:string;reset_mode?:boolean;note:string}>("/api/staff/assignments"),
  tasks:()=>request<Task[]>("/api/tasks"),
  setTask:(body:{animal_id:number;label:string;state:"pending"|"done"|"removed";result?:"healthy"|"sick"|"injured"|"yes"|"no";resolved?:"yes"|"no";note?:string;administered_date?:string;edit_report?:boolean})=>request<object>("/api/tasks",{method:"PUT",body:JSON.stringify(body)}),
  staff:(profile_id:number)=>request<Staff[]>(`/api/resources/staff?profile_id=${profile_id}`),
  createStaff:(body:Omit<Staff,"id">)=>request<Staff>("/api/resources/staff",{method:"POST",body:JSON.stringify(body)}),
  updateStaff:(id:number,body:Omit<Staff,"id">)=>request<Staff>(`/api/resources/staff/${id}`,{method:"PUT",body:JSON.stringify(body)}),
  deleteStaff:(id:number)=>request<{deleted:boolean}>(`/api/resources/staff/${id}`,{method:"DELETE"}),
  animals: (q = "", species = "", dataset = "user", skip = 0, limit = 50) => request<Animal[]>(`/api/animals?q=${encodeURIComponent(q)}&species=${encodeURIComponent(species)}&dataset=${encodeURIComponent(dataset)}&skip=${skip}&limit=${limit}`),
  summary: () => request<Record<string, unknown>>("/api/stats/summary"),
  evaluation: () => request<Record<string, unknown>>("/api/model/evaluation"),
  stage2Evaluation: () => request<any>("/api/stage2/evaluation?days=30"),
  animal: (id: number) => request<Animal>(`/api/animals/${id}`),
  create: (animal: AnimalInput) => request<Animal>("/api/animals", { method: "POST", body: JSON.stringify(animal) }),
  update: (id: number, animal: Partial<AnimalInput>) => request<Animal>(`/api/animals/${id}`, { method: "PATCH", body: JSON.stringify(animal) }),
  adoption: (id: number) => request<ModuleResult>(`/api/adoption/predict?animal_id=${id}`, { method: "POST" }),
  health: (id: number) => request<ModuleResult>(`/api/health/assess?animal_id=${id}`, { method: "POST" }),
  resourceOverview: () => request<{date:string;current_count:number;capacity:number;remaining_capacity:number;daily_food_kg:number;daily_care_hours:number;available_hours:number;pending_tasks:number;urgent_tasks:number;open_issues:number;schedule_status:string}>('/api/schedule/overview'),
  profiles: () => request<ShelterProfile[]>("/api/resources/profiles"),
  createProfile: (body: Omit<ShelterProfile, "id" | "shelter_id">) => request<ShelterProfile>("/api/resources/profiles", { method: "POST", body: JSON.stringify(body) }),
  updateProfile: (id: number, body: Omit<ShelterProfile, "id" | "shelter_id">) => request<ShelterProfile>(`/api/resources/profiles/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProfile: (id: number) => request<{ deleted: boolean }>(`/api/resources/profiles/${id}`, { method: "DELETE" }),
  exitAnimal: ({id,exit_date,exit_reason}:{id:number;exit_date:string;exit_reason:string}) => request<{ exited: boolean }>(`/api/animals/${id}/exit`, { method: "POST", body:JSON.stringify({exit_date,exit_reason}) }),
  exitedAnimals: (q = "") => request<Animal[]>(`/api/animals/exited?q=${encodeURIComponent(q)}`),
  readmitAnimal: ({id,intake_date}:{id:number;intake_date:string}) => request<Animal>(`/api/animals/${id}/readmit`, { method: "POST", body:JSON.stringify({intake_date}) }),
  animalStays: (id: number) => request<Array<{intake_date:string;exit_date:string|null;exit_reason:string|null}>>(`/api/animals/${id}/stays`),
  resetTasksPending: () => request<{reset:boolean;tasks_reset:number;derived_tasks_cleared:number}>("/api/tasks/reset-pending", { method: "POST" }),
  healthBatch: () => request<Array<Record<string, unknown>>>("/api/health/batch"),
  demoSnapshot: () => request<Record<string, unknown>>("/api/demo/snapshot"),
  demoResetA: () => request<{mode:string;backup:string;message:string}>("/api/demo/reset/A",{method:"POST",body:JSON.stringify({mode:"A",confirm:"RESET_TASKS"})}),
};
