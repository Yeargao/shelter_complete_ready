"""Shared Gemini transport, local quota ledger and summary cache."""
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
import time
from zoneinfo import ZoneInfo

import httpx
from google import genai
from google.genai import errors as genai_errors, types

DEFAULT_MODEL = 'gemini-3.1-flash-lite'
APPROVED_MODELS = (DEFAULT_MODEL, 'gemini-2.5-flash-lite', 'gemini-2.5-flash', 'gemini-3.5-flash-lite')
PACIFIC = ZoneInfo('America/Los_Angeles')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


LOCAL_BUDGET_DEFAULTS = {
    'MAX_REQUESTS_PER_DAY': 20,
    'MAX_REQUESTS_PER_MINUTE': 5,
    'MAX_INPUT_TOKENS_PER_MINUTE': 20000,
}


def limit(name, default=None):
    if default is None:
        default = LOCAL_BUDGET_DEFAULTS.get(name, 0)
    try:
        return max(0, int(os.getenv('LLM_' + name, str(default))))
    except ValueError:
        return 0


def model_name():
    return (os.getenv('GEMINI_MODEL', '').strip() or DEFAULT_MODEL).removeprefix('models/')


def day_key(now):
    return datetime.fromtimestamp(now, PACIFIC).date().isoformat()


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS llm_attempts (
        id INTEGER PRIMARY KEY, at REAL NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
        input_tokens INTEGER NOT NULL, status TEXT NOT NULL)""")
    db.execute('CREATE INDEX IF NOT EXISTS llm_attempt_day ON llm_attempts(day, at)')
    db.execute('CREATE INDEX IF NOT EXISTS llm_attempt_time ON llm_attempts(at)')
    db.execute("""CREATE TABLE IF NOT EXISTS llm_events (
        day TEXT NOT NULL, kind TEXT NOT NULL, event TEXT NOT NULL, count INTEGER NOT NULL,
        PRIMARY KEY(day,kind,event))""")
    db.execute("""CREATE TABLE IF NOT EXISTS llm_state (
        config TEXT PRIMARY KEY, until REAL NOT NULL, error TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS llm_summary_cache (
        cache_key TEXT PRIMARY KEY, animal_id INTEGER NOT NULL, task_type TEXT NOT NULL,
        data_hash TEXT NOT NULL, prompt_version TEXT NOT NULL, model TEXT NOT NULL,
        response TEXT NOT NULL, source_record_ids TEXT NOT NULL,
        created_at REAL NOT NULL, expires_at REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS llm_summary_leases (
        cache_key TEXT PRIMARY KEY, owner TEXT NOT NULL, until REAL NOT NULL)""")


def count_event(db, kind, event):
    db.execute("""INSERT INTO llm_events VALUES (?,?,?,1)
        ON CONFLICT(day,kind,event) DO UPDATE SET count=count+1""",
               (day_key(time.time()), kind, event))


def settings_error():
    if os.getenv('LLM_ENABLED', '0').lower() not in ('1', 'true', 'yes'):
        return 'disabled'
    if not os.getenv('GEMINI_API_KEY', '').strip():
        return 'missing_key'
    if os.getenv('LLM_DATA_APPROVED', '0').lower() not in ('1', 'true', 'yes'):
        return 'data_not_approved'
    if model_name() not in APPROVED_MODELS:
        return 'invalid_model'
    return None


def config_id(model=None):
    return digest([model or model_name(), os.getenv('GEMINI_API_KEY', '').strip()])


def reserve(connect, kind, tokens, model=None):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        now = time.time()
        state = db.execute('SELECT until,error FROM llm_state WHERE config=?', (config_id(model),)).fetchone()
        if state and state['until'] > now:
            return None, state['error']
        daily = db.execute('SELECT COUNT(*) FROM llm_attempts WHERE day=?', (day_key(now),)).fetchone()[0]
        minute, used = db.execute('SELECT COUNT(*),COALESCE(SUM(input_tokens),0) FROM llm_attempts WHERE at>?',
                                  (now-60,)).fetchone()
        if any(limit(name) == 0 for name in LOCAL_BUDGET_DEFAULTS):
            return None, 'local_budget_disabled'
        maximum = limit('MAX_REQUESTS_PER_DAY')
        if kind != 'chat':
            maximum = max(0, maximum - limit('CHAT_RESERVED_REQUESTS'))
        for exceeds, reason in (
            (daily >= maximum, 'daily_budget'),
            (minute >= limit('MAX_REQUESTS_PER_MINUTE'), 'minute_budget'),
            (used + tokens > limit('MAX_INPUT_TOKENS_PER_MINUTE'), 'token_budget'),
        ):
            if exceeds:
                return None, reason
        attempt = db.execute('INSERT INTO llm_attempts(at,day,kind,input_tokens,status) VALUES (?,?,?,?,?)',
                             (now, day_key(now), kind, tokens, 'pending')).lastrowid
        return attempt, None


def retry_after(value):
    if value:
        try:
            return max(1, int(value))
        except ValueError:
            try:
                return max(1, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    return 60


def http_client():
    return httpx.Client(timeout=8, follow_redirects=False)


def gemini_call(instruction, content, schema, maximum, model=None):
    with http_client() as transport, genai.Client(
        api_key=os.getenv('GEMINI_API_KEY', '').strip(),
        vertexai=False,
        http_options=types.HttpOptions(
            api_version='v1beta', base_url='https://generativelanguage.googleapis.com',
            timeout=8000, httpx_client=transport,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    ) as client:
        result = client.models.generate_content(
            model=model or model_name(), contents=content,
            config=types.GenerateContentConfig(
                system_instruction=instruction, response_mime_type='application/json',
                response_json_schema={k: v for k, v in schema.items() if k != 'additionalProperties'},
                max_output_tokens=maximum,
            ),
        )
        return result.model_dump(mode='json', by_alias=True, exclude_none=True)


def generate(connect, kind, instruction, data, schema, validate):
    """Try approved alternatives for model/request errors, retaining all quota and privacy gates."""
    output, error = _generate(connect, kind, instruction, data, schema, validate)
    for alternate in APPROVED_MODELS:
        if error not in ('configuration_400', 'configuration_404'):
            break
        if alternate != model_name():
            output, error = _generate(connect, kind, instruction, data, schema, validate, alternate)
    return output, error


def _generate(connect, kind, instruction, data, schema, validate, model=None):
    """Charge a separate quota reservation before each external attempt."""
    error = settings_error()
    if error:
        return None, error
    content = canonical(data)
    maximum = max(1, limit('MAX_OUTPUT_TOKENS', 512))
    estimated = len(canonical([instruction, content, schema]).encode('utf-8')) + 256
    attempt, error = reserve(connect, kind, estimated, model) if model else reserve(connect, kind, estimated)
    if error:
        return None, error
    output, cooldown, tokens = None, 0, estimated
    try:
        body = gemini_call(instruction, content, schema, maximum, model) if model else gemini_call(instruction, content, schema, maximum)
        actual = body.get('usageMetadata', {}).get('promptTokenCount')
        if type(actual) is int and actual > 0:
            tokens = actual
        candidate = body['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Incomplete response')
        output = validate(json.loads(''.join(
            part['text'] for part in candidate['content']['parts'] if not part.get('thought')
        )))
    except (genai_errors.APIError, httpx.HTTPStatusError) as exc:
        status = exc.code if isinstance(exc, genai_errors.APIError) else exc.response.status_code
        headers = getattr(getattr(exc, 'response', None), 'headers', None) or {}
        if status == 429:
            error, cooldown = 'rate_limited', retry_after(headers.get('Retry-After'))
        elif status in (400, 401, 403, 404):
            error, cooldown = f'configuration_{status}', 3600
        else:
            error, cooldown = 'upstream_error', 15
    except httpx.RequestError:
        error, cooldown = 'network_error', 15
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        error, cooldown = 'invalid_response', 15
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('UPDATE llm_attempts SET status=?,input_tokens=? WHERE id=?',
                   ('failed' if error else 'succeeded', tokens, attempt))
        if error:
            db.execute("""INSERT INTO llm_state VALUES (?,?,?) ON CONFLICT(config) DO UPDATE
                SET until=excluded.until,error=excluded.error WHERE excluded.until>=llm_state.until""",
                       (config_id(model), time.time()+cooldown, error))
    return output, error


def usage(db):
    today = day_key(time.time())
    attempts = db.execute("""SELECT kind,status,COUNT(*) AS count FROM llm_attempts
        WHERE day=? GROUP BY kind,status""", (today,)).fetchall()
    events = dict(db.execute('SELECT event,SUM(count) FROM llm_events WHERE day=? GROUP BY event', (today,)))
    hits, misses = events.get('cache_hit', 0), events.get('cache_miss', 0)
    state = db.execute('SELECT until,error FROM llm_state WHERE config=?', (config_id(),)).fetchone()
    cooling = bool(state and state['until'] > time.time())
    successes = sum(r['count'] for r in attempts if r['status'] == 'succeeded')
    return {
        'day': today, 'local_daily_budget': limit('MAX_REQUESTS_PER_DAY'),
        'used': sum(r['count'] for r in attempts), 'successes': successes,
        'failures': sum(r['count'] for r in attempts if r['status'] == 'failed'),
        'chat_requests': sum(r['count'] for r in attempts if r['kind'] == 'chat'),
        'chat_interactions': events.get('interaction', 0),
        'summary_requests': sum(r['count'] for r in attempts if r['kind'] == 'summary'),
        'cache_hits': hits, 'cache_hit_rate': hits / (hits + misses) if hits + misses else None,
        'rule_answers': events.get('rule', 0),
        'connection': settings_error() or ('cooling_down' if cooling else 'connected' if successes else 'unverified'),
        'cooling': cooling, 'last_error': state['error'] if state else None,
    }
