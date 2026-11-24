"""Test destructive demo-reset ONLY against a temporary SQLite copy."""
from __future__ import annotations
import sqlite3
import tempfile
import shutil
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'/'tools'))
from reset_showcase_tasks import reset_demo_tasks

class TestTaskDemoReset(unittest.TestCase):
    def test_preview_and_confirmed_reset_preserve_business_data(self):
        with tempfile.TemporaryDirectory() as td:
            test_db=Path(td)/'copy.sqlite3'
            shutil.copy2(ROOT/'backend'/'showcase.sqlite3',test_db)
            with sqlite3.connect(test_db) as c:
                # Fingerprint animals/staff and real medical records.
                baseline={table:c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                          for table in ('animals','staff','vaccination_records','deworming_events')}
            preview=reset_demo_tasks(test_db)
            self.assertEqual(preview['mode'],'dry_run')
            self.assertGreater(preview['counts_before']['assignment_snapshot'],0)
            with self.assertRaises(ValueError):reset_demo_tasks(test_db,apply=True)
            result=reset_demo_tasks(test_db,apply=True,confirm='RESET_TASKS')
            self.assertEqual(result['mode'],'reset_applied')
            self.assertTrue(Path(result['backup']).is_file())
            with sqlite3.connect(test_db) as c:
                self.assertEqual(c.execute("SELECT value FROM demo_ui_state WHERE key='reset_mode'").fetchone()[0],'1')
                for t in ('assignment_snapshot','task_overrides','task_report_history', 'generated_tasks','task_metadata','task_animal_baseline'):
                    self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0],0,t)
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])
                for table,n in baseline.items():self.assertEqual(c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],n,table)
            with sqlite3.connect(result['backup']) as c:
                self.assertGreater(c.execute('SELECT COUNT(*) FROM assignment_snapshot').fetchone()[0],0)
                self.assertGreater(c.execute('SELECT COUNT(*) FROM task_report_history').fetchone()[0],0)

if __name__=='__main__':unittest.main()
