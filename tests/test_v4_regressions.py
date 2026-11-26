"""Standalone tests: no FastAPI, OR-Tools or live SQLite required."""
import ast
from contextlib import closing
import math
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'backend/main.py'

class SchedulingRulesTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
  names={'quarter','time_quarter','shift_break_windows','effective_capacity','find_slot'}
  scope={'math':math}
  nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
  nodes.extend(node for node in tree.body if isinstance(node,ast.Assign)
               and any(isinstance(target,ast.Name) and target.id=='SHELTER_LUNCH' for target in node.targets))
  exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),scope)
  cls.functions=scope

 def test_ineligible_skill_and_no_time(self):
  f=self.functions
  staff={'id':1,'attending':True,'skills':['health:observation'],'shift_start':'09:00','shift_end':'10:00','break_start':None,'break_end':None,'available_hours':1,'scheduled_hours':0,'weekly_hours':40}
  self.assertNotIn('health:veterinary',staff['skills'])
  self.assertIsNotNone(f['find_slot'](staff,2,[], '2026-11-15'))
  occupied=[{'task_id':'existing','staff_id':1,'hours':1,'start_time':'09:00','end_time':'10:00'}]
  self.assertIsNone(f['find_slot'](staff,1,occupied,'2026-11-15'))

 def test_break_time(self):
  f=self.functions
  staff={'id':1,'attending':True,'shift_start':'09:00','shift_end':'10:00','break_start':'09:15','break_end':'09:45','available_hours':1,'scheduled_hours':0,'weekly_hours':40}
  self.assertIsNone(f['find_slot'](staff,2,[], '2026-11-15'))

 def test_demo_seed_is_82(self):
  text=SOURCE.read_text(encoding='utf-8')
  self.assertIn('for i in range(82):',text)

class DemoRosterTest(unittest.TestCase):
 def test_safe_80_to_82(self):
  with tempfile.TemporaryDirectory() as td:
   db=Path(td)/'roster.db'
   with closing(sqlite3.connect(db)) as c, c:
    c.execute('CREATE TABLE animals(id INTEGER PRIMARY KEY, name TEXT, species TEXT, breed TEXT, age_months INTEGER,sex TEXT,health_status TEXT,vaccinated TEXT,sterilized TEXT,dewormed TEXT,intake_date TEXT,is_active INTEGER)')
    c.executemany('INSERT INTO animals(id,name,health_status,is_active) VALUES (?,?,?,1)',[(i,f'A{i}','healthy') for i in range(1,81)])
   script=ROOT/'backend/tools/set_demo_roster_82.py'
   preview=subprocess.run([sys.executable,str(script),'--db',str(db)],capture_output=True,text=True)
   self.assertEqual(preview.returncode,0,preview.stderr)
   with closing(sqlite3.connect(db)) as c, c:self.assertEqual(c.execute('SELECT COUNT(*) FROM animals WHERE is_active=1').fetchone()[0],80)
   run=subprocess.run([sys.executable,str(script),'--db',str(db),'--apply'],capture_output=True,text=True)
   self.assertEqual(run.returncode,0,run.stderr)
   with closing(sqlite3.connect(db)) as c, c:
    self.assertEqual(c.execute('SELECT COUNT(*) FROM animals WHERE is_active=1').fetchone()[0],82)
    self.assertEqual(c.execute('SELECT COUNT(*) FROM animals WHERE id<=80').fetchone()[0],80)

if __name__=='__main__':unittest.main()
