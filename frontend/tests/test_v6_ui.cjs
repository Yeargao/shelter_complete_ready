const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const base=path.resolve(__dirname,'../src');
const load=(p)=>fs.readFileSync(path.join(base,p),'utf8');
const health=load('pages/HealthPage.tsx');
const resource=load('pages/ResourcePage.tsx');
const timeline=load('components/common/DailyTimeline.tsx');
const presentation=load('components/common/taskPresentation.ts');
const style=load('pages/ResourceBoard.css');
const timelineStyle=load('components/common/DailyTimeline.css');
assert(health.includes('<section className="panel space-y-3 health-admin-board">')); // no collapsible parent
assert(health.includes('<details key={label}')); // group remains collapsible
assert(health.indexOf("'健康問題追蹤'") > health.indexOf("'優先確認健康狀況'"));
assert(presentation.includes('基礎驅蟲(含確認是否驅蟲)'));
assert(presentation.includes('疫苗施打(含確認是否已注射)'));
assert(timeline.includes("label==='基礎驅蟲'") && timeline.includes("label==='健康問題追蹤'"));
const schedule=load('components/common/ScheduleCalendar.tsx');
assert(schedule.includes("daily.filter(t=>t.state==='done').length"));
assert(schedule.includes('完成 ${daily.filter'));
assert(resource.includes('data-priority={t.display_priority??t.priority}'));
assert(style.includes('.weekly-event[data-priority="0"]'));
assert(timeline.includes('daily-timeline__staff-grid'));
assert(timelineStyle.includes('grid-template-columns:minmax(0,3fr) minmax(47px,1fr) minmax(0,6fr)'));
console.log('V6 source regression checks: 12 passed');
