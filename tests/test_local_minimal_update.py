"""Focused regression tests; only a temporary copy of SQLite is ever written."""
import importlib.util
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]


class LocalUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        backend=cls.root/'backend'
        backend.mkdir()
        for filename in ('main.py','stage2_service.py','daily_history.csv','showcase.sqlite3'):
            shutil.copy2(ROOT/'backend'/filename,backend/filename)
        shutil.copytree(ROOT/'models',cls.root/'models')
        # Saved model inputs are read-only; they are not changed by these tests.
        shutil.copytree(ROOT/'stage2_training',cls.root/'stage2_training')
        try:
            from ortools.sat.python import cp_model  # noqa: F401
            cls.fake_solver=False
        except ImportError:
            # Test only non-solver endpoints. This stub is NEVER used to run CP-SAT.
            cls.fake_solver=True
            cls.module_restore={name:sys.modules.get(name) for name in ('ortools','ortools.sat','ortools.sat.python','ortools.sat.python.cp_model')}
            for name in cls.module_restore:sys.modules[name]=types.ModuleType(name)
            sys.modules['ortools.sat.python'].cp_model=sys.modules['ortools.sat.python.cp_model']
        cls.original_path=list(sys.path)
        sys.path.insert(0,str(backend))
        spec=importlib.util.spec_from_file_location('isolated_local_minimal_update',backend/'main.py')
        cls.module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=cls.module
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        sys.path[:]=cls.original_path
        sys.modules.pop('isolated_local_minimal_update',None)
        if cls.fake_solver:
            for name,previous in cls.module_restore.items():
                if previous is None:sys.modules.pop(name,None)
                else:sys.modules[name]=previous
        cls.temp.cleanup()

    def test_same_injury_not_regenerated_on_refresh(self):
        m=self.module
        req=SimpleNamespace(state=SimpleNamespace(user_id=1))
        with m.connect() as c:
            baseline=c.execute("SELECT COUNT(*) FROM generated_tasks WHERE label='優先確認健康狀況'").fetchone()[0]
        first=m.staff_assignments(req)
        second=m.staff_assignments(req)
        with m.connect() as c:
            afterwards=c.execute("SELECT COUNT(*) FROM generated_tasks WHERE label='優先確認健康狀況'").fetchone()[0]
        self.assertEqual(baseline,afterwards)
        self.assertEqual(len(first['assignments']),len(second['assignments']))
        self.assertFalse(any(a['is_new'] for a in second['assignments'] if a['label']=='優先確認健康狀況' and a['date'] and a['date']!=m.WORK_DATE.isoformat()))

    def test_completed_report_note_update_is_in_place(self):
        m=self.module
        req=SimpleNamespace(state=SimpleNamespace(user_id=1))
        with m.connect() as c:
            prior=c.execute("SELECT * FROM task_overrides WHERE state='done' AND (label='優先確認健康狀況' OR result IN ('yes','no','healthy','sick','injured')) LIMIT 1").fetchone()
            self.assertIsNotNone(prior)
            original=dict(prior)
            counts={table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('generated_tasks','assignment_snapshot','task_overrides','vaccination_records','deworming_events','task_report_history')}
        value='回歸測試：更新已儲存備註'
        body=m.TaskChange(animal_id=original['animal_id'],label=original['label'],state='done',result=original['result'],resolved=original['resolved'],note=value,edit_report=True)
        out=m.change_task(body,req)
        self.assertTrue(out['edit_report'])
        with m.connect() as c:
            after=dict(c.execute('SELECT * FROM task_overrides WHERE animal_id=? AND label=?',(original['animal_id'],original['label'])).fetchone())
            self.assertEqual(after['note'],value)
            self.assertEqual(after['state'],'done')
            self.assertEqual(after['result'],original['result'])
            self.assertEqual(after['resolved'],original['resolved'])
            for table,count in counts.items():self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],count,table)
        m.change_task(m.TaskChange(animal_id=original['animal_id'],label=original['label'],state='done',result=original['result'],resolved=original['resolved'],note='第二次更新',edit_report=True),req)
        with m.connect() as c:self.assertEqual(c.execute('SELECT note FROM task_overrides WHERE animal_id=? AND label=?',(original['animal_id'],original['label'])).fetchone()[0],'第二次更新')

    def test_medical_result_change_is_rejected(self):
        m=self.module
        req=SimpleNamespace(state=SimpleNamespace(user_id=1))
        with m.connect() as c:
            r=c.execute("SELECT animal_id,label,result,resolved FROM task_overrides WHERE state='done' AND result IN ('yes','no') LIMIT 1").fetchone()
        self.assertIsNotNone(r)
        new='no' if r['result']=='yes' else 'yes'
        with self.assertRaises(m.HTTPException) as error:
            m.change_task(m.TaskChange(animal_id=r['animal_id'],label=r['label'],state='done',result=new,resolved=r['resolved'],note='不改變判定',edit_report=True),req)
        self.assertEqual(error.exception.status_code,409)

    def test_stage2_metrics_still_use_saved_files(self):
        from stage2_service import metrics_report
        # Uses the real Stage 2 metrics, not placeholder data.
        report=metrics_report(horizon=30)
        self.assertEqual(len(report['lightgbm']['metrics']),5)
        self.assertIn('MAE',report['catboost']['exit_count']['overall_test'])
        self.assertEqual(len(report['lightgbm']['calibration']),25)


if __name__=='__main__':unittest.main()
