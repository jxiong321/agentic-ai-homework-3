"""read_issue: return one issue from the tracker. Untrusted content: anyone can file an issue.

Its definition, the only thing the model sees, is read_issue.json.
"""


def run(ctx, number):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    try:
        issue = ctx.tracker.issue(int(number))
    except IssueNotFound:
        raise ToolError(f"Invalid number: issue-{number} does not exist. Check the assigned issue number and use an existing issue; retrying this number unchanged will not succeed.")
    import json
    caps = {"title": 1000, "author": 200, "opened": 100, "body": 8000}
    values = {key: str(issue[key]) for key in caps}
    return json.dumps(dict(issue_id=f"issue-{issue['number']}",
                           truncated=any(len(values[k]) > cap for k, cap in caps.items()),
                           **{k: values[k][:cap] for k, cap in caps.items()}))
