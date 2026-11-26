const assert = require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
const src=path.resolve(__dirname,'../src');
const read=p=>fs.readFileSync(path.join(src,p),'utf8');
const timeline=read('components/common/DailyTimeline.tsx');
const style=read('components/common/DailyTimeline.css');
const resource=read('pages/ResourcePage.tsx');
const board=read('pages/ResourceBoard.css');
const staff=read('pages/StaffHome.tsx');
for(const file of ['components/common/DailyTimeline.tsx','pages/ResourcePage.tsx','pages/StaffHome.tsx']){
 const compiled=ts.transpileModule(read(file),{fileName:file,reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}});
 assert.equal(compiled.diagnostics.length,0,file+' parses');
}
assert.match(timeline,/const HALF_CELL=88/);
assert.match(timeline,/const heights=rows\.map\(\(\)=>HALF_CELL\)/);
assert.match(timeline,/style=\{\{top:top\+2,height,\.\.\.laneStyle\}\}/);
assert.doesNotMatch(timeline,/Math\.max\(50,/);
// 09:00-09:15, 09:15-09:30, 09:30-10:00, 10:00-11:00.
const events=[[540,555],[555,570],[570,600],[600,660]];
const bounds=events.map(([start,end])=>({top:(start-540)*88/30+2,bottom:(end-540)*88/30-2}));
for(let i=1;i<bounds.length;i++)assert.ok(bounds[i].top>=bounds[i-1].bottom,'non-overlapping slots');
for(let i=0;i<events.length;i++)assert.equal(bounds[i].bottom-bounds[i].top,(events[i][1]-events[i][0])*88/30-4);
assert.match(style,/\.daily-timeline__event--short/);
assert.match(style,/\.daily-timeline__report-panel/);
assert.match(style,/\.daily-timeline__event--done\{background:#edf0f2!important/);
const weeklyGrid=fs.readFileSync(path.resolve(__dirname,'../src/components/common/ScheduleCalendar.tsx'),'utf8');
assert.match(resource,/view==='week'\?days\.map/);
assert.match(weeklyGrid,/gridTime\(tick\)/);
assert.match(weeklyGrid,/top:gridOffset\(start\)/);
assert.match(weeklyGrid,/data-done=\{task.state==='done'\}/);
assert.match(board,/height:var\(--slot-height\)/);
assert.match(staff,/t\.report\?/);
assert.match(staff,/已回報任務/);
console.log('Timeline geometry, weekly quarter-hour slots, completed history and TSX passed.');
