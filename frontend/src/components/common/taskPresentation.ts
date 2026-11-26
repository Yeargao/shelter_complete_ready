// Only transform labels for presentation; historical SQLite task identifiers stay unchanged.
export const healthTaskLabels=['優先確認健康狀況','健康狀態待確認','健康問題追蹤','確認驅蟲紀錄','基礎驅蟲','補做驅蟲','確認疫苗紀錄','疫苗紀錄待確認','疫苗施打','評估絕育安排'];
export const displayTaskLabel=(label:string)=>label==='優先確認健康狀況'?'傷病治療':label;
export const reportText=(value?:string|null,resolved?:string|null)=>resolved==='no'?'否':resolved==='yes'?'是':value==='no'?'否':value==='yes'?'是':value==='healthy'?'健康':value==='sick'?'生病':value==='injured'?'受傷':value||'—';

// Health administration group titles only; task records and other section names remain unchanged.
export const healthGroupTitle=(label:string)=>label==='基礎驅蟲'?'基礎驅蟲(含確認是否驅蟲)':label==='疫苗施打'?'疫苗施打(含確認是否已注射)':displayTaskLabel(label);
