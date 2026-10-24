"""Literal case-insensitive content search with explicit metadata.

Uses the prebuilt index or current disk files, excludes protected directories,
and reports counts, truncation and index age. Malformed searches raise ToolError;
a well-formed search with zero matches returns a successful empty results list.
"""

from __future__ import annotations

import fnmatch
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRS = {"config", "node_modules", ".git"}
HARD_CAP = 20
MAX_QUERY_CHARS = 200
INDEX = "fixtures/search_index/index.json"
GLOB_CHARS = re.compile(r"^[A-Za-z0-9_.\-/*?\[\]{},]+$")


def glob_problem(pattern: str) -> str | None:
    """Why `pattern` is not a valid path glob, or None when it is one."""
    if pattern.startswith("/"):
        return "a glob is relative to the repository root; it cannot start with /"
    if ".." in pattern.split("/"):
        return "a glob cannot leave the repository (..)"
    if not GLOB_CHARS.match(pattern):
        return "a glob uses letters, digits, / . _ - and the wildcards * ? [ ] { }; no spaces, colons or quotes"
    depth = 0
    for ch in pattern:
        depth += {"[": 1, "]": -1}.get(ch, 0)
        if depth not in (0, 1):
            return "a glob's [ and ] must pair up"
    if depth:
        return "a glob's [ and ] must pair up"
    if pattern.count("{") != pattern.count("}"):
        return "a glob's { and } must pair up"
    return None


def problem(query, filter=None) -> str | None:
    """Why this search is malformed, or None when it is well-formed."""
    text = str(query or "")
    if not text.strip():
        return "the query is empty"
    if len(text) > MAX_QUERY_CHARS:
        return f"the query is {len(text)} characters long; the cap is {MAX_QUERY_CHARS}"
    if filter not in (None, ""):
        return glob_problem(str(filter))
    return None


def _expand(pattern: str) -> list[str]:
    """{a,b} alternatives, which fnmatch does not know."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    return [p for option in match.group(1).split(",")
            for p in _expand(pattern[:match.start()] + option + pattern[match.end():])]


def _matches(path: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    return any(fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path, p.replace("**/", ""))
               for p in _expand(pattern))


def load_index(root: Path) -> dict:
    return json.loads((Path(root) / INDEX).read_text())


def _disk(repo_root: Path) -> dict[str, list[str]]:
    files = {}
    for path in sorted(Path(repo_root).rglob("*")):
        rel = path.relative_to(repo_root)
        if path.is_file() and not (set(rel.parts) & EXCLUDED_DIRS):
            try:
                files[rel.as_posix()] = path.read_text().splitlines()
            except UnicodeDecodeError:
                continue
    return files


def age(built_at: str, now: float | None = None) -> str:
    built = datetime.strptime(built_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    days = int(((now or time.time()) - built.timestamp()) // 86400)
    return "today" if days < 1 else f"{days} day{'s' if days != 1 else ''} ago"


def run(ctx, query, max_results=None, path_glob=None, deep=False, response_format="concise"):
    from tools import ToolError
    issue = problem(query, path_glob)
    if issue:
        raise ToolError(f"Invalid query or path_glob: {issue}. Use 1–200 nonblank query characters and a repository-relative glob or null.")
    if response_format not in ("concise", "detailed"):
        raise ToolError("response_format must be concise or detailed.")
    if max_results is not None and (type(max_results) is not int or not 1 <= max_results <= 20):
        raise ToolError("max_results must be an integer from 1 to 20, or null for 10.")
    repo_root = Path(ctx.repo_root)
    if deep:
        files, index_age = _disk(repo_root), "live disk"
    else:
        index = load_index(repo_root.parent.parent)
        files, index_age = index["files"], age(index["built_at"])
    concise = response_format == "concise"
    limit = min(max_results or 10, 10 if concise else 20)
    excerpt_cap = 160 if concise else 500
    needle = query.strip().lower()
    hits = [{"path": rel, "line": number, "excerpt": line.strip()}
            for rel, lines in sorted(files.items()) if _matches(rel, path_glob)
            for number, line in enumerate(lines, 1) if needle in line.lower()]
    shown = hits[:limit]
    truncated = len(hits) > limit or any(len(h["excerpt"]) > excerpt_cap for h in shown)
    shown = [dict(h, excerpt=h["excerpt"][:excerpt_cap]) for h in shown]
    return json.dumps(dict(query=query, query_valid=True, count=len(hits), shown=len(shown),
                           results=shown, truncated=truncated, index_age=index_age))
