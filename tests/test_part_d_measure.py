"""Measurement tests: no model calls and no access to the real tracker."""
import sqlite3
import unittest
from types import SimpleNamespace
from eval.measure_03 import aggregate, count_run, surface_cost


class MeasurementTests(unittest.TestCase):
    def test_database_duplicates_override_successful_trace(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE comments(id INTEGER, run_id TEXT, issue INTEGER, body TEXT, key TEXT);
            CREATE TABLE prs(id INTEGER, run_id TEXT, branch TEXT, state TEXT, key TEXT);
            CREATE TABLE attempts(id INTEGER, run_id TEXT, kind TEXT, key TEXT, outcome TEXT);
        """)
        for n in (1, 2):
            db.execute("INSERT INTO comments VALUES(?,?,?,?,?)", (n, "r", 99, "label: bug\nfile: src/example.ts", f"k{n}"))
        db.execute("INSERT INTO prs VALUES(?,?,?,?,?)", (1, "r", "repomind/issue-99", "open", "p"))
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,?)", (1, "r", "comment", "k1", "timeout_after_commit"))
        calls = [dict(role="comment", key="k1", outcome="timeout"), dict(role="comment", key="k2", outcome="ok"), dict(role="open_pr", key="p", outcome="ok")]
        run = dict(start=dict(run_id="r", issue=99, sweep=1), end=dict(terminal_reason="completed"), calls=calls)
        row = count_run(db, run, dict(label="bug", file="src/example.ts"))
        self.assertEqual(row["comments"], 2)
        self.assertFalse(row["triage_pass"])
        self.assertTrue(row["prs_correct"])
        self.assertTrue(row["all_committed_timeouts_recorded"])
        self.assertEqual(aggregate([row])["duplicate_comment_runs"], 1)
        calls.pop(0)
        self.assertFalse(count_run(db, run, dict(label="bug", file="src/example.ts"))["all_writes_recorded"])
        db.close()

    def test_prices_text_list_and_one_tool_without_submit_plan(self):
        counts = {v: dict(all_five=100*m, alone={"search_repo": 20*m}, list=30*m,
                          names={"codebase_search": "search_repo"}) for v,m in [("before", 1), ("after", 2)]}
        calls = [dict(model="test", purpose="plan", tools=["submit_plan"]),
                 dict(model="test", purpose="revise", tools=["submit_plan"]),
                 dict(model="test", purpose="fill", tools=["codebase_search"]),
                 dict(model="test", purpose="critique", tools=[])]
        price = SimpleNamespace(find=lambda model: SimpleNamespace(input=1.0))
        result = surface_cost(calls, counts, price)
        self.assertAlmostEqual(result["before"], 80/1_000_000)
        self.assertAlmostEqual(result["after"], 160/1_000_000)
        self.assertAlmostEqual(result["all_five"], 800/1_000_000)
