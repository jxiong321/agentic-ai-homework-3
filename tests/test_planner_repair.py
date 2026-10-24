"""Generic plan-format regressions, exercised only with a development issue."""
import json
import tempfile
import unittest
from pathlib import Path
from checks.check_03 import scripted_run
from harness.scripted import ScriptedTriage


class MalformedThenRepair(ScriptedTriage):
    def __init__(self, fault, always=False):
        super().__init__()
        self.fault = fault
        self.always = always
        self.plans = 0
        self.repair_request = None

    def create(self, *, system, messages, tools):
        result = super().create(system=system, messages=messages, tools=tools)
        if not any(t["name"] == "submit_plan" for t in tools or []):
            return result
        self.plans += 1
        if self.plans == 2:
            self.repair_request = messages[0]["content"]
        if self.plans == 1 or self.always:
            steps = result[0][0]["input"]["steps"]
            if self.fault == "args_json":
                steps[0]["args_json"] = '{"number":'
            else:
                for step in steps:
                    step.pop(self.fault)
        return result


class PlannerRepairTests(unittest.TestCase):
    def test_repair_sees_rejected_plan_and_specific_error(self):
        for fault in ("id", "tool", "args_json"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                backend = MalformedThenRepair(fault)
                result = scripted_run(backend, 4192, Path(tmp), "repair")
                self.assertIsNone(result["error"])
                self.assertEqual(result["ends"], ["completed"])
                self.assertEqual(len(result["comments"]), 1)
                self.assertEqual(len(result["prs"]), 1)
                request = backend.repair_request
                self.assertIn("Rejected plan to repair", request)
                self.assertIn("all these keys: id, action, tool, args_json, depends_on, expected_result, status", request)
                self.assertIn(fault, request)
                self.assertIn('"id": 1', request)
                records = result["records"]
                first_dispatch = next(i for i,r in enumerate(records) if r["type"] == "tool_call")
                plans_before = [r for r in records[:first_dispatch] if r["type"] == "model_call" and r.get("purpose") == "plan"]
                self.assertEqual(len(plans_before), 2)
                self.assertTrue(any(r["type"] == "schema" for r in records[:first_dispatch]))

    def test_repeated_invalid_plans_still_stop_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = MalformedThenRepair("id", always=True)
            result = scripted_run(backend, 4192, Path(tmp), "always-invalid")
            self.assertEqual(backend.plans, 3)
            self.assertEqual(result["ends"], ["escalated"])
            self.assertFalse(result["comments"])
            self.assertFalse(result["prs"])
            self.assertFalse(result["calls"])
