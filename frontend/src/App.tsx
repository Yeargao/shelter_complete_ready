import AgentEvaluation from './pages/AgentEvaluation';
import './mobile.css';
import ShelterChat from './components/common/ShelterChat';
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import { NavLink,Route,Routes,Navigate } from 'react-router-dom';
import AnimalCreate from './pages/AnimalCreate';import AnimalDetail from './pages/AnimalDetail';import AnimalList from './pages/AnimalList';import Dashboard from './pages/Dashboard';import HealthPage from './pages/HealthPage';import EvaluationPage from './pages/EvaluationPage';import ResourcePage from './pages/ResourcePage';import StaffHome from './pages/StaffHome';
const links=[['/','總覽','▦'],['/animals','動物列表','♧'],['/health','健康行政核對','♡'],['/resources','資源配置','◈'],['/ai-tools','AI','✦']];
export default function App(){
 const queries=useQueryClient();
 const [session,setSession]=useState<{token:string;role:string;user_id:number}|null>(()=>{try{return JSON.parse(sessionStorage.getItem('shelter_session')||'null')}catch{return null}});
 const [sidebarCollapsed,setSidebarCollapsed]=useState(false);
 const [password,setPassword]=useState('');const [error,setError]=useState('');
 const [warming,setWarming]=useState(false);
 const [backendReady,setBackendReady]=useState(false);
 const [loggingIn,setLoggingIn]=useState(false);
 const [slowLogin,setSlowLogin]=useState(false);
 const inFlight=useRef(false);
 const warmRequest=useRef<Promise<boolean>|null>(null);
 const apiOrigin=(import.meta.env.VITE_API_URL||'').replace(/\/+$/,'');
 const loggedIn=!!session;

 useEffect(()=>{
  if(loggedIn)return;
  // Warm only on entry to the login page. Reuse the request under React StrictMode.
  let active=true;
  setWarming(true);
  setBackendReady(false);
  if(!warmRequest.current){
   const controller=new AbortController();
   const timer=window.setTimeout(()=>controller.abort(),75000);
   warmRequest.current=fetch(apiOrigin+'/healthz',{cache:'no-store',signal:controller.signal})
    .then(async r=>r.ok&&(await r.json()).status==='ok')
    .catch(()=>false)
    .finally(()=>window.clearTimeout(timer));
  }
  const pending=warmRequest.current;
  void pending.then(ok=>{
   if(active){setWarming(false);setBackendReady(ok);}
  });
  return ()=>{active=false;};
 },[loggedIn,apiOrigin]);

 async function login(e:FormEvent<HTMLFormElement>){
  e.preventDefault();
  if(inFlight.current)return;
  inFlight.current=true;
  setLoggingIn(true);setSlowLogin(false);setError('');
  const slowTimer=window.setTimeout(()=>setSlowLogin(true),8000);
  const controller=new AbortController();
  const timeout=window.setTimeout(()=>controller.abort(),90000);
  try{
   // Let an already-started cold boot finish before sending credentials.
   if(warmRequest.current)await warmRequest.current;
   // A single deadline covers both waiting for prewarm and login.
   const r=await fetch(apiOrigin+'/api/auth/login',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password}),signal:controller.signal
   });
   if(!r.ok)throw Error(r.status===401?'密碼錯誤':`登入 API 請求失敗（HTTP ${r.status}）`);
   if(!r.headers.get('content-type')?.includes('application/json'))throw Error('登入 API 未回傳 JSON，請檢查 Vercel API 轉送設定');
   const data=await r.json();
   if(typeof data.token!=='string'||typeof data.role!=='string'||typeof data.user_id!=='number')throw Error('登入 API 回傳格式錯誤');
   sessionStorage.setItem('shelter_token',data.token);
   sessionStorage.setItem('shelter_session',JSON.stringify(data));
   setPassword('');setSession(data);
  }catch(e){
   setError(controller.signal.aborted?'登入連線逾時，後端可能仍在啟動，請稍後再試。':e instanceof Error?e.message:String(e));
  }finally{
   window.clearTimeout(slowTimer);
   window.clearTimeout(timeout);
   inFlight.current=false;setLoggingIn(false);setSlowLogin(false);
  }
 }

 if(!session)return <main className="min-h-screen flex items-center justify-center bg-slate-50 p-5">
  <form className="panel w-full max-w-sm space-y-4" onSubmit={login} aria-busy={loggingIn}>
   <h1>智慧收容所登入</h1>
   {import.meta.env.VITE_SHELTER_DEMO!=='false'&&<p className="muted">展示帳號：管理者 01；照護人員 02～06</p>}
   <label>密碼<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required disabled={loggingIn} autoComplete="current-password"/></label>
   {error&&<p role="alert" className="text-red-700">{error}</p>}
   <button type="submit" disabled={loggingIn} className="flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed">
    {loggingIn&&<span aria-hidden="true" className="inline-block h-4 w-4 rounded-full border-2 border-current border-r-transparent animate-spin"/>}
    {loggingIn?'登入中…':'登入'}
   </button>
   <div role="status" aria-live="polite" className="text-sm muted">
    {loggingIn?(slowLogin?'正在連線至後端伺服器。若後端剛從休眠喚醒，首次登入可能需要約一分鐘，請勿重複送出。':'正在驗證登入…'):
      warming?'正在預先連線至後端，您可以先輸入密碼。':
      backendReady?'後端已連線。':'尚未確認後端連線；仍可嘗試登入。'}
   </div>
  </form>
 </main>;
 const manager=session.role==='manager';
 return <div className={`app-shell ${sidebarCollapsed?'app-shell--nav-collapsed':''}`}><aside className="sidebar"><button type="button" className="sidebar-collapse-toggle" aria-label={sidebarCollapsed?'展開導覽列':'收合導覽列'} title={sidebarCollapsed?'展開導覽列':'收合導覽列'} aria-expanded={!sidebarCollapsed} onClick={()=>setSidebarCollapsed(v=>!v)}>{sidebarCollapsed?'❯':'❮'}</button><div className="brand"><div className="brand-icon">✦</div><div><strong>Shelter AI</strong><small>智慧收容管理平台</small></div></div><div className="sidebar-label">工作空間</div><nav>{(manager?links:[['/','照護人員工作台','▦'],['/animals','動物列表','♧']]).map(([to,label,icon])=><NavLink key={to} to={to} end title={label} className={({isActive})=>isActive?'nav-item active':'nav-item'}><span>{icon}</span>{label}</NavLink>)}</nav><div className="sidebar-footer"><button className="secondary" onClick={()=>{Object.keys(sessionStorage).filter(k=>k.startsWith('shelter-smart-v1:')).forEach(k=>sessionStorage.removeItem(k));sessionStorage.removeItem('shelter_token');sessionStorage.removeItem('shelter_session');queries.clear();warmRequest.current=null;setError('');setPassword('');setSession(null)}}>登出 · {manager?'管理者':`照護人員 ${String(session.user_id).padStart(2,'0')}`}</button><div><div className="online-dot"/> 健康與收容管理{import.meta.env.VITE_SHELTER_DEMO!=='false'&&<div className="text-xs opacity-60 mt-1">示範展示環境</div>}</div></div></aside><div className="main-column"><header className="topbar"><span>動物收容所智慧決策支援系統</span>{import.meta.env.VITE_SHELTER_DEMO!=='false'&&<span className="top-pill">展示環境</span>}</header><main className="content"><Routes><Route path="/" element={manager?<Dashboard/>:<StaffHome userId={session.user_id}/>}/><Route path="/animals" element={<AnimalList/>}/><Route path="/animals/new" element={manager?<AnimalCreate/>:<Navigate to="/animals" replace/>}/><Route path="/animals/:id" element={<AnimalDetail/>}/><Route path="/health" element={manager?<HealthPage/>:<StaffHome userId={session.user_id}/>}/><Route path="/resources" element={manager?<ResourcePage/>:<StaffHome userId={session.user_id}/>}/><Route path="/ai-tools" element={manager?<AgentEvaluation/>:<Navigate to="/" replace/>}/><Route path="/evaluation" element={manager?<EvaluationPage/>:<StaffHome userId={session.user_id}/>}/></Routes></main></div><ShelterChat key={session.token} manager={manager}/></div>}
