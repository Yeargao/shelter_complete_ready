"""Local-first management tools. All SQL and actions are allowlisted; no generated SQL."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
import re
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

TZ = ZoneInfo('Asia/Taipei')
ACTIVE = "('pending','in_progress')"
METRICS = {'stock':'飼料庫存低於（公斤）','stay':'在所天數超過且健康待確認','overdue':'緊急任務逾期','load':'員工今日排定工時達百分比','vaccine':'疫苗在指定天數內到期'}
REPORTS = {'health':'在所動物健康分布','species':'在所動物物種分布','tasks':'任務狀態','staff':'員工任務完成率','intake':'入離所事件統計'}
EVENTS = {'intake':'動物入所','sick':'生病','injured':'受傷','serious':'嚴重健康異常'}
LABELS = ('健康狀態待確認','優先確認健康狀況','確認疫苗紀錄','確認驅蟲紀錄','健康問題追蹤')
ROUTES = {'animals':'/animals','new':'/animals/new','health':'/health','resources':'/resources','home':'/','tools':'/'}

def now():
    return datetime.now(TZ)

def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS smart_rules(
        id TEXT PRIMARY KEY, metric TEXT NOT NULL, threshold REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS smart_workflows(
        id TEXT PRIMARY KEY, event TEXT NOT NULL, labels TEXT NOT NULL, cursor INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS smart_inbox(
        id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL,
        detail TEXT NOT NULL, payload TEXT NOT NULL, created TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending')""")

def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql,args)]

def candidates(db, metric, threshold, day):
    if metric=='stock':
        p=db.execute('SELECT food_stock_kg FROM profiles WHERE id=1').fetchone()
        return [('stock',f'飼料庫存 {p[0]:g} 公斤，低於 {threshold:g} 公斤')] if p and p[0]<threshold else []
    if metric=='stay':
        return [(str(r['id']),f"#{r['id']} {r['name']} 在所超過 {threshold:g} 天且健康待確認") for r in db.execute(
            "SELECT id,name FROM animals WHERE is_active=1 AND health_status IN ('unknown','needs_review') AND julianday(?)-julianday(intake_date)>?",(day,threshold))]
    if metric=='overdue':
        return [(r['task_id'],f"{r['name']}：{r['label']} 已逾期（{r['due']}）") for r in db.execute(
            f"""SELECT t.task_id,a.name,t.label,t.due FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id
            WHERE a.is_active=1 AND t.priority<=1 AND t.state IN {ACTIVE} AND t.due<?""",(day,))]
    if metric=='load':
        return [(str(r['id']),f"{r['name']} 今日排定 {r['hours']:g} / {r['capacity']:g} 小時（以可用工時為分母）") for r in db.execute(
            """SELECT s.id,s.name,COALESCE(d.available_hours,s.available_hours) capacity,
            COALESCE(sum(t.quarters),0)/4.0 hours FROM staff s LEFT JOIN staff_daily_shifts d
            ON d.staff_id=s.id AND d.day=? LEFT JOIN weekly_tasks t ON t.staff_id=s.id AND t.day=? AND t.state!='cancelled'
            WHERE s.profile_id=1 AND COALESCE(d.attending,s.attending)=1 GROUP BY s.id
            HAVING capacity>0 AND hours/capacity*100>=?""",(day,day,threshold))]
    if metric=='vaccine':
        until=(date.fromisoformat(day)+timedelta(days=int(threshold))).isoformat()
        return [(str(r['id']),f"#{r['animal_id']} {r['name']} 疫苗 {r['next_due_date']} 到期") for r in db.execute(
            """SELECT v.id,v.animal_id,a.name,v.next_due_date FROM vaccination_records v JOIN animals a ON a.id=v.animal_id
            WHERE a.is_active=1 AND v.next_due_date BETWEEN ? AND ? AND NOT EXISTS(
            SELECT 1 FROM vaccination_records n WHERE n.animal_id=v.animal_id AND n.vaccine_type=v.vaccine_type
            AND (n.administered_date>v.administered_date OR (n.administered_date=v.administered_date AND n.id>v.id)))""",(day,until))]
    return []

def recommend(db, aid):
    a=db.execute('SELECT * FROM animals WHERE id=? AND is_active=1',(aid,)).fetchone()
    if not a:
        raise HTTPException(404,'找不到在所動物')
    wanted=[]
    if a['health_status'] in ('unknown','needs_review'):
        wanted.append('健康狀態待確認')
    if a['health_status'] in ('sick','injured','serious'):
        wanted.append('優先確認健康狀況')
    if a['vaccinated']=='unknown':
        wanted.append('確認疫苗紀錄')
    if a['dewormed']=='unknown':
        wanted.append('確認驅蟲紀錄')
    if db.execute('SELECT 1 FROM weekly_issues WHERE animal_id=? AND resolved_at IS NULL',(aid,)).fetchone():
        wanted.append('健康問題追蹤')
    return {'animal_id':aid,'name':a['name'],'steps':[{'label':label,'existing':bool(db.execute(
        f'SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label=? AND state IN {ACTIVE}',(aid,label)).fetchone())} for label in wanted]}

def scan(db):
    """Idempotent, persistent inbox. Run from authenticated polling or a scheduled local job."""
    migrate(db)
    stamp=now().isoformat()
    day=stamp[:10]
    for rule in rows(db,'SELECT * FROM smart_rules'):
        hits=candidates(db,rule['metric'],rule['threshold'],day)
        live={subject for subject,_ in hits}
        for prior in rows(db,"SELECT id,subject FROM smart_inbox WHERE rule_id=? AND state='pending'",(rule['id'],)):
            if prior['subject'] not in live:
                db.execute("UPDATE smart_inbox SET state='expired' WHERE id=?",(prior['id'],))
        for subject,detail in hits:
            # Re-arm only once the condition has cleared; an acknowledged active hit stays acknowledged.
            old=db.execute("SELECT id,state FROM smart_inbox WHERE rule_id=? AND subject=? ORDER BY rowid DESC LIMIT 1",(rule['id'],subject)).fetchone()
            if not old or old['state']=='expired':
                db.execute("INSERT INTO smart_inbox VALUES (?,?,?,?,?,?,?,'pending')",
                    (uuid4().hex,rule['id'],'reminder',subject,detail,'{}',stamp))
        for prior in rows(db,"SELECT id,subject FROM smart_inbox WHERE rule_id=? AND state='ack'",(rule['id'],)):
            if prior['subject'] not in live:
                db.execute("UPDATE smart_inbox SET state='expired' WHERE id=?",(prior['id'],))
    for rule in rows(db,'SELECT * FROM smart_workflows'):
        events=rows(db,'SELECT id,animal_id,event FROM weekly_events WHERE id>? ORDER BY id LIMIT 500',(rule['cursor'],))
        for event in events:
            if event['event']!=rule['event'] or not event['animal_id']:
                continue
            try:
                info=recommend(db,event['animal_id'])
            except HTTPException:
                continue
            selected=json.loads(rule['labels'])
            # Only propose steps justified by current facts; human confirmation precedes writes.
            labels=[s['label'] for s in info['steps'] if s['label'] in selected and not s['existing']]
            if labels:
                payload={'animal_id':info['animal_id'],'labels':labels}
                db.execute("INSERT OR IGNORE INTO smart_inbox VALUES (?,?,?,?,?,?,?,'pending')",
                    (rule['id']+':'+str(event['id']),rule['id'],'workflow',str(event['id']),
                    f"{info['name']}：{event['event']} → "+'、'.join(labels),json.dumps(payload,ensure_ascii=False),stamp))
        if events:
            db.execute('UPDATE smart_workflows SET cursor=? WHERE id=?',(events[-1]['id'],rule['id']))
    return rows(db,"SELECT * FROM smart_inbox WHERE state='pending' ORDER BY created DESC,id LIMIT 200")

def report(db, kind, start, end):
    args=(start,end)
    if kind in ('health','species'):
        field={'health':'health_status','species':'species'}[kind]
        result=rows(db,f"SELECT coalesce({field},'unknown') label,count(*) value FROM animals WHERE is_active=1 GROUP BY {field} ORDER BY value DESC")
        note='目前在所動物快照。'
    elif kind=='tasks':
        result=rows(db,"SELECT state label,count(*) value FROM weekly_tasks WHERE day BETWEEN ? AND ? GROUP BY state ORDER BY value DESC",args)
        note='依排定日期統計。'
    elif kind=='staff':
        result=rows(db,"""SELECT s.name||' #'||s.id label, count(t.task_id) total,
            sum(CASE WHEN t.state='done' THEN 1 ELSE 0 END) completed,
            round(100.0*sum(CASE WHEN t.state='done' THEN 1 ELSE 0 END)/count(t.task_id),1) value
            FROM staff s JOIN weekly_tasks t ON t.staff_id=s.id WHERE s.profile_id=1
            AND t.day BETWEEN ? AND ? AND t.state!='cancelled' GROUP BY s.id ORDER BY value DESC""",args)
        note='完成率＝已完成／期間已排定且未取消任務（含未來日期）。'
    else:
        result=rows(db,"""SELECT event label,count(*) value FROM (
            SELECT '入所' event FROM animal_stay_history WHERE intake_date BETWEEN ? AND ?
            UNION ALL SELECT '離所' FROM animal_stay_history WHERE exit_date BETWEEN ? AND ?
            UNION ALL SELECT '入所' FROM animals WHERE intake_date BETWEEN ? AND ?
            UNION ALL SELECT '離所' FROM animals WHERE exit_date BETWEEN ? AND ?) GROUP BY event""",args*4)
        note='依入離所紀錄計數。'
    return {'title':REPORTS[kind],'rows':result,'note':note,'start':start,'end':end,'unit':'%' if kind=='staff' else '筆'}

def audit(db):
    findings=rows(db,"""SELECT a.id animal_id,a.name,'已離所仍有未完成任務' kind,t.task_id source
        FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id WHERE a.is_active=0 AND t.state IN ('pending','in_progress')""")
    findings+=rows(db,"""SELECT a.id animal_id,a.name,'健康登錄與未結案異常待核對' kind,i.task_id source
        FROM weekly_issues i JOIN animals a ON a.id=i.animal_id WHERE a.is_active=1 AND a.health_status='healthy' AND i.resolved_at IS NULL""")
    findings+=rows(db,"""SELECT a.id animal_id,a.name,'已接種但缺少日期，可能為歷史資料缺漏' kind,'vaccination_records' source
        FROM animals a WHERE a.is_active=1 AND a.vaccinated='yes' AND NOT EXISTS
        (SELECT 1 FROM vaccination_records v WHERE v.animal_id=a.id AND v.administered_date IS NOT NULL)""")
    findings+=rows(db,"""SELECT a.id animal_id,a.name,'員工當日未出勤仍有未完成指派' kind,t.task_id source
        FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id JOIN staff s ON s.id=t.staff_id
        LEFT JOIN staff_daily_shifts d ON d.staff_id=s.id AND d.day=t.day
        WHERE t.state IN ('pending','in_progress') AND t.day>=? AND COALESCE(d.attending,s.attending)=0""",(now().date().isoformat(),))
    return findings

class Rule(BaseModel):
    metric: str
    threshold: float=Field(default=0,ge=0,le=1000000,allow_inf_nan=False)
class Workflow(BaseModel):
    event: str
    labels: list[str]=Field(min_length=1,max_length=5)
class Command(BaseModel):
    text: str=Field(min_length=1,max_length=500)
    context: str | None=Field(default=None,max_length=2048)
class ManualTask(BaseModel):
    animal_id: int=Field(gt=0)
    label: str
    earliest: date
    due: date
class Check(BaseModel):
    animal_id: int=Field(gt=0)
    label: str
class Handover(BaseModel):
    staff_id: int=Field(gt=0)
    day: date

def mount(legacy,populate,week_days,catalog,quarters):
    router=APIRouter(prefix='/api/smart')
    def manager(request):
        if request.state.user_id!=1:
            raise HTTPException(403,'此功能限管理者')
    @router.get('/options')
    def options(request:Request):
        manager(request)
        with legacy.connect() as db:
            return {'animals':rows(db,'SELECT id,name FROM animals WHERE is_active=1 ORDER BY name,id'),
                    'staff':rows(db,'SELECT id,name FROM staff WHERE profile_id=1 ORDER BY id'),
                    'labels':list(catalog)}
    @router.post('/command')
    def command(body:Command,request:Request):
        manager(request)
        text=body.text.strip()
        if re.search(r'刪除|刪掉|修改資料庫|忽略|DROP\s|DELETE\s',text,re.I):
            raise HTTPException(422,'不支援此指令；請使用原本有權限的操作介面')
        if '工作流程' in text or '自動化流程' in text:
            event_matches=[]
            for key, words in {'intake':('入所',),'sick':('生病',),'injured':('受傷',),'serious':('嚴重健康異常','嚴重狀況')}.items():
                if any(w in text for w in words):
                    event_matches.append(key)
            selected=[l for l in LABELS if l in text and l in catalog]
            if len(event_matches)!=1 or not selected:
                return {'type':'clarify','message':'請指定一種觸發事件和任務，例如：建立工作流程，動物入所後確認疫苗紀錄及確認驅蟲紀錄。'}
            return {'type':'workflow','event':event_matches[0],'labels':selected}
        if re.search(r'(新增|建立|安排|加一個|加一項).*任務',text):
            from chat_intent import dates,decode_context
            with legacy.connect() as db:
                animals=rows(db,'SELECT id,name FROM animals WHERE is_active=1')
                named=[a for a in animals if a['name'] and a['name'].casefold() in text.casefold()]
                ids=re.findall(r'#\s*(\d{1,18})(?!\d)',text)
                if len(set(ids))>1 or (not ids and len(named)>1):
                    return {'type':'clarify','message':'有多個可能的動物，請提供單一動物 #ID。'}
                if ids:
                    found=next((a for a in animals if a['id']==int(ids[0])),None)
                    if not found or (named and not any(a['id']==found['id'] for a in named)):
                        return {'type':'clarify','message':'動物編號不存在或與名稱不一致。'}
                elif named:
                    found=named[0]
                else:
                    previous=decode_context(legacy.AUTH_SECRET,request.headers.get('Authorization',''),body.context)
                    aid=previous.get('animal_id') if previous and re.search(r'他|牠|它|這隻|該動物',text) else None
                    found=next((a for a in animals if a['id']==aid),None)
                if not found:
                    return {'type':'clarify','message':'請指定動物名稱或 #ID。'}
                options=[l for l in catalog if l in text]
                if not options and '健康追蹤' in text:
                    options=['健康問題追蹤']
                if len(options)!=1:
                    return {'type':'clarify','message':'請指定一種現有任務類型，例如健康問題追蹤、確認疫苗紀錄。'}
                try:
                    temporal,explicit=dates(text,now().date())
                except ValueError as exc:
                    return {'type':'clarify','message':str(exc)}
                if not explicit or temporal['start']<now().date().isoformat() or temporal['period']!='all_day':
                    return {'type':'clarify','message':'請指定今天或之後的日期；實際時段由排程器安排。'}
                return {'type':'task','animal_id':found['id'],'name':found['name'],'label':options[0],
                        'earliest':temporal['start'],'due':temporal['end']}
        # Slot extraction with explicit numeric thresholds, no guessed values.
        n=re.search(r'(?<!\d)(\d+(?:\.\d+)?)',text)
        if '提醒' in text or '通知' in text:
            metric='stock' if '飼料' in text else 'stay' if '在所' in text and '健康' in text else 'overdue' if '逾期' in text and '緊急' in text else 'load' if '工時' in text or '工作量' in text else 'vaccine' if '疫苗' in text and '到期' in text else None
            supported=metric=='overdue' or (metric=='stock' and any(w in text for w in ('低於','少於','不足')) and any(w in text for w in ('公斤','kg','KG'))) or (metric=='stay' and any(w in text for w in ('超過','大於')) and '天' in text) or (metric=='load' and any(w in text for w in ('達','超過','高於')) and ('%' in text or '％' in text)) or (metric=='vaccine' and '天' in text)
            if supported and metric and (n or metric=='overdue') and (metric=='overdue' or len(re.findall(r'\d+(?:\.\d+)?',text))==1):
                return {'type':'rule','metric':metric,'threshold':float(n[1]) if n and metric!='overdue' else 0}
            return {'type':'clarify','message':'請明確指定條件與數值（例如：飼料低於 30 公斤提醒我）。'}
        if any(w in text for w in ('統計','報表','分布','完成率','比較')):
            kind='staff' if '員工' in text and '完成率' in text else 'intake' if any(w in text for w in ('入所','離所','入離所')) else 'health' if '健康' in text else 'species' if '物種' in text else 'tasks' if '任務' in text else None
            if kind:
                from chat_intent import dates
                today=now().date()
                try:
                    temporal,explicit=dates(text,today)
                except ValueError as exc:
                    return {'type':'clarify','message':str(exc)}
                if '這週' in text or '本週' in text:
                    start=today-timedelta(days=today.weekday())
                    temporal={'start':start.isoformat(),'end':(start+timedelta(days=6)).isoformat()}
                return {'type':'report','kind':kind,'start':temporal['start'],'end':temporal['end']}
            return {'type':'clarify','message':'請指定健康、物種、任務狀態、員工完成率或入離所統計。'}
        # Navigation is a suggestion only; unknown or ambiguous targets do not navigate.
        with legacy.connect() as db:
            named=[a for a in rows(db,'SELECT id,name FROM animals WHERE is_active=1') if a['name'] and a['name'].casefold() in text.casefold()]
            ids=re.findall(r'#\s*(\d+)',text)
            if len(set(ids))>1 or (not ids and len(named)>1):
                return {'type':'clarify','message':'有多個可能的動物，請提供單一動物 #ID。'}
            if ids:
                found=db.execute('SELECT id,name FROM animals WHERE id=? AND is_active=1',(int(ids[0]),)).fetchone()
                if not found or (named and not any(a['id']==found['id'] for a in named)):
                    return {'type':'clarify','message':'動物 ID 不存在或名稱不一致。'}
                named=[dict(found)]
            if named:
                return {'type':'link','path':'/animals/'+str(named[0]['id']),'message':'開啟 '+named[0]['name']+' 的資料'}
        route='new' if '新增' in text and '動物' in text else 'health' if '健康' in text or '疫苗' in text else 'resources' if any(w in text for w in ('飼料','班表','工時','資源','員工','派工')) else 'animals' if '動物' in text else 'home' if '總覽' in text else None
        return {'type':'link','path':ROUTES[route],'message':'開啟對應頁面'} if route else {'type':'clarify','message':'目前支援動物、健康、資源、總覽、條件提醒及統計報表。'}
    @router.post('/task')
    def create_manual(body:ManualTask,request:Request):
        manager(request)
        day=now().date()
        if body.label not in catalog or not day<=body.earliest<=body.due<=day+timedelta(days=366):
            raise HTTPException(422,'任務類型或日期無效')
        with legacy.lock,legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM animals WHERE id=? AND is_active=1',(body.animal_id,)).fetchone():
                raise HTTPException(404,'找不到在所動物')
            populate(db,week_days(body.earliest))
            if db.execute(f'SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label=? AND state IN {ACTIVE}',(body.animal_id,body.label)).fetchone():
                return {'message':'已有同類未完成任務，未重複建立。'}
            _,skill,hours,urgent=catalog[body.label]
            if not any(skill in json.loads(s['skills']) for s in db.execute('SELECT skills FROM staff WHERE profile_id=1')):
                raise HTTPException(409,'沒有具備所需技能的員工，請先確認員工設定')
            tid=uuid4().hex
            db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due,note)
                VALUES (?,?,?,?,?,?,?,?,?)""",(tid,body.animal_id,body.label,skill,0 if urgent else 3,quarters(hours),body.earliest.isoformat(),body.due.isoformat(),'智慧助理：管理者確認'))
            db.execute('INSERT INTO weekly_new_tasks VALUES (?)',(tid,))
            db.execute('INSERT INTO weekly_events(animal_id,event) VALUES (?,?)',(body.animal_id,'urgent_task' if urgent else 'task_created'))
        return {'message':'任務已建立，尚未指派員工；可到資源配置預覽排程。'}
    @router.get('/monitor')
    def monitor(request:Request):
        manager(request)
        with legacy.lock,legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            inbox=scan(db)
            return {'rules':rows(db,'SELECT * FROM smart_rules ORDER BY rowid DESC'),'workflows':rows(db,'SELECT * FROM smart_workflows ORDER BY rowid DESC'),'inbox':inbox,'history':rows(db,"SELECT * FROM smart_inbox WHERE state IN ('ack','applied') ORDER BY created DESC,id LIMIT 100")}
    @router.post('/rules')
    def rule(body:Rule,request:Request):
        manager(request)
        if body.metric not in METRICS or (body.metric=='vaccine' and body.threshold>365):
            raise HTTPException(422,'不支援的條件或門檻')
        with legacy.lock,legacy.connect() as db:
            migrate(db)
            existing=db.execute('SELECT id FROM smart_rules WHERE metric=? AND threshold=?',(body.metric,body.threshold)).fetchone()
            if existing:
                return {'id':existing[0]}
            rid=uuid4().hex
            db.execute('INSERT INTO smart_rules VALUES (?,?,?)',(rid,body.metric,body.threshold))
        return {'id':rid}
    @router.post('/workflows')
    def workflow(body:Workflow,request:Request):
        manager(request)
        if body.event not in EVENTS or any(label not in LABELS or label not in catalog for label in body.labels):
            raise HTTPException(422,'不支援的事件或任務')
        with legacy.lock,legacy.connect() as db:
            migrate(db)
            labels=json.dumps(sorted(set(body.labels)),ensure_ascii=False)
            old=db.execute('SELECT id FROM smart_workflows WHERE event=? AND labels=?',(body.event,labels)).fetchone()
            if old:
                return {'id':old[0]}
            cursor=db.execute('SELECT coalesce(max(id),0) FROM weekly_events').fetchone()[0]
            rid=uuid4().hex
            db.execute('INSERT INTO smart_workflows VALUES (?,?,?,?)',(rid,body.event,labels,cursor))
        return {'id':rid}
    @router.delete('/rules/{rid}')
    def remove(rid:str,request:Request):
        manager(request)
        with legacy.lock,legacy.connect() as db:
            migrate(db)
            db.execute('DELETE FROM smart_rules WHERE id=?',(rid,))
            db.execute('DELETE FROM smart_workflows WHERE id=?',(rid,))
            db.execute("UPDATE smart_inbox SET state='expired' WHERE rule_id=? AND state='pending'",(rid,))
        return {'ok':True}
    @router.post('/inbox/{item}/ack')
    def ack(item:str,request:Request):
        manager(request)
        with legacy.lock,legacy.connect() as db:
            migrate(db)
            db.execute("UPDATE smart_inbox SET state='ack' WHERE id=? AND state='pending'",(item,))
        return {'ok':True}
    @router.post('/inbox/{item}/apply')
    def apply(item:str,request:Request):
        manager(request)
        with legacy.lock,legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            entry=db.execute("SELECT * FROM smart_inbox WHERE id=? AND kind='workflow' AND state='pending'",(item,)).fetchone()
            if not entry:
                raise HTTPException(409,'草案已處理或不存在')
            payload=json.loads(entry['payload'])
            aid=payload['animal_id']
            today=now().date()
            populate(db,week_days(today))
            info=recommend(db,aid)
            eligible={s['label'] for s in info['steps'] if not s['existing']}
            created=[]
            for label in payload['labels']:
                if label not in eligible or label not in catalog:
                    continue
                _,skill,hours,urgent=catalog[label]
                tid=uuid4().hex
                db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due,note)
                    VALUES (?,?,?,?,?,?,?,?,?)""",(tid,aid,label,skill,0 if urgent else 3,quarters(hours),today.isoformat(),(today+timedelta(days=1)).isoformat(),'自訂工作流程：管理者確認'))
                db.execute('INSERT INTO weekly_new_tasks VALUES (?)',(tid,))
                db.execute('INSERT INTO weekly_events(animal_id,event) VALUES (?,?)',(aid,'urgent_task' if urgent else 'task_created'))
                created.append(tid)
            db.execute("UPDATE smart_inbox SET state='applied' WHERE id=?",(item,))
        return {'created':created,'message':f'已新增 {len(created)} 筆任務'}
    @router.get('/report')
    def make_report(kind:str,start:date,end:date,request:Request):
        manager(request)
        if kind not in REPORTS or not 0<=(end-start).days<=366:
            raise HTTPException(422,'報表類型或日期範圍不支援')
        with legacy.connect() as db:
            return report(db,kind,start.isoformat(),end.isoformat())
    @router.get('/recommend/{aid}')
    def recommendations(aid:int,request:Request):
        manager(request)
        with legacy.connect() as db:
            return recommend(db,aid)
    @router.post('/check')
    def check(body:Check,request:Request):
        manager(request)
        with legacy.connect() as db:
            a=db.execute('SELECT id,name,is_active FROM animals WHERE id=?',(body.animal_id,)).fetchone()
            issues=[]
            if not a or not a['is_active']:
                issues.append('動物不存在或已離所')
            if body.label not in catalog:
                issues.append('不支援的任務類型')
            if db.execute(f'SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label=? AND state IN {ACTIVE}',(body.animal_id,body.label)).fetchone():
                issues.append('已存在同類未完成任務')
            if body.label in catalog:
                skill=catalog[body.label][1]
                staff=[r for r in rows(db,'SELECT id,skills FROM staff WHERE profile_id=1') if skill in json.loads(r['skills'])]
                if not staff:
                    issues.append('無符合技能的員工')
            return {'ok':not issues,'issues':issues,'note':''}
    @router.post('/handover')
    def handover(body:Handover,request:Request):
        day=body.day.isoformat()
        with legacy.connect() as db:
            if request.state.user_id!=1:
                account=db.execute('SELECT a.staff_id FROM weekly_staff_accounts a JOIN staff s ON s.id=a.staff_id WHERE a.user_id=? AND s.profile_id=1',(request.state.user_id,)).fetchone()
                if not account or account['staff_id']!=body.staff_id:
                    raise HTTPException(403,'只能查看自己的交接')
            staff=db.execute('SELECT name FROM staff WHERE id=? AND profile_id=1',(body.staff_id,)).fetchone()
            if not staff:
                raise HTTPException(404,'找不到員工')
            tasks=rows(db,"""SELECT t.task_id,t.label,a.name,t.state,t.priority,t.due,r.result,r.note
                FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id LEFT JOIN weekly_reports r ON r.task_id=t.task_id
                WHERE t.staff_id=? AND t.day=? AND t.state!='cancelled' ORDER BY t.priority,t.start,t.task_id""",(body.staff_id,day))
            issues=rows(db,"""SELECT DISTINCT i.task_id,a.name,i.note FROM weekly_issues i JOIN animals a ON a.id=i.animal_id
                WHERE i.resolved_at IS NULL AND EXISTS (SELECT 1 FROM weekly_tasks t WHERE t.animal_id=i.animal_id AND t.staff_id=? AND t.day=?)""",(body.staff_id,day))
            return {'name':staff[0],'day':day,'done':sum(t['state']=='done' for t in tasks),'pending':sum(t['state'] in ('pending','in_progress') for t in tasks),'tasks':tasks,'issues':issues}
    @router.get('/audit')
    def consistency(request:Request):
        manager(request)
        with legacy.connect() as db:
            return {'findings':audit(db)}
    return router
