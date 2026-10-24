# Assignment 3 · A tool surface that tells the truth, and writes that happen once

Fill in each section. Every number here must match `reports/LAB_03.json`, and
every count of writes must come from the tracker's database, not from your traces.

## Part A · The five definitions

- Strict tools, optional parameters, nullable or union-typed parameters: **5, 0, 2**. `make audit` passes.
- Provider support and live test: Gemini's [native function-calling documentation](https://ai.google.dev/gemini-api/docs/function-calling) describes a validated mode; its [OpenAI compatibility documentation](https://ai.google.dev/gemini-api/docs/openai) does not clearly document enforcement of the function-level strict flag used by this starter (checked 2026-10-23). We sent all five definitions with `strict: true`; Gemini accepted them together in the live ping at 2026-10-23T19:58:00, hash `8a5ce6be549bcafc`. Thus `compiles: true` follows the assignment's accepted-request definition. Acceptance alone does not establish enforcement; the registry validates every call locally.
- Consolidation, in one line: Keep all five roles separate: reads depend on earlier results, and PR/comment writes need independently verifiable outcomes and a conditional PR skip.

`search_repo`, before and after:

| Before | After |
|---|---|
| Generic `search_repo`, free-text filter, ambiguous “No matches.”, unstructured output. | `codebase_search`, explicit `path_glob`, format enum, malformed-query errors, and structured counts, truncation and index age. |

Starter definitions are preserved at commit `ed6b2e9cba6a548af2c144a767dd7cc6f704866d`. Tasks 1 and 2 are implemented: each definition has a typical example followed by a harder conditional example; the registry appends both to the vendor-facing description without sending a separate examples field. Strict flags, registry-wide boundary validation, and live development verification are now implemented as well.

### Task 4: schema compatibility

All five schemas meet the assignment's structural limits. Every property is required and every object has `additionalProperties: false`. The only unions are search's `max_results` (integer or null) and `path_glob` (string or null): both keys must be present, with null selecting the default limit or no path restriction. No field needs competing object shapes or a kind discriminator.

The definitions contain 14 properties in total (1, 5, 2, 2, 4 in registry order), at most 5 in any tool, and one object level. Thus they fit the course's 100-property and 5-level limits, with 0 optional parameters and 2 of the allowed 16 union parameters. All five could be enabled within the 20-strict-tool limit.

Length, pattern, and range validation keywords are absent from the schemas; content constraints remain described in the interfaces and belong in code. The registry-wide boundary checks are implemented in `tools/validation.py` and called by `tools/__init__.py`. Offline checks confirmed that the examples fit, while omitted required keys, extra arguments, and invalid enum values fail schema checking. The full audit now passes with all five explicit strict flags enabled. The live ping confirms request acceptance; it does not independently prove provider-side enforcement.

### Boundary validation and development verification

Before dispatch, the registry checks required fields, types (including rejecting booleans as integers), extra arguments and enum choices. Enum strings are matched case-insensitively and normalized without changing query, path or body casing. It checks positive issue numbers, search length and glob syntax, result limits, safe paths, nonblank bounded write text, and the required PR branch. Invalid arguments return a capped execution error naming the field and a repair, before tool execution.

Each definition declares an `output_schema` kept local rather than sent to the vendor. After execution the registry parses the JSON result and checks its declared shape, caps, semantic identifiers and applicable consistency rules (query echo, result counts, truncation, requested issue/branch/path). Broken results become errors rather than passing through as successful data. This checks the result contract, not whether a triage conclusion is correct. An output error after a write cannot undo that write; Part C now supplies safe recovery.

The file reader additionally checks exact path casing against a file list, with near-match feedback. This brings forward Part B's required case-sensitive behavior so result paths remain truthful on macOS.

Validation: 66 tests ran, 64 passed and 2 starter-only tests skipped. Six focused boundary tests include mocked dispatch to prove bad write arguments never execute and mocked malformed results to prove they are blocked. Both scripted development runs completed. Both real Gemini development runs, `planned-4191-s01-9fd590` and `planned-4192-s01-950a7e`, ended `completed`, with 11 tool calls total, zero tool errors, and only renamed tools. These are development checks, not Part D measurements. Part C now enforces the PR ordering and skip safeguards.

## Part B · Errors

| Tool | Transient | Permanent | Ambiguous |
|---|---|---|---|
| tracker_read_issue | Temporary tracker read unavailability, if encountered (not simulated in current issue reads). | Invalid issue number or issue not found; correct the number or fix the underlying issue data. | None: this read creates no write whose outcome needs confirmation. |
| codebase_search | Temporary storage read failure, if identified as temporary (not simulated in current search). | Blank or oversized query, malformed path glob, invalid result limit or response format. Missing or corrupt search index requires repair; repeating the unchanged call does not fix it. | None: this read creates no write whose outcome needs confirmation. |
| codebase_read_file | Temporary storage read failure, if identified as temporary (not simulated in current file reads). | Missing file, wrong path capitalization, excluded or outside-repository path, non-text file, or invalid response format. | None: this read creates no write whose outcome needs confirmation. |
| tracker_post_comment | Transport failure known to occur before dispatch, if encountered; no write could have occurred. | Invalid or missing issue; blank or oversized comment body; invalid arguments. | Timeout after dispatch: the comment may already have committed. Every simulated TrackerTimeout is treated as ambiguous, including one secretly raised before commit. |
| pulls_open_draft | Transport failure known to occur before dispatch, if encountered; no write could have occurred. | Invalid or missing issue; incorrect branch; blank or oversized title/body; invalid arguments. | Timeout after dispatch: the PR may already have committed. Every simulated TrackerTimeout is treated as ambiguous, including one secretly raised before commit. |

A permanent failure means the same call will keep failing under the current conditions. It does not mean the problem cannot be fixed: a nonexistent file path can be corrected. A transient failure may succeed unchanged after a temporary condition clears, so bounded retries belong in code. The transient cases above are classifications, not claims of live failures observed. Their retry handling is now implemented and tested with injected failures.

A write timeout is ambiguous because the reply may have been lost after the tracker committed. Immediately retrying could post the comment twice. The tracker deliberately gives the same timeout for before-commit and after-commit failures, so our harness must classify by what it can know, not by the hidden fault. It must verify: if the write happened, continue with the existing result; if it did not, retry with the same key; if verification fails, escalate. Read-only timeouts can leave us without data, but create no duplicate-write uncertainty.


- Protocol errors: **`end_run`**. Unknown/malformed tool names and non-object argument payloads are logged with their full request details in `runs/<run_id>.harness.log`; the registry raises `ProtocolError`. The agent loop and planned executor end with `tool_error` and make no subsequent model request, so no protocol details are sent back to the model. Retrying argument variations cannot repair an unavailable tool. Invalid arguments to a known tool remain execution errors with `is_error: true` and repair feedback. A known but off-plan tool remains an execution-boundary violation under Assignment 2's policy, not an unknown-tool protocol error.
- The exact text of your `read_file` near-miss error for `src/report.ts`:

```text
Error: Invalid path: use an exact case-sensitive repository path. Near matches: src/reports.ts, src/report.tsx, src/Report.ts. Requested: 'src/report.ts'. Correct the path before retrying.
```

### Tasks 3–5: repair feedback, retry allocation and direct checks

Execution errors put the repair instruction first and are capped at 1000 characters. Missing issues tell the caller to correct the issue number; path errors name accessible alternatives where available; non-text and excluded files explain which kind of file to choose. Internal implementation/data failures tell the operator to repair the implementation or stored data instead of exposing a raw exception as if the model could fix it. Full internal details remain in the harness log. The file reader compares against actual repository path spellings, so a case-insensitive filesystem cannot silently substitute a near match.

The registry retries temporary reads (timeouts, connection failures and selected temporary OS error codes) and explicitly certified pre-dispatch write failures. The bound is three total attempts, with ordinary waits of 0.1 and 0.2 seconds. The adapter can provide a retry-after delay; delays over 2 seconds are returned to the caller rather than shortened or slept through. On exhaustion, feedback says a later retry may work and gives the delay and attempt count. Retries occur below the model and reuse a copy of the original validated arguments. Semantic and permanent I/O failures are not retried. Part C now intercepts write failures, verifies the outcome and retries only after confirming absence (except under the deliberate control switch). Unavailable verification and exhaustion end the run escalated, without asking the model to guess.

`eval/check_part_b_errors.py` directly tests an unknown tool, malformed arguments and the near-miss file path without any model request. It saves the protocol diagnostic in `runs/part-b-errors.harness.log`. All three checks pass. Eight focused Part B tests cover read recovery, retry exhaustion, long retry-after delays, confirmed pre-dispatch writes, uncertain writes that must not retry, permanent failures, protocol logging, and the direct argument/path checks. The complete suite ran 74 tests: 72 passed and 2 starter-only tests skipped. The course error-contract check also scores 10/10; its unknown-tool simulation makes exactly one model request and ends `tool_error`.

## Part C · Writes that may already have happened

- The key formula: `SHA256(UTF8(JSON([run_id, plan_step, validated_arguments], sort_keys=True, separators=(",", ":"), ensure_ascii=False)))`. The compact JSON array separates the three components unambiguously, recursively sorts object keys and adds no formatting whitespace; whitespace inside text is preserved. The registry freezes a copy of validated arguments, computes the key once per call and supplies it privately to `post_comment` and `open_pr` as `idempotency_key`. Neither tool's model-facing schema contains the key. Each internal retry uses the same key and a fresh copy of the original arguments. Non-planned callers use null for the step ID. A different run, step or argument value denotes a different action and produces a different key.
- How a run whose file is `none` skips the PR: an executor check. The validated plan always has exactly one PR step immediately before exactly one final comment step. Before executing the PR, the executor drafts the comment and applies the configured second pass (off, self or external). A held draft ends the run before either write. The final draft is cached; if its file is `none`, the executor records `pr_skipped` and marks that plan step complete without calling the PR tool. Otherwise it opens the PR with a body naming that file. A failed PR prevents posting. The final comment step posts the cached draft unchanged, without another drafting call.

Step 1 verification: five focused tests cover normal ordering and the saved draft, the scripted `DraftNamesNoFile` skip, a held review with zero writes, PR execution failure withholding the comment, and rejection of missing/duplicate/misordered write steps. The complete suite ran 79 tests (77 passed, 2 starter-only skips); no live model calls were needed. Tasks 2–6 are now implemented: idempotency keys, pre-write checks, timeout verification, audit records, hooks and control switches.
### Checks, verification, records and controls

Before every write attempt, including retries, the registry reads this run's existing open PR by branch or its comment by the current attempt's key. A match returns the stored receipt without a new write. Every failed write is checked again when VERIFY is on: an existing effect returns success; confirmed absence allows a temporary failure to retry with the same arguments and derived key; unavailable readback raises `WriteUnconfirmed`, which ends the planned run `escalated`. A third unconfirmed attempt also escalates. A failed PR never proceeds to the comment.

The registry runs pre-call hooks before every attempt. A non-None return denies the call; an exception also denies it (fail closed). Arguments passed to hooks are copies, so hooks cannot silently change the intended write. The default hook allows calls. `ctx.calls.write(...)` records reads and writes, each retry, rejected/denied calls, protocol errors and resolved timeouts with tool, arguments, step, key, outcome, result summary, latency and zero local-tool cost. A recovered timeout has a timeout line and an ok line for the same attempt.

KEY_MODE=uuid generates a fresh key for each attempt. VERIFY=off skips post-failure verification but retains pre-attempt existence checks and the three-attempt bound. This intentionally allows duplicate comments under the control while the PR's branch still protects it.

Deterministic verification: scenario A (PR fails before commit, retry succeeds; comment commits then times out) completed with one PR and one comment. Scenario B (PR commits then times out, readback fails) escalated with one PR and no comment. Scenario C (both writes lose replies under the control switches) completed with one PR and two comments. Every stored write in these scenarios matched a call-record key. Tests also cover attempt exhaustion, hooks on retries, hook exceptions, existence checks, and logging of reads/rejections/protocol errors. All 91 tests ran successfully (89 passed, 2 starter-only skips). The course checker scored 7/7 for the three exits and passed both hook checks. Remaining automated points depend on Part D's measurements.

Saved scripted development evidence (`eval/summarize_part_c_dev.py`, `reports/PART_C_DEV_CHECKS.json`): six flaky runs all completed with one comment and one PR per run, no duplicates, and seven committed timeouts. Six readback-failure runs produced five escalations and one completion, three committed timeouts, no duplicates, and no comments after uncertain PR writes. Every stored write matched an ok/timeout call-record key. These use a scripted backend and do not substitute for Part D's real-model measurements.

The first live Gemini development batch finished without crashes but exposed pre-write plan errors: over-escaped args_json strings silently decoded to empty arguments, and embedded $fill text was not resolved. The plan checker now rejects invalid/non-object args_json, missing or extra tool arguments, wrong fixed types, and embedded placeholders before execution. Prompts clarify single encoding and whole-value placeholders; an off-plan retry receives feedback identifying the allowed tool. These are development findings, not hidden successes. The updated suite ran 91 tests (89 passed, 2 starter-only skips). Live verification was repeated as sweeps 4–6, preserving the original runs. With FLAKY_WRITES=1, five of six runs completed with exactly one PR and one comment; seven committed timeouts were recovered without duplicates. Run planned-4191-s04-ce9624 escalated before any writes after three invalid plans containing incomplete args_json. This remains a planner reliability limitation, so this batch is not a six-of-six completion pass. With FLAKY_WRITES=1 READBACK_FAIL=1, four runs escalated safely and two completed. Three escalations followed uncertain PR writes and produced no comment; the fourth followed an uncertain comment write. There were four committed timeouts and no duplicate writes. Every stored write in both batches matched an ok/timeout call-record key. The terminal summary of zero errors means no harness errors, not that every run completed. No Part D evaluation runs have been made.

- One actual call-record line for a write from the scripted development tests:

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
### Measured tool surface

Provider prompt-token differences (cached input included); baseline is the same one-message request without tools. Single-tool counts each include the provider's tool preamble.

| Surface | Starter tokens | Rewritten tokens |
|---|---:|---:|
| read_issue alone | 51 | 243 |
| search_repo alone | 114 | 644 |
| read_file alone | 48 | 321 |
| post_comment alone | 70 | 337 |
| open_pr alone | 103 | 511 |
| All five together | 386 | 2056 |
| Planner/reviser text list | 117 | 1337 |

Mean calls per harness run: 5.6667. For each version, cost = sum over harness calls of (single-tool token difference, or all-five difference if all five were offered, plus the list difference on plan/revise calls) × that call's model input rate / 1,000,000 / 12. submit_plan is excluded. The counterfactual charges all five on every call, including planner/reviser calls, with no extra list.

Mean surface cost: starter $0.00016777; rewritten $0.00138655; all-five counterfactual $0.00349520. At the recorded model's rate, the implied mean surface tokens are each cost × 1,000,000 / its input rate. Raw counts and call usage are saved in SURFACE_COUNTS_03.json and SURFACE_CALLS_03.jsonl.

Input rate: $0.3000 per million tokens. Mean surface tokens: starter 559.25, rewritten 4621.83, all-five 11650.67. Offering only the needed tool saves $0.00210865 per mean run against the all-five counterfactual.

The added descriptions buy explicit argument choices, result caps and empty-result meaning, plus two examples. This is a surface-only price, not the total task bill. Caching can discount dollars without reducing context occupancy.

### Tracker results

| Measure | Your harness | Control |
|---|---|---|
| Comments per run | 0: 1 runs, 1: 11 runs | 0: 3 runs, 1: 5 runs, 2: 1 runs, 3: 3 runs |
| PRs per run | 0: 3 runs, 1: 9 runs | 0: 4 runs, 1: 8 runs |
| Runs with correct PR count/branch | 12 | 11 |
| Committed timeouts | 5 | 13 |
| Escalated runs | 1 | 6 |
| Grounded triage passes | 4 | 2 |

Counts come from SQLite, grouped by run_id; terminal outcomes come from traces. Grounded success requires exactly one comment and a label/file matching the reference answer, so duplicate comments fail even if their text is correct. PART_D_DETAILS.json lists every run and verifies write keys and committed timeouts against the call records.

### Prediction comparison

- harness: predicted 0 extra comments in 0 duplicate-comment runs and 0 extra PRs; measured 0, 0, and 0, respectively.
- control: predicted 6 extra comments in 5 duplicate-comment runs and 0 extra PRs; measured 7, 4, and 0, respectively.
  The exact duplicate estimate missed: duplicates depend on which comment writes reached a committed timeout and how many attempts ran. Planning/triage stops can also prevent a write from reaching the fault gate. The per-run tracker counts above preserve those outcomes.
- Predicted search would be most misused. Observed rejected/execution-error attempts by role: {'read_file': 2}. This proxy cannot detect a valid but inappropriate query; with no such errors or tied counts, the prediction is not established.

### Four shapes of misuse

1. Right tool, wrong arguments: the boundary and schema checks narrow this. Measured rejected/execution-error attempts: 2. Evidence references: planned-4202-s02-f199a9, planned-4204-s02-91609b. Errors may also be transport/storage failures; inspect their saved repair messages before classifying each as model misuse.
2. Wrong tool, valid call: one-tool fill requests and the executor's allowed-tool check narrow selection. Measured off-plan events: 0; references: none observed. Both experimental arms share this surface, so this is not a causal before/after comparison.
3. Correct call, misread result: structured counts, query_valid and truncation narrow ambiguity, but cannot ensure understanding. Observed valid empty searches: 2. Harness grounded passes: 4/12. A wrong final answer alone does not prove a result was misread; trace review is needed to distinguish it from a poor query or insufficient evidence.
4. No call at all remains possible: descriptions cannot force the model to seek missing evidence. Runs missing a successful issue read or search: 3; references: planned-4203-s01-2b9b73, planned-4204-s03-79f971, planned-4204-s04-c517bd. These are audit candidates, not automatic proof of voluntary omission: rejected plans can stop before dispatch. Even when basic reads are present, an omitted necessary additional read requires tasks with known answers and expected evidence to detect. The assignment cites a 36% MCP-Atlas benchmark figure; this small experiment cannot validate that external percentage.

<!-- PART_D_MEASUREMENTS_END -->

## Transparent follow-up experiment

The original 24-run batch is retained in `reports/batches/original/`; its full code, run files and tracker database are preserved in Git commit `e6cce1c74a9430b5d0feefe804ed8ac694e21845`. Its automated score was 81.33/82, not a full pass. The harness left 11 single comments and one run with no writes; the latter rejected three invalid plans, with missing step IDs in the final attempt. There were no duplicate harness writes. Control runs produced seven extra comments across four runs, rather than the predicted six across five. No duplicate PRs occurred in either arm.

After inspecting these results, we changed only general planner format guidance and repair context: each request now shows the complete required step fields and correctly serialized examples; a retry receives the previous rejected plan alongside its validation errors. The validator still rejects malformed plans, the retry bound is unchanged, and no missing fields are silently supplied by the harness. No evaluation answers were added to prompts or execution code. Both arms of the follow-up will use the same revised code. This is a post-evaluation improvement, not an independent preregistered replication; instructor acceptance of the follow-up as graded evidence is not assumed.

Offline regression verification: 95 tests ran, 93 passed and 2 starter-only tests skipped. New scripted development tests inject missing IDs, missing tool names and incomplete args_json, verify that retries receive the rejected plan and repair facts before any tool dispatch, and verify that three invalid plans still escalate with no writes. Live development verification and follow-up measurements are pending. The first-batch reports and predictions remain unchanged in the snapshot. The original predictions were pushed before the original evaluation; they are not being rewritten to match observed outcomes.

## AI assistance

Which tool, what it wrote, and what you checked:

OpenAI Codex implemented the Part A tool definitions and examples, registry boundary validation, output contracts, prompt updates and focused tests, and drafted the Part A report. I ran the live ping and development commands; Codex inspected their saved records and ran the offline audit and tests. We discussed transient, permanent and ambiguous failures and selected the end-run protocol policy together. Codex implemented Part B error routing, repair messages, bounded safe retries and token-free checks, and recorded the results. Codex implemented Part C ordering, idempotency, verification, escalation, audit records, hooks and control switches and ran deterministic fault tests. Codex also implemented Part D token-difference pricing and database-based counting, drafted pre-evaluation predictions, and generated the measured report. I ran the live experiments; final interpretation is reviewed together.
