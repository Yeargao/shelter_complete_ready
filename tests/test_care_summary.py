"""SQLite persistence and mocked Gemini coverage. No test calls the external API."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import Mock, patch

import httpx

BACKEND = Path(__file__).resolve().parents[1] / 'backend'


class CareSummaryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(sys, 'path', [str(BACKEND), *sys.path]))
        import care_summary
        import llm_service
        self.llm = llm_service
        self.summary = care_summary.summary
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'llm.sqlite3'
        self.task = {'task_id': 'test', 'animal_id': 1, 'priority': 0, 'label': '健康問題追蹤',
                     'staff_id': 1, 'day': '2026-11-23', 'start': 32}
        with self.connect() as db:
            self.llm.migrate(db)
            db.executescript("""
                CREATE TABLE animals (id, name, species, health_status, vaccinated, dewormed);
                INSERT INTO animals VALUES (1,'測試動物','dog','sick','no','no');
                CREATE TABLE weekly_tasks (task_id, animal_id, label);
                CREATE TABLE weekly_reports (task_id, result, reported_at, note);
                CREATE TABLE weekly_issues (task_id, animal_id, resolved_at, note);
                CREATE TABLE vaccination_records (id, animal_id, vaccine_type, administered_date, next_due_date);
                CREATE TABLE deworming_events (animal_id, intake_date, completed_date);
            """)
        self.enterContext(patch.dict(os.environ, {
            'GEMINI_API_KEY': 'mock-key', 'GEMINI_MODEL': '', 'LLM_ENABLED': '1',
            'LLM_DATA_APPROVED': '1', 'LLM_MAX_REQUESTS_PER_MINUTE': '10',
            'LLM_MAX_REQUESTS_PER_DAY': '20', 'LLM_MAX_INPUT_TOKENS_PER_MINUTE': '50000',
            'LLM_CHAT_RESERVED_REQUESTS': '2', 'LLM_CACHE_TTL_SECONDS': '1000',
        }))
        self.request = httpx.Request('POST', 'https://generativelanguage.googleapis.com')
        self.post = Mock()
        self.enterContext(patch.object(llm_service, 'http_client', side_effect=lambda:
            httpx.Client(transport=httpx.MockTransport(self.post), follow_redirects=False)))
        self.success = self.response({'animal_summary':[0], 'known_issues':[0], 'observations':[0], 'unconfirmed':[]})
        self.post.return_value = self.success

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def response(self, output):
        return httpx.Response(200, request=self.request, json={
            'usageMetadata': {'promptTokenCount': 100},
            'candidates': [{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(output)}]}}],
        })

    def call(self):
        return self.summary(self.connect, self.task, allow_ai=True)

    def use(self):
        with self.connect() as db:
            return self.llm.usage(db)

    def test_cache_reused_across_placements_and_connections(self):
        result = self.call()
        self.assertEqual(result['mode'], 'llm')
        self.task.update(task_id='different',staff_id=6,day='2026-11-25',start=44)
        self.assertEqual(self.call()['mode'], 'cache')
        self.post.assert_called_once()
        self.assertEqual(self.use()['cache_hits'], 1)
        self.assertEqual(self.use()['used'], 1)
        sent = self.post.call_args.args[0]
        self.assertNotIn('測試動物',sent.content.decode())
        self.assertEqual(sent.headers['x-goog-api-key'],'mock-key')
        self.assertNotIn('mock-key',str(sent.url))
        with self.connect() as db:
            db.execute("UPDATE animals SET health_status='injured'")
        self.assertEqual(self.call()['mode'], 'llm')
        self.assertEqual(self.post.call_count, 2)
        with self.connect() as db:
            db.execute('UPDATE llm_summary_cache SET expires_at=0')
        self.assertEqual(self.call()['mode'], 'llm')
        self.assertEqual(self.post.call_count, 3)

    def test_concurrent_same_key_deduplicates(self):
        entered, release = Event(), Event()
        def slow_response(*_args, **_kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('Test request timed out')
            return self.success
        self.post.side_effect = slow_response
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.call)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(pool.submit(self.call).result(5)['fallback_reason'], 'in_progress')
            finally:
                release.set()
            self.assertEqual(future.result(5)['mode'], 'llm')
        self.assertEqual(self.call()['mode'], 'cache')
        self.post.assert_called_once()

    def test_missing_key_and_routine_task_skip_api(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY':' '}):
            self.assertEqual(self.call()['fallback_reason'], 'missing_key')
        self.task['priority'] = 4
        self.assertEqual(self.call()['mode'], 'rule_based')
        self.post.assert_not_called()

    def test_budgets_and_reserved_chat(self):
        for setting, value, expected in [
            ('MAX_REQUESTS_PER_MINUTE','0','local_budget_disabled'),
            ('MAX_INPUT_TOKENS_PER_MINUTE','1','token_budget'),
            ('MAX_REQUESTS_PER_DAY','2','daily_budget'),
        ]:
            with self.subTest(setting=setting), patch.dict(os.environ, {'LLM_'+setting:value}):
                self.assertEqual(self.call()['fallback_reason'], expected)
        self.post.assert_not_called()
        with patch.dict(os.environ, {'LLM_MAX_REQUESTS_PER_DAY':'1'}):
            self.assertEqual(self.call()['fallback_reason'], 'daily_budget')
            self.post.return_value = self.response({'order':[0]})
            result, error = self.llm.generate(self.connect, 'chat', 'Select', [], {}, lambda answer: answer)
            self.assertEqual(result, {'order':[0]})
            self.assertIsNone(error)
            _, error = self.llm.generate(self.connect, 'chat', 'Select', [], {}, lambda answer: answer)
            self.assertEqual(error, 'daily_budget')
        self.post.assert_called_once()

    def test_429_charges_attempt_and_cools_down_shared_service(self):
        self.post.return_value = httpx.Response(429, request=self.request, headers={'Retry-After':'90'})
        self.assertEqual(self.call()['fallback_reason'], 'rate_limited')
        _, error = self.llm.generate(self.connect, 'chat', 'Select', [], {}, lambda answer: answer)
        self.assertEqual(error, 'rate_limited')
        self.post.assert_called_once()
        self.assertEqual(self.use()['failures'], 1)
        self.assertEqual(self.use()['used'], 1)
        self.assertTrue(self.use()['cooling'])
        with self.connect() as db:
            self.assertGreater(db.execute('SELECT until FROM llm_state').fetchone()[0]-time.time(), 80)

    def test_invalid_payload_and_transport_errors_fall_back(self):
        for effect, response, reason in [
            (None,self.response({'invalid':[]}), 'invalid_response'),
            (httpx.ReadTimeout('timeout'),None,'network_error'),
            (None,httpx.Response(403,request=self.request),'configuration_403'),
            (None,httpx.Response(503,request=self.request),'upstream_error'),
        ]:
            with self.subTest(reason=reason):
                with self.connect() as db:
                    db.execute('UPDATE llm_state SET until=0')
                self.post.side_effect = effect
                self.post.return_value = response
                self.assertEqual(self.call()['fallback_reason'], reason)
        self.assertEqual(self.use()['failures'], 4)
