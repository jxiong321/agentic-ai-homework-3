# ARCHITECTURE.md · RepoMind on the seven layers

For each layer: what does this job, and where is it enforced. Cite code as a file
path and line number joined by a colon, inside backticks; a checker opens every
reference (`checks/FORMATS.md`, section 8). A layer held only by a sentence in a
prompt (any file under `prompts/`) is **EMPTY**, and so is a layer nothing does
yet. Status is one of: present, partial (say what is missing), or **EMPTY**. Each
assignment brings this file up to date.

What each layer is for (Lecture 1, slides 42 to 44):

- **Model**: reasoning, choosing tools, generating text.
- **Harness**: runs the loop, builds each prompt, trims old history.
- **Tools**: where the system acts on the world.
- **Memory & State**: what survives a step, a session, a restart.
- **Control & Policy**: what the system may do, and when it must ask.
- **Observability**: a step-by-step record of what it did.
- **Evaluation**: measuring quality, before and after release.

The table includes Assignment 3 tool validation and write-recovery controls.

| Layer | What does this job | Where it is enforced | Status |
|---|---|---|---|
| Model | The configured model, called only through the metered client | `harness/client.py:120` | present |
| Harness | Bounded loop, validated plans, fixed execution order, prepared draft before either write | `agent/loop.py:32`, `ways/planned.py:91`, `ways/planned.py:318` | present |
| Tools | Five structured tools; argument/result boundary checks, derived write keys, pre-write checks and verified recovery | `tools/__init__.py:276`, `tools/validation.py:22`, `tools/validation.py:60`, `tools/__init__.py:96`, `tools/__init__.py:212` | present |
| Memory & State | A run's progress file, outside the model's context | `ways/notes.py:67` | partial: nothing survives a run |
| Control & Policy | Review before writes, fail-closed hooks, escalation when write outcomes cannot be confirmed | `ways/planned.py:318`, `tools/__init__.py:164`, `tools/__init__.py:187` | partial: operator review required, no approval UI |
| Observability | Model/plan traces, protocol diagnostics, and per-attempt tool records including keys and denied calls | `tools/__init__.py:152`, `tools/__init__.py:145`, `harness/calls.py:47` | partial: records, no alert delivery |
| Evaluation | The grounded check reads the tracker, never the agent | `eval/check_triage.py:7` | partial: offline only |

**Empty layers: 0 of 7**, and four are partial.
