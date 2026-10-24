"""Summarize Part C development evidence from the tracker and call records."""
import json
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    db=sqlite3.connect(ROOT/'tracker/tracker.db');db.row_factory=sqlite3.Row
    results=[]
    for path in sorted((ROOT/'runs').glob('planned-419*-*.jsonl')):
        if path.name.endswith('.calls.jsonl'):continue
        records=[json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        if not records:continue
        start=records[0];switches=start.get('switches',{})
        if not switches.get('flaky_writes') or records[-1]['type']!='run_end':continue
        run=start['run_id'];calls_path=ROOT/'runs'/f'{run}.calls.jsonl'
        calls=[json.loads(x) for x in calls_path.read_text().splitlines()] if calls_path.exists() else []
        comments=[dict(r) for r in db.execute('select * from comments where run_id=?',(run,))]
        prs=[dict(r) for r in db.execute('select * from prs where run_id=?',(run,))]
        attempts=[dict(r) for r in db.execute('select * from attempts where run_id=?',(run,))]
        recorded={(r['role'],r['key']) for r in calls if r['outcome'] in ('ok','timeout')}
        matched=all((role,r['key']) in recorded for role,rows in [('comment',comments),('open_pr',prs)] for r in rows)
        ends=[r['terminal_reason'] for r in records if r['type']=='end']
        results.append(dict(run_id=run,sweep=start.get('sweep'),backend=start['backend'],readback_fail=switches.get('readback_fail'),terminal_reason=ends[-1] if ends else None,comments=len(comments),prs=len(prs),committed_timeouts=sum(r['outcome']=='timeout_after_commit' for r in attempts),timed_out_pr=any(r['kind']=='pr' and r['outcome'].startswith('timeout') for r in attempts),all_writes_recorded=matched))
    db.close()
    target=ROOT/'reports/PART_C_DEV_CHECKS.json';target.write_text(json.dumps(results,indent=2)+'\n')
    for backend in sorted({r['backend'] for r in results}):
        for fail in (False,True):
            rows=[r for r in results if r['backend']==backend and r['readback_fail']==fail]
            if not rows:continue
            print(json.dumps(dict(backend=backend,readback_fail=fail,runs=len(rows),completed=sum(r['terminal_reason']=='completed' for r in rows),escalated=sum(r['terminal_reason']=='escalated' for r in rows),duplicate_runs=sum(r['comments']>1 or r['prs']>1 for r in rows),committed_timeouts=sum(r['committed_timeouts'] for r in rows),all_writes_recorded=all(r['all_writes_recorded'] for r in rows),comments_after_uncertain_pr=sum(r['comments']>0 for r in rows if fail and r['timed_out_pr']))))
    assert all(r['all_writes_recorded'] for r in results),'A tracker write is missing its call record'

if __name__=='__main__':main()
