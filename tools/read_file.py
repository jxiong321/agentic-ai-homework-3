"""Return bounded file content and metadata, checking exact path casing.

Concise reads cap content at 4000 characters; detailed reads at 20000.
An explicit path inventory prevents case-insensitive disks opening a near match.
"""

import json
from pathlib import Path

MAX_CHARS = 20_000   # a longer file comes back cut, with a note saying so


def run(ctx, path, response_format="concise"):
    from harness.formats import normalize_path
    from tools import ToolError
    from tools.search_repo import EXCLUDED_DIRS

    rel = normalize_path(str(path))
    if rel in (None, "none"):
        raise ToolError("Invalid path: use a nonempty repository-relative file path from search, not none.")
    root = Path(ctx.repo_root).resolve()
    target = (root / rel).resolve()
    if root != target and root not in target.parents:
        raise ToolError("Invalid path: choose a file inside the repository; absolute paths and traversal are not allowed.")
    parts = target.relative_to(root).parts
    if set(parts) & EXCLUDED_DIRS:
        raise ToolError("Invalid path: choose a file outside config, node_modules and .git; retries cannot grant access.")
    exact_paths = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if rel not in exact_paths:
        import difflib
        matches = difflib.get_close_matches(rel, sorted(exact_paths), n=3, cutoff=0.6)
        raise ToolError(f"Invalid path: use an exact case-sensitive repository path. Near matches: {', '.join(matches) or 'none'}. Requested: {str(path)[:120]!r}. Correct the path before retrying.")
    if not target.is_file():
        raise ToolError("Invalid path: the file is missing or is not a regular file. Search again and choose an existing text file before retrying.")
    try:
        text = target.read_text()
    except UnicodeDecodeError:
        raise ToolError("Invalid path: this is not a readable text file. Choose a text/code file from search; retrying this binary file will not work.")
    if response_format not in ("concise", "detailed"):
        raise ToolError("response_format must be concise or detailed.")
    cap = 4000 if response_format == "concise" else MAX_CHARS
    return json.dumps(dict(path=rel, content=text[:cap], truncated=len(text) > cap, total_chars=len(text)))
