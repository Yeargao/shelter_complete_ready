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

const pool=extractBetween(page,' const pool=',' const go=');
const inPool=evaluateTs(`function filter(tasks,search){${pool}return pool;}`,'filter');
const urgent={task_id:'urgent',animal_id:7,animal_name:'Test',label:'健康問題追蹤',priority:0,state:'pending',is_active:1};
const ordinary={...urgent,task_id:'ordinary',priority:4,label:'基礎照護'};
const data=[urgent,ordinary,{...urgent,task_id:'done',state:'done'},
 {...urgent,task_id:'placed',staff_id:3},{...urgent,task_id:'exited',is_active:0}];
assert.equal(inPool(data,'健康問題追蹤').map(x=>x.task_id).join(','),'urgent');
assert.equal(inPool(data,'基礎照護').map(x=>x.task_id).join(','),'ordinary');
assert.equal(inPool(data,'7').map(x=>x.task_id).join(','),'urgent,ordinary');
for(const file of ['components/common/DailyTimeline.tsx','pages/ResourcePage.tsx']){
 const out=ts.transpileModule(fs.readFileSync(path.join(src,file),'utf8'),{fileName:file,reportDiagnostics:true,compilerOptions:{jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}});
 assert.equal(out.diagnostics.length,0,file+' TSX parses');
}
console.log('V9: classification, manager font scope, employee half-hour side-by-side, exceptions and TSX parsing passed');
