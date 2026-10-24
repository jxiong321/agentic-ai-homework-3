"""RepoMind's tools, and the registry that runs them.

Each tool is two files with one name: tools/<module>.json, its definition, the only
thing the model sees of it; and tools/<module>.py, the code that runs it. Rename a
tool inside its .json file and keep both file names. tools/roles.yaml says which
tool plays each of RepoMind's five roles (checks/FORMATS.md, section 11.2).

Assignment 3 starts with five definitions that are weak on purpose: generic names,
free-text filters, nothing said about an empty result, no cap on a response, no
examples. You rewrite them (Part A), and you make this registry check every call
at the boundary, return errors a model can repair from, key every write, verify a
write that failed, record every call and run a hook before each one (Parts A to C).

The registry's interface, which the runner, your ways and the checker use
(checks/FORMATS.md, section 11.3):

    registry = ToolRegistry(ctx)          # ctx is a RunContext, below
    registry.schemas                      # what the vendor gets: name, description, input_schema, strict
    registry.names()                      # the tools' names, in MODULES order
    registry.definition(name)             # the whole definition file, examples included
    registry.hooks.append(hook)           # hook(name, tool_input) runs before every call
    registry.call(name, tool_input, plan_step=None) -> ToolResult

A registry is bound to one run: every write is stamped with that run's ID. Build
one per run with `default_tools(ctx)`.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import importlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent

# The five modules, in the order the registry offers them. Keep these file names.
MODULES = ("read_issue", "search_repo", "read_file", "post_comment", "open_pr")

# The fields of a definition the vendor gets. Everything else in the file (the
# examples, notes of your own) stays here; examples are also rendered into description.
SENT = ("name", "description", "input_schema", "strict")


class ToolError(Exception):
    """A tool failed in a way the model can be told about. Becomes an is_error result."""


class TransientToolError(Exception):
    """Adapter-confirmed temporary failure. Writes require proof of no dispatch.

    retry_after is seconds; waits longer than MAX_RETRY_WAIT are not shortened.
    """
    def __init__(self, message, *, before_dispatch=False, retry_after=0.1):
        super().__init__(message)
        self.before_dispatch = before_dispatch
        self.retry_after = retry_after


MAX_ATTEMPTS = 3
MAX_RETRY_WAIT = 2.0
READ_MODULES = {"read_issue", "search_repo", "read_file"}
TEMPORARY_ERRNOS = {errno.EAGAIN, errno.EINTR, errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNREFUSED}


class WriteUnconfirmed(Exception):
    """Stop and ask a person: a write cannot be confirmed safely."""


class ProtocolError(Exception):
    """Logged integration failure; callers must stop without another model request."""


@dataclass
class ToolResult:
    content: str
    is_error: bool
    latency_s: float


@dataclass
class RunContext:
    run_id: str
    tracker: object                    # harness.tracker.Tracker
    repo_root: object                  # pathlib.Path to fixtures/repo
    calls: object = None               # harness.calls.CallRecord: runs/<run_id>.calls.jsonl
    harness_log: object = None         # pathlib.Path: runs/<run_id>.harness.log, for protocol errors
    switches: dict = field(default_factory=dict)   # harness.switches.current(), as the runner read them


def derive_write_key(run_id, plan_step, arguments):
    """Same intended action -> same SHA-256 key, independent of dict key order.

    An array separates components unambiguously. Keys are sorted recursively;
    compact JSON adds no formatting whitespace (whitespace inside text is kept).
    Non-planned callers use a null plan_step.
    """
    canonical = json.dumps([run_id, plan_step, arguments], sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_definition(module: str) -> dict:
    return json.loads((TOOLS_DIR / f"{module}.json").read_text())


class ToolRegistry:
    def __init__(self, ctx: RunContext, modules=MODULES):
        self.ctx = ctx
        self.hooks: list = [lambda name, arguments: None]
        self._tools: dict[str, tuple[dict, object]] = {}
        for module in modules:
            definition = load_definition(module)
            self._tools[definition["name"]] = (definition, importlib.import_module(f"tools.{module}"))

    @property
    def schemas(self) -> list[dict]:
        """The definitions as the vendor gets them, in MODULES order, ready for
        ModelClient.create(tools=...)."""
        schemas = []
        for definition, _ in self._tools.values():
            schema = {k: definition[k] for k in SENT if k in definition}
            examples = definition.get("examples", [])
            if examples:
                rendered = [
                    f"Example {i}: {json.dumps(example['input'], ensure_ascii=False)}\n"
                    f"When to use: {example['note']}"
                    for i, example in enumerate(examples, 1)
                ]
                schema["description"] = definition["description"] + "\n\nExamples:\n" + "\n\n".join(rendered)
            schemas.append(schema)
        return schemas

    def names(self) -> list[str]:
        return list(self._tools)

    def definition(self, name: str) -> dict:
        return self._tools[name][0]

    def log_error(self, event, **details):
        """Local diagnostic record, separate from model-facing feedback."""
        log = Path(self.ctx.harness_log) if self.ctx.harness_log else TOOLS_DIR.parent / "runs" / f"{self.ctx.run_id}.harness.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            fh.write(json.dumps({"event": event, "run_id": self.ctx.run_id, **details}, default=repr) + "\n")

    def record_attempt(self, name, arguments, plan_step, key, attempt, outcome, content, started):
        if self.ctx.calls is not None:
            self.ctx.calls.write(tool=name if isinstance(name, str) else repr(name), args=copy.deepcopy(arguments),
                                 plan_step=plan_step, key=key, attempt=attempt, outcome=outcome,
                                 is_error=outcome != 'ok', result=str(content)[:300],
                                 latency_s=time.monotonic()-started, cost_usd=0.0)

    def protocol_error(self, name, tool_input, reason, plan_step=None):
        self.log_error('protocol_error', tool=name, arguments=tool_input, reason=reason)
        self.record_attempt(name, tool_input, plan_step, None, 1, 'protocol', reason, time.monotonic())
        raise ProtocolError('Tool protocol error; see the harness log.')

    def check_hooks(self, name, arguments):
        for hook in self.hooks:
            try:
                reason = hook(name, copy.deepcopy(arguments))
            except Exception as exc:
                self.log_error('hook_error', tool=name, error=repr(exc))
                return 'Call denied: a pre-call policy hook failed. Ask the operator to repair the hook before retrying.'
            if reason is not None:
                return 'Call denied: ' + str(reason)[:700] + '. Resolve the policy restriction before retrying.'
        return None

    def existing_write(self, module, arguments, key):
        if module.__name__.endswith('.open_pr'):
            rows = self.ctx.tracker.prs(self.ctx.run_id, branch=arguments['branch'], state='open')
            return rows[0] if rows else None
        return self.ctx.tracker.comment_by_key(self.ctx.run_id, key)

    def receipt(self, module, row):
        if module.__name__.endswith('.open_pr'):
            return json.dumps(dict(issue_id=f"issue-{row['issue']}", pr_id=f"pr-{row['id']}",
                                   branch=row['branch'], draft=bool(row['draft']), truncated=False))
        return json.dumps(dict(issue_id=f"issue-{row['issue']}", comment_id=f"comment-{row['id']}", truncated=False))

    def read_back(self, module, arguments, key):
        try:
            return self.existing_write(module, arguments, key)
        except Exception as exc:
            self.log_error('verification_unavailable', tool=module.__name__, error=repr(exc))
            raise WriteUnconfirmed('Cannot determine whether the write exists; a person must check the tracker before resuming.') from exc

    @staticmethod
    def temporary(exc):
        return (isinstance(exc, (TransientToolError, TimeoutError, ConnectionError))
                or getattr(exc, 'errno', None) in TEMPORARY_ERRNOS)

    @staticmethod
    def retry_delay(exc, attempt):
        delay = exc.retry_after if isinstance(exc, TransientToolError) else 0.1 * 2 ** (attempt - 1)
        return max(0.0, float(delay))

    def execution_error(self, name, exc):
        if isinstance(exc, ToolError):
            return f'Error: {exc}'[:1000]
        self.log_error('tool_execution_error', tool=name, error=repr(exc))
        if isinstance(exc, OSError):
            return 'Error: Storage access failed: check the path, restore missing files/index, or correct access permissions. Repeating this call unchanged will not repair storage.'
        return 'Error: Tool implementation or stored data needs repair; ask the operator to inspect the harness log. Changing arguments or repeating this call cannot repair it.'

    def execute(self, name, module, arguments, *, idempotency_key=None, plan_step=None):
        from tools.validation import validate_output
        reading = module.__name__.split('.')[-1] in READ_MODULES
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            key = None if reading else (uuid.uuid4().hex if self.ctx.switches.get('key_mode', 'derived') == 'uuid' else idempotency_key)
            denied = self.check_hooks(name, arguments)
            if denied is not None:
                self.record_attempt(name, arguments, plan_step, key, attempt, 'denied', denied, started)
                raise ToolError(denied)
            if not reading:
                try:
                    existing = self.read_back(module, arguments, key)
                except WriteUnconfirmed as exc:
                    self.record_attempt(name, arguments, plan_step, key, attempt, 'error', exc, started)
                    raise
                if existing is not None:
                    content = self.receipt(module, existing)
                    validate_output(self.definition(name), content, arguments)
                    self.record_attempt(name, arguments, plan_step, existing.get('key') or key, attempt, 'ok', content, started)
                    return content
            try:
                sent = copy.deepcopy(arguments)
                if not reading:
                    sent['idempotency_key'] = key
                content = module.run(self.ctx, **sent)
                validate_output(self.definition(name), content, arguments)
            except Exception as exc:
                transient = self.temporary(exc)
                outcome = 'timeout' if not reading and isinstance(exc, (TimeoutError, ConnectionError, TransientToolError)) else 'error'
                self.record_attempt(name, arguments, plan_step, key, attempt, outcome, str(exc), started)
                if not reading:
                    # Every failed write is unknown until checked, including a
                    # malformed receipt after a successful tracker commit.
                    if self.ctx.switches.get('verify', 'on') != 'off':
                        existing = self.read_back(module, arguments, key)
                        if existing is not None:
                            content = self.receipt(module, existing)
                            validate_output(self.definition(name), content, arguments)
                            self.record_attempt(name, arguments, plan_step, existing.get('key') or key, attempt, 'ok', content, started)
                            return content
                    if not transient:
                        raise ToolError(self.execution_error(name, exc)) from exc
                    if attempt == MAX_ATTEMPTS:
                        raise WriteUnconfirmed('Write still unconfirmed after three attempts; a person must check the tracker.') from exc
                    delay = self.retry_delay(exc, attempt)
                    if delay > MAX_RETRY_WAIT:
                        raise WriteUnconfirmed(f'Write retry requires waiting {delay:g} seconds; pause for operator review before resuming.') from exc
                    self.log_error('write_retry', tool=name, attempt=attempt, key=key,
                                   verified=self.ctx.switches.get('verify', 'on') != 'off')
                    time.sleep(delay)
                    continue
                if not transient:
                    raise ToolError(self.execution_error(name, exc)) from exc
                delay = self.retry_delay(exc, attempt)
                can_retry = attempt < MAX_ATTEMPTS and delay <= MAX_RETRY_WAIT
                self.log_error('transient_error', tool=name, attempt=attempt, error=repr(exc), retry=can_retry, retry_after=delay)
                if not can_retry:
                    raise ToolError(f'Temporary service/storage failure: retry after {delay:g} seconds may work; stopped after {attempt} attempt(s). This was a read; no write was performed. Do not change arguments to repair a temporary outage.') from exc
                time.sleep(delay)
            else:
                self.record_attempt(name, arguments, plan_step, key, attempt, 'ok', content, started)
                return content

    def call(self, name: str, tool_input: dict, plan_step=None) -> ToolResult:
        start = time.monotonic()
        if not isinstance(name, str) or not name.strip():
            self.protocol_error(name, tool_input, 'Malformed request: tool name must be a nonempty string.', plan_step)
        if not isinstance(tool_input, dict):
            self.protocol_error(name, tool_input, 'Malformed request: arguments must be a JSON object.', plan_step)
        entry = self._tools.get(name)
        if entry is None:
            self.protocol_error(name, tool_input, f'Unknown tool {name!r}; registered tools: {self.names()!r}.', plan_step)
        definition, module = entry
        from tools.validation import validate_input
        try:
            arguments = copy.deepcopy(validate_input(definition, tool_input, self.ctx, module.__name__.split('.')[-1]))
        except ToolError as exc:
            self.record_attempt(name, tool_input, plan_step, None, 1, 'rejected', exc, start)
            return ToolResult(f'Error: {exc}'[:1000], True, time.monotonic()-start)
        key = (derive_write_key(self.ctx.run_id, plan_step, arguments)
               if module.__name__.split('.')[-1] not in READ_MODULES else None)
        try:
            content = self.execute(name, module, arguments, idempotency_key=key, plan_step=plan_step)
            return ToolResult(content, False, time.monotonic()-start)
        except ToolError as exc:
            message = str(exc)
            return ToolResult((message if message.startswith('Error:') else 'Error: '+message)[:1000], True, time.monotonic()-start)


def default_tools(ctx: RunContext) -> ToolRegistry:
    return ToolRegistry(ctx)
