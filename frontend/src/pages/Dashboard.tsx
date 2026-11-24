import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { CartesianGrid, Area, AreaChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../services/api';
import { ErrorView, Loading } from '../components/common/States';
export default function Dashboard(){
 const summary=useQuery({queryKey:['summary'],queryFn:api.summary});
 const forecast=useQuery({queryKey:['forecast',30],queryFn:()=>api.forecast(30)});
 const [days,setDays]=React.useState<7|14|30>(14);
 const displayStart=80; // 展示情境，不改動資料庫中的實際在養數
 const adjustment=displayStart-(forecast.data?.current_count??displayStart);
 const data=(forecast.data?.forecast.slice(0,days)||[]).map(point=>({...point,expected_occupancy:Math.max(0,point.expected_occupancy+adjustment),lower_bound:Math.max(0,point.lower_bound+adjustment),upper_bound:Math.max(0,point.upper_bound+adjustment)}));
 return <section className="space-y-6">
  <div className="hero"><div className="eyebrow">SHELTER INTELLIGENCE / LIVE MODEL INFERENCE</div><h1>智慧收容所管理總覽</h1><p>以 80 隻的展示預測情境為起點，整合健康分類、送養分析與 CatBoost 收容量預測。</p><span className="demo-tag">展示資料 · 非真實收容紀錄</span></div>
  {summary.isLoading&&<Loading/>}{summary.error&&<ErrorView error={summary.error}/>}
  <div className="grid md:grid-cols-4 gap-4">
   <div className="metric"><span className="text-[4.5rem] leading-tight">🐾 目前在養</span><strong>{String(summary.data?.in_care_count??'…')} <small>隻</small></strong><p>資料庫動態統計</p></div>
   <div className="metric"><span className="text-[4.5rem] leading-tight">🐶 犬隻</span><strong>{String(summary.data?.dog_count??'…')}</strong><p>展示名單</p></div>
   <div className="metric"><span className="text-[4.5rem] leading-tight">🐱 貓隻</span><strong>{String(summary.data?.cat_count??'…')}</strong><p>展示名單</p></div>
   <div className="metric"><span className="text-[4.5rem] leading-tight">🩺 健康待核對</span><strong>{String(summary.data?.review_count??'…')}</strong><p>依登錄狀態統計</p></div>
  </div>
<div className="grid md:grid-cols-3 gap-4"><Link className="quick" to="/animals">動物名單 <span>查看與管理 →</span></Link><Link className="quick" to="/health">健康行政核對 <span>健康任務核對 →</span></Link><Link className="quick" to="/resources">資源配置 <span>容量與人力試算 →</span></Link></div>
  <div className="panel space-y-4"><div className="flex flex-wrap justify-between items-center gap-3"><div><h2>收容數量預測</h2><p className="muted">CatBoost 雙模型 · 入所 / 離所遞迴推估 · 歷史截止日 2026/10/22</p></div><div className="flex gap-2">{([7,14,30] as const).map(n=><button key={n} className={days===n?'':'secondary'} onClick={()=>setDays(n)}>{n} 天</button>)}</div></div>
  {forecast.isLoading&&<Loading/>}{forecast.error&&<ErrorView error={forecast.error}/>}
  {forecast.data&&<><div className="h-72"><ResponsiveContainer width="100%" height="100%"><AreaChart data={[{date:'基準',expected_occupancy:displayStart,lower_bound:displayStart,upper_bound:displayStart},...data]}><defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#0d9488" stopOpacity={.3}/><stop offset="100%" stopColor="#0d9488" stopOpacity={.02}/></linearGradient></defs><CartesianGrid stroke="#e2e8f0" strokeDasharray="4 4"/><XAxis dataKey="date" tick={{fontSize:11}}/><YAxis domain={['auto','auto']}/><Tooltip/><Area dataKey="upper_bound" name="上界（未校正）" stroke="#d97706" fill="none" strokeDasharray="5 4"/><Area dataKey="lower_bound" name="下界（未校正）" stroke="#94a3b8" fill="none" strokeDasharray="5 4"/><Area dataKey="expected_occupancy" name="預估在養" stroke="#0f766e" strokeWidth={3} fill="url(#grad)"/></AreaChart></ResponsiveContainer></div><p className="muted">圖表從 80 隻開始，使用原始預測每日增減量建立展示情境（不改動實際資料庫數量）；80 隻是展示基準，不是歷史資料的真實在養量；上下界為歷史變異數推算的未校正情境帶，並非經回測校正的預測區間。</p></>}
  </div>
 </section>
}
