import { useQuery } from '@tanstack/react-query';
import {Link} from 'react-router-dom';
import { api } from '../../services/api';
import { ErrorView, Loading } from './States';

export default function ResourceOverview() {
 const { data, error } = useQuery({
  queryKey: ['resource-overview'],
  queryFn: api.resourceOverview,
  refetchInterval: 30000,
 });
 if (error) return <ErrorView error={error}/>;
 if (!data) return <Loading/>;
 const metrics = [
  ['目前在養', data.current_count, '隻'],
  ['收容容量', data.capacity, '隻'],
  ['剩餘名額', data.remaining_capacity, '隻'],
  ['今日可配置工時', data.available_hours, '小時'],
  ['今日未完成任務', data.pending_tasks, '件'],
  ['本週派工狀態', data.schedule_status==='applied'?'已套用':'待更新', ''],
 ];
 return <section className="panel space-y-3">
  <h2>即時資源概況</h2>
  <p className="muted">{data.date}（臺灣時間）</p>
  <div className="ux-alert-grid">
    <Link className="ux-alert ux-danger" to="/resources"><strong>高優先級任務</strong><b>{data.urgent_tasks} 件</b><span>前往資源配置 →</span></Link>
    <Link className="ux-alert ux-warning" to="/health"><strong>待處理異常</strong><b>{data.open_issues} 件</b><span>前往健康行政核對 →</span></Link>
   </div>
   {data.capacity>0&&<div className="ux-progress-panel"><div className="ux-heading"><strong>收容率</strong><b>{Math.round(data.current_count/data.capacity*100)}%</b></div><progress aria-label="收容容量使用率" max={data.capacity} value={Math.min(data.current_count,data.capacity)}/><span className="muted">{data.current_count} / {data.capacity} 隻</span></div>}
   <div className="overview-grid">
   {metrics.map(([label, value, unit]) => <div className="metric" key={label}>
    <span>{label}</span><strong>{value} <small>{unit}</small></strong>
   </div>)}
  </div>
  <details><summary>規則式資源估算</summary>
   <p>每日飼料需求 {data.daily_food_kg} kg，基礎照護需求 {data.daily_care_hours} 小時。</p>
  </details>
 </section>;
}
