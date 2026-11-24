"""Read-only integration checks for shipped model/data artifacts."""
import sqlite3
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from stage2_service import animal_probabilities, resource_forecast, metrics_report


class TestStage2Integration(unittest.TestCase):
    def test_arbitrary_age_competing_risks(self):
        animal = {'id': 999, 'intake_date': '2024-01-01', 'species': 'cat',
                  'breed': 'domestic shorthair', 'age_months': 36,
                  'health_status': 'healthy', 'sex': 'female'}
        out = animal_probabilities(animal, date(2026,10,22), 30)
        self.assertTrue(out['tail_extrapolated'])
        self.assertEqual(len(out['predictions']), 30)
        self.assertIn('未驗證', out['warning'])
        for row in out['predictions']:
            total=row['survival_probability']+sum(row['cumulative_event_probabilities'].values())
            self.assertAlmostEqual(total,1.,places=6)
            self.assertGreaterEqual(row['survival_probability'],0.)

    def test_forecast_uses_database_and_real_metrics(self):
        conn=sqlite3.connect(ROOT/'backend/showcase.sqlite3')
        conn.row_factory=sqlite3.Row
        animals=[dict(r) for r in conn.execute('SELECT * FROM animals WHERE is_active=1')]
        conn.close()
        as_of=max([date(2026,10,22)]+[date.fromisoformat(a['intake_date']) for a in animals])
        out=resource_forecast(animals,as_of,30,simulations=120)
        self.assertEqual(out['forecast'][0]['date'],(as_of+timedelta(days=1)).isoformat())
        self.assertEqual(out['forecast'][-1]['date'],(as_of+timedelta(days=30)).isoformat())
        self.assertEqual(len(out['forecast']),30)
        self.assertEqual(out['estimated_animals'],len(animals))
        for row in out['forecast']:
            self.assertLessEqual(row['food_lower_kg'],row['food_upper_kg'])
            self.assertLessEqual(row['care_lower_hours'],row['care_upper_hours'])
        self.assertEqual(out['monte_carlo']['simulations'],120)

    def test_evaluation_is_loaded(self):
        r=metrics_report(horizon=30)
        self.assertEqual(len(r['lightgbm']['metrics']),5)
        self.assertEqual(len(r['lightgbm']['calibration']),25)
        self.assertIn('MAE',r['catboost']['intake_count']['overall_test'])
        self.assertIsNotNone(r['long_stay_brier'][0]['brier_30d'])
        self.assertIsNone(r['long_stay_brier'][2]['brier_30d'])

if __name__ == '__main__': unittest.main()
