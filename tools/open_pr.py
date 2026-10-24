"""open_pr: open a draft pull request on the mock remote. New in Assignment 3.

Its definition is open_pr.json. The mock remote needs no commits: a PR is a branch,
a title and a body, stored in the tracker's database. `idempotency_key` is not in
the definition: your registry passes it, as for post_comment.
"""


def run(ctx, number, branch, title, body, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    if branch != f"repomind/issue-{number}":
        raise ToolError(f"branch must be repomind/issue-{number}.")
    for field, value, cap in (("title", title, 200), ("body", body, 4000)):
        if not str(value).strip() or len(str(value)) > cap:
            raise ToolError(f"{field} must be nonblank and at most {cap} characters.")
    try:
        pr = ctx.tracker.open_pr(ctx.run_id, int(number), str(branch), str(title), str(body), key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"Invalid number: issue-{number} does not exist. Check the assigned issue number and use an existing issue; retrying this number unchanged will not succeed.")
    import json
    return json.dumps(dict(issue_id=f"issue-{number}", pr_id=f"pr-{pr['id']}", branch=branch, draft=True, truncated=False))
