"""Run: python -m unittest discover -s tests -v (from project root)."""
import importlib.util
import sqlite3
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE=Path(__file__).resolve().parents[1] / 'backend' / 'main.py'

class SchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        root=Path(cls.temp.name)
        (root/'backend').mkdir()
        shutil.copyfile(SOURCE,root/'backend/main.py')
        spec=importlib.util.spec_from_file_location('isolated_shelter_schedule_tests',root/'backend/main.py')
        cls.mod=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=cls.mod
        spec.loader.exec_module(cls.mod)

    @classmethod
    def tearDownClass(cls):
        # SQLite connections created by main.connect() are closed on every exit.
        cls.temp.cleanup()
        sys.modules.pop('isolated_shelter_schedule_tests', None)

    def test_connection_closed_after_context(self):
        m=self.mod
        with m.connect() as c:
            db_path=m.DB
            self.assertEqual(c.execute('SELECT 1').fetchone()[0],1)
        with self.assertRaises(sqlite3.ProgrammingError):
            c.execute('SELECT 1')
        self.assertTrue(db_path.is_file())

    def test_migration_upgrades_legacy_vaccination_table(self):
        migration=SOURCE.parent / 'migrations' / '20261115_daily_schedule.py'
        spec=importlib.util.spec_from_file_location('isolated_shelter_migration', migration)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        db=Path(self.temp.name)/'old-schema.sqlite3'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE vaccination_records (id INTEGER PRIMARY KEY,animal_id INTEGER NOT NULL, notes TEXT)')
            c.execute('INSERT INTO vaccination_records(animal_id,notes) VALUES (1,?)',('old record',))
            c.execute('CREATE TABLE assignment_snapshot (task_id TEXT PRIMARY KEY)')
            c.execute('CREATE TABLE staff (id INTEGER PRIMARY KEY)')
        module.migrate(db)
        module.migrate(db)
        with sqlite3.connect(db) as c:
            cols={r[1] for r in c.execute('PRAGMA table_info(vaccination_records)')}
            self.assertIn('administered_date',cols)
            self.assertEqual(c.execute('SELECT notes,administered_date FROM vaccination_records').fetchone(),('old record',None))

    def test_round_up_quarters(self):
        m=self.mod
        self.assertEqual(m.quarter(0.30),2)
        self.assertEqual(m.quarter(8),32)
        self.assertEqual(m.quarter_time(37),'09:15')

    def test_leap_year_date(self):
        m=self.mod
        self.assertEqual(m.month_after(m.date(2024,2,29),12).isoformat(),'2025-02-28')

    def test_solver_hard_capacity_and_no_overlap(self):
        m=self.mod
        tasks=[dict(id=str(i),label='基礎驅蟲',animal_id=i,animal_name=str(i),category='health',skill='health:observation',hours=0.5,serious=False,priority=4) for i in range(10)]
        workers=[dict(id=1,name='測試員工',skills=['health:observation'],available_hours=2,scheduled_hours=0,weekly_hours=40,attending=True,shift_start='09:00',shift_end='17:00',break_start=None,break_end=None)]
        assigned,unassigned,_=m.allocate(tasks,workers,1,[],m.WORK_DATE.isoformat())
        self.assertEqual(len(assigned),4)
        self.assertEqual(len(unassigned),6)
        ranges=sorted((m.time_quarter(t['start_time']),m.time_quarter(t['end_time'])) for t in assigned)
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(ranges,ranges[1:])))

    def test_manual_reassign_hard_limit(self):
        m=self.mod
        with m.connect() as c:
            a=c.execute('SELECT id,name FROM animals LIMIT 1').fetchone()
            w=c.execute("SELECT * FROM staff WHERE skills LIKE '%observation%' AND attending=1 LIMIT 1").fetchone()
            c.execute('UPDATE staff SET available_hours=0.5,scheduled_hours=0 WHERE id=?',(w['id'],))
            for i in range(2):
                c.execute('INSERT INTO assignment_snapshot(task_id,animal_id,animal_name,category,label,date,hours) VALUES (?,?,?,?,?,?,?)',(f'test-{i}',a['id'],a['name'],'health','基礎驅蟲',m.WORK_DATE.isoformat(),0.5))
            m._reassign_in_tx(c,'test-0',m.ReassignRequest(staff_id=w['id']))
            with self.assertRaises(m.HTTPException) as problem:
                m._reassign_in_tx(c,'test-1',m.ReassignRequest(staff_id=w['id']))
            self.assertEqual(problem.exception.status_code,409)

if __name__=='__main__':unittest.main()
