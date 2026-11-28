
"""Seven-day scheduling. Plan generation and persistence are separate operations."""
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
import llm_service
import care_workflow as care

def mount(legacy):
    router = APIRouter(prefix='/api/schedule')
    TAIPEI = ZoneInfo('Asia/Taipei')
    INACTIVE = {'done', 'cancelled'}
    # Retired only from the weekly resource scheduling workflow; keep legacy clinical history.
    retired_labels = {'疫苗紀錄待確認','補做驅蟲'}
    schedule_catalog = {label: spec for label, spec in legacy.TASK_CATALOG.items() if label not in retired_labels}


    def migrate(db, import_legacy=True):
        llm_service.migrate(db)
        db.execute("""CREATE TABLE IF NOT EXISTS staff_daily_shifts (
            staff_id INTEGER NOT NULL, day TEXT NOT NULL, attending INTEGER NOT NULL,
            shift_start TEXT NOT NULL, shift_end TEXT NOT NULL, break_start TEXT, break_end TEXT,
            scheduled_hours REAL NOT NULL, available_hours REAL NOT NULL, PRIMARY KEY (staff_id, day))""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_tasks (
            task_id TEXT PRIMARY KEY, animal_id INTEGER NOT NULL, label TEXT NOT NULL,
            skill TEXT NOT NULL, priority INTEGER NOT NULL, quarters INTEGER NOT NULL,
            earliest TEXT NOT NULL, due TEXT, recurring INTEGER NOT NULL DEFAULT 0,
            day TEXT, staff_id INTEGER, start INTEGER, state TEXT NOT NULL DEFAULT 'pending',
            locked INTEGER NOT NULL DEFAULT 0, reason TEXT, note TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_reports (
            task_id TEXT PRIMARY KEY, staff_id INTEGER NOT NULL, result TEXT NOT NULL,
            note TEXT NOT NULL, reported_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_report_withdrawals (
            id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, staff_id INTEGER NOT NULL,
            withdrawn_at TEXT NOT NULL, payload TEXT NOT NULL)""")
        db.execute('CREATE TABLE IF NOT EXISTS weekly_new_tasks (task_id TEXT PRIMARY KEY)')
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_health_report_baseline (
            task_id TEXT PRIMARY KEY, old_status TEXT, event_id INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_plans (
            plan_id TEXT PRIMARY KEY, week TEXT NOT NULL, revision TEXT NOT NULL, body TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_applied (
            week TEXT PRIMARY KEY, event_id INTEGER NOT NULL, solver_status TEXT NOT NULL,
            body TEXT NOT NULL, applied_at TEXT NOT NULL)""")


        db.execute("""CREATE TABLE IF NOT EXISTS weekly_issues (
            task_id TEXT PRIMARY KEY, animal_id INTEGER NOT NULL, note TEXT NOT NULL, resolved_at TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS task_photos (
            photo_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, animal_id INTEGER NOT NULL,
            staff_id INTEGER NOT NULL, uploaded_at TEXT NOT NULL, storage_key TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS care_summary_cache (
            task_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)""")

        db.execute("""CREATE TABLE IF NOT EXISTS weekly_events (
            id INTEGER PRIMARY KEY, animal_id INTEGER, staff_id INTEGER,
            event TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS weekly_intake AFTER INSERT ON animals
            WHEN NEW.is_active=1 BEGIN INSERT INTO weekly_events(animal_id,event) VALUES (NEW.id,'intake'); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS weekly_animal_update AFTER UPDATE OF is_active,health_status ON animals
            WHEN OLD.is_active IS NOT NEW.is_active OR OLD.health_status IS NOT NEW.health_status
            BEGIN INSERT INTO weekly_events(animal_id,event) VALUES (NEW.id,
                CASE WHEN NEW.is_active=0 THEN 'exit' WHEN OLD.is_active=0 THEN 'intake'
                     WHEN NEW.health_status IN ('sick','injured','serious') THEN NEW.health_status ELSE 'health_update' END);
            END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS weekly_exit_tasks AFTER UPDATE OF is_active ON animals
            WHEN OLD.is_active=1 AND NEW.is_active=0
            BEGIN UPDATE weekly_tasks SET state='cancelled', reason='動物已離所'
              WHERE animal_id=NEW.id AND state='pending'
              AND COALESCE(day,earliest)>=COALESCE(NEW.exit_date,date('now','+8 hours')); END""")
        db.execute("""CREATE TRIGGER IF NOT EXISTS weekly_staff_change AFTER UPDATE OF skills,attending,
            weekly_hours,available_hours,scheduled_hours,shift_start,shift_end,break_start,break_end ON staff
            WHEN NEW.profile_id=1 BEGIN INSERT INTO weekly_events(staff_id,event) VALUES (NEW.id,'staff_change'); END""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_staff_accounts (
            user_id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL UNIQUE)""")
        db.execute("""CREATE TABLE IF NOT EXISTS weekly_schedule_migrations (migration TEXT PRIMARY KEY)""")
        if import_legacy and db.execute("INSERT OR IGNORE INTO weekly_schedule_migrations VALUES ('legacy_assignments')").rowcount:
            for offset, staff in enumerate(db.execute('SELECT id FROM staff WHERE profile_id=1 ORDER BY id LIMIT 5')):
                db.execute('INSERT OR IGNORE INTO weekly_staff_accounts VALUES (?,?)', (offset+2, staff['id']))
            for old in db.execute("""SELECT a.*, o.state AS old_state, o.result AS old_result, o.note AS old_note,
                    o.updated_at, m.due_date FROM assignment_snapshot a LEFT JOIN task_overrides o
                    ON o.animal_id=a.animal_id AND o.label=a.label LEFT JOIN task_metadata m ON m.task_id=a.task_id
                    WHERE a.staff_id IS NOT NULL AND a.date IS NOT NULL AND a.start_time IS NOT NULL
                    ORDER BY a.date DESC, a.task_id"""):
                if not old['animal_id'] or old['label'] not in legacy.TASK_CATALOG or old['old_state'] == 'removed':
                    continue
                _, skill, default_hours, urgent = legacy.TASK_CATALOG[old['label']]
                state = 'done' if old['old_state']=='done' else 'pending'
                try:
                    start = slot(old['start_time'])
                    date.fromisoformat(old['date'])
                except (HTTPException,ValueError):
                    continue
                tid = old['task_id']
                if state == 'pending' and '@' in tid and old['label'] not in ('基礎驅蟲','疫苗施打'):
                    tid = tid.split('@',1)[0]
                imported = db.execute("""INSERT OR IGNORE INTO weekly_tasks
                    (task_id,animal_id,label,skill,priority,quarters,earliest,due,day,staff_id,start,state,locked)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (tid,old['animal_id'],old['label'],skill,0 if urgent else 3,quarters(old['hours'] or default_hours),
                     old['date'],old['due_date'],old['date'],old['staff_id'],start,state,old['locked'])).rowcount
                if imported and state == 'done' and old['updated_at']:
                    db.execute('INSERT OR IGNORE INTO weekly_reports VALUES (?,?,?,?,?)',
                               (tid,old['staff_id'],old['old_result'] or 'done',old['old_note'] or '',old['updated_at']))

    def today():
        return datetime.now(TAIPEI).date()


    def week_days(value, rolling=False):
        start = value if rolling else value - timedelta(days=value.weekday())
        return [(start + timedelta(days=n)).isoformat() for n in range(7)]


    def quarters(value):
        return math.ceil(float(value) * 4)


    def clock(value):
        return legacy.quarter_time(value) if value is not None else None


    def slot(value):
        if len(value) != 5 or value[2] != ':' or not (value[:2]+value[3:]).isdigit():
            raise HTTPException(422, '時間格式須為 HH:MM')
        hour, minute = map(int, value.split(':'))
        if hour > 23 or minute not in (0, 15, 30, 45):
            raise HTTPException(422, '請選擇 15 分鐘時間格')
        return hour * 4 + minute // 15


    def rows(db, sql, params=()):
        return [dict(r) for r in db.execute(sql, params)]


    def event_state(db, monday):
        event = db.execute('SELECT COALESCE(MAX(id),0) FROM weekly_events').fetchone()[0]
        applied = db.execute('SELECT * FROM weekly_applied WHERE week=?', (monday,)).fetchone()
        return event, ('needs_update' if not applied or applied['event_id'] != event else 'applied')


    def shifts_for(db, days):
        workers = {w['id']: legacy.staff_row(w) for w in db.execute('SELECT * FROM staff WHERE profile_id=1')}
        overrides = {(s['staff_id'], s['day']): s for s in rows(db, 'SELECT * FROM staff_daily_shifts WHERE day BETWEEN ? AND ?', (days[0], days[-1]))}
        shifts = {}
        for worker_id, worker in workers.items():
            for day in days:
                shifts[worker_id, day] = {**worker, **overrides.get((worker_id, day), {})}
        return workers, shifts


    def populate(db, days, *, reschedule_overdue=False):
        present = today().isoformat()
        if days[-1] < present:
            return
        # Preserve existing vaccine-check assignments by using the remaining check label.
        # Do not create duplicates when a replacement check already exists.
        db.execute("""UPDATE weekly_tasks AS old SET label='確認疫苗紀錄'
            WHERE old.label='疫苗紀錄待確認' AND old.state IN ('pending','in_progress')
            AND NOT EXISTS (SELECT 1 FROM weekly_tasks current WHERE current.animal_id=old.animal_id
                AND current.label='確認疫苗紀錄' AND current.state IN ('pending','in_progress','done'))
            AND old.task_id=(SELECT preferred.task_id FROM weekly_tasks preferred
                WHERE preferred.animal_id=old.animal_id AND preferred.label='疫苗紀錄待確認'
                AND preferred.state IN ('pending','in_progress')
                ORDER BY (preferred.state='in_progress') DESC,(preferred.staff_id IS NOT NULL) DESC,
                    preferred.day DESC,preferred.task_id LIMIT 1)""")
        # Only an explicit optimization request may requeue overdue assigned work.
        if reschedule_overdue:
            db.execute("""INSERT OR IGNORE INTO weekly_tasks
                (task_id,animal_id,label,skill,priority,quarters,earliest,due,note)
                SELECT 'carry:'||t.task_id,t.animal_id,t.label,t.skill,t.priority,t.quarters,?,t.due,t.note
                FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id
                WHERE a.is_active=1 AND t.label='健康問題追蹤' AND t.state='pending' AND t.day<?
                  AND t.task_id=(SELECT latest.task_id FROM weekly_tasks latest
                    WHERE latest.animal_id=t.animal_id AND latest.label=t.label AND latest.state='pending' AND latest.day<?
                    ORDER BY latest.day DESC,latest.task_id LIMIT 1)
                  AND NOT EXISTS (SELECT 1 FROM weekly_tasks carry WHERE carry.task_id='carry:'||t.task_id)
                  AND NOT EXISTS (SELECT 1 FROM weekly_tasks live
                    WHERE live.animal_id=t.animal_id AND live.label=t.label AND live.state IN ('pending','in_progress')
                      AND (live.day IS NULL OR live.day>=?))
                """, (present,present,present,present))
        active = rows(db, 'SELECT * FROM animals WHERE is_active=1')
        for animal in active:
            if animal['health_status'] not in ('sick','injured','serious'):
                continue
            event = db.execute("""SELECT id,created_at FROM weekly_events WHERE animal_id=? AND
                event IN ('sick','injured','serious') ORDER BY id DESC LIMIT 1""", (animal['id'],)).fetchone()
            label = '優先確認健康狀況'
            if not event or db.execute("""SELECT 1 FROM weekly_tasks WHERE animal_id=?
                    AND label IN ('優先確認健康狀況','健康問題追蹤','術後健康追蹤') AND state IN ('pending','in_progress')
                    AND (day IS NULL OR day>=?)""", (animal['id'],present)).fetchone():
                continue
            if db.execute("""SELECT 1 FROM weekly_reports r JOIN weekly_tasks t ON t.task_id=r.task_id
                    WHERE t.animal_id=? AND t.label=? AND datetime(r.reported_at)>=?""",
                    (animal['id'],label,event['created_at'])).fetchone():
                continue
            _, skill, hours, _ = legacy.TASK_CATALOG[label]
            db.execute("""INSERT OR IGNORE INTO weekly_tasks
                (task_id,animal_id,label,skill,priority,quarters,earliest,due)
                VALUES (?,?,?,?,0,?,?,?)""",
                (f"health-event:{event['id']}",animal['id'],label,skill,quarters(hours),max(present,animal['intake_date'] or present),present))
        overrides = {(r['animal_id'], r['label']): r['state'] for r in db.execute('SELECT * FROM task_overrides')}
        intakes = {a['id']:a['intake_date'] or present for a in active}
        health_labels = set(care.GROUPS['健康照護'])
        for task in legacy.build_tasks(active, overrides):
            if task['label'] == '疫苗紀錄待確認':
                label = '確認疫苗紀錄'
                _, skill, hours, _ = schedule_catalog[label]
                # A completed check is sufficient even when the historical injection date is unknown.
                if db.execute("""SELECT 1 FROM weekly_tasks WHERE animal_id=?
                    AND label IN ('確認疫苗紀錄','疫苗紀錄待確認') AND state='done'""", (task['animal_id'],)).fetchone():
                    continue
                task = {**task, 'label':label, 'id':f"{task['animal_id']}:{label}", 'skill':skill, 'hours':hours}
            if task['label']=='基礎驅蟲':
                aid=task['animal_id']
                history=db.execute('SELECT 1 FROM animal_stay_history WHERE animal_id=?',(aid,)).fetchone()
                existing=db.execute("""SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label IN
                    ('確認驅蟲紀錄','基礎驅蟲','更新驅蟲紀錄','更新驅蟲狀態')
                    AND state IN ('pending','in_progress')""",(aid,)).fetchone()
                if not history and not existing:
                    if db.execute("SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label='確認驅蟲紀錄' AND state='done'",(aid,)).fetchone():
                        continue
                    label='確認驅蟲紀錄'
                    _,skill,hours,_=schedule_catalog[label]
                    task={**task,'label':label,'id':f"{aid}:{label}",'skill':skill,'hours':hours,'due_date':None}
            if task['label'] not in schedule_catalog:
                continue
            group=next((labels for labels in care.GROUPS.values() if task['label'] in labels),())
            if group:
                marks=','.join('?' for _ in group)
                if db.execute(f"""SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label IN ({marks})
                    AND label!=? AND state IN ('pending','in_progress')""",(task['animal_id'],*group,task['label'])).fetchone():
                    continue
            pending = db.execute("""SELECT task_id,day FROM weekly_tasks WHERE animal_id=? AND label=?
                          AND state IN ('pending','in_progress') ORDER BY day IS NULL DESC, day DESC""",
                          (task['animal_id'], task['label'])).fetchone()
            if pending and (not reschedule_overdue or task['label'] not in health_labels or not pending['day'] or pending['day']>=present):
                continue
            earliest = max(present,intakes[task['animal_id']])
            if task['label'] == '疫苗施打' and task['due_date']:
                earliest = max(earliest, task['due_date'])
            db.execute("""INSERT OR IGNORE INTO weekly_tasks
                (task_id,animal_id,label,skill,priority,quarters,earliest,due)
                VALUES (?,?,?,?,?,?,?,?)""",
                (f"carry:{pending['task_id']}" if pending else task['id'],
                 task['animal_id'], task['label'], task['skill'], 3 if task['label']=='基礎驅蟲' else task['priority'],
                 quarters(task['hours']), earliest, task['due_date']))


    def tasks_for(db, days):
        placeholders = ','.join('?' for _ in schedule_catalog)
        tasks = rows(db, f"""SELECT t.*, a.name AS animal_name, a.is_active, a.species, a.breed,
                                  a.age_months, a.health_status, a.photo_url, a.intake_date
            FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id
            WHERE t.label IN ({placeholders}) AND (t.day BETWEEN ? AND ? OR
                (t.day IS NULL AND t.earliest<=?)) ORDER BY t.priority,t.task_id""",
            (*schedule_catalog, days[0], days[-1], days[-1]))
        for task in tasks:
            if task['label'] == '基礎驅蟲':
                task['priority'] = 3
        return sorted(tasks,key=lambda task:(task['priority'],task['task_id']))


    def as_task(t):
        result = dict(t)
        result['start_time'] = clock(t['start'])
        result['end_time'] = clock(t['start'] + t['quarters']) if t['start'] is not None else None
        result['hours'] = t['quarters'] / 4
        return result


    def windows(shift):
        if not shift['attending']:
            return []
        begin, end = slot(shift['shift_start']), slot(shift['shift_end'])
        available = []
        for lo, hi in legacy.shift_break_windows(shift):
            if begin < lo:
                available.append((begin, lo))
            begin = hi
        if begin < end:
            available.append((begin, end))
        return available


    def daily_limit(shift):
        return max(0, min(math.floor(shift['available_hours'] * 4), sum(hi-lo for lo,hi in windows(shift)))
                   - quarters(shift['scheduled_hours'])) if shift['attending'] else 0

    def shift_availability(workers, shifts, tasks, days):
        daily_used = defaultdict(int)
        for task in tasks:
            sid, day = task['staff_id'], task['day']
            if sid in workers and day in days and task['state'] != 'cancelled':
                daily_used[sid, day] += task['quarters']
        return {key: max(0, daily_limit(shifts[key]) - daily_used[key]) / 4
                for key in shifts if key[0] in workers}


    def placement(task):
        return (task['staff_id'], task['day'], task['start'])


    def fixed_task(task):
        return task['day'] is not None and (task['locked'] or task['state'] in {'done', 'in_progress'} or task['day'] < today().isoformat())


    def eligible(task, shift, day):
        return task['skill'] in shift['skills'] and (
            task['is_active'] or task['state'] == 'done' or day < today().isoformat())


    def solve(tasks, workers, shifts, days):
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        intervals, daily = defaultdict(list), defaultdict(list)
        choices = defaultdict(list)
        urgent, high, assigned_quarters, late, retained = [], [], [], [], []
        fixed_errors = []
        busy, day_used, date_used = defaultdict(set), defaultdict(int), defaultdict(int)
        completed_daily = defaultdict(int)
        seed_half = defaultdict(int)
        seed_person_half = defaultdict(int)
        half_load = defaultdict(list)
        rest_intervals = defaultdict(list)
        rest_penalties = []
        window_events = defaultdict(list)
        for task in tasks:
            if task['state'] == 'cancelled':
                continue
            tid, length = task['task_id'], task['quarters']
            if fixed_task(task):
                sid, day, start = placement(task)
                key = (sid, day)
                if key not in shifts or start is None:
                    fixed_errors.append(tid)
                    continue
                shift = shifts[key]
                if task['state'] != 'done' and day >= today().isoformat() and (
                    not eligible(task, shift, day) or
                    not any(lo <= start and start + length <= hi for lo, hi in windows(shift))
                ):
                    fixed_errors.append(tid)
                intervals[key].append(model.new_fixed_size_interval_var(start, length, f'fixed_{tid}'))
                daily[key].append(length)
                half = 0 if start < 46 else 1
                half_load[key, half].append(length)
                seed_half[day, half] += length
                seed_person_half[key, half] += length
                for lo, hi in windows(shift):
                    if lo <= start and start + length <= hi:
                        wk = (sid, day, lo, hi)
                        window_events[wk].append((1, start, length))
                        rest_intervals[wk].append(model.new_fixed_size_interval_var(start, length, f'rest_fixed_{tid}'))
                        break
                if not busy[key].isdisjoint(range(start,start+length)):
                    fixed_errors.append(tid)
                busy[key].update(range(start,start+length))
                day_used[key] += length
                date_used[day] += length
                if task['state']=='done' or day < today().isoformat():
                    completed_daily[key] += length
                continue
            if not task['is_active'] or task['state'] in INACTIVE or task['state'] == 'in_progress':
                continue
            for (sid, day), shift in shifts.items():
                if day < max(today().isoformat(), task['earliest']) or not eligible(task, shift, day) or length > daily_limit(shift):
                    continue
                for lo, hi in windows(shift):
                    if hi - lo < length:
                        continue
                    use = model.new_bool_var(f'use_{tid}_{sid}_{day}_{lo}')
                    start = model.new_int_var(lo, hi-length, f'start_{tid}_{sid}_{day}_{lo}')
                    intervals[sid, day].append(model.new_optional_fixed_size_interval_var(start, length, use, f'work_{tid}_{sid}_{day}_{lo}'))
                    daily[sid, day].append(length * use)
                    half_load[(sid, day), 0 if lo < 46 else 1].append(length * use)
                    wk = (sid, day, lo, hi)
                    window_events[wk].append((use, start, length))
                    buffered = model.new_bool_var(f'buffer_{tid}_{sid}_{day}_{lo}')
                    plain = model.new_bool_var(f'plain_{tid}_{sid}_{day}_{lo}')
                    model.add(buffered + plain == use)
                    rest_intervals[wk].append(model.new_optional_fixed_size_interval_var(start, length + 1, buffered, f'buffered_{tid}_{sid}_{day}_{lo}'))
                    rest_intervals[wk].append(model.new_optional_fixed_size_interval_var(start, length, plain, f'plain_interval_{tid}_{sid}_{day}_{lo}'))
                    rest_penalties.append(plain)
                    assigned_quarters.append(length * use)
                    choices[tid].append((use, sid, day, start, lo, hi))
                    if task['priority'] == 0:
                        urgent.append(use)
                    elif task['priority'] == 1:
                        high.append(use)
                    if task['due'] and day > task['due']:
                        late.append(use)
                    if (sid, day) == (task['staff_id'], task['day']) and task['start'] is not None:
                        same = model.new_bool_var(f'keep_{tid}_{sid}_{day}_{lo}')
                        model.add(same <= use)
                        model.add(start == task['start']).only_enforce_if(same)
                        retained.append(same)
            assigned = sum(choice[0] for choice in choices[tid])
            model.add(assigned <= 1)
        if fixed_errors:
            raise HTTPException(409, '固定任務已不可行：' + '、'.join(fixed_errors))
        for key, items in intervals.items():
            model.add_no_overlap(items)
            model.add(sum(daily[key]) <= max(daily_limit(shifts[key]),completed_daily[key]))
        working_days = [day for day in days if day >= today().isoformat()
                        and any(daily_limit(shifts[sid, day]) for sid in workers)]
        bound = sum(t['quarters'] for t in tasks)
        day_loads = [sum(sum(daily[sid, day]) for sid in workers) for day in working_days]
        spread = []
        for day, load in zip(working_days, day_loads):
            delta = model.new_int_var(0, bound * len(working_days), f'load_deviation_{day}')
            model.add_abs_equality(delta, len(working_days)*load - sum(day_loads))
            spread.append(delta)
        balance = sum(spread)
        if len(day_loads)>1:
            busiest = model.new_int_var(0,bound,'busiest_day')
            quietest = model.new_int_var(0,bound,'quietest_day')
            model.add_max_equality(busiest,day_loads)
            model.add_min_equality(quietest,day_loads)
            balance += (bound * len(day_loads)**2 + 1) * (busiest-quietest)
        # Soft objectives: preserve assignment coverage and existing hard constraints.
        half_deviations = []
        for (sid, day), shift in shifts.items():
            if day < today().isoformat():
                continue
            available = windows(shift)
            if not any(lo < 46 for lo, hi in available) or not any(lo >= 46 for lo, hi in available):
                continue
            delta = model.new_int_var(0, bound, f'half_delta_{sid}_{day}')
            model.add_abs_equality(delta, sum(half_load[(sid, day), 0]) - sum(half_load[(sid, day), 1]))
            half_deviations.append(delta)
        # Daily total balance is the primary distribution objective, not a feasibility cutoff.
        daily_half_deviations = []
        for day in working_days:
            am = sum(sum(half_load[(sid, day), 0]) for sid in workers)
            pm = sum(sum(half_load[(sid, day), 1]) for sid in workers)
            delta = model.new_int_var(0, bound, f'daily_half_delta_{day}')
            model.add_abs_equality(delta, am - pm)
            daily_half_deviations.append(delta)
        worst_daily_half = model.new_int_var(0, bound, 'worst_daily_half_delta')
        model.add_max_equality(worst_daily_half, daily_half_deviations or [0])
        # First minimize the worst individual daily AM/PM imbalance, then the total.
        worst_half = model.new_int_var(0, bound, 'worst_half_delta')
        model.add_max_equality(worst_half, half_deviations or [0])
        gap_deviations = []
        for wk, events in window_events.items():
            sid, day, lo, hi = wk
            model.add_no_overlap(rest_intervals[wk])
            starts, ends, uses, lengths = [], [], [], []
            for i, (use, start, length) in enumerate(events):
                a = model.new_int_var(lo, hi, f'gap_start_{wk}_{i}')
                b = model.new_int_var(lo, hi, f'gap_end_{wk}_{i}')
                if isinstance(use, int):
                    model.add(a == start)
                    model.add(b == start + length)
                else:
                    model.add(a == start).only_enforce_if(use)
                    model.add(b == start + length).only_enforce_if(use)
                    model.add(a == hi).only_enforce_if(use.Not())
                    model.add(b == lo).only_enforce_if(use.Not())
                starts.append(a)
                ends.append(b)
                uses.append(use)
                lengths.append(length * use)
            first = model.new_int_var(lo, hi, f'gap_first_{wk}')
            last = model.new_int_var(lo, hi, f'gap_last_{wk}')
            model.add_min_equality(first, starts)
            model.add_max_equality(last, ends)
            span = model.new_int_var(0, hi-lo, f'gap_span_{wk}')
            model.add_max_equality(span, [last-first, 0])
            count_minus_one = model.new_int_var(0, len(events), f'gap_count_{wk}')
            model.add_max_equality(count_minus_one, [sum(uses)-1, 0])
            deviation = model.new_int_var(0, hi-lo+len(events), f'gap_deviation_{wk}')
            model.add_abs_equality(deviation, span-sum(lengths)-count_minus_one)
            gap_deviations.append(deviation)
        # A validated greedy schedule is also a safe incumbent if CP-SAT times out.
        for key, used in day_used.items():
            if used > max(daily_limit(shifts[key]), completed_daily[key]):
                raise HTTPException(409, '固定任務超出每日工時上限')
        seed = {}
        for task in tasks:
            tid, length = task['task_id'], task['quarters']
            options = choices[tid]
            options.sort(key=lambda option:(bool(task['due'] and option[2]>task['due']),
                                            abs(seed_half[option[2], 0] - seed_half[option[2], 1] + (length if option[4] < 46 else -length)) - abs(seed_half[option[2], 0] - seed_half[option[2], 1]),
                                            date_used[option[2]],
                                            abs(seed_person_half[(option[1],option[2]), 0] - seed_person_half[(option[1],option[2]), 1] + (length if option[4] < 46 else -length)),
                                            day_used[option[1],option[2]],
                                            (option[1],option[2])!=(task['staff_id'],task['day']),
                                            option[2],option[1]))
            assigned = False
            for use,sid,day,var,lo,hi in options:
                key = sid, day
                start = lo
                selected = False
                if not assigned and day_used[key]+length<=daily_limit(shifts[key]):
                    previous = task['start'] if (sid,day)==placement(task)[:2] else None
                    candidates = list(range(lo,hi-length+1))
                    if previous in candidates:
                        candidates.remove(previous)
                        candidates.insert(0,previous)
                    for tick in candidates:
                        if busy[key].isdisjoint(range(tick,tick+length)):
                            start = tick
                            selected = assigned = True
                            busy[key].update(range(tick,tick+length))
                            day_used[key] += length
                            date_used[day] += length
                            half = 0 if tick < 46 else 1
                            seed_half[day, half] += length
                            seed_person_half[key, half] += length
                            seed[tid] = (sid, day, tick)
                            break
                model.add_hint(use,int(selected))
                model.add_hint(var,start)

        solver = cp_model.CpSolver()
        phase_seconds = max(0.01, float(os.environ.get('SHELTER_SOLVER_PHASE_SECONDS','6')))
        solver.parameters.num_search_workers = 4
        best = seed.copy()
        status_name = 'FEASIBLE'
        proved_optimal = True
        # Keep task coverage and clinical priorities; then balance every day before
        # optimizing individual balance and the 15-minute rest target.
        primary = [-sum(assigned_quarters), -sum(urgent), -sum(high), sum(late),
                   worst_daily_half, sum(daily_half_deviations)]
        # Lexicographic objective: every incumbent already considers daily AM/PM balance.
        # Each component ranges over at most bound quarters (or task count).
        radix = max(2, bound + 1, len(tasks) + 1)
        # CP-SAT validates domains conservatively; cap coefficients using option count.
        option_count = sum(len(options) for options in choices.values())
        combined = radix**5 * max(1, option_count) * max(1, bound) < 2**60
        if combined:
            primary = [sum(term * radix**(5-i) for i, term in enumerate(primary))]
        objectives = primary + [worst_half, sum(half_deviations),
                                sum(rest_penalties), sum(gap_deviations), balance, -sum(retained)]
        objectives = [item for item in objectives if not isinstance(item,int)] or [model.new_constant(0)]
        deadline = time.monotonic() + max(0.01, float(os.environ.get(
            'SHELTER_SOLVER_TOTAL_SECONDS', str(phase_seconds * (len(objectives) + (5 if combined else 0))))))
        for objective in objectives:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status_name = 'FEASIBLE'
                break
            solver.parameters.max_time_in_seconds = min(phase_seconds * (6 if combined and objective is objectives[0] else 1), remaining)
            model.minimize(objective)
            status = solver.solve(model)
            if status == cp_model.INFEASIBLE:
                raise HTTPException(409, '無法同時滿足固定任務、班表、休息及工時上限')
            if status == cp_model.MODEL_INVALID:
                raise HTTPException(500, '派工模型設定錯誤')
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                # No new incumbent: keep the last valid schedule, never read UNKNOWN values.
                status_name = 'FEASIBLE'
                break
            proved_optimal = proved_optimal and status == cp_model.OPTIMAL
            status_name = 'OPTIMAL' if proved_optimal else 'FEASIBLE'
            candidate = {tid: (sid,day,solver.value(start)) for tid,options in choices.items()
                         for use,sid,day,start,_,_ in options if solver.boolean_value(use)}
            # The first objective is coverage; never replace the seed with a worse one.
            if objective is objectives[0]:
                lengths = {t['task_id']: t['quarters'] for t in tasks}
                def primary_score(plan):
                    by_day = defaultdict(int)
                    for task in tasks:
                        tid = task['task_id']
                        if fixed_task(task) and task['state'] != 'cancelled':
                            sid, day, start = placement(task)
                        elif tid in plan:
                            sid, day, start = plan[tid]
                        else:
                            continue
                        if start is not None:
                            by_day[day] += task['quarters'] * (1 if start < 46 else -1)
                    differences = [abs(by_day[day]) for day in working_days]
                    selected = [task for task in tasks if task['task_id'] in plan]
                    return (-sum(lengths[t] for t in plan),
                            -sum(t['priority'] == 0 for t in selected),
                            -sum(t['priority'] == 1 for t in selected),
                            sum(bool(t['due'] and plan[t['task_id']][1] > t['due']) for t in selected),
                            max(differences, default=0), sum(differences))
                if (primary_score(candidate) > primary_score(best) if combined else
                        sum(lengths[t] for t in candidate) < sum(lengths[t] for t in best)):
                    status_name = 'FEASIBLE'
                    break
            best = candidate
            model.add(objective == round(solver.objective_value))
            model.clear_hints()
            for options in choices.values():
                for use,_,_,start,_,_ in options:
                    model.add_hint(use,solver.value(use))
                    model.add_hint(start,solver.value(start))
        changes = []
        for task in tasks:
            if fixed_task(task) or task['state'] in INACTIVE or task['state'] == 'in_progress':
                continue
            tid = task['task_id']
            candidates = choices[tid]
            after = best.get(tid,(None,None,None))
            reason = None
            if after[0] is None:
                if not task['is_active']:
                    reason = '動物已離所'
                elif not candidates:
                    reason = '無符合技能、班表與日期的員工'
                elif status_name == 'FEASIBLE':
                    reason = '目前可行方案未安排，尚未證明最佳'
                else:
                    reason = '依任務優先級與班表工時限制保留在任務池'
            if placement(task) != after or task['reason'] != reason:
                previous = shifts.get((task['staff_id'], task['day']))
                adjustment = reason or ('原員工該日不出勤' if previous and not previous['attending'] else
                    '依技能、班表、任務期限與工作量重新配置' if task['staff_id'] else '依技能、班表與任務期限指派')
                changes.append({'task_id': tid, 'animal_name': task['animal_name'], 'label': task['label'],
                                'before': placement(task), 'after': after, 'reason': reason,
                                'adjustment_reason': adjustment})
        return changes, status_name


    def revision(db):
        digest = hashlib.sha256()
        for table in ('animals', 'staff', 'staff_daily_shifts', 'profiles', 'weekly_tasks',
                      'weekly_reports', 'weekly_issues', 'weekly_events', 'task_overrides', 'generated_tasks', 'vaccination_records',
                      'deworming_events', 'assignment_snapshot'):
            digest.update(json.dumps(rows(db, f'SELECT * FROM {table} ORDER BY rowid'), sort_keys=True, default=str).encode())
        digest.update(today().isoformat().encode())
        return digest.hexdigest()


    def staff_identity(db, request):
        uid = request.state.user_id
        if uid == 1:
            return None
        record = db.execute('SELECT s.id FROM weekly_staff_accounts a JOIN staff s ON s.id=a.staff_id WHERE a.user_id=? AND s.profile_id=1', (uid,)).fetchone()
        if not record:
            raise HTTPException(403, '目前帳號未連結員工')
        return record['id']


    @router.get('/overview')
    def overview(request: Request):
        if request.state.user_id != 1:
            raise HTTPException(403, '僅管理者可查看全所資源')
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            current = today().isoformat()
            days = week_days(today(), rolling=True)
            populate(db, days)
            profile = db.execute('SELECT * FROM profiles WHERE id=1').fetchone()
            if not profile:
                raise HTTPException(404, '找不到收容所設定')
            active = rows(db, 'SELECT * FROM animals WHERE is_active=1')
            food,care = legacy.resource_totals(active,profile['food_rate'],profile['care_minutes'])
            workers,shifts = shifts_for(db,days)
            tasks = tasks_for(db,days)
            pending = [t for t in tasks if t['is_active'] and t['state'] in ('pending','in_progress')
                       and (t['day']==current or (t['day'] is None and t['earliest']<=current))]
            available = shift_availability(workers, shifts, tasks, days)
            issues = db.execute("""SELECT COUNT(*) FROM weekly_issues i JOIN animals a ON a.id=i.animal_id
                                    WHERE i.resolved_at IS NULL AND a.is_active=1""").fetchone()[0]
            _, schedule_status = event_state(db, days[0])
        return {'date':current,'current_count':len(active),'capacity':profile['capacity'],
                'remaining_capacity':max(0,profile['capacity']-len(active)),
                'daily_food_kg':round(food,2),'daily_care_hours':round(care,2),
                'available_hours':sum(available[sid,current] for sid in workers),'pending_tasks':len(pending),
                'urgent_tasks':sum(t['priority']<=1 for t in pending),'open_issues':issues,
                'schedule_status':schedule_status}

    @router.get('/health-tasks')
    def health_tasks(request: Request):
        if request.state.user_id!=1:
            raise HTTPException(403,'僅管理者可查看全所健康行政任務')
        with legacy.lock,legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            populate(db,week_days(today(),rolling=True))
            marks=','.join('?' for _ in care.RULES)
            result=[]
            for t in db.execute(f"""SELECT t.*,a.name AS animal_name,r.result,r.reported_at,r.note AS report_note
                FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id
                LEFT JOIN weekly_reports r ON r.task_id=t.task_id
                WHERE a.is_active=1 AND t.label IN ({marks}) AND t.state!='cancelled'
                AND NOT EXISTS (SELECT 1 FROM weekly_tasks c WHERE c.task_id='carry:'||t.task_id)
                ORDER BY COALESCE(t.due,t.earliest),t.priority,t.animal_id""",tuple(care.RULES)):
                category,skill,hours,serious=legacy.TASK_CATALOG[t['label']]
                result.append(dict(id=t['task_id'],animal_id=t['animal_id'],animal_name=t['animal_name'],
                    label=t['label'],category=category,skill=skill,hours=t['quarters']/4,serious=serious,
                    state='done' if t['state']=='done' else 'pending',due_date=t['due'] or t['earliest'],
                    priority=t['priority'],completed_at=t['reported_at'],result=t['result'],note=t['report_note'] or t['note']))
            return result

    @router.get('/week')
    def get_week(week: date, request: Request, rolling: bool = False):
        days = week_days(week, rolling)
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            sid = staff_identity(db, request)
            if sid is None:
                populate(db, days)
            workers, shifts = shifts_for(db, days)
            tasks = tasks_for(db, days)
            reports = {r['task_id']: r for r in rows(db, 'SELECT * FROM weekly_reports')}
            if sid is not None:
                tasks = [task for task in tasks if task['staff_id'] == sid]
                workers = {key: value for key, value in workers.items() if key == sid}
            available = shift_availability(workers, shifts, tasks, days)
            event_id, schedule_status = event_state(db, days[0]) if sid is None else (0, None)
            placeholders = ','.join('?' for _ in schedule_catalog)
            overdue = rows(db, f"""SELECT t.task_id,t.label,t.due,t.day,a.name AS animal_name
                FROM weekly_tasks t JOIN animals a ON a.id=t.animal_id
                WHERE t.label IN ({placeholders}) AND t.state IN ('pending','in_progress') AND COALESCE(t.due,t.day)<?
                AND (? IS NULL OR t.staff_id=?) ORDER BY COALESCE(t.due,t.day),t.task_id LIMIT 100""",
                (*schedule_catalog,today().isoformat(),sid,sid)) if days[-1] >= today().isoformat() else []
            photos = defaultdict(list)
            for image in rows(db, 'SELECT task_id,photo_id FROM task_photos'):
                photos[image['task_id']].append(image['photo_id'])
            issues = {r['task_id']: r for r in rows(db, 'SELECT * FROM weekly_issues')}
            new_tasks = {r[0] for r in db.execute('SELECT task_id FROM weekly_new_tasks')}
            derived = {(r['animal_id'], r['label']) for r in db.execute("""SELECT g.animal_id,g.label
                FROM generated_tasks g JOIN task_metadata m ON m.task_id=g.task_id WHERE m.source='employee_report'""")}
            result = []
            for task in tasks:
                tid = task['task_id']
                origin = tid
                while origin.startswith('carry:'):
                    origin = origin.removeprefix('carry:')
                generated = origin.startswith(('health-event:', 'followup:'))
                item = {**as_task(task), 'report': reports.get(tid), 'is_new': tid in new_tasks or generated,
                        'is_derived': generated or (task['animal_id'],task['label']) in derived,
                        'photos': photos[tid], 'issue': issues.get(tid)}
                # Display colours only; solver priorities remain unchanged.
                colours = {'優先確認健康狀況':0, '健康狀態待確認':1,
                           '健康問題追蹤':5, '疫苗施打':3, '確認疫苗紀錄':3, '基礎驅蟲':3}
                if item['label'] in colours:
                    item['display_priority'] = colours[item['label']]
                elif item['is_derived']:
                    item['display_priority'] = 3
                result.append(item)
            if sid is not None:
                for item in result:
                    item['summary'] = {
                        'animal_summary': f"{item['animal_name']} · 健康登錄：{item['health_status']}",
                        'known_issues': ['有待處理的照護異常。'] if item['issue'] and not item['issue']['resolved_at'] else [],
                        'observations': [f"本次任務：{item['label']}"], 'unconfirmed': [],
                        'mode': 'rule_based', 'fallback_reason': None,
                        'source_record_ids': [f"task:{item['task_id']}"],
                    }
        return {'days': days, 'event_id':event_id, 'schedule_status':schedule_status, 'overdue':overdue, 'workers': list(workers.values()),
                'shifts': [{**shift, 'day': day, 'assignable_hours': available[key, day],
                            'daily_capacity_hours':daily_limit(shift)/4,
                            'break_windows':[(clock(lo),clock(hi)) for lo,hi in legacy.shift_break_windows(shift)]}
                           for (key, day), shift in shifts.items() if key in workers],
                    'tasks': result}

    @router.post('/tasks/{task_id}/summary')
    def task_summary(task_id: str, request: Request):
        from care_summary import summary
        with legacy.connect() as db:
            sid = staff_identity(db, request)
            task = db.execute('SELECT * FROM weekly_tasks WHERE task_id=?', (task_id,)).fetchone()
            if not task or (sid is not None and task['staff_id'] != sid):
                raise HTTPException(404, '找不到可查看的任務')
        return summary(legacy.connect, dict(task), allow_ai=task['state'] in ('pending', 'in_progress'))


    class ShiftInput(BaseModel):
        attending: bool
        shift_start: str
        shift_end: str
        break_start: str | None = None
        break_end: str | None = None
        scheduled_hours: float = Field(ge=0, le=24)
        available_hours: float = Field(ge=0, le=24)


    @router.put('/shifts/{staff_id}/{day}')
    def save_shift(staff_id: int, day: date, body: ShiftInput):
        if day < today():
            raise HTTPException(409, '歷史班表只供查閱')
        start, end = slot(body.shift_start), slot(body.shift_end)
        if start >= end or bool(body.break_start) != bool(body.break_end) or (
            body.break_start and not start <= slot(body.break_start) < slot(body.break_end) <= end
        ):
            raise HTTPException(422, '班表或休息時間無效')
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            if not db.execute('SELECT 1 FROM staff WHERE id=? AND profile_id=1', (staff_id,)).fetchone():
                raise HTTPException(404, '找不到員工')
            db.execute("""INSERT INTO staff_daily_shifts VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(staff_id,day) DO UPDATE SET attending=excluded.attending,
                shift_start=excluded.shift_start,shift_end=excluded.shift_end,break_start=excluded.break_start,
                break_end=excluded.break_end,scheduled_hours=excluded.scheduled_hours,available_hours=excluded.available_hours""",
                (staff_id, day.isoformat(), body.attending, body.shift_start, body.shift_end,
                 body.break_start, body.break_end, body.scheduled_hours, body.available_hours))
            db.execute("INSERT INTO weekly_events(staff_id,event) VALUES (?,?)", (staff_id,"shift" if body.attending else "leave"))
        return {'ok': True}


    @router.post('/preview')
    def preview(week: date, rolling: bool = False):
        days = week_days(week, rolling)
        if days[-1] < today().isoformat():
            raise HTTPException(409, '歷史週只供查閱')
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            populate(db, days, reschedule_overdue=True)
            workers, shifts = shifts_for(db, days)
            tasks = tasks_for(db, days)
            version = revision(db)
        # Preview must not change any existing placement. Only unlock invalid lunch
        # placements in the solver's private copy; apply handles the actual update.
        lunch_start, lunch_end = legacy.SHELTER_LUNCH
        lunch_ids = {t['task_id'] for t in tasks if t['state'] == 'pending' and t['is_active']
                     and t['day'] and t['day'] >= today().isoformat() and t['start'] is not None
                     and t['start'] < lunch_end and t['start'] + t['quarters'] > lunch_start}
        solver_tasks = [dict(t, locked=0) if t['task_id'] in lunch_ids else t for t in tasks]
        changes, status = solve(solver_tasks, workers, shifts, days)
        for change in changes:
            if change['task_id'] in lunch_ids:
                change['unlock_lunch'] = True
        plan_id = uuid4().hex
        with legacy.connect() as db:
            db.execute('INSERT INTO weekly_plans VALUES (?,?,?,?)',
                       (plan_id, days[0], version, json.dumps({'changes': changes, 'status': status})))
        return {'plan_id': plan_id if status in ('OPTIMAL', 'FEASIBLE') else None,
                'changes': changes, 'solver_status': status}


    @router.post('/apply/{plan_id}')
    def apply(plan_id: str):
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            plan = db.execute('SELECT * FROM weekly_plans WHERE plan_id=?', (plan_id,)).fetchone()
            if not plan or revision(db) != plan['revision']:
                raise HTTPException(409, '排程資料已變更，請重新預覽')
            proposal = json.loads(plan['body'])
            if not isinstance(proposal, dict) or proposal.get('status') not in ('OPTIMAL', 'FEASIBLE'):
                raise HTTPException(409, '此預覽沒有可套用的可行解')
            for change in proposal['changes']:
                sid, day, start = change['after']
                if sid is not None and start is not None:
                    length = db.execute('SELECT quarters FROM weekly_tasks WHERE task_id=?',(change['task_id'],)).fetchone()[0]
                    lunch_start,lunch_end = legacy.SHELTER_LUNCH
                    if start<lunch_end and start+length>lunch_start:
                        raise HTTPException(409,'預覽包含與午休重疊的任務，請重新預覽')
                db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=?,reason=?,locked=CASE WHEN ? THEN 0 ELSE locked END WHERE task_id=?',
                           (sid, day, start, change['reason'], bool(change.get('unlock_lunch')), change['task_id']))
            event, _ = event_state(db, plan['week'])
            db.execute('INSERT OR REPLACE INTO weekly_applied VALUES (?,?,?,?,?)',
                       (plan['week'], event, proposal['status'], plan['body'], datetime.now(TAIPEI).isoformat()))
            db.execute('DELETE FROM weekly_plans WHERE plan_id=?', (plan_id,))
        return {'ok': True}


    class MoveInput(BaseModel):
        staff_id: int | None = None
        day: date | None = None
        start_time: str | None = None
        locked: bool = True


    @router.patch('/tasks/{task_id}/placement')
    def move(task_id: str, body: MoveInput):
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            task = db.execute("""SELECT t.*, a.is_active, a.intake_date FROM weekly_tasks t
                JOIN animals a ON a.id=t.animal_id WHERE task_id=?""", (task_id,)).fetchone()
            if not task:
                raise HTTPException(404, '找不到任務')
            if task['label'] not in schedule_catalog:
                raise HTTPException(422, '此任務類型未列入健康行政核對')
            if not task['is_active']:
                raise HTTPException(422, '動物已離所')
            if task['state'] != 'pending' or (task['day'] and task['day'] < today().isoformat()):
                raise HTTPException(409, '僅可移動尚未執行的任務')
            if body.staff_id is None:
                raise HTTPException(409, '已指派任務只能透過七天最佳化派工重新移回任務池')
            if body.day is None or body.start_time is None or body.day < today():
                raise HTTPException(422, '請指定今天或未來的日期及開始時間')
            days = week_days(body.day)
            day, start = body.day.isoformat(), slot(body.start_time)
            _, shifts = shifts_for(db, days)
            key = body.staff_id, day
            shift = shifts.get(key)
            length = task['quarters']
            if shift and any(start<hi and start+length>lo for lo,hi in legacy.shift_break_windows(shift)):
                raise HTTPException(422, '與休息時間重疊')
            if not shift or not eligible(task, shift, day) or not any(
                lo <= start and start + length <= hi for lo, hi in windows(shift)
            ):
                raise HTTPException(422, '技能、出勤或班表時段不符')
            assignments = [t for t in tasks_for(db, days) if t['staff_id'] == body.staff_id and
                           t['task_id'] != task_id and t['day'] in days and t['state'] != 'cancelled']
            for other in assignments:
                if other['day'] == day and start < other['start'] + other['quarters'] and other['start'] < start + length:
                    raise HTTPException(409, '該時間與既有任務重疊')
            if length + sum(t['quarters'] for t in assignments if t['day'] == day) > daily_limit(shift):
                raise HTTPException(409, '超出每日可用工時')
            db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=?,locked=?,reason=NULL WHERE task_id=?',
                       (body.staff_id, day, start, body.locked, task_id))
        return {'ok': True}


    class NewTask(BaseModel):
        animal_id: int
        label: str
        earliest: date
        due: date
        priority: int = Field(ge=0, le=4)
        note: str = Field(default='', max_length=2000)


    @router.post('/tasks')
    def create_task(body: NewTask):
        catalog = schedule_catalog
        if body.label not in catalog or body.earliest < today() or body.due < body.earliest:
            raise HTTPException(422, '任務類型或允許日期無效')
        _, skill, hours, _ = catalog[body.label]
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            if not db.execute('SELECT 1 FROM animals WHERE id=? AND is_active=1', (body.animal_id,)).fetchone():
                raise HTTPException(404, '找不到在所動物')
            populate(db, week_days(body.earliest))
            duplicate = db.execute("""SELECT task_id FROM weekly_tasks WHERE animal_id=? AND label=?
                AND state IN ('pending','in_progress') ORDER BY earliest LIMIT 1""", (body.animal_id, body.label)).fetchone()
            if duplicate:
                db.execute('INSERT OR IGNORE INTO weekly_new_tasks VALUES (?)', (duplicate['task_id'],))
                db.execute('UPDATE weekly_tasks SET priority=min(priority,?),note=? WHERE task_id=?',
                           (body.priority, body.note, duplicate['task_id']))
                db.execute('INSERT INTO weekly_events(animal_id,event) VALUES (?,?)',
                           (body.animal_id,'task_updated'))
                return {'task_id': duplicate['task_id']}
            task_id = uuid4().hex
            db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due,note)
                VALUES (?,?,?,?,?,?,?,?,?)""", (task_id, body.animal_id, body.label, skill,
                body.priority, quarters(hours), body.earliest.isoformat(), body.due.isoformat(), body.note))
            db.execute('INSERT INTO weekly_events(animal_id,event) VALUES (?,?)',
                       (body.animal_id,'urgent_task' if body.priority<=1 else 'task_created'))
            db.execute('INSERT INTO weekly_new_tasks VALUES (?)', (task_id,))
        return {'task_id': task_id}


    class ReportInput(BaseModel):
        result: str
        note: str = Field(default='', max_length=4000)
        administered_date: date | None = None
        photos: list[str] = Field(default_factory=list, max_length=4)
        expected_day: date | None = None


    @router.post('/tasks/{task_id}/report')
    def report(task_id: str, body: ReportInput, request: Request):
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            staff_id = staff_identity(db, request)
            task = db.execute("""SELECT t.*, a.intake_date, a.is_active FROM weekly_tasks t
                JOIN animals a ON a.id=t.animal_id WHERE task_id=?""", (task_id,)).fetchone()
            if not task:
                raise HTTPException(404, '找不到任務')
            if staff_id is None or staff_id != task['staff_id']:
                raise HTTPException(403, '只能回報自己的任務')
            prior=db.execute('SELECT result,note FROM weekly_reports WHERE task_id=?',(task_id,)).fetchone()
            if prior:
                if prior['result']!=body.result or prior['note']!=body.note:
                    raise HTTPException(409,'已有不同回報，請先核對原紀錄')
                return {'ok': True}
            if body.expected_day is not None and (task['day']!=body.expected_day.isoformat() or body.expected_day!=today()):
                raise HTTPException(409,'任務日期已變動，請重新查詢')
            if db.execute('SELECT 1 FROM weekly_tasks WHERE task_id=?', (f'carry:{task_id}',)).fetchone():
                raise HTTPException(409, '逾期任務已重新入池，請使用新的指派回報')
            if (not task['is_active'] or not task['day'] or task['day'] > today().isoformat()
                or (task['reason']=='任務延遲' and task['day']<task['earliest'])
                or task['state'] not in ('pending','in_progress')):
                raise HTTPException(409, '此任務目前不可回報')
            label, result, animal_id = task['label'], body.result, task['animal_id']
            if label not in schedule_catalog:
                raise HTTPException(422, '此任務類型已停用')
            if result not in care.allowed(label):
                raise HTTPException(422,'回報選項不適用：'+care.outcomes(label))
            if label=='更新疫苗紀錄' and result=='done':
                dose=body.administered_date
                if dose is None and not db.execute("SELECT 1 FROM vaccination_records WHERE animal_id=? AND administered_date IS NOT NULL AND next_due_date IS NOT NULL",(animal_id,)).fetchone():
                    raise HTTPException(422,'缺少可信施打日期；請提供實際施打日期，不可假設為今天')
                if dose is not None:
                    if dose>today():
                        raise HTTPException(422,'實際施打日期不可晚於今日')
                    db.execute("""INSERT OR IGNORE INTO vaccination_records(animal_id,administered_date,next_due_date)
                        VALUES (?,?,?)""",(animal_id,dose.isoformat(),legacy.month_after(dose,12).isoformat()))
                db.execute("UPDATE animals SET vaccinated='yes' WHERE id=?",(animal_id,))
            if label in ('更新驅蟲狀態','更新驅蟲紀錄') and result=='done':
                db.execute("UPDATE animals SET dewormed='yes' WHERE id=?",(animal_id,))
            if label=='更新絕育狀態' and result=='done':
                db.execute("UPDATE animals SET sterilized='yes' WHERE id=?",(animal_id,))
            if label in ('基礎驅蟲','補做驅蟲') and result == 'done':
                db.execute("""INSERT OR IGNORE INTO deworming_events
                    (animal_id,intake_date,completed_date) VALUES (?,?,?)""",
                    (animal_id, task['intake_date'], today().isoformat()))
                db.execute("UPDATE animals SET dewormed='yes' WHERE id=?", (animal_id,))
            if (label == '確認疫苗紀錄' and result == 'yes') or (label == '疫苗施打' and result == 'done'):
                # Confirming a prior injection need not invent an unknown historical date.
                # Completing an administration task records today's dose unless an explicit date is supplied.
                dose = body.administered_date or (today() if label == '疫苗施打' else None)
                if dose is not None:
                    if dose > today():
                        raise HTTPException(422, '實際施打日期不可晚於今日')
                    if not db.execute("""SELECT 1 FROM vaccination_records
                        WHERE animal_id=? AND vaccine_type='general' AND administered_date=?""", (animal_id, dose.isoformat())).fetchone():
                        db.execute("""INSERT INTO vaccination_records (animal_id,administered_date,next_due_date)
                            VALUES (?,?,?)""", (animal_id, dose.isoformat(), legacy.month_after(dose,12).isoformat()))
                db.execute("UPDATE animals SET vaccinated='yes' WHERE id=?", (animal_id,))
            health_result={'recovered':'healthy','abnormal':'needs_review'}.get(result,result)
            if health_result in ('healthy','sick','injured','needs_review'):
                old_status = db.execute('SELECT health_status FROM animals WHERE id=?', (animal_id,)).fetchone()[0]
                db.execute('UPDATE animals SET health_status=? WHERE id=?', (health_result, animal_id))
                if old_status != health_result:
                    event_id = db.execute('SELECT MAX(id) FROM weekly_events WHERE animal_id=?', (animal_id,)).fetchone()[0]
                    db.execute('INSERT OR REPLACE INTO weekly_health_report_baseline VALUES (?,?,?)',
                               (task_id,old_status,event_id))
            if body.photos:
                from care_photos import save, validate
                images = [validate(encoded) for encoded in body.photos]
                for image in images:
                    key = save(image)
                    db.execute('INSERT INTO task_photos VALUES (?,?,?,?,?,?)',
                               (uuid4().hex, task_id, animal_id, staff_id, datetime.now(TAIPEI).isoformat(), key))
            if result in care.ISSUE_RESULTS:
                db.execute('INSERT INTO weekly_issues(task_id,animal_id,note) VALUES (?,?,?)', (task_id,animal_id,body.note))
            db.execute('INSERT INTO weekly_reports VALUES (?,?,?,?,?)',
                       (task_id, staff_id, result, body.note, datetime.now(TAIPEI).isoformat()))
            db.execute("UPDATE weekly_tasks SET state='done' WHERE task_id=?", (task_id,))
            source_id=task_id
            while source_id.startswith('carry:'):
                source_id=source_id.removeprefix('carry:')
            parent=source_id.removeprefix('followup:') if source_id.startswith('followup:') else None
            surgery_parent=bool(parent and db.execute("SELECT 1 FROM weekly_tasks WHERE task_id=? AND label='絕育手術'",(parent,)).fetchone())
            retry_label=care.next_task(label,result,from_surgery=surgery_parent)
            if retry_label:
                existing=db.execute("""SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label=?
                    AND state IN ('pending','in_progress')""",(animal_id,retry_label)).fetchone()
                if not existing:
                    _,skill,hours,urgent=legacy.TASK_CATALOG[retry_label]
                    earliest=today().isoformat()
                    if result in ('failed','defer','improving','not_recovered') and retry_label==label:
                        earliest=(today()+timedelta(days=1)).isoformat()
                    db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due,note)
                        VALUES (?,?,?,?,?,?,?,?,?)""",(f'followup:{task_id}',animal_id,retry_label,skill,
                        0 if urgent else 3,quarters(hours),earliest,earliest,body.note))
            if label=='更新疫苗紀錄' and result=='done':
                latest=db.execute("""SELECT next_due_date FROM vaccination_records WHERE animal_id=? AND vaccine_type='general'
                    AND next_due_date IS NOT NULL ORDER BY administered_date DESC,id DESC LIMIT 1""",(animal_id,)).fetchone()
                if latest:
                    due=latest['next_due_date']
                    _,skill,hours,_=legacy.TASK_CATALOG['疫苗施打']
                    db.execute("""INSERT OR IGNORE INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due)
                        VALUES (?,?, '疫苗施打',?,3,?,?,?)""",(f'{animal_id}:疫苗施打@{due}',animal_id,skill,quarters(hours),max(due,today().isoformat()),due))
            if label in care.RULES:
                db.execute('INSERT INTO weekly_events(animal_id,event) VALUES (?,?)',(animal_id,'task_report'))
        return {'ok': True}

    @router.post('/tasks/{task_id}/withdraw-report')
    def withdraw_report(task_id: str, request: Request):
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            sid = staff_identity(db, request)
            record = db.execute("""SELECT r.*,t.animal_id,a.is_active FROM weekly_reports r
                JOIN weekly_tasks t ON t.task_id=r.task_id JOIN animals a ON a.id=t.animal_id
                WHERE r.task_id=? AND r.staff_id=? AND t.staff_id=? AND t.state='done'""",
                (task_id,sid,sid)).fetchone()
            if not record:
                raise HTTPException(404, '找不到可收回的本人回報')
            if not record['is_active'] or record['reported_at'][:10] != today().isoformat():
                raise HTTPException(409, '僅可收回今日在所動物的回報')
            issue = db.execute('SELECT * FROM weekly_issues WHERE task_id=?', (task_id,)).fetchone()
            followup_id = f'followup:{task_id}'
            followups = []
            for candidate in rows(db, 'SELECT * FROM weekly_tasks WHERE animal_id=?', (record['animal_id'],)):
                origin = candidate['task_id']
                while origin.startswith('carry:'):
                    origin = origin.removeprefix('carry:')
                if origin == followup_id:
                    followups.append(candidate)
            followup = next((f for f in followups if f['task_id']==followup_id), None)
            if (issue and issue['resolved_at']) or any(f['staff_id'] is not None or f['state'] != 'pending' or f['locked'] for f in followups):
                raise HTTPException(409, '這筆回報已有處理或派工紀錄，請由管理者確認')
            photos = rows(db, 'SELECT * FROM task_photos WHERE task_id=?', (task_id,))
            archived = {'report':dict(record), 'issue':dict(issue) if issue else None,
                        'followup':dict(followup) if followup else None, 'followups':followups, 'photos':photos}
            db.execute("""INSERT INTO weekly_report_withdrawals(task_id,staff_id,withdrawn_at,payload)
                VALUES (?,?,?,?)""", (task_id,sid,datetime.now(TAIPEI).isoformat(),json.dumps(archived,ensure_ascii=False)))
            for child in followups:
                for table in ('weekly_new_tasks','care_summary_cache','weekly_tasks'):
                    db.execute(f'DELETE FROM {table} WHERE task_id=?', (child['task_id'],))
            # Undo only the withdrawn health assessment, not independently recorded medical history.
            baseline = db.execute('SELECT * FROM weekly_health_report_baseline WHERE task_id=?', (task_id,)).fetchone()
            if baseline:
                latest = db.execute("""SELECT MAX(id) FROM weekly_events WHERE animal_id=?
                    AND event IN ('sick','injured','serious','health_update','intake','exit')""", (record['animal_id'],)).fetchone()[0]
                if latest == baseline['event_id']:
                    db.execute('UPDATE animals SET health_status=? WHERE id=? AND health_status=?',
                               (baseline['old_status'],record['animal_id'],{'recovered':'healthy','abnormal':'needs_review'}.get(record['result'],record['result'])))
                    db.execute("""DELETE FROM weekly_tasks WHERE task_id=? AND state='pending'
                        AND staff_id IS NULL AND locked=0""", (f"health-event:{baseline['event_id']}",))
                db.execute('DELETE FROM weekly_health_report_baseline WHERE task_id=?', (task_id,))
            db.execute('DELETE FROM task_photos WHERE task_id=?', (task_id,))
            db.execute('DELETE FROM weekly_issues WHERE task_id=?', (task_id,))
            db.execute('DELETE FROM weekly_reports WHERE task_id=?', (task_id,))
            db.execute("UPDATE weekly_tasks SET state='pending' WHERE task_id=?", (task_id,))
            db.execute("INSERT INTO weekly_events(animal_id,event) VALUES (?,'report_withdrawn')", (record['animal_id'],))
        return {'ok': True}

    @router.get('/tasks/{task_id}/photos/{photo_id}')
    def photo(task_id: str, photo_id: str, request: Request):
        from care_photos import read
        with legacy.connect() as db:
            migrate(db)
            sid = staff_identity(db, request)
            image = db.execute('SELECT * FROM task_photos WHERE task_id=? AND photo_id=?', (task_id,photo_id)).fetchone()
            if not image or (sid is not None and image['staff_id'] != sid):
                raise HTTPException(404, '找不到照片')
        return Response(read(image['storage_key']), media_type='image/jpeg',
                        headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    class TaskEvent(BaseModel):
        event: str
        earliest: date | None = None

    @router.post('/tasks/{task_id}/event')
    def task_event(task_id: str, body: TaskEvent):
        with legacy.lock, legacy.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate(db)
            task = db.execute('SELECT * FROM weekly_tasks WHERE task_id=?', (task_id,)).fetchone()
            if not task or task['state'] != 'pending':
                raise HTTPException(409, '此任務已開始、已結束或不存在')
            if body.event == 'start' and task['day'] == today().isoformat():
                db.execute("UPDATE weekly_tasks SET state='in_progress' WHERE task_id=?", (task_id,))
            elif body.event == 'delay' and body.earliest and body.earliest >= today() and not task['recurring'] and not task['locked']:
                db.execute("""UPDATE weekly_tasks SET earliest=?,
                    reason='任務延遲' WHERE task_id=?""",
                    (body.earliest.isoformat(),task_id))
            else:
                raise HTTPException(422, '此事件不適用，或任務已手動鎖定')
            db.execute('INSERT INTO weekly_events(animal_id,event) VALUES (?,?)', (task['animal_id'],body.event))
        return {'ok':True}

    @router.post('/tasks/{task_id}/resolve')
    def resolve(task_id: str):
        with legacy.connect() as db:
            migrate(db)
            changed = db.execute('UPDATE weekly_issues SET resolved_at=? WHERE task_id=? AND resolved_at IS NULL',
                                 (datetime.now(TAIPEI).isoformat(),task_id)).rowcount
            if changed != 1:
                raise HTTPException(404, '找不到未解決異常')
            db.execute("""INSERT INTO weekly_events(animal_id,event)
                SELECT animal_id,'issue_resolved' FROM weekly_issues WHERE task_id=?""", (task_id,))
        return {'ok': True}

    with legacy.lock, legacy.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        migrate(db, import_legacy=False)
    from shelter_chat import mount as mount_chat
    chat_router=mount_chat(legacy, staff_identity, today, week_days, shifts_for, daily_limit, tasks_for)
    legacy.app.include_router(chat_router)
    from smart_tools import mount as mount_smart
    smart_router=mount_smart(legacy, populate, week_days, schedule_catalog, quarters)
    legacy.app.include_router(smart_router)
    from chat_agent import mount as mount_agent
    read_chat=next(r.endpoint for r in chat_router.routes if r.path=='/api/chat')
    command=next(r.endpoint for r in smart_router.routes if r.path=='/api/smart/command')
    check=next(r.endpoint for r in smart_router.routes if r.path=='/api/smart/check')
    legacy.app.include_router(mount_agent(legacy,read_chat,command,check))
    return router
