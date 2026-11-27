"""Focused tests of deterministic helpers; run against a disposable in-memory DB."""
import sqlite3
import unittest
from smart_tools import migrate, scan, candidates, report

class SmartToolsTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE profiles(id INTEGER,food_stock_kg REAL)')
        self.db.execute('INSERT INTO profiles VALUES(1,20)')
        self.db.execute('CREATE TABLE animals(id INTEGER,name TEXT,is_active INTEGER,health_status TEXT,species TEXT)')
        self.db.execute("INSERT INTO animals VALUES (1,'A',1,'unknown','dog'),(2,'B',0,'healthy','cat')")
        self.db.execute('CREATE TABLE weekly_events(id INTEGER,animal_id INTEGER,event TEXT)')
        migrate(self.db)
    def tearDown(self):
        self.db.close()
    def test_reminder_idempotent_and_rearm(self):
        self.db.execute("INSERT INTO smart_rules VALUES ('r','stock',30)")
        first=scan(self.db)
        self.assertEqual(len(first),1)
        self.assertEqual(scan(self.db)[0]['id'],first[0]['id'])
        self.db.execute("UPDATE smart_inbox SET state='ack'")
        self.assertEqual(scan(self.db),[])
        self.db.execute("UPDATE profiles SET food_stock_kg=40")
        self.assertEqual(scan(self.db),[])
        self.db.execute("UPDATE profiles SET food_stock_kg=10")
        self.assertNotEqual(scan(self.db)[0]['id'],first[0]['id'])
    def test_current_health_excludes_exited(self):
        self.assertEqual(report(self.db,'health','2026-11-01','2026-11-28')['rows'],[{'label':'unknown','value':1}])
    def test_stock_strict_threshold(self):
        self.assertEqual(candidates(self.db,'stock',20,'2026-11-28'),[])

if __name__=='__main__':
    unittest.main()
