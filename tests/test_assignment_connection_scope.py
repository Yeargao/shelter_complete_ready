"""Regression: all staff_assignments DB reads must occur inside an open connection."""
import ast
from pathlib import Path
import unittest

MAIN = Path(__file__).resolve().parents[1] / 'backend' / 'main.py'


class StaffAssignmentsConnectionScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(MAIN.read_text(encoding='utf-8'), filename=str(MAIN))
        cls.func = next(n for n in ast.walk(cls.tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n.name == 'staff_assignments')

    def test_active_ids_query_runs_with_open_connection(self):
        assigned = [n for n in ast.walk(self.func)
                    if isinstance(n, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == 'active_ids'
                        for t in n.targets)]
        self.assertEqual(len(assigned), 1)
        query = assigned[0]
        connection_scopes = [n for n in ast.walk(self.func)
                             if isinstance(n, (ast.With, ast.AsyncWith))
                             and any(isinstance(x.context_expr, ast.Call)
                                     and isinstance(x.context_expr.func, ast.Name)
                                     and x.context_expr.func.id == 'connect'
                                     for x in n.items)]
        self.assertTrue(connection_scopes)
        self.assertTrue(any(scope.lineno <= query.lineno <= scope.end_lineno
                            for scope in connection_scopes),
                        'active_ids must be queried before the connection is closed')

    def test_no_database_query_after_second_connection_scope(self):
        scopes = sorted((n for n in ast.walk(self.func)
                         if isinstance(n, ast.With)
                         and any(isinstance(x.context_expr, ast.Call)
                                 and isinstance(x.context_expr.func, ast.Name)
                                 and x.context_expr.func.id == 'connect'
                                 for x in n.items)), key=lambda n: n.lineno)
        self.assertGreaterEqual(len(scopes), 2)
        final_scope = scopes[-1]
        # The outer function may still manipulate already materialized records.
        # But it must not attempt to execute SQL using the closed cursor/connection.
        late_calls = [n for n in ast.walk(self.func)
                      if isinstance(n, ast.Call) and n.lineno > final_scope.end_lineno
                      and isinstance(n.func, ast.Attribute)
                      and isinstance(n.func.value, ast.Name)
                      and n.func.value.id == 'c'
                      and n.func.attr in {'execute', 'executemany', 'executescript'}]
        self.assertEqual(late_calls, [])


if __name__ == '__main__':
    unittest.main()
