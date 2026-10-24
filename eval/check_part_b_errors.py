"""Part B task 5: direct registry checks; no model calls or writes to the tracker."""
import json
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import RunContext,ToolRegistry,ProtocolError
from harness.tracker import Tracker

def main():
    log=ROOT/'runs'/'part-b-errors.harness.log'
    with tempfile.TemporaryDirectory() as tmp:
        tracker=Tracker(root=ROOT,state_dir=Path(tmp),flaky=False)
        registry=ToolRegistry(RunContext('part-b-errors',tracker,ROOT/'fixtures/repo',harness_log=log))
        try:registry.call('nonexistent_tool',{'number':4191})
        except ProtocolError:
            assert 'nonexistent_tool' in log.read_text()
            print('Unknown tool: ProtocolError; full details saved to runs/part-b-errors.harness.log.')
        else:raise AssertionError('unknown tool must stop')
        for name,args in [('tracker_read_issue',{'number':'not-an-integer'}),('codebase_read_file',{'path':'src/report.ts','response_format':'concise'})]:
            result=registry.call(name,args)
            assert result.is_error
            print(json.dumps(dict(tool=name,is_error=result.is_error,content=result.content)))
        assert all(path in result.content for path in ('src/reports.ts','src/Report.ts','src/report.tsx'))
    print('Direct error checks passed; no model tokens spent.')

if __name__=='__main__':main()
