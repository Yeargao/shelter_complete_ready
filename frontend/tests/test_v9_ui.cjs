// V9: pure presentation logic regressions; never opens or mutates SQLite.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const src=path.resolve(__dirname,'../src');
const timeline=fs.readFileSync(path.join(src,'components/common/DailyTimeline.tsx'),'utf8');
const css=fs.readFileSync(path.join(src,'components/common/DailyTimeline.css'),'utf8');
const page=fs.readFileSync(path.join(src,'pages/ResourcePage.tsx'),'utf8');

function extractBetween(source,start,end){
 const a=source.indexOf(start),b=source.indexOf(end,a);
 assert.ok(a>=0&&b>a,`Could not find ${start}...${end}`);
 return source.slice(a,b);
}
function evaluateTs(source,returnCode){
 const js=ts.transpileModule(`${source}\n${returnCode}`,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
 return vm.runInNewContext(js,{Map,Set,Boolean});
}
const pairSource=extractBetween(timeline,'export function adjacentQuarterHourPairs','export default function DailyTimeline');
const makePairs=evaluateTs(pairSource.replace('export function','function'),'adjacentQuarterHourPairs');
const task=(id,s,e)=>({task_id:id,s,e});
const paired=makePairs([task('A',540,555),task('B',555,570),task('C',570,600),task('D',600,660)]);
assert.equal(paired.size,2);
assert.equal(paired.get('A').side,'left');
assert.equal(paired.get('B').side,'right');
assert.equal(paired.get('A').slotStart,540);
assert.equal(paired.get('B').slotStart,540);
for(const other of [
 [task('A',540,570)],
 [task('A',540,600)],
 [task('A',600,660)],
 [task('A',555,570),task('B',570,585)],
 [task('A',540,555),task('B',555,575)],
 [task('A',540,555),task('B',555,570),task('C',550,560)],
])assert.equal(makePairs(other).size,0,'Nonmatching tasks must stay in ordinary timeline positions');
assert.match(timeline,/const paired=onTaskClick&&!compact\?adjacentQuarterHourPairs/);
assert.match(timeline,/const begin=pair\?pair\.slotStart:t\.s/);
assert.match(timeline,/const end=pair\?pair\.slotStart\+30:t\.e/);
assert.match(timeline,/!onTaskClick&&compact&&t\.e-t\.s<=15\?'daily-timeline__event--manager-short'/);
assert.match(css,/\.daily-timeline--compact \.daily-timeline__event--manager-short/);
assert.match(css,/\.daily-timeline__event--staff-paired--left/);
assert.match(css,/\.daily-timeline__event--staff-paired--right/);
assert.match(css,/\.daily-timeline__event--staff-paired \.daily-timeline__staff-answer\{display:none\}/);

const logic=extractBetween(page,' const healthReports=new Set(', ' const visible=list.filter(');
const classify=evaluateTs(`function build(assignments){\n${logic}\nreturn {isNewFollowUp,inNewQueue};\n}`,'build');
const health={animal_id:7,label:'健康狀態待確認',state:'done',result:'sick'};
const {inNewQueue}=classify({data:{assignments:[health]}});
const newTask=(animal_id,label,source,is_new=true,staff_id=null,state='pending')=>({animal_id,label,source,is_new,staff_id,state});
assert.equal(inNewQueue(newTask(2,'健康狀態待確認','rule')),false,'Original health confirmation');
assert.equal(inNewQueue(newTask(3,'疫苗紀錄待確認','rule')),false,'Original vaccine confirmation');
assert.equal(inNewQueue(newTask(4,'優先確認健康狀況','rule')),false,'Original urgent confirmation');
assert.equal(inNewQueue(newTask(7,'優先確認健康狀況','rule')),true,'Sick report derived urgent follow-up');
assert.equal(inNewQueue(newTask(8,'健康問題追蹤','employee_report')),true,'Treatment report follow-up');
assert.equal(inNewQueue(newTask(9,'疫苗施打','employee_report')),true,'Negative vaccine report follow-up');
assert.equal(inNewQueue(newTask(9,'疫苗施打','rule')),false,'Rule-created vaccine cycle not a report follow-up');
assert.equal(inNewQueue(newTask(9,'疫苗施打','employee_report',false)),false,'Existing unmarked task');
assert.equal(inNewQueue(newTask(9,'疫苗施打','employee_report',true,1)),false,'Already assigned');
assert.equal(inNewQueue(newTask(9,'疫苗施打','employee_report',true,null,'done')),false,'Completed');
assert.match(page,/tab==='new'&&inNewQueue\(t\)/);
assert.match(page,/k==='new'\?inNewQueue\(t\)/);
for(const file of ['components/common/DailyTimeline.tsx','pages/ResourcePage.tsx']){
 const out=ts.transpileModule(fs.readFileSync(path.join(src,file),'utf8'),{fileName:file,reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}});
 assert.equal(out.diagnostics.length,0,file+' TSX parses');
}
console.log('V9: classification, manager font scope, employee half-hour side-by-side, exceptions and TSX parsing passed');
