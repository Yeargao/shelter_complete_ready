"""Real FastAPI HTTP dialogue tests with a disposable copy of the seed database."""
import os,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from fastapi.testclient import TestClient

BACKEND=Path(os.environ.get('AGENT_BACKEND_DIR',Path(__file__).resolve().parents[1]/'backend')).resolve()
sys.path.insert(0,str(BACKEND))
class DialogueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ.update(SHELTER_DB_PATH=str(Path(cls.temp.name)/'dialogue.sqlite3'),GEMINI_API_KEY='',LLM_ENABLED='0',SHELTER_AUTH_PASSWORDS='',SHELTER_PHOTO_BUCKET='',SHELTER_REQUIRE_OBJECT_STORAGE='0')
        import main
        cls.main=main
        cls.client=TestClient(main.app)
        cls.manager=cls.login('01');cls.staff=cls.login('02');cls.other=cls.login('03')
        cls.day=datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()
    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.temp.cleanup()
    @classmethod
    def login(cls,p):
        r=cls.client.post('/api/auth/login',json={'password':p})
        assert r.status_code==200,r.text
        return {'Authorization':'Bearer '+r.json()['token']}
    def setUp(self):
        self.session=uuid4().hex
        self.names=['Qatest'+uuid4().hex[:8] for _ in range(3)]
        with self.main.connect() as db:
            self.ids=[]
            for name in self.names:
                row=db.execute("""INSERT INTO animals(name,species,breed,age_months,sex,health_status,vaccinated,dewormed,sterilized,intake_date,is_active)
                    VALUES (?,'dog','Mixed',12,'female','unknown','unknown','unknown','unknown','2020-01-01',1)""",(name,))
                self.ids.append(row.lastrowid)
            staff=list(db.execute('SELECT id FROM staff WHERE profile_id=1 ORDER BY id LIMIT 2'))
            assert len(staff)==2,'fixture staff missing'
            db.execute('DELETE FROM weekly_staff_accounts')
            db.executemany('INSERT INTO weekly_staff_accounts VALUES (?,?)',[(2,staff[0][0]),(3,staff[1][0])])
            self.sid=staff[0][0];self.other_sid=staff[1][0]
            self.tids=[uuid4().hex for _ in range(3)]
            for idx,(task,aid,staff_id,state,label) in enumerate(zip(self.tids,self.ids,[self.sid,self.other_sid,self.sid],['pending','pending','done'],['健康狀態待確認','健康狀態待確認','基礎驅蟲'])):
                db.execute("""INSERT INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due,day,staff_id,start,state)
                  VALUES (?,?,?,'health:observation',1,1,?,?,?,?,?,?)""",(task,aid,label,self.day,self.day,self.day,staff_id,36+idx,state))
    def request(self,method,path,body=None,headers=None,expected=200):
        r=self.client.request(method,path,json=body,headers=headers or self.manager)
        self.assertEqual(r.status_code,expected,r.text)
        return r.json()
    def send(self,q,headers=None,session=None):
        r=self.request('POST','/api/agent/chat',{'question':q,'session_id':session or self.session},headers)
        print('USER:',q,'BOT:',r['turns'])
        return r['turns'][-1]
    def confirm(self,cmd,headers=None):
        return self.request('POST','/api/agent/actions/'+cmd['action_id'],{'session_id':self.session,'decision':'confirm'},headers)
    def test_manager_profile_and_followup(self):
        name=self.names[0]
        r=self.send(name.lower()+' 資料')
        self.assertIn(name+' #'+str(self.ids[0]),r['answer']['answer'])
        self.assertIn('入所日期',r['answer']['answer'])
        r=self.send('驅蟲日期？')
        self.assertIn(name,r['answer']['answer'])
    def test_manager_different_animals_keep_drafts(self):
        a=self.send(self.names[0]+' 健康：健康')['command']
        b=self.send(self.names[1]+' 健康：受傷')['command']
        self.confirm(a);self.confirm(b)
        r=self.send(self.names[0]+' 資料')
        self.assertIn('健康登錄為「健康」',r['answer']['answer'])
        self.assertEqual(self.send('改回來')['command']['animal_id'],self.ids[1])
    def test_manager_mixed_query_and_update(self):
        self.send(self.names[0]+' 資料')
        c=self.send('健康：健康；驅蟲日期：今天')['command']
        self.confirm(c)
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT health_status,dewormed FROM animals WHERE id=?',(self.ids[0],)).fetchone()[:],('healthy','yes'))
            self.assertEqual(db.execute('SELECT completed_date FROM deworming_events WHERE animal_id=?',(self.ids[0],)).fetchone()[0],self.day)
    def test_staff_reads_own_tasks_and_followup(self):
        name=self.names[0]
        r=self.send(name+' 資料',self.staff)
        self.assertIn(name,r['answer']['answer'])
        r=self.send('疫苗日期？',self.staff)
        self.assertIn(name,r['answer']['answer'])
        r=self.send('今天已完成哪些任務？',self.staff)
        self.assertIn('已完成任務',r['answer']['answer'])
        self.assertIn(self.names[2],r['answer']['answer'])
        self.assertNotIn(self.names[1],r['answer']['answer'])
    def test_staff_report_and_authorization(self):
        r=self.send('回報 '+self.names[0]+' 健康狀態待確認 結果：健康',self.staff)
        cmd=r['command'];self.assertEqual(cmd['type'],'staff_report')
        self.assertEqual(cmd['task_id'],self.tids[0])
        payload={'result':cmd['result'],'note':cmd['note'],'photos':[],'expected_day':cmd['day']}
        self.request('POST','/api/schedule/tasks/'+cmd['task_id']+'/report',payload,self.other,403)
        self.request('POST','/api/schedule/tasks/'+cmd['task_id']+'/report',payload,self.staff)
        self.assertIn('已完成',self.send('今天已完成哪些任務？',self.staff)['answer']['answer'])
        with self.main.connect() as db:
            self.assertEqual(db.execute('SELECT health_status FROM animals WHERE id=?',(self.ids[0],)).fetchone()[0],'healthy')
        r=self.send(self.names[1]+' 健康：健康',self.staff)
        self.assertEqual(r['command']['type'],'clarify')
    def test_staff_id_scope(self):
        r=self.send('員工 #'+str(self.sid)+' 今天班表')
        self.assertEqual(r['answer']['intent'],'staff_schedule')
    def test_query_not_edit(self):
        r=self.send('列出已驅蟲的動物')
        self.assertNotEqual(r.get('command',{}).get('type'),'animal_action')
    def test_incremental_consistency(self):
        path='/api/ai-tools/quality?scope=health'
        first=self.request('GET',path)
        self.assertGreaterEqual(first['checked_count'],3)
        empty=self.request('GET',path)
        self.assertEqual(empty['checked_count'],0)
        with self.main.connect() as db:
            db.execute("UPDATE animals SET vaccinated='yes' WHERE id=?",(self.ids[0],))
        one=self.request('GET',path)
        self.assertEqual(one['checked_count'],1)
        self.assertTrue(any(r['animal_id']==self.ids[0] and '疫苗' in r['detail'] for r in one['findings']))
        with self.main.connect() as db:
            db.execute("UPDATE animals SET vaccinated='unknown' WHERE id=?",(self.ids[0],))
        clear=self.request('GET',path)
        self.assertEqual(clear['checked_count'],1)
        self.assertFalse(any(r['animal_id']==self.ids[0] and '疫苗' in r['detail'] for r in clear['findings']))
        self.request('GET',path,headers=self.staff,expected=403)
if __name__=='__main__':unittest.main(verbosity=2)
