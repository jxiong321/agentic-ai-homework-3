# Assignment 3 · Tool design and safe writes

These results use the original 24-run batch. I also report the follow-up experiment and why we rolled it back. Lecture references use PDF page numbers.

## Part A · The five definitions

### Strict mode and schema counts

All five tools request strict mode. There are **0 optional parameters and 2 union-typed parameters**: search’s `max_results` accepts an integer or null, and `path_glob` accepts a string or null. Both fields must be present. Null means “use the default limit” or “do not restrict the paths.”

Every input object rejects extra properties. The schemas contain 14 properties total and one object level, so they fit the assignment’s limits. Lengths, ranges and other content rules are checked in code. `make audit` passes.

Gemini accepted all five current definitions with `strict: true` in the saved ping at `2026-10-23T19:58:00` (definition hash `8a5ce6be549bcafc`). That is why the report says `compiles: true`. Its [native documentation](https://ai.google.dev/gemini-api/docs/function-calling) describes validated function calling, but the [OpenAI-compatible endpoint documentation](https://ai.google.dev/gemini-api/docs/openai) does not clearly establish enforcement of this flag. Acceptance is not proof of enforcement, so we still validate every call ourselves. This follows the lecture’s distinction between valid structure and correct content (pp. 25–27).

### Consolidation

I kept the five tools separate because searches and reads can branch or repeat, the PR is conditional, and each write needs its own outcome check. There was no fixed sequence worth combining into one tool.

### Search before and after

These are the actual definition fields, shown side by side. The starter is preserved at commit `ed6b2e9cba6a548af2c144a767dd7cc6f704866d`.

| Field | Starter | Rewritten |
|---|---|---|
| Name | `"search_repo"` | `"codebase_search"` |
| Description | `"Search the code."` | `"Search literal text, case-insensitively, in repository file contents (not filenames). Excludes config, node_modules and .git. Returns query, query_valid, count (all matching lines), shown, results (path, line, excerpt), truncated, and index_age. Zero matches is success with count=0 and query_valid=true; an empty/whitespace query, query over 200 characters, or malformed path glob is an error. Defaults to concise: at most 10 hits with 160-character excerpts; detailed allows 20 hits with 500-character excerpts. truncated indicates omitted matches or shortened excerpts. index_age reports how old the index is, or live disk for deep search."` |
| Input type | `"object"` | `"object"` |
| query | `{"type": "string", "description": "Text to look for"}` | `{"type": "string", "description": "Literal text to find, 1–200 characters and not whitespace-only. Use a distinctive code term or error string; broad terms consume more result space."}` |
| max_results | `{"type": "integer", "description": "How many results. Default 10."}` | `{"type": ["integer", "null"], "description": "Maximum matching lines, 1–20; null uses 10. Smaller limits save context; concise additionally caps results at 10."}` |
| filter | `{"type": "string", "description": "Optional filter expression"}` | Not declared |
| path_glob | Not declared | `{"type": ["string", "null"], "description": "Restrict matching repository-relative paths using a glob such as src/*.ts; null searches all indexed paths. Supports *, ?, brackets and {a,b}; no SQL, free-text filter syntax, absolute paths or .. segments. Restriction reduces results."}` |
| deep | `{"type": "boolean", "description": "Whether to do a deep search. Default false."}` | `{"type": "boolean", "description": "False uses the cheaper prebuilt index; true scans current files from disk, costing more local I/O. Choose true when index age makes freshness uncertain."}` |
| response_format | Not declared | `{"type": "string", "description": "Choose concise by default to save context; detailed returns more code when the shorter result is insufficient.", "enum": ["concise", "detailed"]}` |
| Required fields | `["query"]` | `["query", "max_results", "path_glob", "deep", "response_format"]` |
| additionalProperties | Not declared | `false` |
| strict | Not declared | `true` |

The starter has no examples. The rewritten definition adds these two examples, in this order; the registry appends their inputs and notes to the description sent to the vendor:

```json
[
  {
    "input": {
      "query": "export",
      "max_results": null,
      "path_glob": null,
      "deep": false,
      "response_format": "concise"
    },
    "note": "Typical: begin with a cheap indexed literal-text search, the default ten-result limit, and no path restriction."
  },
  {
    "input": {
      "query": "export",
      "max_results": 20,
      "path_glob": "src/*.{ts,tsx}",
      "deep": true,
      "response_format": "detailed"
    },
    "note": "Hard case: if earlier results were truncated and the index may be stale, search current TypeScript files with a larger result budget. The glob filters paths; query still searches file contents. This costs more disk I/O and context; zero matches remains a valid result."
  }
]
```

The rewrite gives the model clearer choices: what to search, how to limit it, and when a result is empty or incomplete. The filter is a documented glob, not an open-ended query language. Names such as `tracker_read_issue` identify the service, and IDs such as `issue-4191` identify the result. Response caps and examples support the six design rules; they do not replace semantic IDs as rule six (lecture pp. 15–24).

### Boundary validation

Before a tool runs, the registry checks required fields, types, extra arguments, case-insensitive enum values, and content rules. It also checks the returned JSON against a local output schema. A rejected call gets an error explaining what to fix. Paths are checked against the actual file list, including case.

The renamed tools completed the two initial real-model development runs, `planned-4191-s01-9fd590` and `planned-4192-s01-950a7e`. Local tests also verify that invalid arguments never reach the tool and malformed results are not returned as successes. These checks protect the interface; they do not prove the agent picked the right diagnosis.

## Part B · Errors

### Failure classifications

| Tool | Transient | Permanent | Ambiguous |
|---|---|---|---|
| `tracker_read_issue` | Temporary tracker unavailability | Invalid or nonexistent issue | None: no write occurs |
| `codebase_search` | Temporary storage failure | Invalid query, glob, limit or format; missing/corrupt index | None: no write occurs |
| `codebase_read_file` | Temporary storage failure | Missing, incorrectly cased, excluded or non-text file; invalid format | None: no write occurs |
| `tracker_post_comment` | Transport failure confirmed before dispatch | Invalid issue or blank/oversized body | Timeout after dispatch: the comment may already exist |
| `pulls_open_draft` | Transport failure confirmed before dispatch | Invalid issue, branch, title or body | Timeout after dispatch: the PR may already exist |

“Permanent” means repeating the same call will not fix it. Changing a wrong filename can fix the request. A transient failure may succeed unchanged later. An ambiguous failure needs verification because we do not know whether the write happened. The tracker gives the same timeout before and after a commit, so our code cannot assume which occurred. The transient examples above describe possible failures; they were tested with injected faults, not all observed live (lecture p. 42).

### Protocol policy and repair feedback

I chose **`end_run`** for protocol errors. An unknown tool or non-object argument payload is logged in full, and the run ends with `tool_error`. No further model request is made. Rewording arguments cannot make an unavailable tool exist.

Invalid arguments to a known tool are execution errors. They return `is_error: true`, explain the correction first, and are capped at 1,000 characters. This gives the model something useful to act on instead of a raw exception (lecture pp. 43–45).

The exact near-match error is:

```text
Error: Invalid path: use an exact case-sensitive repository path. Near matches: src/reports.ts, src/report.tsx, src/Report.ts. Requested: 'src/report.ts'. Correct the path before retrying.
```

### Retries and checks

Temporary failures are retried in code, up to three total attempts, with ordinary waits of 0.1 and 0.2 seconds. A requested delay above two seconds is returned for later handling rather than shortened. Permanent failures are not retried automatically. Write failures follow Part C’s verification gate before any retry.

`eval/check_part_b_errors.py` tests an unknown tool, malformed arguments and the near-match path without using model tokens. All three checks pass. The course error-contract check scores 10/10.

## Part C · Writes that may already have happened

### Key formula

```text
SHA256(UTF8(JSON([run_id, plan_step, validated_arguments],
                sort_keys=True, separators=(",", ":"), ensure_ascii=False)))
```

The harness computes the key, not the model. It sorts object keys and removes formatting whitespace while preserving whitespace inside text. Each retry sends the same arguments and key. A new run gets a new key because it is a separate experiment. The tracker enforces uniqueness and returns the existing result for a repeated key (lecture pp. 46–47).

### Draft, PR, then comment

The plan must contain exactly one PR step immediately before one final comment step. The executor prepares the comment and applies the configured second pass before either write. A held draft stops the run. If the draft says `file: none`, an executor check skips the PR. Otherwise, the PR body must name that file. The final step posts the saved draft unchanged.

The comment comes last because a PR can be closed, but a comment someone has already read cannot be taken back (lecture p. 50).

### Check, verify, then retry

Before every attempt, the code looks for this run’s existing PR by branch or comment by key. After a failed write:

- **It happened:** use the existing result and continue.
- **It did not happen:** retry a temporary failure with the same arguments and key.
- **We cannot tell:** stop with `escalated` and ask a person to check.

A write gets at most three attempts. An uncertain PR prevents the comment from being posted. This is the lecture’s three-exit verification rule (p. 49).

Every attempt has an independent record with its arguments, key, outcome, result, latency and cost. A pre-call hook can deny it; if the hook crashes, the call is also denied. Local tool cost is zero (lecture p. 51).

For the control, `KEY_MODE=uuid` creates a fresh key per attempt and `VERIFY=off` skips post-failure verification. Pre-write checks and the three-attempt limit remain. A branch can still identify an existing PR, but a new comment key cannot identify an earlier comment.

### Development evidence

Scripted tests verified recovery after both pre-commit and post-commit timeouts, escalation when readback fails, the `none` skip, held drafts, and fail-closed hooks. They also produced duplicate comments under the control switches.

In real-model development sweeps 4–6, five of six normal flaky runs completed with one PR and one comment; seven committed timeouts were recovered without duplicates. One run rejected three invalid plans and never wrote. With readback failure enabled, four runs escalated and two completed. The three uncertain-PR runs posted no comment. All stored writes matched their call records.

Here is one actual timeout record from the scripted development tests. A timeout record means the outcome was unknown at that moment; it does not mean the write was absent.

```json
{
  "run_id": "planned-4191-s01-d45ef9",
  "t": 0.374,
  "tool": "pulls_open_draft",
  "role": "open_pr",
  "args": {
    "number": 4191,
    "branch": "repomind/issue-4191",
    "title": "Fix for issue 4191",
    "body": "Proposed change in src/ingest/dedupe.ts: the cause the triage names."
  },
  "plan_step": 4,
  "key": "9c11e55943be7cd72c39ddf57b1a044bb34e3789718c644dcef6886f1ac67d44",
  "attempt": 1,
  "outcome": "timeout",
  "is_error": true,
  "result": "the tracker did not answer in time",
  "latency_s": 0.014,
  "cost_usd": 0.0
}
```

## Part D · Measure

<!-- PART_D_MEASUREMENTS_START -->
### Surface cost

`eval/price_surface.py` sends the same small request with and without the surface being measured, then subtracts `prompt_tokens`, including cached tokens. Each single-tool count includes the provider’s tool-use preamble.

| Surface | Starter tokens | Rewritten tokens |
|---|---:|---:|
| Issue read | 51 | 243 |
| Search | 114 | 644 |
| File read | 48 | 321 |
| Comment | 70 | 337 |
| PR | 103 | 511 |
| All five together | 386 | 2056 |
| Planner/reviser list | 117 | 1337 |

The harness averaged **5.6667 model calls per run**. For each call, I charged the measured definitions it carried, plus the text list on planner/reviser calls. The unchanged `submit_plan` schema is excluded. The all-five comparison charges all five definitions on every call, without an additional list.

At **$0.30 per million input tokens**:

| Comparison | Mean surface tokens/run | Calculation | Cost/run |
|---|---:|---|---:|
| Starter | 559.25 | 559.25 × 0.30 / 1,000,000 | $0.000167775 |
| Rewritten | 4621.8333 | 4621.8333 × 0.30 / 1,000,000 | $0.00138655 |
| All five on every call | 11650.6667 | 11650.6667 × 0.30 / 1,000,000 | $0.00349520 |

The rewrite costs more because it adds usable descriptions, constraints, result meanings and examples. Offering only the needed tool saves **$0.00210865 per mean run**, about 60% against the all-five comparison. These are definition costs, not the whole run’s bill. Caching can reduce the price without reducing context use (lecture p. 30).

### Tracker results

`eval/measure_03.py` counts writes and committed timeouts from SQLite by run ID, checks them against call records, and reads terminal outcomes from traces.

| Measure | Harness | Control |
|---|---|---|
| Comments per run | 11 runs: one; 1 run: zero | 5 runs: one; 3 runs: zero; 1 run: two; 3 runs: three |
| PRs per run | 9 runs: one; 3 runs: zero | 8 runs: one; 4 runs: zero |
| Correct PR count/branch | 12/12 | 11/12 |
| Committed timeouts | 5 | 13 |
| Escalated runs | 1 | 6 |
| Grounded triage passes | 4/12 | 2/12 |

PR-count correctness means agreement with the posted comment, not that the chosen file is right. A no-comment/no-PR run passes that count check but still fails triage. Grounded success requires exactly one comment with the correct label and file. Duplicate comments fail even when their text is correct.

### Predictions compared with results

The original predictions were committed alone as `3e2c73b` and pushed before evaluation. They remain unchanged.

- **Harness:** predicted zero duplicate comments and PRs; observed zero. However, one run failed to produce any write because its plans were invalid.
- **Control:** predicted six extra comments across five runs; observed seven across four. Three runs each added two extra comments, and one added one: `3 × 2 + 1 = 7`. I underestimated repeats within a run and overestimated how many runs would duplicate. Zero duplicate PRs was correct: branch checks protected both arms.
- **Most misused tool:** predicted search, but the two explicit argument/path failures were file reads. By that measure, the prediction missed. A valid search can still be unhelpful without raising an error, so this does not prove every search was appropriate.

### Four shapes of misuse

The lecture’s four shapes are below. **Wrong tool/valid call** and **correct call/misread result** are the two that can return a well-formed result without revealing the mistake. Double-posting is a separate execution failure (pp. 11, 65).

1. **Right tool, wrong arguments.** Types, enums and content checks narrow this. In `planned-4202-s02-f199a9`, the file reader rejected nonexistent `src/Export.ts` and offered alternatives. The agent still posted that filename afterward. The error made repair possible; it did not guarantee repair.
2. **Wrong tool, valid call.** Namespaces clarify each tool’s role, and each fill request offers only its planned tool. Neither arm recorded an off-plan event. For example, `planned-4201-s01-11e267` used the issue read, search, file read, PR and comment in their intended roles. This shows correct selection, but not that descriptions alone caused it: both arms share the surface and executor restrictions.
3. **Correct call, misread result.** Explicit counts, validity and truncation make results easier to interpret. In `planned-4204-s02-91609b`, `Monday summary` returned `count: 0`, `query_valid: true`, and `truncated: false`. The agent then tried a nonexistent path and posted an unsupported file. The response made the lack of evidence clear, but did not ensure a grounded answer. We cannot infer the model’s exact internal interpretation from the trace.
4. **No call at all.** Descriptions cannot force an agent to investigate. Three original runs made no tool calls because invalid plans were rejected: `planned-4203-s01-2b9b73`, `planned-4204-s03-79f971`, and `planned-4204-s04-c517bd`. These are zero-call outcomes, not evidence that the agent chose to answer from memory. A related omission occurred in `planned-4206-s04-f45cb6`: it named `src/exportUtils.ts` without reading that file, after reading a different one. To detect missing investigation, we need to label whether tools were needed, inspect the calls, and compare against known answers and required evidence—not just count tool errors (lecture pp. 36–37).

The lecture’s 36% no-tool-use figure refers to MCP-Atlas **v1**. Its final reading slide notes later revisions; our small experiment does not establish that percentage (p. 69).

Our write protection worked against duplicates in the tested runs. Diagnosis was still weak: only 4/12 harness runs passed triage. Safe execution and correct answers are different things.

<!-- PART_D_MEASUREMENTS_END -->

## Transparent follow-up experiment and rollback

After the first batch, we added complete step-format examples and included the rejected plan in repair requests (`5ba900c`). Validation and the three-attempt bound stayed unchanged; no evaluation answers were added. All six development runs completed, but the follow-up evaluation was worse.

| Measure | Original harness | Follow-up harness | Original control | Follow-up control |
|---|---:|---:|---:|---:|
| Runs | 12 | 12 | 12 | 12 |
| Escalated | 1 | 3 | 6 | 6 |
| Runs with duplicate comments | 0 | 0 | 4 | 7 |
| Correct PR count/branch | 12 | 12 | 11 | 12 |
| Committed timeouts | 5 | 8 | 13 | 13 |
| Grounded triage passes | 4 | 4 | 2 | 0 |

The automated score fell from **81.33/82 to 80/82**. This small comparison does not prove the prompt change caused the decline, but it did not show a reliable improvement. We restored the original code and complete original batch as the active checker inputs. No runs were mixed across batches.

The original code and evidence are preserved at `e6cce1c74a9430b5d0feefe804ed8ac694e21845`, with report copies in `reports/batches/original/`. The follow-up’s reports, traces, database and changed planner remain in `reports/batches/followup/`. Both outcomes and our selection of the original batch are disclosed; acceptance for grading is up to the instructor.

## AI assistance

I used OpenAI Codex to help write and debug the code, generate results tables, and run automated checks. For the written answers, AI helped me understand what the questions were asking, break down the concepts, interpret my results and their implications, and brainstorm and draft some responses. I reviewed the code and explanations, ran the live experiments, and checked and revised the written answers to reflect my understanding.