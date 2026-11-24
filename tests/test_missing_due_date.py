"""Regression test for /api/staff/assignments with a missing vaccine due date."""
import ast
import unittest
from datetime import date
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "main.py"

class MissingDueDateTests(unittest.TestCase):
    def test_is_new_always_integer_when_due_date_missing(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        endpoint = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "staff_assignments")
        expr = next(node.value for node in ast.walk(endpoint) if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "is_new" for t in node.targets))
        expression = compile(ast.Expression(expr), str(SOURCE), "eval")
        for task, expected in [
            ({"label": "基礎驅蟲", "due_date": None}, 0),
            ({"label": "疫苗施打", "due_date": None}, 0),
            ({"label": "疫苗施打"}, 0),
            ({"label": "疫苗施打", "due_date": "2026-11-14"}, 1),
            ({"label": "疫苗施打", "due_date": "2026-11-16"}, 0),
        ]:
            with self.subTest(task=task):
                result = eval(expression, {"WORK_DATE": date(2026, 11, 15)}, {"task": task})
                self.assertIs(type(result), int)
                self.assertEqual(result, expected)

if __name__ == "__main__":
    unittest.main()
