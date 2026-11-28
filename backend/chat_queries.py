"""Execute validated chat query plans against the existing read-only schedule helpers."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
from care_workflow import display_label

TAIPEI = ZoneInfo('Asia/Taipei')
ACTIVE = ('pending','in_progress')
HEALTH = {'sick','injured','serious','needs_review','unknown'}

def day_range(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]

def overlap(lo, hi, left, right):
    return max(0,min(hi,right)-max(lo,left))

def period_bounds(period):
    # Fixed midday break is excluded separately by the schedule's break helper.
    return (0,48) if period=='morning' else (48,96) if period=='afternoon' else (0,96)

def hours(q):
    return f'{q/4:g} 小時'

def staff_metrics(legacy, shift, tasks, daily_limit, period):
    left,right = period_bounds(period)
    occupied = set()
    used = 0
    total = 0
    for task in tasks:
        if task['state']=='cancelled':
            continue
        total += task['quarters']
        if task['start'] is not None:
            start,end = task['start'],task['start']+task['quarters']
            used += overlap(start,end,left,right)
            occupied.update(range(max(left,start),min(right,end)))
    daily_remaining = max(0,daily_limit(shift)-total)
    if period=='all_day':
        return total,daily_remaining
    if not shift['attending']:
        return used,0
    start,end = legacy.time_quarter(shift['shift_start']),legacy.time_quarter(shift['shift_end'])
    available = set(range(max(start,left),min(end,right)))
    for lo,hi in legacy.shift_break_windows(shift):
        available.difference_update(range(lo,hi))
    return used,min(len(available-occupied),daily_remaining)

def execute(legacy, db, plan, sid, shifts_for, daily_limit, tasks_for, task_answer):
    """All identifiers are resolved locally and rechecked by the caller; scope again here."""
    intent,period = plan['intent'],plan['period']
    days = day_range(plan['start'],plan['end'])
    staff_id,animal_id,task_id = (plan.get(k) for k in ('staff_id','animal_id','task_id'))
    workers, shifts = shifts_for(db,days)
    if sid is not None:
        workers = {k:v for k,v in workers.items() if k==sid}
    if staff_id is not None:
        workers = {k:v for k,v in workers.items() if k==staff_id}
        if not workers:
            return ['目前沒有可查看的員工紀錄。'],[],{}
    if sid is not None and intent in ('capacity','leave_impact','unassigned_tasks'):
        return ['此查詢僅提供管理者使用。'],[],{}
    if intent=='capacity':
        if plan.get('explicit_date') and (days!=[plan['today']] or period!='all_day'):
            return ['目前只能查詢即時收容數與容量，不能以目前資料推算指定日期的容量。'],[],{}
        species = plan.get('species')
        count = db.execute('SELECT COUNT(*) FROM animals WHERE is_active=1').fetchone()[0]
        profile = db.execute('SELECT capacity FROM profiles WHERE id=1').fetchone()
        detail = f'設定容量 {profile[0]} 隻，剩餘 {max(0,profile[0]-count)} 隻。' if profile else '目前沒有容量設定。'
        result = [f'目前在養 {count} 隻。{detail}']
        if species:
            n = db.execute('SELECT COUNT(*) FROM animals WHERE is_active=1 AND species=?',(species,)).fetchone()[0]
            result.append(f'其中{"犬隻" if species=="dog" else "貓隻"} {n} 隻。')
        return result,['在養動物名單','收容所設定 #1'],{}
    tasks = [t for t in tasks_for(db,days) if sid is None or t['staff_id']==sid]
    if staff_id is not None:
        tasks = [t for t in tasks if t['staff_id']==staff_id]
    left,right = period_bounds(period)
    dated = [t for t in tasks if t['day'] in days and (period=='all_day' or
             (t['start'] is not None and overlap(t['start'],t['start']+t['quarters'],left,right)))]
    title = days[0] if len(days)==1 else f'{days[0]} 至 {days[-1]}'
    title += {'morning':' 上午','afternoon':' 下午','all_day':''}[period]
    if intent in ('staff_workload','staff_availability','workload_balance'):
        if plan.get('species'):
            return ['目前剩餘工時按員工全部工作計算，尚無依犬貓物種判定可支援資格的資料。請改查整體可用工時。'],[],{}
        metrics=[]
        for key,worker in workers.items():
            used=remaining=am=pm=0
            for day in days:
                own=[t for t in tasks if t['staff_id']==key and t['day']==day]
                a,b=staff_metrics(legacy,shifts[key,day],own,daily_limit,period)
                used+=a;remaining+=b
                am+=staff_metrics(legacy,shifts[key,day],own,daily_limit,'morning')[0]
                pm+=staff_metrics(legacy,shifts[key,day],own,daily_limit,'afternoon')[0]
            metrics.append((key,worker['name'],used,remaining,am,pm))
        idx=3 if intent=='staff_availability' else 2
        if plan['sort']!='none' and metrics:
            best=(max if plan['sort']=='most' else min)(x[idx] for x in metrics)
            metrics=[x for x in metrics if x[idx]==best]
        if not metrics:
            return ['目前沒有可查看的員工班表。'],[],{}
        if intent=='workload_balance':
            lines=[f'{title} · {name} 上午 {hours(am)}，下午 {hours(pm)}，差 {hours(abs(am-pm))}。'
                   for key,name,used,remaining,am,pm in metrics]
            lines.insert(0,f'全體可查看員工上午 {hours(sum(x[4] for x in metrics))}，下午 {hours(sum(x[5] for x in metrics))}。')
        else:
            lines=[f'{name} · {title} 已排 {hours(used)}，剩餘 {"最多 " if period!="all_day" else ""}{hours(remaining)}。'
                   for key,name,used,remaining,am,pm in metrics]
        if period!='all_day' and intent!='workload_balance':
            lines.append('時段剩餘量為依班表、休息、任務及每日額度計算的上限；未定位的既有工時可能進一步減少可用時間。')
        return lines,[f'員工班表 #{x[0]} · {title}' for x in metrics],({'staff_id':metrics[0][0]} if len(metrics)==1 else {})
    if intent=='open_issues':
        rows=db.execute("""SELECT i.task_id,i.animal_id,a.name,a.species,r.reported_at
            FROM weekly_issues i JOIN weekly_tasks t ON t.task_id=i.task_id
            JOIN animals a ON a.id=i.animal_id LEFT JOIN weekly_reports r ON r.task_id=i.task_id
            WHERE i.resolved_at IS NULL AND (? IS NULL OR t.staff_id=?)
            ORDER BY r.reported_at DESC,i.task_id""",(sid,sid)).fetchall()
        rows=[r for r in rows if (animal_id is None or r['animal_id']==animal_id)
              and (not plan.get('species') or r['species']==plan['species'])
              and (not plan.get('explicit_date') or (r['reported_at'] and r['reported_at'][:10] in days))]
        lines=[f'{r["name"]} · {r["reported_at"][:10] if r["reported_at"] else "日期未記錄"} · 待處理異常' for r in rows[:12]]
        return [f'目前符合條件的待處理異常共 {len(rows)} 筆。',*lines],[f'任務 {r["task_id"]}' for r in rows[:12]],{}
    if intent=='schedule_changes':
        if period!='all_day':
            return ['目前最佳化紀錄僅支援按方案日期查詢，請移除時段限制。'],[],{}
        if plan.get('explicit_date'):
            records=db.execute('SELECT * FROM weekly_applied WHERE week BETWEEN ? AND ? ORDER BY applied_at DESC',(days[0],days[-1])).fetchall()
        else:
            records=db.execute('SELECT * FROM weekly_applied ORDER BY applied_at DESC LIMIT 1').fetchall()
        if not records:
            return ['目前沒有符合日期的已套用最佳化紀錄。'],[],{}
        lines=[];sources=[]
        for record in records:
            record_tasks=[t for t in tasks_for(db,day_range(record['week'],(date.fromisoformat(record['week'])+timedelta(days=6)).isoformat())) if sid is None or t['staff_id']==sid]
            if staff_id is not None:
                record_tasks=[t for t in record_tasks if t['staff_id']==staff_id]
            ids={c['task_id'] for c in json.loads(record['body'])['changes']}
            matched=[t for t in record_tasks if t['task_id'] in ids]
            a,b=task_answer(matched,'方案中可查看的變動任務',workers)
            lines.extend([f'套用時間 {record["applied_at"]}，CP-SAT {record["solver_status"]}。',*a]);sources.extend(b)
        return lines,sources,{}
    # Task-specific queries: all filtering happens after role scope.
    if task_id and intent=='assignment_reason' and not plan.get('explicit_date'):
        row=db.execute('SELECT day,earliest FROM weekly_tasks WHERE task_id=? AND (? IS NULL OR staff_id=?)',(task_id,sid,sid)).fetchone()
        if row:
            key=row['day'] or row['earliest']
            tasks=[t for t in tasks_for(db,[key]) if t['task_id']==task_id and (sid is None or t['staff_id']==sid)]
            dated=tasks
    if intent=='unassigned_tasks':
        if period!='all_day':
            return ['未指派任務尚無安排時段，請查詢全天。'],[],{}
        selected=[t for t in tasks if not t['staff_id'] and t['state'] in ACTIVE and t['is_active'] and t['earliest']<=days[-1]]
        name=title+' 待指派任務'
    else:
        selected=[t for t in dated if t['state']!='cancelled']
        if intent=='completed_tasks':
            selected=[t for t in selected if t['state']=='done']
        elif intent not in ('staff_schedule','assignment_reason'):
            selected=[t for t in selected if t['state'] in ACTIVE and t['is_active']]
        if intent in ('pending_tasks','urgent_tasks','assignment_reason') and sid is None and staff_id is None and period=='all_day':
            selected.extend(t for t in tasks if not t['day'] and t['earliest']<=days[-1] and t['state'] in ACTIVE and t['is_active'])
        name=title+' '+{'staff_schedule':'排定任務','pending_tasks':'待完成任務','completed_tasks':'已完成任務','urgent_tasks':'需優先留意的照護任務','next_task':'下一項排定任務','leave_impact':'請假時需核對的任務','assignment_reason':'排程原因'}.get(intent,'任務')
    if animal_id is not None:
        selected=[t for t in selected if t['animal_id']==animal_id]
    if task_id:
        selected=[t for t in selected if t['task_id']==task_id]
    if plan.get('species'):
        selected=[t for t in selected if t['species']==plan['species']]
    if plan.get('labels'):
        selected=[t for t in selected if t['label'] in plan['labels']]
    if intent=='urgent_tasks':
        selected=[t for t in selected if t['priority']<=1 or t['health_status'] in ('sick','injured','serious')]
    if intent=='leave_impact' and staff_id is None:
        return ['請提供查詢的員工姓名，例如「照顧人員02 明天請假會影響哪些任務？」。'],[],{}
    selected.sort(key=lambda t:(t['day'] or '9999', t['start'] if t['start'] is not None else 96,t['priority'],t['task_id']))
    if intent=='next_task':
        now=datetime.now(TAIPEI)
        tick=now.hour*4+now.minute//15
        selected=[t for t in selected if t['start'] is not None and (t['day']!=plan['today'] or t['start']+t['quarters']>tick)][:1]
    if intent=='assignment_reason':
        if not selected:
            return ['目前沒有符合條件且可查看的任務。請提供動物名稱、任務名稱或任務 ID。'],[],{}
        lines=[f'找到 {len(selected)} 項符合的任務，以下為已記錄的排程原因：']
        sources=[]
        for t in selected[:12]:
            reason=t['reason'] or ('目前已指派，沒有其他已記錄原因。' if t['staff_id'] else '目前沒有已記錄的未指派原因。')
            lines.append(f'{t["day"] or "待指派"} · {t["animal_name"]} · {display_label(t["label"])}：{reason}')
            sources.append(f'任務 {t["task_id"]}')
        if len(selected)>12:
            lines.append('僅顯示前 12 項，可提供任務 ID 縮小範圍。')
    else:
        lines,sources=task_answer(selected,name,workers,plan['count_only'])
    extra={}
    if len(selected)==1:
        t=selected[0]
        extra={'task_id':t['task_id'],'animal_id':t['animal_id'],'staff_id':t['staff_id']}
    return lines,sources,extra
