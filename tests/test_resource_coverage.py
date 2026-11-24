"""Integration coverage for the 80 active animals in the shipped SQLite."""
from __future__ import annotations
import math
import sqlite3
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from stage2_service import resource_forecast, resource_table, resource_rate_for_animal

class TestResourceCoverage(unittest.TestCase):
    def test_all_active_animals_get_conditioned_30_day_forecast(self):
        with sqlite3.connect(ROOT/'backend/showcase.sqlite3') as c:
            c.row_factory=sqlite3.Row
            rows=[dict(r) for r in c.execute('SELECT * FROM animals WHERE is_active=1 ORDER BY id')]
        self.assertEqual(len(rows),80,'原始 SQLite 應有 80 隻有效在所動物')
        forecast=resource_forecast(rows,date(2026,10,22),30,simulations=30)
        self.assertEqual(forecast['animal_count'],80)
        self.assertEqual(forecast['estimated_animals'],80)
        self.assertEqual(len(forecast['individual_predictions']),80)
        self.assertEqual({p['animal_id'] for p in forecast['individual_predictions']},{a['id'] for a in rows})
        for pred in forecast['individual_predictions']:
            self.assertEqual(len(pred['conditional_survival_by_day']),30)
            self.assertTrue(all(math.isfinite(p) and 0<=p<=1 for p in pred['conditional_survival_by_day']))
            self.assertTrue(all(a>=b for a,b in zip(pred['conditional_survival_by_day'],pred['conditional_survival_by_day'][1:])))
            self.assertGreater(pred['food_kg_per_day'],0)
            self.assertGreater(pred['care_hours_per_day'],0)
        self.assertTrue(any(p['days_in_shelter']>300 for p in forecast['individual_predictions']))
        self.assertTrue(any(p['tail_extrapolated'] for p in forecast['individual_predictions']))
        self.assertEqual(forecast['start_date'],'2026-10-23')

    def test_missing_resource_crosswalk_is_explicit_error(self):
        animal={'id':1234,'species':'unsupported_species','intake_date':'2026-10-01'}
        with self.assertRaisesRegex(ValueError,'1234'):
            resource_rate_for_animal(animal,resource_table())

if __name__=='__main__':unittest.main()
