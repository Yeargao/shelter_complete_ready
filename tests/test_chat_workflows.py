"""User-journey acceptance suite against the actual authenticated FastAPI app.

Uses the same temporary seed DB, login accounts and HTTP API as test_agent_live_api.
No production writes or Gemini calls. Run against a prior checkout via AGENT_BACKEND_DIR.
"""
import unittest
from datetime import date,timedelta
from uuid import uuid4
import test_agent_live_api as fixture

class WorkflowDialogueTests(fixture.DialogueTests):
    def guidance(self,q,headers=None,words=()):
        t=self.send(q,headers)
        self.assertIn('answer',t,t)
        for word in words:self.assertIn(word,t['answer']['answer'],t)
        self.assertTrue(t.get('links'),t)
        return t
    def test_manager_sick_general(self):
        t=self.guidance('某動物生病了之後要怎麼做？',words=('獸醫','資源配置','優先確認健康狀況','派工'))
        self.assertIn('/resources',{x['path'] for x in t['links']})
    def test_staff_sick_general(self):
        t=self.guidance('某動物生病了之後要怎麼做？',self.staff,('獸醫','個人工作台','回報','主管'))
        self.assertNotIn('/resources',{x['path'] for x in t['links']})
    def test_manager_sick_specific_and_task_draft(self):
        name=self.names[0]
        t=self.guidance(name+' 生病了該怎麼做？',words=(name,'健康狀態待確認','優先確認健康狀況'))
        s=next(x for x in t['suggestions'] if '健康修改草案' in x['label'] and '生病' in x['label'])
        c=self.send(s['question'])['command'];self.assertEqual(c['animal_id'],self.ids[0]);self.assertEqual(c['type'],'animal_action')
        with self.main.connect() as db:self.assertEqual(db.execute('SELECT health_status FROM animals WHERE id=?',(self.ids[0],)).fetchone()[0],'unknown')
        self.confirm(c)
        self.assertIn('生病',self.send(name+' 資料')['answer']['answer'])
        t=self.guidance('牠生病了下一步怎麼做？',words=(name,'資源配置'))
        suggestion=next((x for x in t['suggestions'] if '建立今日優先' in x['label']),None)
        if suggestion:
            r=self.send(suggestion['question']);self.assertEqual(r['command']['type'],'task');self.assertEqual(r['command']['animal_id'],self.ids[0])
    def test_staff_sick_note_and_followup(self):
        t=self.guidance(self.names[0]+' 生病了',self.staff,('個人工作台',self.names[0]))
        r=self.send(next(s['question'] for s in t['suggestions'] if '回報生病' in s['label']),self.staff)
        self.assertIn('備註',r['command']['message'])
        with self.main.connect() as db:self.assertIsNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(self.tids[0],)).fetchone())
        cmd=self.send('備註：早上精神不佳，已通知主管',self.staff)['command'];self.assertEqual(cmd['type'],'staff_report');self.assertEqual(cmd['task_id'],self.tids[0])
        self.request('POST','/api/schedule/tasks/'+cmd['task_id']+'/report',{'result':cmd['result'],'note':cmd['note'],'expected_day':cmd['day']},self.staff)
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT health_status FROM animals WHERE id=?',(self.ids[0],)).fetchone()[0],'sick')
            self.assertIsNotNone(db.execute('SELECT 1 FROM weekly_issues WHERE task_id=?',(self.tids[0],)).fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM weekly_tasks WHERE animal_id=? AND label='優先確認健康狀況' AND state='pending'",(self.ids[0],)).fetchone())
        self.assertIn('早上精神不佳',self.send(self.names[0]+' 最近照護回報',self.staff)['answer']['answer'])
    def test_staff_unassigned_sick_no_leak(self):
        r=self.send(self.names[1]+' 受傷了怎麼辦？',self.staff)
        self.assertIn('主管',r['command']['message']);self.assertNotIn('suggestions',r)
        self.assertNotIn(self.names[1],r['command']['message'])
    def test_staff_cancel_note(self):
        self.send('回報 '+self.tids[0]+' 結果：生病',self.staff)
        r=self.send('取消',self.staff);self.assertIn('已取消',r['command']['message'])
        r=self.send('備註：觀察',self.staff);self.assertNotEqual(r.get('command',{}).get('type'),'staff_report')
        with self.main.connect() as db:self.assertIsNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(self.tids[0],)).fetchone())
    def test_staff_short_report_after_profile(self):
        self.send(self.names[0]+' 資料',self.staff)
        c=self.send('回報這隻動物 結果：健康',self.staff)['command']
        self.assertEqual(c['type'],'staff_report');self.assertEqual(c['task_id'],self.tids[0])
    def test_manager_leave_workflow(self):
        t=self.guidance('員工請假後如何調整排程？',words=('每日班表與員工設定','預覽','儲存班表'))
        self.assertEqual(t['links'][0]['path'],'/resources')
    def test_staff_leave_workflow(self):
        self.guidance('我明天不能上班要怎麼做？',self.staff,('管理者','個人工作台'))
    def test_manager_intake_readmit_exit(self):
        for q,path,word in [('如何新增動物？','/animals/new','待確認'),('重新入所要怎麼做？','/animals/new','原動物編號'),('送養後怎麼登記離所？','/animals','離所日期')]:
            r=self.guidance(q,words=(word,));self.assertIn(path,[x['path'] for x in r['links']])
    def test_staff_no_manager_navigation(self):
        t=self.guidance('如何新增動物？',self.staff,('管理者權限',))
        self.assertNotIn('/animals/new',[x['path'] for x in t['links']])
    def test_staff_withdraw_guidance(self):
        self.guidance('回報錯了如何收回回報？',self.staff,('收回回報','個人工作台','管理者'))
    def test_inverse_operation_journeys(self):
        for q,words in [
            ('如何取消指派？',('取消指派','釋放','不必')),
            ('不小心標成執行中，要怎麼恢復待辦？',('恢復待辦','實際')),
            ('如何取消已解決標記？',('取消已解決標記','健康登錄')),
            ('手機怎麼派工？',('底部','可用時段','儲存指派','休息')),
            ('如何取消最佳化派工預覽？',('取消','確認儲存','不會更動')),
            ('如何重新指派？',('重新檢查','儲存指派')),
            ('昨天的回報錯了，如何更正？',('代為收回完成回報','誤報更正','跨日','醫療')),
        ]:
            with self.subTest(q=q):
                t=self.guidance(q,words=words)
                self.assertNotIn('command',t)
                self.assertIn('/resources',{x['path'] for x in t['links']})
        for q in ('如何取消指派？','手機怎麼派工？','如何取消已解決標記？'):
            t=self.guidance(q,self.staff,('管理者權限',))
            self.assertNotIn('/resources',{x['path'] for x in t['links']})
    def test_inverse_report_uses_scoped_live_state_without_writing(self):
        tid=self.tids[0]
        self.request('POST','/api/schedule/tasks/'+tid+'/report',{'result':'sick','note':'觀察紀錄','expected_day':self.day},self.staff)
        q=self.names[0]+' 剛才的回報是誤報，如何收回回報？'
        t=self.guidance(q,self.staff,(self.names[0],'可收回','誤報更正'))
        self.assertNotIn('command',t)
        with self.main.connect() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(tid,)).fetchone())
            db.execute('UPDATE weekly_reports SET reported_at=? WHERE task_id=?',((date.fromisoformat(self.day)-timedelta(days=1)).isoformat()+'T12:00:00',tid))
        t=self.guidance(q,self.staff,('不可自行收回','跨日回報'))
        self.assertNotIn('command',t)
        t=self.guidance(q,words=('須管理者審核','跨日回報','誤報更正'))
        self.assertNotIn('command',t)
        with self.main.connect() as db:self.assertIsNotNone(db.execute('SELECT 1 FROM weekly_reports WHERE task_id=?',(tid,)).fetchone())
    def test_manager_resolve_guidance(self):
        self.guidance('健康異常要怎麼結案？',words=('標記已解決','資源配置','健康登錄'))
    def test_stock_fact_and_privacy(self):
        with self.main.connect() as db:stock=db.execute('SELECT food_stock_kg FROM profiles WHERE id=1').fetchone()[0]
        t=self.guidance('飼料庫存還剩多少？',words=(f'{stock:g} 公斤','每日估算需求'))
        self.assertEqual(t['answer']['source'],'db')
        r=self.guidance('飼料庫存還剩多少？',self.staff,('管理者權限',))
        self.assertNotIn('每日估算需求',r['answer']['answer'])
    def test_due_vaccine_scope(self):
        day=date.fromisoformat(self.day);due=(day+timedelta(days=3)).isoformat()
        with self.main.connect() as db:
            for aid in self.ids[:2]:
                db.execute("INSERT INTO vaccination_records(animal_id,vaccine_type,administered_date,next_due_date,source) VALUES (?,'general',?,?,'test')",(aid,(day-timedelta(days=360)).isoformat(),due))
        t=self.guidance('未來7天哪些動物疫苗到期？',words=(self.names[0],self.names[1],due))
        r=self.guidance('未來7天哪些動物疫苗到期？',self.staff,words=(self.names[0],due))
        self.assertNotIn(self.names[1],r['answer']['answer'])
        s=self.guidance(self.names[0]+' 疫苗到期日？',words=(self.names[0],due))
        self.assertNotIn(self.names[1],s['answer']['answer'])
    def test_animal_tasks_followup(self):
        self.send(self.names[0]+' 資料')
        t=self.guidance('牠有哪些未完成任務？',words=(self.names[0],'健康狀態待確認'))
        self.assertNotIn(self.names[1],t['answer']['answer'])
    def test_medical_advice_boundary(self):
        self.guidance('動物生病了該用什麼藥？',self.staff,('不能提供','獸醫'))
if __name__=='__main__':
    # Run only new user-journey cases, not inherited baseline methods.
    own=[name for name in WorkflowDialogueTests.__dict__ if name.startswith('test_')]
    suite=unittest.TestSuite(WorkflowDialogueTests(name) for name in own)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
