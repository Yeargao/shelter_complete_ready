import {ReminderPanel} from '../components/common/SmartPanels';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import ResourceOverview from '../components/common/ResourceOverview';
import LlmUsage from '../components/common/LlmUsage';

export default function Dashboard() {
 return <section className="space-y-6">
  <div className="hero"><h1>智慧收容所管理總覽</h1></div>
  <ResourceOverview/>
  <div className="grid md:grid-cols-3 gap-4">
   {[
    {to:'/animals',title:'動物名單',action:'查看與管理'},
    {to:'/health',title:'健康行政核對',action:'健康任務核對'},
    {to:'/resources',title:'資源配置',action:'查看與管理排程'},
   ].map(({to,title,action})=><Link className="quick dashboard-link" to={to} key={to}>
    <strong>{title}</strong><span>{action}<ArrowRight size={16} aria-hidden="true"/></span>
   </Link>)}
  </div>
  <ReminderPanel/>
  <LlmUsage/>
 </section>;
}
