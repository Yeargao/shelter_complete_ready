"""Shared report effects, dependency provenance and conservative clinical correction.

The weekly report transaction is the only writer of report effects. Legacy
reports lack reliable before-images; they may be reviewed but never guessed.
"""
import json
from uuid import uuid4
import care_workflow as care

FIELDS = ('health_status', 'vaccinated', 'dewormed', 'sterilized')
MEDICAL_TABLES = ('vaccination_records', 'deworming_events')


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS weekly_report_effects (
        task_id TEXT PRIMARY KEY, before_payload TEXT NOT NULL, after_payload TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS weekly_report_dependencies (
        parent_id TEXT NOT NULL, child_id TEXT NOT NULL, PRIMARY KEY(parent_id,child_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS weekly_report_owned_tasks (task_id TEXT PRIMARY KEY)""")
    db.execute("""CREATE TABLE IF NOT EXISTS weekly_retained_dependencies (
        parent_id TEXT NOT NULL, child_id TEXT NOT NULL, result TEXT NOT NULL,
        PRIMARY KEY(parent_id,child_id,result))""")
    db.execute("""CREATE TABLE IF NOT EXISTS weekly_clinical_versions (
        animal_id INTEGER NOT NULL, field TEXT NOT NULL, version INTEGER NOT NULL,
        PRIMARY KEY(animal_id,field))""")
    for field in FIELDS:
        # Count even a same-value write: another valid report may affirm it.
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS weekly_clinical_version_{field}
            AFTER UPDATE OF {field} ON animals BEGIN
              INSERT INTO weekly_clinical_versions VALUES (NEW.id,'{field}',1)
                ON CONFLICT(animal_id,field) DO UPDATE SET version=version+1;
            END""")


def snapshot(db, animal_id):
    animal = dict(db.execute('SELECT * FROM animals WHERE id=?',(animal_id,)).fetchone())
    versions = {r['field']:r['version'] for r in db.execute(
        'SELECT field,version FROM weekly_clinical_versions WHERE animal_id=?',(animal_id,))}
    return {'fields':{f:animal[f] for f in FIELDS},
            'versions':{f:versions.get(f,0) for f in FIELDS},
            'intake_date':animal['intake_date'],
            **{table:rows(db,f'SELECT * FROM {table} WHERE animal_id=?',(animal_id,))
               for table in MEDICAL_TABLES}}


def save_effects(db, task_id, before, after):
    db.execute('INSERT OR REPLACE INTO weekly_report_effects VALUES (?,?,?)',
               (task_id,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False)))


def root(task_id):
    while task_id.startswith('carry:'):
        task_id=task_id.removeprefix('carry:')
    return task_id


def child_id(db, parent):
    base='followup:'+parent
    return base if not db.execute('SELECT 1 FROM weekly_tasks WHERE task_id=?',(base,)).fetchone() else base+':'+uuid4().hex


def link(db, parent, child, created=False):
    child=root(child)
    if created:
        db.execute('INSERT OR IGNORE INTO weekly_report_owned_tasks VALUES (?)',(child,))
    db.execute('INSERT OR IGNORE INTO weekly_report_dependencies VALUES (?,?)',(parent,child))


def from_surgery(db, task_id):
    child=root(task_id)
    if db.execute("""SELECT 1 FROM weekly_report_dependencies d
        JOIN weekly_tasks t ON t.task_id=d.parent_id
        JOIN weekly_reports r ON r.task_id=d.parent_id
        WHERE d.child_id=? AND t.label='絕育手術' AND r.result='done'""",(child,)).fetchone():
        return True
    # Legacy tasks created before provenance was introduced.
    if db.execute('SELECT 1 FROM weekly_report_dependencies WHERE child_id=?',(child,)).fetchone():
        return False
    return child.startswith('followup:') and bool(db.execute(
        "SELECT 1 FROM weekly_tasks WHERE task_id=? AND label='絕育手術'",
        (child.removeprefix('followup:'),)).fetchone())


def retained(db, parent, label, result, due=None):
    for r in db.execute("""SELECT child_id FROM weekly_retained_dependencies
        WHERE parent_id=? AND result=?""",(parent,result)):
        for task in rows(db,"SELECT * FROM weekly_tasks WHERE label=? AND state IN ('in_progress','done')",(label,)):
            if root(task['task_id'])==r['child_id'] and (due is None or task['due']==due):
                return task['task_id']
    return None


def dependencies(db, record):
    task_id=record['task_id']
    roots={r[0] for r in db.execute('SELECT child_id FROM weekly_report_dependencies WHERE parent_id=?',(task_id,))}
    # Include historical explicit follow-up IDs and carry descendants. For old
    # reports, missing provenance prevents automatic cancellation when uncertain.
    has_effects=db.execute('SELECT 1 FROM weekly_report_effects WHERE task_id=?',(task_id,)).fetchone()
    if not has_effects:
        roots.add('followup:'+task_id)
    baseline=db.execute('SELECT event_id FROM weekly_health_report_baseline WHERE task_id=?',(task_id,)).fetchone()
    if baseline:
        roots.add('health-event:'+str(baseline[0]))
    candidates=rows(db,'SELECT * FROM weekly_tasks WHERE animal_id=?',(record['animal_id'],))
    groups={}
    for child in candidates:
        key=root(child['task_id'])
        if key in roots:
            groups.setdefault(key,[]).append(child)
    result=[]
    for key,children in groups.items():
        other=db.execute("""SELECT 1 FROM weekly_report_dependencies d
            JOIN weekly_reports r ON r.task_id=d.parent_id
            WHERE d.child_id=? AND d.parent_id!=?""",(key,task_id)).fetchone()
        manual=any(db.execute('SELECT 1 FROM weekly_new_tasks WHERE task_id=?',(c['task_id'],)).fetchone() for c in children)
        owned=db.execute('SELECT 1 FROM weekly_report_owned_tasks WHERE task_id=?',(key,)).fetchone()
        # Legacy source reconstruction is deliberately conservative.
        exclusive=bool((owned or (baseline and key=='health-event:'+str(baseline[0])))
                       and has_effects and not other and not manual)
        started=any(c['state'] in ('in_progress','done') for c in children)
        result.append({'root':key,'tasks':children,'exclusive':exclusive,'started':started,
                       'uncertain':not bool(has_effects) and not other and not manual})
    return result


def status(db, record, sid, today):
    if not record or (sid is not None and record['staff_id']!=sid):
        return {'allowed':False,'reason':'找不到可收回的本人回報','requires_review':False,'can_correct':False}
    effects=db.execute('SELECT 1 FROM weekly_report_effects WHERE task_id=?',(record['task_id'],)).fetchone()
    issue=db.execute('SELECT resolved_at FROM weekly_issues WHERE task_id=?',(record['task_id'],)).fetchone()
    children=dependencies(db,record)
    reasons=[]
    if not record['is_active']:reasons.append('動物已離所')
    if record['reported_at'][:10]!=today:reasons.append('跨日回報')
    if issue and issue['resolved_at']:reasons.append('問題已結案')
    if any(c['started'] for c in children):reasons.append('衍生任務已開始或完成')
    if any(c['uncertain'] for c in children):reasons.append('舊回報的衍生來源無法確認')
    return {'allowed':bool(record['is_active'] and (sid is None or not reasons)),
            'reason':'；'.join(reasons) if reasons else None,'requires_review':bool(reasons),
            'can_correct':bool(effects),
            'cancel_count':sum(c['exclusive'] and not c['started'] for c in children),
            'retain_count':sum(c['started'] or not c['exclusive'] for c in children)}


def restore_clinical(db, record):
    effects=db.execute('SELECT * FROM weekly_report_effects WHERE task_id=?',(record['task_id'],)).fetchone()
    if not effects:
        raise ValueError('舊回報沒有原始資料快照，不能自動復原醫療資料')
    before,after=json.loads(effects['before_payload']),json.loads(effects['after_payload'])
    aid=record['animal_id']
    current=snapshot(db,aid)
    if current['intake_date']!=after['intake_date']:
        raise ValueError('動物入所期間已變更，須人工核對醫療紀錄')
    preserved=[]
    for field in FIELDS:
        if before['fields'][field]==after['fields'][field]:
            continue
        if current['versions'][field]!=after['versions'][field] or current['fields'][field]!=after['fields'][field]:
            preserved.append(field)
        else:
            db.execute(f'UPDATE animals SET {field}=? WHERE id=?',(before['fields'][field],aid))
    # Remove only rows introduced by this exact report, never a pre-existing
    # administration. Later reports in the same workflow may rely on these rows.
    for table in MEDICAL_TABLES:
        inserted=[r for r in after[table] if r not in before[table]]
        group='疫苗' if table=='vaccination_records' else '驅蟲'
        labels=tuple(care.GROUPS[group])
        marks=','.join('?' for _ in labels)
        later=db.execute(f"""SELECT 1 FROM weekly_reports r JOIN weekly_tasks t ON t.task_id=r.task_id
            WHERE t.animal_id=? AND r.task_id!=? AND t.label IN ({marks})
            AND julianday(r.reported_at)>=julianday(?)""",(aid,record['task_id'],*labels,record['reported_at'])).fetchone()
        for row in inserted:
            if row not in current[table] or later:
                preserved.append(table)
                continue
            if table=='vaccination_records':
                if db.execute('SELECT 1 FROM task_vaccination_link WHERE record_id=?',(row['id'],)).fetchone():
                    preserved.append(table)
                    continue
                db.execute('DELETE FROM vaccination_records WHERE id=? AND animal_id=?',(row['id'],aid))
            else:
                db.execute('DELETE FROM deworming_events WHERE animal_id=? AND intake_date=? AND completed_date=?',
                           (aid,row['intake_date'],row['completed_date']))
    return sorted(set(preserved))
