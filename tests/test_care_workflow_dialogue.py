"""HTTP acceptance checks for the four care workflows, using a disposable SQLite fixture.
Real chatbot drafts and report API; scheduling assignments are deliberately fixture-controlled.
"""
import unittest
from datetime import date,timedelta
from uuid import uuid4
import test_agent_live_api as fixture

class CareDialogueTests(fixture.DialogueTests):
    def assign(self,label,parent=None):
        aid=self.ids[0]
        tid='followup:'+parent if parent else uuid4().hex
        with self.main.connect() as db:
            _,skill,hours,_=self.main.TASK_CATALOG[label]
            db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due,day,staff_id,start)
                VALUES (?,?,?,?,3,?,?,?,?,?,36)""",(tid,aid,label,skill,int(hours*4),self.day,self.day,self.day,self.sid))
        return tid

    def reset_care(self):
        aid=self.ids[0]
        with self.main.connect() as db:
            db.execute('DELETE FROM weekly_reports WHERE task_id IN (SELECT task_id FROM weekly_tasks WHERE animal_id=?)',(aid,))
            db.execute('DELETE FROM weekly_issues WHERE animal_id=?',(aid,))
            db.execute('DELETE FROM weekly_tasks WHERE animal_id=?',(aid,))
            db.execute('DELETE FROM vaccination_records WHERE animal_id=?',(aid,))
            db.execute('DELETE FROM deworming_events WHERE animal_id=?',(aid,))
            db.execute("UPDATE animals SET health_status='unknown',vaccinated='unknown',dewormed='unknown',sterilized='unknown' WHERE id=?",(aid,))

    def submit(self,tid,phrase,dose=False):
        q=f'回報 {tid} 結果：{phrase}'+(' 施打日期：'+self.day if dose else '')+' 備註：測試回報'
        turn=self.send(q,self.staff)
        self.assertEqual(turn['command']['type'],'staff_report',turn)
        cmd=turn['command']
        self.assertEqual(cmd['task_id'],tid)
        with self.main.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(tid,)).fetchone())
        payload={k:cmd[k] for k in ('result','note','administered_date')}
        payload['expected_day']=cmd['day']
        endpoint='/api/schedule/tasks/'+tid+'/report'
        self.request('POST',endpoint,payload,self.other,403)
        self.request('POST',endpoint,payload,self.staff)
        self.request('POST',endpoint,payload,self.staff) # repeat is idempotent
        return cmd

    def test_all_outcome_branches(self):
        from care_workflow_cases import CASES
        for label,phrase,code,target in CASES:
            with self.subTest(label=label,phrase=phrase):
                self.reset_care()
                tid=self.assign(label)
                cmd=self.submit(tid,phrase,dose=label=='更新疫苗紀錄')
                self.assertEqual(cmd['result'],code)
                with self.main.connect() as db:
                    self.assertEqual(db.execute('SELECT state FROM weekly_tasks WHERE task_id=?',(tid,)).fetchone()[0],'done')
                    following=db.execute('SELECT label,due FROM weekly_tasks WHERE task_id=?',('followup:'+tid,)).fetchall()
                    if label=='更新疫苗紀錄':
                        due=self.main.month_after(date.fromisoformat(self.day),12).isoformat()
                        self.assertEqual([tuple(x) for x in following],[('疫苗施打',due)])
                    else:
                        self.assertEqual([x['label'] for x in following],[target] if target else [])
                    if code in ('healthy','recovered'):
                        self.assertEqual(db.execute('SELECT health_status FROM animals WHERE id=?',(self.ids[0],)).fetchone()[0],'healthy')
                    if label in ('更新驅蟲狀態','更新驅蟲紀錄'):
                        self.assertEqual(db.execute('SELECT dewormed FROM animals WHERE id=?',(self.ids[0],)).fetchone()[0],'yes')
                    if label=='更新絕育狀態':
                        self.assertEqual(db.execute('SELECT sterilized FROM animals WHERE id=?',(self.ids[0],)).fetchone()[0],'yes')

    def test_surgery_update_postoperative_chain(self):
        self.reset_care()
        tid=self.assign('絕育手術')
        self.submit(tid,'成功')
        child='followup:'+tid
        with self.main.connect() as db:
            db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=40 WHERE task_id=?',(self.sid,self.day,child))
        self.submit(child,'已更新')
        postoperative='followup:'+child
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT label FROM weekly_tasks WHERE task_id=?',(postoperative,)).fetchone()[0],'術後健康追蹤')
            db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=44 WHERE task_id=?',(self.sid,self.day,postoperative))
        self.submit(postoperative,'出現異常')
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT label FROM weekly_tasks WHERE task_id=?',('followup:'+postoperative,)).fetchone()[0],'優先確認健康狀況')

    def test_first_time_roles_and_options(self):
        for who in (self.manager,self.staff):
            for group in ('健康照護','疫苗','驅蟲','絕育'):
                turn=self.send(group+'流程',who)
                self.assertIn('【'+group+'】',turn['answer']['answer'])
            turn=self.send('第一次使用',who)
            self.assertIn('健康照護',turn['answer']['answer'])
        turn=self.send('我的照護任務回報選項',self.staff)
        self.assertIn(self.names[0],turn['answer']['answer'])
        self.assertNotIn(self.names[1],turn['answer']['answer'])
        options=self.send('回報 '+self.tids[0],self.staff)
        self.assertEqual({s['label'] for s in options['suggestions']},{'健康','生病','受傷'})
        denied=self.send('回報 '+self.tids[0]+' 結果：健康',self.manager)
        self.assertIn('管理者不可',denied['command']['message'])

    def test_novice_scoped_followup(self):
        first=self.send('我第一次使用這個系統，該怎麼開始？',self.staff)
        self.assertIn('回報',first['answer']['answer'])
        self.assertIn('我的照護任務回報選項',[s['question'] for s in first['suggestions']])
        manager=self.send('第一次使用',self.manager)
        self.assertIn('待指派照護任務',[s['question'] for s in manager['suggestions']])
        self.reset_care()
        tid=self.assign('健康狀態待確認')
        aid=self.ids[0]
        scoped=f'我的照護任務回報選項 動物 #{aid}'
        options=self.send(scoped,self.staff)
        self.assertEqual([s['question'] for s in options['suggestions']],['回報 '+tid])
        cmd=self.submit(tid,'受傷')
        self.assertEqual(cmd['animal_id'],aid)
        child='followup:'+tid
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT label FROM weekly_tasks WHERE task_id=?',(child,)).fetchone()[0],'優先確認健康狀況')
        self.assertIn('尚未指派',self.send(scoped,self.staff)['answer']['answer'])
        manager=self.send(f'待指派照護任務 動物 #{aid}',self.manager)
        self.assertIn('傷病治療',manager['answer']['answer'])
        with self.main.connect() as db:
            db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=40 WHERE task_id=?',(self.sid,self.day,child))
        self.assertEqual([s['question'] for s in self.send(scoped,self.staff)['suggestions']],['回報 '+child])
        self.submit(child,'尚未康復')
        track='followup:'+child
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT label FROM weekly_tasks WHERE task_id=?',(track,)).fetchone()[0],'健康問題追蹤')
            db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=44 WHERE task_id=?',(self.sid,self.day,track))
        self.submit(track,'已康復')
        self.assertFalse(self.send(scoped,self.staff)['suggestions'])
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT health_status FROM animals WHERE id=?',(aid,)).fetchone()[0],'healthy')

    def test_continuous_vaccine_and_deworm_journeys(self):
        for start,first,second,third,expected in (
            ('確認疫苗紀錄','未施打','疫苗施打','更新疫苗紀錄','疫苗施打'),
            ('確認驅蟲紀錄','未驅蟲','基礎驅蟲','更新驅蟲紀錄',None),
        ):
            with self.subTest(start=start):
                self.reset_care()
                self.assertIn(start,self.send(('疫苗' if '疫苗' in start else '驅蟲')+'流程',self.staff)['answer']['answer'])
                task=self.assign(start)
                self.submit(task,first)
                for label,phrase in ((second,'成功'),(third,'已更新')):
                    child='followup:'+task
                    with self.main.connect() as db:
                        self.assertEqual(db.execute('SELECT label FROM weekly_tasks WHERE task_id=?',(child,)).fetchone()[0],label)
                        db.execute('UPDATE weekly_tasks SET staff_id=?,day=?,start=40 WHERE task_id=?',(self.sid,self.day,child))
                    self.submit(child,phrase)
                    task=child
                with self.main.connect() as db:
                    following=db.execute('SELECT label,due,earliest FROM weekly_tasks WHERE task_id=?',('followup:'+task,)).fetchone()
                    if expected:
                        due=self.main.month_after(date.fromisoformat(self.day),12).isoformat()
                        self.assertEqual(tuple(following),(expected,due,due))
                    else:self.assertIsNone(following)

    def test_vaccine_date_followup(self):
        self.reset_care()
        tid=self.assign('更新疫苗紀錄')
        first=self.send('回報 '+tid+' 結果：已更新',self.staff)
        self.assertIn('日期',first['command']['message'])
        cmd=self.send(self.day,self.staff)['command']
        self.assertEqual(cmd['administered_date'],self.day)
        self.request('POST','/api/schedule/tasks/'+tid+'/report',
            {k:cmd[k] for k in ('result','note','administered_date')},self.staff)
        with self.main.connect() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM vaccination_records WHERE animal_id=?',(self.ids[0],)).fetchone())

    def test_novice_exact_buttons_and_followup(self):
        from care_workflow import RULES, display_label
        from chat_workflows import DIRECT_REPORT_TASKS
        for label, outcomes in RULES.items():
            for who in (self.staff,self.manager):
                with self.subTest(label=label,role='staff' if who==self.staff else 'manager'):
                    turn=self.send(display_label(label)+'要按哪個按鈕？',who)
                    answer=turn['answer']['answer']
                    self.assertIn('照護人員工作台',answer)
                    self.assertIn('任務右側' if label in DIRECT_REPORT_TASKS else '填寫回報',answer)
                    for _,title,_ in outcomes:self.assertIn(title,answer)
                    self.assertNotIn('command',turn)
                    if label in DIRECT_REPORT_TASKS:self.assertNotIn('送出回報',answer)
                    else:self.assertIn('送出回報',answer)
        self.send('疫苗施打怎麼操作？',self.staff)
        answer=self.send('那失敗之後下一步呢？',self.staff)['answer']['answer']
        self.assertIn('最早安排於隔日',answer)
        self.assertIn('建立問題回報',answer)
        self.assertIn('12個月',self.send('更新疫苗紀錄要填日期嗎？',self.staff)['answer']['answer'])
        self.assertIn('手術成功',self.send('更新絕育狀態之後會怎樣？',self.staff)['answer']['answer'])

    def test_novice_find_missing_and_assign(self):
        for q in ('我剛入職，不知道從哪裡開始','找不到後續任務怎麼辦？'):
            answer=self.send(q,self.staff)['answer']['answer']
            self.assertIn('照護人員工作台',answer)
        for q in ('後續任務還沒指派怎麼辦？','七天最佳化派工怎麼操作？'):
            answer=self.send(q,self.manager)['answer']['answer']
            for word in ('待指派任務池','衍生任務','儲存指派','確認儲存'):
                self.assertIn(word,answer)
        denied=self.send('七天最佳化派工怎麼操作？',self.staff)
        self.assertIn('管理者權限',denied['answer']['answer'])
        self.assertNotIn('/resources',[x['path'] for x in denied['links']])

    def test_novice_optional_note_and_direct_failure(self):
        self.reset_care()
        tid=self.assign('健康狀態待確認')
        first=self.send('回報 '+tid+' 結果：受傷',self.staff)
        self.assertIn('略過備註',first['command']['message'])
        cmd=self.send('略過備註',self.staff)['command']
        self.assertEqual((cmd['type'],cmd['task_id'],cmd['note']),('staff_report',tid,''))
        with self.main.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(tid,)).fetchone())
        for label,title in (('疫苗施打','失敗'),('基礎驅蟲','失敗'),('評估絕育安排','暫不適合絕育'),('絕育手術','未完成')):
            self.reset_care()
            tid=self.assign(label)
            cmd=self.send('回報 '+tid+' 結果：'+title,self.staff)['command']
            self.assertEqual((cmd['type'],cmd['task_id'],cmd['note']),('staff_report',tid,''))
            with self.main.connect() as db:
                self.assertIsNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(tid,)).fetchone())

    def test_readmission_deworm(self):
        self.reset_care()
        aid=self.ids[0]
        self.assertIn('基礎驅蟲',self.send('如何重新入所？',self.manager)['answer']['answer'])
        with self.main.connect() as db:
            db.execute("UPDATE animals SET is_active=0,exit_date=?,dewormed='yes' WHERE id=?",(self.day,aid))
        self.request('POST',f'/api/animals/{aid}/readmit',{'intake_date':self.day})
        with self.main.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM weekly_tasks WHERE animal_id=? AND label='基礎驅蟲' AND state='pending'",(aid,)).fetchone()[0],1)

if __name__=='__main__':
    suite=unittest.TestSuite(CareDialogueTests(n) for n in CareDialogueTests.__dict__ if n.startswith('test_'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
