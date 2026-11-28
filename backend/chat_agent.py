"""Local-first agent: explicit drafts, role-scoped reads and transactional administrative corrections."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
import re
import time
import unicodedata
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
import chat_intent as ci
import care_workflow as care
from chat_workflows import guide as work_guide
from shelter_chat import Question
from smart_tools import Command, Check, report

TZ=ZoneInfo('Asia/Taipei')
FIELDS={'health_status':'健康','vaccinated':'疫苗','dewormed':'驅蟲'}
HEALTH={'健康':'healthy','生病':'sick','受傷':'injured','嚴重':'serious','嚴重狀況':'serious','待確認':'needs_review','未確認':'unknown','未知':'unknown'}
TRI={'是':'yes','有':'yes','已接種':'yes','已施打':'yes','已驅蟲':'yes','否':'no','無':'no','未接種':'no','未施打':'no','未驅蟲':'no','待確認':'unknown','未確認':'unknown','未知':'unknown'}
DISPLAY={**{v:k for k,v in HEALTH.items()},'yes':'是','no':'否','unknown':'未確認'}
DATE_KEYS={'vaccination_date':'疫苗日期','deworming_date':'驅蟲日期'}
UNDO=re.compile(r'^(?:請|幫我)?(?:改回來|改回去|復原|撤銷|撤回|還原|取消上次修改)[。！!？?]*$')
CANCEL=re.compile(r'^(?:算了|取消|不要改|算了不要改|取消修改|取消草案)[。！!]*$')
QUERY=re.compile(r'[?？]|(?:嗎|呢|如何|什麼|多少|幾隻|幾項|哪隻|哪些|有沒有|是否|何時|哪天|怎麼樣)[。！!\s]*$|^(?:請|幫我)?(?:查詢|查一下|查|查看|想知道|請問|列出|顯示|搜尋|找出|有哪些|哪隻|哪些|統計)')
FIELD_WORDS=r'健康(?:登錄|狀況|狀態)?|疫苗(?:紀錄|狀態|接種日期|施打日期|日期)?|驅蟲(?:紀錄|狀態|日期)?'
VALS='|'.join(sorted(set(HEALTH)|set(TRI),key=len,reverse=True))
FIELD_RE=re.compile(r'('+FIELD_WORDS+r')\s*(?:為|是|改成|改為|設為|更新為|[:：=])\s*[「"“]?\s*('+VALS+r')(?=[」"”\s，,。；;、！!]|$)')
DIRECT_RE=re.compile(r'(?:已驅蟲|未驅蟲|已接種|未接種|已施打|未施打)')
DATE_RE=re.compile(r'((?:驅蟲|疫苗(?:接種|施打)?)日期)\s*(?:為|是|改成|改為|[:：=])?\s*([0-9０-９年月日/\-]+|今天|昨天|前天|[一二三四五六七八九十\d]+天前)')
SMART=re.compile(r'提醒|通知|統計|報表|分布|完成率|開啟|前往|我要新增動物|工作流程|自動化流程|(?:新增|建立|安排|加一個|加一項).*任務')
def today():
    return datetime.now(TZ).date()
def stamp():
    return datetime.now(TZ).isoformat()
def dump(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def norm(x):
    return unicodedata.normalize('NFKC',x).strip()
def normalize_date(raw,current):
    v=norm(raw)
    if v in ('今天','昨天','前天'):
        return current-timedelta(days=('今天','昨天','前天').index(v))
    m=re.fullmatch(r'([一二三四五六七八九十]|\d{1,3})天前',v)
    if m:
        n='一二三四五六七八九十'.index(m[1])+1 if not m[1].isdigit() else int(m[1])
        return current-timedelta(days=n)
    v=v.replace('年','-').replace('月','-').replace('日','').replace('/','-')
    try:
        if re.fullmatch(r'\d{4}',v):
            return date(current.year,int(v[:2]),int(v[2:]))
        if re.fullmatch(r'\d{8}',v):
            return date(int(v[:4]),int(v[4:6]),int(v[6:]))
        if re.fullmatch(r'\d{1,2}-\d{1,2}',v):
            m,d=map(int,v.split('-'));return date(current.year,m,d)
        y,m,d=map(int,v.split('-'))
        if not 1900<=y<=9999:raise ValueError()
        return date(y,m,d)
    except (ValueError,OverflowError):
        raise ValueError('日期無效，請輸入 YYYY-MM-DD 或月日，例如 1128') from None

def parse_edit(text,current):
    """Only explicit assertions become drafts, never questions or invented dates."""
    q=norm(text)
    if QUERY.search(q) or re.search(r'(?:已驅蟲|已接種|已施打|未驅蟲)的(?:資料|日期|紀錄)',q):return None
    if re.search(r'診斷|劑量|開藥|用藥|給藥|不要|不用|不是|假設|如果|是否|可能|好像|應該|尚未確定|不確定',q):return None
    if re.search(r'任務|工作流程|提醒|通知|報表|統計|回報|完成|哪些|有沒有|哪天|何時|多少|幾隻|幾個|所有|全部|清單|列表|名單|查詢|查看',q):return None
    changes={}
    dates={}
    def put(key,value):
        if key in changes and changes[key]!=value:raise ValueError('同一欄位有矛盾的數值，請確認')
        changes[key]=value
    for m in FIELD_RE.finditer(q):
        field,val=m.groups()
        key='health_status' if field.startswith('健康') else 'vaccinated' if field.startswith('疫苗') else 'dewormed'
        if '日期' in field:continue
        vocab=HEALTH if key=='health_status' else TRI
        if val not in vocab:raise ValueError('欄位數值不適用')
        if key=='vaccinated' and '驅蟲' in val or key=='dewormed' and val in ('已接種','未接種','已施打','未施打'):
            raise ValueError('欄位數值不適用')
        put(key,vocab[val])
    for m in DIRECT_RE.finditer(q):
        # Explicit field expressions already consumed by the same value are harmless.
        if m[0] in ('已驅蟲','未驅蟲'):put('dewormed',TRI[m[0]])
        else:put('vaccinated',TRI[m[0]])
    m=re.search(r'(?:改成|改為|是|為)\s*([「"])?(健康|生病|受傷|嚴重狀況|待確認|未確認)(?:[」"])?(?:[。！!]|$)',q)
    if m and not changes:put('health_status',HEALTH[m[2]])
    if not changes and re.search(r'是健康的[。！!]*$',q):put('health_status','healthy')
    for m in DATE_RE.finditer(q):
        key='deworming_date' if m[1].startswith('驅蟲') else 'vaccination_date'
        d=normalize_date(m[2],current)
        if d>current:raise ValueError('實際醫療日期不可晚於今日')
        if key in dates and dates[key]!=d.isoformat():raise ValueError('日期互相矛盾，請確認')
        dates[key]=d.isoformat()
        put('dewormed' if key=='deworming_date' else 'vaccinated','yes')
    if re.search(r'(?:驅蟲|疫苗(?:接種|施打)?)日期\s*[:：=]',q) and not dates:
        raise ValueError('請提供有效醫療日期')
    # Avoid partially applying an invalid or omitted explicit field.
    for m in re.finditer(r'('+FIELD_WORDS+r')\s*[:：=]',q):
        field=m[1]
        key=('deworming_date' if field.startswith('驅蟲') else 'vaccination_date') if '日期' in field else 'health_status' if field.startswith('健康') else 'vaccinated' if field.startswith('疫苗') else 'dewormed'
        if key not in changes and key not in dates:raise ValueError('請提供有效的'+field+'數值')
    if not changes and not dates:return None
    return {'changes':changes,'dates':dates}

def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS ai_chat_sessions(
        user_id INTEGER NOT NULL, session_id TEXT NOT NULL, animal_id INTEGER,
        read_context TEXT, missing_json TEXT, PRIMARY KEY(user_id,session_id))""")
    if 'guide_topic' not in {r[1] for r in db.execute('PRAGMA table_info(ai_chat_sessions)')}:
        db.execute('ALTER TABLE ai_chat_sessions ADD COLUMN guide_topic TEXT')
    db.execute("""CREATE TABLE IF NOT EXISTS ai_action_history(
        action_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,session_id TEXT NOT NULL,
        animal_id INTEGER NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,
        before_data TEXT NOT NULL,after_data TEXT,status TEXT NOT NULL,
        created_at TEXT NOT NULL,completed_at TEXT,undo_of TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS ai_medical_corrections(
        id INTEGER PRIMARY KEY,action_id TEXT NOT NULL,animal_id INTEGER NOT NULL,
        before_data TEXT NOT NULL,after_data TEXT NOT NULL,created_at TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS ai_history_session ON ai_action_history(user_id,session_id,created_at)")

def snapshot(db,aid):
    a=db.execute('SELECT id,name,is_active,intake_date,health_status,vaccinated,dewormed FROM animals WHERE id=?',(aid,)).fetchone()
    if not a:raise HTTPException(404,'找不到動物')
    d=dict(a)
    d['deworming']=[dict(r) for r in db.execute('SELECT * FROM deworming_events WHERE animal_id=? ORDER BY intake_date',(aid,))]
    d['vaccinations']=[dict(r) for r in db.execute('SELECT * FROM vaccination_records WHERE animal_id=? ORDER BY id',(aid,))]
    d['event_id']=db.execute('SELECT COALESCE(MAX(id),0) FROM weekly_events WHERE animal_id=?',(aid,)).fetchone()[0]
    return d

def resolve(db,q,active=None,allow_active=False):
    animals=[dict(r) for r in db.execute('SELECT id,name FROM animals ORDER BY id')]
    def name_matches(a):
        name=norm(a['name'] or '').casefold()
        if not name:return False
        if re.fullmatch(r'[a-z0-9 ]+',name):
            return bool(re.search(r'(?<![a-z0-9])'+re.escape(name)+r'(?![a-z0-9])',q.casefold()))
        return name in q.casefold()
    named=[a for a in animals if name_matches(a)]
    named=[a for a in named if not any(a['name']!=b['name'] and a['name'].casefold() in b['name'].casefold() for b in named)]
    animal_q=re.sub(r'(?:員工|照顧人員|照護人員)\s*#?\s*\d{1,6}(?!\d)','',q)
    ids=re.findall(r'(?:動物\s*#?|#)\s*(\d{1,18})(?!\d)',animal_q)
    if len(set(ids))>1:raise ValueError('請指定單一動物編號')
    if ids:
        a=next((a for a in animals if a['id']==int(ids[0])),None)
        if not a:raise ValueError('找不到動物 #'+ids[0])
        if named and (not any(b['id']==a['id'] for b in named) or any(b['name'].casefold()!=a['name'].casefold() for b in named)):raise ValueError('名稱與編號不一致')
        return a['id']
    if len(named)>1:raise ValueError('找到多個動物：'+'、'.join(f"{a['name']} #{a['id']}" for a in named[:10])+'，請指定編號')
    if named:return named[0]['id']
    # An unfamiliar explicit Latin name must not silently fall back to the last animal.
    if re.search(r'[A-Za-z]{2,}',q):return None
    # Detect a new unrecognised subject before a field assignment (Chinese names included).
    m=re.match(r'^(.+?)的(?:健康|疫苗|驅蟲)',q)
    if m and m[1] not in ('他','她','牠','它','這隻','該動物','幫他','幫牠','請幫他'):return None
    subjectless=re.match(r'^(?:那|所以|另外|請|幫我|幫他|幫她|幫牠|他|她|牠|它|這隻|該動物|把|將|更正|修改|更新|登錄|設定|改成|改為|的|\s)*(?:健康|疫苗|驅蟲|已驅蟲|未驅蟲|已接種|未接種|已施打|未施打)',q)
    return active if allow_active and subjectless else None

def describe_edit(before,payload):
    rows=[]
    for key,val in payload['changes'].items():
        rows.append({'field':FIELDS[key],'before':DISPLAY.get(before[key],before[key] or '未確認'),'after':DISPLAY.get(val,val)})
    for key,val in payload['dates'].items():
        old=next((r['completed_date'] for r in before['deworming'] if r['intake_date']==before['intake_date']),None) if key=='deworming_date' else (max((r['administered_date'] for r in before['vaccinations']),default=None))
        rows.append({'field':DATE_KEYS[key],'before':old or '無日期紀錄','after':val})
    return rows

def draft(db,uid,sid,aid,payload,current,kind='edit',undo_of=None):
    before=snapshot(db,aid)
    if not before['is_active']:raise HTTPException(409,'動物已離所，請使用原有歷史資料核對流程')
    if kind=='edit':
        for key,val in payload['dates'].items():
            d=date.fromisoformat(val)
            if d>current or (key=='deworming_date' and val<before['intake_date']):
                raise HTTPException(422,'驅蟲日期須在本次入所期間，醫療日期不可晚於今日')
        old=next((r for r in before['deworming'] if r['intake_date']==before['intake_date']),None)
        if old and payload['dates'].get('deworming_date') not in (None,old['completed_date']) and not payload.get('correction'):
            raise HTTPException(409,'已有驅蟲日期，請明確輸入「更正驅蟲日期：日期」')
        if payload.get('correction') and 'vaccination_date' in payload['dates']:
            records=[r for r in before['vaccinations'] if r['vaccine_type']=='general']
            if len(records)!=1:
                raise HTTPException(409,'更正疫苗日期需有唯一的一般疫苗紀錄；多筆時請使用原有行政核對流程')
            payload['vaccination_correction_id']=records[0]['id']
        if payload['changes'].get('dewormed')=='no' and old:
            raise HTTPException(409,'本次入所有驅蟲紀錄，請先核對醫療紀錄')
        if payload['changes'].get('vaccinated')=='no' and before['vaccinations']:
            raise HTTPException(409,'已有疫苗紀錄，請先核對醫療紀錄')
        changes=describe_edit(before,payload)
    else:
        changes=payload['display']
    db.execute("UPDATE ai_action_history SET status='cancelled' WHERE user_id=? AND session_id=? AND animal_id=? AND status='pending'",(uid,sid,aid))
    aid_action=uuid4().hex
    db.execute("INSERT INTO ai_action_history VALUES (?,?,?,?,?,?,?,NULL,'pending',?,NULL,?)",
               (aid_action,uid,sid,aid,kind,dump(payload),dump(before),stamp(),undo_of))
    return {'type':'animal_action','action_id':aid_action,'animal_id':aid,'name':before['name'],'kind':kind,'changes':changes}

def restore_medical(db,before,target,action_id):
    # The active projection is corrected; the append-only correction ledger retains both versions.
    aid=before['id']
    for key,table,pk in [('deworming','deworming_events','intake_date'),('vaccinations','vaccination_records','id')]:
        old={r[pk]:r for r in before[key]}
        new={r[pk]:r for r in target[key]}
        for k in old.keys()-new.keys():
            db.execute(f'DELETE FROM {table} WHERE animal_id=? AND {pk}=?',(aid,k))
        for k,row in new.items():
            if k in old and old[k]==row:continue
            if k in old:
                cols=[c for c in row if c not in (pk,'animal_id')]
                db.execute(f'UPDATE {table} SET '+','.join(c+'=?' for c in cols)+f' WHERE animal_id=? AND {pk}=?',(*[row[c] for c in cols],aid,k))
            else:
                cols=list(row)
                db.execute(f'INSERT INTO {table} ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(row.values()))
    db.execute('INSERT INTO ai_medical_corrections(action_id,animal_id,before_data,after_data,created_at) VALUES (?,?,?,?,?)',
               (action_id,aid,dump({k:before[k] for k in ('deworming','vaccinations')}),dump({k:target[k] for k in ('deworming','vaccinations')}),stamp()))

def apply_action(db,uid,sid,action_id,month_after,current):
    if uid!=1:raise HTTPException(403,'此操作需要管理者權限')
    r=db.execute('SELECT * FROM ai_action_history WHERE action_id=? AND user_id=? AND session_id=?',(action_id,uid,sid)).fetchone()
    if not r:raise HTTPException(404,'草案不存在或無權限')
    if r['status']=='applied':return {'message':'已執行（不重複修改）','status':'applied','duplicate':True}
    if r['status']!='pending':raise HTTPException(409,'草案已取消或失效')
    before=json.loads(r['before_data']);payload=json.loads(r['payload']);aid=r['animal_id']
    if snapshot(db,aid)!=before or not before['is_active']:
        raise HTTPException(409,'資料已被其他操作更新，請重新產生草案')
    if r['kind']=='undo':
        original=db.execute("SELECT * FROM ai_action_history WHERE action_id=? AND user_id=? AND session_id=? AND status='applied'",(r['undo_of'],uid,sid)).fetchone()
        if not original or json.loads(original['after_data'])!=before:
            raise HTTPException(409,'原操作已變更，無法復原')
        target=json.loads(original['before_data'])
        db.execute('UPDATE animals SET health_status=?,vaccinated=?,dewormed=? WHERE id=?',(target['health_status'],target['vaccinated'],target['dewormed'],aid))
        if any(before[k]!=target[k] for k in ('deworming','vaccinations')):restore_medical(db,before,target,action_id)
        db.execute("UPDATE ai_action_history SET status='undone' WHERE action_id=?",(original['action_id'],))
    else:
        changes=payload['changes']
        if not changes or any(k not in FIELDS for k in changes):raise HTTPException(422,'不支援的欄位')
        for key,val in changes.items():
            if val not in (set(HEALTH.values()) if key=='health_status' else set(TRI.values())):raise HTTPException(422,'欄位值無效')
        db.execute('UPDATE animals SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',(*changes.values(),aid))
        dates=payload['dates']
        if 'deworming_date' in dates:
            d=dates['deworming_date']
            if not before['intake_date']<=d<=current.isoformat():raise HTTPException(422,'驅蟲日期無效')
            db.execute("""INSERT INTO deworming_events(animal_id,intake_date,completed_date,source) VALUES (?,?,?,?)
                ON CONFLICT(animal_id,intake_date) DO UPDATE SET completed_date=excluded.completed_date
                WHERE deworming_events.completed_date!=excluded.completed_date""",(aid,before['intake_date'],d,'chat:'+action_id))
        if 'vaccination_date' in dates:
            d=date.fromisoformat(dates['vaccination_date'])
            if d>current:raise HTTPException(422,'疫苗日期無效')
            if payload.get('vaccination_correction_id'):
                db.execute('UPDATE vaccination_records SET administered_date=?,next_due_date=? WHERE id=? AND animal_id=?',(d.isoformat(),month_after(d,12).isoformat(),payload['vaccination_correction_id'],aid))
            else:
                db.execute('INSERT OR IGNORE INTO vaccination_records(animal_id,vaccine_type,administered_date,next_due_date,source) VALUES (?,?,?,?,?)',(aid,'general',d.isoformat(),month_after(d,12).isoformat(),'chat:'+action_id))
        after=snapshot(db,aid)
        if any(before[k]!=after[k] for k in ('deworming','vaccinations')):
            db.execute('INSERT INTO ai_medical_corrections(action_id,animal_id,before_data,after_data,created_at) VALUES (?,?,?,?,?)',(action_id,aid,dump({k:before[k] for k in ('deworming','vaccinations')}),dump({k:after[k] for k in ('deworming','vaccinations')}),stamp()))
    after=snapshot(db,aid)
    if after!=before:
        db.execute("INSERT INTO weekly_events(animal_id,event) VALUES (?,'chat_correction')",(aid,))
        after=snapshot(db,aid)
    db.execute("UPDATE ai_action_history SET status='applied',after_data=?,completed_at=? WHERE action_id=?",(dump(after),stamp(),action_id))
    return {'message':('已復原 ' if r['kind']=='undo' else '已更新 ')+before['name'],'status':'applied','duplicate':False}

class AgentInput(BaseModel):
    question:str=Field(min_length=1,max_length=500)
    session_id:str=Field(pattern=r'^[a-f0-9-]{32,36}$')
class ActionInput(BaseModel):
    session_id:str=Field(pattern=r'^[a-f0-9-]{32,36}$')
    decision:str=Field(pattern=r'^(confirm|cancel)$')

def mount(legacy,read_chat,smart_command,smart_check,populate_tasks=None):
    router=APIRouter(prefix='/api/agent')
    def turn(question,**kwargs):return {'question':question,**kwargs}
    def message(question,text):return turn(question,command={'type':'clarify','message':text})
    @router.post('/chat')
    def chat(body:AgentInput,request:Request):
        uid=request.state.user_id;sid=body.session_id
        raw=norm(body.question)
        if not raw:raise HTTPException(422,'請輸入指令')
        parts=[s.strip() for s in re.split(r'[；;\n]+|(?:，|,)\s*(?=並|再|另外)|(?:並且|並)(?=幫|安排|新增|建立|統計|開啟)',raw) if s.strip()]
        if len(parts)>6:raise HTTPException(422,'一次最多六項操作')
        # Multi-field assignments separated by semicolons remain one atomic edit.
        if len(parts)>1:
            try:
                if all(parse_edit(p,today()) is not None for p in parts):
                    with legacy.connect() as db:
                        subjects={resolve(db,p) for p in parts}
                    if len(subjects-{None})<=1:parts=[raw]
            except ValueError:
                pass
        result=[]
        with legacy.lock,legacy.connect() as db:
            migrate(db)
            db.execute('INSERT OR IGNORE INTO ai_chat_sessions(user_id,session_id) VALUES (?,?)',(uid,sid))
            state=dict(db.execute('SELECT * FROM ai_chat_sessions WHERE user_id=? AND session_id=?',(uid,sid)).fetchone())
        active=state['animal_id'];ctx=state['read_context'];topic=state.get('guide_topic')
        missing=json.loads(state['missing_json']) if state['missing_json'] else None
        for index,q in enumerate(parts):
            q=re.sub(r'^(並且|並|再|另外)','',q).strip()
            if not q:continue
            try:
                if uid==1 and populate_tasks and re.fullmatch(r'(?:查看)?待指派照護任務[。？?]*',q):
                    with legacy.lock,legacy.connect() as db:
                        db.execute('BEGIN IMMEDIATE');populate_tasks(db)
                # Product guidance and scoped operational answers precede generic keyword routing.
                with legacy.connect() as db:
                    guidance=work_guide(db,uid,q,active,today(),resolve,getattr(legacy,'resource_totals',None),topic) if hasattr(legacy,'resource_totals') else None
                if guidance:
                    response,target=guidance
                    if target!=active:
                        ctx=None;missing=None
                    active=target;topic=response.pop('workflow_topic',None)
                    response['answer']['queried_at']=stamp()
                    result.append(turn(q,**response));continue
                if re.search(r'自訂自動化|工作流程|智慧提醒|(?:建立|設定|新增|自動).*提醒|(?:提醒|通知)我',q):
                    result.append(message(q,'此功能已移除，可直接查詢目前資料或建立照護任務'));continue
                if UNDO.fullmatch(q) or CANCEL.fullmatch(q):
                    if uid!=1:
                        if missing and missing.get('staff_report'):
                            missing=None;result.append(message(q,'已取消尚未送出的回報'));continue
                        result.append(message(q,'如需收回已送出的本人回報，請至個人工作台核對。'));continue
                    with legacy.lock,legacy.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        pending=db.execute("SELECT action_id FROM ai_action_history WHERE user_id=? AND session_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1",(uid,sid)).fetchone()
                        if pending or missing:
                            db.execute("UPDATE ai_action_history SET status='cancelled' WHERE user_id=? AND session_id=? AND status='pending'",(uid,sid))
                            missing=None
                            result.append(message(q,'已取消尚未確認的修改草案'));continue
                        if CANCEL.fullmatch(q):result.append(message(q,'沒有待確認的草案'));continue
                        old=db.execute("SELECT * FROM ai_action_history WHERE user_id=? AND session_id=? AND kind='edit' AND status='applied' ORDER BY completed_at DESC LIMIT 1",(uid,sid)).fetchone()
                        if not old:result.append(message(q,'目前沒有可復原的資料修改'));continue
                        current=snapshot(db,old['animal_id']);previous=json.loads(old['before_data'])
                        if current!=json.loads(old['after_data']):raise HTTPException(409,'資料已有後續變更，無法安全復原')
                        display=[{'field':FIELDS[k],'before':DISPLAY.get(current[k],current[k]),'after':DISPLAY.get(previous[k],previous[k])} for k in FIELDS if current[k]!=previous[k]]
                        for key,label in [('deworming','驅蟲紀錄'),('vaccinations','疫苗紀錄')]:
                            if current[key]!=previous[key]:
                                field='completed_date' if key=='deworming' else 'administered_date'
                                display.append({'field':label,'before':'、'.join(r[field] for r in current[key]) or '無日期紀錄','after':'、'.join(r[field] for r in previous[key]) or '無日期紀錄'})
                        cmd=draft(db,uid,sid,old['animal_id'],{'display':display},today(),'undo',old['action_id'])
                        result.append(turn(q,command=cmd));continue
                if uid!=1 and missing and missing.get('staff_report') and not missing.get('staff_date') and re.fullmatch(r'(?:備註|說明)\s*[:：]\s*.+',q):
                    saved=missing['staff_report']
                    note=re.split(r'[:：]',q,maxsplit=1)[1].strip()
                    with legacy.connect() as db:
                        ok=db.execute("""SELECT 1 FROM weekly_tasks t JOIN weekly_staff_accounts a ON a.staff_id=t.staff_id
                            JOIN animals x ON x.id=t.animal_id
                            WHERE a.user_id=? AND t.task_id=? AND t.day=? AND t.state IN ('pending','in_progress') AND x.is_active=1""",(uid,saved['task_id'],today().isoformat())).fetchone()
                    missing=None
                    if not ok:result.append(message(q,'任務已變動，請重新查詢'));continue
                    if not note or len(note)>4000:result.append(message(q,'備註無效，請重新回報'));continue
                    result.append(turn(q,command={**saved,'note':note}));continue
                if uid!=1 and missing and missing.get('staff_report') and missing.get('staff_date'):
                    raw_date=re.sub(r'^(?:實際)?(?:施打|接種)?日期\s*[:：]\s*','',q)
                    if re.fullmatch(r'[0-9年月日/\-]+|今天|昨天|前天|[一二三四五六七八九十\d]+天前',raw_date):
                        dose=normalize_date(raw_date,today())
                        if dose>today():raise ValueError('實際施打日期不可晚於今日')
                        saved=missing['staff_report']
                        with legacy.connect() as db:
                            ok=db.execute("""SELECT 1 FROM weekly_tasks t JOIN weekly_staff_accounts a ON a.staff_id=t.staff_id
                                JOIN animals x ON x.id=t.animal_id WHERE a.user_id=? AND t.task_id=? AND t.day=?
                                AND t.state IN ('pending','in_progress') AND x.is_active=1""",(uid,saved['task_id'],today().isoformat())).fetchone()
                        missing=None
                        if not ok:result.append(message(q,'任務已變動，請重新查詢'));continue
                        result.append(turn(q,command={**saved,'administered_date':dose.isoformat()}));continue
                report_q=q.replace('傷病治療','優先確認健康狀況')
                report_tail=report_q
                for known_label in care.RULES:
                    report_tail=report_tail.replace(known_label,'')
                if re.search(r'^(?:請|幫我|我要|我想)?回報|^我(?:已經|已|剛剛)?完成|^我做完',report_q) and not QUERY.search(q) and not re.search(r'哪些|多少|幾項|清單',report_tail):
                    q=report_q
                    if uid==1:
                        result.append(message(q,'管理者不可代替員工回報；請使用照護人員帳號'));continue
                    with legacy.connect() as db:
                        account=db.execute('SELECT a.staff_id FROM weekly_staff_accounts a JOIN staff s ON s.id=a.staff_id WHERE a.user_id=? AND s.profile_id=1',(uid,)).fetchone()
                        if not account:raise HTTPException(403,'帳號未連結員工')
                        own=[dict(r) for r in db.execute("""SELECT t.task_id,t.animal_id,t.label,t.day,t.state,t.staff_id,a.name
                            FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id
                            WHERE t.staff_id=? AND t.day=? AND t.state IN ('pending','in_progress') AND a.is_active=1""",(account[0],today().isoformat()))]
                        ids=re.findall(r'#\s*(\d{1,18})(?!\d)',q)
                        exact=[r for r in own if re.search(r'(?<![A-Za-z0-9_:-])'+re.escape(r['task_id'])+r'(?![A-Za-z0-9_:-])',q)]
                        def name_match(r):
                            name=r['name'].casefold()
                            if not name:return False
                            if re.fullmatch(r'[a-z0-9 ]+',name):
                                return bool(re.search(r'(?<![a-z0-9])'+re.escape(name)+r'(?![a-z0-9])',q.casefold()))
                            return name in q.casefold()
                        named=[r for r in own if name_match(r)]
                        candidates=exact if exact else [r for r in own if r['label'] in q and (str(r['animal_id']) in ids if ids else r in named)]
                        # Allow a contextual pronoun only when it resolves to an assigned animal.
                        if not candidates and not exact and not ids and not named and active and re.search(r'牠|它|這隻|該動物|幫他|幫她',q) and not re.search(r'[A-Za-z]{2,}',q):
                            candidates=[r for r in own if r['animal_id']==active and r['label'] in q]
                        if not candidates and not exact:
                            # Short result-only reports can select a unique matching own health observation task.
                            if re.search(r'結果\s*[:：]\s*(?:健康|生病|受傷)',q):
                                selected_id=int(ids[0]) if len(set(ids))==1 and ids else (named[0]['animal_id'] if len({r['animal_id'] for r in named})==1 else active if not named and re.search(r'牠|它|這隻|該動物',q) else None)
                                candidates=[r for r in own if r['animal_id']==selected_id and r['label'] in ('健康狀態待確認','優先確認健康狀況') and not any(l in q for l in legacy.TASK_CATALOG if l not in ('健康狀態待確認','優先確認健康狀況'))]
                        if ids and (len(set(ids))!=1 or any(str(r['animal_id']) not in ids for r in candidates)):
                            candidates=[]
                        if named and any(r['animal_id'] not in {n['animal_id'] for n in named} for r in candidates):
                            candidates=[]
                    if len(candidates)!=1:
                        result.append(message(q,'請指定今天自己的動物名稱和完整任務名稱，或任務 ID'));continue
                    t=candidates[0]
                    if re.search(r'照片|圖片|驅蟲日期',q):
                        result.append(turn(q,command={'type':'link','path':'/','message':'請到個人工作台回報日期或上傳照片'}));continue
                    note=re.search(r'(?:備註|說明)\s*[:：]\s*(.+)$',q)
                    report_text=(q[:note.start()] if note else q)
                    dose_match=re.search(r'(?:實際)?(?:施打|接種)日期\s*[:：]\s*([0-9年月日/\-]+|今天|昨天|前天|[一二三四五六七八九十\d]+天前)',report_text)
                    dose=None
                    if dose_match:
                        if t['label'] not in ('更新疫苗紀錄','確認疫苗紀錄','疫苗施打'):
                            raise ValueError('此任務不需疫苗日期')
                        dose=normalize_date(dose_match[1],today())
                        if dose>today():raise ValueError('實際施打日期不可晚於今日')
                        report_text=report_text[:dose_match.start()]+report_text[dose_match.end():]
                    if re.search(r'施打日期|接種日期',report_text):
                        result.append(message(q,'請提供施打日期，例如「施打日期：2026-11-28」'));continue
                    txt=report_text.replace(t['label'],'').replace(t['task_id'],'')
                    txt=re.sub(re.escape(t['name']),'',txt,flags=re.I)
                    explicit=re.search(r'結果\s*[:：]\s*(.+)$',txt)
                    code=care.result_code(t['label'],explicit[1] if explicit else '')
                    if not explicit:
                        # Permit a short natural result only when the remaining phrase exactly matches a choice.
                        short=re.sub(r'^(?:請|幫我|我要|我想)?回報\s*|^我(?:已經|已|剛剛)?完成\s*|^我做完\s*','',txt).strip()
                        short=re.sub(r'#\s*\d+','',short).strip(' ，,：:。')
                        code=care.result_code(t['label'],short)
                        if not short and re.match(r'^我(?:已經|已|剛剛)?完成|^我做完',q) and 'done' in care.allowed(t['label']):
                            code='done'
                    if re.search(r'不要|取消|可能|如果|假設|不確定|不是|沒有生病|沒有受傷|無法',txt):
                        code=None
                    if not code and explicit and re.search(r'不要|取消|可能|如果|假設|不確定|不是|沒有生病|沒有受傷|無法',txt):
                        result.append(message(q,'請明確提供本次回報結果'));continue
                    if not code:
                        suggestions=[{'label':title,'question':f"回報 {t['task_id']} 結果：{title}"}
                                     for _,title,_ in care.RULES.get(t['label'],(('done','完成',None),))]
                        result.append(turn(q,answer={'answer':'請選擇實際結果：'+care.outcomes(t['label']),'source':'rules','sources':[],'context':None,'queried_at':stamp(),'fallback_reason':None},suggestions=suggestions));continue
                    cmd={'type':'staff_report','task_id':t['task_id'],'name':t['name'],'label':t['label'],'day':t['day'],
                         'result':code,'note':note[1].strip() if note else '', 'administered_date':dose.isoformat() if dose else None,
                         'next_step':care.describe_next(t['label'],code)}
                    active=t['animal_id']
                    if t['label']=='更新絕育狀態' and code=='done':
                        parent=t['task_id']
                        while parent.startswith('carry:'):parent=parent.removeprefix('carry:')
                        with legacy.connect() as db:
                            from_surgery=parent.startswith('followup:') and db.execute("SELECT 1 FROM weekly_tasks WHERE task_id=? AND label='絕育手術'",(parent.removeprefix('followup:'),)).fetchone()
                        cmd['next_step']='術後健康追蹤' if from_surgery else '任務結束'
                    if t['label']=='更新疫苗紀錄' and code=='done' and not dose:
                        with legacy.connect() as db:
                            known=db.execute("SELECT 1 FROM vaccination_records WHERE animal_id=? AND vaccine_type='general' AND administered_date IS NOT NULL AND next_due_date IS NOT NULL",(active,)).fetchone()
                        if not known:
                            missing={'staff_report':cmd,'staff_date':True}
                            result.append(message(q,'缺少可信的疫苗施打日期。請輸入實際日期（例如 1128 或 2026-11-28），確認前不會送出回報。'));continue
                    if code in care.NOTE_RESULTS and not cmd['note']:
                        missing={'staff_report':cmd}
                        result.append(message(q,'請補充觀察或處理情況，例如「備註：今天早上發現精神不佳，已通知主管」。確認前不會送出回報。'));continue
                    missing=None
                    result.append(turn(q,command=cmd));continue
                q_for_entity=q
                date_missing=re.search(r'(驅蟲|疫苗(?:接種|施打)?)日期\s*(?:(?:為|是|改成|改為|[:：=])\s*)?$',q)
                if date_missing and not QUERY.search(q) and re.search(r'[:：=]|修改|更正|登錄|更新|改成|改為',q):
                    if uid!=1:raise HTTPException(403,'此操作需要管理者權限')
                    with legacy.connect() as db:
                        target=resolve(db,q,active,allow_active=True)
                    missing={'date_slot':'驅蟲日期' if date_missing[1]=='驅蟲' else '疫苗日期','animal_id':target,'correction':'更正' in q}
                    active=target
                    result.append(message(q,'請提供'+missing['date_slot']+'（例如 1128）'));continue
                if missing and missing.get('date_slot') and re.fullmatch(r'[0-9年月日/\-]+|今天|昨天|前天|[一二三四五六七八九十\d]+天前',q):
                    edit=parse_edit(missing['date_slot']+':'+q,today())
                    edit['correction']=missing.get('correction',False)
                    active=missing.get('animal_id')
                    missing=edit
                    q_for_entity='動物 #'+str(active) if active else ''
                else:
                    edit=parse_edit(q,today())
                if edit or (missing and not missing.get('date_slot') and not missing.get('staff_report') and not SMART.search(q) and not QUERY.search(q)):
                    if uid!=1:raise HTTPException(403,'此操作需要管理者權限')
                    with legacy.lock,legacy.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        aid=resolve(db,q_for_entity,active,allow_active=bool(edit))
                        if not edit and missing and aid:
                            animal=db.execute('SELECT name FROM animals WHERE id=?',(aid,)).fetchone()
                            if q.casefold()==norm(animal[0]).casefold() or re.fullmatch(r'(?:動物\s*)?#\s*\d+',q):
                                edit=missing
                        if edit:
                            edit['correction']=bool(edit.get('correction') or '更正' in q)
                            if aid is None:
                                active=None;ctx=None;missing=edit;result.append(message(q,'要修改哪一隻動物？請提供名稱或 #編號'));continue
                            active=aid;missing=None
                            previous=db.execute("SELECT * FROM ai_action_history WHERE user_id=? AND session_id=? AND animal_id=? AND kind='edit' AND status='pending' ORDER BY created_at DESC LIMIT 1",(uid,sid,aid)).fetchone()
                            if previous and json.loads(previous['before_data'])==snapshot(db,aid):
                                old=json.loads(previous['payload'])
                                edit={'changes':{**old['changes'],**edit['changes']},'dates':{**old['dates'],**edit['dates']},'correction':bool(old.get('correction') or edit.get('correction'))}
                                for key,status in [('deworming_date','dewormed'),('vaccination_date','vaccinated')]:
                                    if key in edit['dates'] and edit['changes'].get(status)!='yes':
                                        raise ValueError('醫療日期與狀態矛盾，請先取消舊草案再修改')
                            cmd=draft(db,uid,sid,aid,edit,today())
                            result.append(turn(q,command=cmd));continue
                # Current group queries are factual, role-scoped and do not need a model.
                if re.search(r'哪些|多少|幾隻|列出|名單|清單|所有|全部',q) and re.search(r'動物|犬|狗|貓|貓咪|隻',q) and not re.search(r'任務|工作|排程|班表|統計|報表|昨天|明天|上週|下週|過去|最近|未來',q):
                    conditions=[]
                    for words,field,value in [(r'未驅蟲','dewormed','no'),(r'已驅蟲','dewormed','yes'),(r'未接種|未施打','vaccinated','no'),(r'已接種|已施打','vaccinated','yes'),(r'疫苗(?:紀錄|狀態)?\s*(?:為|是|[:：])?\s*(?:未確認|待確認)','vaccinated','unknown'),(r'驅蟲(?:紀錄|狀態)?\s*(?:為|是|[:：])?\s*(?:未確認|待確認)','dewormed','unknown'),(r'健康(?:狀況|狀態|登錄)?\s*(?:為|是|[:：])?\s*(?:未確認|待確認)','health_status','unknown'),(r'生病','health_status','sick'),(r'受傷','health_status','injured')]:
                        if re.search(words,q):conditions.append((field,value))
                    attention=bool(re.search(r'特別注意|需要注意|健康異常|健康不好|身體不好',q))
                    if conditions or attention:
                        if len(conditions)>1 and not re.search(r'且|並|同時|又|和|與|或',q):
                            result.append(message(q,'請確認多個條件是同時符合，還是符合其中一個即可'));continue
                        with legacy.connect() as db:
                            args=[]
                            clauses=[]
                            for field,value in conditions:
                                if value=='unknown' and field=='health_status':
                                    clauses.append("health_status IN ('unknown','needs_review')")
                                else:
                                    clauses.append(field+'=?');args.append(value)
                            if attention:
                                clauses.append("(health_status IN ('unknown','needs_review','sick','injured','serious') OR EXISTS(SELECT 1 FROM weekly_issues i WHERE i.animal_id=animals.id AND i.resolved_at IS NULL))")
                            joiner=' OR ' if '或' in q else ' AND '
                            query="SELECT id,name FROM animals WHERE is_active=1 AND ("+joiner.join(clauses)+")"
                            if uid!=1:
                                query+=" AND EXISTS(SELECT 1 FROM weekly_tasks t JOIN weekly_staff_accounts s ON s.staff_id=t.staff_id WHERE t.animal_id=animals.id AND s.user_id=? AND t.state!='cancelled')";args.append(uid)
                            if re.search(r'狗|犬',q) and '貓' not in q:query+=" AND species='dog'"
                            if '貓' in q and not re.search(r'狗|犬',q):query+=" AND species='cat'"
                            found=list(db.execute(query+' ORDER BY id',args))
                        lines=[f'目前符合條件且可查看的在所動物共 {len(found)} 隻。']
                        if not re.search(r'多少|幾隻',q):lines.extend(f"{r['name']} #{r['id']}" for r in found[:20])
                        if len(found)>20 and not re.search(r'多少|幾隻',q):lines.append('顯示前 20 隻，完整資料請至動物列表。')
                        active=None;ctx=None;missing=None
                        result.append(turn(q,answer={'answer':'\n'.join(lines),'source':'db','sources':['在所動物登錄'],'context':None,'fallback_reason':None,'queried_at':stamp()}));continue
                if uid==1 and SMART.search(q) and ((not QUERY.search(q) and not re.search(r'哪些|什麼|有沒有|是否|幾項|多少|誰|哪位',q)) or re.search(r'統計|報表|分布|完成率',q)):
                    # Legacy tools use signed read context. Inject the selected subject only for explicit pronouns.
                    smart_q=q
                    if active and re.search(r'(?:他|牠|它|這隻|該動物)',q) and not re.search(r'#\d+',q):
                        with legacy.connect() as db:
                            if resolve(db,q) is None:smart_q=q+' 動物 #'+str(active)
                    c=smart_command(Command(text=smart_q,context=ctx),request)
                    out=turn(q,command=c)
                    if c['type']=='report':
                        with legacy.connect() as db:out['report']=report(db,c['kind'],c['start'],c['end'])
                    if c['type']=='task':
                        out['check']=smart_check(Check(animal_id=c['animal_id'],label=c['label']),request)
                        active=c['animal_id']
                    result.append(out);continue
                if re.search(r'修改|更正|改成|改為|更新|登錄|設定|[:：=]',q) and not QUERY.search(q) and re.search(FIELD_WORDS,q):
                    result.append(message(q,'請提供要修改的欄位與數值，例如「健康：健康」'));continue
                read_q=q
                # Both roles may reuse a verified active animal for a narrowly scoped read.
                # The existing read endpoint still authorizes the animal and all returned data.
                if active and re.fullmatch(r'(?:那|所以|另外|他|她|牠|它|這隻|的|請問|\s)*(?:健康(?:狀況|狀態|登錄)?|疫苗(?:紀錄|日期)?|驅蟲(?:紀錄|日期)?|最近照護回報|照護回報|資料)[呢嗎?？。]*',q):
                    read_q=q+' 動物 #'+str(active)
                if uid!=1 and re.fullmatch(r'(?:我要|請|幫我)?(?:開啟|前往|看)(?:個人工作台|照護人員工作台|今日工作|動物列表)',q):
                    result.append(turn(q,command={'type':'link','path':'/animals' if '動物列表' in q else '/','message':'開啟頁面'}));continue
                if uid==1:
                    with legacy.connect() as db:
                        # Use the server-side active entity only on animal-specific follow-ups.
                        selected=resolve(db,q,active,allow_active=False)
                    if selected is None and re.fullmatch(r'.+?(?:資料|詳細資料|基本資料)[。?？]*',q) and q not in ('資料','詳細資料','基本資料') and not re.search(r'員工|人員|班表|任務|資源|收容所|派工',q):
                        active=None;ctx=None
                        result.append(message(q,'找不到指定動物，請提供正確名稱或 #編號'));continue
                    if selected:
                        active=selected
                        if re.fullmatch(r'.*?(?:資料|詳細資料|基本資料)[。?？]*',q):read_q=q+' 健康狀況'
                    elif active and re.fullmatch(r'(?:那|所以|另外|他|她|牠|它|這隻|的|請問|\s)*(?:健康(?:狀況|狀態|登錄)?|疫苗(?:紀錄|日期)?|驅蟲(?:紀錄|日期)?|資料)[呢嗎?？。]*',q):
                        read_q=q+' 動物 #'+str(active)
                    elif re.search(r'[A-Za-z]{2,}',q) and re.search(r'健康|疫苗|驅蟲|資料',q):
                        active=None;ctx=None
                        result.append(message(q,'找不到指定動物，請提供正確名稱或 #編號'));continue
                answer=read_chat(Question(question=read_q,context=ctx),request)
                ctx=answer.get('context')
                decoded=ci.decode_context(legacy.AUTH_SECRET,request.headers.get('Authorization',''),answer.get('context'))
                if answer.get('sources') and decoded and decoded.get('animal_id'):
                    if active!=decoded['animal_id']:topic=None;missing=None
                    active=decoded['animal_id']
                elif re.search(r'資料|健康|疫苗|驅蟲|照護回報',q) and not answer.get('sources'):
                    active=None;ctx=None;topic=None;missing=None
                result.append(turn(q,answer=answer))
            except (ValueError,HTTPException) as e:
                detail=str(e.detail) if isinstance(e,HTTPException) else str(e)
                if re.search(r'多個動物|單一動物編號|找不到動物|找不到指定動物|名稱與編號不一致|目前沒有可查看的動物紀錄',detail):
                    active=None;ctx=None;missing=None;topic=None
                result.append(message(q,detail))
        with legacy.lock,legacy.connect() as db:
            db.execute('UPDATE ai_chat_sessions SET animal_id=?,read_context=?,missing_json=?,guide_topic=? WHERE user_id=? AND session_id=?',(active,ctx,dump(missing) if missing else None,topic,uid,sid))
        return {'turns':result}

    @router.post('/actions/{action_id}')
    def action(action_id:str,body:ActionInput,request:Request):
        uid=request.state.user_id
        if uid!=1:raise HTTPException(403,'此操作需要管理者權限')
        with legacy.lock,legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE');migrate(db)
            if body.decision=='cancel':
                n=db.execute("UPDATE ai_action_history SET status='cancelled' WHERE action_id=? AND user_id=? AND session_id=? AND status='pending'",(action_id,uid,body.session_id)).rowcount
                if not n:raise HTTPException(409,'草案已處理或不存在')
                return {'message':'已取消','status':'cancelled'}
            return apply_action(db,uid,body.session_id,action_id,legacy.month_after,today())
    @router.post('/evaluate')
    def evaluation(request:Request):
        if request.state.user_id!=1:raise HTTPException(403,'此功能限管理者')
        from agent_evaluation import evaluate
        return evaluate()
    @router.get('/actions')
    def statuses(session_id:str,request:Request):
        with legacy.lock,legacy.connect() as db:
            migrate(db)
            return {'actions':[dict(r) for r in db.execute('SELECT action_id,status FROM ai_action_history WHERE user_id=? AND session_id=?',(request.state.user_id,session_id))]}
    return router
