import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from checks.check_03 import scripted_run
from harness.scripted import ScriptedTriage,DraftNamesNoFile
from harness.roles import role_of
from tools import ToolError
from ways.planned import Executor,schema_check

class WriteOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_reviewed_draft_precedes_writes(self):
        result=scripted_run(ScriptedTriage(),4192,self.root,'ordered')
        self.assertEqual(result['ends'],['completed'],result['error'])
        self.assertEqual(len(result['prs']),1);self.assertEqual(len(result['comments']),1)
        records=result['records']
        draft=next(i for i,r in enumerate(records) if r['type']=='draft_prepared')
        writes=[(i,role_of(r['name'])) for i,r in enumerate(records) if r['type']=='tool_call' and role_of(r['name']) in ('open_pr','comment')]
        self.assertEqual([r for _,r in writes],['open_pr','comment'])
        self.assertLess(draft,writes[0][0])
        self.assertIn('src/ingest/dedupe.ts',result['prs'][0]['body'])
        self.assertEqual(result['comments'][0]['body'],'label: bug\nfile: src/ingest/dedupe.ts')

    def test_none_skips_pr(self):
        result=scripted_run(DraftNamesNoFile(),4192,self.root,'none')
        self.assertEqual(result['ends'],['completed'],result['error'])
        self.assertFalse(result['prs']);self.assertEqual(len(result['comments']),1)
        self.assertTrue(any(r['type']=='pr_skipped' for r in result['records']))

    def test_held_review_prevents_both_writes(self):
        with patch.object(Executor,'second_pass',return_value=None):
            result=scripted_run(ScriptedTriage(),4192,self.root,'held')
        self.assertEqual(result['ends'],['escalated'])
        self.assertFalse(result['prs']);self.assertFalse(result['comments'])

    def test_pr_error_withholds_comment(self):
        with patch('tools.open_pr.run',side_effect=ToolError('Invalid body: repair proposal.')):
            result=scripted_run(ScriptedTriage(),4192,self.root,'pr-error')
        self.assertEqual(result['ends'],['escalated'])
        self.assertFalse(result['comments'])

    def test_plan_rejects_missing_duplicate_and_misordered_writes(self):
        result=scripted_run(ScriptedTriage(),4192,self.root,'plan')
        plan=next(r['plan'] for r in result['records'] if r['type']=='plan')
        from tools import ToolRegistry,RunContext
        ctx=Mock();ctx.tools=ToolRegistry(RunContext('schema-test',None,Path(__file__).resolve().parents[1]/'fixtures/repo'))
        self.assertFalse(schema_check(ctx,plan,1))
        mutations=[]
        missing=copy.deepcopy(plan);missing['steps'].pop(-2);mutations.append(missing)
        duplicate=copy.deepcopy(plan);duplicate['steps'].insert(-1,copy.deepcopy(duplicate['steps'][-1]));mutations.append(duplicate)
        duplicate_pr=copy.deepcopy(plan);duplicate_pr['steps'].insert(-2,copy.deepcopy(duplicate_pr['steps'][-2]));mutations.append(duplicate_pr)
        swapped=copy.deepcopy(plan);swapped['steps'][-2:]=reversed(swapped['steps'][-2:]);mutations.append(swapped)
        bad_json=copy.deepcopy(plan);bad_json['steps'][0]['args_json']='not json';mutations.append(bad_json)
        missing_args=copy.deepcopy(plan);missing_args['steps'][0]['args_json']='{}';mutations.append(missing_args)
        embedded=copy.deepcopy(plan);embedded['steps'][-1]['args_json']='{"number":4192,"body":"file: $fill"}';mutations.append(embedded)
        for altered in mutations:self.assertTrue(schema_check(ctx,altered,1))
