const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
const src=path.resolve(__dirname,'../src/pages');
const resource=fs.readFileSync(path.join(src,'ResourcePage.tsx'),'utf8');
const css=fs.readFileSync(path.join(src,'ResourceBoard.css'),'utf8');
const staff=fs.readFileSync(path.join(src,'StaffHome.tsx'),'utf8');
const staffCss=fs.readFileSync(path.join(src,'StaffHome.css'),'utf8');
const schedule=fs.readFileSync(path.join(src,'../components/common/ScheduleCalendar.tsx'),'utf8');
for(const [name,text] of [['ResourcePage.tsx',resource],['StaffHome.tsx',staff]]){
 const out=ts.transpileModule(text,{fileName:name,reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}});
 assert.equal((out.diagnostics||[]).length,0,`${name} must parse as TSX`);
}
assert.match(resource,/\{t.animal_name\} #\{t.animal_id\}/);
assert.match(resource,/衍生任務/);
assert.doesNotMatch(resource,/只顯示高優先級|任務日期不符/);
assert.match(css,/data-priority="0"/);
assert.match(css,/data-priority="1"/);
assert.match(schedule,/daily\.filter\(t=>t.state==='done'\)\.length/);
assert.match(schedule,/daily\.length/);
assert.match(resource,/<ScheduleCalendar/);
assert.match(staff,/<ScheduleCalendar/);
assert.match(staff,/flex flex-wrap gap-2/);
assert.match(css,/@media\(max-width:850px\)/);
assert.match(staffCss,/\.care-image/);
console.log('Calendar progress, priority emphasis, task identity, mobile layout and TSX checks passed.');
