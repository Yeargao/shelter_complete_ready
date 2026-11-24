"""Safe archival should never delete or overwrite prior animal records."""
import contextlib
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'backend' / 'tools' / 'limit_demo_animals.py'
spec = importlib.util.spec_from_file_location('limit_demo_animals', MODULE)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)

class ArchiveTest(unittest.TestCase):
    def test_preview_and_archive_with_review_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            archive.DB = Path(folder) / 'showcase.sqlite3'
            with sqlite3.connect(archive.DB) as db:
                db.execute('CREATE TABLE animals(id INTEGER PRIMARY KEY, name TEXT, health_status TEXT, is_active INTEGER DEFAULT 1)')
                db.executemany('INSERT INTO animals VALUES (?,?,?,1)', [(1, 'Healthy', 'healthy'), (2, 'Needs review', 'needs_review'), (3, 'Healthy 2', 'healthy')])
            with patch.object(sys, 'argv', ['archive', '--limit', '2']), contextlib.redirect_stdout(io.StringIO()):
                archive.main()
            with sqlite3.connect(archive.DB) as db:
                self.assertEqual(db.execute('SELECT SUM(is_active) FROM animals').fetchone()[0], 3)
            with patch.object(sys, 'argv', ['archive', '--limit', '2', '--apply']), contextlib.redirect_stdout(io.StringIO()):
                archive.main()
            with sqlite3.connect(archive.DB) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM animals').fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT SUM(is_active) FROM animals').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT is_active FROM animals WHERE id=2').fetchone()[0], 0)
            self.assertEqual(len(list(Path(folder).glob('*.bak'))), 1)

if __name__ == '__main__': unittest.main()
