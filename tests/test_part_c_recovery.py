import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from checks.check_03 import scripted_run,scripted_scenarios,registry,written
from harness.scripted import ScriptedTriage
from harness.calls import read_calls
from tools import ProtocolError

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)

    def test_three_exits_and_control(self):
        scenarios=scripted_scenarios(self.path)
        a,b,c=[scenarios[x] for x in 'ABC']
        self.assertEqual(a['ends'],['completed']);self.assertEqual(len(a['comments']),1);self.assertEqual(len(a['prs']),1)
        self.assertEqual(b['ends'],['escalated']);self.assertFalse(b['comments']);self.assertEqual(len(b['prs']),1)
        self.assertEqual(c['ends'],['completed']);self.assertEqual(len(c['comments']),2);self.assertEqual(len(c['prs']),1)
        attempts=[r for r in a['calls'] if r['role']=='open_pr']
        self.assertEqual(attempts[0]['outcome'],'timeout')
        self.assertEqual(len({r['key'] for r in attempts}),1)
        self.assertTrue(any(r['attempt']==2 and r['outcome']=='ok' for r in attempts))
        for result in scenarios.values():
            recorded={(r['role'],r['key']) for r in result['calls'] if r['outcome'] in ('ok','timeout')}
            for role,table in [('comment','comments'),('open_pr','prs')]:
                for row in result[table]:self.assertIn((role,row['key']),recorded)
            for line in result['calls']:
                self.assertEqual(line['cost_usd'],0);self.assertLessEqual(len(line['result']),300)

    def test_attempt_bound(self):
        r=scripted_run(ScriptedTriage(),4192,self.path,'bound',faults=['before_commit']*3)
        self.assertEqual(r['ends'],['escalated']);self.assertFalse(r['comments']);self.assertFalse(r['prs'])
        calls=[x for x in r['calls'] if x['role']=='open_pr']
        self.assertEqual([x['attempt'] for x in calls],[1,2,3])
        self.assertEqual(len({x['key'] for x in calls}),1)

    def test_hooks_fail_closed_and_leave_records(self):
        for label,hook in [('deny',lambda n,a:'maintenance'),('raise',lambda n,a:1/0)]:
            tools,ctx=registry(self.path,label)
            tools.hooks.append(hook)
            name='tracker_post_comment';args=copy.deepcopy(tools.definition(name)['examples'][0]['input'])
            result=tools.call(name,args,plan_step=5)
            self.assertTrue(result.is_error);self.assertEqual(written(ctx),([],[]))
            self.assertEqual(read_calls(ctx.calls.path)[-1]['outcome'],'denied')

    def test_hook_runs_again_before_retry(self):
        tools,ctx=registry(self.path,'retryhook',faults=['before_commit'])
        count=[]
        def hook(name,args):
            count.append(name)
            return None if len(count)==1 else 'policy changed'
        tools.hooks.append(hook)
        args=copy.deepcopy(tools.definition('tracker_post_comment')['examples'][0]['input'])
        result=tools.call('tracker_post_comment',args,plan_step=5)
        self.assertTrue(result.is_error);self.assertEqual(len(count),2)
        self.assertEqual(written(ctx),([],[]))
        self.assertEqual([x['outcome'] for x in read_calls(ctx.calls.path)],['timeout','denied'])

    def test_precheck_skips_existing_write(self):
        tools,ctx=registry(self.path,'precheck')
        for name,step in [('pulls_open_draft',4),('tracker_post_comment',5)]:
            args=copy.deepcopy(tools.definition(name)['examples'][0]['input'])
            first=tools.call(name,args,plan_step=step)
            module=tools._tools[name][1]
            with patch.object(module,'run') as run:
                second=tools.call(name,args,plan_step=step)
            run.assert_not_called();self.assertEqual(first.content,second.content)
        self.assertEqual([len(x) for x in written(ctx)],[1,1])

    def test_reads_rejections_protocol_are_recorded(self):
        tools,ctx=registry(self.path,'records')
        tools.call('tracker_read_issue',{'number':4191},plan_step=1)
        tools.call('tracker_read_issue',{'number':True},plan_step=1)
        with self.assertRaises(ProtocolError):tools.call('tracker_read_issue',[],plan_step=1)
        lines=read_calls(ctx.calls.path)
        self.assertEqual([x['outcome'] for x in lines],['ok','rejected','protocol'])
        self.assertTrue(all(x['key'] is None for x in lines))
        self.assertIn('arguments must be a JSON object',Path(ctx.harness_log).read_text())

    def test_uuid_changes_per_attempt_with_original_arguments(self):
        r=scripted_run(ScriptedTriage(),4192,self.path,'uuid',faults=[None,'after_commit',None],switches={'key_mode':'uuid','verify':'off'})
        self.assertEqual(r['ends'],['completed'])
        writes=[x for x in r['calls'] if x['role']=='comment']
        self.assertEqual([x['attempt'] for x in writes],[1,2])
        self.assertNotEqual(writes[0]['key'],writes[1]['key'])
        self.assertEqual(writes[0]['args'],writes[1]['args'])
        self.assertEqual(len(r['comments']),2)
