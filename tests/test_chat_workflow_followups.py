"""Second round: context, factual scopes and unsupported writes."""
import unittest
from datetime import date,timedelta
from uuid import uuid4
import test_agent_live_api as fixture

class FollowupDialogueTests(fixture.DialogueTests):
    def answer(self,q,headers=None):
        r=self.send(q,headers)
        self.assertIn('answer',r,r)
        return r['answer']['answer']
    def test_staff_health_guide_then_vaccine(self):
        self.send(self.names[0]+' 生病了',self.staff)
        self.assertIn(self.names[0],self.answer('疫苗日期？',self.staff))
    def test_manager_health_guide_next_step(self):
        self.send(self.names[0]+' 資料')
        self.send(self.names[1]+' 受傷了該怎麼做？')
        t=self.send('牠下一步呢？')
        self.assertIn(self.names[1],t['answer']['answer']);self.assertIn('資源配置',t['answer']['answer'])
        self.assertNotIn(self.names[0],t['answer']['answer'])
    def test_unauthorized_target_clears_context(self):
        self.send(self.names[0]+' 資料',self.staff)
        denied=self.send(self.names[1]+' 受傷了怎麼辦？',self.staff)
        self.assertIn('主管',denied['command']['message'])
        r=self.send('疫苗日期？',self.staff)
        self.assertNotIn(self.names[0],str(r.get('answer',{})))
        self.assertNotIn(self.names[1],str(r.get('answer',{})))
    def test_exact_due_after_thirty_days(self):
        day=date.fromisoformat(self.day);due=(day+timedelta(days=180)).isoformat()
        with self.main.connect() as db:
            db.execute("INSERT INTO vaccination_records(animal_id,vaccine_type,administered_date,next_due_date,source) VALUES (?,'general',?,?,'test')",(self.ids[0],(day-timedelta(days=185)).isoformat(),due))
        self.assertIn(due,self.answer(self.names[0]+' 疫苗到期日？'))
    def test_upcoming_excludes_expired(self):
        day=date.fromisoformat(self.day)
        with self.main.connect() as db:
            for aid,days in zip(self.ids[:2],[3,-3]):
                db.execute("INSERT INTO vaccination_records(animal_id,vaccine_type,administered_date,next_due_date,source) VALUES (?,'general',?,?,'test')",(aid,(day-timedelta(days=365-days)).isoformat(),(day+timedelta(days=days)).isoformat()))
        r=self.answer('未來7天哪些動物疫苗到期？')
        self.assertIn(self.names[0],r);self.assertNotIn(self.names[1],r)
        r=self.answer('哪些動物疫苗已逾期？')
        self.assertIn(self.names[1],r);self.assertNotIn(self.names[0],r)
    def test_overdue_tasks_role_scope(self):
        yesterday=(date.fromisoformat(self.day)-timedelta(days=1)).isoformat()
        with self.main.connect() as db:
            db.executemany('UPDATE weekly_tasks SET due=? WHERE task_id=?',[(yesterday,self.tids[0]),(yesterday,self.tids[1])])
        r=self.answer('有哪些逾期任務？');self.assertIn(self.names[0],r);self.assertIn(self.names[1],r)
        r=self.answer('我有哪些逾期任務？',self.staff);self.assertIn(self.names[0],r);self.assertNotIn(self.names[1],r)
    def test_open_issue_notes_scope(self):
        with self.main.connect() as db:
            for aid,tid,note in zip(self.ids,self.tids,['測試自己的異常','測試他人的異常','已處理']):
                db.execute('INSERT INTO weekly_issues(task_id,animal_id,note) VALUES (?,?,?)',(tid,aid,note))
            db.execute("UPDATE weekly_issues SET resolved_at=? WHERE task_id=?",(self.day,self.tids[2]))
        r=self.answer('有哪些還沒結案的異常？');self.assertIn('測試自己的異常',r);self.assertIn('測試他人的異常',r);self.assertNotIn('已處理',r)
        r=self.answer('有哪些還沒結案的異常？',self.staff);self.assertIn('測試自己的異常',r);self.assertNotIn('測試他人的異常',r)
    def test_manual_assignment_guide(self):
        t=self.send('如何手動指派任務？')
        self.assertIn('儲存指派',t['answer']['answer'])
        self.assertIn('/resources',[l['path'] for l in t['links']])
    def test_direct_close_no_unauthorized_write(self):
        t=self.send('幫我標記已解決',self.staff)
        self.assertIn('管理者權限',t['answer']['answer'])
        t=self.send('幫我標記已解決');self.assertIn('聊天尚不直接結案',t['answer']['answer'])
    def test_missing_vaccine_date(self):
        with self.main.connect() as db:
            db.execute("UPDATE animals SET vaccinated='yes' WHERE id=?",(self.ids[0],))
        r=self.answer('哪些動物已接種但缺少日期？')
        self.assertIn(self.names[0],r);self.assertNotIn(self.names[1],r)
    def test_long_stay_scope(self):
        r=self.answer('哪些動物在所超過90天？')
        # Use count to avoid depending on the first 20 names of the seed database.
        self.assertIn('超過 90 天',r)
        r=self.answer('我可以查看哪些動物在所超過90天？',self.staff)
        self.assertIn('超過 90 天',r)
    def test_named_today_includes_done(self):
        with self.main.connect() as db:
            db.execute("UPDATE weekly_tasks SET state='done' WHERE task_id=?",(self.tids[0],))
        r=self.answer(self.names[0]+' 今天有哪些任務？')
        self.assertIn('已完成',r);self.assertIn(self.names[0],r)
if __name__=='__main__':
    own=[name for name in FollowupDialogueTests.__dict__ if name.startswith('test_')]
    suite=unittest.TestSuite(FollowupDialogueTests(name) for name in own)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
