import unittest
from agent_evaluation import evaluate

class AgentRegressionTests(unittest.TestCase):
    def test_regressions(self):
        result=evaluate()
        failures=[c for c in result['cases'] if not c['passed']]
        self.assertEqual(failures,[],str(failures))

if __name__=='__main__':
    unittest.main()
