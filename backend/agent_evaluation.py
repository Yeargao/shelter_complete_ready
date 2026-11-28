"""Deterministic offline regression suite. All mutations use an isolated in-memory fixture."""
from contextlib import contextmanager
from datetime import date, datetime
import sqlite3
import time
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4
from fastapi import HTTPException
import chat_agent as agent
import chat_intent as ci

def fixture():
    db=sqlite3.connect(':memory:',check_same_thread=False)
    db.row_factory=sqlite3.Row
    db.executescript("""
      CREATE TABLE animals(id INTEGER PRIMARY KEY,name TEXT,is_active INTEGER,intake_date TEXT,health_status TEXT,vaccinated TEXT,dewormed TEXT);
      INSERT INTO animals VALUES(1,'Lulu',1,'2020-01-01','unknown','unknown','unknown'),(2,'Mimi',1,'2020-01-01','healthy','unknown','unknown');
      CREATE TABLE deworming_events(animal_id INTEGER,intake_date TEXT,completed_date TEXT,source TEXT,PRIMARY KEY(animal_id,intake_date));
      CREATE TABLE vaccination_records(id INTEGER PRIMARY KEY,animal_id INTEGER,vaccine_type TEXT,administered_date TEXT,next_due_date TEXT,source TEXT,UNIQUE(animal_id,vaccine_type,administered_date));
      CREATE TABLE weekly_events(id INTEGER PRIMARY KEY,animal_id INTEGER,event TEXT);
    """)
    agent.migrate(db);db.commit()
    return db

def evaluate():
    cases=[]; timings=[]; edit_expected=[]; edit_pred=[]; slot_tp=slot_fp=slot_fn=0
    current=date(2026,11,28)
    examples=[
      ('健康：健康',{'health_status':'healthy'},{}),
      ('Lulu的健康登錄為「健康」。 疫苗紀錄：是。 驅蟲紀錄：已驅蟲。',{'health_status':'healthy','vaccinated':'yes','dewormed':'yes'},{}),
      ('驅蟲日期：1128',{'dewormed':'yes'},{'deworming_date':'2026-11-28'}),
      ('Lulu驅蟲日期：1128',{'dewormed':'yes'},{'deworming_date':'2026-11-28'}),
      ('Lulu已驅蟲，驅蟲日期：1128',{'dewormed':'yes'},{'deworming_date':'2026-11-28'}),
      ('Lulu 疫苗日期：20261128',{'vaccinated':'yes'},{'vaccination_date':'2026-11-28'}),
      ('Lulu 健康嗎？',None,{}),('查詢 Lulu 驅蟲日期',None,{}),('Lulu 資料',None,{}),
      ('幫他安排明天的健康問題追蹤任務',None,{}),('改回來',None,{}),
      ('Lulu可能已驅蟲',None,{}),('不要改成健康',None,{}),
      ('Lulu 健康：生病；疫苗：否',{'health_status':'sick','vaccinated':'no'},{}),
    ]
    multi_tp=multi_fp=multi_fn=0
    for q,wanted,wanted_dates in examples:
        t=time.perf_counter()
        try:
            got=agent.parse_edit(q,current)
            actual=got['changes'] if got else None
            dates=got['dates'] if got else {}
            ok=actual==wanted and dates==wanted_dates
            detail=str(actual)+' '+str(dates)
        except Exception as e:
            actual=None;dates={};ok=False;detail=str(e)
        timings.append((time.perf_counter()-t)*1000)
        edit_expected.append(wanted is not None);edit_pred.append(actual is not None)
        exp=set((wanted or {}).items())|set(wanted_dates.items());pred=set((actual or {}).items())|set(dates.items())
        slot_tp+=len(exp&pred);slot_fp+=len(pred-exp);slot_fn+=len(exp-pred)
        expected_fields=set((wanted or {}).keys());pred_fields=set((actual or {}).keys())
        multi_tp+=len(expected_fields&pred_fields);multi_fp+=len(pred_fields-expected_fields);multi_fn+=len(expected_fields-pred_fields)
        cases.append({'name':q,'passed':ok,'detail':detail})
    dates_ok=[]
    for q,wanted in [('1128','2026-11-28'),('11/28','2026-11-28'),('11月28日','2026-11-28'),('今天','2026-11-28'),('昨天','2026-11-27'),('三天前','2026-11-25'),('20261128','2026-11-28'),('0230',None)]:
        try:actual=agent.normalize_date(q,current).isoformat()
        except ValueError:actual=None
        ok=actual==wanted;dates_ok.append(ok);cases.append({'name':'日期：'+q,'passed':ok,'detail':str(actual)})
    db=fixture()
    @contextmanager
    def connect():
        with db:yield db
    legacy=SimpleNamespace(connect=connect,lock=RLock(),AUTH_SECRET=b'isolated-evaluation',month_after=lambda d,n:d.replace(year=d.year+1))
    # Read adapter is a deterministic fixture, not a live database or Gemini benchmark.
    def read_chat(body,request):
        aid=agent.resolve(db,body.question)
        context=ci.encode_context(legacy.AUTH_SECRET,'fixture',{'intent':'animal_health','animal_id':aid,'start':current.isoformat(),'end':current.isoformat(),'period':'all_day','sort':'none'}) if aid else None
        return {'answer':'fixture','sources':['fixture'] if aid else [],'context':context,'source':'db','queried_at':current.isoformat(),'fallback_reason':None}
    def unsupported(*args):raise AssertionError('unexpected legacy tool')
    router=agent.mount(legacy,read_chat,unsupported,unsupported)
    chat=next(r.endpoint for r in router.routes if r.path=='/api/agent/chat')
    action=next(r.endpoint for r in router.routes if r.path=='/api/agent/actions/{action_id}')
    uid=SimpleNamespace(state=SimpleNamespace(user_id=1),headers={'Authorization':'fixture'})
    staff=SimpleNamespace(state=SimpleNamespace(user_id=2),headers={'Authorization':'fixture'})
    session=uuid4().hex
    def send(q,who=uid,sid=session):
        return chat(agent.AgentInput(question=q,session_id=sid),who)['turns'][-1]
    def execute(cmd,who=uid,decision='confirm',sid=session):
        return action(cmd['action_id'],agent.ActionInput(session_id=sid,decision=decision),who)
    results={}
    def test(name,fn):
        try:
            fn();ok=True;detail='符合預期'
        except Exception as e:
            ok=False;detail=type(e).__name__+': '+str(e)
        cases.append({'name':name,'passed':ok,'detail':detail});results[name]=ok
    draft_holder={}
    def context_test():
        send('Lulu 資料')
        cmd=send('健康：健康')['command']
        assert cmd['animal_id']==1 and cmd['type']=='animal_action'
        assert agent.snapshot(db,1)['health_status']=='unknown'
        draft_holder['health']=cmd
    test('上下文與未確認不寫入',context_test)
    def apply_test():
        cmd=draft_holder['health'];execute(cmd)
        assert agent.snapshot(db,1)['health_status']=='healthy'
    test('確認健康修改',apply_test)
    def multiple():
        cmd=send('Lulu的健康登錄為「健康」。疫苗紀錄：是。驅蟲紀錄：已驅蟲。')['command']
        assert len(cmd['changes'])==3;execute(cmd)
        s=agent.snapshot(db,1);assert s['vaccinated']=='yes' and s['dewormed']=='yes' and not s['deworming']
    test('多欄位原子修改及不虛構日期',multiple)
    def date_test():
        q='驅蟲日期：'+agent.today().strftime('%m%d')
        cmd=send(q)['command'];execute(cmd)
        s=agent.snapshot(db,1);assert s['deworming'][0]['completed_date']==agent.today().isoformat()
        draft_holder['date']=cmd
    test('省略對象的驅蟲日期寫入',date_test)
    def duplicate():
        cmd=draft_holder['date'];before=agent.snapshot(db,1);r=execute(cmd)
        assert r['duplicate'] and agent.snapshot(db,1)==before
    test('重複確認不重複寫入',duplicate)
    def undo():
        cmd=send('改回來')['command'];assert cmd['kind']=='undo';execute(cmd)
        assert not agent.snapshot(db,1)['deworming']
        assert db.execute('SELECT count(*) FROM ai_medical_corrections').fetchone()[0]>=2
    test('復原與醫療更正稽核',undo)
    def denied():
        before=agent.snapshot(db,1)
        r=send('Lulu 健康：生病',staff,uuid4().hex)
        assert r['command']['type']=='clarify'
        try:execute(draft_holder['health'],staff)
        except HTTPException as e:assert e.status_code==403
        else:raise AssertionError('staff action allowed')
        assert agent.snapshot(db,1)==before
    test('員工未授權修改及確認',denied)
    def conflict():
        cmd=send('Lulu 健康：生病')['command']
        db.execute("UPDATE animals SET health_status='injured' WHERE id=1");db.commit()
        try:execute(cmd)
        except HTTPException as e:assert e.status_code==409
        else:raise AssertionError('stale action allowed')
        assert agent.snapshot(db,1)['health_status']=='injured'
    test('資料變動阻擋過期草案',conflict)
    def unknown():
        cmd=send('Nemo 健康：健康')['command'];assert cmd['type']=='clarify'
        cmd=send('小白 健康：健康')['command'];assert cmd['type']=='clarify'
    test('未知對象不沿用 Lulu',unknown)
    def missing_date():
        sid=uuid4().hex
        send('Lulu 資料',sid=sid)
        assert send('驅蟲日期：',sid=sid)['command']['type']=='clarify'
        c=send(agent.today().strftime('%m%d'),sid=sid)['command']
        assert c['type']=='animal_action' and c['animal_id']==1
        execute(c,decision='cancel',sid=sid)
    test('日期缺漏後續補齊',missing_date)
    import care_workflow as care
    from care_dialogue_cases import DIALOGUES
    import care_dialogue as cd
    db.executescript("""
      CREATE TABLE staff(id INTEGER PRIMARY KEY,profile_id INTEGER);
      INSERT INTO staff VALUES(1,1);
      CREATE TABLE weekly_staff_accounts(user_id INTEGER,staff_id INTEGER);
      INSERT INTO weekly_staff_accounts VALUES(2,1);
      CREATE TABLE weekly_tasks(task_id TEXT PRIMARY KEY,animal_id INTEGER,label TEXT,day TEXT,state TEXT,staff_id INTEGER);
    """)
    recognition=[];transitions=[]
    for label,phrase,expected_code,expected_next in DIALOGUES:
        tid=uuid4().hex;sid=uuid4().hex;actual=None;preview='';correct=False;transition=False
        try:
            with db:
                db.execute('DELETE FROM weekly_tasks')
                db.execute("INSERT INTO weekly_tasks VALUES (?,?,?,?,'pending',1)",(tid,1,label,agent.today().isoformat()))
            q='Lulu '+phrase
            first=send(q+' 下一步',staff,sid)
            preview=first.get('answer',{}).get('answer','')
            answer=send(q,staff,sid)
            if answer.get('command',{}).get('type')=='clarify':
                msg=answer['command']['message']
                if '施打日期' in msg:answer=send(agent.today().isoformat(),staff,sid)
                elif '略過備註' in msg:answer=send('略過備註',staff,sid)
            cmd=answer.get('command',{})
            actual=cmd.get('result')
            correct=cmd.get('type')=='staff_report' and cmd.get('task_id')==tid and actual==expected_code
            marker=care.display_label(expected_next) if expected_next else '結束'
            transition=correct and not first.get('command') and marker in preview and len(preview)<160
        except Exception as exc:
            preview=type(exc).__name__+': '+str(exc)
        recognition.append(correct);transitions.append(transition)
        cases.append({'name':'新手對話 · '+care.display_label(label)+'／'+phrase+' 下一步 → 回報','passed':correct and transition,
                      'detail':'辨識：'+str(actual)+'；'+preview})
    db.close()
    surgery=care.next_task('更新絕育狀態','done',from_surgery=True)=='術後健康追蹤'
    transitions.append(surgery)
    cases.append({'name':'絕育手術來源 · 更新絕育狀態','passed':surgery,'detail':'應接續術後健康追蹤'})
    def pct(v,n):return round(100*v/n,2) if n else None
    def metric(name,v,n,detail,unit='%'):return {'name':name,'value':v,'unit':unit,'n':n,'detail':detail}
    def group(names):return pct(sum(results.get(n,False) for n in names),len(names))
    task_names=['確認健康修改','多欄位原子修改及不虛構日期','省略對象的驅蟲日期寫入']
    context_names=['上下文與未確認不寫入','未知對象不沿用 Lulu']
    metrics=[
      metric('Care Outcome Recognition',pct(sum(recognition),len(recognition)),len(recognition),'獨立口語情境的隔離 chatbot 對話與回報草案辨識；非 Gemini 或真實流量泛化測試'),
      metric('Care Transition Coverage',pct(sum(transitions),len(transitions)),len(transitions),'獨立口語情境及預期轉移；完整 HTTP 多輪測試另見 tests/test_care_workflow_dialogue.py'),
      metric('Intent Accuracy',pct(sum(a==b for a,b in zip(edit_expected,edit_pred)),len(examples)),len(examples),'本機修改候選二元辨識；非全意圖分類'),
      metric('Multi-intent F1',pct(2*multi_tp,2*multi_tp+multi_fp+multi_fn),len(examples),'多欄位意圖 micro-F1；不含所有舊有查詢類別'),
      metric('Slot F1',pct(2*slot_tp,2*slot_tp+slot_fp+slot_fn),len(examples),'欄位與標準化日期精確配對 micro-F1'),
      metric('Joint Goal Accuracy',group(context_names),len(context_names),'隔離對話案例的對象與目標狀態核對'),
      metric('Date Parsing Accuracy',pct(sum(dates_ok),len(dates_ok)),len(dates_ok),'固定 2026-11-28 基準日期'),
      metric('Task Success Rate',group(task_names),len(task_names),'隔離 SQLite 修改操作完成率'),
      metric('Undo Success Rate',group(['復原與醫療更正稽核']),1,'隔離醫療更正案例'),
      metric('Unauthorized Execution Rate',0 if results.get('員工未授權修改及確認') else None,1,'隔離角色拒絕案例；失敗時不推估比例'),
      metric('LLM Invocation Rate',None,0,'本套件未發送 Gemini；正式流量比例尚未量測'),
      metric('Average Response Time',round(sum(timings)/len(timings),3),len(timings),'本機欄位解析平均延遲；非網路端到端','ms'),
      metric('Duplicate Execution Rate',0 if results.get('重複確認不重複寫入') else None,1,'隔離重複確認案例；失敗時不推估比例'),
    ]
    return {'at':datetime.now(agent.TZ).isoformat(),'metrics':metrics,'cases':cases}
