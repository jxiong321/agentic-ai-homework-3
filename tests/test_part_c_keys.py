import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from harness.tracker import Tracker,TrackerTimeout
from tools import ToolRegistry,RunContext,derive_write_key,TransientToolError
ROOT=Path(__file__).resolve().parents[1]

class WriteKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.tracker=Tracker(ROOT,state_dir=Path(self.tmp.name)/'tracker',flaky=False)
        self.registry=ToolRegistry(RunContext('key-test',self.tracker,ROOT/'fixtures/repo',harness_log=Path(self.tmp.name)/'test.log'))
    def args(self,name):return copy.deepcopy(self.registry.definition(name)['examples'][0]['input'])

    def test_key_canonicalization_and_scope(self):
        args={'number':4191,'body':'label: docs\nfile: README.md'}
        key=derive_write_key('run',4,args)
        self.assertEqual(key,derive_write_key('run',4,dict(reversed(list(args.items())))))
        self.assertNotEqual(key,derive_write_key('other-run',4,args))
        self.assertNotEqual(key,derive_write_key('run',5,args))
        self.assertNotEqual(key,derive_write_key('run',4,dict(args,body=args['body']+' ')))
        self.assertEqual(len(key),64)

    def test_repeated_calls_store_one_write_each(self):
        for name,step in [('tracker_post_comment',5),('pulls_open_draft',4)]:
            args=self.args(name)
            first=self.registry.call(name,args,plan_step=step)
            second=self.registry.call(name,dict(reversed(list(args.items()))),plan_step=step)
            self.assertFalse(first.is_error,first.content)
            self.assertEqual(first.content,second.content)
        self.assertEqual(len(self.tracker.comments('key-test')),1)
        self.assertEqual(len(self.tracker.prs('key-test')),1)
        for row,step,name in [(self.tracker.comments('key-test')[0],5,'tracker_post_comment'),(self.tracker.prs('key-test')[0],4,'pulls_open_draft')]:
            self.assertEqual(row['key'],derive_write_key('key-test',step,self.args(name)))

    def test_committed_timeout_replay_does_not_duplicate(self):
        for name in ('tracker_post_comment','pulls_open_draft'):
            self.tracker.faults=['after_commit',None]
            args=self.args(name)
            recovered=self.registry.call(name,args,plan_step=7)
            self.assertFalse(recovered.is_error,recovered.content)
            # Explicit repeat now demonstrates the pre-write existence check after recovery.
            replay=self.registry.call(name,args,plan_step=7)
            self.assertFalse(replay.is_error,replay.content)
        self.assertEqual(len(self.tracker.comments('key-test')),1)
        self.assertEqual(len(self.tracker.prs('key-test')),1)

    def test_internal_retries_preserve_snapshot_and_key(self):
        name='tracker_post_comment';args=self.args(name);original=copy.deepcopy(args)
        module=self.registry._tools[name][1];received=[]
        def attempt(ctx,**kwargs):
            received.append(copy.deepcopy(kwargs))
            if len(received)==1:
                args['body']='caller changed original object'
                raise TransientToolError('not sent',before_dispatch=True)
            return json.dumps(dict(issue_id='issue-4191',comment_id='comment-1',truncated=False))
        with patch.object(module,'run',side_effect=attempt),patch('tools.time.sleep'):
            result=self.registry.call(name,args,plan_step=5)
        self.assertFalse(result.is_error,result.content)
        self.assertEqual(received[0],received[1])
        self.assertEqual(received[0]['body'],original['body'])
        self.assertEqual(received[0]['idempotency_key'],derive_write_key('key-test',5,original))

    def test_model_cannot_supply_key_and_reads_do_not_get_one(self):
        for schema in self.registry.schemas:
            self.assertNotIn('idempotency_key',schema['input_schema']['properties'])
        args=self.args('tracker_post_comment');args['idempotency_key']='model-key'
        result=self.registry.call('tracker_post_comment',args,plan_step=5)
        self.assertTrue(result.is_error);self.assertFalse(self.tracker.comments('key-test'))
        module=self.registry._tools['tracker_read_issue'][1]
        with patch.object(module,'run',wraps=module.run) as run:
            result=self.registry.call('tracker_read_issue',{'number':4191},plan_step=1)
        self.assertFalse(result.is_error)
        self.assertNotIn('idempotency_key',run.call_args.kwargs)
