"""Demo API. Loads user-supplied trained models; never trains or fabricates evaluation scores."""
from __future__ import annotations
import json, random, sqlite3, threading, os, hmac, hashlib, base64, time, sys
from contextlib import closing
from functools import lru_cache
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar, math
from contextlib import contextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
import logging
from pydantic import BaseModel, Field
from uuid import uuid4

ROOT=Path(__file__).resolve().parent.parent
SEED_DB=ROOT/'backend'/'showcase.sqlite3'
DB=Path(os.environ.get('SHELTER_DB_PATH') or str(SEED_DB)).resolve()
if DB!=SEED_DB.resolve() and not DB.exists():
 DB.parent.mkdir(parents=True,exist_ok=True)
 if not SEED_DB.is_file():raise RuntimeError('Missing seed SQLite database')
 with closing(sqlite3.connect(SEED_DB)) as source, source, closing(sqlite3.connect(DB)) as target, target:source.backup(target)
MODELS=ROOT/'models'
lock=threading.RLock()
app=FastAPI(title='Shelter AI Showcase',version='1.0')
allowed_origins=['http://127.0.0.1:8000','http://localhost:8000']
allowed_origins.extend(origin.strip() for origin in os.environ.get('SHELTER_CORS_ORIGINS','').split(',') if origin.strip())
app.add_middleware(CORSMiddleware,allow_origins=allowed_origins,allow_methods=['*'],allow_headers=['*'])

AUTH_SECRET=os.environ.get('SHELTER_AUTH_SECRET') or 'local-demo-change-me'
configured_passwords=os.environ.get('SHELTER_AUTH_PASSWORDS')
AUTH_PASSWORDS=json.loads(configured_passwords) if configured_passwords else {str(n):f'{n:02}' for n in range(1,7)}
if configured_passwords and (len(AUTH_SECRET)<32 or not AUTH_PASSWORDS or any(
 key not in {'1','2','3','4','5','6'} or not isinstance(value,str) or len(value)<12
 for key,value in AUTH_PASSWORDS.items()
) or '1' not in AUTH_PASSWORDS or len(set(AUTH_PASSWORDS.values()))!=len(AUTH_PASSWORDS)):
 raise RuntimeError('Configure a strong SHELTER_AUTH_SECRET and distinct per-account passwords')
AUTH_SECRET=AUTH_SECRET.encode()
class LoginInput(BaseModel):
 password: str

def token_for(user_id:int):
 payload=f'{user_id}:{int(time.time())+86400}:{uuid4().hex}'
 signature=hmac.new(AUTH_SECRET,payload.encode(),hashlib.sha256).hexdigest()
 return base64.urlsafe_b64encode(f'{payload}:{signature}'.encode()).decode()

def verify_token(token:str):
 try:
  raw=base64.urlsafe_b64decode(token.encode()).decode()
  payload,signature=raw.rsplit(':',1)
  uid,expiry,*_=payload.split(':')
  valid=hmac.compare_digest(signature,hmac.new(AUTH_SECRET,payload.encode(),hashlib.sha256).hexdigest())
  return int(uid) if valid and int(expiry)>time.time() and uid in AUTH_PASSWORDS else None
 except (ValueError,TypeError,UnicodeError):return None

@app.post('/api/auth/login')
def login(body:LoginInput):
 uid=next((int(key) for key,value in AUTH_PASSWORDS.items()
           if hmac.compare_digest(value.encode(),body.password.encode())),None)
 if uid is None:raise HTTPException(401,'密碼錯誤')
 refresh_consistency_safely()
 return {'token':token_for(uid),'user_id':uid,'role':'manager' if uid==1 else 'staff'}

@app.middleware('http')
async def auth_guard(request:Request,call_next):
 global WORK_DATE
 WORK_DATE=datetime.now(ZoneInfo('Asia/Taipei')).date()
 path=request.url.path.rstrip('/')
 if not path.startswith('/api/') or path=='/api/auth/login' or request.method=='OPTIONS':return await call_next(request)
 uid=verify_token(request.headers.get('Authorization','').removeprefix('Bearer ').strip())
 if uid is None:return JSONResponse(status_code=401,content={'detail':'請先登入'})
 if uid!=1 and (path=='/api/tasks' or path.startswith('/api/staff/assignments')):
  return JSONResponse(status_code=403,content={'detail':'請在個人工作台查看與回報任務'})
 task_action=path.removeprefix('/api/schedule/tasks/').split('/') if path.startswith('/api/schedule/tasks/') else []
 own_task_action=request.method=='POST' and len(task_action)==2 and task_action[1] in {'report','summary','withdraw-report','photo-analysis'}
 if uid!=1 and request.method in ('POST','PATCH','DELETE','PUT') and path not in ('/api/stage2/answer','/api/chat','/api/agent/chat','/api/smart/handover') and not own_task_action:
  return JSONResponse(status_code=403,content={'detail':'此操作僅管理者可執行'})
 request.state.user_id=uid
 # Removed modules are no longer executable through old cached clients.
 if path.startswith(('/api/smart/rules','/api/smart/workflows','/api/smart/inbox')) or path in ('/api/smart/monitor','/api/smart/handover'):
  return JSONResponse(status_code=410,content={'detail':'此功能已移除'})
 response=await call_next(request)
 if response.status_code<300 and not path.endswith('/photo-analysis') and request.method in ('POST','PATCH','PUT','DELETE') and (path.startswith(('/api/animals','/api/schedule/tasks','/api/agent/actions','/api/tasks')) or path=='/api/smart/task'):
  await run_in_threadpool(refresh_consistency_safely)
 return response

def refresh_consistency_safely():
 # Never report a successful operational write as failed because of a secondary audit.
 # A failed audit transaction leaves the dirty queue available for the next read or write.
 try:
  from consistency_audit import refresh
  with lock,connect() as db:
   db.execute('BEGIN IMMEDIATE')
   refresh(db)
 except Exception:
  logging.getLogger(__name__).exception('Incremental consistency refresh failed')

@contextmanager
def connect():
 """Commit/rollback and ALWAYS close SQLite connection (Windows-safe)."""
 c=sqlite3.connect(DB,check_same_thread=False,timeout=15)
 c.row_factory=sqlite3.Row
 try:
  with c:
   yield c
 finally:
  c.close()

def init():
 if DB.exists() and DB.stat().st_size and not (DB.parent / (DB.name+'.pre_schedule.bak')).exists():
  with closing(sqlite3.connect(DB)) as original, original, sqlite3.connect(str(DB)+'.pre_schedule.bak') as backup: original.backup(backup)
 with lock,connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS animals (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, species TEXT NOT NULL, breed TEXT, age_months INTEGER, sex TEXT, health_status TEXT, vaccinated TEXT, sterilized TEXT, dewormed TEXT, intake_date TEXT, photo_url TEXT)')
  animal_cols={r[1] for r in c.execute('PRAGMA table_info(animals)')}
  if 'is_active' not in animal_cols:c.execute('ALTER TABLE animals ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
  if 'exit_date' not in animal_cols:c.execute('ALTER TABLE animals ADD COLUMN exit_date TEXT')
  if 'exit_reason' not in animal_cols:c.execute('ALTER TABLE animals ADD COLUMN exit_reason TEXT')
  c.execute('CREATE TABLE IF NOT EXISTS animal_stay_history (id INTEGER PRIMARY KEY AUTOINCREMENT, animal_id INTEGER NOT NULL, intake_date TEXT NOT NULL, exit_date TEXT, exit_reason TEXT, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP)')
  if 'exit_reason' not in {r[1] for r in c.execute('PRAGMA table_info(animal_stay_history)')}:c.execute('ALTER TABLE animal_stay_history ADD COLUMN exit_reason TEXT')
  for column in ('food_grams_per_day','routine_care_hours_per_day'):
   if column not in animal_cols:c.execute(f'ALTER TABLE animals ADD COLUMN {column} REAL')
  c.execute('CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL, name TEXT NOT NULL, skills TEXT NOT NULL, available_hours REAL NOT NULL, scheduled_hours REAL NOT NULL DEFAULT 0, attending INTEGER NOT NULL DEFAULT 1,weekly_hours REAL NOT NULL DEFAULT 40)')
  c.execute('CREATE TABLE IF NOT EXISTS assignment_snapshot (task_id TEXT PRIMARY KEY, animal_id INTEGER, animal_name TEXT, staff_id INTEGER, staff_name TEXT, category TEXT, label TEXT, date TEXT, hours REAL)')
  c.execute('CREATE TABLE IF NOT EXISTS task_overrides (animal_id INTEGER NOT NULL, label TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY(animal_id,label))')
  cols={r[1] for r in c.execute('PRAGMA table_info(task_overrides)')}
  for col in ('result','resolved','updated_at','note'):
   if col not in cols:c.execute(f'ALTER TABLE task_overrides ADD COLUMN {col} TEXT')
  c.execute('CREATE TABLE IF NOT EXISTS task_report_history (id INTEGER PRIMARY KEY AUTOINCREMENT, animal_id INTEGER, label TEXT, user_id INTEGER, old_state TEXT, new_state TEXT, old_result TEXT, new_result TEXT, old_resolved TEXT, new_resolved TEXT, changed_at TEXT DEFAULT CURRENT_TIMESTAMP)')
  c.execute('CREATE TABLE IF NOT EXISTS generated_tasks (task_id TEXT PRIMARY KEY, animal_id INTEGER NOT NULL, label TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
  c.execute('CREATE TABLE IF NOT EXISTS vaccination_records (id INTEGER PRIMARY KEY, animal_id INTEGER NOT NULL, vaccine_type TEXT NOT NULL DEFAULT "general", administered_date TEXT NOT NULL, next_due_date TEXT NOT NULL, source TEXT NOT NULL DEFAULT "staff_report", UNIQUE(animal_id,vaccine_type,administered_date))')
  # Track the exact vaccine dose introduced by a completed task; cancellation never guesses.
  c.execute('CREATE TABLE IF NOT EXISTS task_vaccination_link (animal_id INTEGER NOT NULL,label TEXT NOT NULL,record_id INTEGER NOT NULL,PRIMARY KEY(animal_id,label))')
  # Older installations may already contain vaccination_records without
  # administered_date. CREATE TABLE IF NOT EXISTS cannot upgrade an existing table.
  vaccine_cols={r[1] for r in c.execute('PRAGMA table_info(vaccination_records)')}
  if 'animal_id' not in vaccine_cols:
   raise RuntimeError('vaccination_records 缺少 animal_id；無法安全自動遷移，請檢查資料庫備份')
  for column,kind in [('vaccine_type',"TEXT NOT NULL DEFAULT 'general'"),
                      ('administered_date','TEXT'),('next_due_date','TEXT'),
                      ('source',"TEXT NOT NULL DEFAULT 'legacy'")]:
   if column not in vaccine_cols:
    c.execute(f'ALTER TABLE vaccination_records ADD COLUMN {column} {kind}')
  # Unknown historical vaccination dates remain NULL, never invent an injection date.
  c.execute('CREATE TABLE IF NOT EXISTS deworming_events (animal_id INTEGER NOT NULL, intake_date TEXT NOT NULL, completed_date TEXT NOT NULL, source TEXT NOT NULL DEFAULT "staff_report", PRIMARY KEY(animal_id,intake_date))')
  c.execute('CREATE TABLE IF NOT EXISTS task_metadata (task_id TEXT PRIMARY KEY, source TEXT NOT NULL DEFAULT "rule", is_new INTEGER NOT NULL DEFAULT 0, due_date TEXT, vaccine_type TEXT DEFAULT "general")')
  # Explicit reset marker: a browser refresh must not immediately auto-schedule reset tasks.
  c.execute('CREATE TABLE IF NOT EXISTS demo_ui_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
  snap_cols={r[1] for r in c.execute('PRAGMA table_info(assignment_snapshot)')}
  for col,kind in [('start_time','TEXT'),('end_time','TEXT'),('locked','INTEGER NOT NULL DEFAULT 0')]:
   if col not in snap_cols:c.execute(f'ALTER TABLE assignment_snapshot ADD COLUMN {col} {kind}')
  c.execute('CREATE INDEX IF NOT EXISTS idx_assignment_staff_date ON assignment_snapshot(staff_id,date)')
  c.execute('CREATE INDEX IF NOT EXISTS idx_assignment_date ON assignment_snapshot(date)')
  c.execute('CREATE TABLE IF NOT EXISTS task_animal_baseline (animal_id INTEGER, label TEXT, column_name TEXT, old_value TEXT, PRIMARY KEY(animal_id,label))')
  c.execute('CREATE TABLE IF NOT EXISTS profiles (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,capacity INTEGER,budget REAL,staff_hours REAL,food_rate REAL,care_minutes REAL,unit_cost REAL,food_stock_kg REAL NOT NULL DEFAULT 0)')
  profile_cols={r[1] for r in c.execute('PRAGMA table_info(profiles)')}
  if 'food_stock_kg' not in profile_cols:c.execute('ALTER TABLE profiles ADD COLUMN food_stock_kg REAL NOT NULL DEFAULT 0')
  c.execute("UPDATE profiles SET food_stock_kg=500 WHERE name='示範收容所' AND food_stock_kg=0")
  staff_cols={r[1] for r in c.execute('PRAGMA table_info(staff)')}
  if 'weekly_hours' not in staff_cols:c.execute('ALTER TABLE staff ADD COLUMN weekly_hours REAL NOT NULL DEFAULT 40')
  for column,kind in [('shift_start','TEXT NOT NULL DEFAULT "09:00"'),('shift_end','TEXT NOT NULL DEFAULT "17:00"'),('break_start','TEXT'),('break_end','TEXT')]:
   if column not in staff_cols:c.execute(f'ALTER TABLE staff ADD COLUMN {column} {kind}')
  if c.execute('SELECT COUNT(*) FROM animals').fetchone()[0]==0:
   rng=random.Random(162);names=['小橘','米米','豆豆','可可','奶茶','阿福','球球','花花','小白','麻糬','布丁','黑糖','橘子','小虎','朵朵','樂樂','皮皮','旺旺']
   today=date.today()
   for i in range(82):
    species='dog' if i%5<3 else 'cat'; breed=rng.choice(['米克斯','柴犬','台灣犬'] if species=='dog' else ['米克斯','虎斑','橘貓']); flags=[rng.choice(['yes','yes','no','unknown']) for _ in range(3)]
    c.execute('INSERT INTO animals (name,species,breed,age_months,sex,health_status,vaccinated,sterilized,dewormed,intake_date,photo_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(f'{names[i%len(names)]}{i+1:03}',species,breed,rng.randint(3,132),rng.choice(['male','female']),rng.choice(['healthy']*8+['needs_review','serious']),*flags,(today-timedelta(days=rng.randint(1,250))).isoformat(),None))
  if c.execute('SELECT COUNT(*) FROM profiles').fetchone()[0]==0:
   c.execute('INSERT INTO profiles (name,capacity,budget,staff_hours,food_rate,care_minutes,unit_cost) VALUES (?,?,?,?,?,?,?)',('示範收容所',100,350000,32,0.4,15,85))
  if c.execute('SELECT COUNT(*) FROM staff').fetchone()[0]==0:
   sample=[('小林',['health:observation','admin:records'],8,0,1),('陳獸醫',['health:observation','health:veterinary'],6,1,1),('阿美',['admin:records','adoption:followup'],8,2,1),('小周',['health:observation','adoption:followup'],8,0,1),('王助理',[],6,0,1)]
   for name,skills,hours,scheduled,attending in sample:
    c.execute('INSERT INTO staff (profile_id,name,skills,available_hours,scheduled_hours,attending) VALUES (1,?,?,?,?,?)',(name,json.dumps(skills),hours,scheduled,attending))
  # 保留既有員工資料，只補齊專職飼料管理者。
  if not c.execute("SELECT 1 FROM staff WHERE profile_id=1 AND name='王助理'").fetchone():
   c.execute('INSERT INTO staff (profile_id,name,skills,available_hours,scheduled_hours,attending,weekly_hours) VALUES (?,?,?,?,?,?,?)',(1,'王助理','[]',6,0,1,30))

init()

def load(cls,filename):
 m=cls();m.load_model(str(MODELS/filename));return m
# Model files are optional in demo mode; never pretend generated values are trained predictions.
DEMO_MODE=os.environ.get('SHELTER_MODEL_MODE','demo').lower()=='demo'
@lru_cache(maxsize=4)
def optional_model(kind, filename):
 path=MODELS/filename
 if DEMO_MODE and not path.is_file():return None
 if not path.is_file():raise FileNotFoundError(f'Missing required model file: {path}')
 from catboost import CatBoostClassifier, CatBoostRegressor
 cls=CatBoostClassifier if kind=='classifier' else CatBoostRegressor
 return load(cls,filename)

def get_health_model():
 return optional_model('classifier','health_catboost.cbm')

def get_adoption_model():
 return optional_model('classifier','adoption_catboost.cbm')

def model_availability(filename):
 # Health checks must never import ML libraries or load model weights.
 return 'on_demand' if (MODELS/filename).is_file() else 'demo' if DEMO_MODE else 'missing'
occupancy_metrics=json.loads((MODELS/'best_params_and_metrics.json').read_text(encoding='utf-8')) if (MODELS/'best_params_and_metrics.json').is_file() else {}

@lru_cache(maxsize=1)
def occupancy_research_inputs():
 import pandas as pd
 intake_model=optional_model('regressor','intakes_catboost.cbm')
 outcome_model=optional_model('regressor','outcomes_catboost.cbm')
 history_path=Path(__file__).parent/'daily_history.csv'
 if history_path.is_file():
  history=pd.read_csv(history_path,parse_dates=['date']).sort_values('date')
 elif DEMO_MODE:
  rng=random.Random(731)
  end=date.today()-timedelta(days=1)
  history=pd.DataFrame([{'date':pd.Timestamp(end-timedelta(days=119-i)),'intakes':rng.randint(1,7),'outcomes':rng.randint(1,6)} for i in range(120)])
 else:raise FileNotFoundError(f'Missing required history file: {history_path}')
 return intake_model,outcome_model,history

WORK_DATE=datetime.now(ZoneInfo("Asia/Taipei")).date() # Taiwan-local task scheduling date

class AnimalInput(BaseModel):
 name:str=Field(min_length=1,max_length=80)
 species:str=Field(pattern='^(dog|cat|other)$')
 breed:str|None=None
 age_months:int|None=Field(default=None,ge=0)
 sex:str=Field(pattern='^(male|female|unknown)$')
 health_status:str='unknown'
 vaccinated:str=Field(pattern='^(yes|no|unknown)$')
 sterilized:str=Field(pattern='^(yes|no|unknown)$')
 dewormed:str=Field(pattern='^(yes|no|unknown)$')
 intake_date:date
 photo_url:str|None=None

class AnimalExitInput(BaseModel):
 exit_date:date
 exit_reason:str=Field(min_length=1,max_length=500)

class AnimalReadmitInput(BaseModel):
 intake_date:date

class ProfileInput(BaseModel):
 name:str=Field(min_length=1)
 capacity:int=Field(ge=0)
 budget:float=Field(ge=0)
 staff_hours:float=Field(ge=0)
 food_rate:float=Field(ge=0)
 care_minutes:float=Field(ge=0)
 unit_cost:float=Field(ge=0)
 food_stock_kg:float=Field(default=0,ge=0)

def row(r):
 d=dict(r);d.update(stay_id=d['id'],intake_at=d['intake_date'],stay_days=max(0,(date.today()-date.fromisoformat(d['intake_date'])).days),dataset_scope='synthetic_demo',data_notes=['此動物為固定亂數種子產生的展示資料，不是真實收容所紀錄。']);return d

def get_animal(id):
 with connect() as c:r=c.execute('SELECT * FROM animals WHERE id=?',(id,)).fetchone()
 if not r:raise HTTPException(404,'動物不存在')
 return row(r)

def resource_totals(animals, food_rate, care_minutes):
 """Use per-animal stored estimates; fall back only for records not yet enriched."""
 food=sum((a.get('food_grams_per_day') if a.get('food_grams_per_day') is not None else food_rate*1000) for a in animals)/1000
 care=sum((a.get('routine_care_hours_per_day') if a.get('routine_care_hours_per_day') is not None else care_minutes/60) for a in animals)
 return food,care

@app.get('/healthz')
def healthz():
 return {'status':'ok','health_catboost':model_availability('health_catboost.cbm'),'adoption_catboost':model_availability('adoption_catboost.cbm'),'occupancy_catboost':'on_demand'}
@app.get('/api/animals')
def animals(q:str='',species:str='',dataset:str='',skip:int=0,limit:int=500):
 with connect() as c:rows=c.execute('SELECT * FROM animals WHERE is_active=1 AND (name LIKE ? OR CAST(id AS TEXT) LIKE ?) AND (?="" OR species=?) ORDER BY id LIMIT ? OFFSET ?',('%'+q+'%','%'+q+'%',species,species,min(limit,2000),skip)).fetchall()
 return [row(r) for r in rows]
@app.get('/api/animals/exited')
def exited_animals(q:str=''):
 with connect() as c:
  rows=c.execute('SELECT * FROM animals WHERE is_active=0 AND (name LIKE ? OR CAST(id AS TEXT) LIKE ?) ORDER BY exit_date DESC,id DESC',('%'+q+'%','%'+q+'%')).fetchall()
 return [row(r) for r in rows]

@app.get('/api/animals/{id}/stays')
def animal_stays(id:int):
 get_animal(id)
 with connect() as c:
  history=[dict(r) for r in c.execute('SELECT intake_date,exit_date,exit_reason FROM animal_stay_history WHERE animal_id=? ORDER BY id',(id,))]
  animal=c.execute('SELECT intake_date,exit_date,exit_reason,is_active FROM animals WHERE id=?',(id,)).fetchone()
 return history+[{'intake_date':animal['intake_date'],'exit_date':animal['exit_date'],'exit_reason':animal['exit_reason']}]

@app.post('/api/animals/{id}/readmit')
def readmit_animal(id:int,payload:AnimalReadmitInput):
 with lock,connect() as c:
  animal=c.execute('SELECT * FROM animals WHERE id=?',(id,)).fetchone()
  if not animal:raise HTTPException(404,'動物不存在')
  if animal['is_active']:raise HTTPException(409,'動物目前已在所內')
  if not animal['exit_date']:raise HTTPException(409,'缺少離所日期，無法重新入所')
  if payload.intake_date<date.fromisoformat(animal['exit_date']):raise HTTPException(422,'重新入所日期不能早於離所日期')
  c.execute('INSERT INTO animal_stay_history(animal_id,intake_date,exit_date,exit_reason) VALUES (?,?,?,?)',(id,animal['intake_date'],animal['exit_date'],animal['exit_reason']))
  c.execute('UPDATE animals SET is_active=1,intake_date=?,exit_date=NULL,exit_reason=NULL WHERE id=?',(payload.intake_date.isoformat(),id))
  stay=c.execute('SELECT MAX(id) FROM animal_stay_history WHERE animal_id=?',(id,)).fetchone()[0]
  if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='weekly_tasks'").fetchone():
   c.execute("UPDATE weekly_tasks SET state='cancelled',reason='重新入所：舊驅蟲任務結束' WHERE animal_id=? AND label IN ('確認驅蟲紀錄','基礎驅蟲','更新驅蟲紀錄','更新驅蟲狀態') AND state IN ('pending','in_progress')",(id,))
   c.execute("""INSERT OR IGNORE INTO weekly_tasks(task_id,animal_id,label,skill,priority,quarters,earliest,due)
     VALUES (?,?,'基礎驅蟲','health:observation',3,2,?,?)""",(f'readmit:{stay}',id,payload.intake_date.isoformat(),payload.intake_date.isoformat()))
 return get_animal(id)

@app.get('/api/animals/{id}')
def animal(id:int):return get_animal(id)
@app.post('/api/animals')
def create_animal(a:AnimalInput):
 if not a.name.strip() or a.intake_date>datetime.now(ZoneInfo('Asia/Taipei')).date():raise HTTPException(422,'名稱或入所日期無效')
 d=a.model_dump(mode='json');d['name']=a.name.strip();keys=list(d)
 with lock,connect() as c:
  cur=c.execute('INSERT INTO animals ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')',tuple(d.values()));id=cur.lastrowid
 return get_animal(id)
@app.patch('/api/animals/{id}')
def update_animal(id:int,a:AnimalInput):
 if not a.name.strip() or a.intake_date>datetime.now(ZoneInfo('Asia/Taipei')).date():raise HTTPException(422,'名稱或入所日期無效')
 get_animal(id);d=a.model_dump(mode='json');d['name']=a.name.strip()
 with lock,connect() as c:c.execute('UPDATE animals SET '+','.join(k+'=?' for k in d)+' WHERE id=?',(*d.values(),id))
 return get_animal(id)
@app.post('/api/animals/{id}/exit')
def exit_animal(id:int,payload:AnimalExitInput):
 with lock,connect() as c:
  animal=c.execute('SELECT * FROM animals WHERE id=?',(id,)).fetchone()
  if not animal:raise HTTPException(404,'動物不存在')
  if not animal['is_active']:raise HTTPException(409,'動物已離所')
  if payload.exit_reason not in ('adoption','transfer','return_to_owner','other_exit','death_euthanasia'):raise HTTPException(422,'離所原因須選擇資料集中的實際離所類別')
  if payload.exit_date<date.fromisoformat(animal['intake_date']):raise HTTPException(422,'離所日期不能早於入所日期')
  today=payload.exit_date.isoformat()
  c.execute('UPDATE animals SET is_active=0,exit_date=?,exit_reason=? WHERE id=?',(today,payload.exit_reason.strip(),id))
  # Keep clinical reports and assignment snapshots for auditing; exclude exited animals from active schedules.
 return {'exited':True,'animal_id':id,'exit_date':today,'exit_reason':payload.exit_reason.strip()}
@app.get('/api/stats/summary')
def summary():
 with connect() as c:
  count=c.execute('SELECT COUNT(*) FROM animals WHERE is_active=1').fetchone()[0]
  dog=c.execute("SELECT COUNT(*) FROM animals WHERE is_active=1 AND species='dog'").fetchone()[0]
  review=c.execute("SELECT COUNT(*) FROM animals WHERE is_active=1 AND health_status!='healthy'").fetchone()[0]
 return {'in_care_count':count,'dog_count':dog,'cat_count':count-dog,'review_count':review,'demo':True}

def pet_type(a):return '1' if a['species']=='dog' else '2'
def tri(v):return {'yes':'1','no':'2','unknown':'3'}.get(v,'3')
def gender(a):return {'male':'1','female':'2','unknown':'3'}[a['sex']]
def health_features(a, model=None):
 import pandas as pd
 model=model if model is not None else get_health_model()
 return pd.DataFrame([{'Type':pet_type(a),'Age':int((a['age_months'] or 24)/12),'Gender':gender(a),'Vaccinated':tri(a['vaccinated']),'Dewormed':tri(a['dewormed']),'Sterilized':tri(a['sterilized'])}])[model.feature_names_]
def health_prediction(a):
 health_model=get_health_model()
 if health_model is None:
  labels=['1','2','3'];seed=int(a['id'])*41+int(a.get('age_months') or 24)
  base=[0.72,0.20,0.08] if a.get('health_status')=='healthy' else ([0.12,0.26,0.62] if a.get('health_status')=='serious' else [0.22,0.60,0.18])
  jitter=(seed%11-5)*0.005
  probs=[round(base[0]+jitter,5),round(base[1]-jitter,5),round(base[2],5)]
  return {'status':'demo','mode':'demo','predicted_label':labels[max(range(3),key=lambda i:probs[i])],'class_probabilities':dict(zip(labels,probs))}
 x=health_features(a,health_model);prob=health_model.predict_proba(x)[0];labels=[str(k) for k in health_model.classes_];ix=max(range(len(prob)),key=lambda i:prob[i])
 return {'status':'ready','predicted_label':labels[ix],'class_probabilities':dict(zip(labels,[round(float(v),5) for v in prob]))}

def assess(a):
 health_model=get_health_model()
 ml=health_prediction(a)
 tasks=[]
 if a['vaccinated']!='yes':tasks.append('確認疫苗紀錄')
 if a['dewormed']!='yes':tasks.append('確認驅蟲紀錄')
 if a['sterilized']!='yes':tasks.append('評估絕育安排')
 if a['health_status'] in ('sick','injured','serious'):tasks.append('傷病治療')
 elif a['health_status']!='healthy':tasks.append('健康狀態待確認')
 return {'mock':health_model is None,'mode':'demo' if health_model is None else 'real','ml_status':'demo' if health_model is None else 'real','ml_model':ml,'priority':'high' if a['health_status'] in ('serious','sick','injured') else 'medium' if tasks else 'low','tasks':tasks,'model_version':'health_catboost.cbm' if health_model is not None else 'synthetic-demo-health-v1','warnings':['模型標籤來自 PetFinder，輸入欄位有示範映射；結果僅供展示，不可作為醫療診斷。']}
@app.post('/api/health/assess')
def health_assess(animal_id:int):return assess(get_animal(animal_id))
@app.get('/api/health/batch')
def batch_health():
 with connect() as c:rows=c.execute('SELECT * FROM animals WHERE is_active=1 ORDER BY id').fetchall()
 return [{'animal_id':a['id'],**assess(row(a))} for a in rows]

@app.post('/api/adoption/predict')
def adoption(animal_id:int):
 a=get_animal(animal_id)
 adoption_model=get_adoption_model()
 if adoption_model is None:
  seed=int(a['id'])*13+int(a.get('age_months') or 24)
  probs=[0.08,0.17,0.36,0.25,0.14]
  idx=seed%5;probs[idx]+=0.05;total=sum(probs);probs=[round(v/total,4) for v in probs]
  return {'mode':'demo','ml_status':'demo','model_version':'synthetic-demo-adoption-v1','adoption_speed':{'predicted_class':max(range(5),key=lambda i:probs[i]),'class_probabilities':{str(i):v for i,v in enumerate(probs)},'label_meaning':'展示用送養速度類別 0–4，非真實模型預測'},'adoption_event':{'available':False,'note':'展示模式未提供真實送養事件預測'},'warnings':['此結果為固定規則產生的模擬資料，不是 CatBoost 推論。']}
 import pandas as pd
 x=pd.DataFrame([{'Type':pet_type(a),'Age':int((a['age_months'] or 24)/12),'Breed1':'307','Breed2':'0','Gender':gender(a),'MaturitySize':'2','FurLength':'1','Vaccinated':tri(a['vaccinated']),'Dewormed':tri(a['dewormed']),'Sterilized':tri(a['sterilized']),'Health':str({'healthy':1,'needs_review':2,'serious':3}.get(a['health_status'],1)),'Fee':0,'PhotoAmt':0}])[adoption_model.feature_names_]
 p=adoption_model.predict_proba(x)[0];pred=int(adoption_model.classes_[max(range(len(p)),key=lambda i:p[i])])
 return {'mode':'real','ml_status':'real','model_version':'adoption_catboost.cbm','adoption_speed':{'predicted_class':pred,'class_probabilities':{str(k):round(float(v),4) for k,v in zip(adoption_model.classes_,p)},'label_meaning':'PetFinder 送養速度類別 0–4，不等於精確天數'},'warnings':['PetFinder 特徵中的品種代碼、費用、照片數為展示假設值；跨資料集預測未經在地驗證。']}

def features_for(target_date, hist):
 import numpy as np
 f={'dayofweek':target_date.weekday(),'month':target_date.month,'dayofyear':target_date.timetuple().tm_yday,'dayofmonth':target_date.day,'is_weekend':int(target_date.weekday()>=5),'time_idx':(target_date-date.fromisoformat('2025-05-06')).days}
 for target in ['intakes','outcomes']:
  values=[float(r[target]) for r in hist]
  for lag in (1,2,3,7,14,21,28):f[f'{target}_lag_{lag}']=values[-lag]
  for window in (7,14,28):
   f[f'{target}_mean_{window}']=float(np.mean(values[-window:]));f[f'{target}_std_{window}']=float(np.std(values[-window:],ddof=1))
 return f
@app.get('/api/occupancy/forecast')
def forecast(days:int=30):
 if days not in (7,14,30):raise HTTPException(422,'僅支援 7、14、30 天')
 import numpy as np
 import pandas as pd
 intake_model,outcome_model,history=occupancy_research_inputs()
 hist=history[['intakes','outcomes']].to_dict('records');last=date.fromisoformat(str(history.iloc[-1]['date'].date()))
 count=summary()['in_care_count'];running=count;points=[]
 # Model training data ends 2026-10-22; forecast is explicitly anchored at that historical cutoff.
 for i in range(1,days+1):
  dt=last+timedelta(days=i);features=features_for(dt,hist)
  if intake_model is None or outcome_model is None:
   intake=max(0,int(round(float(np.mean([r['intakes'] for r in hist[-14:]]))+(i%5-2)*0.3)))
   outcome=max(0,int(round(float(np.mean([r['outcomes'] for r in hist[-14:]]))+(i%7-3)*0.2)))
  else:
   intake=max(0,round(float(intake_model.predict(pd.DataFrame([features])[intake_model.feature_names_])[0])))
   outcome=max(0,round(float(outcome_model.predict(pd.DataFrame([features])[outcome_model.feature_names_])[0])))
  running=max(0,running+intake-outcome)
  hist.append({'intakes':intake,'outcomes':outcome})
  # 以歷史逐日入離所量的殘差代理波動估算未校正情境帶；不是信賴區間。
  daily_variance=float(history['intakes'].var()+history['outcomes'].var())
  margin=1.645*np.sqrt(max(0.0,daily_variance)*i)
  points.append({'date':dt.isoformat(),'expected_occupancy':running,'lower_bound':max(0,int(np.floor(running-margin))),'upper_bound':int(np.ceil(running+margin)),'predicted_intakes':intake,'predicted_outcomes':outcome})
 return {'mock':intake_model is None or outcome_model is None,'mode':'demo' if intake_model is None or outcome_model is None else 'real','demo':True,'current_count':count,'horizon_days':days,'forecast':points,'model_version':'synthetic-demo-occupancy-v1' if intake_model is None or outcome_model is None else 'intakes_catboost.cbm + outcomes_catboost.cbm','interval_method':'歷史每日入所與離所量變異數的平方根時間擴散 ×1.645，未校正情境帶（非統計信賴區間）','warnings':['預測以歷史資料截止日 2026-10-22 為起點，將目前展示名單數量作為假設基準。','多日預測採遞迴法，尚未有多步回測；上下界使用歷史量變異近似，非經驗證的信賴或預測區間。']}

@app.get('/api/resources/animal-needs')
def animal_needs():
 with connect() as c:rows=c.execute('SELECT * FROM animals WHERE is_active=1 ORDER BY id').fetchall()
 if (ROOT/'stage2_training').exists():
  from stage2_service import resource_rate_for_animal,resource_table
  resource=resource_table()
  results=[]
  for r in rows:
   a=dict(r)
   try:
    food,care,source=resource_rate_for_animal(a,resource)
    a.update(food_grams_per_day=round(food*1000,2),routine_care_hours_per_day=round(care,4),resource_source=source)
   except ValueError as exc:
    a.update(resource_source=str(exc))
   results.append({k:a[k] for k in ('id','name','species','food_grams_per_day','routine_care_hours_per_day','resource_source')})
  return results
 return [dict(r) for r in rows]

@app.get('/api/resources/needs-forecast')
def needs_forecast(days:int=30):
 if days < 1 or days > 30:raise HTTPException(422,'資源需求前端僅支援 1–30 天')
 with connect() as c:
  animals=[dict(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1')]
 if (ROOT/'stage2_training').exists():
  from stage2_service import resource_forecast
  try:return resource_forecast(animals,datetime.now(ZoneInfo("Asia/Taipei")).date(),days)
  except (FileNotFoundError,ValueError) as exc:raise HTTPException(503,f'Stage 2 模型推論失敗：{exc}') from exc
 occupancy=forecast(days)
 with connect() as c:
  animals=[dict(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1')]
  profile=c.execute('SELECT * FROM profiles ORDER BY id LIMIT 1').fetchone()
 rate=float(profile['food_rate']) if profile else .4
 minutes=float(profile['care_minutes']) if profile else 15
 food,care=resource_totals(animals,rate,minutes)
 count=len(animals)
 daily_food=food/count if count else rate
 daily_care=care/count if count else minutes/60
 points=[{'date':p['date'],'expected_food_kg':round(p['expected_occupancy']*daily_food,2),'food_lower_kg':round(p['lower_bound']*daily_food,2),'food_upper_kg':round(p['upper_bound']*daily_food,2),'expected_care_hours':round(p['expected_occupancy']*daily_care,2),'care_lower_hours':round(p['lower_bound']*daily_care,2),'care_upper_hours':round(p['upper_bound']*daily_care,2)} for p in occupancy['forecast']]
 return {'mode':'rule_based_demo','forecast':points,'daily_food_kg':round(food,2),'daily_care_hours':round(care,2),'animal_count':count,'estimated_animals':sum(a['food_grams_per_day'] is not None and a['routine_care_hours_per_day'] is not None for a in animals),'note':'Austin 欄位衍生之規則式個體需求估算；未來動物組成按目前平均值固定，非真實餵食建議或已驗證模型。'}

@app.get('/api/resources/profiles')
def profiles():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM profiles ORDER BY id')]
@app.post('/api/resources/profiles')
def create_profile(p:ProfileInput):
 d=p.model_dump()
 with lock,connect() as c:
  cur=c.execute('INSERT INTO profiles ('+','.join(d)+') VALUES ('+','.join('?' for _ in d)+')',tuple(d.values()));id=cur.lastrowid
 return {'id':id,'shelter_id':str(id),**d}
@app.patch('/api/resources/profiles/{id}')
def update_profile(id:int,p:ProfileInput):
 d=p.model_dump()
 with lock,connect() as c:
  if not c.execute('SELECT 1 FROM profiles WHERE id=?',(id,)).fetchone():raise HTTPException(404,'收容所不存在')
  c.execute('UPDATE profiles SET '+','.join(k+'=?' for k in d)+' WHERE id=?',(*d.values(),id))
 return {'id':id,'shelter_id':str(id),**d}
@app.delete('/api/resources/profiles/{id}')
def delete_profile(id:int):
 with lock,connect() as c:c.execute('DELETE FROM profiles WHERE id=?',(id,))
 return {'deleted':True}
class StaffInput(BaseModel):
 profile_id:int
 name:str=Field(min_length=1)
 skills:list[str]
 available_hours:float=Field(ge=0)
 scheduled_hours:float=Field(ge=0)
 attending:bool=True
 weekly_hours:float=Field(default=40,ge=0)
 shift_start:str="09:00"
 shift_end:str="17:00"
 break_start:str|None=None
 break_end:str|None=None

VALID_SKILLS={'health:observation','health:veterinary','admin:records','adoption:followup'}
def staff_row(r):
 d=dict(r);d['skills']=json.loads(d['skills']);d['attending']=bool(d['attending']);return d

def validate_shift(item):
 try:
  start=time_quarter(item.shift_start);end=time_quarter(item.shift_end)
  if end<=start or quarter_time(start)!=item.shift_start or quarter_time(end)!=item.shift_end:raise ValueError()
  if item.break_start or item.break_end:
   if not item.break_start or not item.break_end:raise ValueError()
   bs=time_quarter(item.break_start);be=time_quarter(item.break_end)
   if not (start<=bs<be<=end) or quarter_time(bs)!=item.break_start or quarter_time(be)!=item.break_end:raise ValueError()
 except (TypeError,ValueError):raise HTTPException(422,'員工班表時間必須為 HH:MM、每 15 分鐘且結束晚於開始')
@app.get('/api/resources/staff')
def staff(profile_id:int=1):
 with connect() as c:return [staff_row(r) for r in c.execute('SELECT * FROM staff WHERE profile_id=? ORDER BY id',(profile_id,))]
@app.post('/api/resources/staff')
def add_staff(item:StaffInput):
 validate_shift(item)
 if not set(item.skills)<=VALID_SKILLS:raise HTTPException(422,'不支援的技能資格')
 with lock,connect() as c:
  if not c.execute('SELECT 1 FROM profiles WHERE id=?',(item.profile_id,)).fetchone():raise HTTPException(404,'收容所不存在')
  cur=c.execute('INSERT INTO staff (profile_id,name,skills,available_hours,scheduled_hours,attending,weekly_hours,shift_start,shift_end,break_start,break_end) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(item.profile_id,item.name,json.dumps(item.skills),item.available_hours,item.scheduled_hours,int(item.attending),item.weekly_hours,item.shift_start,item.shift_end,item.break_start,item.break_end))
 return {'id':cur.lastrowid,**item.model_dump()}
@app.put('/api/resources/staff/{id}')
def edit_staff(id:int,item:StaffInput):
 validate_shift(item)
 if not set(item.skills)<=VALID_SKILLS:raise HTTPException(422,'不支援的技能資格')
 with lock,connect() as c:
  # Removing a qualification must not silently leave today's pending work
  # assigned to a worker who can no longer perform it.
  todays=c.execute('''SELECT a.label FROM assignment_snapshot a
    LEFT JOIN task_overrides t ON t.animal_id=a.animal_id AND t.label=a.label
    WHERE a.staff_id=? AND a.date=? AND COALESCE(t.state,'pending')!='done' ''',
    (id,WORK_DATE.isoformat())).fetchall()
  incompatible=sorted({r['label'] for r in todays if r['label'] in TASK_CATALOG and TASK_CATALOG[r['label']][1] not in item.skills})
  if incompatible:raise HTTPException(409,'請先重新指派使用該技能的未完成任務：'+'、'.join(incompatible))
  planned=c.execute('SELECT hours FROM assignment_snapshot WHERE staff_id=? AND date=?',(id,WORK_DATE.isoformat() if 'WORK_DATE' in globals() else date.today().isoformat())).fetchall()
  used=sum(math.ceil(float(r['hours'])*4-1e-9) for r in planned)
  new_limit=max(0,math.floor((item.available_hours-item.scheduled_hours)*4+1e-9)) if item.attending else 0
  if used>new_limit:raise HTTPException(409,'調整後員工工時不足，請先重新安排現有任務')
  cur=c.execute('UPDATE staff SET profile_id=?,name=?,skills=?,available_hours=?,scheduled_hours=?,attending=?,weekly_hours=?,shift_start=?,shift_end=?,break_start=?,break_end=? WHERE id=?',(item.profile_id,item.name,json.dumps(item.skills),item.available_hours,item.scheduled_hours,int(item.attending),item.weekly_hours,item.shift_start,item.shift_end,item.break_start,item.break_end,id))
  if not cur.rowcount:raise HTTPException(404,'員工不存在')
 return {'id':id,**item.model_dump()}
@app.delete('/api/resources/staff/{id}')
def remove_staff(id:int):
 with lock,connect() as c:c.execute('DELETE FROM staff WHERE id=?',(id,))
 return {'deleted':True}

OBSOLETE_TASKS=('未來長期滯留風險','長期在所動物關懷','長期留所追蹤','定期驅蟲')
TASK_CATALOG={'優先確認健康狀況':('health','health:veterinary',1.0,True),'健康狀態待確認':('health','health:observation',0.5,False),'疫苗紀錄待確認':('admin','admin:records',0.25,False),'疫苗施打':('health','health:veterinary',0.5,False),'基礎驅蟲':('health','health:observation',0.5,False),'評估絕育安排':('admin','admin:records',0.25,False),'健康問題追蹤':('health','health:veterinary',1.0,True),'補做驅蟲':('health','health:observation',0.5,False),'確認疫苗紀錄':('admin','admin:records',0.25,False),'確認驅蟲紀錄':('admin','admin:records',0.25,False)}
from care_workflow import ADDITIONAL_TASKS
TASK_CATALOG.update(ADDITIONAL_TASKS)
class TaskChange(BaseModel):
 animal_id:int
 label:str
 state:str=Field(pattern='^(pending|done|removed)$')
 result:str|None=None
 resolved:str|None=None
 note:str|None=None
 administered_date:str|None=None
 edit_report:bool=False
@app.get('/api/animals/{animal_id}/vaccinations')
def animal_vaccinations(animal_id:int):
 get_animal(animal_id)
 with connect() as c:
  return [dict(r) for r in c.execute('SELECT vaccine_type,administered_date,next_due_date,source FROM vaccination_records WHERE animal_id=? ORDER BY administered_date DESC',(animal_id,))]

@app.get('/api/animals/{animal_id}/deworming')
def animal_deworming(animal_id:int):
 get_animal(animal_id)
 with connect() as c:
  return [dict(r) for r in c.execute('SELECT intake_date,completed_date,source FROM deworming_events WHERE animal_id=? ORDER BY intake_date DESC',(animal_id,))]

@app.get('/api/tasks')
def list_tasks():
 with connect() as c:
  animals=[row(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1')]
  overrides={(r['animal_id'],r['label']):r['state'] for r in c.execute('SELECT * FROM task_overrides') if r['label'] not in OBSOLETE_TASKS}
 result=[]
 for t in build_tasks(animals,overrides,include_done=True):result.append(t)
 with lock,connect() as c:
  for t in result:
   if t['label']=='疫苗施打' and t.get('due_date') and t['due_date']<=WORK_DATE.isoformat():
    c.execute('INSERT OR IGNORE INTO task_metadata(task_id,source,is_new,due_date) VALUES (?,?,1,?)',(t['id'],'rule',t.get('due_date')))
    t['is_new']=bool(c.execute('SELECT is_new FROM task_metadata WHERE task_id=?',(t['id'],)).fetchone()[0])
 return result
def queue_followup(c, animal_id, label, note=''):
 """Persist follow-up even if no qualified worker has capacity."""
 task_id=f'{animal_id}:{label}'
 existing=c.execute('SELECT 1 FROM generated_tasks WHERE task_id=?',(task_id,)).fetchone()
 if existing:return False
 c.execute('INSERT OR IGNORE INTO generated_tasks(task_id,animal_id,label) VALUES (?,?,?)',(task_id,animal_id,label))
 if note:
  c.execute("INSERT INTO task_overrides(animal_id,label,state,result,resolved,note,updated_at) VALUES (?,?, 'pending',NULL,NULL,?,CURRENT_TIMESTAMP) ON CONFLICT(animal_id,label) DO UPDATE SET note=excluded.note",(animal_id,label,note))
 c.execute('INSERT OR IGNORE INTO task_metadata(task_id,source,is_new) VALUES (?,?,1)',(task_id,'employee_report'))
 return True

@app.put('/api/tasks')
def change_task(item:TaskChange,request:Request):
 if item.label in OBSOLETE_TASKS or item.label.startswith('定期驅蟲（') or item.label not in TASK_CATALOG:raise HTTPException(422,'不支援的任務類型')
 get_animal(item.animal_id)
 uid=request.state.user_id
 with lock,connect() as c:
  if uid!=1:
   workers=c.execute('SELECT id FROM staff WHERE profile_id=1 ORDER BY id').fetchall()
   if uid-2<0 or uid-2>=len(workers):raise HTTPException(403,'找不到員工')
   if not c.execute('SELECT 1 FROM assignment_snapshot WHERE animal_id=? AND label=? AND staff_id=?',(item.animal_id,item.label,workers[uid-2]['id'])).fetchone():raise HTTPException(403,'只能回報自己的派工')
  previous=c.execute('SELECT * FROM task_overrides WHERE animal_id=? AND label=?',(item.animal_id,item.label)).fetchone()
  old_state=previous['state'] if previous else 'pending'
  if item.edit_report:
   if item.state!='done' or old_state!='done':raise HTTPException(409,'只能編輯已完成且已儲存的回報')
   if item.label=='健康狀態待確認':
    if item.result not in ('healthy','sick','injured'):raise HTTPException(422,'請選擇健康、生病或受傷')
   elif item.label=='優先確認健康狀況':
    if item.resolved not in ('yes','no'):raise HTTPException(422,'請同時回報健康問題是否解決')
    if item.resolved=='no' and not (item.note or '').strip():raise HTTPException(422,'健康問題未解決時必須填寫追蹤備註')
   elif item.result not in ('yes','no'):raise HTTPException(422,'請選擇是或否')
   # Completion/results can have already created clinical records and follow-ups.
   # Changing those events would require a separate audited correction workflow.
   if item.result!=previous['result'] or item.resolved!=previous['resolved']:
    raise HTTPException(409,'修改醫療或健康判定結果請先重新開啟任務；已完成回報可直接編輯備註')
   if item.administered_date and item.label in ('疫苗施打','疫苗紀錄待確認'):
    saved=c.execute("SELECT administered_date FROM vaccination_records WHERE animal_id=? AND vaccine_type='general' ORDER BY administered_date DESC LIMIT 1",(item.animal_id,)).fetchone()
    if saved and item.administered_date!=saved['administered_date']:
     raise HTTPException(409,'已有疫苗紀錄的施打日期不可直接改寫，請透過紀錄修正程序處理')
   c.execute('UPDATE task_overrides SET note=?,updated_at=CURRENT_TIMESTAMP WHERE animal_id=? AND label=?',(item.note,item.animal_id,item.label))
   return {'animal_id':item.animal_id,'label':item.label,'state':'done','result':previous['result'],'resolved':previous['resolved'],'note':item.note,'edit_report':True}
  if old_state=='done' and item.state=='done':
   # A completed cycle cannot be reported twice, but the existing annual
   # vaccination / new-intake deworming cycle must remain reportable.
   new_cycle=False
   if item.label=='疫苗施打':
    latest=c.execute("SELECT next_due_date FROM vaccination_records WHERE animal_id=? AND vaccine_type='general' ORDER BY administered_date DESC LIMIT 1",(item.animal_id,)).fetchone()
    new_cycle=bool(latest and latest['next_due_date'] and latest['next_due_date']<=WORK_DATE.isoformat())
   elif item.label=='基礎驅蟲':
    current=c.execute('SELECT intake_date FROM animals WHERE id=?',(item.animal_id,)).fetchone()
    new_cycle=bool(current and not c.execute('SELECT 1 FROM deworming_events WHERE animal_id=? AND intake_date=?',(item.animal_id,current['intake_date'])).fetchone())
   if not new_cycle:raise HTTPException(409,'任務已完成；請先重新開啟再回報')
  old_result=previous['result'] if previous else None
  old_resolved=previous['resolved'] if previous else None
  if item.state=='done':
   if item.label=='健康狀態待確認':
    if item.result not in ('healthy','sick','injured'):raise HTTPException(422,'請選擇健康、生病或受傷')
   elif item.label!='優先確認健康狀況' and item.result not in ('yes','no'):raise HTTPException(422,'請選擇是或否')
   if item.label=='優先確認健康狀況' and item.resolved not in ('yes','no'):
    raise HTTPException(422,'請同時回報健康問題是否解決')
  else:
   item.result=old_result
   item.resolved=old_resolved
   item.note=previous['note'] if previous else None
  if item.label in ('疫苗施打','基礎驅蟲') and item.state=='done' and item.result=='no':
   # A negative report is recorded, but the administration task remains pending.
   item.state='pending'
  if item.label=='優先確認健康狀況':
   item.result=None
   if item.state=='done' and item.resolved=='no' and not (item.note or '').strip():raise HTTPException(422,'健康問題未解決時必須填寫追蹤備註')
  column=('health_status' if item.label=='健康狀態待確認' else 'vaccinated' if item.label in ('確認疫苗紀錄','疫苗紀錄待確認','疫苗施打') else 'sterilized' if item.label=='評估絕育安排' else 'dewormed' if item.label in ('確認驅蟲紀錄','基礎驅蟲') else None)
  if column and item.state=='done':
   old=c.execute(f'SELECT {column} FROM animals WHERE id=?',(item.animal_id,)).fetchone()[0]
   c.execute('INSERT OR IGNORE INTO task_animal_baseline VALUES (?,?,?,?)',(item.animal_id,item.label,column,old))
   c.execute(f'UPDATE animals SET {column}=? WHERE id=?',(item.result,item.animal_id))
  elif column and item.state=='pending' and old_state=='done':
   # Restore only when the animal value still matches this task's last report.
   current=c.execute(f'SELECT {column} FROM animals WHERE id=?',(item.animal_id,)).fetchone()[0]
   baseline=c.execute('SELECT old_value FROM task_animal_baseline WHERE animal_id=? AND label=?',(item.animal_id,item.label)).fetchone()
   if baseline and current==old_result:
    c.execute(f'UPDATE animals SET {column}=? WHERE id=?',(baseline['old_value'],item.animal_id))
  if item.label in ('疫苗施打','疫苗紀錄待確認') and item.state=='done' and item.result=='yes':
   if item.label=='疫苗紀錄待確認' and not item.administered_date:raise HTTPException(422,'確認已施打疫苗時，必須填寫可信的實際施打日期')
   try:administered=date.fromisoformat(item.administered_date) if item.administered_date else date.today()
   except (ValueError,TypeError):raise HTTPException(422,'實際疫苗施打日期格式必須為 YYYY-MM-DD')
   if administered>date.today():raise HTTPException(422,'實際施打日期不能晚於今日')
   next_due=month_after(administered,12)
   # Identify records created by this specific task so undo never deletes unrelated vaccine history.
   saved=c.execute('INSERT OR IGNORE INTO vaccination_records(animal_id,vaccine_type,administered_date,next_due_date,source) VALUES (?,?,?,?,?)',(item.animal_id,'general',administered.isoformat(),next_due.isoformat(),f'task:{item.label}'))
   if saved.rowcount:
    c.execute('INSERT INTO task_vaccination_link(animal_id,label,record_id) VALUES (?,?,?) ON CONFLICT(animal_id,label) DO UPDATE SET record_id=excluded.record_id',(item.animal_id,item.label,saved.lastrowid))
  if item.label in ('疫苗施打','疫苗紀錄待確認') and item.state=='pending' and old_state=='done':
   if old_result=='yes':
    # Undo the latest matching administration from this report, including legacy staff_report rows.
    # Never delete imported/other historical vaccination records.
    linked=c.execute('SELECT record_id FROM task_vaccination_link WHERE animal_id=? AND label=?',(item.animal_id,item.label)).fetchone()
    latest=c.execute('SELECT id,next_due_date,source FROM vaccination_records WHERE id=?',(linked['record_id'],)).fetchone() if linked else None
    # Compatibility with reports saved by previous versions, before links existed.
    if not linked:
     latest_report=c.execute("SELECT label FROM task_report_history WHERE animal_id=? AND label IN ('疫苗施打','疫苗紀錄待確認') AND new_state='done' AND new_result='yes' ORDER BY id DESC LIMIT 1",(item.animal_id,)).fetchone()
     if latest_report and latest_report['label']==item.label:
      latest=c.execute("SELECT id,next_due_date,source FROM vaccination_records WHERE animal_id=? AND vaccine_type='general' AND source='staff_report' ORDER BY id DESC LIMIT 1",(item.animal_id,)).fetchone()
    c.execute('DELETE FROM task_vaccination_link WHERE animal_id=? AND label=?',(item.animal_id,item.label))
    if latest:
     c.execute('DELETE FROM vaccination_records WHERE id=?',(latest['id'],))
     # The next annual injection was generated from this now-revoked dose.
     # Remove only that dated cycle; unrelated vaccinations/assignments are retained.
     annual_id=f"{item.animal_id}:疫苗施打@{latest['next_due_date']}"
     for table in ('assignment_snapshot','generated_tasks','task_metadata'):
      c.execute(f'DELETE FROM {table} WHERE task_id=?',(annual_id,))
   elif old_result=='no' and item.label=='疫苗紀錄待確認':
    # A negative check spawned an administration follow-up; retract it only if
    # it is still unfinished and was created by that employee report.
    follow_id=f'{item.animal_id}:疫苗施打'
    meta=c.execute('SELECT source FROM task_metadata WHERE task_id=?',(follow_id,)).fetchone()
    follow=c.execute("SELECT state FROM task_overrides WHERE animal_id=? AND label='疫苗施打'",(item.animal_id,)).fetchone()
    if meta and meta['source']=='employee_report' and (not follow or follow['state']!='done'):
     for table in ('assignment_snapshot','generated_tasks','task_metadata'):
      c.execute(f'DELETE FROM {table} WHERE task_id=?',(follow_id,))
     c.execute("DELETE FROM task_overrides WHERE animal_id=? AND label='疫苗施打' AND state='pending'",(item.animal_id,))
  if item.label=='基礎驅蟲' and item.state=='done' and item.result=='yes':
   intake=c.execute('SELECT intake_date FROM animals WHERE id=?',(item.animal_id,)).fetchone()['intake_date']
   c.execute('INSERT OR IGNORE INTO deworming_events(animal_id,intake_date,completed_date) VALUES (?,?,?)',(item.animal_id,intake,date.today().isoformat()))
  if item.label=='疫苗紀錄待確認' and item.state=='done' and item.result=='no':
   queue_followup(c,item.animal_id,'疫苗施打')
  c.execute('INSERT INTO task_overrides (animal_id,label,state,result,resolved,note,updated_at) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(animal_id,label) DO UPDATE SET state=excluded.state,result=excluded.result,resolved=excluded.resolved,note=excluded.note,updated_at=CURRENT_TIMESTAMP',(item.animal_id,item.label,item.state,item.result,item.resolved,item.note))
  c.execute('INSERT INTO task_report_history (animal_id,label,user_id,old_state,new_state,old_result,new_result,old_resolved,new_resolved) VALUES (?,?,?,?,?,?,?,?,?)',(item.animal_id,item.label,uid,old_state,item.state,old_result,item.result,old_resolved,item.resolved))
  # Reconcile only unstarted auto-generated priority tasks; never rearrange existing assignments.
  if item.label=='健康狀態待確認' and (item.state!='done' or item.result=='healthy'):
   auto=c.execute('SELECT state FROM task_overrides WHERE animal_id=? AND label=?',(item.animal_id,'優先確認健康狀況')).fetchone()
   if not auto or auto['state']!='done':
    c.execute('DELETE FROM generated_tasks WHERE animal_id=? AND label=?',(item.animal_id,'優先確認健康狀況'))
    c.execute('DELETE FROM assignment_snapshot WHERE animal_id=? AND label=?',(item.animal_id,'優先確認健康狀況'))
    c.execute("DELETE FROM task_overrides WHERE animal_id=? AND label='優先確認健康狀況'",(item.animal_id,))
  if item.label=='優先確認健康狀況' and item.state=='done' and item.resolved=='no':
   queue_followup(c,item.animal_id,'健康問題追蹤',item.note or '')
  if item.label=='確認驅蟲紀錄' and item.state=='done' and item.result=='no':
   queue_followup(c,item.animal_id,'基礎驅蟲')
  for source,target,active in [('優先確認健康狀況','健康問題追蹤',item.state=='done' and item.resolved=='no'),('確認驅蟲紀錄','基礎驅蟲',item.state=='done' and item.result=='no')]:
   if item.label==source and not active:
    follow=c.execute('SELECT state FROM task_overrides WHERE animal_id=? AND label=?',(item.animal_id,target)).fetchone()
    if not follow or follow['state']!='done':
     c.execute('DELETE FROM generated_tasks WHERE animal_id=? AND label=?',(item.animal_id,target))
     c.execute('DELETE FROM assignment_snapshot WHERE animal_id=? AND label=?',(item.animal_id,target))
     c.execute("DELETE FROM task_overrides WHERE animal_id=? AND label=? AND state='pending'",(item.animal_id,target))
  if item.state=='done' and item.label=='健康狀態待確認' and item.result in ('sick','injured'):
   # Newly identified sick/injured animals go to the unassigned queue first.
   queue_followup(c,item.animal_id,'優先確認健康狀況')
  c.commit()
 return item.model_dump()

class ResourceRequest(BaseModel):
 profile_id:int=1
 capacity:int=Field(ge=0)
 budget:float=Field(ge=0)
 staff_hours:float=Field(ge=0)
 food_rate:float=Field(ge=0)
 care_minutes:float=Field(ge=0)
 unit_cost:float=Field(ge=0)
 food_stock_kg:float=Field(default=0,ge=0)

def month_after(d,months):
 m=d.month-1+months;y=d.year+m//12;m=m%12+1
 return date(y,m,min(d.day,calendar.monthrange(y,m)[1]))

def build_tasks(animals,overrides=None,include_done=False):
 overrides=overrides or {};tasks=[]
 with connect() as c:
  vaccinations={r['animal_id']:dict(r) for r in c.execute("SELECT v.* FROM vaccination_records v JOIN (SELECT animal_id, MAX(administered_date) AS latest FROM vaccination_records WHERE vaccine_type='general' GROUP BY animal_id) x ON x.animal_id=v.animal_id AND x.latest=v.administered_date")}
  metadata={r['task_id']:dict(r) for r in c.execute('SELECT * FROM task_metadata')}
  task_reports={(r['animal_id'],r['label']):dict(r) for r in c.execute('SELECT * FROM task_overrides')}
  generated_by_animal={}
  for r in c.execute('SELECT animal_id,label FROM generated_tasks'):
   generated_by_animal.setdefault(r['animal_id'],[]).append(r['label'])
  deworm_events={}
  for r in c.execute('SELECT animal_id,intake_date FROM deworming_events'):
   deworm_events.setdefault(r['animal_id'],set()).add(r['intake_date'])
  legacy={(r['animal_id'],r['label']):r['state'] for r in c.execute("SELECT * FROM task_overrides WHERE label IN ('確認驅蟲紀錄','確認疫苗紀錄')")}
 for a in animals:
  defaults=[]
  if a['health_status'] in ('serious','sick','injured'):defaults.append('優先確認健康狀況')
  elif a['health_status']!='healthy':defaults.append('健康狀態待確認')
  vac=vaccinations.get(a['id'])
  if vac:defaults.append('疫苗施打')
  else:defaults.append('疫苗紀錄待確認')
  previous_deworm=deworm_events.get(a['id'],set())
  needs_deworm=a['intake_date'] not in previous_deworm and (bool(previous_deworm) or a['dewormed']!='yes')
  if needs_deworm and (previous_deworm or legacy.get((a['id'],'確認驅蟲紀錄'))!='done'):defaults.append('基礎驅蟲')
  if a['sterilized']!='yes':defaults.append('評估絕育安排')
  extra=[label for label in generated_by_animal.get(a['id'],[]) if label in TASK_CATALOG]+[label for (aid,label),state in overrides.items() if aid==a['id'] and state!='removed' and label in TASK_CATALOG and label not in ('確認驅蟲紀錄','確認疫苗紀錄')]
  for label in dict.fromkeys(defaults+extra):
   state=overrides.get((a['id'],label),'pending')
   if label=='基礎驅蟲' and a['intake_date'] not in deworm_events.get(a['id'],set()) and deworm_events.get(a['id']):state='pending'
   if label=='疫苗施打' and vac:state='pending' # new annual cycle is independent of prior completion
   if state=='removed' or (state=='done' and not include_done):continue
   category,skill,hours,serious=TASK_CATALOG[label]
   task_id=f"{a['id']}:{label}"
   if label=='基礎驅蟲':task_id+=f"@{a['intake_date']}"
   if label=='疫苗施打' and vac:task_id+=f"@{vac['next_due_date']}"
   info=metadata.get(task_id,{})
   due=vac['next_due_date'] if vac and label=='疫苗施打' else (a['intake_date'] if label=='基礎驅蟲' else info.get('due_date'))
   tasks.append({'id':task_id,'animal_id':a['id'],'animal_name':a['name'],'category':category,'skill':skill,'label':label,'hours':hours,'serious':serious,'state':state,'due_date':due,'source':info.get('source','rule'),'is_new':bool(info.get('is_new',False)),'completed_at':(task_reports.get((a['id'],label)) or {}).get('updated_at') if state=='done' else None,'result':(task_reports.get((a['id'],label)) or {}).get('result'),'note':(task_reports.get((a['id'],label)) or {}).get('note'),'priority':1 if label=='健康狀態待確認' else 2 if label=='健康問題追蹤' else 0 if serious else 1 if due and due<WORK_DATE.isoformat() else 2 if due==WORK_DATE.isoformat() else 3 if category=='health' else 4})
 return sorted(tasks,key=lambda t:(t['due_date'] or '9999-12-31',t['priority'],t['animal_id'],t['id']))

def expand_recurring(tasks,days=1):
 return tasks

def quarter(hours):
 return max(1,math.ceil(float(hours)*4-1e-9))

SHELTER_LUNCH = (46,54)  # 11:30–13:30

def shift_break_windows(w):
 begin,end=time_quarter(w['shift_start']),time_quarter(w['shift_end'])
 breaks=[SHELTER_LUNCH]
 if w.get('break_start') and w.get('break_end'):
  breaks.append((time_quarter(w['break_start']),time_quarter(w['break_end'])))
 merged=[]
 for lo,hi in sorted(breaks):
  lo,hi=max(begin,lo),min(end,hi)
  if lo>=hi:continue
  if merged and lo<=merged[-1][1]:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
  else:merged.append((lo,hi))
 return merged

def effective_capacity(w):
 if not w['attending']:return 0
 interval=max(0,time_quarter(w['shift_end'])-time_quarter(w['shift_start']))
 interval-=sum(hi-lo for lo,hi in shift_break_windows(w))
 return max(0,min(math.floor(float(w['available_hours'])*4+1e-9),interval)-math.ceil(float(w['scheduled_hours'])*4-1e-9))

def schedule_fixed(c,work_date):
 return [dict(r) for r in c.execute("SELECT * FROM assignment_snapshot WHERE date=? AND staff_id IS NOT NULL",(work_date,))]

def find_slot(staff, task_quarters, records, work_date, exclude=None):
 cap=effective_capacity(staff)
 existing=[r for r in records if r['staff_id']==staff['id'] and r['task_id']!=exclude]
 used=sum(quarter(r['hours']) for r in existing)
 if used+task_quarters>cap:return None
 # 09:00 start; include an implicit daily shift budget. Existing time ranges are blocked.
 start=time_quarter(staff['shift_start']);end=time_quarter(staff['shift_end'])
 breaks=shift_break_windows(staff)

 for t in range(start,end-task_quarters+1):
  if any(t<hi and t+task_quarters>lo for lo,hi in breaks):continue
  if any(r.get('start_time') and r.get('end_time') and t < time_quarter(r['end_time']) and t+task_quarters>time_quarter(r['start_time']) for r in existing):continue
  # Legacy assigned records with no interval reserve capacity, even before they get scheduled.
  return t
 return None

def time_quarter(value):
 hh,mm=map(int,value.split(':')[:2]);return hh*4+mm//15

def quarter_time(v):return f'{v//4:02d}:{v%4*15:02d}'

def scheduling_priority_weight(task, task_count):
 # Lexicographic tiers: one feasible higher-tier job outweighs ALL lower
 # tier jobs combined, not just a few of them. Manual/finished jobs remain fixed.
 # The factor 10 also preserves the previous ordering inside the ordinary tier.
 base=10*max(1,task_count)+1
 label=task['label']
 if label=='健康狀態待確認':return base**2
 if label=='健康問題追蹤':return base
 if task['serious']:return base**3
 if task['priority']<=2:return 10
 if task['category']=='health':return 4
 return 1

def allocate(tasks,workers,days=1,fixed=None,work_date=None):
 from ortools.sat.python import cp_model
 work_date=work_date or WORK_DATE.isoformat(); fixed=fixed or []
 model=cp_model.CpModel(); edges={}; starts={};ends={};intervals={j:[] for j in range(len(workers))}
 # Reserve manually locked and already completed work, leave it untouched.
 occupied={w['id']:[r for r in fixed if r['staff_id']==w['id']] for w in workers}
 for ti,t in enumerate(tasks):
  length=quarter(t['hours'])
  for wi,w in enumerate(workers):
   if not w['attending'] or t['skill'] not in w['skills']:continue
   cap=effective_capacity(w);shift_start=time_quarter(w['shift_start']);shift_end=time_quarter(w['shift_end'])
   if length>cap or length>shift_end-shift_start:continue
   present=model.NewBoolVar(f'x_{ti}_{wi}')
   start=model.NewIntVar(shift_start,max(shift_start,shift_end-length),f's_{ti}_{wi}')
   end=model.NewIntVar(shift_start+length,shift_end,f'e_{ti}_{wi}')
   model.Add(end==start+length).OnlyEnforceIf(present)
   interval=model.NewOptionalIntervalVar(start,length,end,present,f'i_{ti}_{wi}')
   edges[ti,wi]=present;starts[ti,wi]=start;ends[ti,wi]=end;intervals[wi].append(interval)
 for ti in range(len(tasks)):model.Add(sum(v for (i,_),v in edges.items() if i==ti)<=1)
 for wi,w in enumerate(workers):
  held=occupied[w['id']]
  cap=effective_capacity(w)
  for brs,bre in shift_break_windows(w):
   intervals[wi].append(model.NewIntervalVar(brs,bre-brs,bre,f'break_{wi}_{brs}'))
  model.Add(sum(quarter(tasks[ti]['hours'])*v for (ti,j),v in edges.items() if j==wi)+sum(quarter(r['hours']) for r in held)<=cap)
  for r in held:
   if r.get('start_time') and r.get('end_time'):
    st=time_quarter(r['start_time']);en=time_quarter(r['end_time'])
    intervals[wi].append(model.NewIntervalVar(st,en-st,en,f'fixed_{wi}_{len(intervals[wi])}'))
  model.AddNoOverlap(intervals[wi])
 model.Maximize(sum(v*scheduling_priority_weight(tasks[ti],len(tasks)) for (ti,_),v in edges.items()))
 solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=12;solver.parameters.num_search_workers=max(1,int(os.environ.get("SHELTER_SOLVER_WORKERS","1")))
 status=solver.Solve(model);ok=status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
 selected=[(ti,wi) for (ti,wi),v in edges.items() if ok and solver.Value(v)]
 assigned=[{**tasks[ti],'staff_id':workers[wi]['id'],'staff_name':workers[wi]['name'],'date':work_date,'day_index':0,'start_time':quarter_time(solver.Value(starts[ti,wi])),'end_time':quarter_time(solver.Value(ends[ti,wi])),'duration_minutes':quarter(tasks[ti]['hours'])*15} for ti,wi in selected]
 completed={i for i,_ in selected}
 unassigned=[{**t,'reason':'無符合資格且有空檔的員工','reinforcement_required':bool(t['serious'])} for i,t in enumerate(tasks) if i not in completed]
 return assigned,unassigned,'OPTIMAL' if status==cp_model.OPTIMAL else 'FEASIBLE' if ok else 'NO_SOLUTION'

optimization_lock=threading.Lock()
def resources(p:ResourceRequest):
 if not optimization_lock.acquire(blocking=False):raise HTTPException(409,'已有派工正在執行')
 try:
  with lock:return _resources_locked(p)
 finally:optimization_lock.release()

def _resources_locked(p:ResourceRequest):
 reconcile_completed_followups()
 with connect() as c:
  animals=[row(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1')]
  workers=[staff_row(r) for r in c.execute('SELECT * FROM staff WHERE profile_id=?',(p.profile_id,))]
  profile=c.execute('SELECT * FROM profiles WHERE id=?',(p.profile_id,)).fetchone()
  overrides={(r['animal_id'],r['label']):r['state'] for r in c.execute('SELECT * FROM task_overrides') if r['label'] not in OBSOLETE_TASKS}
 count=len(animals);daily_food,care=resource_totals(animals,p.food_rate,p.care_minutes);cost=count*p.unit_cost
 work_date=WORK_DATE.isoformat()
 with connect() as c:
  existing=schedule_fixed(c,work_date)
  generated_ids={r['task_id'] for r in c.execute('SELECT task_id FROM generated_tasks')}
 tasks=[t for t in build_tasks(animals,overrides) if t['label']!='疫苗施打' or not t['due_date'] or t['due_date']<=work_date]
 # Historical snapshots must retain their original dates. New work gets date-qualified IDs.
 with connect() as c:
  snapshot_dates={r['task_id']:r['date'] for r in c.execute('SELECT task_id,date FROM assignment_snapshot')}
 for t in tasks:
  if t['id'] in snapshot_dates and snapshot_dates[t['id']]!=work_date:
   t['id']=f"{t['id']}@{work_date}"
 # Existing manual assignments are preserved; existing automatic assignments are recalculated.
 fixed=[r for r in existing if r.get('locked') or overrides.get((r['animal_id'],r['label']))=='done']
 tasks=[t for t in tasks if t['id'] not in {r['task_id'] for r in fixed}]
 assigned,unassigned,status=allocate(tasks,[w for w in workers if w['name']!='王助理'],1,fixed,work_date)
 if status not in ('OPTIMAL','FEASIBLE'):raise HTTPException(503,'最佳化未取得可行解，保留原有排程')
 with lock,connect() as c:
  # Only replace unlocked, unfinished assignments for this work date.
  for old in c.execute('SELECT task_id,animal_id,label,locked FROM assignment_snapshot WHERE date=?',(work_date,)).fetchall():
   if old['locked'] or overrides.get((old['animal_id'],old['label']))=='done':continue
   c.execute('UPDATE assignment_snapshot SET staff_id=NULL,staff_name=NULL,start_time=NULL,end_time=NULL WHERE task_id=?',(old['task_id'],))
  for a in assigned:
   c.execute('INSERT INTO assignment_snapshot(task_id,animal_id,animal_name,staff_id,staff_name,category,label,date,hours,start_time,end_time,locked) VALUES (?,?,?,?,?,?,?,?,?,?,?,0) ON CONFLICT(task_id) DO UPDATE SET staff_id=excluded.staff_id,staff_name=excluded.staff_name,date=excluded.date,start_time=excluded.start_time,end_time=excluded.end_time WHERE assignment_snapshot.locked=0',(a['id'],a['animal_id'],a['animal_name'],a['staff_id'],a['staff_name'],a['category'],a['label'],a['date'],a['hours'],a['start_time'],a['end_time']))
   c.execute('INSERT OR IGNORE INTO task_metadata(task_id,source,is_new) VALUES (?,?,0)',(a['id'],'rule'))
   c.execute('UPDATE task_metadata SET is_new=0 WHERE task_id=?',(a['id'],))
  for t in unassigned:
   c.execute('INSERT OR IGNORE INTO assignment_snapshot(task_id,animal_id,animal_name,staff_id,staff_name,category,label,date,hours) VALUES (?,?,?,?,?,?,?,?,?)',(t['id'],t['animal_id'],t['animal_name'],None,None,t['category'],t['label'],work_date,t['hours']))
  # Manual optimization explicitly ends the demonstration reset state.
  c.execute("DELETE FROM demo_ui_state WHERE key='reset_mode'")
  c.commit()
 food_demand=daily_food*7
 care_demand=care*7
 stock=float(profile['food_stock_kg']) if profile else 0
 available_hours=sum(7*effective_capacity(w)/4 for w in workers if w['name']!='王助理')
 resources7={'food_stock_kg':stock,'predicted_food_kg':round(food_demand,2),'food_shortage_kg':round(max(0,food_demand-stock),2),'available_staff_hours':round(available_hours,2),'predicted_care_hours':round(care_demand,2),'care_shortage_hours':round(max(0,care_demand-available_hours),2),'method':f'在養數量情境 × 目前{count}隻個體估算的平均飼料／工時；缺口為規則換算，並非另行訓練的資源需求 ML 模型。'}
 return {'resource_sufficiency_7d':resources7,'planning_start':WORK_DATE.isoformat(),'planning_days':1,'mode':'optimization','current_count':count,'occupancy_rate':round(100*count/p.capacity,1) if p.capacity else None,'daily_food_kg':round(daily_food,2),'daily_care_hours':round(care,2),'daily_cost':round(cost,2),'capacity_gap':max(0,count-p.capacity),'staff_gap_hours':round(max(0,care-p.staff_hours),2),'budget_days':round(p.budget/cost,1) if cost else None,'assignments':assigned,'unassigned':unassigned,'workers':workers,'category_summary':{cat:{'total':sum(t['category']==cat for t in tasks),'assigned':sum(t['category']==cat for t in assigned)} for cat in ['health','admin','adoption']},'optimization':{'solver_status':status,'message':'Google OR-Tools CP-SAT：未完成任務於單日最多指派一次，硬性限制技能、工時與時間重疊；先嚴重健康任務，再健康狀態待確認、健康問題追蹤、一般任務；已鎖定與完成的工作不移動。' },'warnings':['個體飼料與工時為規則式展示估算，非實測；七日試算為當日估算乘以七。','展示人員與任務工時為示範設定，實際部署需由主管核對資格及工作量。']}
def reconcile_completed_followups():
 """Backfill generated tasks from previously saved completed reports.
 Safe to run repeatedly; never deletes or reshuffles existing assignments.
 """
 with lock,connect() as c:
  reports=c.execute("SELECT animal_id,label,result,resolved,note FROM task_overrides WHERE state='done' AND (label='確認驅蟲紀錄' OR label='優先確認健康狀況')").fetchall()
  for r in reports:
   if r['label']=='確認驅蟲紀錄' and r['result']=='no':
    queue_followup(c,r['animal_id'],'基礎驅蟲')
   if r['label']=='優先確認健康狀況' and r['resolved']=='no':
    queue_followup(c,r['animal_id'],'健康問題追蹤',r['note'] or '')

@app.get('/api/staff/assignments')
def staff_assignments(request:Request):
 reconcile_completed_followups()
 uid=request.state.user_id
 with lock,connect() as c:
  # Materialize unscheduled administrative/health work so staff can assign it
  # before running the optimizer, without writing duplicate task records.
  all_animals=[row(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1')]
  current_states={(r['animal_id'],r['label']):r['state'] for r in c.execute('SELECT animal_id,label,state FROM task_overrides')}
  active=build_tasks(all_animals,current_states)
  previous_dates={r['task_id']:r['date'] for r in c.execute('SELECT task_id,date FROM assignment_snapshot')}
  # Do not create a new dated injury-treatment task for each page refresh/day.
  # Without a separate health event ID, existing same-animal histories remain intact.
  historical_treatment={r['animal_id'] for r in c.execute("SELECT animal_id FROM assignment_snapshot WHERE label='優先確認健康狀況'")}
  historical_treatment.update(r['animal_id'] for r in c.execute("SELECT animal_id FROM generated_tasks WHERE label='優先確認健康狀況'"))
  for task in active:
   if task['label']=='疫苗施打' and task.get('due_date') and task['due_date']>WORK_DATE.isoformat():continue
   if task['label']=='優先確認健康狀況' and task['animal_id'] in historical_treatment:continue
   task_id=task['id']
   if task_id in previous_dates and previous_dates[task_id]!=WORK_DATE.isoformat():task_id+=f'@{WORK_DATE.isoformat()}'
   if task_id not in previous_dates:
    c.execute('INSERT OR IGNORE INTO generated_tasks(task_id,animal_id,label) VALUES (?,?,?)',(task_id,task['animal_id'],task['label']))
    is_new=int((task['label']=='疫苗施打' and bool(task.get('due_date')) and task['due_date']<=WORK_DATE.isoformat()) or (task['label'] in ('健康狀態待確認','優先確認健康狀況','健康問題追蹤') and (not task.get('due_date') or task['due_date']<=WORK_DATE.isoformat())))
    c.execute('INSERT OR IGNORE INTO task_metadata(task_id,source,is_new,due_date) VALUES (?,?,?,?)',(task_id,task.get('source','rule'),is_new,task.get('due_date')))
 with connect() as c:
  workers=[staff_row(r) for r in c.execute('SELECT * FROM staff WHERE profile_id=1 ORDER BY id')]
  if uid!=1:
   if uid-2>=len(workers):return {'assignments':[],'planning_start':WORK_DATE.isoformat(),'note':'尚未綁定員工'}
   staff_id=workers[uid-2]['id']
   records=c.execute('SELECT s.* FROM assignment_snapshot s JOIN animals a ON a.id=s.animal_id AND a.is_active=1 WHERE s.staff_id=? ORDER BY s.date,s.start_time,s.task_id',(staff_id,)).fetchall()
  else:records=c.execute('SELECT s.* FROM assignment_snapshot s JOIN animals a ON a.id=s.animal_id AND a.is_active=1 ORDER BY s.date,s.start_time,s.task_id').fetchall()
  overrides={(r['animal_id'],r['label']):r['state'] for r in c.execute('SELECT * FROM task_overrides') if r['label'] not in OBSOLETE_TASKS}
  reports={(r['animal_id'],r['label']):dict(r) for r in c.execute('SELECT * FROM task_overrides')}
  vaccine_dates={}
  for r in c.execute("SELECT animal_id,administered_date FROM vaccination_records WHERE vaccine_type='general' ORDER BY administered_date"):
   vaccine_dates[r['animal_id']]=r['administered_date']
  generated_ids={r['task_id'] for r in c.execute('SELECT task_id FROM generated_tasks')}
  meta={r['task_id']:dict(r) for r in c.execute('SELECT * FROM task_metadata')}
  task_details={t['id']:t for t in build_tasks([row(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1')],overrides,include_done=True)}
  pending_generated=[dict(r) for r in c.execute('SELECT g.task_id,g.animal_id,g.label,g.created_at,a.name AS animal_name,a.dewormed AS animal_dewormed,a.vaccinated AS animal_vaccinated FROM generated_tasks g JOIN animals a ON a.id=g.animal_id AND a.is_active=1 WHERE NOT EXISTS(SELECT 1 FROM assignment_snapshot s WHERE s.task_id=g.task_id)')]
  # Only advertise staff that pass the same shift, skill and capacity checks
  # as manual assignment. Reserved slots and breaks are considered here.
  staff_eligibility={}
  eligible_workers=workers if uid==1 else []
  all_snapshots=[dict(r) for r in c.execute('SELECT * FROM assignment_snapshot WHERE date=?',(WORK_DATE.isoformat(),))]
  snapshot_by_id={r['task_id']:r for r in all_snapshots}
  snapshots_by_worker={w['id']:[] for w in eligible_workers}
  for r in all_snapshots:
   if r['staff_id'] in snapshots_by_worker:snapshots_by_worker[r['staff_id']].append(r)
  slot_cache={}
  def eligible_slot(w,length,exclude=None):
   own=snapshot_by_id.get(exclude)
   exclusion=exclude if own and own['staff_id']==w['id'] else None
   key=(w['id'],length,exclusion)
   if key not in slot_cache:
    slot_cache[key]=find_slot(w,length,snapshots_by_worker[w['id']],WORK_DATE.isoformat(),exclude=exclusion)
   return slot_cache[key]
  for task in task_details.values():
   task_id=task['id']
   snapshot=snapshot_by_id.get(task_id)
   allowed=[]
   if task['label'] in TASK_CATALOG:
    for worker in eligible_workers:
     if not worker['attending'] or TASK_CATALOG[task['label']][1] not in worker['skills']:continue
     w=worker
     if eligible_slot(w,quarter(task['hours']),task_id) is not None:
      allowed.append(worker['id'])
   if snapshot and snapshot['staff_id'] is not None and snapshot['staff_id'] not in allowed:
    # Preserve the existing assignment as a visible option, even if it can no
    # longer receive any new work (e.g. after an availability adjustment).
    allowed.append(snapshot['staff_id'])
   staff_eligibility[task_id]=allowed
  # Include saved tasks even when the current generated task list omits their original rule ID.
  for snapshot in all_snapshots:
   task_id=snapshot['task_id']
   if task_id in staff_eligibility or snapshot['label'] not in TASK_CATALOG:continue
   allowed=[]
   for worker in eligible_workers:
    if not worker['attending'] or TASK_CATALOG[snapshot['label']][1] not in worker['skills']:continue
    w=worker
    if eligible_slot(w,quarter(snapshot['hours']),task_id) is not None:allowed.append(worker['id'])
   if snapshot['staff_id'] is not None and snapshot['staff_id'] not in allowed:allowed.append(snapshot['staff_id'])
   staff_eligibility[task_id]=allowed
  for generated in pending_generated:
   task_id=generated['task_id']
   if task_id in staff_eligibility or generated['label'] not in TASK_CATALOG:continue
   allowed=[]
   for worker in eligible_workers:
    if not worker['attending'] or TASK_CATALOG[generated['label']][1] not in worker['skills']:continue
    w=worker
    if eligible_slot(w,quarter(TASK_CATALOG[generated['label']][2])) is not None:
     allowed.append(worker['id'])
   staff_eligibility[task_id]=allowed
  active_ids={r['id'] for r in c.execute('SELECT id FROM animals WHERE is_active=1')}
  reset_mode=bool(c.execute("SELECT 1 FROM demo_ui_state WHERE key='reset_mode' AND value='1'").fetchone())
  # Distinct injury events cannot be inferred from a matching name alone.
  # Flag the single genuinely current, unhandled entry; retain all historical rows.
  historic_treatment={(r['animal_id'],r['label']) for r in c.execute("SELECT animal_id,label FROM assignment_snapshot WHERE label='優先確認健康狀況'")}
 records=[r for r in records if r['animal_id'] in active_ids and r['label'] not in OBSOLETE_TASKS and (not r['label'].startswith('定期驅蟲（') or overrides.get((r['animal_id'],r['label']))=='done')]
 pending_generated=[g for g in pending_generated if g['label'] not in OBSOLETE_TASKS and not g['label'].startswith('定期驅蟲（')]
 return {'reset_mode':reset_mode,'assignments':[{**dict(r),'state':overrides.get((r['animal_id'],r['label']),'pending'),'result':(reports.get((r['animal_id'],r['label'])) or {}).get('result'),'resolved':(reports.get((r['animal_id'],r['label'])) or {}).get('resolved'),'note':(reports.get((r['animal_id'],r['label'])) or {}).get('note'),'administered_date':vaccine_dates.get(r['animal_id']) if r['label'] in ('疫苗施打','疫苗紀錄待確認') else None,'eligible_staff_ids':staff_eligibility.get(r['task_id'],staff_eligibility.get(r['task_id'].split('@')[0],[])),'duration_minutes':quarter(r['hours'])*15,'work_date':r['date'],'generated':r['task_id'] in generated_ids,'is_new':bool((meta.get(r['task_id']) or {}).get('is_new')) and (r['label']!='優先確認健康狀況' or r['date']==WORK_DATE.isoformat()),'source':(meta.get(r['task_id']) or {}).get('source','rule'),'due_date':(task_details.get(r['task_id']) or task_details.get(r['task_id'].split('@')[0]) or {}).get('due_date'),'priority':(task_details.get(r['task_id']) or {}).get('priority',4)} for r in records]+[{'task_id':g['task_id'],'animal_id':g['animal_id'],'animal_name':g['animal_name'],'label':g['label'],'category':TASK_CATALOG[g['label']][0],'staff_id':None,'staff_name':None,'date':None,'hours':TASK_CATALOG[g['label']][2],'state':reports.get((g['animal_id'],g['label']),{}).get('state','pending'),'result':reports.get((g['animal_id'],g['label']),{}).get('result'),'answer':('未驅蟲' if g['label']=='基礎驅蟲' and g['animal_dewormed']=='no' else '未施打疫苗' if g['label']=='疫苗紀錄待確認' and g['animal_vaccinated']=='no' else None),'resolved':reports.get((g['animal_id'],g['label']),{}).get('resolved'),'note':reports.get((g['animal_id'],g['label']),{}).get('note'),'administered_date':vaccine_dates.get(g['animal_id']) if g['label'] in ('疫苗施打','疫苗紀錄待確認') else None,'generated':True,'eligible_staff_ids':staff_eligibility.get(g['task_id'],[]),'is_new':bool((meta.get(g['task_id']) or {}).get('is_new')) and (g['label']!='優先確認健康狀況' or ('@' not in g['task_id'] and (((g['animal_id'],g['label']) not in historic_treatment) or (meta.get(g['task_id']) or {}).get('source')=='employee_report'))), 'source':(meta.get(g['task_id']) or {}).get('source','employee_report'),'start_time':None,'end_time':None,'work_date':WORK_DATE.isoformat(),'duration_minutes':quarter(TASK_CATALOG[g['label']][2])*15,'due_date':(task_details.get(g['task_id']) or meta.get(g['task_id']) or {}).get('due_date'),'priority':(task_details.get(g['task_id']) or {}).get('priority',4)} for g in pending_generated],'planning_start':WORK_DATE.isoformat(),'note':'單日時間表，任務依日期、重要度、編碼排列；已完成任務保留查閱'}


# Demonstration reset A uses the existing backed-up task-only reset utility.
# Login middleware restricts writes to the manager; confirmation is mandatory.
class DemoResetRequest(BaseModel):
 mode:str='A'
 confirm:str

@app.get('/api/demo/snapshot')
def demo_snapshot():
 from tools.reset_showcase_tasks import reset_demo_tasks
 with lock:
  try:return reset_demo_tasks(DB)
  except (FileNotFoundError,ValueError,sqlite3.Error) as exc:
   raise HTTPException(409,f'重置預覽失敗：{exc}') from exc

@app.post('/api/demo/reset')
@app.post('/api/demo/reset/A')
@app.post('/api/demo/reset/a')
def demo_reset_a(item:DemoResetRequest):
 if item.mode.upper()!='A':raise HTTPException(422,'目前只支援重置 A')
 if item.confirm!='RESET_TASKS':raise HTTPException(422,'請先確認 RESET_TASKS')
 from tools.reset_showcase_tasks import reset_demo_tasks
 with lock:
  try:return reset_demo_tasks(DB,apply=True,confirm=item.confirm)
  except (FileNotFoundError,ValueError,sqlite3.Error) as exc:
   raise HTTPException(409,f'重置失敗：{exc}') from exc

@app.post('/api/tasks/reset-pending')
def reset_tasks_pending():
 """Restore pending states, drop report-generated follow-ups, retain original assignments and reports history."""
 with lock,connect() as c:
  # Restore task-caused animal status only when it still matches the reported value.
  # Independent clinical records (vaccination and deworming events) remain untouched.
  for baseline in c.execute('SELECT animal_id,label,column_name,old_value FROM task_animal_baseline').fetchall():
   column=baseline['column_name']
   if column not in ('health_status','vaccinated','sterilized','dewormed'):continue
   report=c.execute('SELECT result FROM task_overrides WHERE animal_id=? AND label=?',(baseline['animal_id'],baseline['label'])).fetchone()
   animal=c.execute(f'SELECT {column} FROM animals WHERE id=?',(baseline['animal_id'],)).fetchone()
   if report and animal and animal[column]==report['result']:
    c.execute(f'UPDATE animals SET {column}=? WHERE id=?',(baseline['old_value'],baseline['animal_id']))
  c.execute('DELETE FROM task_animal_baseline')
  # Follow-ups from employee reports, not ordinary rules/primary assignments.
  derived=[r['task_id'] for r in c.execute("SELECT task_id FROM task_metadata WHERE source='employee_report'")]
  for task_id in derived:
   c.execute('DELETE FROM assignment_snapshot WHERE task_id=?',(task_id,))
   c.execute('DELETE FROM generated_tasks WHERE task_id=?',(task_id,))
   c.execute('DELETE FROM task_metadata WHERE task_id=?',(task_id,))
  # Also clear report-derived overrides so build_tasks cannot regenerate follow-ups.
  for label in ('優先確認健康狀況','健康問題追蹤'):
   c.execute('DELETE FROM task_overrides WHERE label=? AND NOT EXISTS (SELECT 1 FROM assignment_snapshot s WHERE s.animal_id=task_overrides.animal_id AND s.label=task_overrides.label)',(label,))
  updated=c.execute("UPDATE task_overrides SET state='pending',result=NULL,resolved=NULL,note=NULL,updated_at=CURRENT_TIMESTAMP").rowcount
  c.execute("INSERT INTO demo_ui_state(key,value) VALUES ('reset_mode','1') ON CONFLICT(key) DO UPDATE SET value='1'")
 return {'reset':True,'tasks_reset':updated,'derived_tasks_cleared':len(derived)}

class ReassignRequest(BaseModel):
 staff_id:int
 date:str|None=None
 start_time:str|None=None

def _reassign_in_tx(c,task_id,item):
 task=c.execute('SELECT * FROM assignment_snapshot WHERE task_id=?',(task_id,)).fetchone()
 if not task:
  generated=c.execute('SELECT * FROM generated_tasks WHERE task_id=?',(task_id,)).fetchone()
  if not generated or generated['label'] in OBSOLETE_TASKS:raise HTTPException(404,'找不到任務')
  animal=c.execute('SELECT name FROM animals WHERE id=?',(generated['animal_id'],)).fetchone()
  if not animal:raise HTTPException(404,'找不到動物')
  category,_,hours,_=TASK_CATALOG[generated['label']]
  c.execute('INSERT INTO assignment_snapshot(task_id,animal_id,animal_name,staff_id,staff_name,category,label,date,hours) VALUES (?,?,?,?,?,?,?,?,?)',(task_id,generated['animal_id'],animal['name'],None,None,category,generated['label'],WORK_DATE.isoformat(),hours))
  task=c.execute('SELECT * FROM assignment_snapshot WHERE task_id=?',(task_id,)).fetchone()
 if task['label'] in OBSOLETE_TASKS or task['label'].startswith('定期驅蟲（'):raise HTTPException(404,'此任務已停用')
 state=c.execute('SELECT state FROM task_overrides WHERE animal_id=? AND label=?',(task['animal_id'],task['label'])).fetchone()
 if state and state['state']=='done':raise HTTPException(409,'已完成任務不可指派，請先重新開啟')
 if item.staff_id==0:
  c.execute('UPDATE assignment_snapshot SET staff_id=NULL,staff_name=NULL,start_time=NULL,end_time=NULL,locked=1 WHERE task_id=?',(task_id,))
  return {'task_id':task_id,'staff_id':None,'status':'unassigned'}
 staff=c.execute('SELECT * FROM staff WHERE id=?',(item.staff_id,)).fetchone()
 if not staff or not staff['attending']:raise HTTPException(422,'員工不存在或未出勤')
 if staff['name']=='王助理':raise HTTPException(422,'專責飼料管理員不可派此類任務')
 catalog=TASK_CATALOG.get(task['label'])
 if not catalog or catalog[1] not in json.loads(staff['skills']):raise HTTPException(422,'員工不具備任務技能資格')
 target_date=item.date or WORK_DATE.isoformat()
 try:date.fromisoformat(target_date)
 except (ValueError,TypeError):raise HTTPException(422,'日期必須為 YYYY-MM-DD')
 if target_date!=WORK_DATE.isoformat():raise HTTPException(422,'目前僅支援目標工作日單日派工')
 rows=[dict(r) for r in c.execute('SELECT * FROM assignment_snapshot WHERE date=? AND staff_id=? AND task_id<>?',(target_date,item.staff_id,task_id))]
 w=staff_row(staff);length=quarter(task['hours'])
 if sum(quarter(r['hours']) for r in rows)+length>effective_capacity(w):raise HTTPException(409,'超過員工當日可用工時上限')
 if item.start_time:
  try:
   start=time_quarter(item.start_time)
   if quarter_time(start)!=item.start_time:raise ValueError()
  except (ValueError,TypeError):raise HTTPException(422,'開始時間必須為 15 分鐘整點 HH:MM')
  if start<time_quarter(w['shift_start']) or start+length>time_quarter(w['shift_end']):raise HTTPException(409,'任務超出員工工作時段')
  if any(start<hi and start+length>lo for lo,hi in shift_break_windows(w)):raise HTTPException(409,'任務與休息時間重疊')
  if any(r['start_time'] and start<time_quarter(r['end_time']) and start+length>time_quarter(r['start_time']) for r in rows):raise HTTPException(409,'與員工既有任務時間重疊')
 else:
  slot=find_slot(w,length,rows,target_date)
  if slot is None:raise HTTPException(409,'沒有足夠且不重疊的可用時段')
  start=slot
 c.execute('UPDATE assignment_snapshot SET staff_id=?,staff_name=?,date=?,start_time=?,end_time=?,locked=1 WHERE task_id=?',(staff['id'],staff['name'],target_date,quarter_time(start),quarter_time(start+length),task_id))
 c.execute('INSERT OR IGNORE INTO task_metadata(task_id,source,is_new) VALUES (?,?,0)',(task_id,'manual'))
 c.execute('UPDATE task_metadata SET is_new=0 WHERE task_id=?',(task_id,))
 return {'task_id':task_id,'staff_id':item.staff_id,'date':target_date,'start_time':quarter_time(start),'end_time':quarter_time(start+length),'status':'assigned'}

@app.patch('/api/staff/assignments/{task_id:path}')
def reassign_task(task_id:str,item:ReassignRequest):
 with lock,connect() as c:
  return _reassign_in_tx(c,task_id,item)

class BatchRequest(BaseModel):
 task_ids:list[str]=Field(min_length=1)
 staff_id:int

@app.post('/api/staff/assignments/batch')
def batch_reassign(item:BatchRequest):
 if len(set(item.task_ids))!=len(item.task_ids):raise HTTPException(422,'批次任務不可重複')
 with lock,connect() as c:
  results=[]
  for task_id in item.task_ids:
   results.append(_reassign_in_tx(c,task_id,ReassignRequest(staff_id=item.staff_id)))
  return {'results':results,'count':len(results)}

@app.get('/api/model/evaluation')
def evaluation():
 # Only genuine saved evaluation data; do not invent health/adoption metrics.
 targets=occupancy_metrics.get('targets',{});models={}
 if targets:models['occupancy_catboost']={'status':'evaluated','metrics':[{'target':k,**v.get('test_metrics',{})} for k,v in targets.items()],'method':occupancy_metrics.get('evaluation')}
 return {'models':models,'note':'只顯示 ZIP 中可核對的已保存評估數值；其他模型已載入但未提供可核對的評估檔。'}


# Stage 2 API is isolated from the existing React layout and occupancy dashboard.
@app.get('/api/stage2/animal/{animal_id}/risks')
def stage2_animal_risks(animal_id:int,days:int=30,as_of_date:date|None=None):
 from stage2_service import animal_probabilities
 if not 1<=days<=30:raise HTTPException(422,'前端只支援 1–30 天')
 try:return animal_probabilities(get_animal(animal_id),as_of_date or date.today(),days)
 except (ValueError,FileNotFoundError) as exc:raise HTTPException(422,str(exc)) from exc

@app.get('/api/stage2/counts')
def stage2_counts(days:int=30,species:str|None=None):
 from stage2_service import predict_counts
 if not 1<=days<=30:raise HTTPException(422,'前端只支援 1–30 天')
 try:return {'mode':'trained_catboost_recursive','forecast':predict_counts(days,species),'warning':'測試指標是單步預測；遞迴多日誤差尚未獨立驗證'}
 except (ValueError,FileNotFoundError) as exc:raise HTTPException(503,str(exc)) from exc

@app.get('/api/stage2/evaluation')
def stage2_evaluation(cause:str|None=None,species:str|None=None,days:int=30):
 from stage2_service import metrics_report
 if not 1<=days<=30:raise HTTPException(422,'只能查詢 1–30 天')
 return metrics_report(cause,species,days)

class Stage2Question(BaseModel):
 question:str=Field(min_length=1,max_length=1000)
 species:str|None=None
 cause:str='adoption'
 days:int=Field(default=30,ge=1,le=30)

@app.post('/api/stage2/answer')
def stage2_answer(body:Stage2Question):
 """Structured, auditable answer for future chat integration; not a generative AI response."""
 from stage2_service import metrics_report
 report=metrics_report(body.cause,body.species,body.days)
 light=report.get('lightgbm',{});rows=light.get('metrics',[])
 chosen=rows[0] if rows else None
 messages=['統計指標來自現有輸出檔案，非模型即時預測值。']
 if chosen:
  messages.append(f"{body.cause} 原因的獨立測試 C-index：{chosen.get('cause_specific_c_index')}（風險排序能力，非準確率）；IBS：{chosen.get('integrated_brier_score')}（離散時間點積分近似，越低通常越好，須與基準模型比較）。")
  messages.append(f"{body.days} 天校準分組：{len(light.get('calibration',[]))} 組；需同時比較各組 predicted、observed 和 n。")
 else:messages.append('找不到對應離所原因的測試指標，不提供推測數值。')
 for target,detail in report.get('catboost',{}).items():
  values=detail.get('species_test') if body.species else None
  metrics=(values or [detail['overall_test']])[0]
  messages.append(f"CatBoost {target} 測試 MAE={metrics.get('MAE')}, RMSE={metrics.get('RMSE')}, WAPE={metrics.get('WAPE')}%；屬單步測試，不能解讀成準確率。")
 messages.extend(report['warnings'])
 return {'question':body.question,'model_explanation':'\n'.join(messages),'evaluation':report,'note':'此端點只提供可稽核的模型表現敘述；預測值請從 /api/stage2/animal/{id}/risks、/api/stage2/counts 或 /api/resources/needs-forecast 取得。'}


from weekly_schedule import mount as mount_weekly_schedule
app.include_router(mount_weekly_schedule(sys.modules[__name__]))
from photo_analysis import PhotoAnalysisInput, analyze_input

@app.post('/api/photos/analysis')
def analyze_animal_photo(body:PhotoAnalysisInput, request:Request):
 if request.state.user_id!=1:raise HTTPException(403,'僅管理者可辨識建檔照片')
 return analyze_input(connect,body,'intake')

from ai_tools import mount as mount_ai_tools
app.include_router(mount_ai_tools(sys.modules[__name__]))

@app.post('/api/resources/optimize', deprecated=True)
def optimize_week_alias(week:date|None=None):
 target=week or datetime.now(ZoneInfo('Asia/Taipei')).date()
 return RedirectResponse(f'/api/schedule/preview?week={target.isoformat()}',status_code=307)
