"""Incremental, persistent administrative consistency audit; no LLM or whole-table rescans on edits."""
from datetime import datetime,date
from zoneinfo import ZoneInfo
import json

TZ=ZoneInfo('Asia/Taipei')
VERSION='health-v1'
TABLES={
    'animals':('id',('name','is_active','intake_date','health_status','vaccinated','dewormed')),
    'vaccination_records':('animal_id',('animal_id','administered_date')),
    'deworming_events':('animal_id',('animal_id','intake_date','completed_date')),
    'weekly_issues':('animal_id',('animal_id','resolved_at')),
}
def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS consistency_dirty(animal_id INTEGER PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS consistency_cache(animal_id INTEGER PRIMARY KEY,findings TEXT NOT NULL,future_date INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS consistency_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    for table,(key,columns) in TABLES.items():
        for event,refs in [('INSERT',('NEW',)),('DELETE',('OLD',)),('UPDATE',('OLD','NEW'))]:
            body=' '.join(f'INSERT OR IGNORE INTO consistency_dirty(animal_id) SELECT {r}.{key} WHERE {r}.{key} IS NOT NULL;' for r in refs)
            # Trigger only when a relevant column actually changed, not when the schedule re-saves a row.
            target=event+(' OF '+','.join(columns) if event=='UPDATE' else '')
            condition=(' WHEN '+' OR '.join(f'OLD.{col} IS NOT NEW.{col}' for col in columns)) if event=='UPDATE' else ''
            db.execute(f'CREATE TRIGGER IF NOT EXISTS consistency_{table}_{event.lower()} AFTER {target} ON {table}{condition} BEGIN {body} END')
    old=db.execute("SELECT value FROM consistency_meta WHERE key='version'").fetchone()
    if not old or old[0]!=VERSION:
        db.execute('DELETE FROM consistency_cache')
        db.execute('INSERT OR IGNORE INTO consistency_dirty SELECT id FROM animals')
        db.execute("INSERT OR REPLACE INTO consistency_meta VALUES ('version',?)",(VERSION,))
        return True
    return False

def inspect(db,aid,current):
    a=db.execute('SELECT id,name,is_active,intake_date,health_status,vaccinated,dewormed FROM animals WHERE id=?',(aid,)).fetchone()
    if not a or not a['is_active']:return [],False
    findings=[]
    def add(kind,detail,source):
        findings.append({'animal_id':aid,'name':a['name'],'kind':kind,'detail':detail,'source':source})
    vaccines=list(db.execute('SELECT administered_date FROM vaccination_records WHERE animal_id=?',(aid,)))
    worms=list(db.execute('SELECT completed_date FROM deworming_events WHERE animal_id=? AND intake_date=?',(aid,a['intake_date'])))
    if a['vaccinated']=='yes' and not any(r[0] for r in vaccines):
        add('待核對','已接種，但缺少疫苗日期。','animals / vaccination_records')
    if a['vaccinated']=='no' and vaccines:
        add('狀態待核對','登錄未接種，但有疫苗紀錄。','animals / vaccination_records')
    if a['dewormed']=='yes' and not worms:
        add('待核對','已驅蟲，但本次入所缺少完成紀錄。','animals / deworming_events')
    if a['dewormed']=='no' and worms:
        add('狀態待核對','登錄未驅蟲，但本次入所有完成紀錄。','animals / deworming_events')
    if a['health_status']=='healthy' and db.execute('SELECT 1 FROM weekly_issues WHERE animal_id=? AND resolved_at IS NULL',(aid,)).fetchone():
        add('狀態待核對','登錄健康，但仍有未結案的照護異常。','animals / weekly_issues')
    future=False
    intake=None
    try:
        intake=date.fromisoformat(a['intake_date'])
        if intake>current:
            future=True;add('日期待核對','入所日期晚於今日。','animals.intake_date')
    except (TypeError,ValueError):
        add('日期待核對','入所日期格式無效。','animals.intake_date')
    for rs,label,source in ((vaccines,'疫苗','vaccination_records'),(worms,'驅蟲','deworming_events')):
        for row in rs:
            try:
                d=date.fromisoformat(row[0])
                if d>current:
                    future=True;add('日期待核對',label+'日期晚於今日：'+row[0],source)
                if label=='驅蟲' and intake and d<intake:
                    add('日期待核對','驅蟲日期早於本次入所：'+row[0],source)
            except (TypeError,ValueError):
                add('日期待核對',label+'日期格式無效。',source)
    return findings,future

def refresh(db,current=None):
    current=current or datetime.now(TZ).date()
    initial=migrate(db)
    last=db.execute("SELECT value FROM consistency_meta WHERE key='day'").fetchone()
    if not last or last[0]!=current.isoformat():
        db.execute('INSERT OR IGNORE INTO consistency_dirty SELECT animal_id FROM consistency_cache WHERE future_date=1')
        db.execute("INSERT OR REPLACE INTO consistency_meta VALUES ('day',?)",(current.isoformat(),))
    ids=[r[0] for r in db.execute('SELECT animal_id FROM consistency_dirty ORDER BY animal_id')]
    for aid in ids:
        findings,future=inspect(db,aid,current)
        if db.execute('SELECT 1 FROM animals WHERE id=? AND is_active=1',(aid,)).fetchone():
            db.execute('INSERT OR REPLACE INTO consistency_cache VALUES (?,?,?)',(aid,json.dumps(findings,ensure_ascii=False),int(future)))
        else:
            db.execute('DELETE FROM consistency_cache WHERE animal_id=?',(aid,))
        db.execute('DELETE FROM consistency_dirty WHERE animal_id=?',(aid,))
    if ids or initial:
        db.execute("INSERT OR REPLACE INTO consistency_meta VALUES ('checked_at',?)",(datetime.now(TZ).isoformat(),))
    checked=db.execute("SELECT value FROM consistency_meta WHERE key='checked_at'").fetchone()
    return {'initial':initial,'checked_count':len(ids),'checked_at':checked[0] if checked else None}

def result(db,animal_id=None):
    query='SELECT findings FROM consistency_cache'
    args=()
    if animal_id is not None:
        query+=' WHERE animal_id=?';args=(animal_id,)
    return [item for row in db.execute(query+' ORDER BY animal_id',args) for item in json.loads(row[0])]
