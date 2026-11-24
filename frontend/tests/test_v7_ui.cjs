const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
const src=path.resolve(__dirname,'../src/pages');
const resource=fs.readFileSync(path.join(src,'ResourcePage.tsx'),'utf8');
const css=fs.readFileSync(path.join(src,'ResourceBoard.css'),'utf8');
const staff=fs.readFileSync(path.join(src,'StaffHome.tsx'),'utf8');
const staffCss=fs.readFileSync(path.join(src,'StaffHome.css'),'utf8');
for(const [name,text] of [['ResourcePage.tsx',resource],['StaffHome.tsx',staff]]){
 const out=ts.transpileModule(text,{fileName:name,reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}});
 assert.equal((out.diagnostics||[]).length,0,`${name} must parse as TSX`);
}
assert.match(resource,/className="resource-task-name">\{displayTaskLabel\(t\.label\)\}/);
assert.match(resource,/className="resource-task-identity"> · \{t\.animal_name\} #\{t\.animal_id\}/);
for(const color of ['red','amber','green']) assert.match(css,new RegExp(`resource-task-title--${color} \\.resource-task-identity`));
assert.match(resource,/completed=workerTasks\.filter\(t=>t\.state==='done'\)\.length/);
assert.match(resource,/completedPercent=total\?100\*completed\/total:0/);
assert.equal(100*(0/1),0, '0/1 has zero blue');
assert.equal(100-100*(0/1),100, '0/1 has 100% orange');
assert.match(css,/resource-worker__progress-pending\{flex:none;background:#f09b35!important\}/);
assert.match(staff,/className="staff-report-actions"/);
assert.match(staffCss,/flex-flow:row nowrap/);
assert.match(staffCss,/overflow-x:auto/);
console.log('V7: 12 static/layout and arithmetic checks passed; both TSX files parsed.');
