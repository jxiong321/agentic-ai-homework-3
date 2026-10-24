"""Local tool contracts: validate arguments before dispatch and results afterward."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from harness.schema import errors


def normalize_enums(value, schema):
    """Only enum strings are normalized; queries, bodies and paths keep their case."""
    if isinstance(value, str):
        for option in schema.get('enum', []):
            if isinstance(option, str) and value.casefold() == option.casefold():
                return option
    if isinstance(value, dict):
        return {k: normalize_enums(v, schema.get('properties', {}).get(k, {})) for k,v in value.items()}
    if isinstance(value, list):
        return [normalize_enums(v, schema.get('items', {})) for v in value]
    return copy.deepcopy(value)


def validate_input(definition, value, ctx, module):
    from tools import ToolError
    from tools.search_repo import problem, EXCLUDED_DIRS
    schema = definition['input_schema']
    value = normalize_enums(value, schema)
    broken = errors(value, schema)
    if broken:
        raise ToolError('Invalid arguments: correct the named fields before retrying. ' + '; '.join(broken)[:700])
    def fail(field, repair):
        raise ToolError(f'Invalid {field}: {repair}')
    if 'number' in value and value['number'] <= 0:
        fail('number', 'use a positive integer issue number.')
    if module == 'search_repo':
        why = problem(value['query'], value['path_glob'])
        if why:
            field = 'query' if not value['query'].strip() or len(value['query']) > 200 else 'path_glob'
            fail(field, why + '; use 1–200 nonblank query characters and a repository-relative glob or null.')
        if value['path_glob'] == '':
            fail('path_glob', 'use null for no path restriction, or a nonempty glob such as src/*.ts.')
        limit = value['max_results']
        if limit is not None and not 1 <= limit <= 20:
            fail('max_results', 'use an integer from 1 to 20, or null for 10.')
    if module == 'read_file':
        path = value['path']
        if not path.strip() or path == 'none' or '\\' in path or Path(path).is_absolute() or '..' in Path(path).parts:
            fail('path', 'use a nonempty repository-relative path from search, with / separators and no .. segments.')
        root = Path(ctx.repo_root).resolve()
        target = (root / path).resolve()
        if root not in target.parents or set(Path(path).parts) & EXCLUDED_DIRS:
            fail('path', 'choose a file inside the repository, outside config, node_modules and .git.')
    for field, cap in [('title', 200), ('body', 4000)]:
        if field in value and (not value[field].strip() or len(value[field]) > cap):
            fail(field, f'use nonblank text of at most {cap} characters.')
    if module == 'open_pr' and value['branch'] != f"repomind/issue-{value['number']}":
        fail('branch', f"use repomind/issue-{value['number']}.")
    return value


def validate_output(definition, content, args):
    from tools import ToolError
    try:
        result = json.loads(content)
    except (ValueError, TypeError):
        raise ToolError('Invalid tool result: expected a JSON object matching the declared output schema. The tool implementation needs repair; do not retry a write blindly.')
    broken = errors(result, definition['output_schema'])
    if broken:
        raise ToolError('Invalid tool result: ' + '; '.join(broken)[:600] + '. The tool implementation needs repair; do not retry a write blindly.')
    def require(ok, message):
        if not ok:
            raise ToolError('Invalid tool result: ' + message + '. The tool implementation needs repair; do not retry a write blindly.')
    if 'query_valid' in result:
        require(result['query'] == args['query'], 'query must echo the requested query')
        require(result['count'] >= result['shown'] >= 0, 'counts must be nonnegative and count >= shown')
        require(result['shown'] == len(result['results']), 'shown must equal the results length')
        concise = args['response_format'] == 'concise'
        require(result['shown'] <= min(args['max_results'] or 10, 10 if concise else 20), 'result count exceeds requested cap')
        for hit in result['results']:
            require(hit['line'] > 0 and len(hit['excerpt']) <= (160 if concise else 500), 'line number or excerpt violates its limits')
            require(bool(hit['path']) and not Path(hit['path']).is_absolute() and '..' not in Path(hit['path']).parts, 'result path must be repository relative')
        require(result['count'] == result['shown'] or result['truncated'], 'omitted matches must be marked truncated')
        require(bool(result['index_age']), 'index_age must be present and nonempty')
    if 'total_chars' in result:
        from harness.formats import normalize_path
        require(result['path'] == normalize_path(args['path']), 'path must match the requested file after relative-path normalization')
        require(result['total_chars'] >= len(result['content']), 'total_chars cannot be smaller than content')
        require(len(result['content']) <= (4000 if args['response_format']=='concise' else 20000), 'file content exceeds its cap')
        require(result['truncated'] == (result['total_chars'] > len(result['content'])), 'file truncation flag disagrees with length')
    if 'issue_id' in result:
        require(result['issue_id'] == f"issue-{args['number']}", 'issue_id must match the requested issue')
    for key,cap in [('title',1000),('author',200),('opened',100),('body',8000)]:
        if key in result:
            require(len(result[key]) <= cap, key + ' exceeds its cap')
    for key,prefix in [('comment_id','comment-'),('pr_id','pr-')]:
        if key in result:
            require(result[key].startswith(prefix) and result[key][len(prefix):].isdigit(), key + ' must use a semantic identifier')
    if 'branch' in result:
        require(result['branch'] == args['branch'], 'branch must match the request')
    return result
