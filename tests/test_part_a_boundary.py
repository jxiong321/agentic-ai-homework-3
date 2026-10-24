"""Boundary checks must prevent dispatch, not merely return an error afterward."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from harness.tracker import Tracker
from tools import RunContext, ToolRegistry, ProtocolError

ROOT = Path(__file__).resolve().parents[1]

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tracker = Tracker(root=ROOT, state_dir=Path(self.tmp.name), flaky=False)
        self.registry = ToolRegistry(RunContext('boundary-tests', self.tracker, ROOT/'fixtures/repo'))

    def example(self, name):
        return copy.deepcopy(self.registry.definition(name)['examples'][0]['input'])

    def assert_denied_before_dispatch(self, name, arguments, field):
        module = self.registry._tools[name][1]
        with patch.object(module, 'run') as run:
            result = self.registry.call(name, arguments)
        self.assertTrue(result.is_error, result.content)
        self.assertIn(field, result.content)
        run.assert_not_called()

    def test_bad_write_arguments_never_dispatch(self):
        for name in ('tracker_post_comment','pulls_open_draft'):
            for field, value in [('number',True),('number',0),('body',' '),('body','x'*4001)]:
                with self.subTest(name=name, field=field, value_type=type(value).__name__):
                    args=self.example(name);args[field]=value
                    self.assert_denied_before_dispatch(name,args,field)
            args=self.example(name);args['extra']='invented'
            self.assert_denied_before_dispatch(name,args,'extra')
            args=self.example(name);del args['body']
            self.assert_denied_before_dispatch(name,args,'body')
        args=self.example('pulls_open_draft');args['branch']='different-branch'
        self.assert_denied_before_dispatch('pulls_open_draft',args,'branch')

    def test_search_content_rules_and_types(self):
        name='codebase_search'
        for field,value in [('query',''),('query',' '*3),('query','x'*5000),('max_results',21),('max_results','10'),('path_glob','language:python'),('deep','false'),('response_format','verbose')]:
            with self.subTest(field=field):
                args=self.example(name);args[field]=value
                self.assert_denied_before_dispatch(name,args,field)
        self.registry.ctx.harness_log = Path(self.tmp.name)/'protocol.log'
        with self.assertRaises(ProtocolError):
            self.registry.call(name, [])

    def test_enum_normalization_and_nullable_fields(self):
        args=self.example('codebase_search');args['response_format']='CONCISE'
        result=self.registry.call('codebase_search',args)
        self.assertFalse(result.is_error,result.content)
        self.assertEqual(args['response_format'],'CONCISE')
        data=json.loads(result.content)
        self.assertLessEqual(data['shown'],10)

    def test_invalid_output_is_not_forwarded(self):
        name='codebase_search';module=self.registry._tools[name][1]
        for bad in ['not JSON',json.dumps({'results':[]}), json.dumps(dict(query='export',query_valid=True,count=0,shown=1,results=[],truncated=False,index_age='today'))]:
            with self.subTest(bad=bad),patch.object(module,'run',return_value=bad):
                result=self.registry.call(name,self.example(name))
                self.assertTrue(result.is_error)
                self.assertIn('Invalid tool result',result.content)
                self.assertNotEqual(result.content,bad)

    def test_path_guard_and_exact_case(self):
        for path in ('../README.md','config/secrets.yaml','/tmp/file'):
            self.assert_denied_before_dispatch('codebase_read_file',dict(path=path,response_format='concise'),'path')
        result=self.registry.call('codebase_read_file',dict(path='src/report.ts',response_format='concise'))
        self.assertTrue(result.is_error)
        for path in ('src/reports.ts','src/Report.ts','src/report.tsx'):
            self.assertIn(path,result.content)

    def test_successful_contracts_for_all_tools(self):
        for name in self.registry.names():
            with self.subTest(name=name):
                result=self.registry.call(name,self.example(name))
                self.assertFalse(result.is_error,result.content)
                self.assertIn('truncated',json.loads(result.content))
        args=self.example('codebase_search');args['query']='no_match_expected_93847'
        result=self.registry.call('codebase_search',args)
        self.assertFalse(result.is_error)
        data=json.loads(result.content)
        self.assertEqual(data['count'],0)
        self.assertTrue(data['query_valid'])
