"""Guard the lightweight cold-start path in a fresh Python interpreter."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ColdStartTests(unittest.TestCase):
    def test_health_and_login_do_not_import_prediction_or_solver_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            env={**os.environ,'SHELTER_DB_PATH':str(Path(directory)/'startup.sqlite3'),
                 'SHELTER_UPLOAD_DIR':str(Path(directory)/'uploads'),
                 'SHELTER_MODEL_MODE':'demo','SHELTER_AUTH_PASSWORDS':'',
                 'LLM_ENABLED':'0','PYTHONDONTWRITEBYTECODE':'1'}
            script="""
import sys
sys.path.insert(0, 'backend')
import main
from fastapi.testclient import TestClient
with TestClient(main.app) as client:
    health=client.get('/healthz')
    assert health.status_code==200, health.text
    assert health.json()['status']=='ok'
    login=client.post('/api/auth/login',json={'password':'01'})
    assert login.status_code==200,login.text
    assert login.json()['role']=='manager'
    assert client.post('/api/auth/login',json={'password':'wrong'}).status_code==401
    headers={'Authorization':'Bearer '+login.json()['token']}
    overview=client.get('/api/schedule/overview',headers=headers)
    assert overview.status_code==200,overview.text
    usage=client.get('/api/llm/usage',headers=headers)
    assert usage.status_code==200,usage.text
heavy=('numpy','pandas','catboost','ortools','google.genai','lightgbm','sklearn')
loaded=[name for name in heavy if name in sys.modules]
assert not loaded, loaded
assert main.optional_model.cache_info().currsize==0
"""
            result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,
                                  capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':
    unittest.main()
