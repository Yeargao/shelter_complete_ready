import os
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import ai_tools

class AIToolsTests(unittest.TestCase):
    def test_synonym_fallback(self):
        records=[{'text':'狗狗走路困難，跛行'},{'text':'疫苗施打完成'}]
        with patch.dict(os.environ,{'SHELTER_TEXT_MODEL_DIR':'','SHELTER_AI_NOTES_APPROVED':'0'}):
            result=ai_tools.rank_notes(None,'行動不便',records)
        self.assertEqual(result['mode'],'local_lexical')
        self.assertEqual(result['results'][0]['text'],records[0]['text'])

    def test_scope_and_open_issues(self):
        db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE animals(id INTEGER,name TEXT);
            CREATE TABLE weekly_tasks(task_id TEXT,animal_id INTEGER,label TEXT,staff_id INTEGER,day TEXT,earliest TEXT);
            CREATE TABLE weekly_reports(task_id TEXT,note TEXT,reported_at TEXT);
            CREATE TABLE weekly_issues(task_id TEXT,note TEXT,resolved_at TEXT);
            INSERT INTO animals VALUES(1,'A'),(2,'B');
            INSERT INTO weekly_tasks VALUES('t1',1,'健康',11,'2026-11-26','2026-11-26'),('t2',2,'健康',22,'2026-11-26','2026-11-26');
            INSERT INTO weekly_reports VALUES('t1','跛行','2026-11-26'),('t2','私有備註','2026-11-26');
            INSERT INTO weekly_issues VALUES('t1','跛行',NULL);
        """)
        self.assertEqual([r['task_id'] for r in ai_tools.collect_notes(db,11)],['t1'])
        self.assertEqual(ai_tools.collect_notes(db,22,True),[])
        self.assertEqual(ai_tools.collect_notes(db,11,True)[0]['text'],'跛行')

    def test_audit_is_read_only(self):
        db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE animals(id INTEGER,name TEXT,is_active INTEGER,species TEXT,health_status TEXT,vaccinated TEXT,dewormed TEXT,intake_date TEXT,food_grams_per_day REAL,routine_care_hours_per_day REAL);
            CREATE TABLE vaccination_records(animal_id INTEGER,administered_date TEXT);
            CREATE TABLE deworming_events(animal_id INTEGER,intake_date TEXT);
            CREATE TABLE weekly_issues(animal_id INTEGER,resolved_at TEXT);
            INSERT INTO animals VALUES(1,'A',1,'dog','healthy','yes','yes','2020-01-01',100,1);
            INSERT INTO weekly_issues VALUES(1,NULL);
        """)
        before=db.total_changes
        findings,groups=ai_tools.audit(db)
        self.assertEqual(len(findings),3)
        self.assertEqual(groups,0)
        self.assertEqual(before,db.total_changes)

    def test_image_signature_identical(self):
        from PIL import Image
        def raw(color):
            b=BytesIO();Image.new('RGB',(30,30),color).save(b,format='PNG');return b.getvalue()
        a=ai_tools.image_signature(raw('red'))
        b=ai_tools.image_signature(raw('blue'))
        self.assertAlmostEqual(ai_tools.visual_score(a,a),1)
        self.assertLess(ai_tools.visual_score(a,b),1)

if __name__=='__main__':
    unittest.main()
