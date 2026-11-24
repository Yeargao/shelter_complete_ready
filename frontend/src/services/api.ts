import type { Animal, AnimalInput, Forecast, ModuleResult } from "../types";

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
export const api = {
  needsForecast:(days:number)=>request<{mode:string;forecast:Array<{date:string;expected_food_kg:number;food_lower_kg:number;food_upper_kg:number;expected_care_hours:number;care_lower_hours:number;care_upper_hours:number}>;daily_food_kg:number;daily_care_hours:number;animal_count:number;estimated_animals:number;individual_predictions?:Array<{animal_id:number;days_in_shelter:number;conditional_survival_30d:number;tail_extrapolated:boolean;resource_source:string}>;extrapolated_or_sparse_animals?:number;imputed_animals?:number;warnings?:string[];note:string}>(`/api/resources/needs-forecast?days=${days}`),
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
  forecast: (days: number) => request<Forecast>(`/api/occupancy/forecast?days=${days}`),
  resources: (body: object) => request<ModuleResult>("/api/resources/optimize", { method: "POST", body: JSON.stringify(body) }),
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
