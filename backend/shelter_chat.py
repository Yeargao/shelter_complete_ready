"""Role-scoped shelter queries and optional Gemini synthesis."""
from datetime import date, datetime, timedelta
import hashlib
import hmac
import json
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import llm_service as llm


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=500)
    context: str | None = Field(default=None, max_length=120)


SCHEMA = {'type': 'object', 'properties': {'order': {'type': 'array', 'items': {'type': 'integer'}}},
          'required': ['order'], 'additionalProperties': False}
ACTIVE = ('pending', 'in_progress')
HEALTH = {'healthy': '健康', 'sick': '生病', 'injured': '受傷', 'serious': '嚴重狀況',
          'needs_review': '待確認', 'unknown': '未確認'}
TAIPEI = ZoneInfo('Asia/Taipei')


def mount(legacy, staff_identity, today, week_days, shifts_for, daily_limit, tasks_for):
    router = APIRouter(prefix='/api')

    def sign(request, aid):
        authorization = request.headers.get('Authorization', '')
        signature = hmac.new(legacy.AUTH_SECRET, f'chat:{authorization}:{aid}'.encode(), hashlib.sha256)
        return f'{aid}.{signature.hexdigest()}'

    def context_id(request, context):
        match = re.fullmatch(r'([1-9][0-9]{0,17})\.[a-f0-9]{64}', context or '')
        if match and hmac.compare_digest(context, sign(request, match[1])):
            return int(match[1])
        return None

    def animal_scope(db, sid, question, context):
        if sid is None:
            animals = db.execute('SELECT id,name,health_status FROM animals ORDER BY id')
        else:
            animals = db.execute("""SELECT id,name,health_status FROM animals WHERE EXISTS (
                SELECT 1 FROM weekly_tasks t WHERE t.animal_id=animals.id AND t.staff_id=?
                AND t.state!='cancelled') ORDER BY id""", (sid,))
        allowed = list(animals)
        explicit = re.search(r'(?:動物\s*#?|#)\s*([0-9]{1,18})', question)
        if explicit:
            return next((item for item in allowed if item['id'] == int(explicit[1])), None)
        names = [item for item in allowed if item['name'] and item['name'] in question]
        if names:
            length = max(len(item['name']) for item in names)
            matches = [item for item in names if len(item['name']) == length]
            return matches[0] if len(matches) == 1 else None
        if any(word in question for word in ('牠', '這隻', '該動物')):
            return next((item for item in allowed if item['id'] == context), None)
        return None

    def animal_details(db, animal, question, sid):
        aid = animal['id']
        health = animal['health_status']
        name = animal['name']
        sources = [f'動物 #{aid}']
        worms = db.execute("""SELECT completed_date FROM deworming_events WHERE animal_id=?
            ORDER BY completed_date DESC LIMIT 1""", (aid,)).fetchone()
        dose = db.execute("""SELECT id,administered_date FROM vaccination_records WHERE animal_id=?
            ORDER BY administered_date DESC,id DESC LIMIT 1""", (aid,)).fetchone()
        if '驅蟲' in question:
            if worms:
                sources.append('驅蟲紀錄 ' + worms['completed_date'])
            return [f'{name}最近一次有日期的驅蟲紀錄為 {worms[0]}。' if worms else f'{name}目前沒有具日期的驅蟲紀錄。'], sources, None
        if '疫苗' in question:
            if dose:
                sources.append(f'疫苗紀錄 #{dose["id"]}')
            return [f'{name}最近的疫苗日期為 {dose[1]}。' if dose else f'{name}目前沒有具日期的疫苗紀錄。'], sources, None
        reports = list(db.execute("""SELECT r.task_id,r.reported_at,r.result FROM weekly_reports r
            JOIN weekly_tasks t ON t.task_id=r.task_id WHERE t.animal_id=? AND (? IS NULL OR r.staff_id=?)
            ORDER BY r.reported_at DESC,r.task_id LIMIT 4""", (aid, sid, sid)))
        issues = db.execute("""SELECT COUNT(*) FROM weekly_issues i JOIN weekly_tasks t ON t.task_id=i.task_id
            WHERE i.animal_id=? AND i.resolved_at IS NULL AND (? IS NULL OR t.staff_id=?)""", (aid, sid, sid)).fetchone()[0]
        lines = [f'{name}的健康登錄為「{HEALTH.get(health, "未確認")}」。',
                 f'目前可查看的待處理異常共 {issues} 筆。',
                 f'最近疫苗日期：{dose[1]}。' if dose else '目前沒有具日期的疫苗紀錄。',
                 f'最近驅蟲日期：{worms[0]}。' if worms else '目前沒有具日期的驅蟲紀錄。']
        safe_facts = [{'health': health if health in HEALTH else 'unknown'}, {'open_reports': issues},
                      {'vaccine_record_exists': bool(dose)}, {'deworming_record_exists': bool(worms)}]
        if dose:
            sources.append(f'疫苗紀錄 #{dose["id"]}')
        if worms:
            sources.append('驅蟲紀錄 ' + worms[0])
        labels = {**HEALTH, 'done': '完成', 'reported': '已回報異常', 'failed': '未能執行',
                  'yes': '已確認', 'no': '未確認'}
        for report in reports:
            lines.append(f'{report["reported_at"][:10]} 照護回報：{labels.get(report["result"], "其他")}。')
            sources.append(f'任務 {report["task_id"]} · {report["reported_at"][:10]}')
            safe_facts.append({'care_result': report['result'] if report['result'] in labels else 'other'})
        if not reports:
            lines.append('目前沒有可查看的照護回報。')
            safe_facts.append({'care_reports': 0})
        return lines, sources, safe_facts

    def task_answer(tasks, title, workers, count_only=False):
        lines = [f'{title}共 {len(tasks)} 項。']
        sources = []
        for task in tasks[:12]:
            label = task['label']
            animal = task['animal_name']
            start = task['start']
            when = (f"{task['day']} {start//4:02d}:{start%4*15:02d}"
                    if task['day'] and start is not None else f"待指派，期限 {task['due'] or '未設定'}")
            assignee = workers.get(task['staff_id'])
            detail = f'，{assignee["name"]}' if assignee else ''
            lines.append(f'{when} · {animal} · {label}{detail}。')
            sources.append(f'任務 {task["task_id"]}')
        if not count_only and len(tasks) > 12:
            lines.append('顯示前 12 項，完整清單請查看排程。')
        return (lines[:1] if count_only else lines), sources

    def schedule_answer(db, question, sid):
        current = today()
        selected = current
        date_text = re.search(r'\b\d{4}-\d{2}-\d{2}\b', question)
        if date_text:
            try:
                selected = date.fromisoformat(date_text[0])
            except ValueError:
                return ['請輸入有效日期（YYYY-MM-DD）。'], []
        elif '下週' in question:
            selected += timedelta(days=7)
        elif '上週' in question:
            selected -= timedelta(days=7)
        days = week_days(selected)
        day = selected.isoformat()
        workers, shifts = shifts_for(db, days)
        if sid is not None:
            workers = {key: item for key, item in workers.items() if key == sid}
        tasks = [t for t in tasks_for(db, days) if sid is None or t['staff_id'] == sid]
        active = [t for t in tasks if t['state'] in ACTIVE and t['is_active']]
        daily = [t for t in active if t['day'] == day or (not t['day'] and t['earliest'] <= day)]
        by_time = lambda t: (t['day'] or '9999', t['start'] if t['start'] is not None else 96, t['priority'])
        active.sort(key=by_time)
        daily.sort(key=by_time)
        if sid is None and any(word in question for word in ('容納', '容量', '收容多少', '收容幾', '多少隻', '幾隻')):
            count = db.execute('SELECT COUNT(*) FROM animals WHERE is_active=1').fetchone()[0]
            profile = db.execute('SELECT capacity FROM profiles WHERE id=1').fetchone()
            detail = f'設定容量 {profile[0]} 隻，剩餘 {max(0, profile[0]-count)} 隻。' if profile else '目前沒有容量設定。'
            return [f'目前在養 {count} 隻。{detail}'], ['在養動物名單', '收容所設定 #1']
        if '工時' in question:
            lines, sources = [], []
            for key, worker in workers.items():
                own = [t for t in tasks if t['staff_id'] == key and t['state'] != 'cancelled']
                daily_used = sum(t['quarters'] for t in own if t['day'] == day)
                today_left = max(0, daily_limit(shifts[key, day]) - daily_used)
                lines.append(f'{worker["name"]} · {day} 已排 {daily_used/4:g} 小時，剩餘 {today_left/4:g} 小時。')
                sources.append(f'員工班表 #{key} · {days[0]}–{days[-1]}')
            return lines or ['目前沒有員工班表。'], sources
        if sid is None and '請假' in question:
            matches = [w for w in workers.values() if w['name'] in question]
            affected = [t for t in active if t['staff_id'] in {w['id'] for w in matches or workers.values()} and t['day'] >= current.isoformat()]
            if not matches:
                return ['請提供查詢的員工姓名，例如「王小明請假會影響哪些任務？」。'], []
            if date_text:
                affected = [t for t in affected if t['day'] == day]
            return task_answer(affected, '該員工目前排定、請假時需核對的任務', workers)
        if '為什麼' in question or '原因' in question:
            named = next((t for t in active if len(t['task_id']) > 4 and t['task_id'] in question), None)
            if named is None:
                names = {t['animal_name'] for t in tasks if t['animal_name'] and t['animal_name'] in question}
                labels = {t['label'] for t in tasks if t['label'] and t['label'] in question}
                candidates = active if ('週' in question or names or labels) and not date_text else daily
                matches = [t for t in candidates if (not names or t['animal_name'] in names)
                           and (not labels or t['label'] in labels)]
                if len(matches) == 1:
                    named = matches[0]
                elif matches:
                    lines = [f"找到 {len(matches)} 項符合的任務，以下為已記錄的排程原因："]
                    sources = []
                    for task in matches[:12]:
                        reason = task['reason'] or ('目前已指派，沒有其他已記錄原因。' if task['staff_id'] else '目前沒有已記錄的未指派原因。')
                        lines.append(f"{task['day'] or '待指派'} · {task['animal_name']} · {task['label']}：{reason}")
                        sources.append(f"任務 {task['task_id']}")
                    if len(matches) > 12:
                        lines.append('僅顯示前 12 項，可加入動物名稱或任務名稱縮小範圍。')
                    return lines, sources
                else:
                    return ['找不到符合的可查看任務，請提供動物名稱、任務名稱或日期。'], []
            applied = db.execute('SELECT body FROM weekly_applied WHERE week=?', (days[0],)).fetchone()
            proposal = json.loads(applied['body']) if applied else None
            recorded = proposal and next((change for change in proposal['changes']
                if change['task_id'] == named['task_id'] and change['reason'] == named['reason']), None)
            detail = f'此原因來自已套用的 CP-SAT {proposal["status"]} 方案。' if recorded else ''
            reason = named['reason'] or ('目前已指派。' if named['staff_id'] else '目前沒有已記錄的未指派原因。')
            return [reason, *([detail] if detail else [])], [f'任務 {named["task_id"]}', *([f'CP-SAT {proposal["status"]}'] if recorded else [])]
        if any(word in question for word in ('調整紀錄', '派工變動', '重新最佳化結果')):
            applied = db.execute('SELECT * FROM weekly_applied WHERE week=?', (days[0],)).fetchone()
            if not applied:
                return ['目前沒有此週已套用的最佳化紀錄。'], []
            allowed = {task['task_id'] for task in tasks}
            ids = {change['task_id'] for change in json.loads(applied['body'])['changes']
                   if change['task_id'] in allowed}
            lines, sources = task_answer([t for t in tasks if t['task_id'] in ids], '上次方案中可查看的變動任務', workers)
            return [f"套用時間 {applied['applied_at']}，CP-SAT {applied['solver_status']}。", *lines], sources
        if '異常' in question and not any(word in question for word in ('緊急','任務')):
            matched = db.execute("""SELECT i.task_id,i.animal_id,r.reported_at FROM weekly_issues i
                JOIN weekly_tasks t ON t.task_id=i.task_id JOIN weekly_reports r ON r.task_id=i.task_id
                WHERE i.resolved_at IS NULL AND (? IS NULL OR t.staff_id=?)
                ORDER BY r.reported_at DESC,i.task_id LIMIT 13""", (sid,sid)).fetchall()
            lines = [f"動物 #{item['animal_id']} · {item['reported_at'][:10]} · 待處理異常"
                     for item in matched[:12]]
            return lines or ['目前沒有可查看的待處理異常。'], [f"任務 {item['task_id']}" for item in matched[:12]]
        if any(word in question for word in ('尚未安排', '待指派', '未指派')):
            return task_answer([t for t in active if not t['staff_id']], '本週待指派任務', workers)
        if '下一' in question:
            now = datetime.now(TAIPEI)
            tick = now.hour*4 + now.minute//15
            next_tasks = [t for t in daily if t['day'] == day and t['start'] is not None
                          and (day != current.isoformat() or t['start']+t['quarters'] > tick)]
            return task_answer(next_tasks[:1], '下一項排定任務', workers)
        if any(word in question for word in ('緊急', '優先', '注意', '異常')):
            return task_answer([t for t in (active if '週' in question else daily)
                                if t['priority'] <= 1 or t['health_status'] in ('sick','injured','serious')],
                               '需優先留意的照護任務', workers)
        if any(word in question for word in ('任務', '班表', '排程', '工作', '未完成')):
            return task_answer(active if '週' in question else daily, '待完成任務', workers,
                               any(word in question for word in ('幾項', '多少項', '幾個')))
        return None

    @router.get('/llm/usage')
    def usage(request: Request):
        if request.state.user_id != 1:
            raise HTTPException(403, '僅管理者可查看 AI 使用量')
        with legacy.connect() as db:
            return llm.usage(db)

    @router.post('/chat')
    def ask(body: Question, request: Request):
        question = body.question.strip()
        if not question:
            raise HTTPException(422, '請輸入問題')
        model_data = None
        token = None
        with legacy.connect() as db:
            db.execute('PRAGMA query_only=ON')
            sid = staff_identity(db, request)
            aid = context_id(request, body.context)
            animal = animal_scope(db, sid, question, aid)
            if any(word in question for word in ('劑量', '診斷', '開藥', '用藥', '給藥')):
                result = (['我可以查詢照護及醫療紀錄。診斷與用藥請由獸醫確認。'], [])
            elif animal and not any(word in question for word in ('派工', '工時', '班表', '排程', '指派')) and not (any(word in question for word in ('為什麼', '原因')) and '任務' in question):
                token = sign(request, animal['id'])
                lines, sources, model_data = animal_details(db, animal, question, sid)
                result = lines, sources
                if not any(word in question for word in ('健康', '近況', '整理', '總結', '注意')):
                    model_data = None
            elif any(word in question for word in ('驅蟲', '疫苗', '這隻', '牠', '該動物')):
                result = (['目前沒有可查看的動物紀錄。請提供已授權的動物名稱或編號。'], [])
            else:
                result = schedule_answer(db, question, sid)
                token = body.context if aid is not None else None
        source, error = 'db', None
        if result is None:
            result = (['目前無法查詢這個問題。可詢問已授權的動物紀錄或派工資料。'], [])
            source = 'rules'
        lines, sources = result
        if model_data:
            def validate(answer):
                order = answer['order']
                if not isinstance(order, list) or not order or any(
                    type(i) is not int or not 0 <= i < len(lines) for i in order
                ):
                    raise ValueError('Invalid synthesis')
                return list(dict.fromkeys([*order, *range(len(lines))]))

            indices, error = llm.generate(legacy.connect, 'chat',
                'Order these anonymized veterinary record facts by relevance for a health overview. '
                'Return zero-based indices. Prioritize unresolved issues and symptoms. Do not diagnose.',
                model_data, SCHEMA, validate)
            if indices is not None:
                lines = [lines[i] for i in indices]
                source = 'gemini'
        with legacy.connect() as db:
            llm.count_event(db, 'chat', 'interaction')
            if source != 'gemini':
                llm.count_event(db, 'chat', 'rule')
        return {'answer': '\n'.join(lines), 'source': source, 'sources': sources,
                'context': token, 'fallback_reason': error,
                'queried_at': datetime.now(TAIPEI).isoformat()}

    return router
