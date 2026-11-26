"""Build and cache care summaries using authorized, structured care facts."""
from datetime import datetime, timezone
import json
import time
from uuid import uuid4

import llm_service as llm

PROMPT_VERSION = 'care-v4'
HEALTH = {'healthy', 'sick', 'injured', 'serious', 'unknown', 'needs_review'}


def facts(db, task):
    aid = task['animal_id']
    animal = db.execute("""SELECT name,health_status,vaccinated,dewormed
        FROM animals WHERE id=?""", (aid,)).fetchone()
    status = animal['health_status'] if animal['health_status'] in HEALTH else 'unknown'
    lines = {
        'animal_summary': [f"健康登錄：{status}。"],
        'known_issues': [],
        'observations': [f"本次任務：{task['label']}"],
        'unconfirmed': [],
    }
    vaccines = [tuple(r) for r in db.execute("""SELECT id,vaccine_type,administered_date,next_due_date
        FROM vaccination_records WHERE animal_id=? ORDER BY administered_date DESC,id DESC""", (aid,))]
    worms = [tuple(r) for r in db.execute("""SELECT intake_date,completed_date
        FROM deworming_events WHERE animal_id=? ORDER BY completed_date DESC,intake_date DESC""", (aid,))]
    reports = [tuple(r) for r in db.execute("""SELECT r.task_id,r.result,r.reported_at,t.label,r.note
        FROM weekly_reports r JOIN weekly_tasks t ON t.task_id=r.task_id WHERE t.animal_id=?
        ORDER BY r.reported_at DESC,r.task_id""", (aid,))]
    issues = [tuple(r) for r in db.execute("""SELECT task_id,resolved_at,note FROM weekly_issues
        WHERE animal_id=? ORDER BY task_id""", (aid,))]
    ids = [f'animal:{aid}']
    if animal['health_status'] in ('sick','injured','serious'):
        lines['known_issues'].append('動物目前有傷病登錄。')
    if animal['health_status'] in ('unknown','needs_review',None):
        lines['unconfirmed'].append('尚未確認健康狀況。')
    label = task.get('label', '')
    if '疫苗' in label:
        dose = next((record for record in vaccines if record[2]), None)
        if dose:
            ids.append(f'vaccination:{dose[0]}')
            lines['observations'].append(f'最近疫苗紀錄日期：{dose[2]}')
        else:
            lines['unconfirmed'].append('缺少有日期的疫苗紀錄。')
    if '驅蟲' in label:
        if worms:
            intake, completed = worms[0]
            ids.append(f'deworming:{aid}:{intake}')
            lines['observations'].append(f'最近驅蟲紀錄日期：{completed}')
        else:
            lines['unconfirmed'].append('缺少有日期的驅蟲紀錄。')
    related = [r for r in reports if r[3]==label or any(kind in label and kind in r[3]
                                                        for kind in ('疫苗','驅蟲','健康'))]
    for tid, result, reported, report_label, _ in related[:5]:
        ids.append(f'report:{tid}')
        lines['observations'].append(f'{reported[:10]} {report_label}，回報：{result}')
    for tid, resolved, _ in issues:
        if not resolved and ('健康' in label or tid==task.get('task_id')):
            ids.append(f'issue:{tid}')
            lines['known_issues'].append('有一筆待管理者處理的照護異常。')
    version = [animal['health_status'], animal['vaccinated'], animal['dewormed'], vaccines, worms,
               reports, issues, task['label'], task.get('note'), task.get('skill'), task.get('quarters')]
    return lines, ids, version, animal['name']


def select(connect, lines):
    schema = {'type': 'object', 'properties': {
        key: {'type': 'array', 'items': {'type': 'integer'}} for key in lines
    }, 'required': list(lines), 'additionalProperties': False}

    def validate(answer):
        if not isinstance(answer, dict) or answer.keys() != lines.keys():
            raise ValueError('Invalid summary fields')
        ordered = {}
        for key, values in lines.items():
            indices = answer[key]
            if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(values) for i in indices):
                raise ValueError('Invalid summary indices')
            ordered[key] = [values[i] for i in dict.fromkeys([*indices, *range(len(values))])]
        return ordered

    # Text values such as task labels and dates can come from legacy records.
    # Only structured category counts and enumerated health status leave the server.
    model_data = {key: list(range(len(values))) for key, values in lines.items()}
    model_data['animal_summary'] = lines['animal_summary']
    return llm.generate(connect, 'summary',
        'Select and order supplied facts by zero-based index. Return JSON only. Do not diagnose or recommend treatment.',
        model_data, schema, validate)


def summary(connect, task, allow_ai=False):
    owner = uuid4().hex
    model = llm.model_name()
    with connect() as db:
        lines, ids, version, name = facts(db, task)
        data_hash = llm.digest([version, lines])
        key = llm.digest([task['animal_id'], task['label'], data_hash, PROMPT_VERSION, model])
        db.execute('BEGIN IMMEDIATE')
        now = time.time()
        cached = db.execute('SELECT response,created_at FROM llm_summary_cache WHERE cache_key=? AND expires_at>?',
                            (key, now)).fetchone()
        error, mode, owned = None, 'rule_based', False
        if cached:
            lines, mode, now = json.loads(cached['response']), 'cache', cached['created_at']
            llm.count_event(db, 'summary', 'cache_hit')
        else:
            llm.count_event(db, 'summary', 'cache_miss')
            if allow_ai and task['priority'] <= 1:
                error = llm.settings_error()
                if not error:
                    owned = db.execute("""INSERT INTO llm_summary_leases VALUES (?,?,?)
                        ON CONFLICT(cache_key) DO UPDATE SET owner=excluded.owner,until=excluded.until
                        WHERE llm_summary_leases.until<=?""", (key, owner, now + 90, now)).rowcount == 1
                    if not owned:
                        error = 'in_progress'
    if owned:
        try:
            answer, error = select(connect, lines)
            if answer is not None:
                lines, mode, now = answer, 'llm', time.time()
                with connect() as db:
                    db.execute("""INSERT OR REPLACE INTO llm_summary_cache VALUES (?,?,?,?,?,?,?,?,?,?)""",
                               (key, task['animal_id'], task['label'], data_hash, PROMPT_VERSION, model,
                                llm.canonical(lines), llm.canonical(ids), now,
                                now + llm.limit('CACHE_TTL_SECONDS', 86400)))
        finally:
            with connect() as db:
                db.execute('DELETE FROM llm_summary_leases WHERE cache_key=? AND owner=?', (key, owner))
    if mode == 'rule_based':
        with connect() as db:
            llm.count_event(db, 'summary', 'rule')
    return {**lines, 'animal_summary': name + ' · ' + ' '.join(lines['animal_summary']),
            'observations': [*lines['observations'], *([task['note']] if task.get('note') else [])],
            'source_record_ids': [*ids, f"task:{task['task_id']}"], 'mode': mode,
            'fallback_reason': error, 'updated_at': datetime.fromtimestamp(now, timezone.utc).isoformat()}
