import copy
import errno
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import RunContext,ToolRegistry,ToolError,ProtocolError,TransientToolError,WriteUnconfirmed
from harness.tracker import Tracker,TrackerTimeout

ROOT=Path(__file__).resolve().parents[1]

class ErrorPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.log=Path(self.tmp.name)/'test.harness.log'
        self.tracker=Tracker(root=ROOT,state_dir=Path(self.tmp.name)/'tracker',flaky=False)
        self.registry=ToolRegistry(RunContext('error-test',self.tracker,ROOT/'fixtures/repo',harness_log=self.log))

    def example(self,name):return copy.deepcopy(self.registry.definition(name)['examples'][0]['input'])

    def test_transient_read_recovers_without_model_call(self):
        name='tracker_read_issue';module=self.registry._tools[name][1]
        real=module.run(self.registry.ctx,number=4191)
        with patch.object(module,'run',side_effect=[TimeoutError('temporary'),real]) as run,patch('tools.time.sleep') as sleep:
            result=self.registry.call(name,self.example(name))
        self.assertFalse(result.is_error,result.content)
        self.assertEqual(run.call_count,2);sleep.assert_called_once_with(0.1)
        self.assertEqual(run.call_args_list[0],run.call_args_list[1])

    def test_retry_exhaustion_is_bounded_and_actionable(self):
        name='codebase_search';module=self.registry._tools[name][1]
        with patch.object(module,'run',side_effect=OSError(errno.EAGAIN,'temporary')) as run,patch('tools.time.sleep') as sleep:
            result=self.registry.call(name,self.example(name))
        self.assertTrue(result.is_error)
        self.assertEqual(run.call_count,3);self.assertEqual(sleep.call_count,2)
        self.assertIn('retry after',result.content);self.assertIn('3 attempt',result.content)
        self.assertLessEqual(len(result.content),1000)

    def test_long_retry_after_is_not_shortened(self):
        name='tracker_read_issue';module=self.registry._tools[name][1]
        with patch.object(module,'run',side_effect=TransientToolError('rate limit',retry_after=30)) as run,patch('tools.time.sleep') as sleep:
            result=self.registry.call(name,self.example(name))
        self.assertIn('retry after 30 seconds',result.content)
        self.assertEqual(run.call_count,1);sleep.assert_not_called()

    def test_confirmed_unsent_write_can_retry(self):
        name='tracker_post_comment';module=self.registry._tools[name][1]
        reply=json.dumps(dict(issue_id='issue-4191',comment_id='comment-1',truncated=False))
        with patch.object(module,'run',side_effect=[TransientToolError('not sent',before_dispatch=True),reply]) as run,patch('tools.time.sleep'):
            result=self.registry.call(name,self.example(name))
        self.assertFalse(result.is_error,result.content)
        self.assertEqual(run.call_count,2)
        self.assertEqual(run.call_args_list[0],run.call_args_list[1])

    def test_uncertain_write_is_never_retried_when_verification_unavailable(self):
        for name in ('tracker_post_comment','pulls_open_draft'):
            module=self.registry._tools[name][1]
            for exc in (TrackerTimeout('may have committed'),ConnectionError('lost reply'),TransientToolError('unknown dispatch')):
                with self.subTest(name=name,exc=type(exc).__name__),patch.object(module,'run',side_effect=exc) as run,patch('tools.time.sleep') as sleep:
                    with patch.object(self.registry,'read_back',side_effect=[None,WriteUnconfirmed('verification unavailable')]):
                        with self.assertRaises(WriteUnconfirmed):self.registry.call(name,self.example(name))
                    self.assertEqual(run.call_count,1);sleep.assert_not_called()

    def test_semantic_failure_not_retried(self):
        name='tracker_read_issue';module=self.registry._tools[name][1]
        with patch.object(module,'run',side_effect=ToolError('Invalid number: choose an existing issue.')) as run,patch('tools.time.sleep') as sleep:
            result=self.registry.call(name,self.example(name))
        self.assertTrue(result.is_error);self.assertEqual(run.call_count,1);sleep.assert_not_called()
        with patch.object(module,'run',side_effect=PermissionError('denied')) as run:
            result=self.registry.call(name,self.example(name))
        self.assertTrue(result.is_error);self.assertEqual(run.call_count,1)
        self.assertIn('permissions',result.content)

    def test_unknown_tool_logged_and_raises(self):
        with self.assertRaises(ProtocolError):self.registry.call('nonexistent_tool',{'number':4191})
        log=json.loads(self.log.read_text().splitlines()[0])
        self.assertEqual(log['tool'],'nonexistent_tool');self.assertEqual(log['arguments'],{'number':4191})

    def test_required_direct_calls(self):
        malformed=self.registry.call('tracker_read_issue',{'number':'not-an-integer'})
        self.assertTrue(malformed.is_error);self.assertIn('number',malformed.content)
        near=self.registry.call('codebase_read_file',{'path':'src/report.ts','response_format':'concise'})
        self.assertTrue(near.is_error)
        for path in ('src/reports.ts','src/Report.ts','src/report.tsx'):self.assertIn(path,near.content)
        self.assertIn('Correct the path before retrying',near.content)
        self.assertLessEqual(len(near.content),1000)
