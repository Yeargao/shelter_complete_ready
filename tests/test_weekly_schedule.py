
"""HTTP regression tests with real CP-SAT and a separate temporary SQLite per test."""
import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
MONDAY = '2026-11-23'
TUESDAY = '2026-11-24'
WEEK = '/api/schedule/week?week=' + MONDAY
PREVIEW = '/api/schedule/preview?week=' + MONDAY


class Monday(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 23, 8, tzinfo=tz)


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        database = directory / 'weekly.sqlite3'
        self.enterContext(patch.dict('os.environ', {
            'SHELTER_DB_PATH': str(database), 'SHELTER_UPLOAD_DIR': str(directory/'uploads'),
            'GEMINI_API_KEY': '', 'LLM_ENABLED': '1', 'SHELTER_PHOTO_BUCKET': '',
            'SHELTER_REQUIRE_OBJECT_STORAGE': '0', 'VERCEL': '',
        }))
        self.enterContext(patch.object(sys, 'path', [str(BACKEND), *sys.path]))
        import main
        import weekly_schedule
        self.enterContext(patch.object(main, 'DB', database))
        self.enterContext(patch.object(weekly_schedule, 'datetime', Monday))
        main.init()
        with main.connect() as db:
            for table in ('assignment_snapshot','animals','staff','task_overrides','generated_tasks',
                          'vaccination_records','deworming_events','task_metadata'):
                db.execute(f'DELETE FROM {table}')
            db.execute("""INSERT INTO animals(id,name,species,health_status,vaccinated,dewormed,sterilized,
                intake_date,routine_care_hours_per_day) VALUES
                (1,'Test','dog','healthy','yes','no','yes','2026-11-01',0.25)""")
            db.executemany("""INSERT INTO staff(id,profile_id,name,skills,available_hours,weekly_hours,
                shift_start,shift_end,break_start,break_end) VALUES (?,1,?,?,?,?,'09:00','11:00','09:30','10:00')""",
                [(1,'observer','["health:observation","admin:records"]',1.25,3),
                 (2,'vet','["health:veterinary"]',1,2)])
        self.main = main
        self.client = self.enterContext(TestClient(main.app))
        self.manager, self.staff, self.other = (self.login(x) for x in ('01','02','03'))

    def login(self, password):
        token = self.client.post('/api/auth/login',json={'password':password}).json()['token']
        return {'Authorization':'Bearer '+token}

    def request(self, method, url, payload=None, headers=None, expected=200):
        response = self.client.request(method,url,json=payload,headers=self.manager if headers is None else headers)
        self.assertEqual(response.status_code,expected,response.text if 'image/' not in response.headers.get('content-type','') else '')
        return response

    def week(self, headers=None):
        return self.request('GET',WEEK,headers=headers).json()

    def place(self, tid, staff, day=MONDAY, start='09:00', locked=True, expected=200):
        return self.request('PATCH',f'/api/schedule/tasks/{tid}/placement',
                            {'staff_id':staff,'day':day,'start_time':start,'locked':locked},expected=expected)

    def add(self,label,priority=0,animal=1):
        data={'label':label,'animal_id':animal,'earliest':MONDAY,'due':MONDAY,'priority':priority}
        return self.request('POST','/api/schedule/tasks',data).json()['task_id']

    def shift(self, staff=1, day=MONDAY, attending=False, hours=1.25):
        self.request('PUT',f'/api/schedule/shifts/{staff}/{day}',{
            'attending':attending,'shift_start':'09:00','shift_end':'11:00','break_start':'09:30',
            'break_end':'10:00','available_hours':hours,'scheduled_hours':0,
        })

    def test_generation_independent_completion_and_migration(self):
        first = self.week()
        self.assertEqual(len(first['days']),7)
        self.assertFalse(any(t['label']=='基礎照護' for t in first['tasks']))
        self.assertEqual(first['tasks'],self.week()['tasks'])
        deworm = [t for t in first['tasks'] if t['label']=='基礎驅蟲']
        self.assertEqual(len(deworm),1)
        task = deworm[0]
        self.place(task['task_id'],1,start='10:00')
        self.request('POST',f"/api/schedule/tasks/{task['task_id']}/report",{'result':'done'},self.staff)
        actual = {t['task_id']:t for t in self.week()['tasks']}
        self.assertEqual(actual[task['task_id']]['state'],'done')
        self.assertTrue(any(t['state']=='pending' for t in actual.values()))
        self.shift()
        plan = self.request('POST',PREVIEW).json()
        self.assertNotIn(task['task_id'],{c['task_id'] for c in plan['changes']})
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM weekly_reports').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM animals').fetchone()[0],1)

    def test_assignable_hours_respect_daily_limit_only(self):
        task = self.add('確認驅蟲紀錄')
        self.place(task, 1, day=TUESDAY)
        with self.main.connect() as db:
            db.execute('UPDATE staff SET weekly_hours=.5 WHERE id=1')
        def available(day, headers=None):
            return next(s['assignable_hours'] for s in self.week(headers)['shifts']
                        if s['id']==1 and s['day']==day)
        self.assertEqual(available(MONDAY), 1.25)
        self.assertEqual(available(TUESDAY, self.staff), 1)
        self.shift(day=MONDAY)
        self.assertEqual(available(MONDAY), 0)

    def test_fixed_lunch_blocks_assignments_crossing_it(self):
        self.request('PUT',f'/api/schedule/shifts/1/{MONDAY}',{
            'attending':True,'shift_start':'09:00','shift_end':'17:00',
            'available_hours':8,'scheduled_hours':0,
        })
        shift = next(s for s in self.week()['shifts'] if s['id']==1 and s['day']==MONDAY)
        self.assertEqual(shift['daily_capacity_hours'],6)
        self.assertIn(['11:30','13:30'],shift['break_windows'])
        task = self.add('基礎驅蟲')
        for start in ('11:15','11:30','13:15'):
            self.place(task,1,start=start,expected=422)
        self.place(task,1,start='13:30')

    def test_rolling_preview_crosses_sunday_to_complete_seven_days(self):
        with self.main.connect() as db:
            db.execute("UPDATE animals SET dewormed='yes' WHERE id=1")
            db.execute("""INSERT INTO vaccination_records (animal_id,administered_date,next_due_date)
                VALUES (1,'2026-11-01','2027-11-01')""")
        query = '?week='+TUESDAY+'&rolling=true'
        self.request('GET','/api/schedule/week'+query)
        with self.main.connect() as db:
            db.executemany("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due)
                VALUES (?,1,'確認驅蟲紀錄','admin:records',3,1,?,'2026-11-30')""",
                [(f'rolling-{i}',TUESDAY) for i in range(7)])
        plan = self.request('POST','/api/schedule/preview'+query).json()
        self.request('POST','/api/schedule/apply/'+plan['plan_id'])
        calendar = self.request('GET','/api/schedule/week'+query).json()
        self.assertEqual(calendar['days'][0],TUESDAY)
        self.assertEqual(calendar['days'][-1],'2026-11-30')
        self.assertEqual(sorted(t['day'] for t in calendar['tasks'] if t['task_id'].startswith('rolling-')),calendar['days'])

    def test_injury_report_accepts_optional_note(self):
        task = self.add('健康狀態待確認')
        self.place(task,1,start='10:00')
        self.request('POST',f'/api/schedule/tasks/{task}/report',{'result':'injured'},self.staff)
        reported = next(t for t in self.week(self.staff)['tasks'] if t['task_id']==task)
        self.assertEqual(reported['report']['note'],'')

    def test_existing_locked_lunch_task_returns_to_pool(self):
        task = self.add('基礎驅蟲')
        with self.main.connect() as db:
            db.execute('UPDATE weekly_tasks SET day=?,staff_id=1,start=45,locked=1 WHERE task_id=?',
                       (MONDAY,task))
        restored = next(t for t in self.week()['tasks'] if t['task_id']==task)
        self.assertIsNone(restored['staff_id'])
        self.assertFalse(restored['locked'])
        self.assertIn('午休',restored['reason'])

    def test_optimizer_fills_more_minutes_when_tasks_compete(self):
        self.shift(staff=2,attending=True,hours=1)
        for day in self.week()['days'][1:]:
            self.shift(staff=2,day=day)
        longer = self.add('健康問題追蹤',priority=3)
        shorter = self.add('疫苗施打',priority=0)
        plan = self.request('POST',PREVIEW).json()
        self.request('POST','/api/schedule/apply/'+plan['plan_id'])
        results = {t['task_id']:t for t in self.week()['tasks']}
        self.assertEqual(results[longer]['staff_id'],2)
        self.assertIsNone(results[shorter]['staff_id'])

    def test_health_followups_and_derived_colours(self):
        check = self.add('健康狀態待確認')
        self.place(check,1,start='10:00')
        self.request('POST',f'/api/schedule/tasks/{check}/report',{'result':'injured','note':'Observation'},self.staff)
        treatment = next(t for t in self.week()['tasks'] if t['task_id']==f'followup:{check}')
        self.assertEqual(treatment['label'],'優先確認健康狀況')
        self.assertEqual(treatment['display_priority'],0)
        self.place(treatment['task_id'],2,start='10:00')
        self.request('POST',f"/api/schedule/tasks/{treatment['task_id']}/report",
                     {'result':'injured','note':'Continued observation'},self.other)
        self.assertTrue(any(t['label']=='健康問題追蹤' and t['display_priority']==0 for t in self.week()['tasks']))

    def test_overdue_health_followup_returns_to_pool_once(self):
        self.week()
        with self.main.connect() as db:
            db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,day,staff_id,start)
                VALUES ('followup:past',1,'健康問題追蹤','health:veterinary',0,4,'2026-11-22','2026-11-22',2,40)""")
        for week in (self.week(),self.week()):
            carried = [t for t in week['tasks'] if t['label']=='健康問題追蹤']
            self.assertEqual([t['task_id'] for t in carried],['carry:followup:past'])
            self.assertTrue(carried[0]['is_derived'])
            self.assertIsNone(carried[0]['staff_id'])
        self.request('POST','/api/schedule/tasks/followup:past/report',
                     {'result':'reported','note':'Observation'},self.other,409)

    def test_staff_can_withdraw_own_report_and_reopen_task(self):
        task = self.add('確認驅蟲紀錄')
        self.place(task, 1)
        self.assertTrue(next(t for t in self.week()['tasks'] if t['task_id']==task)['is_new'])
        path = f'/api/schedule/tasks/{task}'
        self.request('POST', path+'/report', {'result':'yes'}, self.staff)

        self.request('POST', path+'/withdraw-report', headers=self.other, expected=404)
        self.request('POST', path+'/withdraw-report/', headers=self.staff)
        reopened = next(t for t in self.week(self.staff)['tasks'] if t['task_id']==task)
        self.assertEqual(reopened['state'], 'pending')
        self.assertIsNone(reopened['report'])
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM weekly_report_withdrawals WHERE task_id=?', (task,)).fetchone()[0], 1)
        self.request('POST', path+'/report', {'result':'yes'}, self.staff)

    def test_manual_placement_accepts_date_before_task_earliest(self):
        task = self.request('POST','/api/schedule/tasks',{'label':'確認驅蟲紀錄','animal_id':1,
            'earliest':TUESDAY,'due':TUESDAY,'priority':3}).json()['task_id']
        self.place(task,1,day=MONDAY)
        self.request('POST',f'/api/schedule/tasks/{task}/report',{'result':'no'},self.staff)

    def test_manual_skill_break_overlap_cross_day_and_budgets(self):
        tid = self.add('健康問題追蹤')
        self.place(tid,1,expected=422)
        self.place(tid,2,start='09:15',expected=422)
        self.place(tid,2,start='10:00')
        other = self.add('優先確認健康狀況')
        self.place(other,2,start='10:00',expected=409)
        self.place(other,2,day=TUESDAY,start='10:00')
        with self.main.connect() as db:
            db.execute('UPDATE staff SET weekly_hours=1 WHERE id=2')
        self.place(other,2,day=TUESDAY,start='10:00')
        self.shift(attending=True,hours=.25)
        a = self.add('確認驅蟲紀錄')
        self.place(a,1)
        b = self.add('確認疫苗紀錄')
        self.place(b,1,start='09:15',expected=409)

    def test_leave_locked_infeasibility_and_stale_preview(self):
        task = self.add('確認驅蟲紀錄')
        self.place(task,1,locked=False)
        plan = self.request('POST',PREVIEW).json()
        self.shift()
        self.request('POST','/api/schedule/apply/'+plan['plan_id'],expected=409)
        revised = self.request('POST',PREVIEW).json()
        changed = next(x for x in revised['changes'] if x['task_id']==task)
        self.assertEqual(changed['before'][0],1)
        self.assertNotEqual(changed['after'][1],MONDAY)
        self.request('POST','/api/schedule/apply/'+revised['plan_id'])
        self.shift(attending=True)
        self.place(task,1)
        normal = self.request('POST',PREVIEW).json()
        self.assertNotIn(task,{c['task_id'] for c in normal['changes']})
        self.shift()
        self.request('POST',PREVIEW,expected=409)

    def test_intake_exit_emergency_and_priority(self):
        emergency = self.add('健康問題追蹤')
        with self.main.connect() as db:
            db.execute("""INSERT INTO animals(id,name,species,health_status,intake_date,routine_care_hours_per_day)
                          VALUES (2,'New','cat','healthy',?,.25)""",(TUESDAY,))
        new_task = next(t for t in self.week()['tasks'] if t['animal_id']==2)
        with self.main.connect() as db:
            db.execute('UPDATE animals SET is_active=0 WHERE id=2')
        self.place(new_task['task_id'],1,TUESDAY,expected=422)
        plan = self.request('POST',PREVIEW).json()
        move = next(c for c in plan['changes'] if c['task_id']==emergency)
        self.assertEqual(move['after'],[2,MONDAY,40])
        self.assertTrue(all(c['after'][0] is None for c in plan['changes'] if c['animal_name']=='New'))
        self.request('POST','/api/schedule/apply/'+plan['plan_id'])

    def test_quick_report_photo_permissions_summary_and_sync(self):
        self.request('GET','/api/tasks',headers=self.staff,expected=403)
        self.request('GET','/api/staff/assignments',headers=self.staff,expected=403)
        tid = self.add('基礎驅蟲')
        self.place(tid,1,start='10:00')
        self.assertIn(tid,{t['task_id'] for t in self.week(self.staff)['tasks']})
        self.assertNotIn(tid,{t['task_id'] for t in self.week(self.other)['tasks']})
        url = f'/api/schedule/tasks/{tid}/report'
        self.request('POST',url,{'result':'done'},self.other,403)
        self.request('POST',url,{'result':'done'},self.staff)
        self.request('POST',url,{'result':'done'},self.staff)
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deworming_events').fetchone()[0],1)
        issue = self.add('健康問題追蹤')
        self.place(issue,2,start='10:00')
        photo = BytesIO()
        Image.new('RGB',(4,4),'green').save(photo,format='PNG')
        endpoint = f'/api/schedule/tasks/{issue}/report'
        self.request('POST',endpoint,{'result':'reported','note':'Observation','photos':['bad']},self.other,422)
        self.request('POST',endpoint,{'result':'reported','note':'Observation',
                     'photos':[base64.b64encode(photo.getvalue()).decode()]},self.other)
        entry = next(t for t in self.week()['tasks'] if t['task_id']==issue)
        self.assertEqual(entry['state'],'done')
        self.assertIsNone(entry['issue']['resolved_at'])
        url = f"/api/schedule/tasks/{issue}/photos/{entry['photos'][0]}"
        self.request('GET',url,headers={},expected=401)
        self.request('GET',url,headers=self.staff,expected=404)
        self.assertEqual(self.request('GET',url,headers=self.other).headers['content-type'],'image/jpeg')
        self.request('GET',url)
        entry = next(t for t in self.week(self.other)['tasks'] if t['task_id']==issue)
        self.assertEqual(entry['summary']['mode'],'rule_based')
        self.assertIsNone(entry['summary']['fallback_reason'])
        self.assertTrue(entry['summary']['source_record_ids'])
        self.request('POST',f'/api/schedule/tasks/{issue}/resolve')
        self.assertIsNotNone(next(t for t in self.week()['tasks'] if t['task_id']==issue)['issue']['resolved_at'])


    def test_delayed_work_retains_before_position_and_started_work_is_fixed(self):
        tid = self.add('健康問題追蹤')
        self.place(tid,2,start='10:00',locked=False)
        self.request('POST',f'/api/schedule/tasks/{tid}/event',{'event':'delay','earliest':TUESDAY})
        self.request('POST',f'/api/schedule/tasks/{tid}/report',{'result':'reported','note':'Too early'},self.other,409)
        started = self.add('確認驅蟲紀錄')
        self.place(started,1,locked=False)
        self.request('POST',f'/api/schedule/tasks/{started}/event',{'event':'start'})
        plan = self.request('POST',PREVIEW).json()
        self.assertNotIn(started,{c['task_id'] for c in plan['changes']})
        change = next(c for c in plan['changes'] if c['task_id']==tid)
        self.assertEqual(change['before'],[2,MONDAY,40])
        self.assertEqual(change['after'][0],2)
        self.assertGreaterEqual(change['after'][1],TUESDAY)
        self.assertEqual(change['after'][2],40)
        self.request('POST','/api/schedule/apply/'+plan['plan_id'])

    def test_injury_event_and_urgent_task_precede_multiple_ordinary_tasks(self):
        initial = self.week()['event_id']
        with self.main.connect() as db:
            db.execute("UPDATE animals SET health_status='injured' WHERE id=1")
            db.execute("""INSERT INTO animals(id,name,species,health_status,vaccinated,dewormed,sterilized,
                intake_date) VALUES (2,'Another','dog','healthy','yes','yes','yes','2026-11-01')""")
        week = self.week()
        self.assertGreater(week['event_id'],initial)
        emergency = next(t for t in week['tasks'] if t['label']=='優先確認健康狀況')
        self.assertTrue(emergency['is_derived'])
        for day in week['days'][1:]:
            self.shift(staff=2,day=day)
        a = self.add('疫苗施打',priority=3)
        b = self.add('疫苗施打',priority=3,animal=2)
        plan = self.request('POST',PREVIEW).json()
        placements = {change['task_id']:change['after'] for change in plan['changes']}
        self.assertEqual(placements[emergency['task_id']],[2,MONDAY,40])
        self.assertIsNone(placements[a][0])
        self.assertIsNone(placements[b][0])
        redirect = self.client.post('/api/resources/optimize?week='+MONDAY,
                                    headers=self.manager,follow_redirects=False)
        self.assertEqual(redirect.status_code,307)
        self.assertEqual(redirect.headers['location'],PREVIEW)

    def test_single_plan_commits_assignments_for_all_seven_days(self):
        with self.main.connect() as db:
            db.execute("UPDATE staff SET weekly_hours=0 WHERE id=1")
            db.execute("UPDATE animals SET dewormed='yes' WHERE id=1")
            db.execute("""INSERT INTO vaccination_records (animal_id,administered_date,next_due_date)
                VALUES (1,'2026-11-01','2027-11-01')""")
        self.week()
        with self.main.connect() as db:
            db.executemany("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due)
                VALUES (?,1,'確認驅蟲紀錄','admin:records',3,1,?,'2026-11-29')""",
                [(f'balance-{i}',MONDAY) for i in range(7)])
        plan = self.request('POST',PREVIEW).json()
        self.assertIn(plan['solver_status'],('OPTIMAL','FEASIBLE'))
        self.request('POST','/api/schedule/apply/'+plan['plan_id'])
        week = self.week()
        scheduled = [t for t in week['tasks'] if t['task_id'].startswith('balance-') and t['staff_id']]
        self.assertEqual(sorted(t['day'] for t in scheduled),week['days'])
        self.assertEqual(week['schedule_status'],'applied')
        self.request('POST','/api/schedule/preview?week=2026-11-16',expected=409)

    def test_chat_live_queries_scopes_and_session_context(self):
        self.week()
        def ask(question, headers=None, context=None):
            return self.request('POST','/api/chat',{'question':question,'context':context},headers).json()
        self.assertEqual(ask('目前還能容納多少動物？')['source'],'db')
        self.assertIn('1 隻',ask('目前收容多少動物？')['answer'])
        self.assertIn('剩餘',ask('哪些員工還有剩餘工時？')['answer'])
        self.assertIn('共',ask('本週有哪些任務尚未安排？')['answer'])
        self.assertIn('共',ask('今天有哪些緊急任務？')['answer'])
        self.assertIn('observer',ask('observer 還有多少工時？')['answer'])
        self.assertIn('班表',ask('哪些員工還有剩餘工時？')['sources'][0])
        tid = self.add('確認驅蟲紀錄')
        self.place(tid,1)
        self.assertIn('Test',ask('我今天有哪些任務？',self.staff)['answer'])
        self.assertIn('Test',ask('本週我還有哪些工作未完成？',self.staff)['answer'])
        self.assertNotIn('Test',ask('我今天有哪些任務？',self.other)['answer'])
        self.assertIn('沒有可查看',ask('動物 #1 有驅蟲嗎？',self.other)['answer'])
        health = ask('Test 最近的健康狀況？',self.staff)
        self.assertEqual(health['source'],'db')
        self.assertEqual(health['fallback_reason'],'missing_key')
        self.assertIsNotNone(health['context'])
        self.assertIn('沒有具日期',ask('牠有驅蟲嗎？',self.staff,health['context'])['answer'])
        self.assertIn('沒有可查看',ask('牠有驅蟲嗎？',self.login('02'),health['context'])['answer'])
        with self.main.connect() as db:
            db.execute("INSERT INTO deworming_events(animal_id,intake_date,completed_date) VALUES (1,'2026-11-01','2026-11-23')")
            db.execute("INSERT INTO animals(name,species) VALUES ('Second','cat')")
        self.assertIn(MONDAY,ask('牠有驅蟲嗎？',self.staff,health['context'])['answer'])
        self.assertIn('2 隻',ask('目前收容多少動物？')['answer'])
        self.assertEqual(ask('DELETE FROM animals')['source'],'rules')
        self.request('POST','/api/chat',{'question':'動物 #1','sql':'DELETE FROM animals'},expected=422)
        self.request('GET','/api/llm/usage',headers=self.staff,expected=403)
        self.assertEqual(self.request('GET','/api/llm/usage').json()['used'],0)

    def test_chat_mocked_gemini_is_deidentified_and_degrades(self):
        import httpx
        import llm_service
        tid = self.add('確認驅蟲紀錄')
        self.place(tid,1)
        config = {'GEMINI_API_KEY':'fake-key','LLM_DATA_APPROVED':'1','LLM_MAX_REQUESTS_PER_DAY':'10',
                  'LLM_MAX_REQUESTS_PER_MINUTE':'10','LLM_MAX_INPUT_TOKENS_PER_MINUTE':'10000'}
        url = httpx.Request('POST','https://generativelanguage.googleapis.com')
        ok = httpx.Response(200,request=url,json={'candidates':[{'finishReason':'STOP',
            'content':{'parts':[{'text':'{"order":[1,0]}'}]}}]})
        mocked = Mock(side_effect=[ok,httpx.Response(503,request=url)])
        with patch.dict('os.environ',config), patch.object(llm_service,'http_client',side_effect=lambda:
            httpx.Client(transport=httpx.MockTransport(mocked), follow_redirects=False)):
            def ask():
                return self.request('POST','/api/chat',{'question':'Test 健康狀況？'},self.staff).json()
            first = ask()
            self.assertEqual(first['source'],'gemini')
            sent = mocked.call_args.args[0].content.decode()
            self.assertNotIn('Test',sent)
            self.assertNotIn('observer',sent)
            second = ask()
            self.assertEqual(second['source'],'db')
            self.assertEqual(second['fallback_reason'],'upstream_error')
            self.assertEqual(ask()['source'],'db')
            self.assertEqual(mocked.call_count,2)
