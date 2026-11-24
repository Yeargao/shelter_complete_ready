export const healthLabel=(v:string)=>({healthy:'狀況正常',needs_review:'需要複核',serious:'嚴重・優先處理',unknown:'尚待確認'} as Record<string,string>)[v]||v;
export const priorityLabel=(v:string)=>({high:'🔴 高優先・請先處理',medium:'🟠 中優先・儘速核對',low:'🟢 一般追蹤'} as Record<string,string>)[v]||'等待核對';
export const priorityClass=(v:string)=>v==='high'?'alert-high':v==='medium'?'alert-medium':'alert-low';
export const healthClass=(v:string)=>v==='serious'?'alert-high':v==='needs_review'?'alert-medium':'alert-low';
