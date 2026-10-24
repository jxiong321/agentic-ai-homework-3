"""post_comment: write a comment on an issue. Public: whoever filed the issue can read it.

Its definition is post_comment.json. `idempotency_key` is not in the definition:
the model never sees or sets it. Your registry passes it (Assignment 3, Part C,
task 2), and the tracker accepts each key once.
"""


def run(ctx, number, body, idempotency_key=None):
    from harness.tracker import IssueNotFound
    from tools import ToolError

    if not str(body).strip():
        raise ToolError("Invalid body: supply a nonblank triage comment of at most 4000 characters, beginning with label: and file: lines.")
    if len(str(body)) > 4000:
        raise ToolError("body must be at most 4000 characters; shorten the comment.")
    try:
        comment = ctx.tracker.post_comment(ctx.run_id, int(number), str(body), key=idempotency_key)
    except IssueNotFound:
        raise ToolError(f"Invalid number: issue-{number} does not exist. Check the assigned issue number and use an existing issue; retrying this number unchanged will not succeed.")
    import json
    return json.dumps(dict(issue_id=f"issue-{number}", comment_id=f"comment-{comment['id']}", truncated=False))
